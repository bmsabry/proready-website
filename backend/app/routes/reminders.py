"""The cron entry point for live-session reminders.

  POST /api/admin/session-reminders/run

Called every 10 minutes by the Render cron job `proreadyengineer-session-reminders`
(scripts/session_reminders_cron.py) with `X-Cron-Secret: <CRON_SECRET>`. The
admin session/token is accepted too, so the button in the admin UI and a
curl with the admin token can run it by hand. Sending logic lives in
app/session_reminders.py; this route only decides who may trigger it.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .. import session_reminders
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..schemas import ReminderRunOut

router = APIRouter(prefix="/api/admin/session-reminders", tags=["admin"])


def require_admin_or_cron(
    x_cron_secret: str = Header(default=""),
    authorization: str = Header(default=""),
    admin_session: str = Cookie(default=""),
) -> str:
    settings = get_settings()
    if settings.CRON_SECRET and x_cron_secret:
        if secrets.compare_digest(x_cron_secret, settings.CRON_SECRET):
            return "cron"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad cron secret.")
    return require_admin(authorization=authorization, admin_session=admin_session)


@router.post("/run", response_model=ReminderRunOut)
def run_session_reminders(
    db: Session = Depends(get_db), _who: str = Depends(require_admin_or_cron)
) -> ReminderRunOut:
    return ReminderRunOut(**session_reminders.run(db))
