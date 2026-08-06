"""Admin endpoints, protected by bearer token.

Endpoints:
  GET  /api/admin/registrations    — list rows across every course
                                     (most recent first, ?course= to filter)
  POST /api/admin/mark-paid        — flip a pending row to paid
  POST /api/admin/cancel           — flip a row to cancelled (release seat if paid)

mark-paid/cancel operate on whatever course the row belongs to — the old
hardwiring to settings.COURSE_CODE predates multi-course support.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

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
from ..seats import count_active, count_paid

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/registrations", response_model=List[AdminRegistrationOut])
def list_registrations(
    course: Optional[str] = None, db: Session = Depends(get_db)
) -> List[Registration]:
    """All registrations, newest first. ?course= narrows to one cohort."""
    stmt = select(Registration).order_by(Registration.created_at.desc())
    if course:
        stmt = stmt.where(Registration.course_code == course)
    return list(db.execute(stmt).scalars().all())


@router.post("/mark-paid", response_model=MarkPaidOut)
def mark_paid(body: MarkPaidIn, db: Session = Depends(get_db)) -> MarkPaidOut:
    settings = get_settings()
    reg = db.get(Registration, body.registration_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    if reg.status == "paid":
        # Idempotent — don't double-write paid_at.
        return MarkPaidOut(
            ok=True,
            taken=count_active(db, reg.course_code),
            registration=AdminRegistrationOut.model_validate(reg),
        )

    # Capacity guard — read live seat cap from the row's own Course so admin
    # edits to total_seats are respected. Use count_paid (true paid count)
    # so we don't reject promoting a pending row to paid when the cohort
    # is "full" of pending+paid (count_active >= capacity is the normal
    # full-cohort state once registrations match capacity).
    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    capacity = course.total_seats if course is not None else settings.COURSE_CAPACITY
    if count_paid(db, reg.course_code) >= capacity:
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
        taken=count_active(db, reg.course_code),
        registration=AdminRegistrationOut.model_validate(reg),
    )


class CancelIn(MarkPaidIn):
    pass  # same shape — registration_id + optional notes


@router.post("/cancel", response_model=MarkPaidOut)
def cancel(body: CancelIn, db: Session = Depends(get_db)) -> MarkPaidOut:
    reg = db.get(Registration, body.registration_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    reg.status = "cancelled"
    reg.paid_at = None
    if body.notes is not None:
        reg.admin_notes = body.notes
    db.commit()
    db.refresh(reg)

    return MarkPaidOut(
        ok=True,
        taken=count_active(db, reg.course_code),
        registration=AdminRegistrationOut.model_validate(reg),
    )
