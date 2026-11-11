"""Oral examinations are not offered while he is teaching.

The site's own live course sessions (Course day dates at the session clock
time) block consulting slots, and from 10 Nov 2026 they block oral-exam
slots too: one busy source, `exam_calendar.course_blocks`, read by both.
Nothing else about examinations changes: their hours, notice, buffer,
horizon and daily cap are their own (asserted here and in
test_exam_calendar.py, which is untouched).

The exam hours in this file are the code's defaults: Monday to Friday,
09:00 to 17:00 New York, an hour long, 30 minutes clear of anything busy.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from consult_support import (  # noqa: F401  (fixtures)
    NOW,
    NY,
    PERSONAL,
    client,
    env,
    ny,
    world,
)

from app import advanced_cert as adv
from app import consult
from app import exam_calendar as xcal
from app.db import SessionLocal
from app.models import AdvancedCertification, Course, Learner, Product

import conftest

WED = date(2031, 6, 11)                      # nine days after the pinned "now"
THU = date(2031, 6, 12)
ALL_DAY = [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)][:-1]     # 09:00 … 16:00


def _exam_day(day: date, now: datetime = NOW) -> list[str]:
    """Oral-exam start times offered on one New York date, as HH:MM."""
    db = SessionLocal()
    try:
        slots = xcal.open_slots(db, now=now, record=False)
    finally:
        db.close()
    return [s.astimezone(NY).strftime("%H:%M") for s in slots if s.astimezone(NY).date() == day]


@pytest.fixture()
def course():
    made: list[str] = []

    def make(code: str, **fields) -> None:
        db = SessionLocal()
        db.add(Course(code=code, title="Exam-slot test cohort", start_date=WED, **fields))
        db.commit()
        db.close()
        made.append(code)

    yield make
    db = SessionLocal()
    db.query(Course).filter(Course.code.in_(made)).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_without_a_course_the_exam_day_is_whole(env):
    assert _exam_day(WED) == ALL_DAY and len(ALL_DAY) == 15
    assert _exam_day(THU) == ALL_DAY


def test_exam_slots_leave_out_a_course_session_and_its_buffer(env, course):
    course(
        "exam-test-live", day_dates=["2031-06-11"],
        session_time_local="10:00", session_timezone="America/New_York", session_duration_minutes=180,
    )
    # The session runs 10:00 to 13:00. An hour-long examination needs 30
    # minutes clear on both sides, so it cannot start from 08:30 (exclusive)
    # to 13:30 (exclusive): 09:00 through 13:00 are gone.
    assert _exam_day(WED) == ["13:30", "14:00", "14:30", "15:00", "15:30", "16:00"]
    assert _exam_day(THU) == ALL_DAY                               # not a course day
    # the same session keeps a consulting call away too: one source for both
    db = SessionLocal()
    low, high = ny(2031, 6, 11, 0), ny(2031, 6, 12, 0)
    assert consult.course_blocks(db, low, high) == xcal.course_blocks(db, low, high) == [
        (ny(2031, 6, 11, 10), ny(2031, 6, 11, 13)),
    ]
    db.close()


def test_every_day_of_a_course_is_kept_clear(env, course):
    course(
        "exam-test-two-days", day_dates=["2031-06-11", "2031-06-12"],
        session_time_local="09:00", session_timezone="America/New_York", session_duration_minutes=340,
    )
    # 09:00 to 14:40: the first examination that is 30 minutes clear starts at 15:30
    for day in (WED, THU):
        assert _exam_day(day) == ["15:30", "16:00"], day
    assert _exam_day(date(2031, 6, 13)) == ALL_DAY


def test_a_course_day_without_a_clock_time_blocks_the_whole_exam_day(env, course):
    course("exam-test-notime", day_dates=["2031-06-11"])
    assert _exam_day(WED) == [] and _exam_day(THU) == ALL_DAY


def test_a_session_set_in_another_time_zone_blocks_where_it_really_is(env, course):
    """15:00 to 17:00 in London is 10:00 to 12:00 in New York."""
    course(
        "exam-test-london", day_dates=["2031-06-11"],
        session_time_local="15:00", session_timezone="Europe/London", session_duration_minutes=120,
    )
    day = _exam_day(WED)
    assert "09:00" not in day and "12:00" not in day and day[0] == "12:30"


def test_a_closed_course_still_blocks_and_a_past_one_changes_nothing(env, course):
    course(
        "exam-test-closed", day_dates=["2031-06-11"], status="closed",
        session_time_local="09:00", session_timezone="America/New_York", session_duration_minutes=480,
    )
    course(
        "exam-test-past", day_dates=["2031-05-20", "2031-05-21"],
        session_time_local="09:00", session_timezone="America/New_York", session_duration_minutes=480,
    )
    assert _exam_day(WED) == [] and _exam_day(THU) == ALL_DAY


def test_google_busy_time_and_course_time_add_up(env, course):
    course(
        "exam-test-morning", day_dates=["2031-06-11"],
        session_time_local="09:00", session_timezone="America/New_York", session_duration_minutes=120,
    )
    env.google.busy[PERSONAL] = [(ny(2031, 6, 11, 14), ny(2031, 6, 11, 15))]
    # course until 11:00 (+30) and his own appointment 14:00-15:00 (30 either side)
    assert _exam_day(WED) == ["11:30", "12:00", "12:30", "15:30", "16:00"]


def test_the_exam_rules_themselves_did_not_move(env, course):
    """Hours, notice, horizon and the daily cap are the examination's own."""
    db = SessionLocal()
    cal = xcal.settings_row(db)
    slots = xcal.open_slots(db, now=NOW, record=False)
    db.close()
    local = [s.astimezone(NY) for s in slots]
    assert min(slots) >= NOW + timedelta(hours=cal.min_notice_hours)
    assert max(slots) <= NOW + timedelta(days=cal.horizon_days)
    assert all(t.weekday() < 5 and 9 <= t.hour < 17 for t in local)
    # a booked examination still counts toward the cap of two a day
    db = SessionLocal()
    rows = [
        AdvancedCertification(
            learner_id=987_100 + i, product_code="exam-course-test", source="manual", amount_cents=0,
            currency="usd", status="scheduled", fee_status="waived", scheduled_at=ny(2031, 6, 11, hour),
        )
        for i, hour in enumerate((9, 14))
    ]
    db.add_all(rows)
    db.commit()
    try:
        assert _exam_day(WED) == []
    finally:
        for row in rows:
            db.delete(row)
        db.commit()
        db.close()


def test_a_candidate_cannot_book_an_examination_into_a_course_session(env, course):
    """The booking itself re-reads the slots under the calendar lock; a time
    inside a course day is refused there too, not only left off the list.
    (The booking code uses the real clock, so this one picks a real day.)"""
    db = SessionLocal()
    before = xcal.open_slots(db, record=False)
    assert before, "the exam calendar offers something to start with"
    pick = before[len(before) // 2]
    day = pick.astimezone(NY).date()
    course("exam-test-book", day_dates=[day.isoformat()])           # he teaches that whole day
    after = xcal.open_slots(db, record=False)
    assert pick not in after and not any(s.astimezone(NY).date() == day for s in after)
    assert [s for s in before if s.astimezone(NY).date() != day] == after      # every other day is untouched

    learner = Learner(email="exam.course.test@example.com", full_name="Exam Course Test")
    db.add(learner)
    db.commit()
    row = AdvancedCertification(
        learner_id=learner.id, product_code=conftest.TEST_ADVANCED_PRODUCT, source="manual", amount_cents=0,
        currency="usd", status="exam_passed", fee_status="waived",
    )
    db.add(row)
    db.commit()
    try:
        product = db.get(Product, conftest.TEST_ADVANCED_PRODUCT)
        with pytest.raises(xcal.SlotTaken):
            adv.book(db, learner, product, row, pick, "UTC")
        db.rollback()
        db.refresh(row)
        assert row.status == "exam_passed" and row.scheduled_at is None
        assert env.google.events == {}                              # nothing went on his calendar
    finally:
        db.delete(row)
        db.delete(learner)
        db.commit()
        db.close()


def test_the_real_clock_is_not_the_pinned_one_here():
    """Guards the test above: exam booking reads the wall clock."""
    assert abs((xcal._utcnow() - datetime.now(timezone.utc)).total_seconds()) < 5
