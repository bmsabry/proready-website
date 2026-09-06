"""Live-session reminders: who, when, once, and who may trigger them.

Mail goes through the real emailer with Resend stubbed at the HTTP seam, so
the EmailLog rows the once-only guard relies on are written exactly as in
production.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import emailer as E
from app import session_reminders as SR
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Course, EmailLog, Registration

from conftest import ADMIN_EMAIL, ADMIN_TOKEN

ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
CODE = "reminder-test-course"
MEETING = (
    "To join the video meeting, click this link: https://meet.google.com/abc-defg-hij\n"
    "Otherwise, to join by phone, dial +1 321-430-1922 and enter this PIN: 316 913 670#\n"
    "To view more phone numbers, click this link: https://tel.meet/abc-defg-hij?hs=5"
)
DAY1 = date(2030, 3, 2)
DAY2 = date(2030, 3, 3)
START1 = datetime(2030, 3, 2, 14, 0, tzinfo=timezone.utc)


class _Resp:
    status_code = 200

    def __init__(self, i: int):
        self._id = f"msg-{i}"
        self.text = ""

    def json(self):
        return {"id": self._id}


@pytest.fixture(autouse=True)
def resend_stub(monkeypatch):
    """Resend answers 200 to everything; the payloads are captured."""
    sent: list[dict] = []

    def fake_post(url, payload, key):
        sent.append(payload)
        return _Resp(len(sent))

    monkeypatch.setattr(E, "_resend_post", fake_post)
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def course(db):
    db.execute(delete(EmailLog).where(EmailLog.scope_code == CODE))
    db.execute(delete(Registration).where(Registration.course_code == CODE))
    db.execute(delete(Course).where(Course.code == CODE))
    db.commit()
    c = Course(
        code=CODE,
        title="Reminder Test Course",
        start_date=DAY1,
        total_seats=10,
        day_dates=[DAY1.isoformat(), DAY2.isoformat()],
        session_time_utc="14:00",
        session_duration_minutes=240,
        meeting_info=MEETING,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    yield c


def _reg(db, email, *, status="pending", confirmed=True, location="Cincinnati, OH", name="Ada Lovelace"):
    r = Registration(
        course_code=CODE,
        full_name=name,
        email=email,
        job_title="Engineer",
        company="Co",
        years_experience="10",
        location=location,
        status=status,
        attendance_confirmed_at=datetime.now(timezone.utc) if confirmed else None,
    )
    db.add(r)
    db.commit()
    return r


def _fresh(db, course):
    db.expire_all()
    return db.get(Course, course.id)


# ----- who -------------------------------------------------------------------

def test_only_live_and_confirmed_registrants_get_the_link(db, course, resend_stub):
    _reg(db, "confirmed-pending@example.com")
    _reg(db, "confirmed-paid@example.com", status="paid")
    _reg(db, "unconfirmed@example.com", confirmed=False)
    _reg(db, "cancelled@example.com", status="cancelled")
    _reg(db, "Confirmed-Pending@example.com")  # same person, registered twice

    res = SR.run(db, now=START1 - timedelta(minutes=59), courses=[_fresh(db, course)])

    assert res["sent"] == 2 and res["failed"] == 0
    assert sorted(p["to"][0] for p in resend_stub) == [
        "confirmed-paid@example.com",
        "confirmed-pending@example.com",
    ]


# ----- when ------------------------------------------------------------------

@pytest.mark.parametrize(
    "offset_minutes, expected",
    [(-61, 0), (-60, 1), (-30, 1), (-1, 1), (0, 0), (30, 0)],
)
def test_the_window_is_the_hour_before_the_session(db, course, resend_stub, offset_minutes, expected):
    _reg(db, "one@example.com")
    res = SR.run(db, now=START1 + timedelta(minutes=offset_minutes), courses=[_fresh(db, course)])
    assert res["sent"] == expected


def test_each_session_day_gets_its_own_reminder(db, course, resend_stub):
    _reg(db, "one@example.com")
    c = _fresh(db, course)
    SR.run(db, now=START1 - timedelta(minutes=45), courses=[c])
    start2 = datetime.combine(DAY2, START1.timetz())
    SR.run(db, now=start2 - timedelta(minutes=45), courses=[c])
    subjects = [p["subject"] for p in resend_stub]
    assert subjects == [
        "Starts in 1 hour: Reminder Test Course — Day 1 of 2",
        "Starts in 1 hour: Reminder Test Course — Day 2 of 2",
    ]


# ----- once ------------------------------------------------------------------

def test_a_second_run_in_the_same_window_sends_nothing(db, course, resend_stub):
    _reg(db, "one@example.com")
    c = _fresh(db, course)
    for minute in (59, 49, 39, 29, 19, 9):
        SR.run(db, now=START1 - timedelta(minutes=minute), courses=[c])
    assert len(resend_stub) == 1


def test_a_late_confirmation_is_picked_up_by_the_next_run(db, course, resend_stub):
    _reg(db, "early@example.com")
    late = _reg(db, "late@example.com", confirmed=False)
    c = _fresh(db, course)
    SR.run(db, now=START1 - timedelta(minutes=55), courses=[c])
    assert [p["to"][0] for p in resend_stub] == ["early@example.com"]

    late.attendance_confirmed_at = datetime.now(timezone.utc)
    db.commit()
    SR.run(db, now=START1 - timedelta(minutes=35), courses=[c])
    assert [p["to"][0] for p in resend_stub] == ["early@example.com", "late@example.com"]


def test_a_failed_send_is_retried_while_the_window_is_open(db, course, resend_stub, monkeypatch):
    _reg(db, "one@example.com")
    c = _fresh(db, course)
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: None)  # network down
    res = SR.run(db, now=START1 - timedelta(minutes=55), courses=[c])
    assert res["failed"] == 1 and res["sent"] == 0
    monkeypatch.undo()
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    captured: list = []
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (captured.append(payload), _Resp(1))[1])
    res = SR.run(db, now=START1 - timedelta(minutes=45), courses=[c])
    assert res["sent"] == 1 and len(captured) == 1


# ----- nothing sends until the admin fills the meeting in --------------------

def test_no_meeting_info_means_no_email(db, course, resend_stub):
    _reg(db, "one@example.com")
    course.meeting_info = ""
    db.commit()
    res = SR.run(db, now=START1 - timedelta(minutes=30), courses=[_fresh(db, course)])
    assert res["sent"] == 0 and resend_stub == []
    assert SR.blocked_by(_fresh(db, course)) == ["no meeting info"]


# ----- what the email says ---------------------------------------------------

def test_the_email_carries_the_instructions_verbatim_with_live_links_and_local_time(db, course, resend_stub):
    _reg(db, "one@example.com", location="Kitimat, BC", name="Grace Hopper")
    SR.run(db, now=START1 - timedelta(minutes=50), courses=[_fresh(db, course)])
    (payload,) = resend_stub
    html = payload["html"]
    assert "Hi Grace," in html
    assert 'href="https://meet.google.com/abc-defg-hij"' in html
    assert 'href="https://tel.meet/abc-defg-hij?hs=5"' in html
    assert "dial +1 321-430-1922 and enter this PIN: 316 913 670#" in html
    assert "14:00 UTC on Saturday, March 2" in html
    # Kitimat is Pacific: 14:00 UTC = 06:00 PST in March 2030 (before DST).
    assert "06:00 PST in Kitimat, BC" in html
    assert "your local time" in html
    # the plain-text part keeps the link destinations
    assert "https://meet.google.com/abc-defg-hij" in payload["text"]


def test_an_unrecognised_location_gets_the_utc_time_only(db, course, resend_stub):
    _reg(db, "one@example.com", location="Somewhere Unknown")
    SR.run(db, now=START1 - timedelta(minutes=50), courses=[_fresh(db, course)])
    html = resend_stub[0]["html"]
    assert "14:00 UTC" in html and "your local time" not in html


def test_pasted_markup_cannot_inject_html(db, course, resend_stub):
    course.meeting_info = "<script>alert(1)</script> link: https://meet.google.com/x-y-z."
    db.commit()
    _reg(db, "one@example.com")
    SR.run(db, now=START1 - timedelta(minutes=50), courses=[_fresh(db, course)])
    html = resend_stub[0]["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    # the trailing full stop stays outside the link
    assert 'href="https://meet.google.com/x-y-z"' in html


# ----- the admin surface -----------------------------------------------------

def test_meeting_info_is_admin_only_and_round_trips(client, db, course):
    r = client.patch(f"/api/admin/courses/{CODE}", json={"meeting_info": "  " + MEETING + "\n"}, headers=ADMIN)
    assert r.status_code == 200
    assert "meeting_info" not in r.json()  # CourseOut never carries it
    assert "meeting_info" not in client.get(f"/api/courses/{CODE}").json()
    assert "meet.google.com" not in client.get(f"/api/courses/{CODE}").text

    m = client.get(f"/api/admin/courses/{CODE}/meeting", headers=ADMIN).json()
    assert m["meeting_info"] == MEETING
    assert m["armed"] is True and m["blocked_by"] == []
    assert client.get(f"/api/admin/courses/{CODE}/meeting").status_code == 401


def test_overview_reports_each_session_state_and_the_recipients(client, db, course, resend_stub):
    _reg(db, "one@example.com", location="Cincinnati, OH")
    _reg(db, "two@example.com", location="Somewhere Unknown", name="Bob")
    _reg(db, "nope@example.com", confirmed=False)
    c = _fresh(db, course)
    SR.run(db, now=START1 - timedelta(minutes=50), courses=[c])

    m = client.get(f"/api/admin/courses/{CODE}/meeting", headers=ADMIN).json()
    assert [r["email"] for r in m["recipients"]] == ["one@example.com", "two@example.com"]
    assert m["recipients"][0]["timezone"] == "America/New_York"
    assert m["recipients"][1]["timezone"] == ""
    day1, day2 = m["sessions"]
    assert day1["state"] == "sent" and day1["sent"] == 2 and day1["pending"] == 0
    assert day2["state"] == "scheduled" and day2["sent"] == 0 and day2["pending"] == 2
    assert day1["remind_at_utc"].startswith("2030-03-02T13:00:00")
    assert len(m["log"]) == 2 and all(row["ok"] for row in m["log"])


def test_the_test_send_goes_to_the_admin_only_and_does_not_count(client, db, course, resend_stub):
    _reg(db, "one@example.com")
    r = client.post(f"/api/admin/courses/{CODE}/meeting/test", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["to"] == ADMIN_EMAIL and r.json()["subject"].startswith("[TEST] Starts in 1 hour")
    assert [p["to"][0] for p in resend_stub] == [ADMIN_EMAIL]
    # the registrant still has their reminder coming
    m = client.get(f"/api/admin/courses/{CODE}/meeting", headers=ADMIN).json()
    assert m["sessions"][0]["sent"] == 0 and m["log"] == []


def test_the_test_send_refuses_an_unarmed_course(client, db, course):
    course.meeting_info = ""
    db.commit()
    r = client.post(f"/api/admin/courses/{CODE}/meeting/test", headers=ADMIN)
    assert r.status_code == 400 and "no meeting info" in r.json()["detail"]


# ----- who may trigger the run ----------------------------------------------

def test_run_accepts_the_cron_secret_or_the_admin_and_nothing_else(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "CRON_SECRET", "cron-secret-123", raising=False)
    assert client.post("/api/admin/session-reminders/run").status_code == 401
    assert client.post("/api/admin/session-reminders/run", headers={"X-Cron-Secret": "wrong"}).status_code == 401
    ok = client.post("/api/admin/session-reminders/run", headers={"X-Cron-Secret": "cron-secret-123"})
    assert ok.status_code == 200 and set(ok.json()) >= {"ran_at", "courses_checked", "sent", "failed", "details"}
    assert client.post("/api/admin/session-reminders/run", headers=ADMIN).status_code == 200


def test_run_with_no_cron_secret_configured_needs_the_admin(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "CRON_SECRET", "", raising=False)
    assert client.post("/api/admin/session-reminders/run", headers={"X-Cron-Secret": "anything"}).status_code == 401
    assert client.post("/api/admin/session-reminders/run", headers=ADMIN).status_code == 200


def test_the_run_endpoint_sends_what_is_due(client, db, course, resend_stub, monkeypatch):
    _reg(db, "one@example.com")
    monkeypatch.setattr(get_settings(), "CRON_SECRET", "s", raising=False)

    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return START1 - timedelta(minutes=40)

    monkeypatch.setattr(SR, "datetime", _Now)
    r = client.post("/api/admin/session-reminders/run", headers={"X-Cron-Secret": "s"})
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] == 1 and body["details"] == [f"{CODE} day=1 date=2030-03-02 -> one@example.com"]
    row = db.execute(select(EmailLog).where(EmailLog.scope_code == CODE)).scalar_one()
    assert row.template == "session_reminder" and row.audience == "2030-03-02" and row.ok
