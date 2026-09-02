"""The paid, instructor-examined certification tier — a strict state machine.

    purchased → exam_passed → slots_proposed → scheduled → passed
                                   ↑              ↓
                              retake_pending ←────┘ ('not yet', once)
                                                  ↓
                                               failed

Invariants that matter:
  * Nothing in this module issues a certificate except `record_outcome`
    with result='pass', which only the admin endpoint calls.
  * The written examination is a product-level QuizItem set
    (item_set='advanced', module_id=0) graded by the same engine as the
    module quizzes; the answer key never leaves the server.
  * The Certificate of Completion is a prerequisite for the written exam,
    so "advanced" is literally true.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import academy as svc
from . import certificates as certs
from .config import get_settings
from .emailer import (
    advanced_exam_passed_html,
    advanced_outcome_failed_html,
    advanced_outcome_retake_html,
    advanced_purchased_html,
    advanced_scheduled_html,
    advanced_slots_admin_html,
    send_email,
)
from .models import AdvancedCertification, Learner, Product, QuizAttempt, QuizItem

log = logging.getLogger(__name__)

TERMINAL = {"passed", "failed", "cancelled"}
OPEN_STATES = {
    "purchased", "exam_passed", "slots_proposed", "scheduled", "retake_pending", "exam_failed"
}
RETAKE_STUDY_DAYS = 14


# -----------------------------------------------------------------------------
# Lookups + eligibility
# -----------------------------------------------------------------------------

def current(db: Session, learner: Learner | None, product_code: str) -> AdvancedCertification | None:
    """The learner's live journey for this product (most recent open row,
    else the most recent terminal row so the dashboard can show the outcome)."""
    if learner is None:
        return None
    rows = db.execute(
        select(AdvancedCertification)
        .where(
            AdvancedCertification.learner_id == learner.id,
            AdvancedCertification.product_code == product_code,
        )
        .order_by(AdvancedCertification.created_at.desc(), AdvancedCertification.id.desc())
    ).scalars().all()
    for r in rows:
        if r.status in OPEN_STATES:
            return r
    return rows[0] if rows else None


def exam_items(db: Session, product_code: str) -> list[QuizItem]:
    return db.execute(
        select(QuizItem)
        .where(
            QuizItem.product_code == product_code,
            QuizItem.item_set == "advanced",
        )
        .order_by(QuizItem.position)
    ).scalars().all()


def offered(db: Session, product: Product) -> bool:
    """Purchasable at all: switched on AND the written exam bank exists."""
    return bool(product.advanced_cert_enabled) and bool(exam_items(db, product.code))


def eligibility(db: Session, learner: Learner, product: Product) -> tuple[bool, str]:
    """May this learner buy the examined tier right now?"""
    if not offered(db, product):
        return False, "The instructor-examined certification is not offered for this course yet."
    if not svc.has_access(db, learner, product.code):
        return False, "You need access to the course first."
    completion = certs.get_certificate(db, learner, product.code, "completion")
    if completion is None or completion.status != "issued":
        return False, "Earn the Certificate of Completion first — it is the prerequisite."
    if certs.get_certificate(db, learner, product.code, "verified") is not None:
        return False, "You already hold the Certificate of Verified Competency for this course."
    row = current(db, learner, product.code)
    if row is not None and row.status in OPEN_STATES:
        return False, "Your examination is already in progress."
    return True, ""


# -----------------------------------------------------------------------------
# Creation (payment webhook / admin comp)
# -----------------------------------------------------------------------------

def create(
    db: Session,
    learner: Learner,
    product: Product,
    *,
    source: str,
    order_id: int | None,
    amount_cents: int,
    currency: str,
    send_welcome: bool = True,
) -> AdvancedCertification:
    """Idempotent on order_id — Stripe delivers at least once."""
    if order_id is not None:
        existing = db.execute(
            select(AdvancedCertification).where(AdvancedCertification.order_id == order_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    row = AdvancedCertification(
        learner_id=learner.id,
        product_code=product.code,
        order_id=order_id,
        source=source,
        amount_cents=amount_cents,
        currency=currency,
        status="purchased",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if send_welcome:
        settings = get_settings()
        price = f"${amount_cents / 100:,.2f} {currency.upper()}" if amount_cents else ""
        send_email(
            to=learner.email,
            subject=f"Instructor-examined certification — {product.title}",
            html=advanced_purchased_html(
                learner.full_name or "", product.title,
                f"{settings.SITE_URL}/learn/{product.code}", price,
            ),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_purchased",
        )
    return row


# -----------------------------------------------------------------------------
# Written examination
# -----------------------------------------------------------------------------

def exam_open(row: AdvancedCertification | None) -> bool:
    return row is not None and row.status == "purchased"


def grade_exam(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification, responses: dict
) -> QuizAttempt:
    settings = get_settings()
    items = exam_items(db, product.code)
    detail: dict = {}
    auto_total = auto_correct = 0
    for item in items:
        raw = responses.get(item.code)
        verdict = svc.grade_item(item, raw)
        if verdict is not None:
            auto_total += 1
            if verdict:
                auto_correct += 1
        detail[item.code] = {"response": raw, "correct": verdict, "kind": item.kind}
    score = round(100.0 * auto_correct / auto_total, 1) if auto_total else 0.0
    passed = auto_total > 0 and score >= settings.ADVANCED_EXAM_THRESHOLD_PCT

    attempt = QuizAttempt(
        learner_id=learner.id,
        module_id=0,
        product_code=product.code,
        item_set="advanced",
        score_pct=score,
        passed=passed,
        auto_total=auto_total,
        auto_correct=auto_correct,
        responses=detail,
    )
    db.add(attempt)
    row.exam_attempts = (row.exam_attempts or 0) + 1
    row.exam_best_pct = max(row.exam_best_pct or 0.0, score)
    if passed:
        row.status = "exam_passed"
        row.exam_passed_at = datetime.now(timezone.utc)
    elif row.exam_attempts >= settings.ADVANCED_EXAM_MAX_ATTEMPTS:
        row.status = "exam_failed"
    db.commit()
    db.refresh(attempt)

    if passed:
        send_email(
            to=learner.email,
            subject=f"Written examination passed — {product.title}",
            html=advanced_exam_passed_html(
                learner.full_name or "", product.title, score,
                f"{settings.SITE_URL}/learn/{product.code}",
            ),
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_exam_passed",
        )
    return attempt


# -----------------------------------------------------------------------------
# Scheduling
# -----------------------------------------------------------------------------

def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def when_lines(at: datetime, tz_name: str) -> list[str]:
    """Human lines for one instant: learner's zone (if known), Eastern, UTC."""
    at = svc._aware(at)
    lines = []
    seen = set()
    for label, zone in (
        (tz_name, _zone(tz_name)),
        ("US Eastern", ZoneInfo("America/New_York")),
        ("UTC", timezone.utc),
    ):
        if zone is None:
            continue
        local = at.astimezone(zone)
        key = local.strftime("%Y-%m-%d %H:%M %z")
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{local.strftime('%A, %B %d, %Y at %H:%M')} ({label})")
    return lines


def can_propose(row: AdvancedCertification | None) -> tuple[bool, str]:
    if row is None:
        return False, "No examination in progress."
    if row.status in ("exam_passed", "slots_proposed"):
        return True, ""
    if row.status == "retake_pending":
        after = row.retake_after or date.today()
        if date.today() >= after:
            return True, ""
        return False, f"Your re-examination can be proposed on or after {after.strftime('%B %d, %Y')}."
    return False, "Not at the scheduling step."


def propose_slots(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    slots: list[datetime], tz_name: str, note: str,
) -> AdvancedCertification:
    now = datetime.now(timezone.utc)
    clean = sorted({svc._aware(s) for s in slots if svc._aware(s) > now + timedelta(hours=12)})
    if len(clean) < 1:
        raise ValueError("Propose at least one window at least 12 hours from now.")
    row.proposed_slots = [s.isoformat() for s in clean[:5]]
    row.learner_timezone = tz_name if _zone(tz_name) else ""
    row.learner_note = (note or "").strip()[:1000]
    row.status = "slots_proposed"
    db.commit()

    settings = get_settings()
    lines = []
    for iso in row.proposed_slots:
        lines.append(" / ".join(when_lines(datetime.fromisoformat(iso), row.learner_timezone)))
    send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Oral exam] {learner.full_name or learner.email} — {product.title}",
        html=advanced_slots_admin_html(
            learner.full_name or "", learner.email, product.title, lines, row.learner_note,
            f"{settings.SITE_URL}/admin#courses/{product.code}/certification",
        ),
        db=db, scope_kind="product", scope_code=product.code,
        template="advanced_slots_admin",
    )
    return row


def _ics(row: AdvancedCertification, product: Product, learner: Learner, minutes: int) -> str:
    start = svc._aware(row.scheduled_at)
    end = start + timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%SZ"
    what = "re-examination" if row.interview_no > 1 else "oral examination"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ProReadyEngineer//Certification//EN",
        "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:advcert-{row.id}-{row.interview_no}@proreadyengineer.com",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.astimezone(timezone.utc).strftime(fmt)}",
        f"DTEND:{end.astimezone(timezone.utc).strftime(fmt)}",
        f"SUMMARY:ProReadyEngineer {what} — {product.title}",
        f"DESCRIPTION:Live one-on-one {what} with the instructor. Meeting link: {row.meeting_url}",
        f"LOCATION:{row.meeting_url}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def schedule(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    at: datetime, meeting_url: str,
) -> AdvancedCertification:
    if row.status not in ("slots_proposed", "exam_passed", "retake_pending", "scheduled"):
        raise ValueError("This candidate is not at the scheduling step.")
    row.scheduled_at = svc._aware(at)
    row.meeting_url = (meeting_url or "").strip()[:500]
    row.status = "scheduled"
    db.commit()

    settings = get_settings()
    minutes = settings.ADVANCED_INTERVIEW_MINUTES
    import base64  # noqa: PLC0415

    ics = base64.b64encode(_ics(row, product, learner, minutes).encode()).decode()
    send_email(
        to=learner.email,
        subject=f"Your oral examination is booked — {product.title}",
        html=advanced_scheduled_html(
            learner.full_name or "", product.title,
            when_lines(row.scheduled_at, row.learner_timezone),
            row.meeting_url, minutes, row.interview_no,
            f"{settings.SITE_URL}/learn/{product.code}",
        ),
        bcc=settings.ADMIN_NOTIFY_EMAIL or None,
        db=db, scope_kind="product", scope_code=product.code,
        template="advanced_scheduled",
        attachments=[{"filename": "oral-examination.ics", "content": ics}],
    )
    return row


def reopen_scheduling(db: Session, row: AdvancedCertification) -> AdvancedCertification:
    """Admin: the booked time fell through — ask the learner for new windows."""
    if row.status != "scheduled":
        raise ValueError("Nothing is scheduled.")
    row.status = "retake_pending" if row.interview_no > 1 else "exam_passed"
    if row.interview_no > 1:
        row.retake_after = date.today()
    row.scheduled_at = None
    row.meeting_url = ""
    row.proposed_slots = []
    db.commit()
    return row


# -----------------------------------------------------------------------------
# Outcome — the only path to a verified certificate
# -----------------------------------------------------------------------------

def record_outcome(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    result: str, note: str, retake_after: date | None = None,
):
    if row.status != "scheduled":
        raise ValueError("Record an outcome only for a scheduled examination.")
    settings = get_settings()
    row.outcome_note = (note or "").strip()
    row.outcome_at = datetime.now(timezone.utc)
    exam_day = svc._aware(row.scheduled_at).date() if row.scheduled_at else date.today()

    if result == "pass":
        cert = certs.issue_verified(
            db, learner, product,
            exam_date=exam_day, exam_minutes=settings.ADVANCED_INTERVIEW_MINUTES,
        )
        row.status = "passed"
        row.certificate_id = cert.id
        db.commit()
        return cert

    if result == "retake":
        if row.interview_no >= 2:
            raise ValueError("The complimentary re-examination has already been used.")
        row.status = "retake_pending"
        row.interview_no = 2
        row.retake_after = retake_after or (date.today() + timedelta(days=RETAKE_STUDY_DAYS))
        row.proposed_slots = []
        row.scheduled_at = None
        row.meeting_url = ""
        db.commit()
        send_email(
            to=learner.email,
            subject=f"Your oral examination — {product.title}",
            html=advanced_outcome_retake_html(
                learner.full_name or "", product.title,
                row.retake_after.strftime("%B %d, %Y"),
                f"{settings.SITE_URL}/learn/{product.code}",
            ),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_retake",
        )
        return None

    if result == "fail":
        row.status = "failed"
        db.commit()
        send_email(
            to=learner.email,
            subject=f"Your re-examination — {product.title}",
            html=advanced_outcome_failed_html(learner.full_name or "", product.title),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_failed",
        )
        return None

    raise ValueError("result must be 'pass', 'retake' or 'fail'.")


def reset_exam(db: Session, row: AdvancedCertification) -> AdvancedCertification:
    """Admin: give the written exam back after the attempt cap."""
    if row.status not in ("exam_failed", "purchased"):
        raise ValueError("The written examination is not what is blocking this candidate.")
    row.status = "purchased"
    row.exam_attempts = 0
    db.commit()
    return row


def cancel(db: Session, row: AdvancedCertification, note: str) -> AdvancedCertification:
    if row.status in TERMINAL:
        raise ValueError("Already closed.")
    row.status = "cancelled"
    row.outcome_note = (note or "").strip()
    row.outcome_at = datetime.now(timezone.utc)
    db.commit()
    return row


# -----------------------------------------------------------------------------
# Serialisers
# -----------------------------------------------------------------------------

def learner_out(db: Session, learner: Learner, product: Product, row: AdvancedCertification | None) -> dict:
    settings = get_settings()
    ok, reason = eligibility(db, learner, product)
    out = {
        "offered": offered(db, product),
        "price_cents": product.advanced_cert_price_cents,
        "currency": product.currency,
        "interview_minutes": settings.ADVANCED_INTERVIEW_MINUTES,
        "exam_threshold": settings.ADVANCED_EXAM_THRESHOLD_PCT,
        "exam_max_attempts": settings.ADVANCED_EXAM_MAX_ATTEMPTS,
        "exam_item_count": len(exam_items(db, product.code)),
        "can_purchase": ok,
        "purchase_blocked_reason": reason,
        "competencies": certs.course_competencies(db, product),
        "state": None,
    }
    if row is None:
        return out
    can_prop, why = can_propose(row)
    out["state"] = {
        "id": row.id,
        "status": row.status,
        "exam_attempts": row.exam_attempts,
        "exam_best_pct": row.exam_best_pct,
        "exam_open": exam_open(row),
        "can_propose": can_prop,
        "propose_blocked_reason": why,
        "proposed_slots": list(row.proposed_slots or []),
        "learner_timezone": row.learner_timezone,
        "scheduled_at": row.scheduled_at,
        "scheduled_lines": when_lines(row.scheduled_at, row.learner_timezone) if row.scheduled_at else [],
        "meeting_url": row.meeting_url if row.status == "scheduled" else "",
        "interview_no": row.interview_no,
        "retake_after": row.retake_after,
        "created_at": row.created_at,
    }
    return out


def admin_out(db: Session, row: AdvancedCertification) -> dict:
    learner = db.get(Learner, row.learner_id)
    cert = db.get(certs.Certificate, row.certificate_id) if row.certificate_id else None
    return {
        "id": row.id,
        "learner_id": row.learner_id,
        "email": learner.email if learner else "",
        "full_name": learner.full_name if learner else "",
        "product_code": row.product_code,
        "status": row.status,
        "source": row.source,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "exam_attempts": row.exam_attempts,
        "exam_best_pct": row.exam_best_pct,
        "exam_passed_at": row.exam_passed_at,
        "proposed_slots": [
            {"iso": iso, "lines": when_lines(datetime.fromisoformat(iso), row.learner_timezone)}
            for iso in (row.proposed_slots or [])
        ],
        "learner_timezone": row.learner_timezone,
        "learner_note": row.learner_note,
        "scheduled_at": row.scheduled_at,
        "scheduled_lines": when_lines(row.scheduled_at, row.learner_timezone) if row.scheduled_at else [],
        "meeting_url": row.meeting_url,
        "interview_no": row.interview_no,
        "retake_after": row.retake_after,
        "outcome_note": row.outcome_note,
        "outcome_at": row.outcome_at,
        "certificate_code": cert.code if cert else "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
