"""Consulting calls: the state the code itself starts in.

The repository is public, so it carries no rate. A fresh database has every
rate unset (0) and booking switched off. Nothing is offered, quoted or booked
until the owner has saved all four hourly rates in the admin panel and
switched booking on there; the switch refuses to go on without them.

(Every other consulting test starts from consult_support's fixture, which
does that step with artificial rates.)
"""
from __future__ import annotations

import pytest

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    PUBLIC,
    RATES,
    book,
    client,
    env,
    get_quote,
    ny,
    world,
)

from app import consult
from app.consult_models import ConsultBooking, ConsultSettings
from app.db import SessionLocal

WED = ny(2031, 6, 11, 10)


@pytest.fixture()
def fresh(env):
    """The consulting settings as a new deployment has them: no row yet."""
    db = SessionLocal()
    db.query(ConsultSettings).delete()
    db.commit()
    db.close()
    return env


def _put(client, body: dict):
    return client.put(f"{ADMIN_API}/settings", headers=ADMIN, json=body)


def test_the_code_itself_carries_no_rate_and_starts_switched_off(fresh):
    for tier in consult.TIERS:
        column = ConsultSettings.__table__.c[f"rate_{tier}_cents"]
        assert column.default.arg == 0, tier
    assert ConsultSettings.__table__.c.enabled.default.arg is False
    db = SessionLocal()
    cs = consult.settings_row(db)                    # created on first use, from the code alone
    assert consult.rates(cs) == {"same_day": 0, "next_day": 0, "priority": 0, "standard": 0}
    assert cs.enabled is False and consult.rates_set(cs) is False and consult.bookable(cs) is False
    db.close()


def test_with_no_rates_the_public_side_is_closed(client, fresh):
    body = client.get(f"{PUBLIC}/availability", params={"tz": "America/New_York"}).json()
    assert body["enabled"] is False and body["days"] == [] and body["next_available"] is None
    assert fresh.google.freebusy_calls() == 0        # the calendars are not even asked
    r = get_quote(client, WED)
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"]
    r = book(client, WED, terms_version="2026-11-v1.0000000000000000")
    assert r.status_code == 503
    db = SessionLocal()
    assert db.query(ConsultBooking).count() == 0
    db.close()
    assert fresh.stripe.calls == []                  # nothing was started at Stripe


def test_the_admin_sees_that_the_rates_are_missing(client, fresh):
    s = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert s["enabled"] is False and s["rates_set"] is False
    assert s["rates_cents_per_hour"] == {"same_day": 0, "next_day": 0, "priority": 0, "standard": 0}
    # everything else has its default
    assert s["durations"] == [30, 60, 90, 120] and s["fee_percent"] == 20 and s["hold_lead_hours"] == 24
    status = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert status["enabled"] is False and status["rates_set"] is False
    assert status["calendar_ok"] is True and status["stripe_ok"] is True


def test_booking_cannot_be_switched_on_without_all_four_rates(client, fresh):
    r = _put(client, {"enabled": True})
    assert r.status_code == 422 and "every hourly rate" in r.json()["detail"]
    three = {t: c for t, c in RATES.items() if t != "priority"}
    r = _put(client, {"enabled": True, "rates_cents_per_hour": three})
    assert r.status_code == 422 and "Still missing: priority" in r.json()["detail"]
    # a refused change stores nothing, not even the three rates that were fine
    s = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert s["enabled"] is False and set(s["rates_cents_per_hour"].values()) == {0}
    assert client.get(f"{PUBLIC}/availability").json()["enabled"] is False


def test_saving_the_rates_and_the_switch_opens_booking(client, fresh):
    r = _put(client, {"enabled": True, "rates_cents_per_hour": RATES})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True and r.json()["rates_set"] is True
    assert r.json()["rates_cents_per_hour"] == RATES
    body = client.get(f"{PUBLIC}/availability", params={"tz": "America/New_York"}).json()
    assert body["enabled"] is True and body["days"]
    q = get_quote(client, WED).json()
    assert (q["tier"], q["rate_cents_per_hour"], q["total_cents"]) == ("standard", 11_100, 11_100)
    assert book(client, WED).status_code == 200


def test_saving_the_rates_alone_does_not_switch_booking_on(client, fresh):
    """The rates can be entered ahead of time. Going live is its own switch."""
    r = _put(client, {"rates_cents_per_hour": RATES})
    assert r.status_code == 200 and r.json()["rates_set"] is True and r.json()["enabled"] is False
    assert client.get(f"{PUBLIC}/availability").json()["enabled"] is False
    assert get_quote(client, WED).status_code == 503
    assert _put(client, {"enabled": True}).status_code == 200
    assert client.get(f"{PUBLIC}/availability").json()["enabled"] is True
    assert get_quote(client, WED).status_code == 200


def test_the_settings_form_can_be_saved_while_the_rates_are_still_empty(client, fresh):
    """The form sends back the whole object it was given, zeros included.
    That changes other fields and leaves the rates unset."""
    current = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert _put(client, current).json() == current
    current["buffer_minutes"] = 30
    saved = _put(client, current)
    assert saved.status_code == 200 and saved.json()["buffer_minutes"] == 30
    assert saved.json()["rates_set"] is False and saved.json()["enabled"] is False
    # the read-only flag cannot be forced from outside
    assert _put(client, {"rates_set": True}).json()["rates_set"] is False


def test_a_quote_is_never_made_at_a_rate_of_zero(fresh):
    """Even with the switch forced on in the database, a missing rate means
    no quote and so no booking: a call is never stored at a price of zero."""
    db = SessionLocal()
    cs = consult.settings_row(db)
    cs.enabled = True
    cs.rate_standard_cents = RATES["standard"]       # three tiers still unset
    db.commit()
    now = ny(2031, 6, 2, 10)
    assert consult.make_quote(cs, WED, 60, now).total_cents == 11_100
    with pytest.raises(consult.Unavailable):
        consult.make_quote(cs, ny(2031, 6, 2, 15), 60, now)      # same day: no rate
    assert consult.bookable(cs) is False
    with pytest.raises(consult.Unavailable):
        consult.create_booking(
            db, start=WED, minutes=60, full_name="Casey Client", email="client@example.com",
            topic="A question", timezone_name="UTC", terms_version="x",
        )
    assert db.query(ConsultBooking).count() == 0
    db.close()
