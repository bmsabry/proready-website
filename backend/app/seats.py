"""Seat-count helpers — single source of truth for what a seat is.

- count_active(): paid + pending rows that have NOT attended. This is the
  PUBLIC seat counter: a registration takes a seat the moment the form is
  submitted. Cancelled rows free the seat (product decision 2026-04-24,
  replacing the 2026-04-19 'paid only' model), and so does attendance —
  someone who sat the previous cohort is a past-cohort record, not a seat
  in the next one (2026-09-15; see app/registrants.py).
- count_paid(): paid, not-attended rows only. Used as a defensive guard so
  admins can't process more payments than capacity even if data drifts.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Registration
from .registrants import active_clauses


def _resolve_code(code: Optional[str]) -> str:
    return (code or get_settings().COURSE_CODE).strip()


def count_active(db: Session, code: Optional[str] = None) -> int:
    """Count registrations that hold a seat (paid + pending).

    Defaults to the configured COURSE_CODE so legacy callers keep working.
    """
    course_code = _resolve_code(code)
    stmt = select(func.count(Registration.id)).where(*active_clauses(course_code))
    return int(db.execute(stmt).scalar_one())


def count_paid(db: Session, code: Optional[str] = None) -> int:
    """Count rows whose status is 'paid' (committed seats)."""
    course_code = _resolve_code(code)
    stmt = select(func.count(Registration.id)).where(
        *active_clauses(course_code), Registration.status == "paid"
    )
    return int(db.execute(stmt).scalar_one())
