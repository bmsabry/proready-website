"""Watching customer email delivery: the cron call and Resend's webhook.

  POST /api/admin/email-delivery/sweep   — called every 10 minutes by the Render
                                           cron job (scripts/session_reminders_cron.py,
                                           right after the session reminders) with
                                           `X-Cron-Secret: <CRON_SECRET>`; the admin
                                           session/token works too. Runs the sweep,
                                           the DNS guard and the daily canary.
  POST /api/webhooks/resend-events       — Resend reports delivered / bounced /
                                           complained / failed / suppressed within
                                           seconds, with the receiving server's own
                                           words. Signed (Svix); RESEND_WEBHOOK_SECRET.

The logic lives in app/delivery_watch.py.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import delivery_watch
from ..config import get_settings
from ..db import get_db
from .reminders import require_admin_or_cron

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/email-delivery", tags=["admin"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Svix refuses messages older or newer than this (replay protection).
TOLERANCE_SECONDS = 5 * 60


@router.post("/sweep")
def sweep(db: Session = Depends(get_db), _who: str = Depends(require_admin_or_cron)) -> dict:
    out = delivery_watch.sweep(db)
    out.update(delivery_watch.checks(db))
    return out


def verify_signature(secret: str, msg_id: str, timestamp: str, body: bytes, header: str) -> bool:
    """Svix signature check, as Resend signs its webhooks.

    signed content = "<svix-id>.<svix-timestamp>.<raw body>", HMAC-SHA256 with
    the base64 key after "whsec_"; the header lists "v1,<base64 signature>"
    entries separated by spaces (several during a secret rotation).
    """
    if not (secret and msg_id and timestamp and header):
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - sent_at) > TOLERANCE_SECONDS:
        return False
    try:
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, IndexError):
        return False
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in header.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return True
    return False


@webhook_router.post("/resend-events", status_code=200)
async def resend_events(request: Request, db: Session = Depends(get_db)) -> dict:
    body = await request.body()
    secret = (get_settings().RESEND_WEBHOOK_SECRET or "").strip()
    if not verify_signature(
        secret,
        request.headers.get("svix-id", ""),
        request.headers.get("svix-timestamp", ""),
        body,
        request.headers.get("svix-signature", ""),
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature.")
    try:
        event = json.loads(body or b"{}")
    except ValueError:
        return {"ok": True, "result": "not json"}
    if not isinstance(event, dict):
        return {"ok": True, "result": "not an object"}
    try:
        result = delivery_watch.apply_event(db, event)
    except Exception:  # never make Resend retry a message we cannot handle
        log.exception("[delivery] webhook event failed")
        result = "error"
    log.info("[delivery] webhook %s: %s", event.get("type"), result)
    return {"ok": True, "result": result}
