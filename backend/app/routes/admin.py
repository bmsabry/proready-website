"""Admin endpoints, protected by bearer token.

Endpoints:
  GET  /api/admin/registrations    — list all rows (most recent first)
  POST /api/admin/mark-paid        — flip a pending row to paid
  POST /api/admin/cancel           — flip a row to cancelled (release seat if paid)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..models import Course, Registration
from ..schemas import (
    AdminRegistrationOut,
    MarkPaidIn,
    MarkPaidOut,
)
from ..seats import count_paid

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/registrations", response_model=List[AdminRegistrationOut])
def list_registrations(db: Session = Depends(get_db)) -> List[Registration]:
    settings = get_settings()
    stmt = (
        select(Registration)
        .where(Registration.course_code == settings.COURSE_CODE)
        .order_by(Registration.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


@router.post("/mark-paid", response_model=MarkPaidOut)
def mark_paid(body: MarkPaidIn, db: Session = Depends(get_db)) -> MarkPaidOut:
    settings = get_settings()
    reg = db.get(Registration, body.registration_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if reg.course_code != settings.COURSE_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration belongs to a different cohort.",
        )

    if reg.status == "paid":
        # Idempotent — don't double-write paid_at.
        return MarkPaidOut(
            ok=True,
            taken=count_paid(db),
            registration=AdminRegistrationOut.model_validate(reg),
        )

    # Capacity guard — read live seat cap from the Course row so admin
    # edits to total_seats are respected. Fall back to env default if the
    # Course row is missing for some reason.
    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    capacity = course.total_seats if course is not None else settings.COURSE_CAPACITY
    if count_paid(db) >= capacity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cohort already at capacity — cannot mark another row paid.",
        )

    reg.status = "paid"
    reg.paid_at = datetime.now(timezone.utc)
    if body.notes is not None:
        reg.admin_notes = body.notes
    db.commit()
    db.refresh(reg)

    return MarkPaidOut(
        ok=True,
        taken=count_paid(db),
        registration=AdminRegistrationOut.model_validate(reg),
    )


class CancelIn(MarkPaidIn):
    pass  # same shape — registration_id + optional notes


@router.post("/cancel", response_model=MarkPaidOut)
def cancel(body: CancelIn, db: Session = Depends(get_db)) -> MarkPaidOut:
    settings = get_settings()
    reg = db.get(Registration, body.registration_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if reg.course_code != settings.COURSE_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration belongs to a different cohort.",
        )

    reg.status = "cancelled"
    reg.paid_at = None
    if body.notes is not None:
        reg.admin_notes = body.notes
    db.commit()
    db.refresh(reg)

    return MarkPaidOut(
        ok=True,
        taken=count_paid(db),
        registration=AdminRegistrationOut.model_validate(reg),
    )
