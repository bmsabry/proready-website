"""Per-device visibility for learner accounts — detect-and-alert only.

Learner auth is a stateless signed cookie, which means one purchased email
can quietly serve a whole group: each person requests a magic link from the
shared inbox and gets a valid session on their own device, and the server
never sees how many devices an account really has. This module closes that
blind spot without blocking anyone:

  * a random `learner_device` cookie names the browser;
  * every authenticated request upserts a LearnerDevice row (throttled to
    one write per TOUCH_INTERVAL so hot endpoints stay cheap);
  * when a second device of the same learner was active inside
    OVERLAP_WINDOW, a LearnerOverlapEvent is recorded (deduped per
    OVERLAP_DEDUP) — the "two people at once" evidence the admin
    Integrity tab surfaces.

Tracking must NEVER break auth: every failure is swallowed after a
rollback, and the caller proceeds as if nothing happened.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Learner, LearnerDevice, LearnerOverlapEvent

log = logging.getLogger(__name__)

DEVICE_COOKIE_NAME = "learner_device"
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 730  # two years; the id is not a credential

# Refresh last_seen at most this often per device. Coarse on purpose — the
# signals below work on 10-minute windows, so 5-minute resolution is plenty.
TOUCH_INTERVAL = timedelta(minutes=5)
# Two devices active within this window count as simultaneous use.
OVERLAP_WINDOW = timedelta(minutes=10)
# Record at most one overlap event per learner per this window.
OVERLAP_DEDUP = timedelta(minutes=30)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite round-trips naive datetimes; compare everything as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def track_device(
    db: Session,
    learner: Learner,
    request: Request,
    response: Response,
    device_cookie: str,
) -> None:
    """Record that this learner's session was just used from this device."""
    # Capture the id up front: on a broken/closed session even reading
    # learner.id can raise (detached instance), and nothing in here —
    # including the error path — is allowed to break auth.
    try:
        learner_id = int(learner.id)
    except Exception:
        return
    try:
        device_id = (device_cookie or "").strip()
        if not device_id or len(device_id) != 32 or not all(
            c in "0123456789abcdef" for c in device_id
        ):
            device_id = secrets.token_hex(16)
            # Same cross-site constraints as the session cookie itself.
            response.set_cookie(
                key=DEVICE_COOKIE_NAME,
                value=device_id,
                max_age=DEVICE_COOKIE_MAX_AGE,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
            )

        now = datetime.now(timezone.utc)
        row = db.execute(
            select(LearnerDevice).where(
                LearnerDevice.learner_id == learner_id,
                LearnerDevice.device_id == device_id,
            )
        ).scalar_one_or_none()

        if row is not None:
            last_seen = _aware(row.last_seen_at)
            if last_seen is not None and now - last_seen < TOUCH_INTERVAL:
                return  # touched recently — nothing to write
            row.last_seen_at = now
            row.ip = _client_ip(request)
            row.user_agent = request.headers.get("user-agent", "")[:400]
            row.seen_count = (row.seen_count or 0) + 1
        else:
            row = LearnerDevice(
                learner_id=learner_id,
                device_id=device_id,
                user_agent=request.headers.get("user-agent", "")[:400],
                ip=_client_ip(request),
                first_seen_at=now,
                last_seen_at=now,
                seen_count=1,
            )
            db.add(row)

        _record_overlap(db, learner_id, device_id, row.ip, now)
        db.commit()
    except Exception:  # pragma: no cover — tracking must never break auth
        log.exception("[devices] tracking failed for learner %s", learner_id)
        try:
            db.rollback()
        except Exception:
            pass


def _record_overlap(
    db: Session, learner_id: int, device_id: str, ip: str, now: datetime
) -> None:
    """If another device of this learner was active just now, log the pair."""
    other = db.execute(
        select(LearnerDevice)
        .where(
            LearnerDevice.learner_id == learner_id,
            LearnerDevice.device_id != device_id,
            LearnerDevice.last_seen_at >= now - OVERLAP_WINDOW,
        )
        .order_by(LearnerDevice.last_seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if other is None:
        return

    recent = db.execute(
        select(LearnerOverlapEvent.id)
        .where(
            LearnerOverlapEvent.learner_id == learner_id,
            LearnerOverlapEvent.at >= now - OVERLAP_DEDUP,
        )
        .limit(1)
    ).scalar_one_or_none()
    if recent is not None:
        return

    db.add(
        LearnerOverlapEvent(
            learner_id=learner_id,
            device_a=device_id,
            device_b=other.device_id,
            ip_a=ip,
            ip_b=other.ip or "",
            at=now,
        )
    )
