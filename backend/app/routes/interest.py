"""Interest waitlist — public signup + admin summary/list/notify.

An "upcoming course" here is just a slug on the marketing site; there is
deliberately NO Course row behind it, so interest can be collected before
anything about the course exists.

Public:
  POST /api/interest                              — leave your email for a slug

Admin (protected):
  GET    /api/admin/interest/summary              — per-slug counts, biggest first
  GET    /api/admin/interest?course_slug=         — signups (all slugs when omitted)
  DELETE /api/admin/interest/{interest_id}        — remove one row (spam cleanup)
  POST   /api/admin/interest/{course_slug}/notify — broadcast to one waitlist
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import support_service as svc
from ..db import get_db
from ..deps import require_admin
from ..emailer import broadcast_html, send_broadcast
from ..models import CourseInterest
from ..schemas import (
    InterestIn,
    InterestNotifyIn,
    InterestOut,
    InterestRowOut,
    InterestSummaryOut,
    NotifyOut,
)

log = logging.getLogger(__name__)


def summary_rows(db: Session) -> List[InterestSummaryOut]:
    """Per-slug signup counts, biggest waitlist first. Shared by the admin
    endpoint and the AI assistant's get_interest_summary tool."""
    rows = db.execute(
        select(
            CourseInterest.course_slug,
            func.count(CourseInterest.id),
            func.max(CourseInterest.created_at),
        )
        .group_by(CourseInterest.course_slug)
        .order_by(func.count(CourseInterest.id).desc(), CourseInterest.course_slug.asc())
    ).all()
    return [
        InterestSummaryOut(course_slug=slug, count=int(n), latest_at=latest)
        for slug, n, latest in rows
    ]


# ----- Public router ---------------------------------------------------------

public_router = APIRouter(prefix="/api", tags=["public"])


@public_router.post("/interest", response_model=InterestOut)
def register_interest(
    payload: InterestIn, db: Session = Depends(get_db)
) -> InterestOut:
    # Honeypot — same silent-accept as /api/register: bots must not learn
    # they were detected.
    if payload.website.strip():
        log.info("Interest honeypot triggered; silently accepting bot submission.")
        return InterestOut()

    email = payload.email.lower().strip()

    existing = db.execute(
        select(CourseInterest).where(
            CourseInterest.course_slug == payload.course_slug,
            CourseInterest.email == email,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return InterestOut(already=True)

    db.add(
        CourseInterest(
            course_slug=payload.course_slug,
            email=email,
            full_name=payload.full_name.strip(),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # A concurrent double-submit lost the race to the unique index —
        # same outcome as the dedupe branch above.
        db.rollback()
        return InterestOut(already=True)
    return InterestOut()


# ----- Admin router ----------------------------------------------------------

admin_router = APIRouter(
    prefix="/api/admin/interest",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("/summary", response_model=List[InterestSummaryOut])
def interest_summary(db: Session = Depends(get_db)) -> List[InterestSummaryOut]:
    return summary_rows(db)


@admin_router.get("", response_model=List[InterestRowOut])
def list_interest(
    course_slug: Optional[str] = None, db: Session = Depends(get_db)
) -> List[CourseInterest]:
    stmt = select(CourseInterest).order_by(
        CourseInterest.created_at.desc(), CourseInterest.id.desc()
    )
    if course_slug:
        stmt = stmt.where(CourseInterest.course_slug == course_slug)
    return list(db.execute(stmt).scalars().all())


@admin_router.delete("/{interest_id}")
def delete_interest(interest_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CourseInterest, interest_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interest signup not found.",
        )
    db.delete(row)
    db.commit()
    return {"ok": True}


@admin_router.post("/{course_slug}/notify", response_model=NotifyOut)
def notify_interest(
    course_slug: str, body: InterestNotifyIn, db: Session = Depends(get_db)
) -> NotifyOut:
    emails = [
        e
        for (e,) in db.execute(
            select(CourseInterest.email)
            .where(CourseInterest.course_slug == course_slug)
            .order_by(CourseInterest.created_at.asc(), CourseInterest.id.asc())
        ).all()
    ]
    recipients = list(dict.fromkeys(emails))

    # No Course row exists for an upcoming course, so the email heading is
    # derived from the slug ("dle-combustion-mapping" -> "Dle Combustion
    # Mapping"). The admin-authored subject + body carry the real message.
    title = course_slug.replace("-", " ").title()
    html = broadcast_html(course_title=title, body_html=body.body_html)

    sent, failed = send_broadcast(
        db,
        recipients,
        subject=body.subject,
        html_builder=lambda _to: html,
        scope={
            "scope_kind": "interest",
            "scope_code": course_slug,
            "audience": "waitlist",
            "template": "broadcast",
        },
        # Same routing as course broadcasts: replies land on the support
        # desk, where they can be counted, not in a personal inbox.
        reply_to=svc.SUPPORT_ADDRESS,
    )

    return NotifyOut(
        ok=True,
        recipients=sent,
        failures=len(failed),
        failed_addresses=failed,
    )
