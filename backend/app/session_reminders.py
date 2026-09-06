"""Joining-instructions emails, sent before each live session day.

Who gets one: every registration on the course that is still live (paid or
pending — never cancelled) AND has answered the "confirm your seat" ask
(attendance_confirmed_at is set). That is the list Bassam runs the session
for; an unconfirmed registrant is not sent a link.

When: SESSION_REMINDER_LEAD_MINUTES (60) before the session starts, where a
session is one entry of course.day_dates at course.session_time_utc. The job
is called every 10 minutes by a Render cron job, so a reminder lands between
60 and 50 minutes ahead. The window stays open until the session starts, so
a cron hiccup delays a reminder rather than dropping it; after the start
nothing is sent — a link that arrives mid-session is noise.

Exactly once: the marker is the email log itself. A recipient with an OK
row (template 'session_reminder', scope_code course, audience session date)
is skipped on every later run. Failed sends leave no OK row and are retried
by the next run while the window is open. Someone who confirms at T-30 is
picked up by the next run — no need to re-arm anything.

Nothing is sent for a course whose meeting_info is empty: the admin fills
in the joining instructions, and that is what turns the reminders on.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import send_email, session_reminder_html
from .local_times import resolve_zone
from .models import Course, EmailLog, Registration

log = logging.getLogger(__name__)

TEMPLATE = "session_reminder"
TEST_TEMPLATE = "session_reminder_test"
LIVE_STATUSES = ("paid", "pending")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def blocked_by(course: Course) -> list[str]:
    """Why reminders cannot run for this course (empty list = they can)."""
    reasons = []
    if not (course.meeting_info or "").strip():
        reasons.append("no meeting info")
    if not _TIME_RE.match(course.session_time_utc or ""):
        reasons.append("no session start time")
    if not course.day_dates:
        reasons.append("no session days")
    return reasons


def session_starts(course: Course) -> list[tuple[int, date, datetime]]:
    """(day number, date, start datetime UTC) for every scheduled day."""
    if not _TIME_RE.match(course.session_time_utc or ""):
        return []
    hh, mm = (int(x) for x in course.session_time_utc.split(":"))
    out = []
    for i, d in enumerate(course.day_dates or [], start=1):
        try:
            day = date.fromisoformat(str(d))
        except (TypeError, ValueError):
            continue
        out.append((i, day, datetime.combine(day, time(hh, mm), tzinfo=timezone.utc)))
    return out


def confirmed_registrants(db: Session, course_code: str) -> list[Registration]:
    rows = db.execute(
        select(Registration)
        .where(
            Registration.course_code == course_code,
            Registration.status.in_(LIVE_STATUSES),
            Registration.attendance_confirmed_at.is_not(None),
        )
        .order_by(Registration.full_name)
    ).scalars().all()
    # One email per address even if someone registered twice.
    seen: set[str] = set()
    out = []
    for r in rows:
        key = r.email.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def sent_to(db: Session, course_code: str, session_date: date) -> set[str]:
    """Addresses that already have an OK reminder for this session day."""
    rows = db.execute(
        select(EmailLog.recipient).where(
            EmailLog.template == TEMPLATE,
            EmailLog.scope_code == course_code,
            EmailLog.audience == session_date.isoformat(),
            EmailLog.ok.is_(True),
        )
    ).scalars().all()
    return {r.lower() for r in rows}


def when_lines(start_utc: datetime, location: str) -> tuple[list[str], str]:
    """['14:00 UTC on Saturday, September 12', '10:00 EDT in Cincinnati (your local time)'].

    Returns the lines and the zone used ("" when the location did not
    resolve — then only the UTC line is given, never a guessed local time).
    """
    lines = [start_utc.strftime("%H:%M UTC on %A, %B %-d")]
    zone = resolve_zone(location or "") or ""
    if zone:
        try:
            local = start_utc.astimezone(ZoneInfo(zone))
        except ZoneInfoNotFoundError:  # pragma: no cover - depends on tzdata
            return lines, ""
        day_note = "" if local.date() == start_utc.date() else local.strftime(" (%A)")
        lines.append(
            f"{local.strftime('%H:%M %Z')} in {location.strip()}{day_note} — your local time"
        )
    return lines, zone


def build_email(course: Course, reg: Registration, day: int, start_utc: datetime) -> tuple[str, str]:
    settings = get_settings()
    total = len(course.day_dates or [])
    lines, _zone = when_lines(start_utc, reg.location)
    subject = f"Starts in 1 hour: {course.title} — Day {day} of {total}"
    if settings.SESSION_REMINDER_LEAD_MINUTES != 60:
        subject = f"Starts soon: {course.title} — Day {day} of {total}"
    html = session_reminder_html(
        full_name=reg.full_name,
        course_title=course.title,
        day=day,
        total_days=total,
        when_lines=lines,
        meeting_info=course.meeting_info,
        lead_minutes=settings.SESSION_REMINDER_LEAD_MINUTES,
    )
    return subject, html


def due_sessions(course: Course, now: datetime) -> list[tuple[int, date, datetime]]:
    lead = timedelta(minutes=get_settings().SESSION_REMINDER_LEAD_MINUTES)
    return [
        (day, d, start)
        for day, d, start in session_starts(course)
        if start - lead <= now < start
    ]


def run(db: Session, now: Optional[datetime] = None, courses: Optional[Iterable[Course]] = None) -> dict:
    """Send every reminder that is due right now. Safe to call as often as you like."""
    now = _aware(now) or datetime.now(timezone.utc)
    if courses is None:
        courses = db.execute(select(Course)).scalars().all()
    checked = sent = failed = 0
    details: list[str] = []
    for course in courses:
        checked += 1
        if blocked_by(course):
            continue
        for day, session_date, start in due_sessions(course, now):
            already = sent_to(db, course.code, session_date)
            for reg in confirmed_registrants(db, course.code):
                if reg.email.lower() in already:
                    continue
                subject, html = build_email(course, reg, day, start)
                ok = send_email(
                    to=reg.email,
                    subject=subject,
                    html=html,
                    db=db,
                    scope_kind="course",
                    scope_code=course.code,
                    audience=session_date.isoformat(),
                    template=TEMPLATE,
                )
                sent += ok
                failed += not ok
                details.append(
                    f"{course.code} day={day} date={session_date.isoformat()} -> {reg.email}"
                    + ("" if ok else " FAILED")
                )
    if sent or failed:
        log.info("[session_reminders] sent=%d failed=%d %s", sent, failed, details)
    return {
        "ran_at": now,
        "courses_checked": checked,
        "sent": sent,
        "failed": failed,
        "details": details,
    }


def send_test(db: Session, course: Course, to: str, now: Optional[datetime] = None) -> dict:
    """Email the admin exactly what a registrant would get, for the next session day.

    Logged under a different template so it never counts as a real send.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    starts = session_starts(course)
    upcoming = [s for s in starts if s[2] > now] or starts
    if not upcoming:
        raise ValueError("This course has no session days or no start time yet.")
    day, _date, start = upcoming[0]
    sample = Registration(
        course_code=course.code,
        full_name="Test Preview",
        email=to,
        job_title="",
        company="",
        years_experience="",
        location="Mason, OH",
        status="pending",
    )
    subject, html = build_email(course, sample, day, start)
    ok = send_email(
        to=to,
        subject=f"[TEST] {subject}",
        html=html,
        db=db,
        scope_kind="course",
        scope_code=course.code,
        audience="test",
        template=TEST_TEMPLATE,
    )
    return {"ok": ok, "to": to, "subject": f"[TEST] {subject}", "day": day}


def overview(db: Session, course: Course, now: Optional[datetime] = None) -> dict:
    """Everything the admin card shows: recipients, per-day state, the log."""
    now = _aware(now) or datetime.now(timezone.utc)
    settings = get_settings()
    lead = timedelta(minutes=settings.SESSION_REMINDER_LEAD_MINUTES)
    recipients = confirmed_registrants(db, course.code)
    reasons = blocked_by(course)

    sessions = []
    for day, session_date, start in session_starts(course):
        done = sent_to(db, course.code, session_date)
        n_sent = sum(1 for r in recipients if r.email.lower() in done)
        n_pending = len(recipients) - n_sent
        if recipients and n_pending == 0:
            state = "sent"
        elif n_sent:
            state = "partial"
        elif now >= start:
            state = "missed" if not done else "sent"
        elif now >= start - lead:
            state = "due"
        else:
            state = "scheduled"
        sessions.append(
            {
                "day": day,
                "date": session_date,
                "start_utc": start,
                "remind_at_utc": start - lead,
                "state": state,
                "sent": n_sent,
                "pending": n_pending,
            }
        )

    log_rows = db.execute(
        select(EmailLog)
        .where(EmailLog.template == TEMPLATE, EmailLog.scope_code == course.code)
        .order_by(EmailLog.ts.desc())
        .limit(200)
    ).scalars().all()

    return {
        "meeting_info": course.meeting_info or "",
        "session_time_utc": course.session_time_utc or "",
        "session_duration_minutes": course.session_duration_minutes or 0,
        "lead_minutes": settings.SESSION_REMINDER_LEAD_MINUTES,
        "armed": not reasons,
        "blocked_by": reasons,
        "recipients": [
            {
                "registration_id": r.id,
                "full_name": r.full_name,
                "email": r.email,
                "status": r.status,
                "location": r.location or "",
                "timezone": resolve_zone(r.location or "") or "",
            }
            for r in recipients
        ],
        "sessions": sessions,
        "log": [
            {
                "ts": _aware(e.ts),
                "session_date": e.audience,
                "recipient": e.recipient,
                "ok": e.ok,
                "subject": e.subject,
            }
            for e in log_rows
        ],
    }
