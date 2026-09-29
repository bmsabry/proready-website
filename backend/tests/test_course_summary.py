"""A course's summary: the current offering first, then its history.

What the owner saw (2026-09-28): the Overview card for Gas Turbine Emissions
Mapping read "5 paid · 1 pending · 9 seats left" for the cohort starting in
November. The five had attended September's cohort; the November cohort had
one pending registration and fourteen free seats. The stats counted every
registration the course had ever had as if it were the current cohort.

Asserted here: `live` is the current cohort only (the registrant rule in
app/registrants.py), `cohort` carries its dates, and `history` carries the
all-time numbers — cohorts delivered, people trained, paid seats, fees.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import conftest  # noqa: F401
from app.db import SessionLocal
from app.main import app
from app.models import Course, Registration

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
CODE = "summary-course-2026-11"


def _reg(email, status, *, created, attended=None, amount=None):
    return Registration(
        course_code=CODE, full_name=email.split("@")[0], email=email, job_title="Engineer",
        company="Plant Co", years_experience="5-10", location="Houston", status=status,
        created_at=created, attended_at=attended, amount_cents=amount,
        payment_provider="stripe" if amount else "",
    )


@pytest.fixture(scope="module")
def seeded():
    now = datetime.now(timezone.utc)
    first_signed_off = now - timedelta(days=100)
    second_signed_off = now - timedelta(days=14)
    db = SessionLocal()
    try:
        db.query(Registration).filter(Registration.course_code == CODE).delete()
        db.query(Course).filter(Course.code == CODE).delete()
        db.add(Course(
            code=CODE, title="Summary Course", start_date=date(2026, 11, 14), total_seats=15,
            price_cents=250_000, currency="usd", status="open",
            day_dates=["2026-11-22", "2026-11-14", "2026-11-15", "2026-11-21"],
        ))
        db.add_all([
            # An earlier cohort, then last month's.
            _reg("a1@x.com", "paid", created=now - timedelta(days=130), attended=first_signed_off),
            _reg("b1@x.com", "paid", created=now - timedelta(days=40), attended=second_signed_off),
            _reg("b2@x.com", "paid", created=now - timedelta(days=40), attended=second_signed_off),
            _reg("b3@x.com", "paid", created=now - timedelta(days=39), attended=second_signed_off,
                 amount=250_000),
            # Cancelled before last month's cohort was signed off: history.
            _reg("c1@x.com", "cancelled", created=now - timedelta(days=60)),
            _reg("c2@x.com", "cancelled", created=now - timedelta(days=50)),
            # The coming cohort.
            _reg("n1@x.com", "pending", created=now - timedelta(days=6)),
            _reg("n2@x.com", "paid", created=now - timedelta(days=5), amount=250_000),
            _reg("n3@x.com", "cancelled", created=now - timedelta(days=4)),
        ])
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    db.query(Registration).filter(Registration.course_code == CODE).delete()
    db.query(Course).filter(Course.code == CODE).delete()
    db.commit()
    db.close()


def _row(client):
    body = client.get("/api/admin/stats/courses", headers=ADMIN).json()
    return next(c for c in body["courses"] if c["code"] == CODE)


def test_the_current_cohort_counts_only_its_own_people(seeded):
    with TestClient(app) as client:
        live = _row(client)["live"]
        assert live["paid"] == 1, "people who attended an earlier cohort are not paid seats now"
        assert live["pending"] == 1
        assert live["seats_taken"] == 2 and live["seats_total"] == 15
        assert live["cancelled"] == 1, "only cancellations since the last cohort was signed off"
        # The same seats the public page and the Courses list show.
        course = client.get(f"/api/admin/courses/{CODE}", headers=ADMIN).json()
        assert course["seats_taken"] == live["seats_taken"]
        assert course["seats_paid"] == live["paid"]


def test_the_cohort_dates_span_all_its_days(seeded):
    with TestClient(app) as client:
        cohort = _row(client)["cohort"]
        assert cohort == {
            "start": "2026-11-14", "end": "2026-11-22", "days": 4,
            "price_cents": 250_000, "currency": "usd",
        }


def test_history_adds_up_everything_the_course_has_done(seeded):
    with TestClient(app) as client:
        h = _row(client)["history"]
        assert h["trained"] == 4
        assert h["cohorts_run"] == 2
        assert [c["trained"] for c in h["cohorts"]] == [3, 1], "newest cohort first"
        assert h["paid_seats"] == 5
        assert h["fees_cents"] == 500_000, "only amounts that were actually recorded"
        assert h["paid_without_amount"] == 3
        assert h["cancelled"] == 3 and h["registrations"] == 9
