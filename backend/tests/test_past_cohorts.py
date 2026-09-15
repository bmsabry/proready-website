"""An attended registration is a past-cohort record, not an active seat.

The incident (2026-09-15): the owner re-dated a course for its next cohort
and the five people who had just finished the previous one were emailed
"Updated start date". This file pins the rule from app/registrants.py to
every audience and counter that could repeat that.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import conftest
from fastapi.testclient import TestClient

from app import ai_tools
from app import emailer as E
from app import session_reminders
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Course, Registration

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "micro-gas-turbine-design"
CODE = "past-cohort-rule-test"
ALUM = "alum.finished@example.com"
BUYER = "buyer.confirmed@example.com"
NOSHOW = "noshow.pending@example.com"


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-past-1"}


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1])
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


@pytest.fixture(scope="module", autouse=True)
def cohort():
    db = SessionLocal()
    db.add(Course(
        code=CODE, title="Rule Cohort", start_date=date(2026, 9, 5),
        day_dates=["2026-09-05", "2026-09-06", "2026-09-12", "2026-09-13"],
        recorded_product_code=PRODUCT, total_seats=15,
        session_time_utc="14:00", session_duration_minutes=300, meeting_info="Zoom 123",
    ))
    now = datetime.now(timezone.utc)
    for email, name, status, confirmed in (
        (ALUM, "Alum Finished", "paid", True),
        (BUYER, "Buyer Confirmed", "paid", True),
        (NOSHOW, "Noshow Pending", "pending", False),
    ):
        db.add(Registration(
            course_code=CODE, full_name=name, email=email, job_title="Engineer",
            company="ACME", years_experience="5", location="Cairo", status=status,
            paid_at=now if status == "paid" else None,
            attendance_confirmed_at=now if confirmed else None,
        ))
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    db.query(Registration).filter(Registration.course_code == CODE).delete()
    db.query(Course).filter(Course.code == CODE).delete()
    db.commit()
    db.close()


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _reg_id(email: str) -> int:
    db = SessionLocal()
    rid = db.query(Registration).filter(Registration.course_code == CODE, Registration.email == email).one().id
    db.close()
    return rid


def _recipients(outbox, subject_prefix: str) -> set[str]:
    """Broadcasts go through Resend's batch endpoint (a list of messages);
    single sends are one dict. Flatten both."""
    msgs = []
    for payload in outbox:
        msgs.extend(payload if isinstance(payload, list) else [payload])
    return {to for m in msgs if m["subject"].startswith(subject_prefix) for to in m["to"]}


# -----------------------------------------------------------------------------

def test_marking_attended_frees_the_seat_and_leaves_the_registrations_list(outbox):
    with _client() as c:
        before = c.get(f"/api/courses/{CODE}").json()
        assert before["seats_taken"] == 3
        r = c.post("/api/admin/mark-attended", headers=ADMIN,
                   json={"registration_id": _reg_id(ALUM), "attended": True, "send_email": False})
        assert r.status_code == 200, r.text
        after = c.get(f"/api/courses/{CODE}").json()
        assert after["seats_taken"] == 2, "a past attendee holds no seat in the next cohort"

        current = c.get(f"/api/admin/registrations?course={CODE}", headers=ADMIN).json()
        assert {x["email"] for x in current} == {BUYER, NOSHOW}
        past = c.get(f"/api/admin/registrations?course={CODE}&scope=past", headers=ADMIN).json()
        assert [x["email"] for x in past] == [ALUM]
        assert past[0]["attended_cohort_start"] == "2026-09-05"
        assert past[0]["attended_cohort_end"] == "2026-09-13"
        assert past[0]["attendance_certificate_code"].startswith("PRE-A-")
        everything = c.get(f"/api/admin/registrations?course={CODE}&scope=all", headers=ADMIN).json()
        assert len(everything) == 3


def test_re_dating_the_course_emails_active_registrants_only(outbox):
    with _client() as c:
        r = c.patch(f"/api/admin/courses/{CODE}", headers=ADMIN, json={"start_date": "2026-11-14"})
        assert r.status_code == 200, r.text
    got = _recipients(outbox, "Updated start date")
    assert got == {BUYER, NOSHOW}
    assert ALUM not in got, "the incident: a past attendee told their start date moved"


def test_notify_audiences_keep_past_cohorts_apart(outbox):
    with _client() as c:
        for audience, expected in (
            ("all", {BUYER, NOSHOW}),
            ("paid", {BUYER}),
            ("pending", {NOSHOW}),
            ("alumni", {ALUM}),
        ):
            outbox.clear()
            r = c.post(f"/api/admin/courses/{CODE}/notify", headers=ADMIN,
                       json={"subject": f"Hello {audience}", "body_html": "<p>x</p>", "audience": audience})
            assert r.status_code == 200, r.text
            assert _recipients(outbox, f"Hello {audience}") == expected, audience


def test_session_reminders_skip_past_cohorts():
    db = SessionLocal()
    rows = session_reminders.confirmed_registrants(db, CODE)
    db.close()
    assert [r.email for r in rows] == [BUYER]


def test_assistant_tools_do_not_list_past_cohorts_as_registrants():
    db = SessionLocal()
    default = ai_tools.list_registrations(db, CODE)
    past = ai_tools.list_registrations(db, CODE, status="attended")
    db.close()
    assert {r["email"] for r in default["registrations"]} == {BUYER, NOSHOW}
    assert {r["email"] for r in past["registrations"]} == {ALUM}


def test_an_alum_may_register_again_for_the_next_cohort(outbox):
    with _client() as c:
        r = c.post("/api/register", json={
            "full_name": "Alum Finished", "email": ALUM, "job_title": "Engineer",
            "company": "ACME", "years_experience": "5", "location": "Cairo",
            "course_code": CODE, "website": "",
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] != "duplicate", "the attended row is history, not a live seat"
    db = SessionLocal()
    rows = db.query(Registration).filter(Registration.course_code == CODE, Registration.email == ALUM).all()
    assert sorted(bool(x.attended_at) for x in rows) == [False, True]
    # Tidy: drop the fresh row so the counts below stay readable.
    for x in rows:
        if x.attended_at is None:
            db.delete(x)
    db.commit()
    db.close()


def test_closing_a_cohort_marks_every_confirmed_paid_seat(outbox):
    with _client() as c:
        r = c.post(f"/api/admin/courses/{CODE}/mark-all-attended", headers=ADMIN,
                   json={"course_code": CODE, "send_email": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["marked"] == 1 and body["skipped"] == 0
        assert body["results"][0]["name"] == "Buyer Confirmed"
        # The pending no-show stays where it is — awaiting the next cohort.
        current = c.get(f"/api/admin/registrations?course={CODE}", headers=ADMIN).json()
        assert [x["email"] for x in current] == [NOSHOW]
        assert c.get(f"/api/courses/{CODE}").json()["seats_taken"] == 1
        # Nothing else to close: a second run is a no-op.
        again = c.post(f"/api/admin/courses/{CODE}/mark-all-attended", headers=ADMIN,
                       json={"course_code": CODE, "send_email": False}).json()
        assert again["marked"] == 0
