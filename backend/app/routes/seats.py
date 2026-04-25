"""GET /api/seats — public seat-availability snapshot.

Optional `?code=` selects a course; default is settings.COURSE_CODE so the
legacy frontend keeps working.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Course
from ..schemas import SeatsOut
from ..seats import count_active

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/seats", response_model=SeatsOut)
def get_seats(
    code: Optional[str] = None, db: Session = Depends(get_db)
) -> SeatsOut:
    settings = get_settings()
    course_code = (code or settings.COURSE_CODE).strip()

    course = db.execute(
        select(Course).where(Course.code == course_code)
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course '{course_code}' not found.",
        )

    return SeatsOut(
        taken=count_active(db, course_code),
        capacity=course.total_seats,
        cohort=course.start_date.strftime("%B %-d, %Y"),
    )
