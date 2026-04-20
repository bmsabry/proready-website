"""Seat-count helper — single source of truth for 'taken' semantics.

'taken' = count of rows where status == 'paid' for the configured course_code.
Pending rows DO NOT count (per product decision 2026-04-19).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Registration


def count_paid(db: Session) -> int:
    settings = get_settings()
    stmt = select(func.count(Registration.id)).where(
        Registration.course_code == settings.COURSE_CODE,
        Registration.status == "paid",
    )
    return int(db.execute(stmt).scalar_one())
