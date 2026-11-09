"""The cron entry point for watching customer email delivery.

  POST /api/admin/email-delivery/sweep

Called every 10 minutes by the Render cron job (scripts/session_reminders_cron.py,
right after the session reminders) with `X-Cron-Secret: <CRON_SECRET>`; the
admin session/token works too, for running it by hand. The logic lives in
app/delivery_watch.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import delivery_watch
from ..db import get_db
from .reminders import require_admin_or_cron

router = APIRouter(prefix="/api/admin/email-delivery", tags=["admin"])


@router.post("/sweep")
def sweep(db: Session = Depends(get_db), _who: str = Depends(require_admin_or_cron)) -> dict:
    return delivery_watch.sweep(db)
