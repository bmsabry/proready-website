"""Consulting calls: booking a time, saving the card, cancelling.

  POST /book        holds the time for 15 minutes and opens Stripe's card
                    page (setup mode: the card is saved, nothing is charged)
  Stripe webhook    card saved: the booking is confirmed exactly once, the
                    call goes on the calendar with a Meet link, both sides
                    get an email
  cancel            free until 24 hours before; the 20% fee after that; a
                    booking made inside 24 hours is free for 15 minutes
"""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import timedelta
import pytest

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    COMPANY,
    NOW,
    OWNER,
    PUBLIC,
    book,
    booking_row,
    charges_of,
    client,
    confirmed,
    env,
    events_of,
    get_quote,
    iso,
    ny,
    post_webhook,
    save_card,
    slot_starts,
    to,
    world,
)

from app import consult
from app import emailer
from app.consult_models import ConsultBooking
from app.db import SessionLocal
from app.models import EmailLog

WED = (2031, 6, 11)               # nine days ahead: standard ($111/h at the tests' artificial rate)
START = ny(*WED, 10)
LINK = '<a href="https://evil.example/pay">Pay for your call here</a>'


def _view(client, b: dict):
    r = client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]})
    assert r.status_code == 200, r.text
    return r.json()


def _cancel(client, b: dict):
    return client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})


# -----------------------------------------------------------------------------
# Booking: the pending hold and the card page
# -----------------------------------------------------------------------------

def test_booking_holds_the_time_and_opens_the_card_page(client, env):
    r = book(client, START, 60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"ref", "manage_token", "checkout_url"}
    assert data["ref"].startswith("C-") and len(data["ref"]) == 10
    assert data["checkout_url"].startswith("https://checkout.stripe.com/")

    row = booking_row(data["ref"])
    assert row.status == "pending_card"
    assert row.hold_expires_at.replace(tzinfo=NOW.tzinfo) == NOW + timedelta(minutes=15)
    assert (row.tier, row.rate_cents_per_hour, row.total_cents, row.fee_cents) == ("standard", 11_100, 11_100, 2_220)
    assert (row.full_name, row.email, row.company) == ("Casey Client", "client@example.com", "Example Turbines")
    assert row.timezone == "Europe/London" and row.minutes == 60

    # Stripe: a customer of this booking's own, and a setup-mode session.
    customer = env.stripe.last("Customer.create")
    assert customer["email"] == "client@example.com" and customer["name"] == "Casey Client"
    session = env.stripe.last("Session.create")
    assert session["mode"] == "setup" and session["payment_method_types"] == ["card"]
    assert session["customer"] == row.stripe_customer_id
    assert session["metadata"] == {
        "kind": "consult", "booking_id": str(row.id), "booking_ref": data["ref"], "purpose": "book",
    }
    base = f"https://proreadyengineer.com/consult/booking/{data['ref']}?t={data['manage_token']}"
    assert session["success_url"] == base + "&card=ok"
    assert session["cancel_url"] == base + "&card=cancelled"
    assert "line_items" not in session and "amount" not in str(session)   # nothing to pay on that page
    assert env.stripe.count("PaymentIntent.create") == 0                   # nothing charged
    assert to(env.outbox, "client@example.com") == []                      # no email until the card is saved

    v = _view(client, {"ref": data["ref"], "token": data["manage_token"]})
    assert set(v) == {
        "ref", "status", "start", "minutes", "timezone", "tier_label", "total_cents", "fee_cents",
        "free_cancel_until", "meet_url", "can_cancel", "cancel_fee_cents", "charged_cents",
        "card_brand", "card_last4", "can_replace_card", "card_problem",
    }
    assert v["status"] == "pending_card" and v["start"] == iso(START) and v["total_cents"] == 11_100
    assert v["meet_url"] is None and v["charged_cents"] is None and v["card_last4"] is None
    assert v["can_cancel"] is True and v["cancel_fee_cents"] == 0
    assert v["free_cancel_until"] == iso(START - timedelta(hours=24))
    assert v["can_replace_card"] is True and v["card_problem"] is False     # "continue to card entry"


def test_a_late_evening_booking_is_stored_at_the_rate_of_its_new_york_date(client, env):
    """Tonight at 22:00 in New York is tomorrow 02:00 in UTC. It is a
    same-day call at the same-day rate, and it is booked as one."""
    tonight = ny(2031, 6, 2, 22, 0)
    assert iso(tonight) == "2031-06-03T02:00:00Z"
    q = get_quote(client, tonight, 60).json()
    assert (q["tier"], q["total_cents"], q["fee_cents"]) == ("same_day", 44_400, 8_880)
    assert "$444 per hour (same day booking)" in q["terms"][0]
    data = book(client, tonight, 60, terms_version=q["terms_version"]).json()
    save_card(client, env, data["ref"])
    row = booking_row(data["ref"])
    assert (row.status, row.tier, row.rate_cents_per_hour, row.total_cents, row.fee_cents) == (
        "confirmed", "same_day", 44_400, 44_400, 8_880)
    assert row.terms_text == q["terms"]
    # Inside 24 hours: free for 15 minutes from the card, and the hold is due now.
    assert row.free_cancel_until.replace(tzinfo=NOW.tzinfo) == NOW + timedelta(minutes=15)
    assert row.hold_due_at.replace(tzinfo=NOW.tzinfo) == NOW
    assert row.settle_due_at.replace(tzinfo=NOW.tzinfo) == ny(2031, 6, 3, 1, 0)     # 23:00 + 2 h
    (mail,) = to(env.outbox, "client@example.com")
    assert "Tuesday, June 3, 2031 at 3:00 AM BST (Europe/London)" in mail["html"]   # their clock
    assert "$444" in mail["html"] and "placed on your card shortly" in mail["html"]
    (alert,) = to(env.outbox, OWNER)
    assert "Monday, June 2, 2031 at 10:00 PM EDT" in alert["subject"]              # his clock
    assert "$444 per hour (Same day)" in alert["html"]
    # The week-ahead evening: Sunday 22:30 is six New York days ahead, so
    # the priority rate, although its UTC date is seven days ahead.
    sunday = ny(2031, 6, 8, 22, 30)
    r = book(client, sunday, 30, email="sun@example.com", ip="203.0.113.21")
    assert r.status_code == 200
    row = booking_row(r.json()["ref"])
    assert (row.tier, row.rate_cents_per_hour, row.total_cents) == ("priority", 22_200, 11_100)


def test_the_consent_record_is_stored_with_the_booking(client, env):
    q = get_quote(client, START, 90).json()
    r = book(client, START, 90, terms_version=q["terms_version"], ip="203.0.113.44")
    row = booking_row(r.json()["ref"])
    assert row.terms_version == q["terms_version"]
    assert row.terms_text == q["terms"]                       # the exact text that was shown
    assert row.terms_hash == hashlib.sha256("\n".join(q["terms"]).encode()).hexdigest()
    assert row.consent_at.replace(tzinfo=NOW.tzinfo) == NOW
    assert row.consent_ip == "203.0.113.44"
    assert row.consent_user_agent == "pytest-consult/1.0"
    # The admin sees the same record.
    a = client.get(f"{ADMIN_API}/bookings/{row.id}", headers=ADMIN).json()
    assert a["consent"] == {
        "terms_version": q["terms_version"], "terms_hash": row.terms_hash, "terms": q["terms"],
        "at": iso(NOW), "ip": "203.0.113.44", "user_agent": "pytest-consult/1.0",
    }


def test_the_manage_token_is_stored_only_as_a_hash(client, env):
    data = book(client, START).json()
    token = data["manage_token"]
    assert len(token) >= 40
    row = booking_row(data["ref"])
    assert row.manage_token_hash == hashlib.sha256(token.encode()).hexdigest()
    columns = {c.name: getattr(row, c.name) for c in ConsultBooking.__table__.columns}
    assert token not in " ".join(str(v) for v in columns.values())
    # …and yet it can be minted again for an email, without being stored.
    db = SessionLocal()
    fresh = db.get(ConsultBooking, row.id)
    assert consult.manage_token(db, fresh) == token
    db.close()


def test_a_booking_is_reached_only_with_its_token(client, env):
    data = book(client, START).json()
    ref, token = data["ref"], data["manage_token"]
    assert client.get(f"{PUBLIC}/booking/{ref}", params={"t": token}).status_code == 200
    assert client.get(f"{PUBLIC}/booking/{ref.lower()}", params={"t": token}).status_code == 200
    wrong = client.get(f"{PUBLIC}/booking/{ref}", params={"t": token[:-1] + ("A" if token[-1] != "A" else "B")})
    missing = client.get(f"{PUBLIC}/booking/C-NOSUCHXX", params={"t": token})
    assert wrong.status_code == missing.status_code == 404
    assert wrong.json() == missing.json()                     # no telling which of the two it was
    assert client.get(f"{PUBLIC}/booking/{ref}").status_code == 404
    assert client.post(f"{PUBLIC}/booking/{ref}/cancel", json={"t": "nope"}).status_code == 404
    assert client.post(f"{PUBLIC}/booking/{ref}/card", json={"t": "nope"}).status_code == 404
    assert booking_row(ref).status == "pending_card"


def test_booking_needs_the_terms_that_are_in_force_now(client, env):
    """Quoted before midnight in New York at the next-day rate; by the time
    the form is sent it is the same day and the rate has gone up. The
    booking is refused, not stored at a price nobody was shown."""
    slot = ny(2031, 6, 3, 15)
    env.clock.set(ny(2031, 6, 2, 23, 58))
    q = get_quote(client, slot).json()
    assert (q["tier"], q["total_cents"]) == ("next_day", 33_300)
    env.clock.set(ny(2031, 6, 3, 0, 1))
    r = book(client, slot, terms_version=q["terms_version"])
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    db = SessionLocal()
    assert db.query(ConsultBooking).count() == 0
    db.close()
    assert env.stripe.calls == []
    # Shown the new price, the client can book.
    q2 = get_quote(client, slot).json()
    assert (q2["tier"], q2["total_cents"]) == ("same_day", 44_400)
    r = book(client, slot, terms_version=q2["terms_version"])
    assert r.status_code == 200 and booking_row(r.json()["ref"]).total_cents == 44_400


def test_a_rate_changed_in_the_admin_between_quote_and_booking_is_not_applied_silently(client, env):
    q = get_quote(client, START).json()
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={"rates_cents_per_hour": {"standard": 12_300}})
    assert r.status_code == 200 and r.json()["rates_cents_per_hour"]["standard"] == 12_300
    assert book(client, START, terms_version=q["terms_version"]).status_code == 409
    assert book(client, START, terms_version="2026-11-v1").status_code == 409     # a bare version is not enough
    r = book(client, START)
    assert r.status_code == 200 and booking_row(r.json()["ref"]).total_cents == 12_300


@pytest.mark.parametrize(
    "fields, where",
    [
        ({"agree": False}, "agree"),
        ({"email": "not-an-email"}, "email"),
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"topic": "  "}, "topic"),
        ({"full_name": "X"}, "full_name"),
        ({"minutes": 45}, "minutes"),
        ({"terms_version": ""}, "terms_version"),
    ],
)
def test_wrong_fields_come_back_as_a_422_list(client, env, fields, where):
    version = get_quote(client, START).json()["terms_version"]
    r = book(client, START, terms_version=fields.pop("terms_version", version), **fields)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail[0]["loc"] == ["body", where] and detail[0]["msg"]
    db = SessionLocal()
    assert db.query(ConsultBooking).count() == 0
    db.close()


def test_the_honeypot_answers_as_if_it_worked_and_does_nothing(client, env):
    r = book(client, START, website="https://spam.example")
    assert r.status_code == 200 and set(r.json()) == {"ref", "manage_token", "checkout_url"}
    db = SessionLocal()
    assert db.query(ConsultBooking).count() == 0
    db.close()
    assert env.stripe.calls == [] and env.outbox == []
    assert iso(START) in slot_starts(client)                  # the time was not held


def test_one_visitor_cannot_sit_on_the_calendar(client, env):
    """Unfinished bookings hold slots without a card. Three per address, two
    per email, eight tries an hour: after that the answer is 429."""
    for i, hour in enumerate((9, 11, 13)):
        r = book(client, ny(*WED, hour), 30, email=f"hoard{i}@example.com", ip="203.0.113.50")
        assert r.status_code == 200, r.text
    r = book(client, ny(*WED, 15), 30, email="hoard9@example.com", ip="203.0.113.50")
    assert r.status_code == 429 and "waiting for a card" in r.json()["detail"]

    # Holds lapse after 15 minutes and the same visitor may book again.
    env.clock.advance(minutes=14, seconds=59)
    assert book(client, ny(*WED, 15), 30, email="hoard9@example.com", ip="203.0.113.50").status_code == 429
    env.clock.advance(seconds=1)
    assert book(client, ny(*WED, 15), 30, email="hoard9@example.com", ip="203.0.113.50").status_code == 200

    # two per email, whatever the address and the capitals
    env.clock.advance(minutes=16)
    for hour in (9, 11):
        assert book(client, ny(2031, 6, 12, hour), 30, email="same@example.com", ip=f"203.0.113.{60 + hour}").status_code == 200
    r = book(client, ny(2031, 6, 12, 13), 30, email="SAME@example.com", ip="203.0.113.99")
    assert r.status_code == 429 and "waiting for a card" in r.json()["detail"]


def test_the_calendar_cannot_be_filled_with_unfinished_bookings_from_many_addresses(client, env):
    """A new address and a new email each time gets past the per-visitor
    limits. Three reservations without a card are kept at once. A fourth
    booking is not refused (review 2, N3: that let a stranger stop everybody
    from booking): it is let in, and the oldest reservation ends."""
    version = get_quote(client, START, 30).json()["terms_version"]
    days = [(2031, 6, d) for d in (11, 12, 13, 14)]
    made = []
    for i in range(3):
        y, m, d = days[i // 2]
        r = book(client, ny(y, m, d, 9 + 3 * (i % 2)), 30, terms_version=version,
                 email=f"many{i}@example.com", ip=f"192.0.2.{10 + i}")
        assert r.status_code == 200, (i, r.text)
        made.append(r.json()["ref"])
        env.clock.advance(seconds=20)
    r = book(client, ny(2031, 6, 15, 9), 30, terms_version=version, email="many8@example.com", ip="192.0.2.99")
    assert r.status_code == 200, r.text
    assert [booking_row(ref).status for ref in made] == ["expired", "pending_card", "pending_card"]
    assert booking_row(r.json()["ref"]).status == "pending_card"
    assert events_of(booking_row(made[0]).id)[-1] == "expired"
    # the time of the reservation that ended is open again
    assert iso(ny(2031, 6, 11, 9)) in slot_starts(client)
    # its client was still entering the card: saved a minute later, with the time still free, it is confirmed
    env.clock.advance(minutes=1)
    assert save_card(client, env, made[0]).status_code == 200
    assert booking_row(made[0]).status == "confirmed"
    assert any("is confirmed" in m["subject"] for m in to(env.outbox, "many0@example.com"))


def test_book_is_rate_limited_per_ip(client, env):
    version = get_quote(client, START).json()["terms_version"]
    codes = []
    for i in range(9):
        r = book(client, START, terms_version="stale-on-purpose", ip="203.0.113.77", email=f"rl{i}@example.com")
        codes.append(r.status_code)
    assert codes == [409] * 8 + [429]
    assert book(client, START, terms_version=version, ip="203.0.113.78").status_code == 200


def test_if_stripe_will_not_open_the_card_page_the_time_goes_straight_back(client, env):
    env.stripe.session_fails = True
    version = get_quote(client, START).json()["terms_version"]
    r = book(client, START, terms_version=version)
    assert r.status_code == 502 and "card entry" in r.json()["detail"]
    db = SessionLocal()
    row = db.query(ConsultBooking).one()
    assert row.status == "expired"
    db.close()
    assert "checkout_failed" in events_of(row.id)
    assert iso(START) in slot_starts(client)
    env.stripe.session_fails = False
    assert book(client, START, terms_version=version).status_code == 200


def test_the_card_page_is_asked_to_expire_soon_after_the_hold_and_works_if_stripe_declines_that(client, env):
    import time as real_time

    r = book(client, START)
    assert r.status_code == 200
    session = env.stripe.last("Session.create")
    life = session["expires_at"] - real_time.time()
    assert 30 * 60 < life <= 31 * 60 + 5                     # Stripe's minimum is 30 minutes
    # Should Stripe not accept an expiry on a setup-mode page, booking still works.
    env.stripe.refuse_expires_at = True
    r = book(client, ny(*WED, 14), email="second@example.com", ip="203.0.113.31")
    assert r.status_code == 200, r.text
    assert "expires_at" not in env.stripe.last("Session.create")
    assert booking_row(r.json()["ref"]).status == "pending_card"
    save_card(client, env, r.json()["ref"])
    assert booking_row(r.json()["ref"]).status == "confirmed"


def test_the_card_page_offers_cards_only_and_works_if_stripe_declines_that(client, env):
    """Without wallet_options Stripe's hosted page also offers Link, and a
    bank account through it, wherever cards are accepted (seen on the real
    page in test mode). The booking terms speak of a card."""
    r = book(client, START)
    assert r.status_code == 200
    session = env.stripe.last("Session.create")
    assert session["wallet_options"] == {"link": {"display": "never"}}
    assert session["payment_method_types"] == ["card"] and session["mode"] == "setup"
    # Should Stripe not accept that on some account or version, booking still works...
    env.stripe.refuse_wallet_options = True
    r = book(client, ny(*WED, 14), email="second@example.com", ip="203.0.113.31")
    assert r.status_code == 200, r.text
    session = env.stripe.last("Session.create")
    assert "wallet_options" not in session and "expires_at" in session      # ...and keeps the short life
    # ...and with both refused, the page is still made, in three tries and no more.
    env.stripe.refuse_expires_at = True
    before = env.stripe.count("Session.create")
    r = book(client, ny(*WED, 16), email="third@example.com", ip="203.0.113.32")
    assert r.status_code == 200, r.text
    session = env.stripe.last("Session.create")
    assert "wallet_options" not in session and "expires_at" not in session
    assert env.stripe.count("Session.create") - before == 3
    save_card(client, env, r.json()["ref"])
    assert booking_row(r.json()["ref"]).status == "confirmed"
    # A refusal that is about anything else is not swallowed: no page, the time is free again.
    env.stripe.refuse_expires_at = env.stripe.refuse_wallet_options = False
    env.stripe.session_fails = True
    assert book(client, ny(*WED, 18), email="fourth@example.com", ip="203.0.113.33").status_code == 502


# -----------------------------------------------------------------------------
# Two people, one time
# -----------------------------------------------------------------------------

def test_the_second_person_to_ask_for_a_time_is_refused(client, env):
    version = get_quote(client, START).json()["terms_version"]
    first = book(client, START, terms_version=version, email="first@example.com", ip="203.0.113.1")
    second = book(client, START, terms_version=version, email="second@example.com", ip="203.0.113.2")
    assert (first.status_code, second.status_code) == (200, 409)
    assert "no longer available" in second.json()["detail"]
    # an overlapping time, and one inside the 15-minute buffer, go the same way
    for start, minutes in ((ny(*WED, 9, 30), 60), (ny(*WED, 11), 30)):
        r = book(client, start, minutes, terms_version=version if minutes == 60 else
                 get_quote(client, ny(2031, 6, 12, 11), 30).json()["terms_version"],
                 email="third@example.com", ip="203.0.113.3")
        assert r.status_code == 409, (start, r.text)
    db = SessionLocal()
    assert db.query(ConsultBooking).count() == 1
    db.close()


def test_two_bookings_for_the_same_time_at_the_same_instant(client, env, monkeypatch):
    """Both requests are inside the calendar check at once (the fake calendar
    answers slowly and they start together). Exactly one gets the time."""
    version = get_quote(client, START).json()["terms_version"]
    real_google = env.google

    def slow_google(method, url, **kw):
        if url.endswith("/freeBusy"):
            time.sleep(0.15)
        return real_google(method, url, **kw)

    monkeypatch.setattr(consult.xcal, "_google", slow_google)
    go = threading.Barrier(6)
    results: list[tuple[str, str]] = []

    def attempt(n: int) -> None:
        db = SessionLocal()
        try:
            go.wait(timeout=10)
            booking, _, _ = consult.create_booking(
                db, start=START, minutes=60, full_name=f"Racer {n}", email=f"racer{n}@example.com",
                topic="Who gets the slot?", timezone_name="UTC", terms_version=version,
                ip=f"203.0.113.{100 + n}", user_agent="race",
            )
            results.append(("booked", booking.ref))
        except consult.SlotGone:
            results.append(("refused", ""))
        except Exception as exc:  # noqa: BLE001 — anything else fails the test below
            results.append(("error", repr(exc)))
        finally:
            db.close()

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(kind for kind, _ in results) == ["booked"] + ["refused"] * 5, results
    db = SessionLocal()
    rows = db.query(ConsultBooking).all()
    assert len(rows) == 1 and rows[0].status == "pending_card"
    db.close()
    assert env.stripe.count("Session.create") == 1            # one card page, for the winner


def test_booking_takes_the_calendar_lock_before_it_looks(client, env, monkeypatch):
    """On Postgres the guard is a row lock on the calendar (the one oral-exam
    bookings take): it must be held before the slots are read and until the
    booking is written."""
    order: list[str] = []
    real_lock, real_slots = consult.xcal.lock, consult.open_slots
    monkeypatch.setattr(consult.xcal, "lock", lambda db: (order.append("lock"), real_lock(db))[1])
    monkeypatch.setattr(
        consult, "open_slots",
        lambda db, cs, now, **kw: (order.append("live" if kw.get("live") else "cached"), real_slots(db, cs, now, **kw))[1],
    )
    version = get_quote(client, START).json()["terms_version"]
    order.clear()
    assert book(client, START, terms_version=version).status_code == 200
    assert order == ["lock", "live"]


# -----------------------------------------------------------------------------
# The card is saved: confirmation, exactly once
# -----------------------------------------------------------------------------

def test_saving_the_card_confirms_the_booking(client, env):
    data = book(client, START, 60).json()
    ref = data["ref"]
    r = save_card(client, env, ref, brand="mastercard", last4="4444")
    assert r.status_code == 200 and r.json() == {"received": True}

    row = booking_row(ref)
    assert row.status == "confirmed" and row.hold_expires_at is None
    assert row.confirmed_at.replace(tzinfo=NOW.tzinfo) == NOW
    assert row.stripe_payment_method_id.startswith("pm_") and row.stripe_setup_intent_id.startswith("seti_")
    assert (row.card_brand, row.card_last4) == ("mastercard", "4444")
    # W1b's clocks are set: hold 24 h before, default outcome 2 h after the end.
    aware = lambda d: d.replace(tzinfo=NOW.tzinfo)  # noqa: E731
    assert aware(row.free_cancel_until) == START - timedelta(hours=24)
    assert aware(row.hold_due_at) == START - timedelta(hours=24)
    assert aware(row.settle_due_at) == START + timedelta(hours=1) + timedelta(hours=2)
    assert row.hold_state == "" and row.charged_cents == 0

    # The call is on the calendar with a Meet link and the client invited.
    (event,) = env.google.events.values()
    assert row.google_event_id in env.google.events and row.meet_url.startswith("https://meet.google.com/")
    assert event["_start"] == START and event["_end"] == START + timedelta(hours=1)
    assert event["attendees"] == [{"email": "client@example.com", "displayName": "Casey Client"}]
    assert "conferenceData" in event and event["_params"]["sendUpdates"] == "all"
    assert "Casey Client" in event["summary"]
    public_text = event["summary"] + event["description"]
    assert "$" not in public_text and "111" not in public_text and "blowout" not in public_text
    assert data["manage_token"] not in public_text

    assert events_of(row.id) == ["created", "card_saved", "confirmed", "calendar_event_created"]
    assert env.stripe.count("PaymentIntent.create") == 0     # still nothing charged

    v = _view(client, {"ref": ref, "token": data["manage_token"]})
    assert v["status"] == "confirmed" and v["meet_url"] == row.meet_url
    assert (v["card_brand"], v["card_last4"]) == ("mastercard", "4444")
    assert v["free_cancel_until"] == iso(START - timedelta(hours=24))
    assert v["can_cancel"] is True and v["cancel_fee_cents"] == 0 and v["charged_cents"] is None


def test_both_sides_get_the_confirmation(client, env):
    data = book(client, START, 60).json()
    save_card(client, env, data["ref"])
    row = booking_row(data["ref"])

    (mail,) = to(env.outbox, "client@example.com")
    assert mail["subject"] == f"Your consulting call is confirmed ({data['ref']})"
    html, text = mail["html"], mail["text"]
    assert "Wednesday, June 11, 2031 at 3:00 PM BST (Europe/London)" in html   # their zone, not New York
    assert f'href="{row.meet_url}"' in html
    manage = f"https://proreadyengineer.com/consult/booking/{data['ref']}?t={data['manage_token']}"
    assert f'href="{manage}"' in html and manage in text
    assert "$111" in html and "charged only after the meeting" in html
    assert "Visa ending 4242" in html
    assert "20% of the booked amount ($22.20)" in html
    assert "Tuesday, June 10, 2031 at 3:00 PM BST" in html                    # free cancellation until
    assert f"invitation from {COMPANY}" in html
    assert "export-controlled" in html                                        # the terms they agreed to
    assert row.confirmation_sent_at is not None

    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"].startswith("[Consulting] New booking: Casey Client, Wednesday, June 11, 2031 at 10:00 AM EDT")
    for needle in ("client@example.com", "Example Turbines", "+1 555 0100", "Lean blowout margin",
                   "$111 per hour (Standard)", "60 minutes", "Visa ending 4242", row.meet_url, data["ref"]):
        assert needle in alert["html"], needle
    assert data["manage_token"] not in alert["html"]


def test_the_copy_kept_in_the_email_log_has_no_manage_token(client, env):
    data = book(client, START).json()
    save_card(client, env, data["ref"])
    db = SessionLocal()
    log = db.query(EmailLog).filter(EmailLog.template == "consult_confirmed").one()
    assert log.recipient == "client@example.com" and log.ok is True
    assert log.scope_code == "consult" and log.audience == "client"
    assert data["manage_token"] not in log.body_html and data["manage_token"] not in log.body_text
    assert f"/consult/booking/{data['ref']}?t=(hidden)" in log.body_html
    assert f"/consult/booking/{data['ref']}?t=(hidden)" in log.body_text
    owner = db.query(EmailLog).filter(EmailLog.template == "consult_owner_new").one()
    assert owner.recipient == OWNER and owner.audience == "admin"
    db.close()


def test_the_webhook_delivered_twice_confirms_once(client, env):
    data = book(client, START).json()
    event = env.stripe.card_saved_event(booking_row(data["ref"]).stripe_checkout_session_id)
    for _ in range(3):
        assert post_webhook(client, env, event).status_code == 200
    row = booking_row(data["ref"])
    assert row.status == "confirmed"
    # the timeline shows one confirmation and nothing after it
    assert events_of(row.id) == ["created", "card_saved", "confirmed", "calendar_event_created"]
    assert env.stripe.count("PaymentIntent.create") == 0
    assert len(env.google.events) == 1                         # one meeting, not three
    assert len(to(env.outbox, "client@example.com")) == 1      # one confirmation
    assert len(to(env.outbox, OWNER)) == 1


def test_the_webhook_delivered_twice_at_the_same_instant_confirms_once(client, env):
    data = book(client, START).json()
    row = booking_row(data["ref"])
    event = env.stripe.card_saved_event(row.stripe_checkout_session_id)["data"]["object"]
    go = threading.Barrier(4)
    outcomes: list[str] = []

    def deliver() -> None:
        db = SessionLocal()
        try:
            go.wait(timeout=10)
            outcomes.append(consult.on_checkout_completed(db, dict(event)))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(repr(exc))
        finally:
            db.close()

    threads = [threading.Thread(target=deliver) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["confirmed", "replay", "replay", "replay"], outcomes
    assert len(env.google.events) == 1
    assert len(to(env.outbox, "client@example.com")) == 1 and len(to(env.outbox, OWNER)) == 1
    assert events_of(row.id).count("confirmed") == 1


def test_other_stripe_events_and_other_sessions_are_left_to_their_own_branches(client, env):
    """A consulting card page never reaches the course-purchase code, and a
    course purchase never reaches the consulting code."""
    data = book(client, START).json()
    row = booking_row(data["ref"])
    expired = {"type": "checkout.session.expired", "data": {"object": {
        "id": row.stripe_checkout_session_id, "mode": "setup", "metadata": {"kind": "consult", "booking_id": str(row.id)},
    }}}
    assert post_webhook(client, env, expired).status_code == 200
    assert booking_row(data["ref"]).status == "pending_card"
    # A course checkout with no consult tag: handled by the old branch (which
    # finds no email/product and does nothing), not by us.
    other = {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_other", "payment_status": "paid", "metadata": {}, "setup_intent": "seti_x",
    }}}
    assert post_webhook(client, env, other).status_code == 200
    assert env.stripe.count("SetupIntent.retrieve") == 0
    # Tampered metadata naming a booking that does not exist: ignored.
    ghost = env.stripe.card_saved_event(row.stripe_checkout_session_id)
    ghost["data"]["object"]["metadata"]["booking_id"] = "999999"
    assert post_webhook(client, env, ghost).status_code == 200
    assert booking_row(data["ref"]).status == "pending_card"


def test_a_card_from_another_customer_cannot_confirm_a_booking(client, env):
    a = book(client, START, email="a@example.com", ip="203.0.113.1").json()
    b = book(client, ny(*WED, 14), email="b@example.com", ip="203.0.113.2").json()
    event = env.stripe.card_saved_event(booking_row(b["ref"]).stripe_checkout_session_id)
    event["data"]["object"]["metadata"]["booking_id"] = str(booking_row(a["ref"]).id)
    assert post_webhook(client, env, event).status_code == 200
    assert booking_row(a["ref"]).status == "pending_card" and booking_row(a["ref"]).stripe_payment_method_id == ""


def test_if_stripe_cannot_be_asked_for_the_card_the_webhook_fails_so_it_is_sent_again(client, env):
    data = book(client, START).json()
    env.stripe.setup_intent_fails = True
    with pytest.raises(Exception):
        save_card(client, env, data["ref"])
    assert booking_row(data["ref"]).status == "pending_card"
    env.stripe.setup_intent_fails = False
    assert save_card(client, env, data["ref"]).status_code == 200
    assert booking_row(data["ref"]).status == "confirmed"


def test_if_google_refuses_the_event_the_booking_still_stands_and_the_owner_is_told(client, env):
    env.google.event_fails = True
    data = book(client, START).json()
    assert save_card(client, env, data["ref"]).status_code == 200
    row = booking_row(data["ref"])
    assert row.status == "confirmed" and row.google_event_id == "" and row.meet_url == ""
    assert "calendar_event_failed" in events_of(row.id)
    (alert,) = to(env.outbox, OWNER)
    assert "Needs your attention" in alert["html"] and "Create the meeting by hand" in alert["html"]
    (mail,) = to(env.outbox, "client@example.com")
    assert "the link is in the calendar invitation" in mail["html"]
    # The seam for a later retry (the cron tick) creates it, once.
    env.google.event_fails = False
    db = SessionLocal()
    assert consult.ensure_calendar_event(db, db.get(ConsultBooking, row.id)) is True
    assert consult.ensure_calendar_event(db, db.get(ConsultBooking, row.id)) is True
    db.close()
    assert len(env.google.events) == 1 and booking_row(data["ref"]).meet_url.startswith("https://meet.google.com/")


# -----------------------------------------------------------------------------
# The hold runs out
# -----------------------------------------------------------------------------

def test_a_pending_booking_expires_after_fifteen_minutes_and_frees_the_time(client, env):
    data = book(client, START, email="slow@example.com").json()
    b = {"ref": data["ref"], "token": data["manage_token"]}
    env.clock.advance(minutes=14, seconds=59)
    assert _view(client, b)["status"] == "pending_card"
    assert iso(START) not in slot_starts(client)
    env.clock.advance(seconds=1)
    v = _view(client, b)
    assert v["status"] == "expired" and v["can_cancel"] is False and v["meet_url"] is None
    assert iso(START) in slot_starts(client)
    assert booking_row(data["ref"]).status == "expired" and "expired" in events_of(booking_row(data["ref"]).id)
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 409 and "book again" in r.json()["detail"]
    # Someone else can now take it.
    assert book(client, START, email="quick@example.com", ip="203.0.113.5").status_code == 200


def test_a_card_saved_after_the_hold_ran_out_confirms_only_if_the_time_is_still_free(client, env):
    data = book(client, START, email="slow@example.com").json()
    env.clock.advance(minutes=25)
    assert save_card(client, env, data["ref"]).status_code == 200
    row = booking_row(data["ref"])
    assert row.status == "confirmed"                           # nobody took it: revived
    assert "Revived" in " ".join(
        e.note for e in SessionLocal().query(consult.ConsultBookingEvent).filter_by(booking_id=row.id)
    )
    assert len(env.google.events) == 1
    assert len(to(env.outbox, "slow@example.com")) == 1


def test_a_card_saved_after_someone_else_took_the_time_is_turned_away(client, env):
    slow = book(client, START, email="slow@example.com", ip="203.0.113.1").json()
    env.clock.advance(minutes=21)
    quick = confirmed(client, env, START, email="quick@example.com", ip="203.0.113.2")
    env.outbox.clear()
    env.clock.advance(minutes=5)
    assert save_card(client, env, slow["ref"]).status_code == 200
    row = booking_row(slow["ref"])
    assert row.status == "expired" and row.stripe_payment_method_id == ""      # the card is not kept
    assert "slot_lost" in events_of(row.id)
    assert booking_row(quick["ref"]).status == "confirmed"
    assert len(env.google.events) == 1                         # only the quick one's meeting
    (mail,) = to(env.outbox, "slow@example.com")
    assert "could not be confirmed" in mail["subject"]
    assert "Nothing was charged" in mail["html"] and "the card you entered will not be used" in mail["html"]
    assert to(env.outbox, OWNER) == []
    assert env.stripe.count("PaymentIntent.create") == 0
    # Redelivery of the same event: nothing more.
    save_card(client, env, slow["ref"])
    assert len(to(env.outbox, "slow@example.com")) == 1


def test_a_late_card_is_turned_away_when_his_calendar_filled_meanwhile(client, env):
    data = book(client, START, email="slow@example.com").json()
    env.clock.advance(minutes=25)
    env.google.busy["primary"] = [(ny(*WED, 10, 30), ny(*WED, 11, 30))]
    save_card(client, env, data["ref"])
    assert booking_row(data["ref"]).status == "expired"
    assert env.google.events == {}


def test_a_late_card_waits_for_another_delivery_when_the_calendar_cannot_be_read(client, env):
    data = book(client, START, email="slow@example.com").json()
    env.clock.advance(minutes=25)
    env.google.errors["primary"] = "backendError"
    with pytest.raises(Exception):
        save_card(client, env, data["ref"])
    assert booking_row(data["ref"]).status in ("pending_card", "expired")
    assert booking_row(data["ref"]).stripe_setup_intent_id == ""     # not marked as handled
    env.google.errors.clear()
    save_card(client, env, data["ref"])
    assert booking_row(data["ref"]).status == "confirmed"


def test_an_exam_booked_into_a_pending_hold_wins_and_the_client_is_told(client, env):
    """Oral-exam booking does not know about a consulting hold that has no
    calendar event yet. If one lands there before the card is saved, the
    consulting booking is not confirmed on top of it."""
    from app.models import AdvancedCertification

    data = book(client, START).json()
    db = SessionLocal()
    exam = AdvancedCertification(
        learner_id=987_002, product_code="consult-test-product", source="manual", amount_cents=0,
        currency="usd", status="scheduled", fee_status="waived", scheduled_at=START,
    )
    db.add(exam)
    db.commit()
    try:
        save_card(client, env, data["ref"])
        assert booking_row(data["ref"]).status == "expired"
        assert env.google.events == {}
        assert "could not be confirmed" in to(env.outbox, "client@example.com")[0]["subject"]
    finally:
        db.delete(exam)
        db.commit()
        db.close()


# -----------------------------------------------------------------------------
# Cancelling
# -----------------------------------------------------------------------------

def test_cancelling_more_than_24_hours_ahead_is_free(client, env):
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=24))                 # the last free moment
    assert _view(client, b)["cancel_fee_cents"] == 0
    r = _cancel(client, b)
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "cancelled" and v["charged_cents"] is None and v["can_cancel"] is False
    assert v["meet_url"] is None
    row = booking_row(b["ref"])
    assert (row.cancelled_by, row.cancel_fee_cents, row.settlement, row.charged_cents) == ("client", 0, "", 0)
    assert env.stripe.count("PaymentIntent.create") == 0 and charges_of(b["id"]) == []
    assert env.google.events == {}                             # the event is deleted (Google tells the guest)
    assert iso(START) in slot_starts(client)
    (mail,) = to(env.outbox, "client@example.com")
    assert "is cancelled" in mail["subject"] and "Nothing was charged" in mail["html"]
    (alert,) = to(env.outbox, OWNER)
    assert "A client cancelled a call" in alert["subject"] and "no fee" in alert["html"]


def test_cancelling_inside_24_hours_costs_the_fee(client, env):
    b = confirmed(client, env, START, 90)                      # $166.50, fee $33.30
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=24) + timedelta(seconds=1))
    assert _view(client, b)["cancel_fee_cents"] == 3_330
    r = _cancel(client, b)
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "cancelled" and v["charged_cents"] == 3_330
    row = booking_row(b["ref"])
    assert (row.cancel_fee_cents, row.settlement, row.amount_due_cents, row.charge_state) == (3_330, "late_cancel", 3_330, "paid")
    assert row.charged_cents == 3_330
    # One off-session charge of exactly the fee, on the saved card.
    assert env.stripe.count("PaymentIntent.create") == 1
    pi = env.stripe.last("PaymentIntent.create")
    assert pi["amount"] == 3_330 and pi["currency"] == "usd" and pi["capture_method"] == "automatic"
    assert pi["customer"] == row.stripe_customer_id and pi["payment_method"] == row.stripe_payment_method_id
    assert pi["off_session"] is True and pi["confirm"] is True
    (charge,) = charges_of(b["id"])
    assert (charge.kind, charge.reason, charge.status, charge.amount_cents) == ("charge", "late_cancel_fee", "succeeded", 3_330)
    assert env.stripe.money_taken() == 3_330
    assert env.google.events == {} and iso(START) in slot_starts(client)
    (mail,) = to(env.outbox, "client@example.com")
    assert "20% fee of $33.30 was charged to your card (Visa ending 4242)" in mail["html"]
    (alert,) = to(env.outbox, OWNER)
    assert "the fee was charged" in alert["subject"]


def test_free_cancel_until_is_the_deadline_while_it_is_open_and_null_once_it_is_not(client, env):
    """null means exactly one thing: no free cancellation is available."""
    b = confirmed(client, env, START)
    deadline = iso(START - timedelta(hours=24))
    assert _view(client, b)["free_cancel_until"] == deadline
    env.clock.set(START - timedelta(hours=24))
    assert _view(client, b)["free_cancel_until"] == deadline              # still open at the deadline itself
    env.clock.advance(seconds=1)
    v = _view(client, b)
    assert v["free_cancel_until"] is None and v["cancel_fee_cents"] == 2_220 and v["can_cancel"] is True
    env.clock.set(START + timedelta(minutes=5))
    assert _view(client, b)["free_cancel_until"] is None
    r = _cancel(client, confirmed(client, env, ny(2031, 6, 12, 10), email="other@example.com", ip="203.0.113.8"))
    assert r.json()["status"] == "cancelled" and r.json()["free_cancel_until"] is None


def test_a_pending_booking_inside_24_hours_shows_the_15_minute_deadline(client, env):
    data = book(client, ny(2031, 6, 2, 15)).json()
    b = {"ref": data["ref"], "token": data["manage_token"]}
    assert _view(client, b)["free_cancel_until"] == iso(NOW + timedelta(minutes=15))
    env.clock.advance(minutes=4)                                           # card saved four minutes in
    save_card(client, env, data["ref"])
    assert _view(client, b)["free_cancel_until"] == iso(NOW + timedelta(minutes=19))
    env.clock.advance(minutes=15, seconds=1)
    assert _view(client, b)["free_cancel_until"] is None


def test_cancelling_twice_charges_the_fee_once(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=3))
    env.outbox.clear()
    first, second = _cancel(client, b), _cancel(client, b)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert env.stripe.money_taken() == 2_220 and env.stripe.count("PaymentIntent.create") == 1
    assert len(to(env.outbox, "client@example.com")) == 1


def test_a_cancellation_cut_short_is_finished_by_asking_again_and_nothing_happens_twice(client, env, monkeypatch):
    """The server dies right after the cancellation is recorded: the time is
    free, but the fee is not taken, the meeting is still on the calendar and
    nobody was told. A repeat within two minutes is taken for a double click
    and does nothing; after that it finishes the job, once."""
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=2))
    env.outbox.clear()
    real_finish = consult.finish_cancellation

    def dies(db, booking_id):
        raise RuntimeError("the server stopped here")

    monkeypatch.setattr(consult, "finish_cancellation", dies)
    with pytest.raises(RuntimeError):
        _cancel(client, b)
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.amount_due_cents, row.charge_state) == ("cancelled", "late_cancel", 2_220, "pending")
    assert env.stripe.money_taken() == 0 and len(env.google.events) == 1 and env.outbox == []
    # Our own record no longer holds the time, but the meeting is still on
    # his calendar, so it is not offered again until the job is finished.
    assert iso(START + timedelta(hours=2)) in slot_starts(client) and iso(START) not in slot_starts(client)

    monkeypatch.setattr(consult, "finish_cancellation", real_finish)
    env.clock.advance(seconds=30)
    assert _cancel(client, b).json()["status"] == "cancelled"  # too soon to tell a crash from a double click
    assert env.stripe.money_taken() == 0 and env.outbox == []

    env.clock.advance(minutes=2)
    r = _cancel(client, b)
    assert r.status_code == 200 and r.json()["charged_cents"] == 2_220
    assert env.stripe.money_taken() == 2_220 and env.google.events == {}
    assert len(to(env.outbox, "client@example.com")) == 1 and len(to(env.outbox, OWNER)) == 1
    assert iso(START + timedelta(minutes=30)) in slot_starts(client)       # the calendar is clear again
    env.clock.advance(minutes=5)
    assert _cancel(client, b).json()["charged_cents"] == 2_220  # and again: nothing more
    assert env.stripe.money_taken() == 2_220 and env.stripe.count("PaymentIntent.create") == 1
    assert len(to(env.outbox, "client@example.com")) == 1 and len(to(env.outbox, OWNER)) == 1
    assert booking_row(b["ref"]).cancel_notice_sent_at is not None


def test_a_booking_made_inside_24_hours_is_free_to_cancel_for_15_minutes(client, env):
    today = ny(2031, 6, 2, 15)                                 # five hours from now: same day
    b = confirmed(client, env, today)
    row = booking_row(b["ref"])
    assert row.free_cancel_until.replace(tzinfo=NOW.tzinfo) == NOW + timedelta(minutes=15)
    v = _view(client, b)
    assert v["free_cancel_until"] == iso(NOW + timedelta(minutes=15)) and v["cancel_fee_cents"] == 0
    env.clock.advance(minutes=15)                              # the last free moment
    assert _view(client, b)["cancel_fee_cents"] == 0
    r = _cancel(client, b)
    assert r.json()["status"] == "cancelled" and r.json()["charged_cents"] is None
    assert env.stripe.money_taken() == 0


def test_after_the_15_minutes_a_same_day_booking_costs_the_fee(client, env):
    b = confirmed(client, env, ny(2031, 6, 2, 15))
    env.clock.advance(minutes=15, seconds=1)
    assert _view(client, b)["cancel_fee_cents"] == 8_880       # 20% of the same-day $444
    r = _cancel(client, b)
    assert r.json()["charged_cents"] == 8_880 and env.stripe.money_taken() == 8_880


def test_the_15_minutes_count_from_the_moment_the_card_was_saved(client, env):
    data = book(client, ny(2031, 6, 2, 15)).json()
    env.clock.advance(minutes=10)                              # ten minutes on Stripe's page
    save_card(client, env, data["ref"])
    b = {"ref": data["ref"], "token": data["manage_token"]}
    env.clock.advance(minutes=14)
    assert _view(client, b)["cancel_fee_cents"] == 0
    env.clock.advance(minutes=2)
    assert _view(client, b)["cancel_fee_cents"] == 8_880


def test_a_booking_made_just_outside_24_hours_still_gets_its_15_minutes(client, env):
    """Booked 24 h 05 min ahead: '24 hours before' would leave five minutes.
    The more generous of the two limits applies."""
    env.clock.set(ny(2031, 6, 10, 9, 55))
    b = confirmed(client, env, START)
    row = booking_row(b["ref"])
    assert row.free_cancel_until.replace(tzinfo=NOW.tzinfo) == ny(2031, 6, 10, 10, 10)
    env.clock.set(ny(2031, 6, 10, 10, 9))
    assert _view(client, b)["cancel_fee_cents"] == 0
    env.clock.set(ny(2031, 6, 10, 10, 11))
    assert _view(client, b)["cancel_fee_cents"] == 6_660       # 20% of the next-day $333


def test_cancelling_before_the_card_is_saved_is_free_and_a_late_card_is_ignored(client, env):
    data = book(client, START).json()
    b = {"ref": data["ref"], "token": data["manage_token"]}
    r = _cancel(client, b)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["charged_cents"] is None
    assert iso(START) in slot_starts(client)
    assert env.outbox == []
    save_card(client, env, data["ref"])                        # they finish the card page anyway
    row = booking_row(data["ref"])
    assert row.status == "cancelled" and row.stripe_payment_method_id == ""
    assert env.google.events == {} and env.outbox == []


def test_a_call_that_has_started_cannot_be_cancelled_by_the_client(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START)
    v = _view(client, b)
    assert v["can_cancel"] is False and v["cancel_fee_cents"] == 0
    r = _cancel(client, b)
    assert r.status_code == 409 and "already started" in r.json()["detail"]
    assert booking_row(b["ref"]).status == "confirmed" and env.stripe.money_taken() == 0


def test_a_fee_that_the_card_refuses_still_cancels_and_is_collected_on_a_new_card(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=2))
    env.outbox.clear()
    env.stripe.card = "declined"
    r = _cancel(client, b)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["charged_cents"] is None
    row = booking_row(b["ref"])
    assert (row.settlement, row.amount_due_cents, row.charge_state, row.charged_cents) == ("late_cancel", 2_220, "failed", 0)
    assert iso(START) in slot_starts(client)                   # the time is free regardless
    (mail,) = to(env.outbox, "client@example.com")
    assert "could not charge your card" in mail["html"] and "$22.20" in mail["html"]
    (alert,) = to(env.outbox, OWNER)
    assert "could NOT be charged" in alert["subject"] and "Your card was declined" in alert["html"]

    v = _view(client, b)
    assert v["card_problem"] is True and v["can_replace_card"] is True    # the page asks for another card

    # The client replaces the card from their page: the fee is taken at once.
    env.stripe.card = "ok"
    env.outbox.clear()
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 200 and r.json()["checkout_url"].startswith("https://checkout.stripe.com/")
    assert env.stripe.last("Session.create")["metadata"]["purpose"] == "card"
    assert env.stripe.count("Customer.create") == 1            # the same customer, not a new one
    save_card(client, env, b["ref"], brand="amex", last4="0005")
    row = booking_row(b["ref"])
    assert (row.card_brand, row.card_last4, row.charge_state, row.charged_cents) == ("amex", "0005", "paid", 2_220)
    assert env.stripe.money_taken() == 2_220
    assert [c.status for c in charges_of(b["id"])] == ["failed", "succeeded"]
    assert "went through" in to(env.outbox, OWNER)[0]["subject"]
    v = _view(client, b)
    assert v["charged_cents"] == 2_220 and v["card_problem"] is False and v["can_replace_card"] is False


# -----------------------------------------------------------------------------
# The card page again
# -----------------------------------------------------------------------------

def test_a_pending_booking_can_reopen_card_entry(client, env):
    data = book(client, START).json()
    b = {"ref": data["ref"], "token": data["manage_token"]}
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 200
    assert r.json()["checkout_url"] != data["checkout_url"]
    assert env.stripe.last("Session.create")["metadata"]["purpose"] == "book"
    assert env.stripe.count("Customer.create") == 1
    # Either page confirms the booking; the other one, finished later, is
    # taken as a replacement card, not a second confirmation.
    sessions = list(env.stripe.sessions)
    post_webhook(client, env, env.stripe.card_saved_event(sessions[0], last4="1111"))
    assert booking_row(b["ref"]).status == "confirmed"
    post_webhook(client, env, env.stripe.card_saved_event(sessions[1], last4="2222"))
    row = booking_row(b["ref"])
    assert row.card_last4 == "2222" and events_of(row.id).count("confirmed") == 1
    assert "card_replaced" in events_of(row.id)
    assert len(env.google.events) == 1 and len(to(env.outbox, "client@example.com")) == 1


def test_a_confirmed_booking_can_replace_its_card_and_a_closed_one_cannot(client, env):
    b = confirmed(client, env, START)
    v = _view(client, b)
    assert v["can_replace_card"] is True and v["card_problem"] is False
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 200
    save_card(client, env, b["ref"], brand="mastercard", last4="5454")
    assert booking_row(b["ref"]).card_last4 == "5454"
    assert _view(client, b)["card_last4"] == "5454"
    _cancel(client, b)
    assert _view(client, b)["can_replace_card"] is False
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 409 and "does not need a card" in r.json()["detail"]


def test_can_replace_card_says_exactly_when_the_card_page_will_open(client, env):
    """The flag and the endpoint never disagree, in any state."""
    def agree(b: dict) -> bool:
        flag = _view(client, b)["can_replace_card"]
        code = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code
        assert (code == 200) is flag, (flag, code)
        return flag

    data = book(client, START, email="p@example.com", ip="203.0.113.1").json()
    pending = {"ref": data["ref"], "token": data["manage_token"]}
    assert agree(pending) is True
    ok = confirmed(client, env, ny(*WED, 14), email="c@example.com", ip="203.0.113.2")
    assert agree(ok) is True
    env.clock.advance(minutes=21)
    assert agree(pending) is False                                         # expired
    _cancel(client, ok)
    assert agree(ok) is False                                              # cancelled, nothing owed


def test_a_failed_hold_is_flagged_so_the_page_can_ask_for_another_card(client, env):
    """W1b places the hold; when the card refuses it, the booking view says so."""
    from app import consult_money as money

    b = confirmed(client, env, START)
    env.stripe.card = "declined"
    db = SessionLocal()
    result = money.place_hold(db, db.get(ConsultBooking, b["id"]))
    db.close()
    assert result.ok is False and booking_row(b["ref"]).hold_state == "failed"
    v = _view(client, b)
    assert v["status"] == "confirmed" and v["card_problem"] is True and v["can_replace_card"] is True


# -----------------------------------------------------------------------------
# Emails: what a stranger types reaches an inbox as text
# -----------------------------------------------------------------------------

def _no_live_markup(html: str) -> None:
    assert '<a href="https://evil.example' not in html
    assert "evil.example/pay\">" not in html
    assert "<script" not in html.lower() and "<img" not in html.lower()
    assert "<b>Al</b>" not in html


def test_typed_markup_in_a_booking_reaches_both_inboxes_as_text(client, env):
    r = book(
        client, START, name=f"<b>Al</b> {LINK}", company=f"{LINK} <script>alert(1)</script>",
        phone='<img src=x onerror=1>', topic=f"First line {LINK}\n<script>steal()</script> second line",
    )
    assert r.status_code == 200, r.text
    save_card(client, env, r.json()["ref"])
    (mail,) = to(env.outbox, "client@example.com")
    (alert,) = to(env.outbox, OWNER)
    _no_live_markup(mail["html"])
    _no_live_markup(alert["html"])
    assert "Hi &lt;b&gt;Al&lt;/b&gt;," in mail["html"]         # shown as the text that was typed
    assert "&lt;a href=" in alert["html"]
    assert "&lt;script&gt;steal()&lt;/script&gt; second line" in alert["html"]
    assert "&lt;img src=x onerror=1&gt;" in alert["html"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in alert["html"]
    # and in the cancellation emails
    env.outbox.clear()
    data = r.json()
    _cancel(client, {"ref": data["ref"], "token": data["manage_token"]})
    (mail,) = to(env.outbox, "client@example.com")
    (alert,) = to(env.outbox, OWNER)
    _no_live_markup(mail["html"])
    _no_live_markup(alert["html"])
    assert "Hi &lt;b&gt;Al&lt;/b&gt;," in mail["html"]
    assert "&lt;b&gt;Al&lt;/b&gt; &lt;a href=" in alert["html"]


def test_every_value_in_the_four_templates_is_escaped():
    evil = f'{LINK}<script>x</script>"onmouseover="y'
    pages = [
        emailer.consult_confirmed_html(
            full_name=evil, when=evil, minutes=60, meet_url=f'https://meet.google.com/x"><b>{evil}',
            manage_url=f'https://proreadyengineer.com/consult/booking/C-1?t=tok"><b>{evil}', ref=evil,
            total=evil, card=evil, hold_when=evil, free_cancel_until=evil, fee=evil, fee_percent=20,
            terms=[evil, evil], invite_from=evil, expert=evil,
        ),
        emailer.consult_cancelled_html(
            full_name=evil, when=evil, kind="owner", money_line=evil, note=evil,
            rebook_url=f'https://proreadyengineer.com/consult"><b>{evil}', ref=evil,
        ),
        emailer.consult_cancelled_html(full_name=evil, when=evil, kind="slot_lost", money_line=evil, ref=evil),
        emailer.consult_cancelled_html(full_name=evil, when=evil, kind="client", money_line=evil, ref=evil),
        emailer.consult_owner_new_html(
            rows=[(evil, evil), ("Client", evil)], topic=f"{evil}\n{evil}", meet_url=f'https://x"><b>{evil}',
            calendar_problem="", admin_url=f'https://proreadyengineer.com/admin"><b>{evil}',
        ),
        emailer.consult_owner_new_html(rows=[("Client", evil)], topic=evil, calendar_problem=evil),
        emailer.consult_owner_update_html(
            headline=evil, detail=evil, rows=[(evil, evil)], admin_url=f'https://x"><b>{evil}',
        ),
    ]
    for html in pages:
        assert "<script>x</script>" not in html
        assert '<a href="https://evil.example' not in html
        assert '"onmouseover="' not in html and '"><b>' not in html
        assert "&lt;script&gt;x&lt;/script&gt;" in html
        # the plain-text part shows what was typed, as text
        assert "<script>x</script>" in emailer.html_to_text(html)


def _consult_templates() -> dict:
    row = [("Client", "Ada Lovelace (ada@example.com)"), ("Booked amount", "$111")]
    common = dict(full_name="Ada Lovelace", when="Wednesday, June 11, 2031 at 3:00 PM BST (Europe/London)")
    return {
        "confirmed": emailer.consult_confirmed_html(
            **common, minutes=60, meet_url="https://meet.google.com/abc-defg-hij",
            manage_url="https://proreadyengineer.com/consult/booking/C-ABCD2345?t=tok", ref="C-ABCD2345",
            total="$111", card="Visa ending 4242", hold_when="Tuesday, June 10, 2031 at 3:00 PM BST (Europe/London)",
            free_cancel_until="Tuesday, June 10, 2031 at 3:00 PM BST (Europe/London)", fee="$22.20", fee_percent=20,
            terms=["Term one.", "Term two."], invite_from="bassam@example.com", expert="Dr. Bassam Abdelnabi",
        ),
        "confirmed_no_link_hold_now": emailer.consult_confirmed_html(
            **common, minutes=30, meet_url="", manage_url="https://proreadyengineer.com/consult/booking/C-1?t=tok",
            ref="C-1", total="$222", card="", hold_when="shortly", free_cancel_until="today at 10:15 AM",
            fee="$44.40", fee_percent=20, terms=[],
        ),
        "cancelled_client": emailer.consult_cancelled_html(
            **common, kind="client", money_line="Nothing was charged.", ref="C-1",
            rebook_url="https://proreadyengineer.com/consult"),
        "cancelled_owner": emailer.consult_cancelled_html(
            **common, kind="owner", money_line="Nothing was charged.", note="Sorry, I am unwell.", ref="C-1"),
        "slot_lost": emailer.consult_cancelled_html(**common, kind="slot_lost", money_line="Nothing was charged.", ref="C-1"),
        "owner_new": emailer.consult_owner_new_html(
            rows=row, topic="Line one\nLine two", meet_url="https://meet.google.com/abc",
            admin_url="https://proreadyengineer.com/admin#consult/booking/1"),
        "owner_new_no_event": emailer.consult_owner_new_html(rows=row, topic="", calendar_problem="No event."),
        "owner_update": emailer.consult_owner_update_html(
            headline="Charge for the call: $111 went through", detail="$111 was charged.", rows=row,
            admin_url="https://proreadyengineer.com/admin#consult/booking/1"),
    }


@pytest.mark.parametrize("name", sorted(_consult_templates()))
def test_the_new_emails_follow_the_house_rules_for_mail_clients(name):
    """The same structural rules test_email_rendering.py holds every other
    template to: no text that inherits its colour from <body>, no CSS
    gradients, and the one shared shell."""
    from test_email_rendering import _UncolouredText

    html = _consult_templates()[name]
    parser = _UncolouredText()
    parser.feed(html)
    assert not parser.offenders, "\n  ".join(parser.offenders)
    assert "gradient" not in html
    assert html.count("<!doctype html>") == 1 and "ProReadyEngineer &middot; Thermal Fluid Sciences" in html
    text = emailer.html_to_text(html)
    assert "Ada" in text and len(text) > 150


def test_ordinary_names_read_exactly_as_typed(client, env):
    r = book(client, START, name="Seán O'Brien & Sons", company="R&D <Combustion>")
    save_card(client, env, r.json()["ref"])
    (mail,) = to(env.outbox, "client@example.com")
    assert "Hi Seán," in mail["text"]
    (alert,) = to(env.outbox, OWNER)
    assert "Seán O'Brien & Sons" in alert["text"] and "R&D <Combustion>" in alert["text"]
    assert "Seán O'Brien & Sons" in alert["subject"]
