"""POST /api/register — create a pending registration lead.

Behavior:
  * Validates payload via Pydantic.
  * Honeypot trap: if `website` field is non-empty, return a fake success
    and do nothing. Bots won't know they failed.
  * Course lookup: resolves payload.course_code (or settings.COURSE_CODE as
    fallback) to a Course row. 404 if missing, 409 if status != 'open'.
  * Duplicate detection by (course_code, email): returns status='duplicate'
    with the current taken count and does NOT send another email.
  * Cohort-full check: if paid seats already = course.total_seats, reject.
  * On success: row inserted with status='pending', confirmation email sent
    to applicant, internal notification sent to ADMIN_NOTIFY_EMAIL.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..emailer import (
    admin_notification_html,
    applicant_confirmation_html,
    send_email,
)
from ..models import Course, Registration
from ..schemas import RegisterIn, RegisterOut
from ..seats import count_active

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["public"])


@router.post("/register", response_model=RegisterOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> RegisterOut:
    settings = get_settings()
    course_code = (payload.course_code or settings.COURSE_CODE).strip()

    # Honeypot — silently drop bots. Use course.total_seats if we can,
    # otherwise fall back to config default so the fake response looks
    # plausible.
    if payload.website.strip():
        log.info("Honeypot triggered; silently accepting bot submission.")
        capacity = settings.COURSE_CAPACITY
        course = db.execute(
            select(Course).where(Course.code == course_code)
        ).scalar_one_or_none()
        if course is not None:
            capacity = course.total_seats
        return RegisterOut(
            taken=count_active(db, course_code),
            capacity=capacity,
            status="pending",
            registration_id=None,
        )

    course = db.execute(
        select(Course).where(Course.code == course_code)
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course '{course_code}' not found.",
        )
    if course.status != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration for this course is closed.",
        )

    # Capacity gate counts ACTIVE rows (paid + pending) — a registration
    # takes a seat from the moment it lands. This matches what the public
    # counter shows.
    taken = count_active(db, course_code)
    if taken >= course.total_seats:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{course.title} is full. "
                "Email info@proreadyengineer.com to join the waitlist."
            ),
        )

    email_normalized = payload.email.lower().strip()

    # Idempotency — if this email has already registered for this cohort,
    # surface the existing row rather than creating a second lead.
    existing = db.execute(
        select(Registration).where(
            Registration.course_code == course_code,
            Registration.email == email_normalized,
        )
    ).scalar_one_or_none()

    if existing is not None:
        return RegisterOut(
            taken=count_active(db, course_code),
            capacity=course.total_seats,
            status="duplicate",
            registration_id=existing.id,
        )

    reg = Registration(
        course_code=course_code,
        full_name=payload.full_name.strip(),
        email=email_normalized,
        job_title=payload.job_title.strip(),
        company=payload.company.strip(),
        years_experience=payload.years_experience.strip(),
        location=payload.location.strip(),
        status="pending",
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)

    # Cohort label for the confirmation email: use the course's real start
    # date when available; otherwise fall back to the configured label.
    cohort_label = course.start_date.strftime("%B %-d, %Y") if course.start_date else settings.COHORT_LABEL

    # Confirmation email to applicant.
    send_email(
        to=reg.email,
        subject=f"Registration received — {course.title} ({cohort_label})",
        html=applicant_confirmation_html(
            full_name=reg.full_name,
            cohort=cohort_label,
            price_display=settings.COURSE_PRICE_DISPLAY,
            payment_instructions=settings.PAYMENT_INSTRUCTIONS,
        ),
    )

    # Recount after commit so both the admin email and the response
    # reflect the new row landing.
    taken_after = count_active(db, course_code)

    # Admin notification.
    if settings.ADMIN_NOTIFY_EMAIL:
        send_email(
            to=settings.ADMIN_NOTIFY_EMAIL,
            subject=f"[ProReady] New registration — {reg.full_name} ({reg.company})",
            html=admin_notification_html(
                reg={
                    "Name": reg.full_name,
                    "Email": reg.email,
                    "Job title": reg.job_title,
                    "Company": reg.company,
                    "Experience": reg.years_experience,
                    "Location": reg.location,
                    "Course": course.code,
                    "Status": reg.status,
                    "Registration ID": str(reg.id),
                },
                taken_after=taken_after,
                capacity=course.total_seats,
            ),
        )

    return RegisterOut(
        taken=taken_after,
        capacity=course.total_seats,
        status="pending",
        registration_id=reg.id,
    )
