"""POST /api/register — create a pending registration lead.

Behavior:
  * Validates payload via Pydantic.
  * Honeypot trap: if `website` field is non-empty, return a fake success
    and do nothing. Bots won't know they failed.
  * Duplicate detection by (course_code, email): returns status='duplicate'
    with the current taken count and does NOT send another email. This
    makes the endpoint idempotent for accidental double-submits.
  * Cohort-full check: if paid seats already = capacity, reject.
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
from ..models import Registration
from ..schemas import RegisterIn, RegisterOut
from ..seats import count_paid

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["public"])


@router.post("/register", response_model=RegisterOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> RegisterOut:
    settings = get_settings()

    # Honeypot — silently drop bots.
    if payload.website.strip():
        log.info("Honeypot triggered; silently accepting bot submission.")
        return RegisterOut(
            taken=count_paid(db),
            capacity=settings.COURSE_CAPACITY,
            status="pending",
            registration_id=None,
        )

    taken = count_paid(db)
    if taken >= settings.COURSE_CAPACITY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cohort {settings.COHORT_LABEL} is full. "
                "Email info@proreadyengineer.com to join the waitlist."
            ),
        )

    email_normalized = payload.email.lower().strip()

    # Idempotency — if this email has already registered for this cohort,
    # surface the existing row rather than creating a second lead.
    existing = db.execute(
        select(Registration).where(
            Registration.course_code == settings.COURSE_CODE,
            Registration.email == email_normalized,
        )
    ).scalar_one_or_none()

    if existing is not None:
        return RegisterOut(
            taken=taken,
            capacity=settings.COURSE_CAPACITY,
            status="duplicate",
            registration_id=existing.id,
        )

    reg = Registration(
        course_code=settings.COURSE_CODE,
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

    # Confirmation email to applicant.
    send_email(
        to=reg.email,
        subject=f"Registration received — Gas Turbine Emissions Mapping ({settings.COHORT_LABEL})",
        html=applicant_confirmation_html(
            full_name=reg.full_name,
            cohort=settings.COHORT_LABEL,
            price_display=settings.COURSE_PRICE_DISPLAY,
            payment_instructions=settings.PAYMENT_INSTRUCTIONS,
        ),
    )

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
                    "Status": reg.status,
                    "Registration ID": str(reg.id),
                },
                taken_after=taken,
                capacity=settings.COURSE_CAPACITY,
            ),
        )

    return RegisterOut(
        taken=taken,
        capacity=settings.COURSE_CAPACITY,
        status="pending",
        registration_id=reg.id,
    )
