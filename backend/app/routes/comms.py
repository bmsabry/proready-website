"""Admin comms — the outbound email log + academy-product broadcasts.

Endpoints (all admin-only):
  GET  /api/admin/comms/log              — newest-first EmailLog rows: search,
                                            "to customers / to me", problems
  GET  /api/admin/comms/log/{id}         — one email in full: headers, the
                                            copy of what was sent, delivery
  POST /api/admin/comms/keep-copies      — fetch and keep copies of recent
                                            emails from Resend (30-day window)
  POST /api/admin/products/{code}/notify — broadcast to a product's active
                                            enrollees (audience 'buyers')

Course broadcasts live in routes/courses.py; this module covers everything
comms-related that isn't tied to a cohort.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import email_copies as copies
from ..db import SessionLocal, get_db
from ..deps import require_admin
from .. import support_service as svc
from ..emailer import broadcast_html, send_broadcast
from ..models import Course, EmailLog, Learner, Product
from ..schemas import NotifyOut
from ..stats_queries import active_enrollee_emails

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class ProductNotifyIn(BaseModel):
    """Same shape as a course notify, minus the audience — a product
    broadcast always targets its active buyers."""

    subject: str = Field(min_length=1, max_length=200)
    body_html: str = Field(min_length=1, max_length=100_000)


def _titles(db: Session) -> tuple[dict[str, str], dict[str, str]]:
    courses = {c: t for c, t in db.execute(select(Course.code, Course.title)).all()}
    products = {c: t for c, t in db.execute(select(Product.code, Product.title)).all()}
    return courses, products


def _about(r: EmailLog, courses: dict[str, str], products: dict[str, str]) -> dict:
    """What the email was about, in words, and where that lives in admin."""
    code = r.scope_code or ""
    if r.scope_kind == "support" and code:
        return {"label": f"Support ticket #{code}", "href": f"#support/{code}"}
    if r.scope_kind == "course" and code:
        label = courses.get(code) or code
        try:  # session reminders carry the session's date as their audience
            day = date.fromisoformat(r.audience)
            label += f" · session of {day.strftime('%b')} {day.day}"
        except (TypeError, ValueError):
            pass
        return {"label": label, "href": f"#courses/{code}"}
    if r.scope_kind == "product" and code:
        return {"label": products.get(code) or courses.get(code) or code, "href": "#academy"}
    if r.scope_kind == "integrity":
        return {"label": "Account integrity", "href": "#students"}
    if r.scope_kind == "interest":
        return {"label": "Course interest list", "href": ""}
    return {"label": code, "href": ""}


def _row(r: EmailLog, courses: dict, products: dict, admins: set[str]) -> dict:
    return {
        "id": r.id,
        "ts": r.ts.isoformat() if r.ts else "",
        "scope_kind": r.scope_kind,
        "scope_code": r.scope_code,
        "audience": r.audience,
        "template": r.template,
        "subject": r.subject,
        "recipient": r.recipient,
        "ok": r.ok,
        "provider_id": r.provider_id,
        "kind_label": copies.kind_label(r.template),
        "to_me": copies.to_admin(r, admins),
        "about": _about(r, courses, products),
        "delivery": copies.delivery_info(r),
        "has_copy": bool(r.body_html or r.body_text),
    }


@router.get("/comms/log")
def comms_log(
    scope_code: str = "",
    q: str = "",
    who: str = "all",
    problems: bool = False,
    limit: int = 200,
    before_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Newest-first outbound email log.

    q      — matches the recipient, the subject or the scope code
    who    — 'customers' (not to Bassam) | 'me' (alerts to Bassam) | 'all'
    problems — only emails that failed, bounced, were suppressed or were
               marked as spam
    before_id — for "show older": rows older than this id
    """
    limit = max(1, min(limit, 1000))
    stmt = select(EmailLog)
    if scope_code:
        stmt = stmt.where(EmailLog.scope_code == scope_code)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(EmailLog.recipient).like(like),
                func.lower(EmailLog.subject).like(like),
                func.lower(EmailLog.scope_code).like(like),
            )
        )
    admins = copies.admin_addresses()
    mine = or_(EmailLog.audience == "admin", func.lower(EmailLog.recipient).in_(admins))
    if who == "me":
        stmt = stmt.where(mine)
    elif who == "customers":
        stmt = stmt.where(~mine)
    if problems:
        stmt = stmt.where(
            or_(EmailLog.ok.is_(False), EmailLog.delivery.in_(copies.PROBLEM_DELIVERY))
        )
    if before_id:
        stmt = stmt.where(EmailLog.id < before_id)
    # id desc as tiebreak: batch sends share one timestamp second.
    stmt = stmt.order_by(EmailLog.ts.desc(), EmailLog.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    courses, products = _titles(db)
    return {
        "rows": [_row(r, courses, products, admins) for r in rows],
        "count": len(rows),
        "has_more": len(rows) == limit,
    }


@router.get("/comms/log/{email_id}")
def comms_email(email_id: int, db: Session = Depends(get_db)) -> dict:
    """One email in full, as the recipient got it.

    The copy comes from our own log, or — for emails sent before copies
    were kept — from Resend, which then gets kept here too. Resend is also
    asked what happened to it (delivered, bounced, opened…) each time it is
    opened, so the status shown is current.
    """
    r = db.get(EmailLog, email_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Email not found.")
    # Resend only knows about its last 30 days; asking about older emails
    # would only cost a round trip.
    sent_at = copies._aware(r.ts)
    recent = sent_at is None or datetime.now(timezone.utc) - sent_at <= copies.RESEND_KEEPS + timedelta(days=1)
    lookup_error = copies.refresh(db, r) if (r.provider_id and recent) else ""
    courses, products = _titles(db)
    learner = db.execute(
        select(Learner.id, Learner.full_name).where(func.lower(Learner.email) == (r.recipient or "").lower())
    ).first()

    has_copy = bool(r.body_html or r.body_text)
    if has_copy:
        note = ""
    elif not r.provider_id:
        note = (
            "No copy of this email exists: it was never accepted for sending, and it was "
            "sent before the website started keeping copies."
        )
    else:
        note = (
            "The content of this email is no longer available. It was sent before the website "
            "started keeping copies (September 28, 2026), and Resend deletes its own copies "
            "after 30 days."
        )
        if r.scope_kind == "support":
            note += " The support ticket still has the message text."
    return {
        **_row(r, courses, products, copies.admin_addresses()),
        "from_addr": r.from_addr,
        "reply_to": r.reply_to,
        "cc": r.cc,
        "bcc": r.bcc,
        "attachments": [a.strip() for a in (r.attachments or "").split(",") if a.strip()],
        "error": r.error,
        "html": r.body_html,
        "text": r.body_text,
        "copy": {"available": has_copy, "source": r.copy_source, "note": note},
        "lookup_error": lookup_error,
        "learner": {"id": learner[0], "name": learner[1] or ""} if learner else None,
    }


def _keep_copies_later() -> None:
    db = SessionLocal()
    try:
        copies.backfill(db)
    finally:
        db.close()


@router.post("/comms/keep-copies")
def keep_copies(background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    """Fetch and keep a copy of every recent email that has none yet.

    Resend deletes its copies after 30 days; this saves the ones it still
    has, in the background (about two a second, Resend's rate limit).
    """
    waiting = db.execute(
        select(func.count(EmailLog.id)).where(
            EmailLog.provider_id != "",
            EmailLog.body_html == "",
            EmailLog.body_text == "",
            EmailLog.copy_source != "gone",
        )
    ).scalar() or 0
    background.add_task(_keep_copies_later)
    return {"ok": True, "queued": int(waiting), "started_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/products/{code}/notify", response_model=NotifyOut)
def notify_product(
    code: str, body: ProductNotifyIn, db: Session = Depends(get_db)
) -> NotifyOut:
    """Broadcast to everyone holding live access to an academy product."""
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found."
        )
    recipients = active_enrollee_emails(db, code)
    html = broadcast_html(course_title=product.title, body_html=body.body_html)

    sent, failed = send_broadcast(
        db,
        recipients,
        subject=body.subject,
        html_builder=lambda _to: html,
        scope={
            "scope_kind": "product",
            "scope_code": code,
            "audience": "buyers",
            "template": "broadcast",
        },
        reply_to=svc.SUPPORT_ADDRESS,
    )

    return NotifyOut(
        ok=True,
        recipients=sent,
        failures=len(failed),
        failed_addresses=failed,
    )
