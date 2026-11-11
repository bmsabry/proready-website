"""Consulting calls: which times are offered.

Open times sit inside the consulting hours (every day of the week, 08:00 to
23:00 in New York), at least 2 hours ahead, at most 60 days ahead, on a
30-minute grid, 15 minutes clear of everything that is busy, on days with
fewer than 4 calls.

Busy means, each tested on its own below: the Google calendars (company and
personal), a confirmed consulting booking, a pending one whose hold still
stands, an oral examination, and a live course session of the site's own. A
calendar that cannot be read blocks every time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    NOW,
    NY,
    OWNER,
    PERSONAL,
    PUBLIC,
    book,
    booking_row,
    client,
    confirmed,
    env,
    events_of,
    get_quote,
    iso,
    ny,
    save_card,
    slot_starts,
    to,
    world,
)

from app import consult
from app import exam_calendar as xcal
from app.config import get_settings
from app.db import SessionLocal
from app.models import AdvancedCertification, Course, ExamCalendar

WED = (2031, 6, 11)   # a Wednesday nine days ahead: standard tier, an empty day


def _day(client, y, m, d, tz="America/New_York") -> dict[str, int]:
    """{HH:MM on the New York clock: max_minutes} for one New York date."""
    r = client.get(f"{PUBLIC}/availability", params={"tz": tz})
    assert r.status_code == 200, r.text
    out = {}
    for day in r.json()["days"]:
        for s in day["slots"]:
            local = datetime.fromisoformat(s["start"].replace("Z", "+00:00")).astimezone(NY)
            if (local.year, local.month, local.day) == (y, m, d):
                out[local.strftime("%H:%M")] = s["max_minutes"]
    return out


FULL_DAY = [f"{h:02d}:{m:02d}" for h in range(8, 23) for m in (0, 30)]   # 08:00 … 22:30


# -----------------------------------------------------------------------------
# The grid itself
# -----------------------------------------------------------------------------

def test_an_empty_day_offers_every_half_hour_inside_the_hours(client):
    day = _day(client, *WED)
    assert list(day) == FULL_DAY and len(day) == 30
    # the longest call that still ends by 23:00
    assert day["08:00"] == 120 and day["21:00"] == 120
    assert day["21:30"] == 90 and day["22:00"] == 60 and day["22:30"] == 30


def test_the_answer_has_the_contract_shape(client):
    body = client.get(f"{PUBLIC}/availability", params={"tz": "America/New_York"}).json()
    assert body["enabled"] is True
    assert body["business_timezone"] == "America/New_York"
    assert body["step_minutes"] == 30 and body["durations"] == [30, 60, 90, 120]
    first_day = body["days"][0]
    assert first_day["date"] == "2031-06-02"
    # 10:00 now + 2 hours' notice: the first time today is 12:00 New York
    assert first_day["slots"][0] == {"start": iso(ny(2031, 6, 2, 12)), "max_minutes": 120, "tier": "same_day"}
    assert body["next_available"] == {"start": iso(ny(2031, 6, 2, 12)), "tier": "same_day"}
    assert [d["date"] for d in body["days"]] == sorted(d["date"] for d in body["days"])
    assert all(s["start"].endswith("Z") for d in body["days"] for s in d["slots"])


def test_every_day_of_the_week_is_open_and_the_horizon_is_sixty_days(client):
    body = client.get(f"{PUBLIC}/availability", params={"tz": "America/New_York"}).json()
    dates = [date.fromisoformat(d["date"]) for d in body["days"]]
    assert dates[0] == date(2031, 6, 2)
    # 60 days after 2 June is 1 August, open until 10:00 (now + 60 d)
    assert dates[-1] == date(2031, 8, 1)
    assert dates == [date(2031, 6, 2) + timedelta(days=i) for i in range(61)]   # no day skipped
    assert {d.weekday() for d in dates} == set(range(7))
    # Saturday and Sunday carry the full grid like any other day
    assert list(_day(client, 2031, 6, 7)) == FULL_DAY and list(_day(client, 2031, 6, 8)) == FULL_DAY
    last = body["days"][-1]["slots"][-1]
    assert datetime.fromisoformat(last["start"].replace("Z", "+00:00")) + timedelta(minutes=30) <= NOW + timedelta(days=60)
    assert last["start"] == iso(ny(2031, 8, 1, 9, 30))


def test_the_hours_are_a_setting_and_a_closed_day_offers_nothing(client):
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={"weekly_hours": {
        "mon": [["09:00", "12:00"], ["14:00", "18:00"]], "wed": [["09:00", "18:00"]],
    }})
    assert r.status_code == 200, r.text
    assert list(_day(client, *WED)) == [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]
    assert _day(client, 2031, 6, 12) == {} and _day(client, 2031, 6, 7) == {}
    monday = _day(client, 2031, 6, 9)
    assert list(monday) == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
                            "14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30"]
    assert monday["11:00"] == 60 and monday["11:30"] == 30       # a call does not run across the lunch gap


def test_tiers_follow_the_new_york_date_of_each_slot(client):
    body = client.get(f"{PUBLIC}/availability", params={"tz": "America/New_York"}).json()
    tier_by_date = {}
    for d in body["days"]:
        tiers = {s["tier"] for s in d["slots"]}
        assert len(tiers) == 1, f"{d['date']} mixes tiers {tiers}"
        tier_by_date[d["date"]] = tiers.pop()
    assert tier_by_date["2031-06-02"] == "same_day"
    assert tier_by_date["2031-06-03"] == "next_day"
    assert [tier_by_date[f"2031-06-0{d}"] for d in (4, 5, 6, 7, 8)] == ["priority"] * 5   # 2 to 6 days
    assert tier_by_date["2031-06-09"] == "standard"   # 7 days ahead
    assert set(tier_by_date.values()) == {"same_day", "next_day", "priority", "standard"}


def test_evening_slots_carry_the_tier_of_their_new_york_date(client):
    """Every slot from 20:00 New York on is already the next day in UTC.
    Its tier must still be the one of its New York date, in every list."""
    body = client.get(f"{PUBLIC}/availability", params={"tz": "UTC"}).json()   # grouped by UTC date
    by_start = {s["start"]: s["tier"] for d in body["days"] for s in d["slots"]}
    assert by_start[iso(ny(2031, 6, 2, 22, 30))] == "same_day"     # 2031-06-03T02:30Z
    assert by_start[iso(ny(2031, 6, 3, 8))] == "next_day"          # 2031-06-03T12:00Z, same UTC date
    assert by_start[iso(ny(2031, 6, 3, 22, 30))] == "next_day"     # 2031-06-04T02:30Z
    assert by_start[iso(ny(2031, 6, 8, 22, 30))] == "priority"     # Sunday night: 2031-06-09T02:30Z
    assert by_start[iso(ny(2031, 6, 9, 8))] == "standard"          # 2031-06-09T12:00Z, same UTC date
    # so a UTC date can hold two tiers, and that is right
    utc_day = next(d for d in body["days"] if d["date"] == "2031-06-09")
    assert {s["tier"] for s in utc_day["slots"]} == {"priority", "standard"}


def test_days_are_grouped_on_the_visitors_clock_but_tiers_stay_on_the_business_clock(client):
    """22:30 in New York on Wednesday is 11:30 Thursday in Tokyo: the slot is
    listed under Thursday for a visitor there, and its tier does not move."""
    body = client.get(f"{PUBLIC}/availability", params={"tz": "Asia/Tokyo"}).json()
    start = iso(ny(*WED, 22, 30))
    found = [(d["date"], s) for d in body["days"] for s in d["slots"] if s["start"] == start]
    assert found == [("2031-06-12", {"start": start, "max_minutes": 30, "tier": "standard"})]
    # an unknown zone falls back to the business clock instead of failing
    body = client.get(f"{PUBLIC}/availability", params={"tz": "Not/AZone"}).json()
    assert [(d["date"]) for d in body["days"] for s in d["slots"] if s["start"] == start] == ["2031-06-11"]


def test_slots_keep_their_wall_clock_time_across_the_clock_change(client, env):
    """New York leaves daylight time on Sunday 2 November 2031. 08:00 on the
    Friday before is 12:00 UTC; 08:00 on the Monday after is 13:00 UTC. The
    Sunday itself is 25 hours long and still offers 08:00 to 22:30."""
    env.clock.set(ny(2031, 10, 27, 10))
    starts = slot_starts(client)
    assert "2031-10-31T12:00:00Z" in starts and "2031-10-31T11:30:00Z" not in starts   # 08:00 EDT is the first
    assert "2031-11-01T02:30:00Z" in starts and "2031-11-01T03:00:00Z" not in starts   # Fri 22:30 EDT is the last
    assert "2031-11-03T13:00:00Z" in starts and "2031-11-03T12:30:00Z" not in starts   # 08:00 EST is the first
    assert "2031-11-04T03:30:00Z" in starts and "2031-11-04T04:00:00Z" not in starts   # Mon 22:30 EST is the last
    assert list(_day(client, 2031, 11, 2)) == FULL_DAY          # the 25-hour Sunday
    assert list(_day(client, 2031, 11, 3)) == FULL_DAY


# -----------------------------------------------------------------------------
# Busy source 1: the Google calendars
# -----------------------------------------------------------------------------

def test_busy_time_on_the_company_calendar_blocks_with_the_buffer(client, env):
    env.google.busy["primary"] = [(ny(*WED, 11), ny(*WED, 12))]
    day = _day(client, *WED)
    # busy 11:00-12:00, 15 minutes clear on both sides
    assert day["10:00"] == 30          # 10:00-10:30 fits; 10:00-11:00 would touch the buffer
    assert day["09:30"] == 60 and day["09:00"] == 90 and day["08:30"] == 120
    for gone in ("10:30", "11:00", "11:30", "12:00"):
        assert gone not in day, gone
    assert day["12:30"] == 120
    assert len(day) == len(FULL_DAY) - 4                         # nothing else moved


def test_a_busy_evening_blocks_the_evening_slots(client, env):
    """He has dinner plans 20:00-21:30 (00:00-01:30 UTC the next day)."""
    env.google.busy[PERSONAL] = [(ny(*WED, 20), ny(*WED, 21, 30))]
    day = _day(client, *WED)
    for gone in ("19:30", "20:00", "20:30", "21:00", "21:30"):
        assert gone not in day, gone
    assert day["19:00"] == 30 and day["22:00"] == 60 and day["22:30"] == 30
    assert list(_day(client, 2031, 6, 12)) == FULL_DAY           # the UTC date it falls on is untouched


def test_busy_time_on_the_personal_calendar_blocks_too(client, env):
    env.google.busy[PERSONAL] = [(ny(*WED, 14), ny(*WED, 15))]
    day = _day(client, *WED)
    for gone in ("13:30", "14:00", "14:30", "15:00"):
        assert gone not in day, gone
    assert "13:00" in day and "15:30" in day
    # and both calendars were asked about, in one FreeBusy call
    asked = [c for c in env.google.calls if c[1].endswith("/freeBusy")][-1][2]["json"]["items"]
    assert asked == [{"id": "primary"}, {"id": PERSONAL}]


# -----------------------------------------------------------------------------
# Busy source 2: consulting bookings, confirmed and pending
# -----------------------------------------------------------------------------

def test_a_pending_booking_holds_its_slot_until_the_hold_runs_out(client, env):
    start = ny(*WED, 11)
    r = book(client, start, 60)
    assert r.status_code == 200, r.text
    assert booking_row(r.json()["ref"]).status == "pending_card"
    day = _day(client, *WED)
    for gone in ("10:30", "11:00", "11:30", "12:00"):
        assert gone not in day, gone
    assert day["10:00"] == 30 and "12:30" in day

    env.clock.advance(minutes=14, seconds=59)
    assert "11:00" not in _day(client, *WED)
    assert get_quote(client, start).status_code == 409
    env.clock.advance(seconds=1)                       # 15 minutes: the hold is over
    # The time is free from that instant, before anything has recorded the
    # expiry: a quote (which records nothing) already sees it open.
    assert booking_row(r.json()["ref"]).status == "pending_card"
    assert get_quote(client, start).status_code == 200
    assert booking_row(r.json()["ref"]).status == "pending_card"
    assert _day(client, *WED)["11:00"] == 120
    assert booking_row(r.json()["ref"]).status == "expired"


def test_a_confirmed_booking_blocks_its_slot_even_if_google_forgot_it(client, env):
    b = confirmed(client, env, ny(*WED, 14), 90)
    assert len(env.google.events) == 1
    env.google.events.clear()                          # only our own record is left
    day = _day(client, *WED)
    for gone in ("13:30", "14:00", "14:30", "15:00", "15:30"):
        assert gone not in day, gone
    assert day["13:00"] == 30 and "16:00" in day
    assert booking_row(b["ref"]).status == "confirmed"


def test_a_cancelled_booking_gives_its_slot_back(client, env):
    b = confirmed(client, env, ny(*WED, 14), 60)
    assert "14:00" not in _day(client, *WED)
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert env.google.events == {}                     # the event is gone from the calendar too
    assert _day(client, *WED)["14:00"] == 120


def test_at_most_four_calls_a_day(client, env):
    for hour in (9, 11, 13):
        confirmed(client, env, ny(*WED, hour), 30, email=f"cap{hour}@example.com", ip=f"198.51.100.{hour}")
    assert _day(client, *WED), "three calls: the day is still open"
    r = book(client, ny(*WED, 15), 30, email="cap15@example.com", ip="198.51.100.15")   # a fourth, no card yet
    assert r.status_code == 200
    # An unfinished booking does not count toward the cap (review 2, N3: three
    # free ones would close a day). It holds its own time and nothing else.
    open_now = _day(client, *WED)
    assert open_now and "15:00" not in open_now and "17:00" in open_now
    other = book(client, ny(*WED, 17), 30, email="cap17@example.com", ip="198.51.100.17")   # and a fifth, no card yet
    assert other.status_code == 200
    # The cap is decided when a card is saved: the first to save one is the
    # day's fourth call, and the day closes.
    assert save_card(client, env, r.json()["ref"]).status_code == 200
    assert booking_row(r.json()["ref"]).status == "confirmed"
    assert _day(client, *WED) == {}
    assert list(_day(client, 2031, 6, 12)) == FULL_DAY # the next day is untouched
    # Even with terms that are still right (same tier on the next day), a
    # fifth call that day is refused.
    version = get_quote(client, ny(2031, 6, 12, 17), 30).json()["terms_version"]
    r = book(client, ny(*WED, 19), 30, email="cap19@example.com", ip="198.51.100.19", terms_version=version)
    assert r.status_code == 409 and "no longer available" in r.json()["detail"]
    # The other unfinished booking saves its card too late: it is not
    # confirmed, nothing is charged, and its client is told why.
    env.outbox.clear()
    assert save_card(client, env, other.json()["ref"]).status_code == 200
    late = booking_row(other.json()["ref"])
    assert late.status == "expired" and "slot_lost" in events_of(late.id)
    (mail,) = to(env.outbox, "cap17@example.com")
    assert "could not be confirmed" in mail["subject"].lower() or "not confirmed" in mail["subject"].lower()
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0


def test_an_evening_call_counts_toward_its_new_york_day(client, env):
    """A call at 22:00 Wednesday in New York is on Thursday's UTC date. It is
    Wednesday's fourth call, not Thursday's first."""
    for hour in (9, 12, 15):
        confirmed(client, env, ny(*WED, hour), 30, email=f"eve{hour}@example.com", ip=f"198.51.100.{hour}")
    late = confirmed(client, env, ny(*WED, 22), 60, email="eve22@example.com", ip="198.51.100.22")
    row = booking_row(late["ref"])
    assert iso(row.start_at.replace(tzinfo=NOW.tzinfo)) == "2031-06-12T02:00:00Z"
    assert row.tier == "standard" and row.total_cents == 11_100
    assert _day(client, *WED) == {}                              # Wednesday is full
    assert list(_day(client, 2031, 6, 12)) == FULL_DAY           # Thursday has all of its times


# -----------------------------------------------------------------------------
# Busy source 3: oral examinations
# -----------------------------------------------------------------------------

@pytest.fixture()
def exam():
    """An oral examination booked for Wednesday 13:00-14:00 New York."""
    db = SessionLocal()
    row = AdvancedCertification(
        learner_id=987_001, product_code="consult-test-product", source="manual", amount_cents=0,
        currency="usd", status="scheduled", fee_status="waived", scheduled_at=ny(*WED, 13),
    )
    db.add(row)
    db.commit()
    row_id = row.id
    db.close()
    yield row_id
    db = SessionLocal()
    db.query(AdvancedCertification).filter(AdvancedCertification.id == row_id).delete()
    db.commit()
    db.close()


def test_an_oral_examination_blocks_its_hour(client, env, exam):
    day = _day(client, *WED)
    for gone in ("12:30", "13:00", "13:30", "14:00"):
        assert gone not in day, gone
    assert day["12:00"] == 30 and day["14:30"] == 120
    version = get_quote(client, ny(*WED, 15), 60).json()["terms_version"]
    assert book(client, ny(*WED, 13), 60, terms_version=version).status_code == 409


def test_an_examination_that_is_not_scheduled_blocks_nothing(client, env, exam):
    db = SessionLocal()
    db.get(AdvancedCertification, exam).status = "cancelled"
    db.commit()
    db.close()
    assert _day(client, *WED)["13:00"] == 120


# -----------------------------------------------------------------------------
# Busy source 4: the site's own live course sessions
# -----------------------------------------------------------------------------

@pytest.fixture()
def course():
    made: list[str] = []

    def make(code: str, **fields) -> None:
        db = SessionLocal()
        db.add(Course(code=code, title="Consult test cohort", start_date=date(2031, 6, 11), **fields))
        db.commit()
        db.close()
        made.append(code)

    yield make
    db = SessionLocal()
    db.query(Course).filter(Course.code.in_(made)).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_a_course_session_blocks_its_time_on_each_course_day(client, env, course):
    course(
        "consult-test-live", day_dates=["2031-06-11", "2031-06-12"],
        session_time_local="10:00", session_timezone="America/New_York", session_duration_minutes=180,
    )
    for y, m, d in (WED, (2031, 6, 12)):
        day = _day(client, y, m, d)
        for gone in ("09:30", "10:00", "11:30", "12:30", "13:00"):   # 10:00-13:00 plus the buffer
            assert gone not in day, (d, gone)
        assert day["09:00"] == 30 and day["08:00"] == 90 and day["13:30"] == 120
    assert "10:00" in _day(client, 2031, 6, 13)          # not a course day
    version = get_quote(client, ny(*WED, 15), 60).json()["terms_version"]
    assert book(client, ny(*WED, 11), 60, terms_version=version).status_code == 409


def test_a_course_session_set_in_another_time_zone_lands_where_it_really_is(client, env, course):
    """15:00-17:00 in London is 10:00-12:00 in New York."""
    course(
        "consult-test-london", day_dates=["2031-06-11"],
        session_time_local="15:00", session_timezone="Europe/London", session_duration_minutes=120,
    )
    day = _day(client, *WED)
    for gone in ("09:30", "10:00", "11:30", "12:00"):
        assert gone not in day, gone
    assert day["09:00"] == 30 and "12:30" in day and len(day) == len(FULL_DAY) - 6


def test_a_course_day_without_a_clock_time_blocks_the_whole_day(client, env, course):
    course("consult-test-notime", day_dates=["2031-06-11"])
    assert _day(client, *WED) == {}
    assert _day(client, 2031, 6, 12) != {}


def test_a_session_without_a_length_blocks_to_the_end_of_its_day(client, env, course):
    course(
        "consult-test-nolength", day_dates=["2031-06-11"],
        session_time_local="14:00", session_timezone="America/New_York",
    )
    day = _day(client, *WED)
    assert list(day)[0] == "08:00" and list(day)[-1] == "13:00"
    assert day["13:00"] == 30 and day["12:00"] == 90
    assert list(_day(client, 2031, 6, 12)) == FULL_DAY           # it stops at New York midnight


def test_a_closed_course_still_blocks_its_sessions(client, env, course):
    course(
        "consult-test-closed", day_dates=["2031-06-11"], status="closed",
        session_time_local="08:00", session_timezone="America/New_York", session_duration_minutes=900,
    )
    assert _day(client, *WED) == {}                              # 08:00 to 23:00: the whole consulting day


def test_an_evening_course_session_blocks_the_evening(client, env, course):
    """A cohort for another continent: 19:00-22:00 New York."""
    course(
        "consult-test-evening", day_dates=["2031-06-11"],
        session_time_local="19:00", session_timezone="America/New_York", session_duration_minutes=180,
    )
    day = _day(client, *WED)
    assert list(day)[-2:] == ["18:00", "22:30"] and day["18:00"] == 30 and day["22:30"] == 30


# -----------------------------------------------------------------------------
# A calendar that cannot be read blocks every time
# -----------------------------------------------------------------------------

def test_an_unreadable_personal_calendar_blocks_everything(client, env):
    env.google.errors[PERSONAL] = "notFound"
    body = client.get(f"{PUBLIC}/availability").json()
    assert body["enabled"] is False and body["days"] == [] and body["next_available"] is None
    r = get_quote(client, ny(*WED, 10))
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"]
    # Booking is refused too, even with terms that were shown a moment before.
    env.google.errors.clear()
    version = get_quote(client, ny(*WED, 10)).json()["terms_version"]
    env.google.errors[PERSONAL] = "notFound"
    r = book(client, ny(*WED, 10), terms_version=version)
    assert r.status_code == 503, r.text
    db = SessionLocal()
    assert db.query(consult.ConsultBooking).count() == 0
    db.close()
    assert env.stripe.calls == []                       # nothing was started at Stripe


def test_the_owner_is_told_once_when_the_calendar_stops_being_readable(client, env):
    env.google.errors["primary"] = "forbidden"
    for _ in range(3):
        assert client.get(f"{PUBLIC}/availability").json()["enabled"] is False
    alerts = [m for m in to(env.outbox, OWNER) if "[Calendar]" in m["subject"]]
    assert len(alerts) == 1                              # the existing 12-hour limit holds
    db = SessionLocal()
    assert "cannot be read" in db.get(ExamCalendar, 1).last_error
    db.close()


def test_google_refusing_the_check_blocks_everything(client, env, monkeypatch):
    def down(method, url, **kw):
        if url.endswith("/freeBusy"):
            return 503, {"error": {"message": "Backend Error"}}
        return env.google(method, url, **kw)

    monkeypatch.setattr(xcal, "_google", down)
    assert client.get(f"{PUBLIC}/availability").json()["days"] == []
    status = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert status["calendar_ok"] is False and "Backend Error" in status["calendar_error"]
    assert status["next_available"] is None


def test_a_calendar_that_was_never_connected_blocks_everything_quietly(client, env):
    db = SessionLocal()
    cal = db.get(ExamCalendar, 1)
    token = cal.refresh_token_encrypted
    cal.refresh_token_encrypted = ""
    db.commit()
    try:
        assert client.get(f"{PUBLIC}/availability").json()["enabled"] is False
        assert to(env.outbox, OWNER) == []               # nothing "stopped": no alert
        assert env.google.freebusy_calls() == 0
    finally:
        cal.refresh_token_encrypted = token
        db.commit()
        db.close()


def test_without_stripe_the_public_side_is_closed(client, env, monkeypatch):
    monkeypatch.setattr(get_settings(), "STRIPE_SECRET_KEY", "")
    assert client.get(f"{PUBLIC}/availability").json()["enabled"] is False
    assert get_quote(client, ny(*WED, 10)).status_code == 503


# -----------------------------------------------------------------------------
# The cache: the public list may be seconds old, a booking never is
# -----------------------------------------------------------------------------

def test_the_public_list_reuses_a_recent_calendar_read_but_booking_reads_live(client, env, monkeypatch):
    monkeypatch.setattr(consult, "BUSY_CACHE_SECONDS", 30)
    consult.clear_cache()
    version = get_quote(client, ny(*WED, 11)).json()["terms_version"]
    assert _day(client, *WED)["11:00"] == 120
    before = env.google.freebusy_calls()
    assert before == 1                                   # quote and list shared one read
    # He adds a meeting to his calendar; the list is still the cached one…
    env.google.busy["primary"] = [(ny(*WED, 11), ny(*WED, 12))]
    assert "11:00" in _day(client, *WED)
    assert env.google.freebusy_calls() == before
    # …but booking asks Google again and refuses the time.
    r = book(client, ny(*WED, 11), terms_version=version)
    assert r.status_code == 409, r.text
    assert env.google.freebusy_calls() == before + 1
    # A calendar change on our side (a new check list) also drops the cache.
    consult.clear_cache()
    assert "11:00" not in _day(client, *WED)


# -----------------------------------------------------------------------------
# The admin's status strip
# -----------------------------------------------------------------------------

def test_status_reports_what_a_client_needs_to_be_able_to_book(client, env, monkeypatch):
    s = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert s["calendar_ok"] is True and s["stripe_ok"] is True and s["enabled"] is True
    assert s["meet_scope_ok"] is False                   # attendance scope not granted yet
    assert s["next_available"] == {"start": iso(ny(2031, 6, 2, 12)), "tier": "same_day"}
    assert {"calendar_ok", "meet_scope_ok", "stripe_ok", "enabled", "next_available"} <= set(s)

    db = SessionLocal()
    cal = db.get(ExamCalendar, 1)
    scopes = cal.scopes
    cal.scopes = scopes + " " + consult.MEET_SCOPE
    db.commit()
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["meet_scope_ok"] is True
    cal.scopes = scopes
    db.commit()
    db.close()

    monkeypatch.setattr(get_settings(), "STRIPE_WEBHOOK_SECRET", "")
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["stripe_ok"] is False


def test_oral_exam_slots_are_computed_exactly_as_before(client, env):
    """The exam calendar's own rules and slot list do not move because the
    consulting settings exist (different hours, notice, horizon, cap)."""
    db = SessionLocal()
    cal = xcal.settings_row(db)
    r = xcal.rules(cal)
    assert (r.minutes, r.buffer, r.notice_hours, r.horizon_days, r.max_per_day) == (
        get_settings().ADVANCED_INTERVIEW_MINUTES, cal.buffer_minutes, cal.min_notice_hours,
        cal.horizon_days, cal.max_per_day,
    )
    slots = xcal.open_slots(db, now=NOW, record=False)
    assert slots and slots[0] >= NOW + timedelta(hours=cal.min_notice_hours)
    assert all(s.astimezone(NY).hour < 17 for s in slots)   # exam hours end at 17:00, not 18:00
    db.close()
