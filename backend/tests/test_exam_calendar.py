"""Oral examinations booked from the instructor's own calendar.

The owner asked (2026-10-17) to hear when a candidate passes the written
exam, to hear when they choose an interview time, and that the times on
offer come from his real calendar — his company calendar and his personal
one. This file covers:

  * the slot arithmetic (exam hours on his clock, notice, buffer, busy time,
    daily cap, daylight-saving change, the re-examination's study period);
  * connecting Google (consent URL, signed state, scopes, encrypted storage,
    secrets never returned);
  * a candidate booking a slot: event with Meet link and invitation on his
    calendar, emails to both, a taken slot refused, the fallback when a
    calendar cannot be read, moving / releasing / cancelling a booking;
  * the "[Written exam passed]" alert with the competency breakdown.

Google is faked at exam_calendar._google; email is captured at the Resend
seam. Runs on the shared SQLite DB and leaves nothing behind.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import crypto  # noqa: E402
from app import emailer as E  # noqa: E402
from app import exam_calendar as xcal  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.learner_auth import issue_login_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AdvancedCertification,
    Certificate,
    ExamCalendar,
    Learner,
    Product,
    QuizItem,
)

PRODUCT = conftest.TEST_ADVANCED_PRODUCT
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
CAL_API = "/api/admin/academy/calendar"
NY = ZoneInfo("America/New_York")
COMPANY = "bassam.abdelnabi@proreadyengineer.com"
PERSONAL = "bmsabry@gmail.com"
FERNET_KEY = "u5Ml1_hZ8b7cQvVQ0M6RH8HRlqYRIbNJ0lWfR0dO5vE="

ALICE = "cal.alice@example.com"   # books from the calendar
BOB = "cal.bob@example.com"       # wants the slot Alice just took
CARA = "cal.cara@example.com"     # passes the written exam (alert)
NAMES = {ALICE: "Alice Calendar", BOB: "Bob Second", CARA: "Cara Passes"}
CERT_CODES = {email: f"PRE-C-CALX-{n:04d}" for n, email in enumerate(NAMES, 1)}


# -----------------------------------------------------------------------------
# A fake Google: token endpoint, FreeBusy, events
# -----------------------------------------------------------------------------

def _id_token(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"x.{payload}.y"


class FakeGoogle:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.busy: dict[str, list[tuple[datetime, datetime]]] = {"primary": [], PERSONAL: []}
        self.errors: dict[str, str] = {}
        self.events: dict[str, dict] = {}
        self.granted = xcal.SCOPES.replace("openid email ", "openid https://www.googleapis.com/auth/userinfo.email ")
        self.refresh_ok = True
        self.n = 0

    def __call__(self, method, url, *, token=None, data=None, json_body=None, params=None):
        self.calls.append((method, url, {"data": data, "json": json_body, "params": params, "token": token}))
        if url == xcal.TOKEN_URL:
            if data.get("grant_type") == "authorization_code":
                return 200, {
                    "access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
                    "scope": self.granted, "id_token": _id_token(COMPANY),
                }
            if not self.refresh_ok:
                return 400, {"error": "invalid_grant"}
            return 200, {"access_token": "at-2", "expires_in": 3600}
        if url == xcal.REVOKE_URL:
            return 200, {}
        assert token, "calendar API called without a token"
        if url.endswith("/freeBusy"):
            out = {}
            for item in json_body["items"]:
                cid = item["id"]
                if cid in self.errors:
                    out[cid] = {"errors": [{"domain": "global", "reason": self.errors[cid]}], "busy": []}
                    continue
                blocks = list(self.busy.get(cid, []))
                if cid == "primary":  # his own events, including exams booked through us
                    blocks += [(e["_start"], e["_end"]) for e in self.events.values()]
                out[cid] = {"busy": [
                    {"start": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": e.strftime("%Y-%m-%dT%H:%M:%SZ")}
                    for s, e in blocks
                ]}
            return 200, {"calendars": out}
        if "/events" in url:
            if method == "POST":
                self.n += 1
                eid = f"evt{self.n}"
                ev = dict(json_body)
                ev["_start"] = datetime.fromisoformat(json_body["start"]["dateTime"].replace("Z", "+00:00"))
                ev["_end"] = datetime.fromisoformat(json_body["end"]["dateTime"].replace("Z", "+00:00"))
                ev["_params"] = params
                self.events[eid] = ev
                out = {"id": eid, "htmlLink": f"https://calendar.google.com/event?eid={eid}"}
                if "conferenceData" in json_body:
                    out["hangoutLink"] = f"https://meet.google.com/abc-{eid}"
                return 200, out
            eid = url.rsplit("/", 1)[-1]
            if method == "PATCH":
                ev = self.events[eid]
                ev["_start"] = datetime.fromisoformat(json_body["start"]["dateTime"].replace("Z", "+00:00"))
                ev["_end"] = datetime.fromisoformat(json_body["end"]["dateTime"].replace("Z", "+00:00"))
                return 200, {"id": eid}
            if method == "DELETE":
                self.events.pop(eid, None)
                return 204, {}
            if method == "GET":
                return 200, {"id": eid, "hangoutLink": f"https://meet.google.com/abc-{eid}"}
        raise AssertionError(f"unexpected Google call {method} {url}")


@pytest.fixture()
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(xcal, "_google", fake)
    xcal._TOKEN.clear()
    return fake


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-cal"}


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1])
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


@pytest.fixture(scope="module", autouse=True)
def world():
    """Three finishers with access and a completion certificate, the tier on
    at $300, an encryption key for the stored secrets. All undone after."""
    old_key = os.environ.get("AI_SETTINGS_KEY")
    os.environ["AI_SETTINGS_KEY"] = FERNET_KEY
    crypto._fernet.cache_clear()
    with TestClient(app, base_url="https://testserver") as c:
        for email, name in NAMES.items():
            r = c.post("/api/admin/academy/grant", json={
                "email": email, "product_code": PRODUCT, "full_name": name, "send_email_invite": False,
            }, headers=ADMIN)
            assert r.status_code == 200, r.text
    db = SessionLocal()
    product = db.get(Product, PRODUCT)
    was = (product.advanced_cert_enabled, product.advanced_cert_price_cents)
    product.advanced_cert_enabled = True
    product.advanced_cert_price_cents = 30000
    ids = {l.email: l.id for l in db.query(Learner).filter(Learner.email.in_(NAMES)).all()}
    for email, code in CERT_CODES.items():
        db.add(Certificate(
            learner_id=ids[email], product_code=PRODUCT, code=code, learner_name=NAMES[email],
            tier="completion", status="issued", course_title=product.title,
            issued_at=datetime.now(timezone.utc),
        ))
    db.query(ExamCalendar).delete()
    db.commit()
    db.close()

    clients = {}
    for email in NAMES:
        c = TestClient(app, base_url="https://testserver")
        c.__enter__()
        db = SessionLocal()
        raw = issue_login_token(db, db.query(Learner).filter(Learner.email == email).one())
        db.close()
        assert c.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
        me = c.get("/api/academy/me").json()
        c.post("/api/academy/accept-terms", json={"version": me["terms_version"]})
        clients[email] = c
    yield {"clients": clients, "ids": ids}

    for c in clients.values():
        c.__exit__(None, None, None)
    from app.progress_guard import allow_progress_loss

    db = SessionLocal()
    db.query(AdvancedCertification).filter(
        AdvancedCertification.learner_id.in_(list(ids.values()))
    ).delete(synchronize_session=False)
    db.query(ExamCalendar).delete()
    with allow_progress_loss("test fixture: remove synthetic certificates"):
        db.query(Certificate).filter(Certificate.code.in_(CERT_CODES.values())).delete(
            synchronize_session=False
        )
        db.commit()
    product = db.get(Product, PRODUCT)
    product.advanced_cert_enabled, product.advanced_cert_price_cents = was
    db.commit()
    db.close()
    xcal._TOKEN.clear()
    if old_key is None:
        os.environ.pop("AI_SETTINGS_KEY", None)
    else:
        os.environ["AI_SETTINGS_KEY"] = old_key
    crypto._fernet.cache_clear()


def _admin() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _row_for(email: str, status: str = "exam_passed", **extra) -> int:
    """An examination at the scheduling step, made directly."""
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == email).one()
    db.query(AdvancedCertification).filter(AdvancedCertification.learner_id == learner.id).delete()
    fields = dict(
        learner_id=learner.id, product_code=PRODUCT, source="manual", amount_cents=0,
        currency="usd", status=status, fee_status="waived", exam_attempts=1, exam_best_pct=90.0,
    )
    fields.update(extra)
    row = AdvancedCertification(**fields)
    db.add(row)
    db.commit()
    rid = row.id
    db.close()
    return rid


def _to(outbox, addr):
    return [m for m in outbox if addr in m["to"]]


def _connect(google) -> None:
    """Paste the OAuth client, go through consent, add the personal calendar."""
    with _admin() as admin:
        r = admin.put(CAL_API, json={"client_id": "cid-123.apps.googleusercontent.com",
                                     "client_secret": "s3cret-value"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        url = admin.post(f"{CAL_API}/connect", headers=ADMIN).json()["url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        r = admin.get(f"{CAL_API}/google/callback", params={"code": "c0de", "state": state},
                      headers=ADMIN, follow_redirects=False)
        assert r.status_code == 303 and "calendar=connected" in r.headers["location"], r.headers
        r = admin.put(CAL_API, json={"check_calendars": ["primary", PERSONAL]}, headers=ADMIN)
        assert r.status_code == 200


# -----------------------------------------------------------------------------
# 1. The slot arithmetic (pure)
# -----------------------------------------------------------------------------

def _rules(**over) -> xcal.Rules:
    base = dict(
        tz=NY,
        weekly={d: ([(time(9), time(17))] if i < 5 else []) for i, d in enumerate(xcal.DAYS)},
        minutes=60, step=30, buffer=30, notice_hours=48, horizon_days=14, max_per_day=2,
    )
    base.update(over)
    return xcal.Rules(**base)


def _ny(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=NY).astimezone(timezone.utc)


def test_slots_sit_inside_exam_hours_on_weekdays_only():
    now = _ny(2026, 10, 12, 8)  # Monday 08:00 New York
    slots = xcal.compute_slots(_rules(), now=now, busy=[], booked=[])
    local = [s.astimezone(NY) for s in slots]
    assert local, "some slots"
    assert all(t.weekday() < 5 for t in local)
    assert all(time(9) <= t.time() and (t + timedelta(hours=1)).time() <= time(17) for t in local)
    # 48 hours of notice: nothing before Wednesday 08:00.
    assert min(slots) >= now + timedelta(hours=48)
    assert local[0] == datetime(2026, 10, 14, 9, 0, tzinfo=NY)
    # Every 30 minutes: 09:00 … 16:00 is 15 starts a day.
    assert sum(1 for t in local if t.date() == date(2026, 10, 14)) == 15


def test_busy_time_and_its_buffer_block_slots():
    now = _ny(2026, 10, 12, 8)
    busy = [(_ny(2026, 10, 14, 11), _ny(2026, 10, 14, 12))]
    day = [s.astimezone(NY).strftime("%H:%M") for s in
           xcal.compute_slots(_rules(), now=now, busy=busy, booked=[])
           if s.astimezone(NY).date() == date(2026, 10, 14)]
    # An hour-long exam needs 30 minutes clear either side of 11:00–12:00.
    assert "09:30" in day and "10:00" not in day and "12:00" not in day and "12:30" in day


def test_daily_cap_counts_booked_exams():
    now = _ny(2026, 10, 12, 8)
    booked = [_ny(2026, 10, 14, 9), _ny(2026, 10, 14, 14)]
    slots = xcal.compute_slots(_rules(), now=now, busy=[], booked=booked)
    assert not any(s.astimezone(NY).date() == date(2026, 10, 14) for s in slots)
    one = xcal.compute_slots(_rules(), now=now, busy=[], booked=booked[:1])
    on_day = [s.astimezone(NY).strftime("%H:%M") for s in one if s.astimezone(NY).date() == date(2026, 10, 14)]
    assert on_day and "09:00" not in on_day and "10:30" in on_day  # booked hour + buffer kept clear


def test_hours_follow_his_clock_across_the_daylight_saving_change():
    now = _ny(2026, 10, 28, 8)
    slots = xcal.compute_slots(_rules(horizon_days=10), now=now, busy=[], booked=[])
    first = {s.astimezone(NY).date(): s for s in slots if s.astimezone(NY).strftime("%H:%M") == "09:00"}
    assert first[date(2026, 10, 30)].strftime("%H:%M") == "13:00"  # EDT
    assert first[date(2026, 11, 2)].strftime("%H:%M") == "14:00"   # EST


def test_re_examination_waits_for_the_study_period():
    now = _ny(2026, 10, 12, 8)
    earliest = _ny(2026, 10, 20, 0)
    slots = xcal.compute_slots(_rules(horizon_days=21), now=now, busy=[], booked=[], earliest=earliest)
    assert min(slots).astimezone(NY) == datetime(2026, 10, 20, 9, 0, tzinfo=NY)


# -----------------------------------------------------------------------------
# 2. Connecting Google
# -----------------------------------------------------------------------------

def test_settings_defaults_and_validation(google):
    with _admin() as admin:
        assert admin.get(CAL_API).status_code == 401  # admin only
        body = admin.get(CAL_API, headers=ADMIN).json()
        assert body["connected"] is False and body["timezone"] == "America/New_York"
        assert body["weekly_hours"]["mon"] == [["09:00", "17:00"]] and body["weekly_hours"]["sat"] == []
        assert body["redirect_uri"] == "https://api.proreadyengineer.com/api/admin/academy/calendar/google/callback"
        for bad in ({"timezone": "Mars/Base"}, {"weekly_hours": {"mon": [["17:00", "09:00"]]}},
                    {"weekly_hours": {"mon": [["9am", "5pm"]]}}, {"buffer_minutes": 999},
                    {"step_minutes": 20}):
            assert admin.put(CAL_API, json=bad, headers=ADMIN).status_code == 422, bad
        # Connecting needs the OAuth client first.
        assert admin.post(f"{CAL_API}/connect", headers=ADMIN).status_code == 409


def test_connect_stores_the_permission_encrypted_and_never_returns_secrets(google):
    with _admin() as admin:
        r = admin.put(CAL_API, json={"client_id": "cid-123.apps.googleusercontent.com",
                                     "client_secret": "s3cret-value"}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["client_secret_set"] is True
        assert "s3cret-value" not in r.text
        url = admin.post(f"{CAL_API}/connect", headers=ADMIN).json()["url"]
        q = parse_qs(urlparse(url).query)
        assert url.startswith(xcal.AUTH_URL)
        assert q["client_id"] == ["cid-123.apps.googleusercontent.com"]
        assert q["redirect_uri"] == [xcal.redirect_uri()]
        assert "calendar.freebusy" in q["scope"][0] and "calendar.events" in q["scope"][0]
        assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]

        # A forged or stale state is refused, and nothing is stored.
        r = admin.get(f"{CAL_API}/google/callback", params={"code": "c", "state": "forged"},
                      headers=ADMIN, follow_redirects=False)
        assert r.status_code == 303 and "calendar_error=" in r.headers["location"]
        # Cancelled on Google's screen.
        r = admin.get(f"{CAL_API}/google/callback", params={"error": "access_denied"},
                      headers=ADMIN, follow_redirects=False)
        assert "cancelled" in r.headers["location"]
        # Boxes left unticked on Google's screen: refused.
        google.granted = "openid email https://www.googleapis.com/auth/calendar.freebusy"
        r = admin.get(f"{CAL_API}/google/callback", params={"code": "c", "state": q["state"][0]},
                      headers=ADMIN, follow_redirects=False)
        assert "calendar_error=" in r.headers["location"]
        assert admin.get(CAL_API, headers=ADMIN).json()["connected"] is False

        google.granted = FakeGoogle().granted
        r = admin.get(f"{CAL_API}/google/callback", params={"code": "c", "state": q["state"][0]},
                      headers=ADMIN, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "https://proreadyengineer.com/admin?calendar=connected#certification"
        body = admin.get(CAL_API, headers=ADMIN).json()
        assert body["connected"] is True and body["account_email"] == COMPANY
        assert "rt-1" not in json.dumps(body) and "s3cret" not in json.dumps(body)
    db = SessionLocal()
    cal = db.get(ExamCalendar, 1)
    assert cal.refresh_token_encrypted and "rt-1" not in cal.refresh_token_encrypted
    assert crypto.decrypt(cal.refresh_token_encrypted) == "rt-1"
    assert "s3cret-value" not in cal.client_secret_encrypted
    db.close()


def test_the_admin_test_names_a_calendar_that_is_not_shared(google):
    _connect(google)
    google.errors[PERSONAL] = "notFound"
    with _admin() as admin:
        r = admin.post(f"{CAL_API}/test", headers=ADMIN)
        assert r.status_code == 200
        by_id = {c["id"]: c for c in r.json()["calendars"]}
        assert by_id["primary"]["ok"] is True and by_id[PERSONAL]["ok"] is False
        assert by_id[PERSONAL]["error"] == "notFound"
        # The preview refuses rather than offering slots it cannot vouch for.
        r = admin.get(f"{CAL_API}/preview", headers=ADMIN)
        assert r.status_code == 502 and PERSONAL in r.json()["detail"]
    google.errors.clear()
    with _admin() as admin:
        r = admin.get(f"{CAL_API}/preview", headers=ADMIN)
        assert r.status_code == 200 and r.json()["count"] > 0
        assert r.json()["slots"][0]["label"]


# -----------------------------------------------------------------------------
# 3. Booking a slot
# -----------------------------------------------------------------------------

def test_a_candidate_books_an_open_slot(world, google, outbox):
    _connect(google)
    rid = _row_for(ALICE)
    alice = world["clients"][ALICE]
    state = alice.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["can_propose"] is True and state["booking"] == "calendar"

    # His personal calendar is busy all of one weekday: no slot that day.
    now = datetime.now(timezone.utc)
    blocked_day = (now + timedelta(days=5)).astimezone(NY).date()
    google.busy[PERSONAL] = [(datetime.combine(blocked_day, time(0), tzinfo=NY).astimezone(timezone.utc),
                              datetime.combine(blocked_day, time(23, 59), tzinfo=NY).astimezone(timezone.utc))]
    r = alice.get(f"/api/academy/advanced/{PRODUCT}/booking")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "calendar" and body["examiner_timezone"] == "America/New_York"
    slots = [datetime.fromisoformat(s.replace("Z", "+00:00")) for s in body["slots"]]
    assert slots and all(s >= now + timedelta(hours=47) for s in slots)
    assert not any(s.astimezone(NY).date() == blocked_day for s in slots)

    # A time that is not offered is refused.
    odd = slots[0] + timedelta(minutes=7)
    assert alice.post(f"/api/academy/advanced/{PRODUCT}/book", json={"start": odd.isoformat()}).status_code == 409

    pick = slots[0]
    r = alice.post(f"/api/academy/advanced/{PRODUCT}/book",
                   json={"start": pick.isoformat(), "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    state = r.json()["state"]
    assert state["status"] == "scheduled" and state["calendar_invite"] is True
    assert state["meeting_url"].startswith("https://meet.google.com/")

    # The event is on his calendar, with Meet, the candidate invited by Google.
    (eid, ev), = google.events.items()
    assert ev["_start"] == pick and ev["_end"] == pick + timedelta(minutes=60)
    assert ev["attendees"] == [{"email": ALICE, "displayName": "Alice Calendar"}]
    assert ev["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
    assert ev["_params"]["sendUpdates"] == "all" and ev["_params"]["conferenceDataVersion"] == 1
    assert ev["guestsCanSeeOtherGuests"] is False
    assert "Alice Calendar" in ev["summary"]
    db = SessionLocal()
    row = db.get(AdvancedCertification, rid)
    assert row.calendar_event_id == eid and row.booked_via == "candidate"
    assert row.learner_timezone == "Europe/Berlin"
    db.close()

    # Both are told: the candidate (no .ics — Google's invitation carries it)…
    mine = _to(outbox, ALICE)
    assert len(mine) == 1 and mine[0]["subject"].startswith("Your oral examination is booked")
    assert "attachments" not in mine[0] and COMPANY in mine[0]["html"]
    assert "Europe/Berlin" in mine[0]["html"]
    # …and the instructor, with the time on both clocks and the Meet link.
    alerts = [m for m in _to(outbox, get_settings().ADMIN_NOTIFY_EMAIL)
              if m["subject"].startswith("[Oral exam booked]")]
    assert len(alerts) == 1
    assert "US Eastern" in alerts[0]["html"] and "meet.google.com" in alerts[0]["html"]
    assert "#courses/" in alerts[0]["html"] or "#certification" in alerts[0]["html"]

    # A second booking is refused: the examination is already booked.
    assert alice.post(f"/api/academy/advanced/{PRODUCT}/book",
                      json={"start": slots[1].isoformat()}).status_code == 409


def test_the_slot_just_taken_is_refused_to_the_next_candidate(world, google):
    _connect(google)
    _row_for(BOB)
    bob = world["clients"][BOB]
    slots = bob.get(f"/api/academy/advanced/{PRODUCT}/booking").json()["slots"]
    first = datetime.fromisoformat(slots[0].replace("Z", "+00:00"))
    # Alice's exam (previous test) sits on the calendar: Bob is not offered it.
    db = SessionLocal()
    alice_row = db.query(AdvancedCertification).filter(
        AdvancedCertification.learner_id == world["ids"][ALICE]).one()
    taken = xcal._aware(alice_row.scheduled_at)
    db.close()
    assert taken.strftime("%Y-%m-%dT%H:%M:%SZ") not in slots
    # Someone else books Bob's chosen time on the calendar before he clicks.
    google.busy["primary"] = [(first, first + timedelta(hours=1))]
    r = bob.post(f"/api/academy/advanced/{PRODUCT}/book", json={"start": first.isoformat()})
    assert r.status_code == 409 and "no longer free" in r.json()["detail"]
    google.busy["primary"] = []


def test_an_unreadable_calendar_falls_back_to_proposing_and_tells_him_once(world, google, outbox):
    _connect(google)
    _row_for(BOB)
    google.errors[PERSONAL] = "notFound"
    bob = world["clients"][BOB]
    for _ in range(2):
        r = bob.get(f"/api/academy/advanced/{PRODUCT}/booking")
        assert r.status_code == 200 and r.json()["mode"] == "propose" and r.json()["notice"]
    alerts = [m for m in outbox if m["subject"].startswith("[Calendar]")]
    assert len(alerts) == 1 and "notFound" in alerts[0]["html"]
    # Proposing windows still works as before.
    future = [(datetime.now(timezone.utc) + timedelta(days=4)).isoformat()]
    r = bob.post(f"/api/academy/advanced/{PRODUCT}/slots", json={"slots": future, "timezone": "UTC"})
    assert r.status_code == 200 and r.json()["state"]["status"] == "slots_proposed"
    google.errors.clear()
    with _admin() as admin:
        assert "notFound" in admin.get(CAL_API, headers=ADMIN).json()["last_error"]


def test_he_can_move_release_and_cancel_a_booking(world, google, outbox):
    _connect(google)
    db = SessionLocal()
    row = db.query(AdvancedCertification).filter(
        AdvancedCertification.learner_id == world["ids"][ALICE]).one()
    rid, eid, old = row.id, row.calendar_event_id, xcal._aware(row.scheduled_at)
    db.close()
    google.events.setdefault(eid, {"_start": old, "_end": old + timedelta(hours=1)})
    new_time = old + timedelta(days=1)
    with _admin() as admin:
        r = admin.post(f"/api/admin/academy/certification/advanced/{rid}/schedule",
                       json={"at": new_time.isoformat()}, headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["calendar_event_id"] == eid and r.json()["booked_via"] == "candidate"
    assert google.events[eid]["_start"] == new_time
    moved = _to(outbox, ALICE)[-1]
    assert moved["subject"].startswith("Your oral examination has a new time")
    assert "attachments" not in moved

    with _admin() as admin:
        r = admin.post(f"/api/admin/academy/certification/advanced/{rid}/reopen", headers=ADMIN)
        assert r.status_code == 200 and r.json()["status"] == "exam_passed"
        assert r.json()["calendar_event_id"] == ""
    assert eid not in google.events, "the event came off his calendar"

    # Booked by hand: the event is made too, with his own link if he gives one.
    with _admin() as admin:
        r = admin.post(f"/api/admin/academy/certification/advanced/{rid}/schedule",
                       json={"at": new_time.isoformat(), "meeting_url": "https://zoom.us/j/9"},
                       headers=ADMIN)
        assert r.status_code == 200 and r.json()["booked_via"] == "admin"
        eid2 = r.json()["calendar_event_id"]
        assert google.events[eid2]["location"] == "https://zoom.us/j/9"
        assert "conferenceData" not in google.events[eid2]
        r = admin.post(f"/api/admin/academy/certification/advanced/{rid}/cancel",
                       json={"note": "candidate withdrew"}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert eid2 not in google.events


def test_a_lost_permission_stops_booking_and_falls_back(world, google, outbox):
    _connect(google)
    _row_for(BOB)
    xcal._TOKEN.clear()
    google.refresh_ok = False
    r = world["clients"][BOB].get(f"/api/academy/advanced/{PRODUCT}/booking")
    assert r.json()["mode"] == "propose"
    with _admin() as admin:
        assert "Connect the calendar again" in admin.get(CAL_API, headers=ADMIN).json()["last_error"]
    google.refresh_ok = True


def test_fee_due_and_study_period_still_lock_booking(world, google):
    _connect(google)
    _row_for(BOB, fee_status="due", amount_cents=30000)
    db = SessionLocal()
    row = db.query(AdvancedCertification).filter(AdvancedCertification.learner_id == world["ids"][BOB]).one()
    row.fee_status = "due"
    db.commit()
    db.close()
    bob = world["clients"][BOB]
    assert bob.get(f"/api/academy/advanced/{PRODUCT}/booking").status_code == 409
    # Re-examination: nothing before the study period ends.
    after = date.today() + timedelta(days=9)
    _row_for(BOB, status="retake_pending", interview_no=2, retake_after=after)
    r = bob.get(f"/api/academy/advanced/{PRODUCT}/booking")
    assert r.status_code == 409 and "on or after" in r.json()["detail"]
    db = SessionLocal()
    row = db.query(AdvancedCertification).filter(AdvancedCertification.learner_id == world["ids"][BOB]).one()
    row.retake_after = date.today()
    db.commit()
    db.close()
    slots = bob.get(f"/api/academy/advanced/{PRODUCT}/booking").json()["slots"]
    assert slots


def test_switching_self_booking_off_returns_to_proposing(world, google):
    _connect(google)
    _row_for(BOB)
    with _admin() as admin:
        assert admin.put(CAL_API, json={"self_booking": False}, headers=ADMIN).status_code == 200
    state = world["clients"][BOB].get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["booking"] == "propose"
    with _admin() as admin:
        admin.put(CAL_API, json={"self_booking": True}, headers=ADMIN)
        r = admin.post(f"{CAL_API}/disconnect", headers=ADMIN)
        assert r.status_code == 200 and r.json()["connected"] is False
    assert any(url == xcal.REVOKE_URL for _, url, _ in google.calls)


# -----------------------------------------------------------------------------
# 4. He hears the moment the written exam is passed
# -----------------------------------------------------------------------------

def test_passing_the_written_exam_alerts_him_with_the_breakdown(world, google, outbox):
    _connect(google)
    _row_for(CARA, status="purchased")
    cara = world["clients"][CARA]
    items = cara.get(f"/api/academy/advanced/{PRODUCT}/exam").json()["items"]
    db = SessionLocal()
    key = {i.code: i.answer.get("key") for i in db.query(QuizItem).filter(
        QuizItem.product_code == PRODUCT, QuizItem.item_set == "advanced")}
    db.close()
    answers = {i["code"]: key[i["code"]] for i in items}
    wrong = items[0]["code"]  # one miss, so the weakest competency is visible
    answers[wrong] = "A"
    r = cara.post(f"/api/academy/advanced/{PRODUCT}/exam", json={"responses": answers})
    assert r.status_code == 200 and r.json()["passed"] is True
    alerts = [m for m in _to(outbox, get_settings().ADMIN_NOTIFY_EMAIL)
              if m["subject"].startswith("[Written exam passed]")]
    assert len(alerts) == 1
    a = alerts[0]
    assert "Cara Passes" in a["subject"] and f"{r.json()['score_pct']:g}%" in a["subject"]
    assert "weakest first" in a["html"] and "open slots on your calendar" in a["html"]
    # The candidate's own email is separate, and sends them to book a time.
    mine = _to(outbox, CARA)[-1]
    assert mine["subject"].startswith("Written examination passed")
    assert "Book your interview time" in mine["html"] and "propose three" not in mine["html"]


# -----------------------------------------------------------------------------
# 5. His test booking: the whole booking path, marked TEST, no candidate
# -----------------------------------------------------------------------------

GUEST = "calendar.test.guest@example.com"


def test_a_test_booking_runs_the_booking_path_and_removes_cleanly(world, google, outbox):
    """Asked for 2026-10-18 instead of a test candidate on the live site: the
    same event, Meet link, Google invitation and emails as a real booking,
    marked TEST, on the latest open time, and gone again on Remove."""
    _connect(google)
    db = SessionLocal()
    rows_before = db.query(AdvancedCertification).count()
    expected = xcal.open_slots(db, record=False)[-1]
    db.close()
    with _admin() as admin:
        assert admin.get(CAL_API, headers=ADMIN).json()["test_booking"] is None
        r = admin.post(f"{CAL_API}/test-booking", json={"guest_email": GUEST}, headers=ADMIN)
        assert r.status_code == 200, r.text
        tb = r.json()["test_booking"]
    assert tb["guest_email"] == GUEST
    assert datetime.fromisoformat(tb["start"].replace("Z", "+00:00")) == expected
    assert tb["label"] == expected.astimezone(NY).strftime("%A, %B %d at %H:%M")
    assert tb["meeting_url"].startswith("https://meet.google.com/")
    assert tb["event_link"].startswith("https://calendar.google.com/")

    # On his calendar exactly as a candidate's booking is, but named TEST.
    (eid, ev), = google.events.items()
    assert ev["_start"] == expected and ev["_end"] == expected + timedelta(minutes=60)
    assert ev["summary"].startswith("TEST — ProReadyEngineer oral examination: Test Candidate")
    assert ev["attendees"] == [{"email": GUEST, "displayName": "Test Candidate"}]
    assert ev["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
    assert ev["_params"]["sendUpdates"] == "all"

    # The candidate's email and his alert, both marked [TEST].
    guest_mail = _to(outbox, GUEST)
    assert len(guest_mail) == 1
    assert guest_mail[0]["subject"].startswith("[TEST] Your oral examination is booked")
    assert "meet.google.com" in guest_mail[0]["html"] and COMPANY in guest_mail[0]["html"]
    alerts = [m for m in _to(outbox, get_settings().ADMIN_NOTIFY_EMAIL)
              if m["subject"].startswith("[TEST] [Oral exam booked] Test Candidate")]
    assert len(alerts) == 1 and "meet.google.com" in alerts[0]["html"]
    # Neither looks like a real booking in the email log's course view.
    assert not any(m["subject"].startswith("[Oral exam booked]") for m in outbox)

    # No candidate or examination behind it, and that time is now taken.
    db = SessionLocal()
    assert db.query(AdvancedCertification).count() == rows_before
    assert expected not in xcal.open_slots(db, record=False)
    db.close()

    with _admin() as admin:
        # One at a time.
        r = admin.post(f"{CAL_API}/test-booking", json={"guest_email": GUEST}, headers=ADMIN)
        assert r.status_code == 409 and "Remove it first" in r.json()["detail"]
        r = admin.post(f"{CAL_API}/test-booking/remove", headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["test_booking"] is None
        assert admin.post(f"{CAL_API}/test-booking/remove", headers=ADMIN).status_code == 409
    assert google.events == {}
    deletes = [c for c in google.calls if c[0] == "DELETE"]
    assert deletes and deletes[-1][1].endswith(f"/events/{eid}")
    assert deletes[-1][2]["params"] == {"sendUpdates": "all"}  # Google tells the guest


def test_a_test_booking_needs_a_connection_and_goes_with_a_disconnect(world, google, outbox):
    _connect(google)
    with _admin() as admin:
        assert admin.post(f"{CAL_API}/test-booking", json={"guest_email": "not-an-email"},
                          headers=ADMIN).status_code == 422
        assert admin.post(f"{CAL_API}/test-booking", json={"guest_email": GUEST},
                          headers=ADMIN).status_code == 200
        assert len(google.events) == 1
        r = admin.post(f"{CAL_API}/disconnect", headers=ADMIN)
        assert r.status_code == 200
        assert r.json()["connected"] is False and r.json()["test_booking"] is None
    assert google.events == {}  # removed before the permission was given up
    with _admin() as admin:
        r = admin.post(f"{CAL_API}/test-booking", json={"guest_email": GUEST}, headers=ADMIN)
        assert r.status_code == 409 and "Connect your Google Calendar" in r.json()["detail"]
