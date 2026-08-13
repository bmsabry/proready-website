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

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as academy_svc
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..emailer import enrollment_granted_html, send_email
from ..learner_auth import issue_login_token
from ..models import Course, Product, Registration
from ..schemas import (
    AdminRegistrationOut,
    MarkPaidIn,
    MarkPaidOut,
)
from ..seats import count_active, count_paid

log = logging.getLogger(__name__)

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


def mark_registration_paid(
    db: Session,
    reg: Registration,
    *,
    provider: str = "",
    payment_ref: str = "",
    amount_cents: Optional[int] = None,
    notes: Optional[str] = None,
) -> bool:
    """Core of mark-paid — shared by the admin endpoint and the online
    payment paths (PayPal capture, Stripe live-cohort webhook) so all of
    them have identical side effects.

    Returns True when the row actually transitioned to paid, False on an
    idempotent replay of an already-paid row (callers use this to avoid
    re-sending receipt emails). Raises HTTPException(409) when the cohort
    is already at paid capacity.
    """
    settings = get_settings()

    if reg.status == "paid":
        # Idempotent — don't double-write paid_at. Backfill the payment
        # attribution if this is the first time a provider claims the row
        # (e.g. admin marked it paid manually while a capture was in flight).
        if provider and not reg.payment_provider:
            reg.payment_provider = provider
            reg.payment_ref = payment_ref
            reg.amount_cents = amount_cents
            db.commit()
        return False

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
    if provider:
        reg.payment_provider = provider
        reg.payment_ref = payment_ref
        reg.amount_cents = amount_cents
    if notes is not None:
        reg.admin_notes = notes
    db.commit()
    db.refresh(reg)

    # Paid = everything. When the cohort is linked to its materials product
    # (courses.recorded_product_code), a paid seat auto-provisions the full
    # course-materials account: learner row, product-wide enrollment, and a
    # sign-in link in their inbox. Deliberately after the commit and inside
    # its own guard — a hiccup here must never un-mark a payment.
    try:
        _grant_course_materials(db, reg, course)
    except Exception:  # pragma: no cover — provisioning is best-effort
        log.exception(
            "Materials auto-grant failed for %s / %s — grant manually from "
            "the admin Access panel",
            reg.email,
            reg.course_code,
        )
    return True


def _grant_course_materials(
    db: Session, reg: Registration, course: Optional[Course]
) -> None:
    """Provision full materials access for a paid cohort seat."""
    if course is None or not course.recorded_product_code:
        return
    product = db.get(Product, course.recorded_product_code)
    if product is None:
        log.warning(
            "Course %s points at missing product %s — no materials to grant",
            course.code,
            course.recorded_product_code,
        )
        return
    settings = get_settings()
    learner = academy_svc.upsert_learner(db, reg.email, reg.full_name)
    academy_svc.grant_enrollment(
        db,
        learner,
        product.code,
        source="cohort",
        note=f"cohort {reg.course_code} marked paid (registration #{reg.id})",
    )
    raw = issue_login_token(db, learner, next_path=f"/learn/{product.code}")
    link = f"{settings.SITE_URL}/learn/signin?token={raw}"
    send_email(
        to=learner.email,
        subject=f"Your course materials are ready — {product.title}",
        html=enrollment_granted_html(learner.full_name or "", product.title, link),
        db=db,
        scope_kind="course",
        scope_code=reg.course_code,
        audience="paid",
        template="materials_ready",
    )
    log.info(
        "Materials access granted to %s for %s (cohort %s)",
        learner.email,
        product.code,
        reg.course_code,
    )


@router.post("/mark-paid", response_model=MarkPaidOut)
def mark_paid(body: MarkPaidIn, db: Session = Depends(get_db)) -> MarkPaidOut:
    reg = db.get(Registration, body.registration_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    mark_registration_paid(db, reg, notes=body.notes)

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

    was_paid = reg.status == "paid"
    reg.status = "cancelled"
    reg.paid_at = None
    if body.notes is not None:
        reg.admin_notes = body.notes
    db.commit()
    db.refresh(reg)

    # Cancelling a previously-paid seat pulls the auto-granted materials
    # access back — but ONLY the cohort-sourced enrollment. An access the
    # admin granted by hand, or one the person separately purchased, is a
    # different promise and stays untouched.
    if was_paid:
        try:
            _revoke_cohort_materials(db, reg)
        except Exception:  # pragma: no cover
            log.exception(
                "Cohort materials auto-revoke failed for %s — revoke manually",
                reg.email,
            )

    return MarkPaidOut(
        ok=True,
        taken=count_active(db, reg.course_code),
        registration=AdminRegistrationOut.model_validate(reg),
    )


def _revoke_cohort_materials(db: Session, reg: Registration) -> None:
    from ..models import Enrollment, Learner

    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    if course is None or not course.recorded_product_code:
        return
    learner = db.execute(
        select(Learner).where(Learner.email == reg.email.lower().strip())
    ).scalar_one_or_none()
    if learner is None:
        return
    enrollment = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id,
            Enrollment.product_code == course.recorded_product_code,
            Enrollment.status == "active",
            Enrollment.source == "cohort",
        )
    ).scalar_one_or_none()
    if enrollment is None:
        return
    enrollment.status = "revoked"
    enrollment.note = (
        f"auto-revoked: registration #{reg.id} cancelled"[:500]
    )
    db.commit()
    log.info(
        "Cohort materials access revoked for %s (%s)",
        learner.email,
        course.recorded_product_code,
    )
