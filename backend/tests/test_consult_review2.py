"""Consulting calls: what the second independent review found (N1 to N7 and
the lower ones), each as a test that failed before its fix.

The review is /home/claude/briefs/REVIEW_VERIFY.md; the lead's decision for
each item is in /home/claude/briefs/REVIEW2_BRIEF.md. Where a test is the
reviewer's own proof, its docstring says so. Stripe, Google and email are
the suite's fakes; nothing here reaches a network.

The stress test runs CONSULT_STRESS_ROUNDS rounds (default 20; the acceptance
run used 300 on Postgres).
"""
from __future__ import annotations

import importlib.util
import os
import random
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
import stripe as stripe_sdk

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    NOW,
    OWNER,
    PUBLIC,
    _Resp,
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
    seed_settings,
    slot_starts,
    subjects,
    tick,
    to,
    wipe_consult,
    world,
)

from app import consult
from app import consult_auto
from app import consult_money as money
from app import emailer as E
from app.consult_models import ConsultBooking, ConsultBookingEvent, ConsultCharge
from app.db import SessionLocal
from app.models import EmailLog
from app.routes import consult as consult_routes

CLIENT = "client@example.com"
TOMORROW = ny(2031, 6, 3, 10)               # inside 24 h: the hold is placed as the card is saved ($333)
NEXT_WEEK = ny(2031, 6, 10, 10)             # eight days ahead: no hold yet ($111)
KEY_IN_USE = "There is currently another in-progress request using this Idempotent Key."


class _Down(_Resp):
    status_code = 503
    text = "service unavailable"


def _admin(client, b: dict, action: str, body: dict | None = None):
    return client.post(f"{ADMIN_API}/bookings/{b['id']}/{action}", headers=ADMIN, json=body or {})


def _a(client, b: dict) -> dict:
    return client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()


def _view(client, b: dict) -> dict:
    return client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()


def _owner(env, words: str) -> list[dict]:
    return [m for m in to(env.outbox, OWNER) if words in m["subject"]]


def _ledger(b: dict) -> list[tuple]:
    return [(c.kind, c.reason, c.status, c.amount_cents, c.captured_cents) for c in charges_of(b["id"])]


def _settle_in_thread(booking_id: int, outcome: str, name: str, results: dict, done: threading.Event | None = None):
    def run():
        db = SessionLocal()
        try:
            results[name] = consult.settle(db, db.get(ConsultBooking, booking_id), outcome, actor=f"{name}@example.com")[1]
        except Exception as exc:  # noqa: BLE001
            results[name] = exc
        finally:
            db.close()
            if done is not None:
                done.set()
    return threading.Thread(target=run, name=name)


# =============================================================================
# N1. A second capture that errors while the first is still in flight
# =============================================================================

def test_n1_a_second_capture_that_errors_while_the_first_is_in_flight_takes_the_money_once(client, env):
    """The reviewer's proof. A's capture is on the wire; B sends the same
    capture, Stripe answers 409 (the key is in use) and the SDK gives up; B
    asks Stripe where the payment stands and is told "not captured yet".
    Before: B put the row back to 'authorized', A's success was then not
    written down, and the next tick charged the card on top of the hold."""
    b = confirmed(client, env, TOMORROW, 60)
    total = booking_row(b["ref"]).total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    before = len(env.outbox)
    a_on_the_wire, b_finished = threading.Event(), threading.Event()
    in_flight = {"key": None}
    real_capture = env.stripe.PaymentIntent.capture

    def capture(pi_id, **kw):
        key = kw.get("idempotency_key")
        if threading.current_thread().name == "request-A":
            in_flight["key"] = key
            a_on_the_wire.set()
            assert b_finished.wait(20), "request B never finished"
            in_flight["key"] = None
            return real_capture(pi_id, **kw)             # Stripe completes A's capture
        if key and key == in_flight["key"]:
            env.stripe.calls.append(("PaymentIntent.capture(409)", {"id": pi_id, **kw}))
            raise stripe_sdk.APIError(KEY_IN_USE, http_status=409, code="idempotency_key_in_use")
        return real_capture(pi_id, **kw)

    env.stripe.PaymentIntent.capture = capture
    results: dict = {}
    ta = _settle_in_thread(b["id"], "charge", "request-A", results)
    tb = _settle_in_thread(b["id"], "charge", "request-B", results, b_finished)
    ta.start()
    assert a_on_the_wire.wait(20), "request A never reached Stripe"
    tb.start()
    ta.join(40)
    tb.join(40)
    env.stripe.PaymentIntent.capture = real_capture

    # B could not tell, said so, and left the row as it was; A's capture is on the ledger
    assert (results["request-B"].ok, results["request-B"].code) == (False, "capture_unconfirmed")
    assert (results["request-A"].ok, results["request-A"].status, results["request-A"].fresh) == (True, "captured", True)
    row = booking_row(b["ref"])
    assert env.stripe.money_taken() == total
    assert (row.charged_cents, row.charge_state, row.hold_state) == (total, "paid", "captured")
    assert _ledger(b) == [("hold", "hold", "captured", total, total)]

    env.clock.advance(minutes=5)
    done = tick(client)["done"]
    assert not [k for k in done if k.startswith(("collection", "settled", "hold"))], done   # nothing left to collect
    assert env.stripe.money_taken() == total and booking_row(b["ref"]).charged_cents == total
    assert env.stripe.count("PaymentIntent.create") == 1             # the hold, and no charge on top of it
    assert [s for s in subjects(env.outbox[before:], CLIENT) if s.startswith("Receipt")] == [
        f"Receipt for your consulting call ({b['ref']})"]


def test_n1_the_same_without_holding_any_thread_when_stripe_takes_two_seconds_to_capture(client, env):
    """The reviewer's second proof: nothing is held. Stripe takes 2 s over the
    capture and Charge is pressed again 0.3 s later; the same-key request
    gets 409 and, after the SDK's two retries, an APIError."""
    b = confirmed(client, env, TOMORROW, 60)
    total = booking_row(b["ref"]).total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    real_capture = env.stripe.PaymentIntent.capture
    guard = threading.Lock()
    in_progress: set = set()

    def capture(pi_id, **kw):
        key = kw.get("idempotency_key")
        for attempt in range(3):                                   # the SDK: one try and two retries
            with guard:
                replay = key in env.stripe.idem
                mine = not replay and key not in in_progress
                if mine:
                    in_progress.add(key)
            if replay:
                return real_capture(pi_id, **kw)
            if mine:
                time.sleep(2.0)                                    # Stripe is slow today
                try:
                    return real_capture(pi_id, **kw)
                finally:
                    with guard:
                        in_progress.discard(key)
            if attempt < 2:
                time.sleep(0.5 if attempt == 0 else 0.75)
        raise stripe_sdk.APIError(KEY_IN_USE, http_status=409, code="idempotency_key_in_use")

    env.stripe.PaymentIntent.capture = capture
    results: dict = {}
    first = _settle_in_thread(b["id"], "charge", "first", results)
    second = _settle_in_thread(b["id"], "charge", "second", results)
    first.start()
    time.sleep(0.3)
    second.start()
    first.join(40)
    second.join(40)
    env.stripe.PaymentIntent.capture = real_capture
    assert env.stripe.money_taken() == total and booking_row(b["ref"]).charged_cents == total
    env.clock.advance(minutes=5)
    tick(client)
    assert env.stripe.money_taken() == total, f"charged {env.stripe.money_taken()} for a call of {total}"
    assert _ledger(b) == [("hold", "hold", "captured", total, total)]


def test_n1_a_capture_with_no_answer_stays_in_flight_until_stripe_says_where_it_stands(client, env):
    """No connection on the capture, and Stripe still shows the authorization:
    that does not say the capture was not made (it may still arrive). The row
    stays 'capturing', nothing else can start meanwhile, and the tick finishes it."""
    b = confirmed(client, env, TOMORROW, 60)
    total = booking_row(b["ref"]).total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    env.stripe.capture = "refused"                                   # the connection drops
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["action"]["code"] == "capture_unconfirmed"
    assert "Nothing was charged twice" in r.json()["action"]["message"]
    assert _ledger(b) == [("hold", "hold", "capturing", total, 0)]
    row = booking_row(b["ref"])
    assert (row.hold_state, row.charge_state, row.charged_cents) == ("authorized", "pending", 0)
    # another outcome cannot be decided, and no direct charge can start, while it is open
    r = _admin(client, b, "no-show")
    assert r.status_code == 409 and "still being confirmed" in r.json()["detail"]
    assert env.stripe.count("PaymentIntent.create") == 1             # the hold; no direct charge
    env.stripe.capture = "ok"
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["collection:collected"] == 1
    assert env.stripe.money_taken() == total and _ledger(b) == [("hold", "hold", "captured", total, total)]
    assert booking_row(b["ref"]).hold_state == "captured"


def test_n1_a_capture_stripe_refuses_outright_goes_back_to_authorized_only_for_the_request_that_started_it(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    total = booking_row(b["ref"]).total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    env.stripe.capture = "invalid"                                   # Stripe answers 400 for the capture itself
    r = _admin(client, b, "charge")
    assert r.json()["action"]["code"] == "capture_failed"
    assert _ledger(b) == [("hold", "hold", "authorized", total, 0)]  # certain: it was not made
    assert booking_row(b["ref"]).hold_state == "authorized" and env.stripe.authorized() == total

    # a request that FOUND the row in flight never puts it back, whatever Stripe answers it
    db = SessionLocal()
    db.query(ConsultCharge).filter(ConsultCharge.booking_id == b["id"]).update(
        {"status": "capturing", "capture_requested_cents": total})
    db.commit()
    result = money.collect(db, db.get(ConsultBooking, b["id"]), actor="second request")
    db.close()
    assert result.code == "capture_unconfirmed"
    assert _ledger(b) == [("hold", "hold", "capturing", total, 0)]
    env.stripe.capture = "ok"
    assert _admin(client, b, "charge").json()["charged_cents"] == total
    assert env.stripe.money_taken() == total


def test_n1_a_capture_stripe_made_is_recorded_even_if_the_row_was_put_back_meanwhile(client, env):
    """The lead's first rule on its own: whatever put the row back to
    'authorized' while the capture was on its way (the code no longer does;
    an older process still running during a deploy would), a capture Stripe
    reports as made is written down. Before: it was dropped, and the hold
    was read as still there to capture or charge on top of."""
    b = confirmed(client, env, TOMORROW, 60)
    total = booking_row(b["ref"]).total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    real_capture = env.stripe.PaymentIntent.capture

    def capture_while_the_row_is_put_back(pi_id, **kw):
        pi = real_capture(pi_id, **kw)                               # Stripe takes the money
        db = SessionLocal()
        db.query(ConsultCharge).filter(ConsultCharge.booking_id == b["id"]).update(
            {"status": "authorized", "capture_requested_cents": 0})
        db.commit()
        db.close()
        return pi

    env.stripe.PaymentIntent.capture = capture_while_the_row_is_put_back
    env.outbox.clear()
    r = _admin(client, b, "charge")
    env.stripe.PaymentIntent.capture = real_capture
    assert r.json()["action"]["ok"] is True and r.json()["charged_cents"] == total
    assert _ledger(b) == [("hold", "hold", "captured", total, total)]
    row = booking_row(b["ref"])
    assert (row.hold_state, row.charge_state, row.charged_cents) == ("captured", "paid", total)
    assert events_of(b["id"]).count("charge_succeeded") == 1
    assert len([m for m in to(env.outbox, CLIENT) if m["subject"].startswith("Receipt")]) == 1
    env.clock.advance(minutes=5)
    tick(client)
    assert env.stripe.money_taken() == total and env.stripe.count("PaymentIntent.create") == 1


def test_n1_the_booking_reads_captured_only_when_the_ledger_row_is(client, env, monkeypatch):
    """What the old code got wrong at its last step: it set hold_state to
    'captured' although its own write of the capture had matched no row."""
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=65))
    real_capture = env.stripe.PaymentIntent.capture

    def capture_while_the_row_is_spoiled(pi_id, **kw):
        pi = real_capture(pi_id, **kw)
        db = SessionLocal()                                          # something this code never does
        db.query(ConsultCharge).filter(ConsultCharge.booking_id == b["id"]).update({"status": "failed"})
        db.commit()
        db.close()
        return pi

    env.stripe.PaymentIntent.capture = capture_while_the_row_is_spoiled
    r = _admin(client, b, "charge")
    env.stripe.PaymentIntent.capture = real_capture
    assert r.json()["action"]["code"] == "unrecorded"
    row = booking_row(b["ref"])
    assert row.hold_state == "authorized" and row.charged_cents == 0  # not "captured" for money the ledger does not show
    assert "capture_unrecorded" in events_of(b["id"])


def test_r2_after_an_unrecorded_capture_the_tick_takes_nothing_more(client, env):
    """Review 3, R2. The 'unrecorded' answer tells the owner to check Stripe
    before doing anything else. The automation has to wait for him too: left
    'pending', the next tick collected again, found no hold it could capture
    and charged the card directly, on top of the capture."""
    b = confirmed(client, env, TOMORROW, 60)
    total = booking_row(b["ref"]).total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    real_capture = env.stripe.PaymentIntent.capture

    def capture_while_the_row_is_spoiled(pi_id, **kw):
        pi = real_capture(pi_id, **kw)                               # Stripe takes the money
        db = SessionLocal()                                          # something this code never does
        db.query(ConsultCharge).filter(ConsultCharge.booking_id == b["id"]).update({"status": "failed"})
        db.commit()
        db.close()
        return pi

    env.stripe.PaymentIntent.capture = capture_while_the_row_is_spoiled
    r = _admin(client, b, "charge")
    env.stripe.PaymentIntent.capture = real_capture
    assert r.json()["action"]["code"] == "unrecorded"
    assert env.stripe.money_taken() == total
    row = booking_row(b["ref"])
    assert row.charge_state == "review"                              # parked for the owner, not left to the tick
    assert "Check the payment in Stripe" in row.charge_error
    creates = env.stripe.count("PaymentIntent.create")
    for minutes in (5, 10, 60, 24 * 60):                             # a day of ticks
        env.clock.set(TOMORROW + timedelta(minutes=65 + minutes))
        tick(client)
    assert env.stripe.money_taken() == total                         # nothing on top of the capture
    assert env.stripe.count("PaymentIntent.create") == creates       # and no direct charge was even tried
    assert booking_row(b["ref"]).charge_state == "review"


def test_n1_stress_overlapping_charges_with_stripe_answering_409_for_a_key_in_use(client, env):
    """The first review's stress, with real Stripe's answer to a same-key
    request that arrives while the first is in progress: an error at once
    (what the SDK raises when its retries are used up), not a wait."""
    rounds = int(os.environ.get("CONSULT_STRESS_ROUNDS", "20"))
    rng = random.Random(20261110)
    real_capture, real_create = env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create
    guard = threading.Lock()
    in_progress: set = set()

    def in_use(fn):
        def call(*a, **kw):
            key = kw.get("idempotency_key")
            with guard:
                replay = key in env.stripe.idem
                mine = not replay and key not in in_progress
                if mine:
                    in_progress.add(key)
            if not replay and not mine:
                raise stripe_sdk.APIError(KEY_IN_USE, http_status=409, code="idempotency_key_in_use")
            try:
                if mine:
                    time.sleep(rng.uniform(0.005, 0.030))            # the network
                return fn(*a, **kw)
            finally:
                if mine:
                    with guard:
                        in_progress.discard(key)
        return call

    wrong, problems = [], []
    for n in range(rounds):
        env.clock.set(NOW)
        db = SessionLocal()
        wipe_consult(db)
        seed_settings(db)
        db.close()
        env.google.events.clear()
        consult.clear_cache()
        for window in consult_routes.LIMITS.values():
            window.reset()
        env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create = real_capture, real_create
        b = confirmed(client, env, TOMORROW, 60)
        total = booking_row(b["ref"]).total_cents
        env.clock.set(TOMORROW + timedelta(minutes=65))
        env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create = in_use(real_capture), in_use(real_create)

        def press(delay):
            time.sleep(delay)
            s = SessionLocal()
            try:
                consult.settle(s, s.get(ConsultBooking, b["id"]), "charge", actor="admin@example.com")
            except consult.ConsultError:
                pass
            except Exception as exc:  # noqa: BLE001
                problems.append(repr(exc)[:200])
            finally:
                s.close()

        gap = rng.uniform(0.0, 0.035)
        threads = [threading.Thread(target=press, args=(0.0,)), threading.Thread(target=press, args=(gap,))]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create = real_capture, real_create
        env.clock.advance(minutes=5)
        tick(client)                                                 # what the cron job does next
        taken = sum(pi["amount_received"] for pi in env.stripe.payment_intents.values()
                    if (pi.get("metadata") or {}).get("booking_ref") == b["ref"])
        row = booking_row(b["ref"])
        if taken != total or row.charged_cents != total or row.charge_state != "paid":
            wrong.append((n, round(gap * 1000, 1), taken, row.charged_cents, row.charge_state))
    print(f"\nrounds: {rounds} | wrong: {len(wrong)} {wrong[:3]} | other errors: {problems[:3]}")
    assert not wrong and not problems, f"{len(wrong)} of {rounds} overlapping charges went wrong"


# ---- the same shape elsewhere: a row moved on a reading that a request still on its way makes stale ----

def test_n1_shape_a_direct_charge_parked_while_its_request_was_on_the_wire_is_still_recorded(client, env):
    """X's charge request is on its way to Stripe. Meanwhile another caller
    reads the row as "no answer for 20 hours" and parks it for the owner.
    Stripe then answers X: paid. That is written down (before: X's answer
    matched no 'pending' row and was dropped; the booking said "check Stripe")."""
    b = confirmed(client, env, NEXT_WEEK, 60)                        # no hold: charged directly
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    env.stripe.card = "network_before"                               # a first try that never arrived
    assert _admin(client, b, "charge").json()["charge_state"] == "pending"
    env.stripe.card = "ok"
    env.clock.advance(hours=19, minutes=59)
    real_create = env.stripe.PaymentIntent.create
    parked = {}

    def create(**kw):
        if not parked:
            env.clock.advance(minutes=2)                             # the other caller comes a moment later
            db = SessionLocal()
            parked["result"] = money.collect(db, db.get(ConsultBooking, b["id"]), actor="the tick")
            db.close()
        return real_create(**kw)                                     # Stripe takes the money for X

    env.stripe.PaymentIntent.create = create
    r = _admin(client, b, "charge")
    env.stripe.PaymentIntent.create = real_create
    assert parked["result"].status == "needs_review"                 # the other caller did park it
    a = r.json()
    assert (a["charged_cents"], a["charge_state"], a["needs_review"]) == (11_100, "paid", [])
    (row,) = charges_of(b["id"])
    assert (row.status, bool(row.stripe_payment_intent_id)) == ("succeeded", True)
    assert env.stripe.money_taken() == 11_100
    for _ in range(3):
        env.clock.advance(minutes=5)
        tick(client)
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    assert env.stripe.money_taken() == 11_100 and env.stripe.count("PaymentIntent.create") == 2


def test_n1_shape_a_charge_the_owner_marked_not_charged_while_its_request_was_on_the_wire(client, env):
    """The same, one step further: the attempt is parked, the owner looks,
    Stripe shows nothing for it yet, and he marks it "not charged". Then
    Stripe answers the request that was still on its way: paid. That is on
    the ledger, so Charge is not offered for money already taken."""
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    env.stripe.card = "network_before"
    assert _admin(client, b, "charge").json()["charge_state"] == "pending"
    env.stripe.card = "ok"
    env.clock.advance(hours=19, minutes=59)
    real_create = env.stripe.PaymentIntent.create
    seen = {}

    def create(**kw):
        if not seen:
            env.clock.advance(minutes=2)
            db = SessionLocal()
            seen["parked"] = money.collect(db, db.get(ConsultBooking, b["id"]), actor="the tick").status
            seen["owner"] = money.resolve_review(db, db.get(ConsultBooking, b["id"]), "not_charged", actor=OWNER)
            db.close()
        return real_create(**kw)                                     # Stripe takes the money for the first request

    env.stripe.PaymentIntent.create = create
    r = _admin(client, b, "charge")
    env.stripe.PaymentIntent.create = real_create
    assert seen["parked"] == "needs_review" and seen["owner"].ok and seen["owner"].fresh
    a = r.json()
    assert (a["charged_cents"], a["charge_state"], a["needs_review"]) == (11_100, "paid", [])
    (row,) = charges_of(b["id"])
    assert (row.status, row.error_code, bool(row.stripe_payment_intent_id)) == ("succeeded", "", True)
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    assert env.stripe.money_taken() == 11_100 and len(env.stripe.payment_intents) == 1


def test_n1_shape_a_lost_hold_closed_as_never_placed_while_its_request_was_on_the_wire(client, env):
    """X's hold request is on the wire when the client cancels; the tick asks
    Stripe, is told there is nothing, and closes the attempt. Then Stripe
    authorizes X's request. It is written down, and the tick lets it go."""
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=25))
    db = SessionLocal()
    db.get(ConsultBooking, b["id"]).hold_due_at = env.clock()
    db.commit()
    db.close()
    env.stripe.card = "network_before"
    tick(client)                                                     # a first try that never arrived
    env.stripe.card = "ok"
    real_create = env.stripe.PaymentIntent.create
    seen = {}

    def create(**kw):
        if not seen:
            seen["x"] = True
            r = client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
            assert r.json()["status"] == "cancelled"
            env.clock.advance(minutes=12)
            db = SessionLocal()
            seen["verdict"] = money.settle_lost_holds(db, db.get(ConsultBooking, b["id"]))
            db.close()
        return real_create(**kw)                                     # Stripe authorizes X's request after all

    env.stripe.PaymentIntent.create = create
    env.clock.advance(minutes=5)
    tick(client)                                                     # X: the tick asks about the hold again
    env.stripe.PaymentIntent.create = real_create
    assert seen["verdict"] == "cleared"
    (row,) = charges_of(b["id"])
    assert row.status in ("authorized", "released")                  # written down, not left as "never placed"
    env.clock.advance(minutes=5)
    tick(client)
    assert env.stripe.authorized() == 0 and env.stripe.money_taken() == 0
    assert charges_of(b["id"])[0].status == "released"


def _charged(client, env) -> dict:
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    assert _admin(client, b, "charge").json()["action"]["ok"]
    env.outbox.clear()
    return b


def test_n1_shape_a_refund_parked_while_its_request_was_on_the_wire_is_still_recorded(client, env):
    b = _charged(client, env)
    real_create = env.stripe.Refund.create
    seen = {}

    def create(**kw):
        if not seen:
            seen["x"] = True
            env.clock.advance(hours=21)
            env.stripe.list_fails = True                             # the other caller cannot ask Stripe: it parks
            db = SessionLocal()
            seen["result"] = money.finish_refunds(db, db.get(ConsultBooking, b["id"]), actor="the tick")
            db.close()
            env.stripe.list_fails = False
        return real_create(**kw)                                     # Stripe makes X's refund

    env.stripe.Refund.create = create
    r = _admin(client, b, "refund", {"cents": 5_000})
    env.stripe.Refund.create = real_create
    assert seen["result"].status == "needs_review"
    assert r.json()["refunded_cents"] == 5_000 and r.json()["action"]["ok"] is True
    (row,) = [c for c in charges_of(b["id"]) if c.kind == "refund"]
    assert row.status == "succeeded" and env.stripe.money_returned() == 5_000
    env.clock.advance(minutes=5)
    assert not [k for k in tick(client)["done"] if k.startswith("refund")]
    assert env.stripe.count("Refund.create") == 1 and env.stripe.money_returned() == 5_000


def test_n1_shape_a_refund_closed_as_never_made_is_still_recorded_when_stripe_made_it(client, env):
    """Belt and braces behind the ten-minute margin: even a refund row that
    was closed as "never made" takes Stripe's word when Stripe then says it
    made it. The money has left; a ledger that says otherwise would offer
    the same refund a second time."""
    b = _charged(client, env)
    real_create = env.stripe.Refund.create
    seen = {}

    def create(**kw):
        if not seen:
            seen["x"] = True
            env.clock.advance(hours=21)                              # far longer than any request can take
            db = SessionLocal()
            seen["result"] = money.finish_refunds(db, db.get(ConsultBooking, b["id"]), actor="the tick")
            db.close()
        return real_create(**kw)

    env.stripe.Refund.create = create
    r = _admin(client, b, "refund", {"cents": 5_000})
    env.stripe.Refund.create = real_create
    assert seen["result"].status == "failed" and seen["result"].code == "not_made"
    assert r.json()["refunded_cents"] == 5_000
    (row,) = [c for c in charges_of(b["id"]) if c.kind == "refund"]
    assert (row.status, row.error_code) == ("succeeded", "") and env.stripe.money_returned() == 5_000
    assert booking_row(b["ref"]).refunded_cents == 5_000


def test_n1_shape_a_refund_is_not_closed_as_never_made_while_a_request_for_it_could_still_be_on_its_way(client, env):
    b = _charged(client, env)
    env.stripe.refund_mode = "network_before"
    _admin(client, b, "refund", {"cents": 5_000})
    env.stripe.refund_mode = "ok"
    env.clock.advance(hours=20, minutes=5)                           # too old to send again, too young to close
    out = tick(client)["done"]
    assert "refund:not_made" not in out and "refund:refunded" not in out
    (row,) = [c for c in charges_of(b["id"]) if c.kind == "refund"]
    assert row.status == "pending" and env.stripe.count("Refund.create") == 1
    env.clock.advance(minutes=10)
    assert tick(client)["done"]["refund:not_made"] == 1


def test_a_request_that_finds_the_amount_already_collected_does_not_tell_the_owner_nothing_was_charged(client, env, monkeypatch):
    """Found while fixing N1: four presses at once sometimes produced a second
    email, "nothing to charge", next to the true one. The request that
    recorded the decision is not always the one that takes the money."""
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    env.outbox.clear()
    real = money.collect
    decided, other_done = threading.Event(), threading.Event()

    def collect(db, booking, *, actor="system"):
        if threading.current_thread().name == "decider":
            decided.set()
            assert other_done.wait(15)                               # the other request takes the money first
        return real(db, booking, actor=actor)

    monkeypatch.setattr(money, "collect", collect)
    results: dict = {}
    first = _settle_in_thread(b["id"], "charge", "decider", results)
    second = _settle_in_thread(b["id"], "charge", "other", results, other_done)
    first.start()
    assert decided.wait(15)
    second.start()
    first.join(30)
    second.join(30)
    assert results["other"].fresh is True and results["decider"].status == "noop"
    assert [m["subject"] for m in to(env.outbox, OWNER)] == [
        "[Consulting] Charge for the call: $111 went through: Casey Client"]
    assert env.stripe.money_taken() == 11_100


def test_a_decision_that_owes_nothing_is_still_reported_to_the_owner(client, env):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    env.outbox.clear()
    assert _admin(client, b, "waive").status_code == 200
    assert len(_owner(env, "nothing to charge")) == 1


# =============================================================================
# N2. The card of a call that has a hold
# =============================================================================

def test_n2a_the_card_page_does_not_open_once_the_hold_is_on_a_card(client, env):
    early = confirmed(client, env, NEXT_WEEK, 60)                    # no hold yet: the card can be replaced
    assert _view(client, early)["can_replace_card"] is True
    assert client.post(f"{PUBLIC}/booking/{early['ref']}/card", json={"t": early["token"]}).status_code == 200

    b = confirmed(client, env, TOMORROW, 60, email="held@example.com", ip="203.0.113.5")   # hold on visa 4242
    assert booking_row(b["ref"]).hold_state == "authorized"
    view = _view(client, b)
    assert (view["can_replace_card"], view["card_problem"], view["card_last4"]) == (False, False, "4242")
    sessions = env.stripe.count("Session.create")
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "A temporary hold for this call is already on your card ending 4242. To use a different card, "
        "reply to your confirmation email before the call."
    )
    assert env.stripe.count("Session.create") == sessions            # no card page was made
    # the admin's view of the booking and his buttons are as before
    a = _a(client, b)
    assert a["hold_state"] == "authorized" and a["actions"]["can_cancel"] is True


def test_n2a_the_card_page_opens_again_when_the_hold_is_refused_or_gone(client, env):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.stripe.card = "declined"
    tick(client)
    env.stripe.card = "ok"
    assert booking_row(b["ref"]).hold_state == "failed"
    view = _view(client, b)
    assert (view["can_replace_card"], view["card_problem"]) == (True, True)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    # saved: the hold goes on the new card, and from then on that is the card
    assert save_card(client, env, b["ref"], brand="mastercard", last4="5454").status_code == 200
    assert booking_row(b["ref"]).hold_state == "authorized"
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 409
    assert "ending 5454" in client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).json()["detail"]
    # the hold is let go: the page opens again
    db = SessionLocal()
    money.release_hold(db, db.get(ConsultBooking, b["id"]))
    db.close()
    assert booking_row(b["ref"]).hold_state == "released"
    assert _view(client, b)["can_replace_card"] is True


def _card_saved_next_to_a_hold(client, env) -> tuple[dict, str, str]:
    """A card page opened before the hold existed and finished after it was
    placed: the one way a new card still lands next to an authorized hold."""
    b = confirmed(client, env, NEXT_WEEK, 60)                        # visa 4242
    old_pm = booking_row(b["ref"]).stripe_payment_method_id
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    session = booking_row(b["ref"]).stripe_checkout_session_id       # the page is open in the client's browser
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    tick(client)                                                     # meanwhile the hold goes on the first card
    assert booking_row(b["ref"]).hold_state == "authorized"
    env.clock.advance(minutes=10)
    event = env.stripe.card_saved_event(session, brand="mastercard", last4="5454")
    assert post_webhook(client, env, event).status_code == 200
    return b, old_pm, booking_row(b["ref"]).stripe_payment_method_id


def test_n2c_a_card_saved_while_a_hold_is_authorized_is_kept_and_the_hold_is_not_touched(client, env):
    b, old_pm, new_pm = _card_saved_next_to_a_hold(client, env)
    row = booking_row(b["ref"])
    assert new_pm != old_pm and (row.card_brand, row.card_last4, row.hold_state) == ("mastercard", "5454", "authorized")
    # one hold, on the first card; nothing was placed, moved or released
    holds = [pi for pi in env.stripe.payment_intents.values()]
    assert len(holds) == 1 and holds[0]["payment_method"] == old_pm and holds[0]["status"] == "requires_capture"
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.count("PaymentIntent.cancel") == 0
    (line,) = [e for e in _a(client, b)["events"] if e["kind"] == "card_replaced"]
    assert line["detail"] == (
        "mastercard ending 5454. The hold of $111 stays on the previous card (Visa ending 4242): a call that "
        "takes place is charged to that card, not to the new one."
    )
    # Stripe delivers the same event again: nothing changes
    session = booking_row(b["ref"]).stripe_checkout_session_id
    assert post_webhook(client, env, env.stripe.card_saved_event(session, brand="mastercard", last4="5454")).status_code == 200
    assert events_of(b["id"]).count("card_replaced") == 1 and env.stripe.count("PaymentIntent.create") == 1
    assert booking_row(b["ref"]).hold_state == "authorized" and env.stripe.authorized() == 11_100


def test_n2b_the_receipt_and_every_view_name_the_card_the_money_was_taken_from(client, env):
    """The reviewer's proof ends here: the call is charged to the card the
    hold is on (by the lead's decision that card is the card for the call),
    and the receipt now names that card, not the one saved later."""
    b, old_pm, new_pm = _card_saved_next_to_a_hold(client, env)
    # before the call: the client's page and the admin name the card the hold is on
    view = _view(client, b)
    assert (view["card_brand"], view["card_last4"], view["can_replace_card"]) == ("visa", "4242", False)
    a = _a(client, b)
    assert (a["card_brand"], a["card_last4"]) == ("mastercard", "5454")           # the saved card
    assert (a["money_card_brand"], a["money_card_last4"]) == ("visa", "4242")     # the card the money is on
    assert [(c["kind"], c["card_brand"], c["card_last4"]) for c in a["charges"]] == [("hold", "visa", "4242")]

    env.clock.set(NEXT_WEEK + timedelta(minutes=60))
    env.outbox.clear()
    tick(client)                                                     # the owner's summary
    (summary,) = _owner(env, "confirm the outcome")
    assert "$111 authorized on Visa ending 4242" in summary["html"] and "5454" not in summary["html"]
    link = re.findall(r"/api/consult/decision\?token=([A-Za-z0-9_.\-]+)", summary["html"])[0]
    page = client.get(f"{PUBLIC}/decision?token={link}").text
    assert "Visa ending 4242" in page and "5454" not in page

    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100
    (paid,) = [pi for pi in env.stripe.payment_intents.values() if pi["amount_received"] > 0]
    assert paid["payment_method"] == old_pm                          # captured from the hold's card
    (receipt,) = [m for m in to(env.outbox, CLIENT) if m["subject"].startswith("Receipt")]
    assert "Visa ending 4242" in receipt["html"], "the receipt does not name the card that was charged"
    assert "Mastercard ending 5454" not in receipt["html"] and "5454" not in receipt["html"]
    assert _view(client, b)["card_last4"] == "4242"


def test_n2b_a_charge_made_directly_names_the_card_it_was_made_on(client, env):
    """The other way round: the hold is lost at Stripe, so the amount is
    charged to the saved card, and that is the card the receipt names."""
    b, old_pm, new_pm = _card_saved_next_to_a_hold(client, env)
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    env.stripe.capture = "expired"                                   # the authorization is gone at Stripe
    env.outbox.clear()
    r = _admin(client, b, "charge")
    assert r.json()["charged_cents"] == 11_100
    (paid,) = [pi for pi in env.stripe.payment_intents.values() if pi["amount_received"] > 0]
    assert paid["payment_method"] == new_pm
    (receipt,) = [m for m in to(env.outbox, CLIENT) if m["subject"].startswith("Receipt")]
    assert "Mastercard ending 5454" in receipt["html"] and "4242" not in receipt["html"]
    a = _a(client, b)
    assert (a["money_card_brand"], a["money_card_last4"]) == ("mastercard", "5454")
    assert [(c["kind"], c["status"], c["card_last4"]) for c in a["charges"]] == [
        ("hold", "released", "4242"), ("charge", "succeeded", "5454")]


def test_n2b_the_late_cancellation_fee_names_the_card_it_was_captured_from(client, env):
    b, old_pm, new_pm = _card_saved_next_to_a_hold(client, env)
    env.outbox.clear()
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})   # inside the fee period
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    (mail,) = [m for m in to(env.outbox, CLIENT) if "cancelled" in m["subject"]]
    assert "(Visa ending 4242)" in mail["html"] and "5454" not in mail["html"]
    assert env.stripe.money_taken() == 2_220


def test_n2b_a_ledger_row_from_before_the_card_was_kept_falls_back_to_the_saved_card(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    db = SessionLocal()
    db.query(ConsultCharge).filter(ConsultCharge.booking_id == b["id"]).update({"card_brand": "", "card_last4": ""})
    db.commit()
    booking = db.get(ConsultBooking, b["id"])
    row = db.query(ConsultCharge).filter(ConsultCharge.booking_id == b["id"]).one()
    assert consult.charged_card_text(db, booking, row.id) == "Visa ending 4242"
    assert consult.card_in_use_text(db, booking) == "Visa ending 4242"
    assert consult.money_card([row]) == ("", "")
    db.close()
    assert _view(client, b)["card_last4"] == "4242" and _a(client, b)["money_card_last4"] is None


# =============================================================================
# N3. Unfinished bookings neither stop booking nor close a day
# =============================================================================

def _book_as(client, start, minutes, email, ip):
    headers = {"CF-Connecting-IP": ip, "User-Agent": "tests/1.0"}
    q = client.post(f"{PUBLIC}/quote", json={"start": iso(start), "minutes": minutes}, headers=headers)
    version = q.json().get("terms_version", "no-quote") if q.status_code == 200 else "no-quote"
    return client.post(f"{PUBLIC}/book", headers=headers, json={
        "start": iso(start), "minutes": minutes, "full_name": "Some Body", "email": email,
        "topic": "A question about a combustor.", "timezone": "America/New_York",
        "terms_version": version, "agree": True, "website": "",
    })


def test_n3_a_stranger_cycling_unfinished_bookings_for_two_hours_does_not_keep_a_client_out(client, env):
    """The reviewer's proof: three unfinished bookings, and three more each
    time they lapse. Before: every real client's /book answered 429."""
    day = lambda d, h: ny(2031, 6, d, h)                            # noqa: E731
    stranger_times = [day(10, 9), day(11, 9), day(12, 9)]
    n = {"stranger": 0}
    answers = []

    def stranger_round():
        for at in stranger_times:
            n["stranger"] += 1
            r = _book_as(client, at, 30, f"s{n['stranger']}@example.net", f"203.0.113.{n['stranger'] % 250 + 1}")
            assert r.status_code == 200, (r.status_code, r.text)

    stranger_round()
    first = _book_as(client, day(16, 14), 60, "real.client@example.com", "198.51.100.200")
    assert first.status_code == 200, first.text                      # let in at once: the oldest reservation ended
    assert save_card(client, env, first.json()["ref"]).status_code == 200
    assert booking_row(first.json()["ref"]).status == "confirmed"
    for minute in range(1, 121):
        env.clock.advance(minutes=1)
        if minute % 15 == 0:
            stranger_round()
        if minute % 20 == 0:                                         # other real clients, other free times
            r = _book_as(client, day(17, 9) + timedelta(days=minute // 20), 30,
                         f"client{minute}@example.com", f"198.51.100.{minute}")
            answers.append(r.status_code)
            assert r.status_code == 200, r.text
            assert save_card(client, env, r.json()["ref"]).status_code == 200
        if minute % 30 == 0:
            consult_routes.LIMITS["book"].reset()
            consult_routes.LIMITS["quote"].reset()
    assert answers == [200] * 6
    db = SessionLocal()
    assert db.query(ConsultBooking).filter(ConsultBooking.status == "confirmed").count() == 7
    live = db.query(ConsultBooking).filter(ConsultBooking.status == "pending_card",
                                           ConsultBooking.hold_expires_at > env.clock()).count()
    db.close()
    assert live <= consult.MAX_PENDING_TOTAL                          # never more than three reservations at once


def test_n3_unfinished_bookings_do_not_close_a_day_that_has_one_call(client, env):
    """The reviewer's second proof: 26 open times became 0."""
    confirmed(client, env, ny(2031, 6, 10, 9), 60)
    on_the_day = lambda: [s for s in slot_starts(client)              # noqa: E731
                          if iso(ny(2031, 6, 10, 0)) <= s < iso(ny(2031, 6, 11, 0))]
    before = on_the_day()
    for i, hour in enumerate((12, 15, 18)):
        assert _book_as(client, ny(2031, 6, 10, hour), 30, f"h{i}@example.net", f"203.0.113.{i + 1}").status_code == 200
    after = on_the_day()
    assert len(before) > 20 and len(after) == len(before) - 3 * 3    # each holds its own time and its two neighbours' overlap
    assert iso(ny(2031, 6, 10, 20)) in after


def test_n3_a_client_whose_reservation_ended_early_is_told_plainly_when_the_time_was_lost(client, env):
    first = _book_as(client, NEXT_WEEK, 60, "first@example.com", "198.51.100.1")
    assert first.status_code == 200
    for i in range(3):                                               # three more bookings: the first reservation ends
        env.clock.advance(seconds=30)
        assert _book_as(client, NEXT_WEEK + timedelta(days=i + 1), 30, f"x{i}@example.com", f"198.51.100.{i + 2}").status_code == 200
    row = booking_row(first.json()["ref"])
    assert row.status == "expired"
    assert "ended early" in [e for e in _events(row.id) if e.kind == "expired"][0].note
    # someone else books that very time and saves a card first
    other = _book_as(client, NEXT_WEEK, 60, "other@example.com", "198.51.100.77")
    assert other.status_code == 200 and save_card(client, env, other.json()["ref"]).status_code == 200
    env.outbox.clear()
    assert save_card(client, env, first.json()["ref"]).status_code == 200     # the first client finishes the card page
    row = booking_row(first.json()["ref"])
    assert row.status == "expired" and "slot_lost" in events_of(row.id)
    (mail,) = to(env.outbox, "first@example.com")
    assert mail["subject"] == f"Your consulting call could not be confirmed ({row.ref})"
    assert "Nothing was charged, and the card you entered will not be used." in mail["html"]
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0


def _events(booking_id: int) -> list[ConsultBookingEvent]:
    db = SessionLocal()
    try:
        rows = db.query(ConsultBookingEvent).filter(ConsultBookingEvent.booking_id == booking_id).order_by(
            ConsultBookingEvent.id).all()
        for r in rows:
            db.expunge(r)
        return rows
    finally:
        db.close()


def test_n3_the_limits_per_visitor_still_refuse(client, env):
    for i in range(3):
        assert _book_as(client, NEXT_WEEK + timedelta(days=i), 30, f"me{i}@example.com", "198.51.100.9").status_code == 200
    r = _book_as(client, NEXT_WEEK + timedelta(days=4), 30, "me9@example.com", "198.51.100.9")
    assert r.status_code == 429 and "waiting for a card" in r.json()["detail"]
    db = SessionLocal()
    assert db.query(ConsultBooking).filter(ConsultBooking.status == "pending_card").count() == 3   # none was ended for it
    db.close()


# =============================================================================
# N4. "Asked" means "sent"
# =============================================================================

def test_n4_a_summary_cut_short_after_its_mark_is_sent_again_and_nothing_is_charged_before(client, env, monkeypatch):
    """The reviewer's proof: the run stops between the mark and the email."""
    b = confirmed(client, env, TOMORROW, 60)                         # attendance unknown: default is the full charge
    end = TOMORROW + timedelta(minutes=60)
    env.clock.set(end + timedelta(minutes=1))
    real = consult_auto.send_email
    state = {"cut": 0}

    def cut_short_once(*a, **kw):
        if kw.get("template") == "consult_owner_summary" and not state["cut"]:
            state["cut"] += 1
            raise RuntimeError("the request stopped here (process restarted)")
        return real(*a, **kw)

    monkeypatch.setattr(consult_auto, "send_email", cut_short_once)
    first = tick(client)
    assert first["problems"] and booking_row(b["ref"]).summary_sent_at is not None    # marked, not sent
    env.clock.advance(minutes=5)
    tick(client)
    assert _owner(env, "confirm the outcome") == []                  # the mark is not yet old enough to distrust
    env.clock.advance(minutes=5)
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["summaries_unsent"] == 1
    sent_at = env.clock()
    assert tick(client)["done"]["summary"] == 1                      # given back and sent
    (mail,) = _owner(env, "confirm the outcome")
    row = booking_row(b["ref"])
    assert money.aware(row.settle_due_at) == sent_at + timedelta(hours=2)   # his two hours count from the real send
    assert events_of(b["id"]).count("summary_sent") == 1
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["summaries_unsent"] == 0
    # the old deadline passes: nothing is charged; the new one: the default applies
    env.clock.set(end + timedelta(hours=2, minutes=5))
    assert "settled:charge" not in tick(client)["done"] and env.stripe.money_taken() == 0
    env.clock.set(sent_at + timedelta(hours=2))
    assert tick(client)["done"]["settled:charge"] == 1
    assert len(_owner(env, "confirm the outcome")) == 1


def test_n4_a_mark_alone_never_lets_the_default_outcome_run(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    end = TOMORROW + timedelta(minutes=60)
    db = SessionLocal()
    row = db.get(ConsultBooking, b["id"])
    row.summary_sent_at = end                                        # as a stopped run leaves it
    db.commit()
    env.clock.set(end + timedelta(hours=2, minutes=1))
    assert consult_auto.settle_due(db, b["id"]) == "waiting"
    db.close()
    assert booking_row(b["ref"]).settlement == "" and env.stripe.money_taken() == 0


def test_n4_a_mark_given_back_leaves_the_call_as_if_the_owner_had_never_been_asked(client, env, monkeypatch):
    """The stopped run had also written its own deadline next to the mark.
    When the mark goes back and the email service then refuses the summary,
    nothing of that run is left: no mark, and the automatic outcome's time
    is the scheduled one again (the admin shows it)."""
    b = confirmed(client, env, TOMORROW, 60)
    end = TOMORROW + timedelta(minutes=60)
    db = SessionLocal()
    row = db.get(ConsultBooking, b["id"])
    row.summary_sent_at = end + timedelta(hours=3)                   # a late run, stopped before it sent
    row.settle_due_at = end + timedelta(hours=5)
    db.commit()
    db.close()
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    env.clock.set(end + timedelta(hours=3, minutes=10))
    assert "summary" not in tick(client)["done"]                     # given back, tried, refused
    row = booking_row(b["ref"])
    assert row.summary_sent_at is None and money.aware(row.settle_due_at) == end + timedelta(hours=2)
    assert _a(client, b)["settle_due_at"] == iso(end + timedelta(hours=2))
    assert row.settlement == "" and env.stripe.money_taken() == 0 and _log_lines("consult_owner_summary") == 1


def test_n4_a_normal_summary_is_sent_exactly_once(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=60))
    for _ in range(24):                                              # every five minutes until just before the outcome
        tick(client)
        env.clock.advance(minutes=5)
    assert len(_owner(env, "confirm the outcome")) == 1 and events_of(b["id"]).count("summary_sent") == 1
    assert booking_row(b["ref"]).settlement == ""
    db = SessionLocal()
    assert consult_auto.send_summary(db, b["id"]) is False           # asked for directly: not a second time either
    db.close()
    assert len(_owner(env, "confirm the outcome")) == 1
    tick(client)
    assert booking_row(b["ref"]).settlement == "charged"
    assert len(_owner(env, "confirm the outcome")) == 1


def test_n4_four_runs_at_once_send_a_cut_short_summary_once(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    end = TOMORROW + timedelta(minutes=60)
    db = SessionLocal()
    db.get(ConsultBooking, b["id"]).summary_sent_at = end
    db.commit()
    db.close()
    env.clock.set(end + timedelta(minutes=11))
    go = threading.Barrier(4)

    def run():
        s = SessionLocal()
        try:
            go.wait(10)
            consult_auto.send_summary(s, b["id"])
        finally:
            s.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert len(_owner(env, "confirm the outcome")) == 1 and events_of(b["id"]).count("summary_sent") == 1


# =============================================================================
# N5. A replacement card saved just before a restart
# =============================================================================

def _cut_the_follow_up_once(monkeypatch) -> None:
    real = consult.after_card_replaced
    cut = {"n": 0}

    def stopped_here(db, booking):
        if not cut["n"]:
            cut["n"] += 1
            raise RuntimeError("the request stopped here (process restarted)")
        return real(db, booking)

    monkeypatch.setattr(consult, "after_card_replaced", stopped_here)


def _deliver_twice(client, env, event) -> None:
    try:
        post_webhook(client, env, event)
    except RuntimeError:
        pass                                                         # no answer: the server stopped
    assert post_webhook(client, env, event).status_code == 200       # Stripe delivers the event again: a replay


def test_n5_a_new_card_saved_just_before_a_restart_gets_the_hold_from_the_tick(client, env, monkeypatch):
    """The reviewer's proof. Before: never tried, and the call was cancelled
    "because no other card was provided"."""
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.stripe.card = "declined"
    tick(client)
    assert booking_row(b["ref"]).hold_state == "failed"
    env.stripe.card = "ok"
    env.clock.advance(hours=3)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    event = env.stripe.card_saved_event(booking_row(b["ref"]).stripe_checkout_session_id, brand="mastercard", last4="5454")
    _cut_the_follow_up_once(monkeypatch)
    _deliver_twice(client, env, event)
    row = booking_row(b["ref"])
    assert (row.card_last4, row.hold_state) == ("5454", "failed")    # saved; nothing tried on it yet
    env.outbox.clear()
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["new_card:hold"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.hold_state) == ("confirmed", "authorized")
    assert [(c.attempt, c.status, c.card_last4) for c in charges_of(b["id"])] == [(1, "failed", "4242"), (2, "authorized", "5454")]
    assert any("temporary hold" in s for s in subjects(env.outbox, CLIENT))
    while env.clock() < NEXT_WEEK - timedelta(hours=1, minutes=50):
        env.clock.advance(minutes=25)
        tick(client)
    assert booking_row(b["ref"]).status == "confirmed"               # not cancelled for want of a card
    assert env.stripe.authorized() == 11_100 and len(env.stripe.payment_intents) == 2


def test_n5_a_refused_amount_is_collected_from_a_card_saved_just_before_a_restart(client, env, monkeypatch):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    env.stripe.card = "declined"
    assert _admin(client, b, "charge").json()["charge_state"] == "failed"
    env.stripe.card = "ok"
    env.clock.advance(hours=1)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    event = env.stripe.card_saved_event(booking_row(b["ref"]).stripe_checkout_session_id, brand="mastercard", last4="5454")
    _cut_the_follow_up_once(monkeypatch)
    _deliver_twice(client, env, event)
    assert booking_row(b["ref"]).charge_state == "failed" and env.stripe.money_taken() == 0
    env.outbox.clear()
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["new_card:charge"] == 1
    row = booking_row(b["ref"])
    assert (row.charge_state, row.charged_cents) == ("paid", 11_100) and env.stripe.money_taken() == 11_100
    (receipt,) = [m for m in to(env.outbox, CLIENT) if m["subject"].startswith("Receipt")]
    assert "Mastercard ending 5454" in receipt["html"]
    assert len(_owner(env, "Retried on the new card")) == 1
    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert env.stripe.money_taken() == 11_100


def test_n5_a_new_card_that_is_refused_too_is_not_tried_again_and_again(client, env, monkeypatch):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.stripe.card = "declined"
    tick(client)
    env.clock.advance(hours=3)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    event = env.stripe.card_saved_event(booking_row(b["ref"]).stripe_checkout_session_id, brand="mastercard", last4="5454")
    _cut_the_follow_up_once(monkeypatch)
    _deliver_twice(client, env, event)
    env.outbox.clear()
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["new_card:hold"] == 1                # tried on the new card: refused as well
    assert booking_row(b["ref"]).hold_state == "failed"
    (asked,) = [m for m in to(env.outbox, CLIENT) if m["subject"].startswith("Action needed")]
    assert "Mastercard ending 5454" in asked["html"] and "4242" not in asked["html"]   # told about the card just refused
    for _ in range(4):
        env.clock.advance(minutes=5)
        assert "new_card:hold" not in tick(client)["done"]
    assert env.stripe.count("PaymentIntent.create") == 2             # once per card
    assert [(c.attempt, c.card_last4) for c in charges_of(b["id"])] == [(1, "4242"), (2, "5454")]
    assert len([m for m in to(env.outbox, CLIENT) if m["subject"].startswith("Action needed")]) == 1
    env.clock.set(NEXT_WEEK - timedelta(hours=2))                    # no card that works by the deadline
    assert tick(client)["done"]["hold:cancelled"] == 1
    assert booking_row(b["ref"]).status == "cancelled"


def test_n5_a_card_saved_at_the_last_moment_is_tried_and_the_call_is_not_cancelled_meanwhile(client, env, monkeypatch):
    """A card saved in the last two minutes is left to the request that saved
    it (most likely still at work), and a booking whose new card is waiting
    to be tried is never cancelled "because no other card was provided"."""
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.stripe.card = "declined"
    tick(client)
    env.stripe.card = "ok"
    env.clock.set(NEXT_WEEK - timedelta(hours=2, minutes=1))          # one minute before the hold deadline
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    event = env.stripe.card_saved_event(booking_row(b["ref"]).stripe_checkout_session_id, brand="mastercard", last4="5454")
    _cut_the_follow_up_once(monkeypatch)
    _deliver_twice(client, env, event)
    env.outbox.clear()
    env.clock.advance(minutes=1)                                     # the deadline; the card is one minute old
    db = SessionLocal()
    assert consult_auto.retry_on_new_card(db, b["id"]) == "waiting"
    db.close()
    done = tick(client)["done"]
    assert "new_card:hold" not in done and "hold:cancelled" not in done
    row = booking_row(b["ref"])
    assert (row.status, row.hold_state) == ("confirmed", "failed") and env.stripe.count("PaymentIntent.create") == 1
    assert to(env.outbox, CLIENT) == []                              # not asked for a card again either
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["new_card:hold"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.hold_state) == ("confirmed", "authorized") and env.stripe.authorized() == 11_100


def test_n5_four_ticks_at_once_try_the_new_card_once(client, env, monkeypatch):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.stripe.card = "declined"
    tick(client)
    env.stripe.card = "ok"
    env.clock.advance(hours=3)
    client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    event = env.stripe.card_saved_event(booking_row(b["ref"]).stripe_checkout_session_id, brand="mastercard", last4="5454")
    _cut_the_follow_up_once(monkeypatch)
    _deliver_twice(client, env, event)
    env.clock.advance(minutes=5)
    env.outbox.clear()
    go = threading.Barrier(4)
    results: list = []

    def run():
        s = SessionLocal()
        try:
            go.wait(10)
            results.append(consult_auto._tick(s, consult.utcnow()))  # past the in-process lock, on purpose
        except Exception as exc:  # noqa: BLE001
            results.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert all(isinstance(r, dict) for r in results), results
    assert env.stripe.authorized() == 11_100 and len(env.stripe.payment_intents) == 2
    assert booking_row(b["ref"]).hold_state == "authorized"
    assert len([s for s in subjects(env.outbox, CLIENT) if "temporary hold" in s]) == 1


# =============================================================================
# N6. The stopped-automation alert, and the cron job's exit status
# =============================================================================

def test_n6_the_owner_is_told_when_the_tick_stops_and_the_only_call_has_ended_unsettled(client, env, monkeypatch):
    """The reviewer's proof."""
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW - timedelta(minutes=10))
    tick(client)                                                     # the cron job's last run
    monkeypatch.setattr(consult_routes, "TICK_WATCH_SECONDS", 0)
    monkeypatch.setattr(consult_routes, "_last_watch", [-1.0])
    env.outbox.clear()
    for hours in (1, 2, 4, 8, 24, 48, 72):
        env.clock.set(TOMORROW + timedelta(hours=hours, minutes=5))
        assert client.get(f"{PUBLIC}/availability").status_code == 200
        assert client.get(f"{ADMIN_API}/status", headers=ADMIN).status_code == 200
    alerts = _owner(env, "automation has stopped")
    assert len(alerts) == 3                                          # at most one in 24 hours: at hours 1, 48 and 72
    assert "1 call is waiting for it" in alerts[0]["html"] and "Casey Client" in alerts[0]["html"]
    assert "already started and not settled" in alerts[0]["html"]
    # settled by hand: nothing is waiting any more, and the alerts stop
    assert _admin(client, b, "charge").status_code == 200
    env.outbox.clear()
    env.clock.advance(days=2)
    client.get(f"{PUBLIC}/availability")
    assert _owner(env, "automation has stopped") == []


def test_n6_a_settled_call_whose_payment_is_still_open_counts_too(client, env, monkeypatch):
    """"It is asked again within a few minutes" is the tick's promise (N1:
    a capture with no answer stays open). With the tick stopped, the owner
    is told that this call is waiting for it."""
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=65))
    tick(client)                                                     # the cron job's last run
    env.stripe.capture = "refused"                                   # no answer to the capture
    assert _admin(client, b, "charge").json()["action"]["code"] == "capture_unconfirmed"
    row = booking_row(b["ref"])
    assert (row.status, row.charge_state) == ("completed", "pending")
    monkeypatch.setattr(consult_routes, "TICK_WATCH_SECONDS", 0)
    monkeypatch.setattr(consult_routes, "_last_watch", [-1.0])
    env.outbox.clear()
    env.clock.advance(hours=1)
    assert client.get(f"{PUBLIC}/availability").status_code == 200
    (alert,) = _owner(env, "automation has stopped")
    assert "1 call is waiting for it" in alert["html"] and "Stripe has not confirmed yet" in alert["html"]
    env.stripe.capture = "ok"
    assert _admin(client, b, "charge").json()["charged_cents"] == booking_row(b["ref"]).total_cents
    env.outbox.clear()
    env.clock.advance(days=2)
    client.get(f"{PUBLIC}/availability")
    assert _owner(env, "automation has stopped") == []               # nothing is waiting any more


def _cron_script():
    path = Path(consult.__file__).resolve().parent.parent / "scripts" / "consult_tick_cron.py"   # backend/scripts
    spec = importlib.util.spec_from_file_location("consult_tick_cron_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("status, body, code", [
    (200, {"ok": True, "done": {"hold:hold_notice": 1}, "problems": []}, 0),
    (200, {"ok": True, "busy": True, "problems": []}, 0),
    (200, {"ok": False, "done": {}, "problems": ["collection: booking 7: boom"]}, 3),
    (200, {"ok": True, "done": {}, "problems": ["hold: booking 3: boom"]}, 3),
    (401, {"detail": "no"}, 1),
    (500, {"detail": "boom"}, 1),
])
def test_n6_the_cron_run_fails_when_the_tick_reports_problems(monkeypatch, capsys, status, body, code):
    script = _cron_script()

    class Answer:
        status_code = status
        ok = status < 400
        text = str(body)

        def json(self):
            return body

    sent = {}
    monkeypatch.setattr(script, "SECRET", "the-cron-secret")
    monkeypatch.setattr(script.requests, "post", lambda url, headers, timeout: (sent.update(url=url, headers=headers), Answer())[1])
    assert script.main() == code
    assert sent["url"].endswith("/api/admin/consult/tick") and sent["headers"] == {"X-Cron-Secret": "the-cron-secret"}
    monkeypatch.setattr(script, "SECRET", "")
    assert script.main() == 2


# =============================================================================
# N7. The visitor's address
# =============================================================================

@pytest.mark.parametrize("cf, forwarded, expected", [
    ("203.0.113.7", "198.51.100.9", "203.0.113.7"),                 # the edge's header, when it is an address
    ("2001:DB8::1", "", "2001:db8::1"),                              # an IPv6 address, in its usual spelling
    (" 203.0.113.7 ", "", "203.0.113.7"),
    ("not-an-address; DROP TABLE; <b>hello</b>", "198.51.100.9", "198.51.100.9"),
    ("203.0.113.7, 10.0.0.1", "198.51.100.9", "198.51.100.9"),      # a list is not an address
    ("", "198.51.100.9, 10.0.0.1", "198.51.100.9"),                 # no edge header: the existing rule
    ("", "<script>", ""),                                            # nothing usable: the test client's socket is no address
    ("999.1.1.1", "also wrong", ""),
])
def test_n7_only_an_address_is_taken_as_the_visitors_address(cf, forwarded, expected):
    class Request:
        headers = {k: v for k, v in (("cf-connecting-ip", cf), ("x-forwarded-for", forwarded)) if v}
        client = type("C", (), {"host": "testclient"})()

    assert consult_routes._ip(Request()) == expected
    Request.client = type("C", (), {"host": "192.0.2.200"})()
    assert consult_routes._ip(Request()) == (expected or "192.0.2.200")   # otherwise the socket's own address


def test_n7_text_that_is_not_an_address_does_not_open_a_new_allowance_per_request(client, env):
    """Consequence 1, as far as code can close it: a different made-up value
    each time used to be a different "address". (A caller who can write real
    addresses into the header still can; that is the platform's to stop.)"""
    codes = [
        get_quote(client, NEXT_WEEK, 60, headers={
            "CF-Connecting-IP": f"visitor-{i}.example", "X-Forwarded-For": "198.51.100.9"}).status_code
        for i in range(41)
    ]
    assert codes[:40] == [200] * 40 and codes[40] == 429


def test_n7_made_up_decision_tokens_cannot_use_up_the_owners_allowance(client, env):
    """Consequence 2 (the reviewer's proof, reversed): sixty requests with a
    worthless token "from" the owner's address; his own button still works."""
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    tick(client)
    summary = _owner(env, "confirm the outcome")[-1]
    token = re.findall(r"/api/consult/decision\?token=([A-Za-z0-9_.\-]+)", summary["html"])[2]   # "Do not charge"
    owner_ip = {"CF-Connecting-IP": "192.0.2.44"}
    spent = [client.get(f"{PUBLIC}/decision?token=x", headers=owner_ip).status_code for _ in range(60)]
    assert spent[:30] == [400] * 30 and set(spent[30:]) == {429}     # made-up tokens have their own, smaller allowance
    assert client.post(f"{PUBLIC}/decision?token=y", headers=owner_ip).status_code == 429
    r = client.post(f"{PUBLIC}/decision?token={token}", headers=owner_ip)
    assert r.status_code == 200
    row = booking_row(b["ref"])
    assert (row.owner_choice, row.settlement) == ("waive", "waived") and env.stripe.money_taken() == 0


def test_n7_valid_links_are_still_limited_per_address(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    tick(client)
    token = re.findall(r"/api/consult/decision\?token=([A-Za-z0-9_.\-]+)", _owner(env, "confirm the outcome")[-1]["html"])[0]
    codes = [client.get(f"{PUBLIC}/decision?token={token}", headers={"CF-Connecting-IP": "192.0.2.44"}).status_code
             for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    assert booking_row(b["ref"]).owner_choice == ""                  # looking decides nothing


def test_n7_the_consent_record_never_keeps_text_that_is_not_an_address(client, env):
    """Consequence 3 (the reviewer's proof, reversed)."""
    said = "not-an-address; DROP TABLE; <b>hello</b>"
    for headers, expected in (
        ({"CF-Connecting-IP": said}, ""),                            # nothing usable was sent
        ({"CF-Connecting-IP": said, "X-Forwarded-For": "198.51.100.9"}, "198.51.100.9"),
        ({"CF-Connecting-IP": "2001:DB8::7"}, "2001:db8::7"),
    ):
        start = NEXT_WEEK + timedelta(days=len(expected) % 5)
        q = client.post(f"{PUBLIC}/quote", json={"start": iso(start), "minutes": 60}, headers=headers).json()
        r = client.post(f"{PUBLIC}/book", headers=headers, json={
            "start": iso(start), "minutes": 60, "full_name": "Casey Client", "email": f"c{len(expected)}@example.com",
            "topic": "A question about a combustor.", "timezone": "Europe/London",
            "terms_version": q["terms_version"], "agree": True, "website": "",
        })
        assert r.status_code == 200, r.text
        assert booking_row(r.json()["ref"]).consent_ip == expected
        a = client.get(f"{ADMIN_API}/bookings/{booking_row(r.json()['ref']).id}", headers=ADMIN).json()
        assert a["consent"]["ip"] == expected and "DROP TABLE" not in str(a)


# =============================================================================
# The lower ones
# =============================================================================

def test_a_refund_of_another_amount_is_refused_while_an_earlier_one_is_unresolved(client, env):
    """The reviewer's note, reversed: $100 pressed while a $50 refund has no
    answer used to be answered "ok, $50"."""
    b = _charged(client, env)
    env.stripe.refund_mode = "network_after"                         # Stripe makes the $50 refund; the answer is lost
    _admin(client, b, "refund", {"cents": 5_000})
    env.stripe.refund_mode = "ok"
    env.clock.advance(seconds=30)
    calls = len(env.stripe.calls)
    r = _admin(client, b, "refund", {"cents": 10_000})
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "A refund of $50.00 asked for earlier has no answer from Stripe yet, so nothing new was sent. It is "
        "checked again within a few minutes. Refund $100.00 once that one shows as refunded or as not made."
    )
    assert len(env.stripe.calls) == calls and env.stripe.money_returned() == 5_000
    # the same amount again finishes the earlier one; then the other amount can be refunded
    r = _admin(client, b, "refund", {"cents": 5_000})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 5_000 and env.stripe.count("Refund.create") == 1
    env.clock.advance(minutes=3)
    r = _admin(client, b, "refund", {"cents": 10_000})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 15_000 and env.stripe.money_returned() == 15_000


def _time_lost_while_the_card_was_entered(client, env) -> str:
    first = _book_as(client, NEXT_WEEK, 60, "late@example.com", "198.51.100.1")
    env.clock.advance(minutes=16)                                    # the reservation runs out
    other = _book_as(client, NEXT_WEEK, 60, "other@example.com", "198.51.100.77")
    assert save_card(client, env, other.json()["ref"]).status_code == 200
    return first.json()["ref"]


def test_the_could_not_be_confirmed_email_is_sent_by_the_tick_when_it_failed_at_first(client, env, monkeypatch):
    ref = _time_lost_while_the_card_was_entered(client, env)
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    assert save_card(client, env, ref).status_code == 200            # the client saves a card; the time is gone
    row = booking_row(ref)
    assert row.status == "expired" and row.cancel_notice_sent_at is None
    monkeypatch.setattr(E, "_resend_post", real)
    env.outbox.clear()
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["slot_lost_notice"] == 1
    (mail,) = to(env.outbox, "late@example.com")
    assert mail["subject"] == f"Your consulting call could not be confirmed ({ref})"
    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert len(to(env.outbox, "late@example.com")) == 1
    # a redelivery of the card event does not send it a second time
    assert booking_row(ref).cancel_notice_sent_at is not None


def _log_lines(template: str) -> int:
    db = SessionLocal()
    try:
        return db.query(EmailLog).filter(EmailLog.template == template).count()
    finally:
        db.close()


def test_an_email_the_service_keeps_refusing_is_tried_a_dozen_times_then_once_an_hour(client, env, monkeypatch):
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    data = book(client, NEXT_WEEK, 60).json()
    assert save_card(client, env, data["ref"]).status_code == 200    # try 1 of each confirmation email, both refused
    for _ in range(72):                                              # six hours of ticks
        env.clock.advance(minutes=5)
        tick(client)
    # before: one line every five minutes for each (73 by now). Now: 12, then one an hour.
    for template in ("consult_confirmed", "consult_owner_new"):
        assert 12 + 4 <= _log_lines(template) <= 12 + 6, (template, _log_lines(template))
    row = booking_row(data["ref"])
    assert row.confirmation_sent_at is None and row.email_tries["confirmation_sent_at"]["n"] >= 16
    monkeypatch.setattr(E, "_resend_post", real)
    for _ in range(13):                                              # the service is back: sent with the next hourly try
        env.clock.advance(minutes=5)
        tick(client)
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call is confirmed ({data['ref']})"]
    assert len(_owner(env, "New booking")) == 1
    assert booking_row(data["ref"]).email_tries == {}


def test_a_summary_the_service_keeps_refusing_is_bounded_too_and_the_admin_status_keeps_saying_so(client, env, monkeypatch):
    b = confirmed(client, env, TOMORROW, 60)
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    env.clock.set(TOMORROW + timedelta(minutes=60))
    tick(client)
    assert booking_row(b["ref"]).summary_sent_at is None             # refused: the mark went back at once
    env.clock.advance(minutes=5)
    tick(client)
    assert _log_lines("consult_owner_summary") == 2                  # and the very next tick tried again
    env.clock.advance(minutes=5)
    for _ in range(70):
        tick(client)
        env.clock.advance(minutes=5)
    assert 12 + 4 <= _log_lines("consult_owner_summary") <= 12 + 6
    status = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert status["summaries_unsent"] == 1 and "has not accepted the summary email yet" in status["summaries_unsent_note"]
    assert booking_row(b["ref"]).settlement == "" and env.stripe.money_taken() == 0
