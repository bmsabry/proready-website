"""Learner visits and activity — what each trainee did, and when.

Two writers feed the admin Student Activity page:

  * touch_visit() — called from the device registry (device_tracking.py) on
    its throttled write, so a visit costs no extra round trip on hot
    endpoints. A new visit opens after VISIT_GAP of silence on a device, or
    on any fresh sign-in.
  * record() — called by the few endpoints whose action no other table
    remembers (a lesson opened, a sign-in, a failed password, a simulator
    session …). Deduplicated where a reload would otherwise spam the log.

Like device tracking, nothing here may ever break the request it rides on:
every failure is logged and swallowed after a rollback. Callers invoke
record() only after their own work is committed, so that rollback can never
undo anything but the activity row itself.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LearnerActivity, LearnerVisit

log = logging.getLogger(__name__)

# Silence on a device longer than this starts a new visit.
VISIT_GAP = timedelta(minutes=30)
# Device id used for the quiz apps, which have no cookie.
APP_DEVICE = "app"


def aware(dt: datetime | None) -> datetime | None:
    """SQLite round-trips naive datetimes; compare everything as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def client_ip(headers: Any, fallback: str = "") -> str:
    fwd = (headers.get("x-forwarded-for") or "") if headers is not None else ""
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (fallback or "")[:64]


def _open_visit(db: Session, learner_id: int, device_id: str, now: datetime) -> LearnerVisit | None:
    """The visit on this device that was open at `now` (normally the present;
    a simulator session looks up the moment it began)."""
    row = db.execute(
        select(LearnerVisit)
        .where(
            LearnerVisit.learner_id == learner_id,
            LearnerVisit.device_id == device_id,
            LearnerVisit.started_at <= now + timedelta(minutes=1),
        )
        .order_by(LearnerVisit.last_seen_at.desc(), LearnerVisit.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    last = aware(row.last_seen_at)
    if last is None or now - last > VISIT_GAP:
        return None
    return row


def touch_visit(
    db: Session,
    learner_id: int,
    device_id: str,
    *,
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
    sign_in: str = "",
) -> LearnerVisit:
    """Extend this device's open visit, or open a new one. Does not commit."""
    now = now or datetime.now(timezone.utc)
    row = None if sign_in else _open_visit(db, learner_id, device_id, now)
    if row is None:
        row = LearnerVisit(
            learner_id=learner_id,
            device_id=device_id[:32],
            started_at=now,
            last_seen_at=now,
            ip=ip[:64],
            user_agent=user_agent[:400],
            sign_in=sign_in[:16],
        )
        db.add(row)
        db.flush()
    else:
        row.last_seen_at = now
        if ip:
            row.ip = ip[:64]
    return row


def request_device(request: Any) -> str:
    """The device id this request carries: the one track_device settled on
    (it may have minted it on this very request), else the cookie."""
    try:
        dev = getattr(request.state, "learner_device", "") or ""
    except Exception:
        dev = ""
    if not dev:
        try:
            dev = request.cookies.get("learner_device", "") or ""
        except Exception:
            dev = ""
    return dev[:32]


def record(
    db: Session,
    learner_id: int,
    kind: str,
    *,
    request: Any = None,
    label: str = "",
    product_code: str = "",
    module_id: int = 0,
    lesson_id: int = 0,
    amount: int = 0,
    detail: dict | None = None,
    visit: str = "create",
    dedupe: timedelta | None = None,
    device_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    at: datetime | None = None,
    last_at: datetime | None = None,
) -> LearnerActivity | None:
    """Append one activity row and commit it. Never raises.

    visit: 'create' — attach to this device's open visit, opening one if
               needed (signed-in actions);
           'existing' — attach only if a visit is already open;
           'none' — signed-out events (link requests, failed passwords).
    dedupe: skip when the same kind with the same lesson/module/product and
            label was recorded for this learner within this window.
    at / last_at: a span that already happened (a simulator session). The
            visit open at `at` is used, and extended to `last_at`.
    """
    try:
        now = datetime.now(timezone.utc)
        if request is not None:
            if device_id is None:
                device_id = request_device(request)
            if ip is None:
                host = request.client.host if getattr(request, "client", None) else ""
                ip = client_ip(request.headers, host)
            if user_agent is None:
                user_agent = request.headers.get("user-agent", "")
        device_id = (device_id or "")[:32]
        ip = (ip or "")[:64]

        if dedupe is not None:
            prev = db.execute(
                select(LearnerActivity.id)
                .where(
                    LearnerActivity.learner_id == learner_id,
                    LearnerActivity.kind == kind,
                    LearnerActivity.lesson_id == lesson_id,
                    LearnerActivity.module_id == module_id,
                    LearnerActivity.product_code == product_code,
                    LearnerActivity.label == (label or "")[:300],
                    LearnerActivity.at >= now - dedupe,
                )
                .limit(1)
            ).scalar_one_or_none()
            if prev is not None:
                return None

        visit_id = None
        ref = at or now
        if visit != "none" and device_id:
            row = _open_visit(db, learner_id, device_id, ref)
            if row is None and visit == "create":
                row = touch_visit(db, learner_id, device_id, ip=ip,
                                  user_agent=user_agent or "", now=ref)
            if row is not None:
                visit_id = row.id
                seen = aware(row.last_seen_at)
                if last_at is not None and (seen is None or seen < last_at):
                    row.last_seen_at = last_at

        act = LearnerActivity(
            learner_id=learner_id,
            visit_id=visit_id,
            at=at or now,
            last_at=last_at,
            kind=kind[:24],
            product_code=(product_code or "")[:64],
            module_id=int(module_id or 0),
            lesson_id=int(lesson_id or 0),
            label=(label or "")[:300],
            amount=int(amount or 0),
            detail=detail or {},
            ip=ip,
            device_id=device_id,
        )
        db.add(act)
        db.commit()
        return act
    except Exception:  # pragma: no cover — activity must never break a request
        log.exception("[activity] could not record %s for learner %s", kind, learner_id)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def add_time_on_lesson(
    db: Session,
    learner_id: int,
    request: Any,
    *,
    lesson_id: int,
    module_id: int,
    product_code: str,
    title: str,
    seconds: int,
) -> None:
    """Credit heartbeat time to one row per (visit, lesson). Never raises."""
    seconds = max(0, min(int(seconds or 0), 60))
    if seconds <= 0:
        return
    try:
        now = datetime.now(timezone.utc)
        device_id = request_device(request)
        visit_row = _open_visit(db, learner_id, device_id, now) if device_id else None
        if visit_row is None:
            host = request.client.host if getattr(request, "client", None) else ""
            visit_row = touch_visit(
                db, learner_id, device_id,
                ip=client_ip(request.headers, host),
                user_agent=request.headers.get("user-agent", ""), now=now,
            )
        row = db.execute(
            select(LearnerActivity).where(
                LearnerActivity.visit_id == visit_row.id,
                LearnerActivity.kind == "lesson_time",
                LearnerActivity.lesson_id == lesson_id,
            ).limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = LearnerActivity(
                learner_id=learner_id, visit_id=visit_row.id, at=now, last_at=now,
                kind="lesson_time", product_code=product_code[:64],
                module_id=module_id, lesson_id=lesson_id, label=title[:300],
                amount=seconds, detail={}, ip=visit_row.ip or "",
                device_id=device_id,
            )
            db.add(row)
        else:
            row.amount = (row.amount or 0) + seconds
            row.last_at = now
        db.commit()
    except Exception:  # pragma: no cover
        log.exception("[activity] lesson time failed for learner %s", learner_id)
        try:
            db.rollback()
        except Exception:
            pass
