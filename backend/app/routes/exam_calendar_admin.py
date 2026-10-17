"""Admin API for the oral-examination calendar.

  GET  /api/admin/academy/calendar                  settings + connection
  PUT  /api/admin/academy/calendar                  change settings / OAuth client
  POST /api/admin/academy/calendar/connect          Google consent URL
  GET  /api/admin/academy/calendar/google/callback  Google returns here
  POST /api/admin/academy/calendar/disconnect
  POST /api/admin/academy/calendar/test             can each calendar be read?
  GET  /api/admin/academy/calendar/preview          the next open slots

Secrets go in and never come back out: the OAuth client secret and the
refresh token are stored encrypted, and the GET shows only whether they are
set.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import exam_calendar as xcal
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/academy/calendar", tags=["academy-admin-calendar"])


@router.get("")
def get_calendar(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    return xcal.settings_out(xcal.settings_row(db))


class CalendarIn(BaseModel):
    client_id: str | None = Field(default=None, max_length=300)
    client_secret: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=64)
    weekly_hours: dict | None = None
    buffer_minutes: int | None = None
    min_notice_hours: int | None = None
    horizon_days: int | None = None
    max_per_day: int | None = None
    step_minutes: int | None = None
    check_calendars: list[str] | None = None
    self_booking: bool | None = None


@router.put("")
def put_calendar(
    body: CalendarIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    try:
        cal = xcal.update_settings(db, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return xcal.settings_out(cal)


@router.post("/connect")
def connect(db: Session = Depends(get_db), admin: str = Depends(require_admin)) -> dict:
    try:
        return {"url": xcal.authorization_url(db, admin)}
    except xcal.CalendarError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/google/callback")
def google_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> RedirectResponse:
    """Google sends the admin's browser back here; answer with the panel."""
    base = f"{get_settings().SITE_URL.rstrip('/')}/admin"
    if error or not code:
        message = "Google sign-in was cancelled." if error == "access_denied" else (
            f"Google sign-in failed: {error or 'no code returned'}."
        )
        return RedirectResponse(f"{base}?calendar_error={quote(message)}#certification", status_code=303)
    try:
        cal = xcal.complete_authorization(db, code, state, admin)
    except xcal.CalendarError as exc:
        return RedirectResponse(f"{base}?calendar_error={quote(str(exc))}#certification", status_code=303)
    log.info("Exam calendar connected as %s", cal.account_email)
    return RedirectResponse(f"{base}?calendar=connected#certification", status_code=303)


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    return xcal.settings_out(xcal.disconnect(db))


@router.post("/test")
def test(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    """Read each calendar's busy time for the next week, separately, so a
    calendar that is not shared shows up by name."""
    try:
        results = xcal.check_each(db)
    except xcal.CalendarError as exc:
        xcal.note_failure(db, str(exc), alert=False)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"calendars": results, "ok": all(r["ok"] for r in results)}


@router.get("/preview")
def preview(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    """The open slots a candidate would be offered now, on his clock."""
    cal = xcal.settings_row(db)
    try:
        slots = xcal.open_slots(db)
    except xcal.CalendarError as exc:
        xcal.note_failure(db, str(exc), alert=False)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    tz = xcal.zone(cal)
    return {
        "timezone": cal.timezone,
        "count": len(slots),
        "slots": [
            {"start": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "label": label}
            for s, label in zip(slots[:40], xcal.day_lines(slots[:40], tz))
        ],
    }
