"""Learner-facing academy API.

Public (no auth):
  GET  /api/academy/catalog                    — every live product
  GET  /api/academy/catalog/{code}             — one product + curriculum
  POST /api/academy/auth/request-link          — email a sign-in link
  POST /api/academy/auth/verify                — exchange link token for session
  GET  /api/academy/verify/{cert_code}         — public certificate check

Learner (session cookie):
  GET  /api/academy/me                         — identity + entitlements
  POST /api/academy/auth/logout
  GET  /api/academy/course/{code}              — modules, gates, progress
  GET  /api/academy/lesson/{id}                — lesson + signed playback URLs
  POST /api/academy/lesson/{id}/progress       — player heartbeat
  GET  /api/academy/quiz/{module_id}/{set}     — items WITHOUT answers
  POST /api/academy/quiz/{module_id}/{set}     — submit, grade, gate
  POST /api/academy/certificate/{code}         — issue if complete
  POST /api/academy/accept-terms               — click-wrap acceptance (logged)
  GET  /api/academy/slide-image/{module}/{n}/{size} — watermarked slide pixels
  GET  /api/academy/asset/{lesson_id}          — gated blob (simulator, labs)

The answer key never crosses the wire. `_public_item()` is the only
serializer used for quiz items, and it has no path to `answer`.

Slide images and asset blobs exist ONLY behind the two endpoints above:
both check the module-level entitlement, both send no-store cache headers,
and both stamp the learner's identity into what they serve — the slide
pixels are watermarked server-side, and HTML assets get a licensed-to
banner injected. There is no public URL to find.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as svc
from ..config import get_settings
from ..db import get_db
from ..emailer import login_link_html, send_email
from ..learner_auth import (
    clear_learner_cookie,
    consume_login_token,
    issue_login_token,
    optional_learner,
    recent_link_count,
    require_learner,
    set_learner_cookie,
)
from ..models import (
    AssetBlob,
    Certificate,
    Chapter,
    Enrollment,
    Learner,
    Lesson,
    Module,
    ModuleGrant,
    Product,
    QuizItem,
    Slide,
    SlideImage,
)
from ..stream_tokens import is_configured as stream_configured
from ..stream_tokens import playback_urls

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/academy", tags=["academy"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------

class RequestLinkIn(BaseModel):
    email: EmailStr
    next_path: str = "/learn"
    # Honeypot — same trick as the registration form. Bots fill it, humans
    # never see it. A filled value is dropped silently.
    website: str = ""


class VerifyIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ProgressIn(BaseModel):
    position_s: int = Field(ge=0, le=60 * 60 * 12)
    watched_delta_s: int = Field(default=0, ge=0, le=60)


class SubmitQuizIn(BaseModel):
    responses: dict


class OkOut(BaseModel):
    ok: bool = True


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _product_or_404(db: Session, code: str) -> Product:
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    return product


def _curriculum(db: Session, product_code: str) -> list[dict]:
    """Public curriculum outline — safe for the sales page, no lesson payloads."""
    modules = db.execute(
        select(Module)
        .where(Module.product_code == product_code)
        .order_by(Module.position)
    ).scalars().all()
    out = []
    for module in modules:
        lessons = db.execute(
            select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.position)
        ).scalars().all()
        out.append(
            {
                "code": module.code,
                "title": module.title,
                "summary": module.summary,
                "position": module.position,
                "hours": module.hours,
                "objectives": module.objectives or [],
                "topics": module.topics or [],
                "lesson_count": len(lessons),
                "duration_s": sum(l.duration_s for l in lessons),
                "has_video": any(l.kind == "video" for l in lessons),
                "has_quiz": bool(module.quiz_app_url)
                or svc.module_has_items(db, module.id, "formative"),
                "preview_lesson_id": next(
                    (l.id for l in lessons if l.is_preview), None
                ),
            }
        )
    return out


def _product_public(db: Session, product: Product) -> dict:
    return {
        "code": product.code,
        "title": product.title,
        "subtitle": product.subtitle,
        "summary": product.summary,
        "price_cents": product.price_cents,
        "currency": product.currency,
        "total_hours": product.total_hours,
        "status": product.status,
        "curriculum": _curriculum(db, product.code),
    }


def _public_item(item: QuizItem) -> dict:
    """Serialize a quiz item for the learner. Never includes `answer`."""
    return {
        "code": item.code,
        "kind": item.kind,
        "stem": item.stem,
        "options": item.options or [],
        "cognitive_level": item.cognitive_level,
        "position": item.position,
        # Items are ordered as (curriculum_section * 100 + index), so the UI
        # can chunk a long bank into the sections the curriculum defines
        # instead of presenting 40 questions as one wall.
        "section": item.position // 100,
        # The rubric is shown deliberately: for short-answer items the
        # learner should know what they're being marked against.
        "rubric": item.rubric if item.kind == "short" else "",
    }


# -----------------------------------------------------------------------------
# Catalog (public)
# -----------------------------------------------------------------------------

@router.get("/catalog")
def catalog(db: Session = Depends(get_db)) -> dict:
    products = db.execute(
        select(Product).where(Product.status == "live").order_by(Product.title)
    ).scalars().all()
    return {"products": [_product_public(db, p) for p in products]}


@router.get("/catalog/{code}")
def catalog_detail(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner | None = Depends(optional_learner),
) -> dict:
    product = _product_or_404(db, code)
    if product.status != "live" and not svc.has_access(db, learner, code):
        raise HTTPException(status_code=404, detail="Course not found.")
    data = _product_public(db, product)
    data["owned"] = svc.has_access(db, learner, code)
    return data


# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------

@router.post("/auth/request-link", response_model=OkOut)
def request_link(body: RequestLinkIn, db: Session = Depends(get_db)) -> OkOut:
    """Email a one-time sign-in link.

    Always returns ok=True, whether or not the address is known. Confirming
    which emails have accounts would leak the customer list to anyone with
    a browser, and the endpoint is unauthenticated by nature.
    """
    if body.website.strip():  # honeypot tripped
        return OkOut()

    settings = get_settings()
    email = body.email.lower().strip()

    learner = db.execute(
        select(Learner).where(Learner.email == email)
    ).scalar_one_or_none()

    # An owner address is configured by the operator, not claimed by a caller,
    # so the row is created on first request rather than requiring a purchase
    # first. Without this a newly-added owner has no way in at all: this
    # endpoint would no-op, and password signup on an owner address is refused
    # by design. The link still only reaches the mailbox itself.
    if learner is None and email in settings.owner_emails_list:
        learner = svc.upsert_learner(db, email, "")
        log.info("Created owner account on first sign-in request")

    if learner is None or learner.status != "active":
        log.info("Sign-in link requested for unknown/blocked address")
        return OkOut()

    svc.promote_if_owner(db, learner)

    if recent_link_count(db, learner.id) >= settings.LOGIN_LINK_MAX_PER_HOUR:
        log.warning("Sign-in link rate limit hit for learner id=%s", learner.id)
        return OkOut()

    next_path = body.next_path if body.next_path.startswith("/") else "/learn"
    raw = issue_login_token(db, learner, next_path=next_path)
    link = f"{settings.SITE_URL}/learn/signin?token={raw}"

    send_email(
        to=learner.email,
        subject="Your ProReadyEngineer sign-in link",
        html=login_link_html(
            learner.full_name or "", link, settings.LOGIN_LINK_TTL_SECONDS // 60
        ),
    )
    return OkOut()


@router.post("/auth/verify")
def verify(body: VerifyIn, response: Response, db: Session = Depends(get_db)) -> dict:
    result = consume_login_token(db, body.token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This sign-in link has expired or was already used. Request a new one.",
        )
    learner, next_path = result
    # Magic-link sign-in is the other way an owner email gets proven, so
    # promote here too — otherwise is_staff only ever gets set on the
    # password path and the quiz apps never see is_admin.
    svc.promote_if_owner(db, learner)
    set_learner_cookie(response, learner)
    return {
        "ok": True,
        "email": learner.email,
        "full_name": learner.full_name,
        "next_path": next_path,
    }


@router.post("/auth/logout", response_model=OkOut)
def logout(response: Response) -> OkOut:
    clear_learner_cookie(response)
    return OkOut()


class SetPasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/set-password", response_model=OkOut)
def set_password(
    body: SetPasswordIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> OkOut:
    """Set the password the legacy quiz apps sign in with.

    Only reachable from a session, which means the mailbox was already proven
    by opening a magic link. That is what makes it safe for this to overwrite
    an existing password: it is the account-recovery path as well as the
    first-time setup path, and it never accepts an email from the caller.
    """
    from .compat import hash_password

    learner.password_hash = hash_password(body.password)
    db.commit()
    log.info("Learner %s set a quiz-app password", learner.email)
    return OkOut()


@router.get("/me")
def me(
    db: Session = Depends(get_db),
    learner: Learner | None = Depends(optional_learner),
) -> dict:
    if learner is None:
        return {"signed_in": False}
    rows = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id, Enrollment.status == "active"
        )
    ).scalars().all()
    # Write-on-read settlement enforcement: a bank payment past its
    # 7-business-day deadline drops out of /me the moment it's looked at.
    rows = [r for r in rows if svc.settlement_ok(db, r)]
    products = {p.code: p for p in db.execute(select(Product)).scalars().all()}

    # Module-level grants surface as course access too — a learner holding
    # only "Day 1" must still find the course on their dashboard.
    grant_rows = db.execute(
        select(ModuleGrant, Module)
        .join(Module, Module.id == ModuleGrant.module_id)
        .where(
            ModuleGrant.learner_id == learner.id,
            ModuleGrant.status == "active",
        )
    ).all()
    enrolled_codes = {r.product_code for r in rows}
    granted_products = []
    seen = set()
    for _grant, module in grant_rows:
        if module.product_code in enrolled_codes or module.product_code in seen:
            continue
        seen.add(module.product_code)
        granted_products.append(
            {
                "product_code": module.product_code,
                "title": products[module.product_code].title
                if module.product_code in products
                else module.product_code,
                "partial": True,
            }
        )

    settings = get_settings()
    return {
        "signed_in": True,
        "email": learner.email,
        "full_name": learner.full_name,
        "is_owner": svc.is_owner(learner),
        # Lets the dashboard prompt for one before sending someone to a quiz
        # app they would otherwise be unable to sign in to.
        "has_password": bool(learner.password_hash),
        "enrollments": [
            {
                "product_code": r.product_code,
                "title": products[r.product_code].title
                if r.product_code in products
                else r.product_code,
                "granted_at": r.granted_at,
                "expires_at": r.expires_at,
            }
            for r in rows
        ],
        "module_grants": granted_products,
        # Click-wrap state: the UI must collect an acceptance for the current
        # terms version before opening any protected material.
        "terms_version": settings.TERMS_VERSION,
        "terms_accepted": svc.terms_accepted(db, learner, settings.TERMS_VERSION),
    }


class AcceptTermsIn(BaseModel):
    version: str = Field(min_length=1, max_length=32)


@router.post("/accept-terms", response_model=OkOut)
def accept_terms(
    body: AcceptTermsIn,
    request: Request,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> OkOut:
    """Record the click-wrap acceptance of the training terms.

    The version echoes back what the UI showed, and only the current version
    counts — accepting an old document is not accepting the new one.
    """
    settings = get_settings()
    if body.version != settings.TERMS_VERSION:
        raise HTTPException(
            status_code=409,
            detail="The terms were updated — please review the current version.",
        )
    svc.record_terms_acceptance(
        db, learner, body.version, request.headers.get("user-agent", "")
    )
    log.info("Learner %s accepted terms %s", learner.email, body.version)
    return OkOut()


# -----------------------------------------------------------------------------
# Course + lessons
# -----------------------------------------------------------------------------

@router.get("/course/{code}")
def course(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    product = _product_or_404(db, code)
    if not svc.has_any_access(db, learner, code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this course yet.",
        )
    modules = svc.course_state(db, learner, code)
    total_lessons = sum(m["lesson_count"] for m in modules)
    done_lessons = sum(m["lessons_completed"] for m in modules)
    certificate = db.execute(
        select(Certificate).where(
            Certificate.learner_id == learner.id, Certificate.product_code == code
        )
    ).scalar_one_or_none()
    return {
        "product": {
            "code": product.code,
            "title": product.title,
            "subtitle": product.subtitle,
            "total_hours": product.total_hours,
            "sequential_gate": product.sequential_gate,
        },
        "modules": modules,
        "percent": round(100.0 * done_lessons / total_lessons, 1)
        if total_lessons
        else 0.0,
        "lessons_completed": done_lessons,
        "lessons_total": total_lessons,
        "complete": svc.course_complete(db, learner, code),
        "certificate_code": certificate.code if certificate else None,
        "video_ready": stream_configured(),
    }


@router.get("/lesson/{lesson_id}")
def lesson_detail(
    lesson_id: int,
    db: Session = Depends(get_db),
    learner: Learner | None = Depends(optional_learner),
) -> dict:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found.")

    ok, reason = svc.lesson_accessible(db, learner, lesson)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    module = db.get(Module, lesson.module_id)
    prog = svc.progress_map(db, learner, [lesson.id]).get(lesson.id)

    siblings = db.execute(
        select(Lesson).where(Lesson.module_id == lesson.module_id).order_by(Lesson.position)
    ).scalars().all()
    index = next((i for i, l in enumerate(siblings) if l.id == lesson.id), 0)

    # Chapters are how a three-hour recording becomes navigable. Their titles
    # come from the deck's own section names, and the timestamps from matching
    # what was on screen to the slides, so they mark where a topic is actually
    # taught rather than where an upload limit happened to cut the file.
    chapters = db.execute(
        select(Chapter).where(Chapter.lesson_id == lesson.id).order_by(Chapter.position)
    ).scalars().all()
    slides = db.execute(
        select(Slide).where(Slide.module_id == lesson.module_id).order_by(Slide.number)
    ).scalars().all()

    return {
        "id": lesson.id,
        "code": lesson.code,
        "title": lesson.title,
        "kind": lesson.kind,
        "duration_s": lesson.duration_s,
        "body": lesson.body,
        "asset_path": lesson.asset_path,
        "is_preview": lesson.is_preview,
        "module": {
            "id": module.id if module else None,
            "code": module.code if module else "",
            "title": module.title if module else "",
            "product_code": module.product_code if module else "",
        },
        "playback": playback_urls(lesson.video_uid) if lesson.kind == "video" else None,
        "video_pending": lesson.kind == "video"
        and (not lesson.video_uid or not stream_configured()),
        "progress": {
            "position_s": prog.position_s if prog else 0,
            "watched_s": prog.watched_s if prog else 0,
            "completed": svc.lesson_is_complete(lesson, prog),
        },
        "chapters": [
            {
                "title": c.title,
                "start_s": c.start_s,
                "end_s": c.end_s,
                "slides": c.slides or [],
            }
            for c in chapters
        ],
        "slides": [
            {
                "number": s_.number,
                "title": s_.title,
                "section": s_.section,
                "appears_at_s": s_.appears_at_s,
                "image_sm": s_.image_sm,
                "image_lg": s_.image_lg,
            }
            for s_ in slides
        ],
        "prev_lesson_id": siblings[index - 1].id if index > 0 else None,
        "next_lesson_id": siblings[index + 1].id if index + 1 < len(siblings) else None,
        # Watermark shown over the player and slide viewer. Rendering the
        # buyer's own address on every frame is the deterrent that survives
        # a screen recording leaving the building.
        "watermark": learner.email if learner else "",
    }


@router.post("/lesson/{lesson_id}/progress")
def lesson_progress(
    lesson_id: int,
    body: ProgressIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    ok, reason = svc.lesson_accessible(db, learner, lesson)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    row = svc.record_progress(
        db, learner, lesson, body.position_s, body.watched_delta_s
    )
    return {
        "ok": True,
        "position_s": row.position_s,
        "watched_s": row.watched_s,
        "completed": row.completed_at is not None,
    }


# -----------------------------------------------------------------------------
# Quizzes
# -----------------------------------------------------------------------------

def _module_for_learner(db: Session, module_id: int, learner: Learner) -> Module:
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    if not svc.module_access(db, learner, module):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this course yet.",
        )
    if not svc.module_unlocked(db, learner, module):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Finish the previous module to unlock this one.",
        )
    return module


@router.get("/quiz/{module_id}/{item_set}")
def quiz_items(
    module_id: int,
    item_set: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    if item_set not in ("formative", "summative"):
        raise HTTPException(status_code=400, detail="Unknown item set.")
    module = _module_for_learner(db, module_id, learner)

    items = db.execute(
        select(QuizItem)
        .where(QuizItem.module_id == module.id, QuizItem.item_set == item_set)
        .order_by(QuizItem.position)
    ).scalars().all()

    settings = get_settings()
    previous = svc.best_attempt(db, learner, module.id, item_set)
    return {
        "module": {"id": module.id, "code": module.code, "title": module.title},
        "item_set": item_set,
        "threshold": settings.MASTERY_THRESHOLD_PCT,
        "items": [_public_item(i) for i in items],
        "best_score": previous.score_pct if previous else None,
        "passed": bool(previous and previous.passed),
    }


@router.post("/quiz/{module_id}/{item_set}")
def submit_quiz(
    module_id: int,
    item_set: str,
    body: SubmitQuizIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    if item_set not in ("formative", "summative"):
        raise HTTPException(status_code=400, detail="Unknown item set.")
    module = _module_for_learner(db, module_id, learner)

    attempt = svc.grade_submission(db, learner, module, item_set, body.responses or {})

    items = {
        i.code: i
        for i in db.execute(
            select(QuizItem).where(
                QuizItem.module_id == module.id, QuizItem.item_set == item_set
            )
        ).scalars().all()
    }
    # Explanations are released only after submission — that's the teaching
    # moment, and withholding them beforehand keeps the bank reusable.
    feedback = [
        {
            "code": code,
            "correct": detail.get("correct"),
            "response": detail.get("response"),
            "explanation": items[code].explanation if code in items else "",
            "rubric": items[code].rubric if code in items else "",
            "needs_review": detail.get("correct") is None,
        }
        for code, detail in attempt.responses.items()
    ]

    return {
        "score_pct": attempt.score_pct,
        "passed": attempt.passed,
        "auto_correct": attempt.auto_correct,
        "auto_total": attempt.auto_total,
        "threshold": get_settings().MASTERY_THRESHOLD_PCT,
        "feedback": feedback,
    }


# -----------------------------------------------------------------------------
# Certificates
# -----------------------------------------------------------------------------

@router.post("/certificate/{code}")
def request_certificate(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    _product_or_404(db, code)
    if not svc.has_access(db, learner, code):
        raise HTTPException(status_code=403, detail="You don't have access to this course.")
    cert = svc.issue_certificate(db, learner, code)
    if cert is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finish every module and its assessments to earn the certificate.",
        )
    return {
        "code": cert.code,
        "learner_name": cert.learner_name,
        "issued_at": cert.issued_at,
    }


@router.get("/verify/{cert_code}")
def verify_certificate(cert_code: str, db: Session = Depends(get_db)) -> dict:
    """Public certificate check. Returns the holder's name and course only."""
    cert = db.execute(
        select(Certificate).where(Certificate.code == cert_code.upper().strip())
    ).scalar_one_or_none()
    if cert is None:
        return {"valid": False}
    product = db.get(Product, cert.product_code)
    return {
        "valid": True,
        "code": cert.code,
        "learner_name": cert.learner_name,
        "course": product.title if product else cert.product_code,
        "issued_at": cert.issued_at,
    }


# -----------------------------------------------------------------------------
# Protected material serving — slide images and asset blobs
# -----------------------------------------------------------------------------
# Both endpoints below are the ONLY paths to these bytes. Both check the
# module-level entitlement (owner / product enrollment / per-module grant),
# send no-store headers so nothing lands in a shared cache, and stamp the
# learner's identity into what they serve.

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Robots-Tag": "noindex, nofollow",
}


def _watermark_image(data: bytes, text: str) -> bytes:
    """Burn a per-learner watermark into slide pixels, server-side.

    A corner tag plus a faint diagonal through the middle: unobtrusive to
    study from, expensive to clean up, and it survives a right-click save —
    which is the point. On any Pillow hiccup the original bytes are served
    rather than failing the lesson (the frontend overlay still shows the
    learner's address in that case).
    """
    if not text:
        return data
    try:
        import io

        from PIL import Image, ImageDraw, ImageFont

        im = Image.open(io.BytesIO(data)).convert("RGBA")
        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = im.size

        try:
            corner_font = ImageFont.load_default(size=max(12, h // 60))
            diag_font = ImageFont.load_default(size=max(18, h // 28))
        except TypeError:  # very old Pillow — unsized bitmap font
            corner_font = diag_font = ImageFont.load_default()

        tag = f"Licensed to {text} · ProReadyEngineer LLC"
        # Corner tag, bottom-left, readable but quiet.
        draw.text((int(w * 0.012), int(h * 0.962)), tag,
                  fill=(255, 255, 255, 150), font=corner_font,
                  stroke_width=1, stroke_fill=(0, 0, 0, 130))
        # Faint diagonal across the middle.
        diag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ddraw = ImageDraw.Draw(diag)
        ddraw.text((w // 2, h // 2), text, fill=(128, 128, 128, 34),
                   font=diag_font, anchor="mm")
        diag = diag.rotate(25, resample=Image.BICUBIC)
        overlay = Image.alpha_composite(overlay, diag)

        out = Image.alpha_composite(im, overlay).convert("RGB")
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=False)
        return buf.getvalue()
    except Exception:  # pragma: no cover — never fail a lesson over a stamp
        log.exception("Slide watermarking failed; serving original")
        return data


@router.get("/slide-image/{module_id}/{number}/{size}")
def slide_image(
    module_id: int,
    number: int,
    size: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> Response:
    """One slide's pixels, watermarked with the requesting learner's email.

    Auth is the session cookie (the <img> tags request with credentials).
    The entitlement check is module-scoped, so a Day-1-only grant cannot
    fetch Day 2's deck by iterating URLs.
    """
    if size not in ("lg", "sm"):
        raise HTTPException(status_code=404, detail="Unknown size.")
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    if not svc.module_unlocked(db, learner, module):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this material.",
        )
    row = db.execute(
        select(SlideImage).where(
            SlideImage.module_id == module_id,
            SlideImage.number == number,
            SlideImage.size == size,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Slide not found.")

    # Thumbnails skip the burn — too small to read a watermark, and the
    # strip requests dozens at once; the viewer image is always stamped.
    payload = row.data if size == "sm" else _watermark_image(
        row.data, learner.email
    )
    return Response(content=payload, media_type=row.content_type,
                    headers=dict(_NO_STORE))


_ASSET_BANNER = """
<style>
#pre-license-banner{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;
background:rgba(12,18,32,.92);color:#cfe3ff;font:12px/1.5 system-ui,Segoe UI,sans-serif;
padding:6px 14px;display:flex;gap:14px;justify-content:space-between;align-items:center;
border-top:1px solid rgba(120,160,255,.35);pointer-events:none}
#pre-license-banner b{color:#fff;font-weight:600}
</style>
<div id="pre-license-banner">
<span>Licensed to <b>__EMAIL__</b> — personal, non-transferable training use only. Do not copy or redistribute.</span>
<span>Training simulation — NOT for operation of any real engine. © ProReadyEngineer LLC</span>
</div>
"""


@router.get("/asset/{lesson_id}")
def lesson_asset(
    lesson_id: int,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> Response:
    """Serve a protected blob (the mapping simulator, labs, handouts).

    Opens as a top-level navigation on the API origin, so the SameSite=None
    session cookie rides along. HTML gets a licensed-to banner injected and
    a frame-ancestors lockdown; everything gets no-store headers.
    """
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    ok, reason = svc.lesson_accessible(db, learner, lesson)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    path = lesson.asset_path or ""
    if not path.startswith("blob:"):
        raise HTTPException(status_code=404, detail="This lesson has no stored asset.")
    blob = db.execute(
        select(AssetBlob).where(AssetBlob.key == path[len("blob:"):])
    ).scalar_one_or_none()
    if blob is None:
        raise HTTPException(status_code=404, detail="Asset not found.")

    headers = dict(_NO_STORE)
    headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    data = blob.data

    if blob.content_type.startswith("text/html"):
        try:
            html = data.decode("utf-8", errors="replace")
            banner = _ASSET_BANNER.replace("__EMAIL__", learner.email)
            lowered = html.lower()
            idx = lowered.rfind("</body>")
            html = (html[:idx] + banner + html[idx:]) if idx != -1 else html + banner
            data = html.encode("utf-8")
        except Exception:  # pragma: no cover
            log.exception("Asset banner injection failed; serving original")

    log.info("Asset %s served to %s", path, learner.email)
    return Response(content=data, media_type=blob.content_type, headers=headers)


# -----------------------------------------------------------------------------
# My courses — everything this account can open, for the /learn chooser
# -----------------------------------------------------------------------------

@router.get("/my-courses")
def my_courses(
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    """The courses this account can open, with how it holds each one.

    Owners see every product (drafts included — that is the point of the
    bypass). Everyone else sees products they hold a full enrollment for,
    plus products where they hold at least one per-module grant. Draft
    status does not hide a course here: entitlement implies visibility,
    which is how a cohort learns from a product that is not yet publicly
    for sale.
    """
    products = {
        p.code: p for p in db.execute(select(Product)).scalars().all()
    }

    def pack(p: Product, access: str) -> dict:
        module_count = db.execute(
            select(Module).where(Module.product_code == p.code)
        ).scalars().all()
        return {
            "code": p.code,
            "title": p.title,
            "subtitle": p.subtitle,
            "total_hours": p.total_hours,
            "status": p.status,
            "module_count": len(module_count),
            # 'owner' | 'full' | 'partial'
            "access": access,
        }

    out: list[dict] = []
    if svc.is_owner(learner):
        out = [pack(p, "owner") for p in products.values()]
    else:
        from datetime import datetime, timezone

        full_codes: set[str] = set()
        rows = db.execute(
            select(Enrollment).where(
                Enrollment.learner_id == learner.id,
                Enrollment.status == "active",
            )
        ).scalars().all()
        now = datetime.now(timezone.utc)
        for row in rows:
            if not svc.settlement_ok(db, row):
                continue
            expires = svc._aware(row.expires_at)
            if expires is not None and expires <= now:
                continue
            if row.product_code in products and row.product_code not in full_codes:
                full_codes.add(row.product_code)
                out.append(pack(products[row.product_code], "full"))

        grant_rows = db.execute(
            select(ModuleGrant, Module)
            .join(Module, Module.id == ModuleGrant.module_id)
            .where(
                ModuleGrant.learner_id == learner.id,
                ModuleGrant.status == "active",
            )
        ).all()
        seen_partial: set[str] = set()
        for _grant, module in grant_rows:
            code = module.product_code
            if code in full_codes or code in seen_partial or code not in products:
                continue
            seen_partial.add(code)
            out.append(pack(products[code], "partial"))

    out.sort(key=lambda c: c["title"])
    return {"courses": out}
