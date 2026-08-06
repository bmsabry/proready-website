"""Admin API for the academy: learners, enrollments, content, analytics.

Auth reuses `require_admin`, so the existing session cookie and the bearer
token escape hatch both work unchanged. Every endpoint here is admin-only —
none of it is reachable with a learner session.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import academy as svc
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..emailer import enrollment_granted_html, login_link_html, send_email
from ..learner_auth import issue_login_token
from ..models import (
    Chapter,
    Enrollment,
    Learner,
    Lesson,
    LessonProgress,
    Module,
    Product,
    QuizAttempt,
    QuizItem,
    Slide,
)
from ..stats_queries import product_headline_stats

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/academy", tags=["academy-admin"])


class GrantIn(BaseModel):
    email: EmailStr
    product_code: str
    full_name: str = ""
    note: str = ""
    send_email_invite: bool = True


class RevokeIn(BaseModel):
    email: EmailStr
    product_code: str


class LoginLinkIn(BaseModel):
    email: EmailStr
    next_path: str = "/learn"
    send_email: bool = False


class ProductPatch(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    summary: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = None
    stripe_price_id: str | None = None
    status: str | None = None


class LessonPatch(BaseModel):
    title: str | None = None
    video_uid: str | None = None
    duration_s: int | None = Field(default=None, ge=0)
    asset_path: str | None = None
    body: str | None = None
    is_preview: bool | None = None
    position: int | None = Field(default=None, ge=0)


# -----------------------------------------------------------------------------
# Products & content
# -----------------------------------------------------------------------------

@router.get("/products")
def list_products(
    db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    products = db.execute(select(Product).order_by(Product.title)).scalars().all()
    out = []
    for product in products:
        modules = db.execute(
            select(Module).where(Module.product_code == product.code)
        ).scalars().all()
        lesson_count = db.execute(
            select(func.count(Lesson.id)).where(
                Lesson.module_id.in_([m.id for m in modules] or [0])
            )
        ).scalar_one()
        ready = db.execute(
            select(func.count(Lesson.id)).where(
                Lesson.module_id.in_([m.id for m in modules] or [0]),
                Lesson.kind == "video",
                Lesson.video_uid != "",
            )
        ).scalar_one()
        pending = db.execute(
            select(func.count(Lesson.id)).where(
                Lesson.module_id.in_([m.id for m in modules] or [0]),
                Lesson.kind == "video",
                Lesson.video_uid == "",
            )
        ).scalar_one()
        enrolled = db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.product_code == product.code,
                Enrollment.status == "active",
            )
        ).scalar_one()
        out.append(
            {
                "code": product.code,
                "title": product.title,
                "subtitle": product.subtitle,
                "status": product.status,
                "price_cents": product.price_cents,
                "currency": product.currency,
                "stripe_price_id": product.stripe_price_id,
                "total_hours": product.total_hours,
                "module_count": len(modules),
                "lesson_count": lesson_count,
                "videos_ready": ready,
                "videos_pending": pending,
                "active_enrollments": enrolled,
            }
        )
    return {"products": out}


@router.patch("/products/{code}")
def patch_product(
    code: str,
    body: ProductPatch,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")

    if body.status is not None and body.status not in ("draft", "live"):
        raise HTTPException(status_code=400, detail="status must be draft or live.")

    # Guard rail: refuse to publish a course nobody can actually pay for.
    # Getting this wrong means a live buy button that 409s on click.
    if body.status == "live":
        price = body.price_cents if body.price_cents is not None else product.price_cents
        if price <= 0 and not (
            body.stripe_price_id
            if body.stripe_price_id is not None
            else product.stripe_price_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Set a price (or a Stripe price id) before going live.",
            )

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(product, field, value)
    db.commit()
    return {"ok": True, "code": product.code, "status": product.status}


@router.get("/products/{code}/content")
def product_content(
    code: str, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    modules = db.execute(
        select(Module).where(Module.product_code == code).order_by(Module.position)
    ).scalars().all()
    out = []
    for module in modules:
        lessons = db.execute(
            select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.position)
        ).scalars().all()
        item_count = db.execute(
            select(func.count(QuizItem.id)).where(QuizItem.module_id == module.id)
        ).scalar_one()
        out.append(
            {
                "id": module.id,
                "code": module.code,
                "title": module.title,
                "position": module.position,
                "hours": module.hours,
                "quiz_app_url": module.quiz_app_url,
                "quiz_item_count": item_count,
                "lessons": [
                    {
                        "id": l.id,
                        "code": l.code,
                        "title": l.title,
                        "kind": l.kind,
                        "body": l.body or "",
                        "position": l.position,
                        "duration_s": l.duration_s,
                        "video_uid": l.video_uid,
                        "source_file": l.source_file,
                        "asset_path": l.asset_path,
                        "is_preview": l.is_preview,
                    }
                    for l in lessons
                ],
            }
        )
    return {"product": {"code": product.code, "title": product.title}, "modules": out}


@router.patch("/lessons/{lesson_id}")
def patch_lesson(
    lesson_id: int,
    body: LessonPatch,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lesson, field, value)
    db.commit()
    return {"ok": True, "id": lesson.id, "video_uid": lesson.video_uid}


class ChapterIn(BaseModel):
    title: str
    start_s: int
    end_s: int
    slides: list[int] = Field(default_factory=list)


class SlideIn(BaseModel):
    number: int
    title: str = ""
    section: str = ""
    text: str = ""
    appears_at_s: int = -1
    image_lg: str = ""
    image_sm: str = ""


class ModuleIngestIn(BaseModel):
    video_uid: str = ""
    duration_s: int = 0
    chapters: list[ChapterIn] = Field(default_factory=list)
    slides: list[SlideIn] = Field(default_factory=list)
    replace: bool = True


@router.post("/modules/{code}/ingest")
def ingest_module(
    code: str,
    body: ModuleIngestIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Apply the ingest pipeline's output to a module.

    This is the seam between the two halves of the platform: the pipeline turns
    a recording and a deck into a master video plus chapters and slides, and
    this endpoint reshapes the module to match. It is idempotent — running the
    pipeline again and re-posting simply replaces what was there.

    The important thing it does is collapse the per-file video lessons into a
    single one. The source recordings arrive split across a dozen or more files
    purely because of upload limits, and a boundary can land mid-sentence; those
    were never units of teaching and should never have been units of delivery.
    What replaces them is one continuous lesson navigated by named chapters.
    """
    module = db.execute(
        select(Module).where(Module.code == code)
    ).scalar_one_or_none()
    if module is None:
        raise HTTPException(status_code=404, detail=f"No module {code}.")

    lessons = db.execute(
        select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.position)
    ).scalars().all()
    videos = [l for l in lessons if l.kind == "video"]

    keep: Lesson | None = None
    if videos:
        keep, *extra = videos
        keep.title = f"{module.code} — full lecture"
        keep.code = f"{module.code}-LECTURE"
        keep.video_uid = body.video_uid
        keep.duration_s = body.duration_s
        keep.source_file = "master.mp4"
        # The surplus part-lessons carry progress rows, so they are removed
        # together with them rather than orphaned.
        for row in extra:
            db.execute(
                delete(LessonProgress).where(LessonProgress.lesson_id == row.id)
            )
            db.delete(row)
    elif body.video_uid:
        keep = Lesson(
            module_id=module.id,
            code=f"{module.code}-LECTURE",
            title=f"{module.code} — full lecture",
            position=0,
            kind="video",
            video_uid=body.video_uid,
            duration_s=body.duration_s,
            source_file="master.mp4",
        )
        db.add(keep)
        db.flush()

    if body.replace and keep is not None:
        db.execute(delete(Chapter).where(Chapter.lesson_id == keep.id))
    if keep is not None:
        for i, ch in enumerate(body.chapters):
            db.add(
                Chapter(
                    lesson_id=keep.id,
                    position=i,
                    title=ch.title,
                    start_s=ch.start_s,
                    end_s=ch.end_s,
                    slides=ch.slides,
                )
            )

    if body.replace:
        db.execute(delete(Slide).where(Slide.module_id == module.id))
    for sl in body.slides:
        db.add(
            Slide(
                module_id=module.id,
                number=sl.number,
                title=sl.title,
                section=sl.section,
                text=sl.text,
                appears_at_s=sl.appears_at_s,
                image_lg=sl.image_lg,
                image_sm=sl.image_sm,
            )
        )

    db.commit()
    log.info(
        "Admin %s ingested %s: uid=%s chapters=%d slides=%d",
        admin, code, body.video_uid, len(body.chapters), len(body.slides),
    )
    return {
        "ok": True,
        "module": code,
        "lesson_id": keep.id if keep else None,
        "video_uid": body.video_uid,
        "duration_s": body.duration_s,
        "chapters": len(body.chapters),
        "slides": len(body.slides),
        "part_lessons_removed": max(0, len(videos) - 1),
    }


# -----------------------------------------------------------------------------
# Learners & enrollments
# -----------------------------------------------------------------------------

@router.get("/learners")
def list_learners(
    product_code: str = "",
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    learners = db.execute(
        select(Learner).order_by(Learner.created_at.desc()).limit(500)
    ).scalars().all()
    enrollments = db.execute(select(Enrollment)).scalars().all()
    by_learner: dict[int, list[Enrollment]] = {}
    for row in enrollments:
        by_learner.setdefault(row.learner_id, []).append(row)

    out = []
    for learner in learners:
        # Self-healing: opening the admin table reconciles every stored owner
        # flag with the current OWNER_EMAILS, so a removed owner stops reading
        # as staff here without waiting for them to sign in again.
        svc.sync_owner_flag(db, learner)
        rows = by_learner.get(learner.id, [])
        if product_code and not any(
            r.product_code == product_code and r.status == "active" for r in rows
        ):
            continue

        progress_rows = db.execute(
            select(func.count(LessonProgress.id)).where(
                LessonProgress.learner_id == learner.id,
                LessonProgress.completed_at.isnot(None),
            )
        ).scalar_one()
        attempts = db.execute(
            select(func.count(QuizAttempt.id)).where(
                QuizAttempt.learner_id == learner.id
            )
        ).scalar_one()

        out.append(
            {
                "id": learner.id,
                "email": learner.email,
                "full_name": learner.full_name,
                "status": learner.status,
                "is_owner": svc.is_owner(learner),
                "has_password": bool(learner.password_hash),
                "created_at": learner.created_at,
                "last_login_at": learner.last_login_at,
                "lessons_completed": progress_rows,
                "quiz_attempts": attempts,
                "enrollments": [
                    {
                        "product_code": r.product_code,
                        "status": r.status,
                        "source": r.source,
                        "granted_at": r.granted_at,
                    }
                    for r in rows
                ],
            }
        )
    return {"learners": out, "count": len(out)}


@router.post("/grant")
def grant(
    body: GrantIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)
) -> dict:
    """Give someone access by hand — comps, beta readers, invoice-paid buyers."""
    settings = get_settings()
    product = db.get(Product, body.product_code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")

    learner = svc.upsert_learner(db, str(body.email), body.full_name)
    svc.grant_enrollment(
        db,
        learner,
        body.product_code,
        source="manual",
        note=body.note or f"granted by {admin}",
    )

    if body.send_email_invite:
        raw = issue_login_token(db, learner, next_path=f"/learn/{body.product_code}")
        link = f"{settings.SITE_URL}/learn/signin?token={raw}"
        send_email(
            to=learner.email,
            subject=f"Your access to {product.title}",
            html=enrollment_granted_html(learner.full_name or "", product.title, link),
        )

    log.info("Admin %s granted %s access to %s", admin, learner.email, body.product_code)
    return {"ok": True, "learner_id": learner.id, "email": learner.email}


@router.post("/revoke")
def revoke(
    body: RevokeIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)
) -> dict:
    learner = db.execute(
        select(Learner).where(Learner.email == str(body.email).lower().strip())
    ).scalar_one_or_none()
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found.")
    enrollment = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id,
            Enrollment.product_code == body.product_code,
        )
    ).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Enrollment not found.")
    enrollment.status = "revoked"
    enrollment.note = f"revoked by {admin}"
    db.commit()
    log.info("Admin %s revoked %s from %s", admin, learner.email, body.product_code)
    return {"ok": True}


@router.post("/login-link")
def login_link(
    body: LoginLinkIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)
) -> dict:
    """Mint a sign-in link for any learner — support, debugging, lost email.

    Returns the raw link so it can be copied straight out of the admin panel
    when the person never received the original. The token is single-use and
    expires like any other, so a copied link is not a standing key.
    """
    settings = get_settings()
    email = str(body.email).lower().strip()
    learner = db.execute(
        select(Learner).where(Learner.email == email)
    ).scalar_one_or_none()
    if learner is None:
        # Owner addresses are created on demand — they are operator config, so
        # there is nothing to look up until the first sign-in. Anyone else has
        # to exist already, which keeps this from doubling as a create-user API.
        if email not in settings.owner_emails_list:
            raise HTTPException(status_code=404, detail="Learner not found.")
        learner = svc.upsert_learner(db, email, "")
    svc.promote_if_owner(db, learner)

    raw = issue_login_token(db, learner, next_path=body.next_path or "/learn")
    link = f"{settings.SITE_URL}/learn/signin?token={raw}"
    if body.send_email:
        send_email(
            to=learner.email,
            subject="Your ProReadyEngineer sign-in link",
            html=login_link_html(
                learner.full_name or "", link, settings.LOGIN_LINK_TTL_SECONDS // 60
            ),
        )
    log.info("Admin %s minted a sign-in link for %s", admin, learner.email)
    return {
        "ok": True,
        "email": learner.email,
        "link": link,
        "expires_in_seconds": settings.LOGIN_LINK_TTL_SECONDS,
        "emailed": bool(body.send_email),
    }


@router.get("/owners")
def owners(_: str = Depends(require_admin)) -> dict:
    """Which addresses hold the everything-bypass, and how it is configured."""
    settings = get_settings()
    return {
        "owner_emails": settings.owner_emails_list,
        "admin_email": settings.ADMIN_EMAIL,
        "env_var": "OWNER_EMAILS",
        "note": (
            "Owner addresses skip every paywall, module lock and mastery gate, "
            "on the course platform and the quiz apps alike. Edit the "
            "OWNER_EMAILS environment variable to change the list."
        ),
    }


# -----------------------------------------------------------------------------
# Analytics
# -----------------------------------------------------------------------------

@router.get("/stats")
def stats(
    product_code: str = "",
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Headline numbers plus per-module funnel — what the dashboard renders.

    The headline block lives in stats_queries.product_headline_stats so the
    per-course stats endpoint (routes/stats.py) reports identical numbers.
    """
    headline = product_headline_stats(db, product_code)

    modules_q = select(Module).order_by(Module.position)
    if product_code:
        modules_q = modules_q.where(Module.product_code == product_code)
    modules = db.execute(modules_q).scalars().all()

    funnel = []
    for module in modules:
        lessons = db.execute(
            select(Lesson).where(Lesson.module_id == module.id)
        ).scalars().all()
        lesson_ids = [l.id for l in lessons] or [0]

        started = db.execute(
            select(func.count(func.distinct(LessonProgress.learner_id))).where(
                LessonProgress.lesson_id.in_(lesson_ids)
            )
        ).scalar_one()
        attempts = db.execute(
            select(QuizAttempt).where(
                QuizAttempt.module_id == module.id,
                QuizAttempt.item_set == "formative",
            )
        ).scalars().all()
        passers = {a.learner_id for a in attempts if a.passed}
        scores = [a.score_pct for a in attempts]

        funnel.append(
            {
                "code": module.code,
                "title": module.title,
                "position": module.position,
                "learners_started": started,
                "quiz_attempts": len(attempts),
                "learners_passed": len(passers),
                "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            }
        )

    return {**headline, "modules": funnel}
