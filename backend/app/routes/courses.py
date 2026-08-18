"""Courses endpoints — public lookup + admin CRUD + admin broadcast.

Public:
  GET  /api/courses/{code}                  — start_date + seats_remaining for a course page

Admin (protected):
  GET    /api/admin/courses                 — list all courses
  POST   /api/admin/courses                 — create course
  GET    /api/admin/courses/{code}          — single course detail
  PATCH  /api/admin/courses/{code}          — update title/start_date/total_seats/status.
                                              Auto-notifies registrants if start_date changed.
  POST   /api/admin/courses/{code}/notify   — broadcast email to registrants
  GET    /api/admin/courses/{code}/registrations — registrations scoped to this course
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import support_service as svc
from ..db import get_db
from ..deps import require_admin
from ..emailer import (
    broadcast_html,
    send_broadcast,
    start_date_updated_html,
)
from ..models import Course, Product, Registration
from ..stats_queries import active_enrollee_emails
from ..schemas import (
    AdminRegistrationOut,
    CourseCreateIn,
    CourseOut,
    CoursePatchIn,
    NotifyIn,
    NotifyOut,
)

log = logging.getLogger(__name__)


# ----- Helpers --------------------------------------------------------------

def _parse_day_dates(raw) -> List[date]:
    """Convert the JSON-stored day_dates (list of ISO strings) to date objects.

    The column is JSON-typed; whatever shape the DB returns we accept a list of
    ISO 'YYYY-MM-DD' strings and parse them. Empty/None becomes an empty list.
    """
    if not raw:
        return []
    out: List[date] = []
    for item in raw:
        if isinstance(item, date):
            out.append(item)
        else:
            try:
                out.append(date.fromisoformat(str(item)))
            except ValueError:
                # Skip a corrupted entry rather than 500 the whole endpoint.
                log.warning("Skipping unparseable day_dates entry: %r", item)
    return out


def _to_out(course: Course, db: Session) -> CourseOut:
    """Compute seat counts and return the response model.

    seats_taken = active (paid + pending) — the public counter.
    seats_paid  = paid only — admin UI uses this for the paid/pending split.
    """
    counts = dict(
        db.execute(
            select(Registration.status, func.count(Registration.id)).where(
                Registration.course_code == course.code,
            ).group_by(Registration.status)
        ).all()
    )
    paid = int(counts.get("paid", 0))
    pending = int(counts.get("pending", 0))
    active = paid + pending
    return CourseOut(
        code=course.code,
        title=course.title,
        start_date=course.start_date,
        total_seats=course.total_seats,
        status=course.status,  # type: ignore[arg-type]
        day_dates=_parse_day_dates(course.day_dates),
        seats_taken=active,
        seats_paid=paid,
        seats_remaining=max(course.total_seats - active, 0),
        price_cents=course.price_cents,
        currency=course.currency,
        recorded_product_code=course.recorded_product_code,
    )


def _get_or_404(db: Session, code: str) -> Course:
    course = db.execute(
        select(Course).where(Course.code == code)
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
    return course


def _recipients_for(db: Session, course: Course, audience: str) -> list[str]:
    """Resolve a notify audience to a deduped list of email addresses.

    Live audiences ('all' | 'paid' | 'pending') read the registrations
    table; 'recorded' reads the active enrollees of the linked academy
    product (course.recorded_product_code — empty link means an empty
    audience, not an error); 'everyone' unions live 'all' with 'recorded'.
    Dedup keeps first-seen order so batch chunks stay deterministic, and
    matters because one person can be both a live registrant and a
    recorded buyer.
    """

    def live(statuses: tuple[str, ...]) -> list[str]:
        stmt = select(Registration.email).where(
            Registration.course_code == course.code,
            Registration.status.in_(statuses),
        )
        return [email for (email,) in db.execute(stmt).all()]

    if audience == "paid":
        emails = live(("paid",))
    elif audience == "pending":
        emails = live(("pending",))
    elif audience == "recorded":
        emails = active_enrollee_emails(db, course.recorded_product_code)
    elif audience == "everyone":
        emails = live(("paid", "pending")) + active_enrollee_emails(
            db, course.recorded_product_code
        )
    else:  # 'all' — live registrants, excluding cancelled
        emails = live(("paid", "pending"))
    return list(dict.fromkeys(emails))


# ----- Public router ---------------------------------------------------------

public_router = APIRouter(prefix="/api/courses", tags=["public"])


@public_router.get("/{code}", response_model=CourseOut)
def get_course_public(code: str, db: Session = Depends(get_db)) -> CourseOut:
    course = _get_or_404(db, code)
    return _to_out(course, db)


# ----- Admin router ----------------------------------------------------------

admin_router = APIRouter(
    prefix="/api/admin/courses",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("", response_model=List[CourseOut])
def list_courses(db: Session = Depends(get_db)) -> List[CourseOut]:
    courses = list(
        db.execute(select(Course).order_by(Course.start_date.asc())).scalars().all()
    )
    return [_to_out(c, db) for c in courses]


@admin_router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(body: CourseCreateIn, db: Session = Depends(get_db)) -> CourseOut:
    existing = db.execute(
        select(Course).where(Course.code == body.code)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Course code '{body.code}' already exists.",
        )
    course = Course(
        code=body.code,
        title=body.title,
        start_date=body.start_date,
        total_seats=body.total_seats,
        status=body.status,
        day_dates=[d.isoformat() for d in body.day_dates],
        price_cents=body.price_cents,
        currency=body.currency.lower(),
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return _to_out(course, db)


@admin_router.get("/{code}", response_model=CourseOut)
def get_course_admin(code: str, db: Session = Depends(get_db)) -> CourseOut:
    course = _get_or_404(db, code)
    return _to_out(course, db)


@admin_router.patch("/{code}", response_model=CourseOut)
def patch_course(
    code: str, body: CoursePatchIn, db: Session = Depends(get_db)
) -> CourseOut:
    course = _get_or_404(db, code)

    old_start = course.start_date
    changed_start = False

    if body.title is not None:
        course.title = body.title
    if body.total_seats is not None:
        course.total_seats = body.total_seats
    if body.status is not None:
        course.status = body.status
    if body.start_date is not None and body.start_date != course.start_date:
        course.start_date = body.start_date
        changed_start = True
    if body.day_dates is not None:
        # Replace the full list. Store as ISO strings so JSON is portable.
        course.day_dates = [d.isoformat() for d in body.day_dates]
    if body.price_cents is not None:
        course.price_cents = body.price_cents
    if body.currency is not None:
        course.currency = body.currency.lower()
    if "recorded_product_code" in body.model_fields_set:
        # Explicit null clears the link; omitting the field leaves it alone.
        if body.recorded_product_code:
            product = db.get(Product, body.recorded_product_code)
            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Academy product '{body.recorded_product_code}' not found."
                    ),
                )
        course.recorded_product_code = body.recorded_product_code or None

    db.commit()
    db.refresh(course)

    # Auto-notify on start-date change (user chose "yes" in scoping).
    if changed_start:
        recipients = _recipients_for(db, course, "all")
        html = start_date_updated_html(
            course_title=course.title,
            old_start_date=old_start,
            new_start_date=course.start_date,
        )
        sent, failed = send_broadcast(
            db,
            recipients,
            subject=f"Updated start date — {course.title}",
            html_builder=lambda _to: html,
            scope={
                "scope_kind": "course",
                "scope_code": course.code,
                "audience": "all",
                "template": "start_date_updated",
            },
        )
        log.info(
            "start_date change for course=%s notified=%d failed=%d",
            course.code, sent, len(failed),
        )

    return _to_out(course, db)


@admin_router.post("/{code}/notify", response_model=NotifyOut)
def notify_course(
    code: str, body: NotifyIn, db: Session = Depends(get_db)
) -> NotifyOut:
    course = _get_or_404(db, code)
    recipients = _recipients_for(db, course, body.audience)
    html = broadcast_html(course_title=course.title, body_html=body.body_html)

    sent, failed = send_broadcast(
        db,
        recipients,
        subject=body.subject,
        html_builder=lambda _to: html,
        scope={
            "scope_kind": "course",
            "scope_code": course.code,
            "audience": body.audience,
            "template": "broadcast",
        },
        # Replies land on the support desk, not in a personal inbox. A
        # broadcast that asks registrants a question is worthless if the
        # answers cannot be counted, and "reply to confirm your seat" is
        # exactly the kind of broadcast this platform sends.
        reply_to=svc.SUPPORT_ADDRESS,
    )

    return NotifyOut(
        ok=True,
        recipients=sent,
        failures=len(failed),
        failed_addresses=failed,
    )


@admin_router.get("/{code}/registrations", response_model=List[AdminRegistrationOut])
def list_course_registrations(
    code: str, db: Session = Depends(get_db)
) -> List[Registration]:
    _get_or_404(db, code)  # existence check
    stmt = (
        select(Registration)
        .where(Registration.course_code == code)
        .order_by(Registration.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())
