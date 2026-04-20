"""GET /api/seats — public seat-availability snapshot."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..schemas import SeatsOut
from ..seats import count_paid

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/seats", response_model=SeatsOut)
def get_seats(db: Session = Depends(get_db)) -> SeatsOut:
    settings = get_settings()
    return SeatsOut(
        taken=count_paid(db),
        capacity=settings.COURSE_CAPACITY,
        cohort=settings.COHORT_LABEL,
    )
