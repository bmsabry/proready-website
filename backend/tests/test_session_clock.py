"""The session start is set on Bassam's New York clock; everything else follows.

2026 clock changes these tests lean on:
  Europe (London, Paris, Berlin) leaves summer time  Sun 25 Oct 2026
  US and Canada leave daylight time                  Sun  1 Nov 2026
  Saudi Arabia (UTC+3) and Algeria (UTC+1) never change.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import session_reminders as SR
from app.ai_tools import update_course
from app.db import SessionLocal
from app.local_times import (
    day_one_utc_hhmm,
    instructor_hhmm,
    local_schedule,
    session_starts_utc,
    set_session_time,
    set_session_time_from_utc,
)
from app.main import _backfill_session_time_local, app
from app.models import Course

from conftest import ADMIN_TOKEN

AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
CODE = "clock-test-course"


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


def _course(db, days, **kw):
    db.execute(delete(Course).where(Course.code == CODE))
    db.commit()
    c = Course(
        code=CODE, title="Clock", start_date=date.fromisoformat(days[0]),
        total_seats=5, day_dates=list(days), session_duration_minutes=340, **kw,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _at(start_utc: datetime, zone: str) -> str:
    return start_utc.astimezone(ZoneInfo(zone)).strftime("%H:%M")


def test_nine_am_new_york_in_november_everywhere(db):
    c = _course(db, ["2026-11-14", "2026-11-15", "2026-11-21", "2026-11-22"])
    set_session_time(c, "09:00")
    starts = session_starts_utc(c)
    assert [s.strftime("%H:%M") for s in starts] == ["14:00"] * 4
    s = starts[0]
    assert _at(s, "America/New_York") == "09:00"
    assert _at(s, "America/Vancouver") == "06:00"
    assert _at(s, "Africa/Algiers") == "15:00"
    assert _at(s, "Asia/Riyadh") == "17:00"


def test_same_new_york_time_in_summer_moves_the_other_countries_not_him(db):
    c = _course(db, ["2026-09-05"])
    set_session_time(c, "09:00")
    s = session_starts_utc(c)[0]
    assert s.strftime("%H:%M") == "13:00"
    assert _at(s, "America/New_York") == "09:00"
    assert _at(s, "America/Vancouver") == "06:00"  # both change together
    assert _at(s, "Africa/Algiers") == "14:00"
    assert _at(s, "Asia/Riyadh") == "16:00"


def test_cohort_across_the_us_change_keeps_his_clock_and_moves_riyadh(db):
    c = _course(db, ["2026-10-31", "2026-11-02"])
    set_session_time(c, "09:00")
    sat, mon = session_starts_utc(c)
    assert (_at(sat, "America/New_York"), _at(mon, "America/New_York")) == ("09:00", "09:00")
    assert (sat.strftime("%H:%M"), mon.strftime("%H:%M")) == ("13:00", "14:00")
    assert (_at(sat, "Asia/Riyadh"), _at(mon, "Asia/Riyadh")) == ("16:00", "17:00")
    assert (_at(sat, "Africa/Algiers"), _at(mon, "Africa/Algiers")) == ("14:00", "15:00")
    # London already changed on Oct 25, so it moves with the US change too.
    assert (_at(sat, "Europe/London"), _at(mon, "Europe/London")) == ("13:00", "14:00")


def test_cohort_across_the_european_change_only_europe_moves(db):
    c = _course(db, ["2026-10-24", "2026-10-26"])
    set_session_time(c, "10:00")
    sat, mon = session_starts_utc(c)
    assert (sat.strftime("%H:%M"), mon.strftime("%H:%M")) == ("14:00", "14:00")
    assert (_at(sat, "Europe/London"), _at(mon, "Europe/London")) == ("15:00", "14:00")
    assert (_at(sat, "Europe/Paris"), _at(mon, "Europe/Paris")) == ("16:00", "15:00")
    assert (_at(sat, "Asia/Riyadh"), _at(mon, "Asia/Riyadh")) == ("17:00", "17:00")


def test_reminders_fire_at_each_dates_own_instant(db):
    c = _course(db, ["2026-10-31", "2026-11-02"], meeting_info="Meet link")
    set_session_time(c, "09:00")
    db.commit()
    starts = [s for _, _, s in SR.session_starts(c)]
    assert starts == [
        datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc),
    ]
    assert SR.blocked_by(c) == []


def test_utc_only_course_is_read_on_its_first_date(db):
    nov = _course(db, ["2026-11-14"], session_time_utc="14:00")
    assert instructor_hhmm(nov) == "09:00"
    set_session_time_from_utc(nov, "14:00")
    assert (nov.session_time_local, nov.session_timezone) == ("09:00", "America/New_York")

    aug = _course(db, ["2026-08-29"], session_time_utc="14:00")
    set_session_time_from_utc(aug, "14:00")
    assert aug.session_time_local == "10:00"


def test_startup_backfill_keeps_every_instant_and_never_revives_a_cleared_time(db):
    c = _course(db, ["2026-11-02", "2026-11-03"], session_time_utc="14:00")
    before = [s for s in session_starts_utc(c)]
    _backfill_session_time_local()
    db.expire_all()
    c = db.execute(select(Course).where(Course.code == CODE)).scalar_one()
    assert c.session_time_local == "09:00"
    assert session_starts_utc(c) == before

    set_session_time(c, "")
    db.commit()
    _backfill_session_time_local()
    db.expire_all()
    c = db.execute(select(Course).where(Course.code == CODE)).scalar_one()
    assert (c.session_time_local, c.session_time_utc) == ("", "")


def test_admin_sets_new_york_time_and_api_reports_it(client, db):
    _course(db, ["2026-11-14", "2026-11-15"])
    r = client.patch(f"/api/admin/courses/{CODE}", json={"session_time_local": "09:00"}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_time_local"] == "09:00"
    assert body["session_timezone"] == "America/New_York"
    assert body["session_time_utc"] == "14:00"

    public = client.get(f"/api/courses/{CODE}").json()
    assert (public["session_time_local"], public["session_time_utc"]) == ("09:00", "14:00")


def test_moving_the_dates_into_summer_keeps_his_time_and_moves_utc(client, db):
    _course(db, ["2026-11-14"])
    client.patch(f"/api/admin/courses/{CODE}", json={"session_time_local": "09:00"}, headers=AUTH)
    r = client.patch(
        f"/api/admin/courses/{CODE}", json={"day_dates": ["2026-06-06", "2026-06-07"]}, headers=AUTH
    )
    assert r.json()["session_time_local"] == "09:00"
    assert r.json()["session_time_utc"] == "13:00"
    db.expire_all()
    assert db.execute(select(Course).where(Course.code == CODE)).scalar_one().session_time_utc == "13:00"


def test_unknown_zone_is_refused(client, db):
    _course(db, ["2026-11-14"])
    r = client.patch(
        f"/api/admin/courses/{CODE}",
        json={"session_time_local": "09:00", "session_timezone": "Mars/Olympus"},
        headers=AUTH,
    )
    assert r.status_code == 400


def test_clearing_the_time_clears_both_fields(client, db):
    _course(db, ["2026-11-14"])
    client.patch(f"/api/admin/courses/{CODE}", json={"session_time_local": "09:00"}, headers=AUTH)
    r = client.patch(f"/api/admin/courses/{CODE}", json={"session_time_local": ""}, headers=AUTH)
    assert (r.json()["session_time_local"], r.json()["session_time_utc"]) == ("", "")


def test_assistant_sets_his_clock_time(db):
    _course(db, ["2026-11-02"])
    out = update_course(db, code=CODE, session_time_local="09:00")
    assert out["ok"] is True
    assert out["course"]["session_time_local"] == "09:00"
    assert out["course"]["session_starts_utc"] == ["2026-11-02T14:00:00+00:00"]


def test_local_schedule_gives_per_date_utc_across_a_change(db):
    c = _course(db, ["2026-10-31", "2026-11-02"])
    set_session_time(c, "09:00")
    out = local_schedule(
        session_time_utc=c.session_time_utc, duration_minutes=60,
        day_dates=list(c.day_dates), locations=["Yanbu"],
        starts_utc=session_starts_utc(c),
    )
    assert [s["start"] for s in out["utc_sessions"]] == ["13:00", "14:00"]
    riyadh = next(z for z in out["zones"] if z["timezone"] == "Asia/Riyadh")
    assert [s["start"] for s in riyadh["sessions"]] == ["16:00", "17:00"]
    assert "per date" in out["note"]
    assert day_one_utc_hhmm(c) == "13:00"
