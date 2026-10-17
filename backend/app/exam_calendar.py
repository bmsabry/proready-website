"""The instructor's calendar for oral examinations.

Bassam asked (2026-10-17) that the interview times a candidate can choose
come from his real availability — his company calendar and his personal one
— and that he hears when a time is booked. This module is the calendar side:

  * OAuth with Google, once, from the admin panel. The refresh token (and
    the OAuth client secret, when pasted there) are stored encrypted.
  * FreeBusy over every calendar in `check_calendars`: 'primary' (the
    connected company calendar) plus any calendar shared with it at least
    free/busy, such as his personal Gmail calendar. Only busy blocks are
    read, never what the events are. A calendar that cannot be read blocks
    every slot: an unseen meeting must not be double-booked.
  * `compute_slots`: open examination slots inside his exam hours, clear of
    busy time by the buffer, at least the minimum notice ahead, within the
    horizon, on days with fewer than the daily maximum of examinations.
  * Events on his calendar: created with a Google Meet link and the
    candidate as guest (Google sends them the invitation), moved, deleted.

Google is reached only through `_google()`, which the tests replace.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .crypto import CryptoNotConfigured, decrypt, encrypt
from .models import AdvancedCertification, ExamCalendar

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
CALLBACK_PATH = "/api/admin/academy/calendar/google/callback"
# Busy times across calendars he can see, and events on his own calendars.
SCOPES = (
    "openid email "
    "https://www.googleapis.com/auth/calendar.freebusy "
    "https://www.googleapis.com/auth/calendar.events"
)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_HOURS = {d: ([["09:00", "17:00"]] if i < 5 else []) for i, d in enumerate(DAYS)}
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class CalendarError(RuntimeError):
    """Google could not be reached, refused, or a calendar cannot be read."""


class SlotTaken(ValueError):
    """The chosen time is no longer free."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return _aware(dt).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------

def settings_row(db: Session) -> ExamCalendar:
    cal = db.get(ExamCalendar, 1)
    if cal is None:
        cal = ExamCalendar(
            id=1, check_calendars=["primary"], weekly_hours=json.loads(json.dumps(DEFAULT_HOURS))
        )
        db.add(cal)
        db.commit()
        db.refresh(cal)
    return cal


def connected(db: Session) -> bool:
    cal = db.get(ExamCalendar, 1)
    return bool(cal and cal.refresh_token_encrypted)


def self_booking_on(db: Session) -> bool:
    """Candidates pick their own slot: switched on and the calendar connected."""
    cal = db.get(ExamCalendar, 1)
    return bool(cal and cal.self_booking and cal.refresh_token_encrypted)


def redirect_uri() -> str:
    return get_settings().API_PUBLIC_URL.rstrip("/") + CALLBACK_PATH


def _client(cal: ExamCalendar) -> tuple[str, str]:
    s = get_settings()
    client_id = (cal.client_id or s.GOOGLE_OAUTH_CLIENT_ID or "").strip()
    secret = ""
    if cal.client_secret_encrypted:
        try:
            secret = decrypt(cal.client_secret_encrypted)
        except CryptoNotConfigured as exc:
            raise CalendarError(str(exc)) from exc
    return client_id, (secret or s.GOOGLE_OAUTH_CLIENT_SECRET or "").strip()


def zone(cal: ExamCalendar) -> ZoneInfo:
    try:
        return ZoneInfo(cal.timezone or "America/New_York")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/New_York")


def settings_out(cal: ExamCalendar) -> dict:
    """What the admin panel shows. Never a secret, only whether one is set."""
    s = get_settings()
    return {
        "connected": bool(cal.refresh_token_encrypted),
        "account_email": cal.account_email,
        "connected_at": cal.connected_at,
        "client_id": cal.client_id or s.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret_set": bool(cal.client_secret_encrypted or s.GOOGLE_OAUTH_CLIENT_SECRET),
        "redirect_uri": redirect_uri(),
        "check_calendars": list(cal.check_calendars or ["primary"]),
        "event_calendar": cal.event_calendar or "primary",
        "timezone": cal.timezone,
        "weekly_hours": {d: list((cal.weekly_hours or {}).get(d, [])) for d in DAYS},
        "buffer_minutes": cal.buffer_minutes,
        "min_notice_hours": cal.min_notice_hours,
        "horizon_days": cal.horizon_days,
        "max_per_day": cal.max_per_day,
        "step_minutes": cal.step_minutes,
        "self_booking": bool(cal.self_booking),
        "last_ok_at": cal.last_ok_at,
        "last_error": cal.last_error,
    }


def _bounded(value, low: int, high: int, what: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} must be a whole number.") from exc
    if not low <= n <= high:
        raise ValueError(f"{what} must be between {low} and {high}.")
    return n


def update_settings(db: Session, data: dict) -> ExamCalendar:
    """Apply the admin panel's changes; anything absent stays as it is."""
    cal = settings_row(db)
    if "client_id" in data:
        cal.client_id = str(data["client_id"] or "").strip()[:300]
    if data.get("client_secret"):
        try:
            cal.client_secret_encrypted = encrypt(str(data["client_secret"]).strip())
        except CryptoNotConfigured as exc:
            raise ValueError(str(exc)) from exc
    if "timezone" in data:
        name = str(data["timezone"] or "").strip()
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone {name!r}.") from exc
        cal.timezone = name
    if "weekly_hours" in data:
        hours = data["weekly_hours"] or {}
        if not isinstance(hours, dict):
            raise ValueError("Exam hours must be given per weekday.")
        clean: dict[str, list[list[str]]] = {}
        for d in DAYS:
            windows = hours.get(d) or []
            if len(windows) > 4:
                raise ValueError("At most four time windows per day.")
            day_windows = []
            for w in windows:
                if not (isinstance(w, (list, tuple)) and len(w) == 2):
                    raise ValueError("Each window is a start and an end time.")
                a, b = str(w[0]).strip(), str(w[1]).strip()
                if not (_HHMM.match(a) and _HHMM.match(b)):
                    raise ValueError(f"Times must look like 09:00 ({d}: {a}–{b}).")
                if a >= b:
                    raise ValueError(f"A window must end after it starts ({d}: {a}–{b}).")
                day_windows.append([a, b])
            clean[d] = sorted(day_windows)
        cal.weekly_hours = clean
    if "buffer_minutes" in data:
        cal.buffer_minutes = _bounded(data["buffer_minutes"], 0, 240, "The gap between exams (minutes)")
    if "min_notice_hours" in data:
        cal.min_notice_hours = _bounded(data["min_notice_hours"], 1, 720, "The minimum notice (hours)")
    if "horizon_days" in data:
        cal.horizon_days = _bounded(data["horizon_days"], 1, 120, "How far ahead (days)")
    if "max_per_day" in data:
        cal.max_per_day = _bounded(data["max_per_day"], 0, 10, "Exams per day")
    if "step_minutes" in data:
        step = _bounded(data["step_minutes"], 15, 60, "Start times every (minutes)")
        if step not in (15, 30, 60):
            raise ValueError("Start times can be every 15, 30 or 60 minutes.")
        cal.step_minutes = step
    if "check_calendars" in data:
        ids = [str(x).strip() for x in (data["check_calendars"] or []) if str(x).strip()]
        if len(ids) > 10 or any(len(x) > 320 for x in ids):
            raise ValueError("At most ten calendars.")
        cal.check_calendars = list(dict.fromkeys(["primary", *ids]))
    if "self_booking" in data:
        cal.self_booking = bool(data["self_booking"])
    db.commit()
    db.refresh(cal)
    return cal


# -----------------------------------------------------------------------------
# Google: transport, OAuth, tokens
# -----------------------------------------------------------------------------

def _google(
    method: str, url: str, *, token: str | None = None, data: dict | None = None,
    json_body: dict | None = None, params: dict | None = None,
) -> tuple[int, dict]:
    """The one place this module talks to Google (replaced in tests)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=15) as client:
            r = client.request(method, url, headers=headers, data=data, json=json_body, params=params)
    except httpx.HTTPError as exc:
        raise CalendarError(f"Google could not be reached ({exc.__class__.__name__}).") from exc
    try:
        body = r.json() if r.content else {}
    except ValueError:
        body = {"raw": r.text[:300]}
    return r.status_code, body if isinstance(body, dict) else {"data": body}


def _google_error(body: dict) -> str:
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or err)[:300]
    return str(body.get("error_description") or err or body.get("raw") or body)[:300]


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().SESSION_SECRET or "dev-only", salt="exam-calendar-oauth")


def authorization_url(db: Session, admin_email: str) -> str:
    """Google's consent page for the calendar permissions."""
    cal = settings_row(db)
    client_id, secret = _client(cal)
    if not client_id or not secret:
        raise CalendarError("Paste the Google OAuth client ID and client secret first.")
    state = _signer().dumps({"a": (admin_email or "").lower(), "n": secrets.token_urlsafe(8)})
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if cal.account_email:
        params["login_hint"] = cal.account_email
    return f"{AUTH_URL}?{urlencode(params)}"


def _id_token_email(token: str) -> str:
    """The account's address from the ID token Google's token endpoint just
    handed us over TLS (no signature check needed for that hop)."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return str(json.loads(base64.urlsafe_b64decode(part)).get("email") or "")
    except (IndexError, ValueError):
        return ""


_TOKEN: dict = {}


def _remember(refresh: str, access: str, expires_in) -> None:
    _TOKEN.clear()
    _TOKEN.update(
        key=hashlib.sha256(refresh.encode()).hexdigest(),
        token=access,
        until=time.time() + max(int(expires_in or 3600) - 120, 60),
    )


def complete_authorization(db: Session, code: str, state: str, admin_email: str) -> ExamCalendar:
    """Google sent the admin back with a code: keep the long-lived permission."""
    try:
        data = _signer().loads(state, max_age=900)
    except SignatureExpired as exc:
        raise CalendarError("The Google sign-in took too long. Start again from the admin panel.") from exc
    except BadSignature as exc:
        raise CalendarError("This sign-in did not start from the admin panel. Start again there.") from exc
    if (data or {}).get("a") != (admin_email or "").lower():
        raise CalendarError("The admin panel is signed in as someone else. Start again.")
    cal = settings_row(db)
    client_id, secret = _client(cal)
    status, body = _google("POST", TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": secret,
        "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
    })
    if status != 200 or not body.get("access_token"):
        raise CalendarError(f"Google refused the sign-in: {_google_error(body)}")
    granted = str(body.get("scope") or "")
    if "calendar.freebusy" not in granted or "calendar.events" not in granted:
        raise CalendarError(
            "Both calendar permissions are needed: tick every box on Google's screen and connect again."
        )
    refresh = body.get("refresh_token")
    if not refresh:
        raise CalendarError(
            "Google did not grant lasting access. Remove the app under your Google Account → "
            "Security → Third-party access, then connect again."
        )
    try:
        cal.refresh_token_encrypted = encrypt(refresh)
    except CryptoNotConfigured as exc:
        raise CalendarError(str(exc)) from exc
    cal.account_email = _id_token_email(str(body.get("id_token") or "")) or cal.account_email
    cal.scopes = granted[:500]
    cal.connected_at = _utcnow()
    cal.last_error = ""
    if not cal.check_calendars:
        cal.check_calendars = ["primary"]
    db.commit()
    _remember(refresh, body["access_token"], body.get("expires_in"))
    return cal


def disconnect(db: Session) -> ExamCalendar:
    cal = settings_row(db)
    if cal.refresh_token_encrypted:
        try:
            _google("POST", REVOKE_URL, data={"token": decrypt(cal.refresh_token_encrypted)})
        except (CalendarError, CryptoNotConfigured):
            log.warning("Could not revoke the calendar token; clearing it anyway")
    cal.refresh_token_encrypted = ""
    cal.connected_at = None
    cal.scopes = ""
    _TOKEN.clear()
    db.commit()
    return cal


def _access_token(cal: ExamCalendar) -> str:
    if not cal.refresh_token_encrypted:
        raise CalendarError("The calendar is not connected.")
    try:
        refresh = decrypt(cal.refresh_token_encrypted)
    except CryptoNotConfigured as exc:
        raise CalendarError(str(exc)) from exc
    key = hashlib.sha256(refresh.encode()).hexdigest()
    if _TOKEN.get("key") == key and _TOKEN.get("until", 0) > time.time():
        return _TOKEN["token"]
    client_id, secret = _client(cal)
    status, body = _google("POST", TOKEN_URL, data={
        "client_id": client_id, "client_secret": secret,
        "refresh_token": refresh, "grant_type": "refresh_token",
    })
    if status != 200 or not body.get("access_token"):
        if body.get("error") == "invalid_grant":
            raise CalendarError("Google withdrew the calendar permission. Connect the calendar again.")
        raise CalendarError(f"Google refused the calendar permission: {_google_error(body)}")
    _remember(refresh, body["access_token"], body.get("expires_in"))
    return body["access_token"]


def _api(cal: ExamCalendar, method: str, path: str, *, json_body=None, params=None) -> tuple[int, dict]:
    status, body = _google(method, f"{API}{path}", token=_access_token(cal), json_body=json_body, params=params)
    if status == 401:  # the cached token expired early: once more, fresh
        _TOKEN.clear()
        status, body = _google(method, f"{API}{path}", token=_access_token(cal), json_body=json_body, params=params)
    return status, body


# -----------------------------------------------------------------------------
# Busy time
# -----------------------------------------------------------------------------

def _parse(value: str) -> datetime:
    return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00"))).astimezone(timezone.utc)


def busy_by_calendar(cal: ExamCalendar, start: datetime, end: datetime) -> dict[str, dict]:
    """{calendar id: {"busy": [(start, end), ...], "error": ""}} for every
    calendar checked. An error means that calendar could not be read."""
    ids = list(dict.fromkeys(cal.check_calendars or ["primary"]))
    status, body = _api(cal, "POST", "/freeBusy", json_body={
        "timeMin": _iso(start), "timeMax": _iso(end), "items": [{"id": i} for i in ids],
    })
    if status != 200:
        raise CalendarError(f"Google refused the availability check: {_google_error(body)}")
    found = body.get("calendars") or {}
    out: dict[str, dict] = {}
    for cid in ids:
        entry = found.get(cid)
        if entry is None and cid == "primary" and cal.account_email:
            entry = found.get(cal.account_email)
        if entry is None:
            out[cid] = {"busy": [], "error": "not returned by Google"}
            continue
        if entry.get("errors"):
            reasons = ", ".join(str(e.get("reason") or "error") for e in entry["errors"])
            out[cid] = {"busy": [], "error": reasons}
            continue
        out[cid] = {
            "busy": [(_parse(b["start"]), _parse(b["end"])) for b in entry.get("busy") or []],
            "error": "",
        }
    return out


def busy_blocks(cal: ExamCalendar, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Busy time across every checked calendar. Fails if any cannot be read."""
    per = busy_by_calendar(cal, start, end)
    problems = {cid: v["error"] for cid, v in per.items() if v["error"]}
    if problems:
        cid, why = next(iter(problems.items()))
        raise CalendarError(
            f"Calendar {cid} cannot be read ({why}). If it is your personal calendar, share it "
            f"with {cal.account_email or 'the connected account'} with \"See only free/busy\"."
        )
    return sorted(b for v in per.values() for b in v["busy"])


# -----------------------------------------------------------------------------
# Open slots
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Rules:
    tz: ZoneInfo
    weekly: dict
    minutes: int
    step: int
    buffer: int
    notice_hours: int
    horizon_days: int
    max_per_day: int


def rules(cal: ExamCalendar, minutes: int | None = None) -> Rules:
    weekly = {}
    for d in DAYS:
        windows = []
        for a, b in (cal.weekly_hours or {}).get(d, []) or []:
            ha, ma = (int(x) for x in a.split(":"))
            hb, mb = (int(x) for x in b.split(":"))
            windows.append((dtime(ha, ma), dtime(hb, mb)))
        weekly[d] = windows
    return Rules(
        tz=zone(cal),
        weekly=weekly,
        minutes=minutes or get_settings().ADVANCED_INTERVIEW_MINUTES,
        step=cal.step_minutes or 30,
        buffer=cal.buffer_minutes or 0,
        notice_hours=cal.min_notice_hours or 0,
        horizon_days=cal.horizon_days or 21,
        max_per_day=cal.max_per_day or 0,
    )


def compute_slots(
    r: Rules, *, now: datetime, busy: list[tuple[datetime, datetime]],
    booked: list[datetime], earliest: datetime | None = None,
) -> list[datetime]:
    """Every examination start (UTC) that is open. Pure: no I/O.

    Inside the weekly exam hours on the instructor's clock; at least the
    minimum notice after `now` (and not before `earliest`); within the
    horizon; `buffer` minutes clear of any busy block or booked exam; on a
    day holding fewer than `max_per_day` exams (0 = no limit).
    """
    dur = timedelta(minutes=r.minutes)
    pad = timedelta(minutes=r.buffer)
    low = now + timedelta(hours=r.notice_hours)
    if earliest is not None and earliest > low:
        low = earliest
    high = now + timedelta(days=r.horizon_days)
    blocks = [(s - pad, e + pad) for s, e in busy] + [(b - pad, b + dur + pad) for b in booked]
    per_day = Counter(b.astimezone(r.tz).date() for b in booked)
    out: list[datetime] = []
    day = low.astimezone(r.tz).date()
    last = high.astimezone(r.tz).date()
    while day <= last:
        if r.max_per_day <= 0 or per_day[day] < r.max_per_day:
            for a, b in r.weekly.get(DAYS[day.weekday()], []):
                t = datetime.combine(day, a, tzinfo=r.tz)
                stop = datetime.combine(day, b, tzinfo=r.tz)
                while t + dur <= stop:
                    s = t.astimezone(timezone.utc)
                    if low <= s and s + dur <= high and not any(
                        bs < s + dur and s < be for bs, be in blocks
                    ):
                        out.append(s)
                    t += timedelta(minutes=r.step)
        day += timedelta(days=1)
    return sorted(set(out))


def booked_exam_starts(db: Session, *, exclude_row: int | None = None) -> list[datetime]:
    """Every oral examination already booked, on any course."""
    q = select(AdvancedCertification.scheduled_at, AdvancedCertification.id).where(
        AdvancedCertification.status == "scheduled",
        AdvancedCertification.scheduled_at.is_not(None),
    )
    return [
        _aware(at).astimezone(timezone.utc)
        for at, row_id in db.execute(q).all()
        if row_id != exclude_row
    ]


def open_slots(
    db: Session, *, earliest: datetime | None = None, now: datetime | None = None,
    record: bool = True, exclude_row: int | None = None,
) -> list[datetime]:
    """Open slots from the live calendars. Raises CalendarError if any
    checked calendar cannot be read. `record=False` leaves the transaction
    alone (the booking holds a lock until it commits)."""
    cal = settings_row(db)
    r = rules(cal)
    now = now or _utcnow()
    low = now + timedelta(hours=r.notice_hours)
    if earliest is not None and earliest > low:
        low = earliest
    high = now + timedelta(days=r.horizon_days)
    if low >= high:
        return []
    pad = timedelta(minutes=r.buffer, hours=1)
    busy = busy_blocks(cal, low - pad, high + pad)
    slots = compute_slots(
        r, now=now, busy=busy, booked=booked_exam_starts(db, exclude_row=exclude_row), earliest=earliest
    )
    if record:
        cal.last_ok_at = now
        cal.last_error = ""
        db.commit()
    return slots


def lock(db: Session) -> ExamCalendar:
    """Serialise bookings: two candidates must not both get the last slot.
    Held until the booking's transaction commits (ignored on SQLite)."""
    settings_row(db)
    return db.execute(
        select(ExamCalendar).where(ExamCalendar.id == 1).with_for_update()
    ).scalar_one()


def check_each(db: Session, days: int = 7) -> list[dict]:
    """The admin's Test button: can each checked calendar be read?"""
    cal = settings_row(db)
    now = _utcnow()
    per = busy_by_calendar(cal, now, now + timedelta(days=days))
    return [
        {"id": cid, "ok": not v["error"], "error": v["error"], "busy_blocks": len(v["busy"])}
        for cid, v in per.items()
    ]


def note_failure(db: Session, message: str, *, alert: bool = True) -> bool:
    """Record a calendar failure. Returns True when the instructor should be
    emailed about it (at most once every 12 hours). `alert=False` when he is
    looking at the error in the admin panel already."""
    cal = settings_row(db)
    cal.last_error = (message or "")[:500]
    now = _utcnow()
    due = alert and (cal.last_alert_at is None or now - _aware(cal.last_alert_at) > timedelta(hours=12))
    if due:
        cal.last_alert_at = now
    db.commit()
    return due


# -----------------------------------------------------------------------------
# Events on his calendar
# -----------------------------------------------------------------------------

def _meet_link(event: dict) -> str:
    if event.get("hangoutLink"):
        return str(event["hangoutLink"])
    for ep in ((event.get("conferenceData") or {}).get("entryPoints") or []):
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return str(ep["uri"])
    return ""


def _events_path(cal: ExamCalendar, event_id: str = "") -> str:
    path = f"/calendars/{quote(cal.event_calendar or 'primary', safe='')}/events"
    return f"{path}/{quote(event_id, safe='')}" if event_id else path


def create_event(
    db: Session, *, start: datetime, minutes: int, summary: str, description: str,
    guest_email: str, guest_name: str = "", meeting_url: str = "", row_id: int | None = None,
) -> dict:
    """Put the examination on his calendar and invite the candidate.
    Without a meeting link of his own, Google Meet makes one."""
    cal = settings_row(db)
    start = _aware(start).astimezone(timezone.utc)
    end = start + timedelta(minutes=minutes)
    body: dict = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": _iso(start), "timeZone": cal.timezone},
        "end": {"dateTime": _iso(end), "timeZone": cal.timezone},
        "attendees": [{"email": guest_email, "displayName": guest_name or guest_email}],
        "guestsCanInviteOthers": False,
        "guestsCanSeeOtherGuests": False,
        "reminders": {"useDefault": True},
        "extendedProperties": {"private": {"proreadyExamRow": str(row_id or "")}},
    }
    params: dict = {"sendUpdates": "all"}
    if meeting_url:
        body["location"] = meeting_url
        body["description"] = f"{description}\n\nJoin: {meeting_url}"
    else:
        body["conferenceData"] = {"createRequest": {
            "requestId": uuid.uuid4().hex, "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }}
        params["conferenceDataVersion"] = 1
    status, event = _api(cal, "POST", _events_path(cal), json_body=body, params=params)
    if status not in (200, 201) or not event.get("id"):
        raise CalendarError(f"Google refused the calendar event: {_google_error(event)}")
    link = meeting_url or _meet_link(event)
    tries = 0
    while not link and tries < 3:  # the Meet link can take a moment
        tries += 1
        time.sleep(1)
        st, again = _api(cal, "GET", _events_path(cal, event["id"]), params={"conferenceDataVersion": 1})
        if st == 200:
            link = _meet_link(again)
    return {"id": event["id"], "meeting_url": link, "html_link": event.get("htmlLink", "")}


def move_event(db: Session, event_id: str, start: datetime, minutes: int) -> None:
    cal = settings_row(db)
    start = _aware(start).astimezone(timezone.utc)
    end = start + timedelta(minutes=minutes)
    status, body = _api(cal, "PATCH", _events_path(cal, event_id), params={"sendUpdates": "all"}, json_body={
        "start": {"dateTime": _iso(start), "timeZone": cal.timezone},
        "end": {"dateTime": _iso(end), "timeZone": cal.timezone},
    })
    if status != 200:
        raise CalendarError(f"Google refused to move the event: {_google_error(body)}")


def delete_event(db: Session, event_id: str) -> None:
    """Remove the event; Google tells the candidate it is cancelled."""
    cal = settings_row(db)
    status, body = _api(cal, "DELETE", _events_path(cal, event_id), params={"sendUpdates": "all"})
    if status not in (200, 204, 404, 410):
        raise CalendarError(f"Google refused to remove the event: {_google_error(body)}")


def day_lines(slots: list[datetime], tz: ZoneInfo) -> list[str]:
    """'Tuesday, October 20 at 09:00' lines on the instructor's clock."""
    return [s.astimezone(tz).strftime("%A, %B %d at %H:%M") for s in slots]


def start_of_day(d: date, cal: ExamCalendar) -> datetime:
    return datetime.combine(d, dtime(0, 0), tzinfo=zone(cal)).astimezone(timezone.utc)
