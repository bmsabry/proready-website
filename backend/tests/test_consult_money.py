"""Consulting calls: every step that touches money.

  charge_saved_card   the one primitive that takes money off-session; safe
                      to call twice, and a refused card comes back as a
                      result, never as an exception
  the hold            authorized before the meeting (W1b decides when),
                      captured in full or in part, or released
  refunds             bounded by what was charged, safe to repeat
  the admin's buttons Charge / No-show / Do not charge / Cancel / Refund

Throughout, FakeStripe.money_taken() is what cards were really charged: the
assertions that matter compare it with what the booking says.
"""
from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from fastapi import HTTPException

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
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
    iso,
    ny,
    post_webhook,
    save_card,
    slot_starts,
    to,
    world,
)

from app import consult
from app import consult_money as money
from app.consult_models import ConsultBooking, ConsultBookingEvent, ConsultCharge
from app.db import SessionLocal
from app.routes import checkout as checkout_routes

WED = (2031, 6, 11)
START = ny(*WED, 10)              # standard: 60 minutes = $111 at the tests' rate, fee $22.20


def _db(fn):
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


def _charge(b: dict, cents: int, reason: str = "meeting", **kw) -> money.PayResult:
    return _db(lambda db: consult.charge_saved_card(db, db.get(ConsultBooking, b["id"]), cents, reason, **kw))


def _hold(b: dict) -> money.PayResult:
    return _db(lambda db: money.place_hold(db, db.get(ConsultBooking, b["id"])))


def _admin(client, b: dict, action: str, body: dict | None = None):
    return client.post(f"{ADMIN_API}/bookings/{b['id']}/{action}", headers=ADMIN, json=body or {})


def _after_start(env) -> None:
    env.clock.set(START + timedelta(minutes=70))


def _together(n: int, fn) -> list:
    """Run fn() on n threads released at the same instant; their results."""
    go = threading.Barrier(n)
    results: list = []

    def run() -> None:
        go.wait(timeout=10)
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


# -----------------------------------------------------------------------------
# charge_saved_card
# -----------------------------------------------------------------------------

def test_a_charge_takes_the_amount_from_the_saved_card(client, env):
    b = confirmed(client, env, START)
    row = booking_row(b["ref"])
    result = _charge(b, 11_100)
    assert (result.ok, result.status, result.amount_cents, result.fresh) == (True, "succeeded", 11_100, True)

    call = env.stripe.last("PaymentIntent.create")
    assert call["amount"] == 11_100 and call["currency"] == "usd"
    assert call["customer"] == row.stripe_customer_id and call["payment_method"] == row.stripe_payment_method_id
    assert call["off_session"] is True and call["confirm"] is True and call["capture_method"] == "automatic"
    assert call["idempotency_key"] == f"consult:{b['ref']}:charge:meeting:1"
    assert call["metadata"]["booking_ref"] == b["ref"] and call["metadata"]["reason"] == "meeting"

    (charge,) = charges_of(b["id"])
    assert (charge.kind, charge.reason, charge.attempt, charge.status, charge.amount_cents) == (
        "charge", "meeting", 1, "succeeded", 11_100)
    assert charge.stripe_payment_intent_id.startswith("pi_")
    assert booking_row(b["ref"]).charged_cents == 11_100 == env.stripe.money_taken()
    assert events_of(b["id"])[-1] == "charge_succeeded"


def test_charging_twice_for_the_same_thing_takes_the_money_once(client, env):
    b = confirmed(client, env, START)
    first = _charge(b, 11_100)
    second = _charge(b, 11_100)
    third = _charge(b, 11_100, actor="someone-else")
    assert first.ok and second.ok and third.ok
    assert (second.status, second.fresh, second.amount_cents) == ("succeeded", False, 11_100)
    assert second.charge_id == first.charge_id == third.charge_id
    assert env.stripe.count("PaymentIntent.create") == 1       # Stripe was asked once
    assert env.stripe.money_taken() == 11_100
    assert len(charges_of(b["id"])) == 1 and booking_row(b["ref"]).charged_cents == 11_100
    assert events_of(b["id"]).count("charge_succeeded") == 1


def test_a_lost_answer_is_asked_again_with_the_same_key_not_charged_again(client, env):
    """Stripe took the money but the answer never reached us. The ledger row
    stays 'pending'; the retry carries the same idempotency key, and Stripe
    hands back the first payment."""
    b = confirmed(client, env, START)
    env.stripe.card = "network_after"
    lost = _charge(b, 11_100)
    assert (lost.ok, lost.status, lost.code) == (False, "error", "stripe_error")
    assert env.stripe.money_taken() == 11_100                  # the card WAS charged
    (charge,) = charges_of(b["id"])
    assert charge.status == "pending" and booking_row(b["ref"]).charged_cents == 0

    env.stripe.card = "ok"
    again = _charge(b, 11_100)
    assert (again.ok, again.status, again.fresh) == (True, "succeeded", True)
    keys = [kw["idempotency_key"] for name, kw in env.stripe.calls if name == "PaymentIntent.create"]
    assert keys == [f"consult:{b['ref']}:charge:meeting:1"] * 2
    assert env.stripe.replays == 1 and len(env.stripe.payment_intents) == 1
    assert env.stripe.money_taken() == 11_100 == booking_row(b["ref"]).charged_cents
    assert [c.status for c in charges_of(b["id"])] == ["succeeded"]


def test_a_request_that_never_reached_stripe_is_simply_made_again(client, env):
    b = confirmed(client, env, START)
    env.stripe.card = "network_before"
    assert _charge(b, 11_100).status == "error"
    assert env.stripe.money_taken() == 0
    env.stripe.card = "ok"
    assert _charge(b, 11_100).ok is True
    assert env.stripe.money_taken() == 11_100 and len(charges_of(b["id"])) == 1


def test_a_declined_card_is_a_result_not_an_exception(client, env):
    b = confirmed(client, env, START)
    env.stripe.card = "declined"
    result = _charge(b, 11_100)                                 # does not raise
    assert (result.ok, result.status, result.code) == (False, "failed", "card_declined")
    assert result.message == "Your card was declined." and result.fresh is True and result.amount_cents == 0
    (charge,) = charges_of(b["id"])
    assert (charge.status, charge.error_code, charge.decline_code) == ("failed", "card_declined", "insufficient_funds")
    assert charge.stripe_payment_intent_id.startswith("pi_")
    assert env.stripe.money_taken() == 0 and booking_row(b["ref"]).charged_cents == 0
    assert events_of(b["id"])[-1] == "charge_failed"
    # The incomplete payment is cancelled at Stripe so nothing can be confirmed on it later.
    assert env.stripe.payment_intents[charge.stripe_payment_intent_id]["status"] == "canceled"

    # A decline took nothing, so the next call is a new attempt with a new key.
    env.stripe.card = "ok"
    retry = _charge(b, 11_100)
    assert retry.ok is True and env.stripe.money_taken() == 11_100
    rows = charges_of(b["id"])
    assert [(c.attempt, c.status) for c in rows] == [(1, "failed"), (2, "succeeded")]
    assert rows[1].idempotency_key == f"consult:{b['ref']}:charge:meeting:2"


def test_a_card_that_needs_authentication_is_a_result_not_an_exception(client, env):
    b = confirmed(client, env, START)
    env.stripe.card = "auth"
    result = _charge(b, 11_100)                                 # does not raise
    assert (result.ok, result.status, result.code) == (False, "requires_action", "authentication_required")
    (charge,) = charges_of(b["id"])
    assert (charge.status, charge.error_code) == ("requires_action", "authentication_required")
    assert env.stripe.money_taken() == 0 and booking_row(b["ref"]).charged_cents == 0
    assert env.stripe.payment_intents[charge.stripe_payment_intent_id]["status"] == "canceled"


def test_other_failures_never_raise_either(client, env, monkeypatch):
    b = confirmed(client, env, START)
    env.stripe.card = "invalid"                                 # Stripe refuses the request itself (400)
    result = _charge(b, 11_100)
    # not a declined card: parked for the owner (test_consult_review_findings.py, finding 3)
    assert (result.ok, result.status, result.code) == (False, "needs_review", "request_refused")

    def not_configured():
        raise HTTPException(status_code=503, detail="Payments are not configured yet.")

    monkeypatch.setattr(checkout_routes, "_stripe", not_configured)
    result = _charge(b, 11_100, "no_show_fee")
    assert (result.ok, result.status, result.code) == (False, "error", "stripe_unavailable")
    assert [c.reason for c in charges_of(b["id"])] == ["meeting"]   # no ledger row for a call never made


def test_a_booking_without_a_saved_card_cannot_be_charged(client, env):
    data = book(client, START).json()
    row = booking_row(data["ref"])
    result = _charge({"id": row.id}, 11_100)
    assert (result.ok, result.code) == (False, "no_card")
    assert env.stripe.count("PaymentIntent.create") == 0 and charges_of(row.id) == []
    assert _charge({"id": row.id}, 0).status == "noop"


def test_different_reasons_are_different_charges(client, env):
    b = confirmed(client, env, START)
    assert _charge(b, 2_220, "late_cancel_fee").ok and _charge(b, 2_220, "late_cancel_fee").ok
    assert _charge(b, 2_220, "no_show_fee").ok
    assert env.stripe.money_taken() == 4_440 == booking_row(b["ref"]).charged_cents
    assert [(c.reason, c.status) for c in charges_of(b["id"])] == [
        ("late_cancel_fee", "succeeded"), ("no_show_fee", "succeeded")]


def test_a_payment_still_processing_is_looked_up_not_made_again(client, env):
    b = confirmed(client, env, START)
    env.stripe.card = "processing"
    first = _charge(b, 11_100)
    assert (first.ok, first.status, first.code) == (False, "error", "processing")
    (charge,) = charges_of(b["id"])
    assert charge.status == "pending" and charge.stripe_payment_intent_id
    pi = env.stripe.payment_intents[charge.stripe_payment_intent_id]
    pi["status"], pi["amount_received"] = "succeeded", 11_100   # it settles at Stripe
    second = _charge(b, 11_100)
    assert second.ok is True and env.stripe.count("PaymentIntent.create") == 1
    assert env.stripe.count("PaymentIntent.retrieve") == 1
    assert booking_row(b["ref"]).charged_cents == 11_100


def test_an_unanswered_charge_that_is_a_day_old_is_parked_for_a_person(client, env):
    """Stripe forgets an idempotency key after about a day. Asking again
    after that could charge twice, so it is not asked."""
    b = confirmed(client, env, START)
    env.stripe.card = "network_after"
    _charge(b, 11_100)
    env.stripe.card = "ok"
    env.clock.advance(hours=21)
    result = _charge(b, 11_100)
    assert (result.ok, result.status) == (False, "needs_review")
    assert env.stripe.count("PaymentIntent.create") == 1
    assert charges_of(b["id"])[0].status == "needs_review"
    assert "charge_needs_review" in events_of(b["id"])
    assert _charge(b, 11_100).status == "needs_review"           # and it stays parked
    assert env.stripe.count("PaymentIntent.create") == 1


def test_a_different_amount_cannot_ride_on_an_unanswered_charge(client, env):
    b = confirmed(client, env, START)
    env.stripe.card = "network_after"
    _charge(b, 11_100)
    env.stripe.card = "ok"
    result = _charge(b, 5_550)
    assert (result.ok, result.code) == (False, "in_progress")
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 11_100


def test_two_calls_writing_the_same_attempt_share_one_key(client, env, monkeypatch):
    """The other call's ledger row lands between this call's look at the
    ledger and its own insert. The unique key refuses the second row; this
    call then adopts the first one's key instead of failing or paying twice."""
    b = confirmed(client, env, START)
    real_ledger = money.ledger
    planted: list[int] = []

    def ledger_then_rival(db, booking_id):
        rows = real_ledger(db, booking_id)
        if not planted:
            planted.append(1)
            other = SessionLocal()
            row = booking_row(b["ref"])
            other.add(ConsultCharge(
                booking_id=b["id"], kind="charge", reason="meeting", attempt=1,
                idempotency_key=f"consult:{b['ref']}:charge:meeting:1", amount_cents=11_100,
                status="pending", payment_method_id=row.stripe_payment_method_id, actor="rival",
                created_at=NOW,
            ))
            other.commit()
            other.close()
        return rows

    monkeypatch.setattr(money, "ledger", ledger_then_rival)
    result = _charge(b, 11_100)                                  # does not raise
    assert result.ok is True and result.status == "succeeded"
    rows = charges_of(b["id"])
    assert len(rows) == 1 and rows[0].actor == "rival" and rows[0].status == "succeeded"
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 11_100


def test_four_charges_at_the_same_instant_take_the_money_once(client, env):
    b = confirmed(client, env, START)
    results = _together(4, lambda: _charge(b, 11_100))
    assert all(isinstance(r, money.PayResult) and r.ok for r in results), results
    assert len(env.stripe.payment_intents) == 1 and env.stripe.money_taken() == 11_100
    assert booking_row(b["ref"]).charged_cents == 11_100
    assert sum(1 for r in results if r.fresh) == 1               # one caller sends the emails
    assert events_of(b["id"]).count("charge_succeeded") == 1


def test_a_late_cancellation_sent_four_times_at_once_charges_and_emails_once(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=2))
    env.outbox.clear()

    def cancel():
        return _db(lambda db: consult.cancel_by_client(db, db.get(ConsultBooking, b["id"])).status)

    assert _together(4, cancel) == ["cancelled"] * 4
    assert env.stripe.money_taken() == 2_220 and len(env.stripe.payment_intents) == 1
    assert booking_row(b["ref"]).charged_cents == 2_220
    assert events_of(b["id"]).count("cancelled") == 1 and events_of(b["id"]).count("charge_succeeded") == 1
    assert len(to(env.outbox, "client@example.com")) == 1 and len(to(env.outbox, OWNER)) == 1
    assert env.google.events == {}


def test_charge_pressed_four_times_at_once_charges_and_emails_once(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    env.outbox.clear()

    def press():
        return _db(lambda db: consult.settle(db, db.get(ConsultBooking, b["id"]), "charge", actor="admin@example.com")[1].ok)

    assert _together(4, press) == [True] * 4
    assert env.stripe.money_taken() == 11_100 and len(env.stripe.payment_intents) == 1
    row = booking_row(b["ref"])
    assert (row.status, row.charged_cents, row.charge_state) == ("completed", 11_100, "paid")
    assert events_of(b["id"]).count("outcome_decided") == 1 and events_of(b["id"]).count("charge_succeeded") == 1
    assert len(to(env.outbox, OWNER)) == 1


def test_a_hold_placed_four_times_at_once_is_one_hold(client, env):
    b = confirmed(client, env, START)
    results = _together(4, lambda: _hold(b))
    assert all(isinstance(r, money.PayResult) and r.ok for r in results), results
    assert len(env.stripe.payment_intents) == 1 and env.stripe.authorized() == 11_100
    assert events_of(b["id"]).count("hold_placed") == 1 and sum(1 for r in results if r.fresh) == 1


# -----------------------------------------------------------------------------
# The hold
# -----------------------------------------------------------------------------

def test_a_hold_authorizes_the_booked_amount_without_taking_it(client, env):
    b = confirmed(client, env, START)
    result = _hold(b)
    assert (result.ok, result.status, result.amount_cents) == (True, "authorized", 11_100)
    call = env.stripe.last("PaymentIntent.create")
    assert call["capture_method"] == "manual" and call["amount"] == 11_100
    assert call["idempotency_key"] == f"consult:{b['ref']}:hold:hold:1"
    row = booking_row(b["ref"])
    assert (row.hold_state, row.hold_cents, row.charged_cents) == ("authorized", 11_100, 0)
    assert row.hold_payment_intent_id.startswith("pi_") and row.hold_placed_at is not None
    assert env.stripe.authorized() == 11_100 and env.stripe.money_taken() == 0
    # asked again (the cron tick runs every few minutes): still one hold
    assert _hold(b).ok is True and env.stripe.count("PaymentIntent.create") == 1
    assert events_of(b["id"]).count("hold_placed") == 1
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    assert a["payment_state"] == "hold_placed" and a["hold_state"] == "authorized" and a["charged_cents"] is None


def test_a_refused_hold_is_recorded_and_can_be_tried_again_on_a_new_card(client, env):
    b = confirmed(client, env, START)
    env.stripe.card = "auth"
    result = _hold(b)
    assert (result.ok, result.status) == (False, "requires_action")
    row = booking_row(b["ref"])
    assert row.hold_state == "requires_action" and row.hold_failed_at is not None and row.hold_error
    assert row.status == "confirmed"                             # what happens next is W1b's decision
    assert "hold_failed" in events_of(b["id"])
    env.stripe.card = "ok"
    client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    save_card(client, env, b["ref"], last4="1881")
    assert _hold(b).ok is True
    row = booking_row(b["ref"])
    assert row.hold_state == "authorized" and env.stripe.authorized() == 11_100
    holds = [c for c in charges_of(b["id"]) if c.kind == "hold"]
    assert [(c.attempt, c.status) for c in holds] == [(1, "requires_action"), (2, "authorized")]
    assert holds[1].payment_method_id != holds[0].payment_method_id      # the new card


def test_a_hold_is_only_for_a_confirmed_booking_with_no_outcome(client, env):
    data = book(client, START).json()
    assert _hold({"id": booking_row(data["ref"]).id}).code == "not_open"
    b = confirmed(client, env, ny(*WED, 14), email="x@example.com", ip="203.0.113.3")
    _after_start(env)
    env.clock.set(ny(*WED, 15, 30))
    assert _admin(client, b, "waive").status_code == 200
    assert _hold(b).code == "not_open" and env.stripe.count("PaymentIntent.create") == 0


def test_charging_in_full_captures_the_hold(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    r = _admin(client, b, "charge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["charged_cents"] == 11_100
    assert body["payment_state"] == "paid" and body["hold_state"] == "captured"
    assert body["action"]["ok"] is True and body["action"]["amount_cents"] == 11_100
    assert env.stripe.count("PaymentIntent.create") == 1         # only the hold: no second payment
    capture = env.stripe.last("PaymentIntent.capture")
    assert capture["amount_to_capture"] == 11_100
    assert env.stripe.money_taken() == 11_100 and env.stripe.authorized() == 0
    (hold,) = charges_of(b["id"])
    assert (hold.kind, hold.status, hold.captured_cents, hold.capture_reason) == ("hold", "captured", 11_100, "meeting")


def test_a_no_show_captures_the_fee_and_lets_the_rest_of_the_hold_go(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    r = _admin(client, b, "no-show")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_show" and body["charged_cents"] == 2_220 and body["payment_state"] == "paid"
    assert env.stripe.last("PaymentIntent.capture")["amount_to_capture"] == 2_220
    assert env.stripe.money_taken() == 2_220                     # 20%, not the $111 that was held
    assert env.stripe.authorized() == 0 and env.stripe.count("PaymentIntent.create") == 1


def test_not_charging_releases_the_hold(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    r = _admin(client, b, "waive")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["charged_cents"] is None
    assert body["payment_state"] == "not_charged" and body["hold_state"] == "released"
    assert env.stripe.count("PaymentIntent.cancel") == 1 and env.stripe.count("PaymentIntent.capture") == 0
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0
    assert "hold_released" in events_of(b["id"])


def test_a_late_cancellation_takes_its_fee_from_the_hold(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=23))
    _hold(b)
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    assert r.status_code == 200 and r.json()["charged_cents"] == 2_220
    assert env.stripe.last("PaymentIntent.capture")["amount_to_capture"] == 2_220
    assert env.stripe.count("PaymentIntent.create") == 1         # no charge beside the hold
    assert env.stripe.money_taken() == 2_220 and env.stripe.authorized() == 0


def test_a_free_cancellation_and_an_owner_cancellation_release_the_hold(client, env):
    b = confirmed(client, env, START)
    _hold(b)                                                     # placed early, for the test
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    assert r.json()["charged_cents"] is None
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0

    c = confirmed(client, env, ny(*WED, 14), email="y@example.com", ip="203.0.113.4")
    env.clock.set(ny(*WED, 13))                                  # one hour before: far inside 24 h
    _hold(c)
    r = _admin(client, c, "cancel", {"note": "I am unwell today; sorry."})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["charged_cents"] is None
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0
    assert booking_row(c["ref"]).hold_state == "released"


def test_a_hold_that_lapsed_at_stripe_falls_back_to_a_direct_charge(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    env.stripe.capture = "expired"                               # the authorization is gone
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100
    assert r.json()["hold_state"] == "released"
    assert env.stripe.money_taken() == 11_100
    assert [(c.kind, c.status) for c in charges_of(b["id"])] == [("hold", "released"), ("charge", "succeeded")]
    assert "hold_lost" in events_of(b["id"])


def test_a_capture_whose_answer_was_lost_is_finished_not_repeated(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    env.stripe.capture = "network_after"
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100    # read back from Stripe at once
    assert env.stripe.money_taken() == 11_100 and env.stripe.count("PaymentIntent.capture") == 1
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    assert env.stripe.money_taken() == 11_100 and env.stripe.count("PaymentIntent.capture") == 1


def test_a_capture_that_could_not_be_made_leaves_the_hold_and_can_be_tried_again(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    env.stripe.capture = "refused"
    r = _admin(client, b, "charge")
    body = r.json()
    assert r.status_code == 200 and body["action"]["ok"] is False and body["charged_cents"] is None
    assert body["payment_state"] == "payment_pending" and body["hold_state"] == "authorized"
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 11_100
    env.stripe.capture = "ok"
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    assert env.stripe.money_taken() == 11_100


# -----------------------------------------------------------------------------
# The admin's buttons
# -----------------------------------------------------------------------------

def test_a_meeting_that_has_not_started_cannot_be_settled(client, env):
    b = confirmed(client, env, START)
    for action in ("charge", "no-show", "waive"):
        r = _admin(client, b, action)
        assert r.status_code == 409 and "not started yet" in r.json()["detail"], action
    assert booking_row(b["ref"]).status == "confirmed" and env.stripe.money_taken() == 0
    assert _admin(client, {"id": 999_999}, "charge").status_code == 404


def test_charge_charges_the_booked_amount_and_completes_the_booking(client, env):
    b = confirmed(client, env, START, 90)                        # $166.50
    env.outbox.clear()
    env.clock.set(START + timedelta(minutes=95))
    r = _admin(client, b, "charge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["charged_cents"] == 16_650 and body["refunded_cents"] == 0
    assert body["payment_state"] == "paid"
    assert body["action"] == {"ok": True, "status": "succeeded", "amount_cents": 16_650, "code": "", "message": ""}
    row = booking_row(b["ref"])
    assert (row.settlement, row.billed_minutes, row.amount_due_cents, row.charge_state) == ("charged", 90, 16_650, "paid")
    assert row.settled_by == "admin@example.com"
    assert env.stripe.money_taken() == 16_650
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] Charge for the call: $166.50 went through: Casey Client"
    # the client's page
    v = client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()
    assert v["status"] == "completed" and v["charged_cents"] == 16_650 and v["can_cancel"] is False


def test_pressing_charge_twice_charges_once(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    env.outbox.clear()
    first, second = _admin(client, b, "charge"), _admin(client, b, "charge")
    assert first.status_code == second.status_code == 200
    assert second.json()["charged_cents"] == 11_100 and second.json()["action"]["status"] == "noop"
    assert env.stripe.money_taken() == 11_100 and env.stripe.count("PaymentIntent.create") == 1
    assert len(to(env.outbox, OWNER)) == 1


def test_charge_for_fewer_minutes_bills_in_thirty_minute_steps(client, env):
    b = confirmed(client, env, START, 120)                       # $222 booked
    env.clock.set(START + timedelta(minutes=130))
    r = _admin(client, b, "charge", {"minutes": 90})
    assert r.status_code == 200 and r.json()["charged_cents"] == 16_650      # rate * minutes / 60
    assert booking_row(b["ref"]).billed_minutes == 90 and env.stripe.money_taken() == 16_650


@pytest.mark.parametrize("minutes", [45, 90, 150])
def test_charge_never_bills_more_than_was_booked_or_off_the_grid(client, env, minutes):
    b = confirmed(client, env, START, 60)
    _after_start(env)
    r = _admin(client, b, "charge", {"minutes": minutes})
    assert r.status_code == 409 and "multiple of 30" in r.json()["detail"] and "60 booked" in r.json()["detail"]
    assert booking_row(b["ref"]).status == "confirmed" and env.stripe.money_taken() == 0


def test_no_show_charges_the_fee_only(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    r = _admin(client, b, "no-show")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "no_show" and r.json()["charged_cents"] == 2_220
    assert env.stripe.last("PaymentIntent.create")["amount"] == 2_220 and env.stripe.money_taken() == 2_220
    assert charges_of(b["id"])[0].reason == "no_show_fee"
    v = client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()
    assert v["status"] == "no_show" and v["charged_cents"] == 2_220


def test_do_not_charge_charges_nothing(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    env.outbox.clear()
    r = _admin(client, b, "waive")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["charged_cents"] is None and body["payment_state"] == "not_charged"
    assert env.stripe.calls == [c for c in env.stripe.calls if c[0] != "PaymentIntent.create"]
    assert env.stripe.money_taken() == 0 and charges_of(b["id"]) == []
    assert "nothing to charge" in to(env.outbox, OWNER)[0]["subject"]


def test_a_declined_charge_is_reported_and_collected_when_the_card_is_replaced(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    env.outbox.clear()
    env.stripe.card = "declined"
    r = _admin(client, b, "charge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["charged_cents"] is None
    assert body["payment_state"] == "payment_failed"
    assert body["action"]["ok"] is False and body["action"]["code"] == "card_declined"
    assert body["action"]["message"] == "Your card was declined."
    assert "FAILED" in to(env.outbox, OWNER)[0]["subject"]
    v = client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()
    assert v["charged_cents"] is None and v["card_problem"] is True and v["can_replace_card"] is True

    # Pressing Charge again is a new attempt (still declined: still nothing taken).
    assert _admin(client, b, "charge").json()["action"]["ok"] is False
    assert env.stripe.money_taken() == 0

    env.stripe.card = "ok"
    client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    save_card(client, env, b["ref"], last4="9995")
    row = booking_row(b["ref"])
    assert (row.charge_state, row.charged_cents) == ("paid", 11_100) and env.stripe.money_taken() == 11_100
    assert [c.status for c in charges_of(b["id"])] == ["failed", "failed", "succeeded"]


def test_an_outcome_can_change_only_while_no_money_was_taken(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    env.stripe.card = "declined"
    assert _admin(client, b, "charge").json()["payment_state"] == "payment_failed"
    env.stripe.card = "ok"
    r = _admin(client, b, "no-show")                             # nothing was taken: he may change his mind
    assert r.status_code == 200 and r.json()["status"] == "no_show" and r.json()["charged_cents"] == 2_220
    for action in ("charge", "waive"):
        r = _admin(client, b, action)                            # now money was taken
        assert r.status_code == 409 and "Use a refund" in r.json()["detail"], action
    assert env.stripe.money_taken() == 2_220 and booking_row(b["ref"]).status == "no_show"


def test_the_owner_cancels_at_no_charge_even_at_the_last_minute(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(minutes=10))
    env.outbox.clear()
    r = _admin(client, b, "cancel", {"note": 'Power cut here <b>sorry</b>'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled" and body["charged_cents"] is None
    row = booking_row(b["ref"])
    assert (row.cancelled_by, row.cancel_fee_cents, row.settlement) == ("owner", 0, "")
    assert env.stripe.money_taken() == 0 and env.google.events == {}
    (mail,) = to(env.outbox, "client@example.com")
    assert "is cancelled" in mail["subject"] and "we have had to cancel" in mail["html"]
    assert "Nothing was charged" in mail["html"]
    assert "Power cut here &lt;b&gt;sorry&lt;/b&gt;" in mail["html"] and "<b>sorry</b>" not in mail["html"]
    # again: nothing more happens; a closed booking cannot be cancelled
    assert _admin(client, b, "cancel").status_code == 200 and len(to(env.outbox, "client@example.com")) == 1
    c = confirmed(client, env, ny(2031, 6, 12, 10), email="z@example.com", ip="203.0.113.6")
    env.clock.set(ny(2031, 6, 12, 11, 30))
    _admin(client, c, "charge")
    r = _admin(client, c, "cancel")
    assert r.status_code == 409 and "refund" in r.json()["detail"]


def test_the_owner_can_cancel_a_booking_that_is_still_waiting_for_its_card(client, env):
    data = book(client, START).json()
    row = booking_row(data["ref"])
    r = _admin(client, {"id": row.id}, "cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert iso(START) in slot_starts(client)


def test_a_late_fee_the_card_refused_can_be_charged_again_or_waived(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=1))
    env.stripe.card = "declined"
    client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    assert a["status"] == "cancelled" and a["payment_state"] == "payment_failed" and a["charged_cents"] is None
    assert a["actions"]["can_charge"] is True and a["actions"]["can_waive"] is True and a["actions"]["can_no_show"] is False
    assert _admin(client, b, "no-show").status_code == 409
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["action"]["ok"] is False        # still declined
    env.stripe.card = "ok"
    r = _admin(client, b, "charge")
    assert r.json()["charged_cents"] == 2_220 and r.json()["status"] == "cancelled"
    assert env.stripe.money_taken() == 2_220
    assert _admin(client, b, "waive").status_code == 409         # it was paid: a refund is the way back

    c = confirmed(client, env, ny(2031, 6, 12, 10), email="w@example.com", ip="203.0.113.9")
    env.clock.set(ny(2031, 6, 12, 9))
    env.stripe.card = "declined"
    client.post(f"{PUBLIC}/booking/{c['ref']}/cancel", json={"t": c["token"]})
    r = _admin(client, c, "waive")
    assert r.status_code == 200 and r.json()["payment_state"] == "not_charged"
    assert booking_row(c["ref"]).amount_due_cents == 0 and env.stripe.money_taken() == 2_220


# -----------------------------------------------------------------------------
# Refunds
# -----------------------------------------------------------------------------

def _charged(client, env) -> dict:
    b = confirmed(client, env, START)
    _after_start(env)
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    return b


def test_a_refund_sends_money_back_against_the_payment(client, env):
    b = _charged(client, env)
    env.outbox.clear()
    r = _admin(client, b, "refund", {"cents": 4_000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["charged_cents"] == 11_100 and body["refunded_cents"] == 4_000
    assert body["payment_state"] == "partly_refunded" and body["actions"]["refundable_cents"] == 7_100
    assert body["action"]["ok"] is True and body["action"]["amount_cents"] == 4_000
    call = env.stripe.last("Refund.create")
    assert call["amount"] == 4_000 and call["payment_intent"] == charges_of(b["id"])[0].stripe_payment_intent_id
    assert call["idempotency_key"].startswith(f"consult:{b['ref']}:refund:1:")
    assert env.stripe.money_returned() == 4_000
    assert "Refund: $40 went through" in to(env.outbox, OWNER)[0]["subject"]
    # the client's page shows what was kept
    v = client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()
    assert v["charged_cents"] == 7_100


def test_a_refund_cannot_exceed_what_was_charged(client, env):
    b = _charged(client, env)
    r = _admin(client, b, "refund", {"cents": 11_101})
    assert r.status_code == 409 and "At most $111.00" in r.json()["detail"]
    assert _admin(client, b, "refund", {"cents": 0}).status_code == 422
    assert _admin(client, b, "refund", {"cents": -5}).status_code == 422
    env.clock.advance(minutes=5)
    assert _admin(client, b, "refund", {"cents": 11_100}).json()["payment_state"] == "refunded"
    env.clock.advance(minutes=5)
    r = _admin(client, b, "refund", {"cents": 1})
    assert r.status_code == 409 and "At most $0.00" in r.json()["detail"]
    assert env.stripe.money_returned() == 11_100
    # nothing charged, nothing to refund
    c = confirmed(client, env, ny(2031, 6, 13, 10), email="n@example.com", ip="203.0.113.7")
    assert _admin(client, c, "refund", {"cents": 100}).status_code == 409


def test_the_same_refund_pressed_twice_is_one_refund(client, env):
    b = _charged(client, env)
    env.outbox.clear()
    first = _admin(client, b, "refund", {"cents": 2_500})
    second = _admin(client, b, "refund", {"cents": 2_500})       # the double click, or a retried request
    assert first.status_code == second.status_code == 200
    assert second.json()["refunded_cents"] == 2_500 and second.json()["action"]["status"] == "noop"
    assert env.stripe.money_returned() == 2_500 and env.stripe.count("Refund.create") == 1
    assert len(to(env.outbox, OWNER)) == 1
    # Two minutes later the same amount is a second, deliberate refund.
    env.clock.advance(seconds=121)
    third = _admin(client, b, "refund", {"cents": 2_500})
    assert third.json()["refunded_cents"] == 5_000 and env.stripe.money_returned() == 5_000


def test_a_refund_whose_answer_was_lost_is_finished_by_asking_stripe(client, env):
    b = _charged(client, env)
    env.stripe.refund_mode = "network_after"
    r = _admin(client, b, "refund", {"cents": 7_500})
    assert r.status_code == 200 and r.json()["action"]["ok"] is False and r.json()["refunded_cents"] == 0
    assert env.stripe.money_returned() == 7_500                  # it did go back
    env.stripe.refund_mode = "ok"
    r = _admin(client, b, "refund", {"cents": 7_500})
    assert r.json()["refunded_cents"] == 7_500 and r.json()["action"]["ok"] is True
    # Stripe was asked what it has for the payment, found the refund, and nothing was sent again
    assert env.stripe.count("Refund.create") == 1 and env.stripe.count("Refund.list") == 1
    assert env.stripe.money_returned() == 7_500 and len(env.stripe.refunds) == 1


def test_a_refund_that_never_reached_stripe_is_sent_again_with_the_same_key(client, env):
    b = _charged(client, env)
    env.stripe.refund_mode = "network_before"
    r = _admin(client, b, "refund", {"cents": 7_500})
    assert r.json()["action"]["ok"] is False and env.stripe.money_returned() == 0
    env.stripe.refund_mode = "ok"
    r = _admin(client, b, "refund", {"cents": 7_500})
    assert r.json()["refunded_cents"] == 7_500 and r.json()["action"]["ok"] is True
    keys = [kw["idempotency_key"] for name, kw in env.stripe.calls if name == "Refund.create"]
    assert len(keys) == 2 and keys[0] == keys[1]                 # Stripe had none: the same request, the same key
    assert env.stripe.money_returned() == 7_500 and len(env.stripe.refunds) == 1


def test_a_refund_against_a_captured_hold(client, env):
    b = confirmed(client, env, START)
    _hold(b)
    _after_start(env)
    _admin(client, b, "no-show")                                 # $22.20 captured from the hold
    r = _admin(client, b, "refund", {"cents": 2_220})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 2_220 and r.json()["payment_state"] == "refunded"
    assert env.stripe.money_taken() == 2_220 and env.stripe.money_returned() == 2_220


def test_a_refund_made_in_the_stripe_dashboard_is_seen(client, env):
    b = _charged(client, env)
    pi = charges_of(b["id"])[0].stripe_payment_intent_id
    event = {"type": "charge.refunded", "data": {"object": {
        "id": "ch_1", "payment_intent": pi, "amount": 11_100, "amount_refunded": 4_100, "refunded": False,
    }}}
    for _ in range(2):                                           # delivered twice: counted once
        assert post_webhook(client, env, event).status_code == 200
    row = booking_row(b["ref"])
    assert (row.charged_cents, row.refunded_cents) == (11_100, 4_100)
    assert events_of(b["id"]).count("refund_seen_at_stripe") == 1
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    assert a["refunded_cents"] == 4_100 and a["actions"]["refundable_cents"] == 7_000
    # and the admin cannot refund the same money a second time
    env.clock.advance(minutes=5)
    assert _admin(client, b, "refund", {"cents": 7_001}).status_code == 409
    assert _admin(client, b, "refund", {"cents": 7_000}).json()["payment_state"] == "refunded"
    # A refund on a payment that is not ours goes on to the course branch as before.
    other = {"type": "charge.refunded", "data": {"object": {
        "id": "ch_2", "payment_intent": "pi_not_ours", "amount": 100, "amount_refunded": 100, "refunded": True,
    }}}
    assert post_webhook(client, env, other).status_code == 200


def _stripe_says_refunded(client, env, b: dict, total: int):
    pi = [c for c in charges_of(b["id"]) if c.kind in ("charge", "hold")][0].stripe_payment_intent_id
    return post_webhook(client, env, {"type": "charge.refunded", "data": {"object": {
        "id": "ch_1", "payment_intent": pi, "amount": 11_100, "amount_refunded": total, "refunded": total >= 11_100,
    }}})


def test_stripes_notice_of_our_own_refund_is_not_counted_as_a_second_refund(client, env):
    """After a refund from the admin panel Stripe sends charge.refunded with
    its running total. That total is our refund, not another one."""
    b = _charged(client, env)
    _admin(client, b, "refund", {"cents": 4_000})
    assert _stripe_says_refunded(client, env, b, 4_000).status_code == 200
    row = booking_row(b["ref"])
    assert row.refunded_cents == 4_000 and "refund_seen_at_stripe" not in events_of(b["id"])
    # A dashboard refund on top of it: the total is now ours plus theirs.
    assert _stripe_says_refunded(client, env, b, 6_500).status_code == 200
    assert booking_row(b["ref"]).refunded_cents == 6_500
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    seen = [e for e in a["events"] if e["kind"] == "refund_seen_at_stripe"]
    assert len(seen) == 1 and seen[0]["cents"] == 2_500 and a["actions"]["refundable_cents"] == 4_600
    # An old notice arriving late changes nothing.
    assert _stripe_says_refunded(client, env, b, 4_000).status_code == 200
    assert booking_row(b["ref"]).refunded_cents == 6_500


def test_stripes_notice_arriving_before_our_own_refund_is_settled_is_not_double_counted(client, env):
    """Our refund went through at Stripe, the answer was lost, and Stripe's
    webhook about it arrives first. When the refund is then finished, the
    money is counted once."""
    b = _charged(client, env)
    env.stripe.refund_mode = "network_after"
    _admin(client, b, "refund", {"cents": 3_330})                # in flight: our row is 'pending'
    assert _stripe_says_refunded(client, env, b, 3_330).status_code == 200
    assert "refund_seen_at_stripe" not in events_of(b["id"])
    env.stripe.refund_mode = "ok"
    r = _admin(client, b, "refund", {"cents": 3_330})            # finished with the same key
    assert r.json()["refunded_cents"] == 3_330 and r.json()["actions"]["refundable_cents"] == 7_770
    assert env.stripe.money_returned() == 3_330


# -----------------------------------------------------------------------------
# The admin's list and the booking object
# -----------------------------------------------------------------------------

def test_the_booking_object_has_the_fields_the_admin_screen_reads(client, env):
    b = confirmed(client, env, START, 90, ip="203.0.113.44")
    r = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN)
    assert r.status_code == 200
    a = r.json()
    row = booking_row(b["ref"])
    expected = {
        "id": b["id"], "ref": b["ref"], "status": "confirmed", "start": iso(START), "minutes": 90,
        "timezone": "Europe/London", "full_name": "Casey Client", "email": "client@example.com",
        "company": "Example Turbines", "phone": "+1 555 0100",
        "topic": "Lean blowout margin on a DLE combustor at part load.",
        "tier": "standard", "tier_label": "Standard", "rate_cents_per_hour": 11_100,
        "total_cents": 16_650, "fee_percent": 20, "fee_cents": 3_330,
        "payment_state": "card_saved", "hold_state": "", "charged_cents": None, "refunded_cents": 0,
        "disputed_cents": 0, "dispute_lost_cents": 0, "dispute_state": "", "kept_cents": 0,
        "needs_review": [],
        "card_brand": "visa", "card_last4": "4242", "meet_url": row.meet_url,
        "settle_due_at": iso(START + timedelta(minutes=90) + timedelta(hours=2)),
        "created_at": iso(NOW),
    }
    assert {k: a[k] for k in expected} == expected
    assert a["attendance"] == {
        "state": "unknown", "host_joined": None, "others_joined": None, "participants": [],
        "checked_at": None, "note": "",
    }
    assert set(a["consent"]) >= {"terms_version", "terms_hash", "at", "ip", "user_agent"}
    assert a["consent"]["ip"] == "203.0.113.44" and a["consent"]["at"] == iso(NOW)
    assert [e["kind"] for e in a["events"]] == ["created", "card_saved", "confirmed", "calendar_event_created"]
    assert all(set(e) == {"at", "kind", "detail", "actor", "cents"} for e in a["events"])
    assert a["events"][0]["cents"] == 16_650 and a["events"][0]["actor"] == "client"
    assert a["events"][1]["detail"] == "visa ending 4242" and a["events"][1]["actor"] == "stripe"
    assert a["actions"] == {
        "can_charge": False, "can_no_show": False, "can_waive": False, "can_cancel": True,
        "can_refund": False, "refundable_cents": 0, "can_review": False,
    }
    assert a["charges"] == []
    # nothing secret rides along
    flat = str(a)
    assert b["token"] not in flat and "manage_token" not in flat and "pm_test" not in flat


def test_attendance_recorded_by_the_settlement_job_reads_through(client, env):
    b = confirmed(client, env, START)

    def record(db):
        row = db.get(ConsultBooking, b["id"])
        row.attendance = {"host_joined": True, "others_joined": 1, "participants": ["Casey Client"], "note": ""}
        row.attendance_state, row.attendance_checked_at = "both", START + timedelta(hours=1)
        db.commit()

    _db(record)
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    assert a["attendance"] == {
        "state": "both", "host_joined": True, "others_joined": 1, "participants": ["Casey Client"],
        "checked_at": iso(START + timedelta(hours=1)), "note": "",
    }


def test_the_list_filters_by_status_and_searches(client, env):
    one = confirmed(client, env, START, email="ada@turbines.example", name="Ada Lovelace", ip="203.0.113.1")
    two = book(client, ny(*WED, 14), email="grace@navy.example", name="Grace Hopper", ip="203.0.113.2",
               company="Naval Combustion", topic="Thermoacoustic instability in an annular combustor").json()
    three = confirmed(client, env, ny(2031, 6, 12, 10), email="kat@nasa.example", name="Katherine Johnson", ip="203.0.113.3")
    client.post(f"{PUBLIC}/booking/{three['ref']}/cancel", json={"t": three["token"]})

    def refs(**params) -> list[str]:
        r = client.get(f"{ADMIN_API}/bookings", headers=ADMIN, params=params)
        assert r.status_code == 200, r.text
        assert set(r.json()) == {"bookings"}
        return [x["ref"] for x in r.json()["bookings"]]

    assert refs() == [three["ref"], two["ref"], one["ref"]]      # latest start first
    assert refs(status="confirmed") == [one["ref"]]
    assert refs(status="pending_card") == [two["ref"]]
    assert refs(status="cancelled") == [three["ref"]]
    assert refs(status="completed") == []
    assert refs(q="hopper") == [two["ref"]] and refs(q="NAVY.example") == [two["ref"]]
    assert refs(q="naval") == [two["ref"]] and refs(q="thermoacoustic") == [two["ref"]]
    assert refs(q=one["ref"].lower()) == [one["ref"]]
    assert refs(q="nobody-by-that-name") == []
    assert refs(status="confirmed", q="ada") == [one["ref"]] and refs(status="cancelled", q="ada") == []
    # a hold that ran out shows, and filters, as expired
    env.clock.advance(minutes=21)
    assert refs(status="expired") == [two["ref"]] and refs(status="pending_card") == []
    assert client.get(f"{ADMIN_API}/bookings/999999", headers=ADMIN).status_code == 404


def test_the_timeline_tells_the_whole_story_in_order(client, env):
    b = confirmed(client, env, START)
    _after_start(env)
    env.stripe.card = "declined"
    _admin(client, b, "charge")
    env.stripe.card = "ok"
    _admin(client, b, "charge")
    env.clock.advance(minutes=5)
    _admin(client, b, "refund", {"cents": 5_000, "note": "Goodwill: the call started late."})
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    assert [e["kind"] for e in a["events"]] == [
        "created", "card_saved", "confirmed", "calendar_event_created",
        "outcome_decided", "charge_failed", "charge_succeeded", "refunded",
    ]
    by_kind = {e["kind"]: e for e in a["events"]}
    assert by_kind["outcome_decided"]["actor"] == "admin@example.com" and by_kind["outcome_decided"]["cents"] == 11_100
    assert "Your card was declined" in by_kind["charge_failed"]["detail"]
    assert by_kind["refunded"]["cents"] == 5_000 and by_kind["refunded"]["detail"] == "Goodwill: the call started late."
    assert [e["at"] for e in a["events"]] == sorted(e["at"] for e in a["events"])
    assert [(c["kind"], c["reason"], c["attempt"], c["status"], c["amount_cents"]) for c in a["charges"]] == [
        ("charge", "meeting", 1, "failed", 11_100), ("charge", "meeting", 2, "succeeded", 11_100),
        ("refund", "refund", 1, "succeeded", 5_000),
    ]
    # Timeline rows are only ever added: the count never goes down.
    count = _db(lambda db: db.query(ConsultBookingEvent).filter_by(booking_id=b["id"]).count())
    assert count == 8


def test_what_the_booking_says_always_equals_what_the_cards_were_charged(client, env):
    """Across a run of everything at once, the ledger and Stripe agree."""
    paid = confirmed(client, env, START, 120, email="a@example.com", ip="203.0.113.1")           # $222
    late = confirmed(client, env, ny(*WED, 14), 60, email="b@example.com", ip="203.0.113.2")     # $111
    gone = confirmed(client, env, ny(*WED, 16), 30, email="c@example.com", ip="203.0.113.3")     # $55.50
    free = confirmed(client, env, ny(2031, 6, 12, 10), 60, email="d@example.com", ip="203.0.113.4")
    client.post(f"{PUBLIC}/booking/{free['ref']}/cancel", json={"t": free["token"]})             # free
    env.clock.set(ny(*WED, 9))
    for b in (paid, late, gone):
        assert _hold(b).ok
    client.post(f"{PUBLIC}/booking/{late['ref']}/cancel", json={"t": late["token"]})             # fee $22.20
    env.clock.set(ny(*WED, 17))
    _admin(client, paid, "charge", {"minutes": 90})                                               # $166.50
    _admin(client, gone, "no-show")                                                               # $11.10
    env.clock.advance(minutes=5)
    _admin(client, paid, "refund", {"cents": 5_000})

    def totals(db):
        rows = db.query(ConsultBooking).all()
        return sum(r.charged_cents for r in rows), sum(r.refunded_cents for r in rows)

    charged, refunded = _db(totals)
    assert charged == 16_650 + 2_220 + 1_110 == env.stripe.money_taken()
    assert refunded == 5_000 == env.stripe.money_returned()
    assert env.stripe.authorized() == 0                          # no hold left dangling
    assert _db(lambda db: db.query(ConsultCharge).filter(ConsultCharge.status == "pending").count()) == 0
