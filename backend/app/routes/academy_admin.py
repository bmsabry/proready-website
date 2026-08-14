"""Admin API for the academy: learners, enrollments, content, analytics.

Auth reuses `require_admin`, so the existing session cookie and the bearer
token escape hatch both work unchanged. Every endpoint here is admin-only —
none of it is reachable with a learner session.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import academy as svc
from .. import provenance as prov
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..emailer import enrollment_granted_html, login_link_html, send_email
from ..learner_auth import issue_login_token
from ..models import (
    AssetBlob,
    AssetDelivery,
    AssetPing,
    Chapter,
    Enrollment,
    Learner,
    Lesson,
    LessonProgress,
    Module,
    ModuleGrant,
    Product,
    QuizAttempt,
    QuizItem,
    Slide,
    SlideImage,
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
    sequential_gate: bool | None = None
    total_hours: float | None = Field(default=None, ge=0)


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
        # Same write-on-read settlement enforcement as the access rule, so the
        # dashboard never shows a lapsed bank payment as live access.
        for r in rows:
            svc.settlement_ok(db, r)
        # The product filter keeps failed-settlement buyers visible: the
        # Buyers tab needs them to badge 'bank payment failed' for follow-up.
        if product_code and not any(
            r.product_code == product_code
            and (r.status == "active" or r.settlement_status == "failed")
            for r in rows
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
                        "settlement_status": r.settlement_status,
                        "settlement_deadline": r.settlement_deadline,
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


# -----------------------------------------------------------------------------
# Content management — create products/modules/lessons, load quiz banks,
# slide images and protected assets, all through the API so new course
# content never requires a code deploy (and never touches the public repo).
# -----------------------------------------------------------------------------

class ProductCreate(BaseModel):
    code: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9-]+$")
    title: str
    subtitle: str = ""
    summary: str = ""
    price_cents: int = Field(default=0, ge=0)
    currency: str = "usd"
    total_hours: float = Field(default=0.0, ge=0)
    status: str = "draft"
    sequential_gate: bool = True


@router.post("/products")
def create_product(
    body: ProductCreate, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    """Create a product, or update these fields on an existing code —
    idempotent so a content-load script can be re-run safely."""
    if body.status not in ("draft", "live"):
        raise HTTPException(status_code=400, detail="status must be draft or live.")
    product = db.get(Product, body.code)
    created = product is None
    if product is None:
        product = Product(code=body.code)
        db.add(product)
    for field in ("title", "subtitle", "summary", "price_cents", "currency",
                  "total_hours", "status", "sequential_gate"):
        setattr(product, field, getattr(body, field))
    db.commit()
    log.info("Admin %s product %s", "created" if created else "updated", body.code)
    return {"ok": True, "created": created, "code": product.code}


class ModuleUpsert(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    title: str
    summary: str = ""
    position: int = Field(default=0, ge=0)
    hours: float = Field(default=0.0, ge=0)
    objectives: list = []
    topics: list = []
    quiz_app_url: str = ""
    # Support modules (simulator, resource packs) sit outside the
    # sequential chain: always open when entitled, never a blocker.
    gate_exempt: bool = False


@router.post("/products/{code}/modules")
def upsert_module(
    code: str,
    body: ModuleUpsert,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    module = db.execute(
        select(Module).where(Module.product_code == code, Module.code == body.code)
    ).scalar_one_or_none()
    created = module is None
    if module is None:
        module = Module(product_code=code, code=body.code)
        db.add(module)
    for field in ("title", "summary", "position", "hours", "objectives",
                  "topics", "quiz_app_url", "gate_exempt"):
        setattr(module, field, getattr(body, field))
    db.commit()
    db.refresh(module)
    return {"ok": True, "created": created, "module_id": module.id, "code": module.code}


class LessonUpsert(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    title: str
    kind: str = "slides"
    position: int = Field(default=0, ge=0)
    duration_s: int = Field(default=0, ge=0)
    asset_path: str = ""
    body: str = ""
    is_preview: bool = False


@router.post("/modules/{module_id}/lessons")
def upsert_lesson(
    module_id: int,
    body: LessonUpsert,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    if body.kind not in ("video", "slides", "reading", "lab", "calculator", "quiz"):
        raise HTTPException(status_code=400, detail="Unknown lesson kind.")
    lesson = db.execute(
        select(Lesson).where(Lesson.module_id == module_id, Lesson.code == body.code)
    ).scalar_one_or_none()
    created = lesson is None
    if lesson is None:
        lesson = Lesson(module_id=module_id, code=body.code)
        db.add(lesson)
    for field in ("title", "kind", "position", "duration_s", "asset_path",
                  "body", "is_preview"):
        setattr(lesson, field, getattr(body, field))
    db.commit()
    db.refresh(lesson)
    return {"ok": True, "created": created, "lesson_id": lesson.id, "code": lesson.code}


class QuizItemIn(BaseModel):
    code: str
    item_set: str = "formative"
    kind: str = "mcq"
    stem: str
    options: list = []
    answer: dict = {}
    rubric: str = ""
    explanation: str = ""
    cognitive_level: str = ""
    outcome_id: str = ""
    position: int = 0


class QuizBankIn(BaseModel):
    items: list[QuizItemIn]
    # When true (default) the module's existing items in the same item_set(s)
    # are replaced wholesale — the safe way to re-run a content load.
    replace: bool = True


@router.post("/modules/{module_id}/quiz-items")
def load_quiz_items(
    module_id: int,
    body: QuizBankIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    if not body.items:
        raise HTTPException(status_code=400, detail="No items supplied.")
    sets = {i.item_set for i in body.items}
    bad = sets - {"formative", "summative"}
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown item_set: {bad}.")
    for item in body.items:
        if item.kind == "mcq":
            keys = {o.get("key") for o in item.options if isinstance(o, dict)}
            if item.answer.get("key") not in keys:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item {item.code}: answer key not among options.",
                )
    if body.replace:
        db.execute(
            delete(QuizItem).where(
                QuizItem.module_id == module_id, QuizItem.item_set.in_(sets)
            )
        )
    for item in body.items:
        db.add(QuizItem(module_id=module_id, **item.model_dump()))
    db.commit()
    n = db.execute(
        select(func.count(QuizItem.id)).where(QuizItem.module_id == module_id)
    ).scalar_one()
    log.info("Quiz bank loaded for module %s: %d items", module_id, n)
    return {"ok": True, "module_id": module_id, "items_total": n}


class SlideIn(BaseModel):
    number: int = Field(ge=1)
    title: str = ""
    section: str = ""
    text: str = ""
    appears_at_s: int = -1
    image_lg_b64: str = ""
    image_sm_b64: str = ""
    # AssetBlob key of a movie embedded on this slide (upload the bytes via
    # POST /assets first). Empty string clears/none.
    video_asset_key: str = ""


class SlideBatchIn(BaseModel):
    slides: list[SlideIn]


@router.post("/modules/{module_id}/slides")
def load_slides(
    module_id: int,
    body: SlideBatchIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """Upsert slide rows and their pixels. Batched — send ~10 slides per call
    so a request stays comfortably inside body-size limits."""
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    if not body.slides:
        raise HTTPException(status_code=400, detail="No slides supplied.")
    if len(body.slides) > 25:
        raise HTTPException(status_code=400, detail="Batch too large — send ≤25.")

    for s in body.slides:
        row = db.execute(
            select(Slide).where(Slide.module_id == module_id, Slide.number == s.number)
        ).scalar_one_or_none()
        if row is None:
            row = Slide(module_id=module_id, number=s.number)
            db.add(row)
        row.title = s.title
        row.section = s.section
        row.text = s.text
        row.appears_at_s = s.appears_at_s
        row.video_asset = s.video_asset_key
        for size, b64 in (("lg", s.image_lg_b64), ("sm", s.image_sm_b64)):
            if not b64:
                continue
            try:
                blob = base64.b64decode(b64, validate=True)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Slide {s.number} {size}: invalid base64.",
                )
            img = db.execute(
                select(SlideImage).where(
                    SlideImage.module_id == module_id,
                    SlideImage.number == s.number,
                    SlideImage.size == size,
                )
            ).scalar_one_or_none()
            if img is None:
                img = SlideImage(module_id=module_id, number=s.number, size=size)
                db.add(img)
            img.data = blob
            img.content_type = "image/png"
            # The learner endpoint is the only reader of these paths.
            setattr(row, f"image_{size}",
                    f"/api/academy/slide-image/{module_id}/{s.number}/{size}")
    db.commit()
    n = db.execute(
        select(func.count(Slide.id)).where(Slide.module_id == module_id)
    ).scalar_one()
    return {"ok": True, "module_id": module_id, "slides_total": n}


class AssetIn(BaseModel):
    key: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9._-]+$")
    filename: str = ""
    content_type: str = "text/html"
    data_b64: str


@router.post("/assets")
def upload_asset(
    body: AssetIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    """Store (or replace) a protected blob — the simulator, a lab, a handout.
    Lessons point at it with asset_path='blob:{key}'."""
    try:
        blob = base64.b64decode(body.data_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload.")
    if len(blob) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Asset exceeds the 25MB cap.")
    row = db.execute(
        select(AssetBlob).where(AssetBlob.key == body.key)
    ).scalar_one_or_none()
    created = row is None
    if row is None:
        row = AssetBlob(key=body.key)
        db.add(row)
    row.filename = body.filename
    row.content_type = body.content_type
    row.data = blob
    db.commit()
    log.info("Asset %s %s (%d bytes)", body.key,
             "created" if created else "replaced", len(blob))
    return {"ok": True, "created": created, "key": body.key, "bytes": len(blob)}


# -----------------------------------------------------------------------------
# Per-module (per-day / per-element) access control
# -----------------------------------------------------------------------------

class ModuleGrantIn(BaseModel):
    email: EmailStr
    module_id: int
    full_name: str = ""
    note: str = ""


@router.get("/products/{code}/access")
def access_matrix(
    code: str, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    """Everything the access panel needs in one call: the product's modules,
    and every learner who holds either a product enrollment or at least one
    module grant, with their per-module state."""
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    modules = db.execute(
        select(Module).where(Module.product_code == code).order_by(Module.position)
    ).scalars().all()
    module_ids = [m.id for m in modules]

    enrollments = db.execute(
        select(Enrollment).where(
            Enrollment.product_code == code, Enrollment.status == "active"
        )
    ).scalars().all()
    grants = db.execute(
        select(ModuleGrant).where(
            ModuleGrant.module_id.in_(module_ids or [0]),
            ModuleGrant.status == "active",
        )
    ).scalars().all()

    learner_ids = {e.learner_id for e in enrollments} | {g.learner_id for g in grants}
    learners = {
        l.id: l
        for l in db.execute(
            select(Learner).where(Learner.id.in_(learner_ids or [0]))
        ).scalars().all()
    }
    grants_by_learner: dict[int, set[int]] = {}
    for g in grants:
        grants_by_learner.setdefault(g.learner_id, set()).add(g.module_id)
    enrolled_ids = {e.learner_id for e in enrollments}

    rows = []
    for lid in sorted(learner_ids):
        learner = learners.get(lid)
        if learner is None:
            continue
        rows.append(
            {
                "learner_id": lid,
                "email": learner.email,
                "full_name": learner.full_name,
                "is_owner": svc.is_owner(learner),
                "enrolled_all": lid in enrolled_ids,
                "module_ids": sorted(grants_by_learner.get(lid, set())),
            }
        )
    return {
        "product": {"code": product.code, "title": product.title,
                    "sequential_gate": product.sequential_gate},
        "modules": [
            {"id": m.id, "code": m.code, "title": m.title, "position": m.position}
            for m in modules
        ],
        "learners": rows,
    }


@router.post("/grant-module")
def grant_module(
    body: ModuleGrantIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)
) -> dict:
    module = db.get(Module, body.module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    learner = svc.upsert_learner(db, str(body.email), body.full_name)
    svc.grant_module(db, learner, module, source="manual",
                     note=body.note or f"granted by admin")
    log.info("Admin %s granted module %s to %s", admin, module.code, learner.email)
    return {"ok": True, "email": learner.email, "module_id": module.id,
            "module_code": module.code}


@router.post("/revoke-module")
def revoke_module(
    body: ModuleGrantIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)
) -> dict:
    module = db.get(Module, body.module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    learner = db.execute(
        select(Learner).where(Learner.email == str(body.email).lower().strip())
    ).scalar_one_or_none()
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found.")
    changed = svc.revoke_module(db, learner, module)
    log.info("Admin %s revoked module %s from %s (changed=%s)",
             admin, module.code, learner.email, changed)
    return {"ok": True, "changed": changed}


# -----------------------------------------------------------------------------
# Integrity — who has copies, and which copies have gone walkabout
# -----------------------------------------------------------------------------

class TraceIn(BaseModel):
    # A whole pasted file, a fragment of one, or just the id. Big enough for
    # the full stamped simulator; anything larger is trimmed client-side.
    content: str = Field(min_length=4, max_length=4_000_000)


def _delivery_out(db: Session, d: AssetDelivery) -> dict:
    learner = db.get(Learner, d.learner_id)
    return {
        "token": d.token,
        "learner_id": d.learner_id,
        "email": d.learner_email or (learner.email if learner else ""),
        "full_name": (learner.full_name if learner else ""),
        "product_code": d.product_code,
        "module_id": d.module_id,
        "lesson_id": d.lesson_id,
        "asset_key": d.asset_key,
        "served_at": d.served_at.isoformat() if d.served_at else None,
        "ip": d.ip,
        "user_agent": d.user_agent,
        "bytes_sent": d.bytes_sent,
        "ping_count": d.ping_count or 0,
        "worst_status": d.worst_status or "",
    }


def _ping_out(p: AssetPing) -> dict:
    return {
        "id": p.id,
        "token": p.token,
        "status": p.status,
        "seen_at": p.seen_at.isoformat() if p.seen_at else None,
        "page_url": p.page_url,
        "origin": p.origin,
        "referrer": p.referrer,
        "ip": p.ip,
        "user_agent": p.user_agent,
        "screen": p.screen,
        "timezone": p.timezone,
        "session_email": p.session_email,
    }


@router.post("/integrity/trace")
def integrity_trace(
    body: TraceIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """"Somebody sent me this file — who leaked it?"

    Paste the file. Every copy carries a per-download id in four different
    places (an HTML comment, invisible characters inside the licence line, a
    data attribute, and the beacon script), so the id survives casual
    tampering; whichever carrier is intact answers the question.

    Returns the matching download(s): the account, the minute, the IP, the
    browser, and every time that copy has since been opened.
    """
    tokens = prov.extract_tokens(body.content)
    matches, unknown = [], []
    for token in tokens[:20]:
        delivery = db.execute(
            select(AssetDelivery).where(AssetDelivery.token == token)
        ).scalar_one_or_none()
        if delivery is None:
            unknown.append(token)
            continue
        pings = db.execute(
            select(AssetPing)
            .where(AssetPing.token == token)
            .order_by(AssetPing.seen_at.desc())
            .limit(50)
        ).scalars().all()
        sibling_count = db.execute(
            select(func.count(AssetDelivery.id))
            .where(AssetDelivery.learner_id == delivery.learner_id)
        ).scalar_one()
        matches.append({
            **_delivery_out(db, delivery),
            "pings": [_ping_out(p) for p in pings],
            "downloads_by_this_account": sibling_count,
        })

    return {
        "tokens_found": tokens,
        "matches": matches,
        "unknown_tokens": unknown,
        "verdict": (
            "traced" if matches
            else "no-id-found" if not tokens
            else "id-not-issued-by-us"
        ),
    }


@router.get("/integrity")
def integrity_report(
    product_code: str = "",
    days: int = 180,
    include_reviewed: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    """"Has anything leaked that I don't know about?"

    Three lists, worst first:

      alerts   — copies that called home from somewhere they should not be:
                 a hard drive or another website (`offsite`), a different
                 signed-in account (`other_account`), or an id we never
                 issued (`unknown_token`). These are the ones to act on.
      watch    — accounts whose behaviour is unusual: many downloads, or the
                 same account appearing from several IP addresses. Not proof
                 of anything; a prompt to look.
      recent   — the plain download log, newest first.
    """
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))

    dq = select(AssetDelivery).where(AssetDelivery.served_at >= since)
    if product_code:
        dq = dq.where(AssetDelivery.product_code == product_code)
    deliveries = db.execute(
        dq.order_by(AssetDelivery.served_at.desc()).limit(500)
    ).scalars().all()
    by_token = {d.token: d for d in deliveries}

    aq = (
        select(AssetPing)
        .where(AssetPing.seen_at >= since)
        .where(AssetPing.status.in_(list(prov.ALERT_STATUSES)))
    )
    if not include_reviewed:
        aq = aq.where(AssetPing.reviewed_at.is_(None))
    alerts = db.execute(
        aq.order_by(AssetPing.seen_at.desc()).limit(200)
    ).scalars().all()

    alert_rows = []
    for p in alerts:
        d = by_token.get(p.token) or db.execute(
            select(AssetDelivery).where(AssetDelivery.token == p.token)
        ).scalar_one_or_none()
        if product_code and d is not None and d.product_code != product_code:
            continue
        alert_rows.append({
            **_ping_out(p),
            "issued_to": d.learner_email if d else "",
            "issued_at": d.served_at.isoformat() if d and d.served_at else None,
            "issued_ip": d.ip if d else "",
            "asset_key": d.asset_key if d else "",
            "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        })

    # Behavioural watch list. Deliberately simple and explainable — an admin
    # has to be able to say why a name is on it.
    watch: dict[int, dict] = {}
    for d in deliveries:
        row = watch.setdefault(d.learner_id, {
            "learner_id": d.learner_id, "email": d.learner_email,
            "downloads": 0, "ips": set(), "user_agents": set(),
            "last_at": None, "alerts": 0,
        })
        row["downloads"] += 1
        if d.ip:
            row["ips"].add(d.ip)
        if d.user_agent:
            row["user_agents"].add(d.user_agent[:120])
        if d.worst_status in prov.ALERT_STATUSES:
            row["alerts"] += 1
        stamp = d.served_at.isoformat() if d.served_at else None
        if stamp and (row["last_at"] is None or stamp > row["last_at"]):
            row["last_at"] = stamp

    watch_rows = []
    for row in watch.values():
        ips, uas = len(row["ips"]), len(row["user_agents"])
        reasons = []
        if row["alerts"]:
            reasons.append(f"{row['alerts']} copy(ies) opened off-site")
        if ips >= 4:
            reasons.append(f"{ips} different IP addresses")
        if uas >= 4:
            reasons.append(f"{uas} different browsers/devices")
        if row["downloads"] >= 25:
            reasons.append(f"{row['downloads']} downloads")
        if not reasons:
            continue
        watch_rows.append({
            "learner_id": row["learner_id"], "email": row["email"],
            "downloads": row["downloads"], "distinct_ips": ips,
            "distinct_agents": uas, "alerts": row["alerts"],
            "last_at": row["last_at"], "reasons": reasons,
        })
    watch_rows.sort(key=lambda r: (r["alerts"], r["distinct_ips"],
                                   r["downloads"]), reverse=True)

    return {
        "since": since.isoformat(),
        "product_code": product_code,
        "totals": {
            "downloads": len(deliveries),
            "accounts": len(watch),
            "alerts": len(alert_rows),
        },
        "alerts": alert_rows,
        "watch": watch_rows[:50],
        "recent": [_delivery_out(db, d) for d in deliveries[:100]],
    }


class DismissIn(BaseModel):
    ping_ids: list[int] = Field(min_length=1, max_length=200)
    note: str = ""


@router.post("/integrity/dismiss")
def integrity_dismiss(
    body: DismissIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Mark alerts as looked at.

    The alert list is an inbox: an item you have investigated should stop
    shouting, or the list stops being read at all. Reviewing never deletes
    the ping — the evidence outlives the admin's attention, and
    `include_reviewed=true` brings the whole history back.
    """
    rows = db.execute(
        select(AssetPing).where(AssetPing.id.in_(body.ping_ids))
    ).scalars().all()
    stamp = datetime.now(timezone.utc)
    for row in rows:
        row.reviewed_at = stamp
        row.reviewed_note = (body.note or f"reviewed by {admin}")[:300]
    db.commit()
    return {"ok": True, "reviewed": len(rows)}
