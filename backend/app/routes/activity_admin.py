"""Admin → Student Activity.

  GET /api/admin/academy/activity?product_code=&days=&q=   one row per learner
  GET /api/admin/academy/activity/{learner_id}?days=       the full picture

Read-only. See app/activity_report.py for how each number is worked out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import activity_report as report
from ..db import get_db
from ..deps import require_admin
from ..models import Learner

router = APIRouter(prefix="/api/admin/academy/activity", tags=["academy-activity"])


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 3650)))


@router.get("")
def activity_list(
    product_code: str = "",
    days: int = 90,
    q: str = "",
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    return report.summaries(db, product_code.strip(), _since(days), q.strip()[:100])


@router.get("/{learner_id}")
def activity_detail(
    learner_id: int,
    days: int = 365,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    learner = db.get(Learner, learner_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found.")
    return report.detail(db, learner, _since(days))
