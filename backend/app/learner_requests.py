"""Learner self-service that needs the instructor's word: start over,
request completion marks, request the answer key.

Three buttons on every course dashboard, for every learner, every course:

  start over          — the learner's own action, applied at once: watch
                        progress, quiz attempts and quiz-app state for the
                        course are cleared so it can be repeated from the
                        first lesson. An earned Certificate of Completion is
                        kept (the owner's call, 2026-09-14): it was earned.
  request completion  — a site problem lost their answers; they ask the
                        instructor to mark every requirement complete so
                        the certificate can issue. Applied only when an
                        admin approves.
  request answer key  — a PDF of every module's evaluation and mastery
                        check with answers and explanations, emailed on
                        approval. Who may ask (owner's rule): a learner who
                        registered for a live cohort of the course may ask
                        at any time; a self-study purchaser only once their
                        Certificate of Completion is issued.

Requests email the owner with a link to the admin panel; the effect is
applied by Approve there, never by a link in the email.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import academy as svc
from . import certificates as certs
from .config import get_settings
from .emailer import (
    answer_key_html,
    learner_request_admin_html,
    request_approved_awaiting_name_html,
    request_declined_html,
    send_email,
)
from .models import (
    Certificate,
    Course,
    Enrollment,
    LearnerRequest,
    Learner,
    Lesson,
    LessonProgress,
    Module,
    ModuleState,
    Product,
    QuizAttempt,
    QuizItem,
    Registration,
)
from .progress_guard import allow_progress_loss

log = logging.getLogger(__name__)

KINDS = ("completion", "answers")
KIND_LABELS = {
    "completion": "completion marks",
    "answers": "the answer key",
}
SET_LABELS = {"formative": "Module evaluation", "summative": "Mastery check"}


class RequestRefused(ValueError):
    """A learner request that the rules do not allow right now; the message
    is shown to the learner as-is."""


# -----------------------------------------------------------------------------
# Who is this learner to the course?
# -----------------------------------------------------------------------------

def _product_modules(db: Session, product_code: str) -> list[Module]:
    return db.execute(
        select(Module).where(Module.product_code == product_code).order_by(Module.position)
    ).scalars().all()


def cohort_attendee(db: Session, learner: Learner, product: Product) -> dict | None:
    """The live-cohort registration behind this learner's access, if any.

    A cohort registrant is someone who registered for a live delivery of the
    course (a `courses` row whose recorded product is this one) and either
    paid or confirmed attendance — or whose enrollment was granted by
    marking such a registration paid. Self-study buyers have neither.
    """
    email = (learner.email or "").strip().lower()
    if email:
        rows = db.execute(
            select(Registration, Course)
            .join(Course, Course.code == Registration.course_code)
            .where(
                func.lower(Registration.email) == email,
                Course.recorded_product_code == product.code,
                Registration.status != "cancelled",
            )
            .order_by(Registration.created_at.desc())
        ).all()
        for reg, course in rows:
            if reg.status == "paid" or reg.attendance_confirmed_at is not None:
                return {
                    "course_code": course.code,
                    "course_title": course.title,
                    "registration_status": reg.status,
                    "attendance_confirmed": reg.attendance_confirmed_at is not None,
                }
    enrollment = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id,
            Enrollment.product_code == product.code,
            Enrollment.source == "cohort",
        )
    ).scalar_one_or_none()
    if enrollment is not None:
        return {
            "course_code": "",
            "course_title": "",
            "registration_status": "paid",
            "attendance_confirmed": False,
            "note": enrollment.note,
        }
    return None


def completion_certificate(db: Session, learner: Learner, product: Product) -> Certificate | None:
    cert = certs.get_certificate(db, learner, product.code, "completion")
    return cert if cert is not None and cert.status == "issued" else None


def answers_allowed(db: Session, learner: Learner, product: Product) -> tuple[bool, str]:
    """The owner's rule for the answer key (see the module docstring)."""
    if cohort_attendee(db, learner, product) is not None:
        return True, ""
    if completion_certificate(db, learner, product) is not None:
        return True, ""
    return (
        False,
        "The answer key can be requested once your Certificate of Completion has "
        "been issued. If you attended this course live, reply to your course email "
        "and we will open it for you.",
    )


def open_requests(db: Session, learner: Learner, product: Product) -> dict[str, LearnerRequest]:
    rows = db.execute(
        select(LearnerRequest).where(
            LearnerRequest.learner_id == learner.id,
            LearnerRequest.product_code == product.code,
            LearnerRequest.status == "pending",
        )
    ).scalars().all()
    return {r.kind: r for r in rows}


def support_state(db: Session, learner: Learner, product: Product) -> dict:
    """What the course dashboard needs to draw the three buttons."""
    allowed, reason = answers_allowed(db, learner, product)
    pending = open_requests(db, learner, product)
    held = completion_certificate(db, learner, product) is not None
    return {
        "reset_available": True,
        "completion_request_available": not held,
        "answers_request_available": allowed,
        "answers_blocked_reason": "" if allowed else reason,
        "pending": {k: {"id": r.id, "created_at": r.created_at} for k, r in pending.items()},
    }


def progress_summary(db: Session, learner: Learner, product: Product) -> dict:
    s = certs.completion_status(db, learner, product.code)
    return {
        "lessons_done": s["lessons_done"],
        "lessons_total": s["lessons_total"],
        "sets_passed": s["sets_passed"],
        "sets_total": s["sets_total"],
        "complete": s["complete"],
    }


# -----------------------------------------------------------------------------
# Start over
# -----------------------------------------------------------------------------

def reset_progress(db: Session, learner: Learner, product: Product) -> dict:
    """Clear the learner's own history for this course so it can be
    repeated. Certificates, entitlements, orders and the examined-tier
    journey are untouched; the product-level 'advanced' attempts live under
    module_id 0 and are therefore not in the module list below."""
    modules = _product_modules(db, product.code)
    module_ids = [m.id for m in modules]
    lesson_ids = list(db.execute(
        select(Lesson.id).where(Lesson.module_id.in_(module_ids))
    ).scalars().all()) if module_ids else []
    app_ids = [m.code.lower() for m in modules]

    with allow_progress_loss(
        f"learner {learner.id} chose to start {product.code} over"
    ):
        lessons_cleared = 0
        if lesson_ids:
            lessons_cleared = db.execute(
                delete(LessonProgress).where(
                    LessonProgress.learner_id == learner.id,
                    LessonProgress.lesson_id.in_(lesson_ids),
                )
            ).rowcount
        attempts_cleared = 0
        if module_ids:
            attempts_cleared = db.execute(
                delete(QuizAttempt).where(
                    QuizAttempt.learner_id == learner.id,
                    QuizAttempt.module_id.in_(module_ids),
                )
            ).rowcount
        app_state_cleared = 0
        if app_ids:
            app_state_cleared = db.execute(
                delete(ModuleState).where(
                    ModuleState.learner_id == learner.id,
                    ModuleState.module_id.in_(app_ids),
                )
            ).rowcount
        db.commit()
    log.info(
        "Learner %s reset %s: %d lesson rows, %d attempts, %d app-state rows",
        learner.email, product.code, lessons_cleared, attempts_cleared, app_state_cleared,
    )
    return {
        "lessons_cleared": lessons_cleared,
        "attempts_cleared": attempts_cleared,
        "app_state_cleared": app_state_cleared,
    }


# -----------------------------------------------------------------------------
# Requests
# -----------------------------------------------------------------------------

def _review_url() -> str:
    return f"{get_settings().SITE_URL}/admin#academy"


def create_request(
    db: Session, learner: Learner, product: Product, kind: str, note: str
) -> LearnerRequest:
    if kind not in KINDS:
        raise RequestRefused("Unknown request.")
    if kind == "completion" and completion_certificate(db, learner, product) is not None:
        raise RequestRefused("You already hold the Certificate of Completion for this course.")
    if kind == "answers":
        ok, reason = answers_allowed(db, learner, product)
        if not ok:
            raise RequestRefused(reason)
    if kind in open_requests(db, learner, product):
        raise RequestRefused(
            f"Your request for {KIND_LABELS[kind]} is already with the instructor."
        )
    row = LearnerRequest(
        learner_id=learner.id,
        product_code=product.code,
        kind=kind,
        note=" ".join((note or "").split())[:1000],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log.info("Learner request #%s: %s asks for %s on %s", row.id, learner.email, kind, product.code)

    settings = get_settings()
    try:
        send_email(
            to=settings.ADMIN_NOTIFY_EMAIL,
            subject=f"[Learner request] {learner.full_name or learner.email} asks for "
                    f"{KIND_LABELS[kind]} — {product.title}",
            html=learner_request_admin_html(
                kind=kind,
                learner_name=learner.full_name or "",
                learner_email=learner.email,
                course_title=product.title,
                note=row.note,
                progress=progress_summary(db, learner, product),
                cohort=cohort_attendee(db, learner, product),
                review_url=_review_url(),
                request_id=row.id,
            ),
            db=db,
            scope_kind="product",
            scope_code=product.code,
            audience="admin",
            template=f"learner_request_{kind}",
        )
    except Exception as exc:  # pragma: no cover — the request stands regardless
        log.error("Learner request #%s: admin email failed: %s", row.id, exc)
    return row


def grant_completion(
    db: Session, learner: Learner, product: Product, request: LearnerRequest
) -> Certificate | None:
    """Mark every requirement complete, as the instructor's act.

    Written as real progress rows rather than a flag so every view — module
    cards, gating, the certificate rule — agrees. A granted quiz attempt
    carries no responses and no auto-graded items (the platform's own
    "nothing to grade → 100, passed" convention) plus a marker naming the
    request, so it is never mistaken for a sat quiz.
    """
    now = datetime.now(timezone.utc)
    modules = _product_modules(db, product.code)
    module_ids = [m.id for m in modules]
    lessons = db.execute(
        select(Lesson).where(Lesson.module_id.in_(module_ids))
    ).scalars().all() if module_ids else []
    totals = svc.slide_totals(db, module_ids)
    prog = svc.progress_map(db, learner, [l.id for l in lessons])

    for lesson in lessons:
        row = prog.get(lesson.id)
        if row is None:
            row = LessonProgress(
                learner_id=learner.id, lesson_id=lesson.id, position_s=0, watched_s=0
            )
            db.add(row)
        if lesson.kind == "slides" and totals.get(lesson.module_id):
            row.position_s = max(row.position_s or 0, totals[lesson.module_id])
        if lesson.duration_s:
            row.watched_s = lesson.duration_s
            row.position_s = max(row.position_s or 0, lesson.duration_s)
        else:
            row.watched_s = max(row.watched_s or 0, 1)
        if row.completed_at is None:
            row.completed_at = now

    marker = {
        "_granted": {
            "by": "instructor",
            "request_id": request.id,
            "at": now.isoformat(),
        }
    }
    for module in modules:
        for item_set in ("formative", "summative"):
            if not svc.module_has_items(db, module.id, item_set):
                continue
            best = svc.best_attempt(db, learner, module.id, item_set)
            if best is not None and best.passed:
                continue
            db.add(
                QuizAttempt(
                    learner_id=learner.id,
                    module_id=module.id,
                    item_set=item_set,
                    score_pct=100.0,
                    passed=True,
                    auto_total=0,
                    auto_correct=0,
                    responses=marker,
                )
            )
    db.commit()
    return certs.maybe_issue_completion(db, learner, product.code)


# -----------------------------------------------------------------------------
# Answer key PDF
# -----------------------------------------------------------------------------

def _para(text: str, style) -> "Paragraph":  # noqa: F821 — reportlab imported lazily
    from reportlab.platypus import Paragraph

    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def answer_key_pdf(db: Session, learner: Learner, product: Product) -> bytes:
    """Every module's formative and summative items with the answer key,
    rubric and explanation — the paid written examination is never included."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    from .certificate_render import _register_fonts

    # The certificate's TTFs: the base-14 Helvetica has no glyphs for the
    # Greek letters, dotted m, subscripts and arrows engineering stems use.
    _register_fonts()
    settings = get_settings()
    styles = getSampleStyleSheet()
    h_course = ParagraphStyle("course", parent=styles["Title"], fontName="Inter-Bold", fontSize=18,
                              leading=22, textColor=colors.HexColor("#0f172a"), alignment=TA_LEFT)
    h_module = ParagraphStyle("module", parent=styles["Heading2"], fontName="Inter-Bold", fontSize=13.5,
                              leading=17, textColor=colors.HexColor("#0f172a"), spaceBefore=14, spaceAfter=4)
    h_set = ParagraphStyle("set", parent=styles["Heading3"], fontName="Inter-Semi", fontSize=11,
                           leading=14, textColor=colors.HexColor("#0e7490"), spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Inter", fontSize=9.6,
                          leading=13, textColor=colors.HexColor("#1e293b"))
    stem = ParagraphStyle("stem", parent=body, fontName="Inter-Semi", spaceBefore=6)
    option = ParagraphStyle("option", parent=body, leftIndent=14)
    answer = ParagraphStyle("answer", parent=body, leftIndent=14, fontName="Inter-Semi",
                            textColor=colors.HexColor("#0e7490"), spaceBefore=2)
    expl = ParagraphStyle("expl", parent=body, leftIndent=14, textColor=colors.HexColor("#475569"),
                          spaceAfter=4)
    meta = ParagraphStyle("meta", parent=body, textColor=colors.HexColor("#64748b"))

    holder = f"{learner.full_name or ''} <{learner.email}>".strip()
    footer_text = (
        f"Prepared for {holder} · personal study copy, not for distribution · "
        f"ProReadyEngineer LLC"
    )

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Inter", 7.2)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(0.75 * inch, 0.5 * inch, footer_text)
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    story = [
        Paragraph(escape(f"Answer key — {product.title}"), h_course),
        Spacer(1, 4),
        _para(
            f"Every module evaluation and mastery check of the course, with the answer to "
            f"each item and the explanation where one is recorded. Prepared for {holder} "
            f"on {datetime.now(timezone.utc).date().isoformat()} at the instructor's approval. "
            f"Mastery threshold {settings.MASTERY_THRESHOLD_PCT:g}%.",
            meta,
        ),
        Spacer(1, 8),
    ]

    modules = _product_modules(db, product.code)
    any_items = False
    for module in modules:
        items = db.execute(
            select(QuizItem)
            .where(QuizItem.module_id == module.id, QuizItem.item_set.in_(("formative", "summative")))
            .order_by(QuizItem.item_set, QuizItem.position, QuizItem.id)
        ).scalars().all()
        if not items:
            continue
        any_items = True
        story.append(_para(module.title, h_module))
        for item_set in ("formative", "summative"):
            set_items = [i for i in items if i.item_set == item_set]
            if not set_items:
                continue
            story.append(_para(f"{SET_LABELS[item_set]} · {len(set_items)} items", h_set))
            for n, item in enumerate(set_items, start=1):
                block = [_para(f"{n}. {item.stem}", stem)]
                options = item.options or []
                for opt in options:
                    if isinstance(opt, dict):
                        block.append(_para(f"{opt.get('key', '')}. {opt.get('text', '')}", option))
                    else:
                        block.append(_para(str(opt), option))
                block.append(_para(_answer_line(item), answer))
                if item.kind == "short" and item.rubric:
                    block.append(_para(f"Marking guide: {item.rubric}", expl))
                if item.explanation:
                    block.append(_para(f"Why: {item.explanation}", expl))
                story.append(KeepTogether(block))
        story.append(Spacer(1, 6))

    if not any_items:
        story.append(_para("This course has no evaluations or mastery checks loaded.", body))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.8 * inch,
        title=f"Answer key — {product.title}", author="ProReadyEngineer LLC",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _answer_line(item: QuizItem) -> str:
    ans = item.answer if isinstance(item.answer, dict) else {}
    if item.kind == "mcq":
        key = str(ans.get("key", "")).strip()
        text = ""
        for opt in item.options or []:
            if isinstance(opt, dict) and str(opt.get("key", "")).strip().upper() == key.upper():
                text = str(opt.get("text", ""))
                break
        return f"Answer: {key}" + (f" — {text}" if text else "")
    if item.kind == "numeric":
        value = ans.get("value")
        tol = ans.get("tolerance")
        unit = ans.get("unit") or ""
        parts = [f"Answer: {value}"]
        if tol not in (None, ""):
            parts.append(f"± {tol}")
        if unit:
            parts.append(str(unit))
        return " ".join(parts)
    if item.kind == "match":
        pairs = ans.get("pairs") or []
        return "Answer: " + "; ".join(f"{a} → {b}" for a, b in pairs)
    return "Answer: see the marking guide below" if item.rubric else "Answer: open response"


# -----------------------------------------------------------------------------
# Decisions
# -----------------------------------------------------------------------------

def _learner_and_product(db: Session, req: LearnerRequest) -> tuple[Learner, Product]:
    learner = db.get(Learner, req.learner_id)
    product = db.get(Product, req.product_code)
    if learner is None or product is None:
        raise RequestRefused("The learner or the course behind this request no longer exists.")
    return learner, product


def approve(db: Session, req: LearnerRequest, admin_email: str, note: str = "") -> LearnerRequest:
    if req.status != "pending":
        raise RequestRefused(f"This request was already {req.status}.")
    learner, product = _learner_and_product(db, req)
    settings = get_settings()

    if req.kind == "completion":
        cert = grant_completion(db, learner, product, req)
        if cert is not None:
            # The certificate email (the instructor's congratulations) is the
            # learner's notice; nothing else to say.
            req.result = cert.code
        else:
            req.result = "awaiting_name"
            send_email(
                to=learner.email,
                subject=f"Your requirements are marked complete — {product.title}",
                html=request_approved_awaiting_name_html(
                    learner.full_name or "", product.title,
                    f"{settings.SITE_URL}/learn/{product.code}",
                ),
                db=db, scope_kind="product", scope_code=product.code,
                template="learner_request_completion_approved",
            )
    elif req.kind == "answers":
        pdf = answer_key_pdf(db, learner, product)
        ok = send_email(
            to=learner.email,
            subject=f"Answer key — {product.title}",
            html=answer_key_html(learner.full_name or "", product.title),
            db=db, scope_kind="product", scope_code=product.code,
            template="learner_request_answers_approved",
            attachments=[{
                "filename": f"ProReadyEngineer_Answer_Key_{product.code}.pdf",
                "content": __import__("base64").b64encode(pdf).decode(),
            }],
        )
        req.result = "answer_key_sent" if ok else "answer_key_email_failed"
    else:  # pragma: no cover — KINDS is checked at creation
        raise RequestRefused("Unknown request kind.")

    req.status = "approved"
    req.decision_note = " ".join((note or "").split())[:1000]
    req.decided_by = admin_email
    req.decided_at = datetime.now(timezone.utc)
    db.commit()
    log.info("Learner request #%s approved by %s: %s", req.id, admin_email, req.result)
    return req


def decline(db: Session, req: LearnerRequest, admin_email: str, note: str = "") -> LearnerRequest:
    if req.status != "pending":
        raise RequestRefused(f"This request was already {req.status}.")
    learner, product = _learner_and_product(db, req)
    req.status = "declined"
    req.decision_note = " ".join((note or "").split())[:1000]
    req.decided_by = admin_email
    req.decided_at = datetime.now(timezone.utc)
    req.result = "declined"
    db.commit()
    send_email(
        to=learner.email,
        subject=f"About your request for {KIND_LABELS[req.kind]} — {product.title}",
        html=request_declined_html(
            learner.full_name or "", product.title, KIND_LABELS[req.kind], req.decision_note,
        ),
        db=db, scope_kind="product", scope_code=product.code,
        template=f"learner_request_{req.kind}_declined",
    )
    log.info("Learner request #%s declined by %s", req.id, admin_email)
    return req


# -----------------------------------------------------------------------------
# Admin shape
# -----------------------------------------------------------------------------

def admin_out(db: Session, req: LearnerRequest) -> dict:
    learner = db.get(Learner, req.learner_id)
    product = db.get(Product, req.product_code)
    out = {
        "id": req.id,
        "kind": req.kind,
        "kind_label": KIND_LABELS.get(req.kind, req.kind),
        "status": req.status,
        "note": req.note,
        "decision_note": req.decision_note,
        "decided_by": req.decided_by,
        "decided_at": req.decided_at,
        "result": req.result,
        "created_at": req.created_at,
        "product_code": req.product_code,
        "product_title": product.title if product else req.product_code,
        "learner_id": req.learner_id,
        "learner_name": learner.full_name if learner else "",
        "learner_email": learner.email if learner else "",
        "progress": None,
        "cohort": None,
    }
    if learner is not None and product is not None:
        out["progress"] = progress_summary(db, learner, product)
        out["cohort"] = cohort_attendee(db, learner, product)
    return out
