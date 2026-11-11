"""Consulting calls: urgency tiers, prices, terms and the admin settings.

The owner's rules (9 Nov 2026): the tier follows the slot's calendar date on
the business clock (New York): same day, next day, 2 to 6 days ahead
(priority), 7 or more (standard), each with its own hourly rate. Billing is
in 30-minute steps. Rates appear in the quote and the booking, and nowhere
else: not in this repository either. The rates used here are the artificial
ones in consult_support.RATES (444, 333, 222 and 111 dollars an hour).

Consulting hours (10 Nov 2026): every day of the week, 08:00 to 23:00 in New
York. The last hours of the New York evening are already the next day in
UTC, so the evening tests below are the ones that would catch a tier taken
from the wrong calendar.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    NOW,
    PUBLIC,
    RATES,
    client,
    env,
    get_quote,
    iso,
    ny,
    world,
)

from app import consult
from app.db import SessionLocal


def _settings():
    db = SessionLocal()
    try:
        cs = consult.settings_row(db)
        db.expunge(cs)
        return cs
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Tier: by the slot's calendar date on the business clock
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "days_ahead, tier, rate",
    [
        (0, "same_day", 44_400),
        (1, "next_day", 33_300),
        (2, "priority", 22_200),
        (6, "priority", 22_200),
        (7, "standard", 11_100),
        (30, "standard", 11_100),
    ],
)
def test_tier_and_rate_by_days_ahead(days_ahead, tier, rate):
    cs = _settings()
    now = ny(2031, 6, 2, 10)                                  # Monday 10:00 in New York
    start = ny(2031, 6, 2, 15) + timedelta(days=days_ahead)   # 15:00 that many days on
    q = consult.make_quote(cs, start, 60, now)
    assert (q.tier, q.rate_cents_per_hour, q.total_cents) == (tier, rate, rate)


def test_the_tier_turns_at_midnight_in_new_york_not_in_utc():
    """Tuesday 09:00 New York is 'next day' until Monday midnight in New
    York and 'same day' one minute later. Midnight UTC, four hours earlier,
    changes nothing."""
    cs = _settings()
    slot = ny(2031, 6, 3, 9)
    assert consult.tier_for(cs, slot, ny(2031, 6, 2, 19, 59)) == "next_day"   # 23:59 UTC
    assert consult.tier_for(cs, slot, ny(2031, 6, 2, 20, 1)) == "next_day"    # 00:01 UTC Tuesday
    assert consult.tier_for(cs, slot, ny(2031, 6, 2, 23, 59)) == "next_day"
    assert consult.tier_for(cs, slot, ny(2031, 6, 3, 0, 1)) == "same_day"
    # and the price follows: the next-day rate before midnight, the same-day rate after
    assert consult.make_quote(cs, slot, 60, ny(2031, 6, 2, 23, 59)).total_cents == RATES["next_day"] == 33_300
    assert consult.make_quote(cs, slot, 60, ny(2031, 6, 3, 0, 1)).total_cents == RATES["same_day"] == 44_400


def test_a_visitor_east_of_new_york_gets_the_business_date_not_their_own():
    """21:00 Monday in New York is already Tuesday in Dubai. A Tuesday slot
    is still 'next day': the business clock decides."""
    cs = _settings()
    now = ny(2031, 6, 2, 21)
    assert now.astimezone(timezone.utc).date().isoformat() == "2031-06-03"
    assert consult.tier_for(cs, ny(2031, 6, 3, 10), now) == "next_day"
    assert consult.tier_for(cs, ny(2031, 6, 9, 10), now) == "standard"   # 7 days on
    assert consult.tier_for(cs, ny(2031, 6, 8, 10), now) == "priority"   # 6 days on


def test_a_late_evening_slot_is_priced_by_its_new_york_date_not_its_utc_date(client, env):
    """22:30 in New York is 02:30 UTC on the following day. Counted on the
    UTC calendar every evening slot would sit one day further out: tonight
    would be 'next day' at the lower rate, and the Sunday-evening slot six
    days ahead would get the standard rate a day early."""
    cs = _settings()
    now = ny(2031, 6, 2, 10)                                   # Monday 10:00 New York
    tonight = ny(2031, 6, 2, 22, 30)
    assert iso(tonight) == "2031-06-03T02:30:00Z"              # Tuesday in UTC
    assert consult.tier_for(cs, tonight, now) == "same_day"
    assert consult.tier_for(cs, ny(2031, 6, 3, 22, 30), now) == "next_day"
    assert consult.tier_for(cs, ny(2031, 6, 4, 22, 30), now) == "priority"
    sunday = ny(2031, 6, 8, 22, 30)                            # 6 New York days ahead, 7 UTC days
    assert iso(sunday) == "2031-06-09T02:30:00Z"
    assert consult.tier_for(cs, sunday, now) == "priority"
    assert consult.tier_for(cs, ny(2031, 6, 9, 22, 30), now) == "standard"

    # The same through the API, in money: 30 minutes tonight is half the same-day rate.
    q = get_quote(client, tonight, 30).json()
    assert (q["tier"], q["rate_cents_per_hour"], q["total_cents"]) == ("same_day", 44_400, 22_200)
    q = get_quote(client, ny(2031, 6, 3, 22, 30), 30).json()
    assert (q["tier"], q["total_cents"]) == ("next_day", 16_650)
    q = get_quote(client, sunday, 30).json()
    assert (q["tier"], q["rate_cents_per_hour"], q["total_cents"]) == ("priority", 22_200, 11_100)
    q = get_quote(client, ny(2031, 6, 9, 22, 30), 30).json()
    assert (q["tier"], q["rate_cents_per_hour"], q["total_cents"]) == ("standard", 11_100, 5_550)


def test_late_in_the_evening_tomorrow_morning_is_still_the_next_day(client, env):
    """At 22:00 on Monday in New York it is already Tuesday in UTC. Tuesday
    08:00 is the next day, not the same day; it becomes the same day at
    New York midnight."""
    cs = _settings()
    env.clock.set(ny(2031, 6, 2, 22, 0))
    assert consult.utcnow().date().isoformat() == "2031-06-03"
    morning = ny(2031, 6, 3, 8)
    q = get_quote(client, morning).json()
    assert (q["tier"], q["total_cents"]) == ("next_day", 33_300)
    assert consult.tier_for(cs, ny(2031, 6, 3, 22, 30), consult.utcnow()) == "next_day"
    env.clock.set(ny(2031, 6, 3, 0, 0))                        # midnight in New York
    q = get_quote(client, morning).json()
    assert (q["tier"], q["total_cents"]) == ("same_day", 44_400)


def test_the_standard_threshold_is_a_setting():
    db = SessionLocal()
    consult.update_settings(db, {"standard_from_days": 3})
    cs = consult.settings_row(db)
    now = ny(2031, 6, 2, 10)
    assert consult.tier_for(cs, ny(2031, 6, 4, 10), now) == "priority"
    assert consult.tier_for(cs, ny(2031, 6, 5, 10), now) == "standard"
    db.close()


# -----------------------------------------------------------------------------
# Billing in 30-minute steps
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rate, minutes, total",
    [
        (44_400, 30, 22_200), (44_400, 60, 44_400), (44_400, 90, 66_600), (44_400, 120, 88_800),
        (33_300, 30, 16_650), (33_300, 90, 49_950),
        (22_200, 30, 11_100), (22_200, 90, 33_300),
        (11_100, 30, 5_550), (11_100, 60, 11_100), (11_100, 90, 16_650), (11_100, 120, 22_200),
        (12_500, 30, 6_250),   # an odd dollar amount still halves to whole cents
    ],
)
def test_thirty_minutes_is_half_the_hourly_rate(rate, minutes, total):
    assert consult.amount_for(rate, minutes) == total


def test_the_fee_is_twenty_percent_of_the_booked_amount():
    assert consult.fee_for(11_100, 20) == 2_220
    assert consult.fee_for(66_600, 20) == 13_320
    assert consult.fee_for(6_250, 20) == 1_250
    assert consult.fee_for(5_550, 20) == 1_110
    assert consult.fee_for(5_550, 0) == 0


def test_quote_endpoint_prices_each_length(client):
    start = ny(2031, 6, 11, 10)   # nine days ahead: standard
    for minutes, total in ((30, 5_550), (60, 11_100), (90, 16_650), (120, 22_200)):
        r = get_quote(client, start, minutes)
        assert r.status_code == 200, r.text
        q = r.json()
        assert q["tier"] == "standard" and q["tier_label"] == "Standard"
        assert q["rate_cents_per_hour"] == 11_100
        assert q["total_cents"] == total
        assert q["fee_percent"] == 20 and q["fee_cents"] == total // 5
        assert q["start"] == iso(start) and q["minutes"] == minutes
    assert set(q) == {
        "start", "minutes", "tier", "tier_label", "rate_cents_per_hour", "total_cents",
        "fee_percent", "fee_cents", "free_cancel_until", "hold_at", "terms_version", "terms",
    }


def test_quote_says_when_cancelling_stops_being_free_and_when_the_hold_lands(client, env):
    far = ny(2031, 6, 11, 10)
    q = get_quote(client, far).json()
    assert q["free_cancel_until"] == iso(far - timedelta(hours=24))
    assert q["hold_at"] == iso(far - timedelta(hours=24))
    # A call later today: the 15-minute rule applies (counted from now, the
    # earliest the booking can be made) and the hold comes right away.
    soon = ny(2031, 6, 2, 15)
    q = get_quote(client, soon).json()
    assert q["tier"] == "same_day" and q["total_cents"] == 44_400
    assert q["free_cancel_until"] == iso(NOW + timedelta(minutes=15))
    assert q["hold_at"] == iso(NOW)
    # Just outside 24 hours, the later of the two limits is the one shown.
    edge = ny(2031, 6, 3, 10, 0)                     # exactly 24 hours ahead
    assert get_quote(client, edge).json()["free_cancel_until"] == iso(NOW + timedelta(minutes=15))
    assert get_quote(client, ny(2031, 6, 3, 10, 30)).json()["free_cancel_until"] == iso(NOW + timedelta(minutes=30))


def test_quote_refuses_a_length_that_is_not_offered(client):
    r = get_quote(client, ny(2031, 6, 11, 10), 45)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail[0]["loc"] == ["body", "minutes"]
    assert "30, 60, 90, 120" in detail[0]["msg"]


def test_quote_refuses_a_time_that_is_not_open(client):
    assert get_quote(client, ny(2031, 6, 7, 10)).status_code == 200        # a Saturday: open every day
    assert get_quote(client, ny(2031, 6, 8, 22, 30), 30).status_code == 200   # Sunday, the last half hour
    assert get_quote(client, ny(2031, 6, 11, 7, 30)).status_code == 409    # before 08:00
    assert get_quote(client, ny(2031, 6, 11, 23, 0), 30).status_code == 409   # at 23:00: closed
    assert get_quote(client, ny(2031, 6, 11, 10, 10)).status_code == 409   # off the half-hour grid
    assert get_quote(client, ny(2031, 6, 2, 11)).status_code == 409        # inside the 2-hour notice
    assert get_quote(client, ny(2031, 8, 2, 10)).status_code == 409        # beyond 60 days
    r = get_quote(client, ny(2031, 6, 11, 22, 30), 60)                     # would run past 23:00
    assert r.status_code == 409 and "no longer available" in r.json()["detail"]
    r = client.post(f"{PUBLIC}/quote", json={"start": "2031-06-11T10:00:00", "minutes": 60})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["body", "start"]


def test_quote_is_rate_limited_per_ip(client):
    start = ny(2031, 6, 11, 10)
    codes = [get_quote(client, start, headers={"X-Forwarded-For": "203.0.113.9"}).status_code for _ in range(41)]
    assert codes[:40] == [200] * 40 and codes[40] == 429
    # another visitor is not held back
    assert get_quote(client, start, headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200


# -----------------------------------------------------------------------------
# Terms
# -----------------------------------------------------------------------------

def test_terms_say_what_the_owner_asked_in_plain_words(client):
    q = get_quote(client, ny(2031, 6, 4, 10), 90).json()   # two days ahead: priority, $222/h in the tests
    text = " ".join(q["terms"])
    assert "$222 per hour" in text and "90-minute call comes to $333" in text
    assert "charged only after the meeting" in text
    assert "temporary hold for $333" in text and "24 hours before the call" in text
    assert "A hold is not a charge" in text
    assert "20% of the booked amount ($66.60)" in text
    assert "free of charge until 24 hours before" in text and "within 15 minutes of booking" in text
    assert "reply to your receipt email" in text and "support team" in text
    assert "third-party proprietary" in text and "export-controlled" in text
    assert "will not be discussed" in text


def test_terms_version_names_the_exact_text_shown(client):
    """The version ends with a digest of the terms text, so two different
    prices can never share a version."""
    a = get_quote(client, ny(2031, 6, 11, 10), 60).json()
    b = get_quote(client, ny(2031, 6, 11, 10), 90).json()
    c = get_quote(client, ny(2031, 6, 12, 14), 60).json()   # another standard slot, same terms
    assert a["terms_version"].startswith(consult.TERMS_VERSION + ".")
    assert a["terms_version"] != b["terms_version"]
    assert a["terms_version"] == c["terms_version"] and a["terms"] == c["terms"]
    digest = consult.terms_hash(a["terms"])
    assert a["terms_version"] == f"{consult.TERMS_VERSION}.{digest[:16]}"


# -----------------------------------------------------------------------------
# Rates never appear in the availability answer
# -----------------------------------------------------------------------------

_MONEY_KEYS = re.compile(r"cents|price|rate|amount|total|fee|usd|dollar|cost", re.I)


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def test_availability_never_contains_a_price(client):
    r = client.get(f"{PUBLIC}/availability", params={"tz": "America/New_York"})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["days"], "the test needs real slots to look at"
    assert set(body) == {"enabled", "business_timezone", "step_minutes", "durations", "days", "next_available"}
    slot_keys = {k for d in body["days"] for s in d["slots"] for k in s}
    assert slot_keys == {"start", "max_minutes", "tier"}
    assert set(body["next_available"]) == {"start", "tier"}
    assert not [k for k in _keys(body) if _MONEY_KEYS.search(k)]
    # No rate, as cents or as dollars, anywhere in the raw text. (The four
    # tiers are all present, so every rate would have had a reason to appear.)
    tiers = {s["tier"] for d in body["days"] for s in d["slots"]}
    assert tiers == {"same_day", "next_day", "priority", "standard"}
    raw = r.text
    assert "$" not in raw
    # every rate in force, as cents and as dollars, and the half-hour amounts
    numbers = {str(c) for c in RATES.values()} | {str(c // 100) for c in RATES.values()}
    numbers |= {str(c // 2) for c in RATES.values()} | {f"{c // 100:,}" for c in RATES.values()}
    assert {"44400", "444", "33300", "333", "22200", "222", "11100", "111", "16650", "5550"} <= numbers
    for number in sorted(numbers):
        # digits of a rate must not appear as a JSON number or inside a string
        assert not re.search(rf'(?<![\d\-T:.]){re.escape(number)}(?![\d\-T:.Z])', raw), number


def test_availability_with_other_rates_is_byte_for_byte_the_same(client):
    """Changing every rate changes nothing in what a visitor can fetch."""
    before = client.get(f"{PUBLIC}/availability", params={"tz": "UTC"}).text
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={
        "rates_cents_per_hour": {"same_day": 888_800, "next_day": 777_700, "priority": 666_600, "standard": 555_500},
    })
    assert r.status_code == 200, r.text
    after = client.get(f"{PUBLIC}/availability", params={"tz": "UTC"}).text
    assert before == after
    assert get_quote(client, ny(2031, 6, 11, 10)).json()["rate_cents_per_hour"] == 555_500


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------

def test_default_settings_are_the_owners(client):
    """Everything but the rates has a default in the code. (The rates and the
    on/off switch are the fixture's here; test_consult_rates_unset.py covers
    the state the code itself starts in.)"""
    r = client.get(f"{ADMIN_API}/settings", headers=ADMIN)
    assert r.status_code == 200
    s = r.json()
    assert s["enabled"] is True and s["timezone"] == "America/New_York"
    # every day of the week, 08:00 to 23:00 (the owner's decision of 10 Nov)
    assert s["weekly_hours"] == {
        d: [["08:00", "23:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    assert s["step_minutes"] == 30 and s["durations"] == [30, 60, 90, 120]
    assert s["buffer_minutes"] == 15 and s["min_notice_hours"] == 2
    assert s["horizon_days"] == 60 and s["max_per_day"] == 4
    assert s["rates_cents_per_hour"] == RATES and s["rates_set"] is True
    assert s["standard_from_days"] == 7 and s["fee_percent"] == 20
    assert s["free_cancel_hours"] == 24 and s["hold_lead_hours"] == 24 and s["auto_settle_hours"] == 2


def test_settings_need_the_admin(client):
    assert client.get(f"{ADMIN_API}/settings").status_code == 401
    assert client.put(f"{ADMIN_API}/settings", json={"enabled": False}).status_code == 401
    assert client.get(f"{ADMIN_API}/bookings").status_code == 401
    assert client.get(f"{ADMIN_API}/status").status_code == 401
    for action in ("charge", "no-show", "waive", "cancel"):
        assert client.post(f"{ADMIN_API}/bookings/1/{action}").status_code == 401
    assert client.post(f"{ADMIN_API}/bookings/1/refund", json={"cents": 100}).status_code == 401


def test_settings_can_be_changed_and_only_what_is_sent_changes(client):
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={
        "weekly_hours": {"mon": [["10:00", "12:00"], ["14:00", "16:00"]]},
        "durations": [60, 30], "buffer_minutes": 0, "min_notice_hours": 4, "horizon_days": 14,
        "max_per_day": 2, "rates_cents_per_hour": {"standard": 12_300}, "fee_percent": 25,
        "free_cancel_hours": 48, "hold_lead_hours": 48, "auto_settle_hours": 3,
    })
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["weekly_hours"]["mon"] == [["10:00", "12:00"], ["14:00", "16:00"]]
    assert s["weekly_hours"]["tue"] == []          # hours are replaced as a whole
    assert s["durations"] == [30, 60]
    assert s["rates_cents_per_hour"] == {**RATES, "standard": 12_300}
    assert (s["fee_percent"], s["free_cancel_hours"], s["hold_lead_hours"], s["auto_settle_hours"]) == (25, 48, 48, 3)
    assert s["timezone"] == "America/New_York" and s["step_minutes"] == 30   # untouched


@pytest.mark.parametrize(
    "change, words",
    [
        ({"timezone": "Mars/Olympus"}, "Unknown time zone"),
        ({"weekly_hours": {"mon": [["18:00", "09:00"]]}}, "end after it starts"),
        ({"weekly_hours": {"mon": [["9", "17:00"]]}}, "09:00"),
        ({"weekly_hours": {"mon": [["09:00", "12:00"], ["11:00", "13:00"]]}}, "overlap"),
        ({"durations": [45]}, "30-minute steps"),
        ({"durations": []}, "at least one"),
        ({"step_minutes": 20}, "15, 30 or 60"),
        ({"rates_cents_per_hour": {"standard": 11_150}}, "whole dollars"),
        ({"rates_cents_per_hour": {"standard": 0}}, "between"),      # a rate that is set cannot be unset
        ({"rates_cents_per_hour": {"vip": 11_100}}, "Unknown tier"),
        ({"fee_percent": 101}, "between 0 and 100"),
        ({"standard_from_days": 1}, "between 2 and 60"),
        ({"hold_lead_hours": 200}, "between 1 and 96"),
        ({"hold_lead_hours": 96, "auto_settle_hours": 48}, "at most 120 hours"),
    ],
)
def test_settings_refuse_nonsense_and_keep_what_was_there(client, change, words):
    before = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json=change)
    assert r.status_code == 422, r.text
    assert words in json.dumps(r.json())
    assert client.get(f"{ADMIN_API}/settings", headers=ADMIN).json() == before


def test_the_admin_screen_can_send_back_the_whole_object_it_was_given(client):
    """The settings form PUTs every field at once, including the read-only
    ones the GET carries."""
    current = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert set(current) >= {
        "enabled", "timezone", "weekly_hours", "step_minutes", "durations", "buffer_minutes",
        "min_notice_hours", "horizon_days", "max_per_day", "rates_cents_per_hour",
        "standard_from_days", "fee_percent", "free_cancel_hours", "hold_lead_hours", "auto_settle_hours",
    }
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json=current)
    assert r.status_code == 200 and r.json() == current


def test_switching_consulting_off_closes_the_public_side(client):
    assert client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={"enabled": False}).status_code == 200
    body = client.get(f"{PUBLIC}/availability").json()
    assert body["enabled"] is False and body["days"] == [] and body["next_available"] is None
    assert get_quote(client, ny(2031, 6, 11, 10)).status_code == 503


def test_the_quote_clock_is_the_pinned_one():
    assert consult.utcnow() == NOW == datetime(2031, 6, 2, 14, 0, tzinfo=timezone.utc)
