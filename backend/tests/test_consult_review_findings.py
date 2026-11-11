"""Consulting calls: the defects an independent review found, each as a test.

Every test here was written from the reviewer's proof (see
/home/claude/briefs/REVIEW_PAYMENTS.md; the finding's number is in the test's
name) and failed on the code as it stood before the fix. Stripe, Google and
email are the suite's fakes; nothing here reaches a network.

The stress test of finding 1 runs CONSULT_STRESS_ROUNDS rounds (default 20,
to keep the suite quick; the acceptance run used 300 on SQLite and Postgres).
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import threading
import time
from datetime import timedelta

import pytest

import conftest
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
    grant_meet_scope,
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
from app.consult_models import ConsultBooking
from app.db import SessionLocal
from app.deps import make_session_token
from app.routes import consult as consult_routes

CLIENT = "client@example.com"
TOMORROW = ny(2031, 6, 3, 10)               # inside 24 h: the hold is placed as the card is saved
NEXT_WEEK = ny(2031, 6, 10, 10)             # eight days ahead: no hold yet


class _Down(_Resp):
    status_code = 503
    text = "service unavailable"


# -----------------------------------------------------------------------------
# 1. Two overlapping collections of one decided amount
# -----------------------------------------------------------------------------

def _race(env, monkeypatch, booking_id: int, outcome_a: str = "charge", outcome_b: str = "charge"):
    """Request A's capture is on the wire at Stripe while request B reads
    "nothing charged yet, a hold is authorized"; B goes on only after A has
    finished."""
    a_in_stripe, b_has_read, a_done = threading.Event(), threading.Event(), threading.Event()
    real_api_capture = env.stripe.PaymentIntent.capture

    def capture_on_the_wire(pi_id, **kw):
        a_in_stripe.set()
        assert b_has_read.wait(15), "request B never got to its read"
        return real_api_capture(pi_id, **kw)

    env.stripe.PaymentIntent.capture = capture_on_the_wire
    real = money._capture_hold

    def capture_hold(db, booking, cents, reason, *, actor):
        if threading.current_thread().name == "request-B":
            b_has_read.set()
            assert a_done.wait(15), "request A never finished"
        return real(db, booking, cents, reason, actor=actor)

    monkeypatch.setattr(money, "_capture_hold", capture_hold)
    results, errors = {}, {}

    def request(name, outcome):
        db = SessionLocal()
        try:
            _, results[name] = consult.settle(
                db, db.get(ConsultBooking, booking_id), outcome, actor=f"{name}@example.com")
        except Exception as exc:  # noqa: BLE001
            errors[name] = exc
        finally:
            db.close()
            if name == "request-A":
                a_done.set()

    ta = threading.Thread(target=request, args=("request-A", outcome_a), name="request-A")
    tb = threading.Thread(target=request, args=("request-B", outcome_b), name="request-B")
    ta.start()
    assert a_in_stripe.wait(15), "request A never reached Stripe"
    tb.start()
    ta.join(30)
    tb.join(30)
    assert not ta.is_alive() and not tb.is_alive()
    env.stripe.PaymentIntent.capture = real_api_capture
    return results, errors


def test_f1_two_charge_requests_at_once_take_the_money_once(client, env, monkeypatch):
    b = confirmed(client, env, TOMORROW, 60)
    row = booking_row(b["ref"])
    assert row.hold_state == "authorized"
    total = row.total_cents
    env.clock.set(TOMORROW + timedelta(minutes=65))
    before = len(env.outbox)
    results, errors = _race(env, monkeypatch, b["id"])
    assert errors == {}, errors
    assert env.stripe.money_taken() == total, "the client was charged twice for one call"
    row = booking_row(b["ref"])
    assert (row.charged_cents, row.charge_state) == (total, "paid")
    assert [(c.kind, c.status, c.captured_cents) for c in charges_of(b["id"])] == [("hold", "captured", total)]
    assert [s for s in subjects(env.outbox[before:], CLIENT) if s.startswith("Receipt")] == [
        f"Receipt for your consulting call ({b['ref']})"]
    # the request that found the hold already captured reports it as captured, not as lost
    assert {r.status for r in results.values()} <= {"captured", "noop"}


def test_f1_a_double_click_on_charge_under_real_timing_never_charges_twice(client, env):
    rounds = int(os.environ.get("CONSULT_STRESS_ROUNDS", "20"))
    rng = random.Random(20261110)
    real_capture, real_create = env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create

    def slow(fn):
        def call(*a, **kw):
            time.sleep(rng.uniform(0.005, 0.030))            # the network
            return fn(*a, **kw)
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
        env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create = slow(real_capture), slow(real_create)

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
        taken = sum(pi["amount_received"] for pi in env.stripe.payment_intents.values()
                    if (pi.get("metadata") or {}).get("booking_ref") == b["ref"])
        row = booking_row(b["ref"])
        if taken != total or row.charged_cents != total or row.charge_state != "paid":
            wrong.append((n, round(gap * 1000, 1), taken, row.charged_cents, row.charge_state))
    env.stripe.PaymentIntent.capture, env.stripe.PaymentIntent.create = real_capture, real_create
    print(f"\nrounds: {rounds} | wrong: {len(wrong)} {wrong[:3]} | other errors: {problems[:3]}")
    assert not wrong and not problems, f"{len(wrong)} of {rounds} double clicks went wrong"


def test_f1_a_decision_changed_while_a_charge_was_starting_is_not_collected_twice(client, env, monkeypatch):
    """Same root cause, the other shape: nothing re-read the decision after
    collect let go of the lock. A is about to charge the booked amount; B
    changes the outcome to no-show and takes the fee; A must not then take
    the booked amount on top."""
    b = confirmed(client, env, NEXT_WEEK, 60)        # no tick ran: no hold, the card is charged directly
    env.clock.set(NEXT_WEEK + timedelta(minutes=65))
    row = booking_row(b["ref"])
    total, fee = row.total_cents, row.fee_cents
    a_has_read, b_done = threading.Event(), threading.Event()
    real = money.charge_saved_card

    def charge(db, booking, cents, reason, *, actor="system"):
        if threading.current_thread().name == "request-A":
            a_has_read.set()                         # A has read: the booked amount is owed
            assert b_done.wait(15), "request B never finished"
        return real(db, booking, cents, reason, actor=actor)

    monkeypatch.setattr(money, "charge_saved_card", charge)
    out: dict = {}

    def request(name, outcome):
        db = SessionLocal()
        try:
            out[name] = consult.settle(db, db.get(ConsultBooking, b["id"]), outcome, actor=f"{name}@example.com")[1]
        except Exception as exc:  # noqa: BLE001
            out[name] = exc
        finally:
            db.close()
            if name == "request-B":
                b_done.set()

    ta = threading.Thread(target=request, args=("request-A", "charge"), name="request-A")
    tb = threading.Thread(target=request, args=("request-B", "no_show"), name="request-B")
    ta.start()
    assert a_has_read.wait(15)
    tb.start()
    ta.join(30)
    tb.join(30)
    row = booking_row(b["ref"])
    taken = env.stripe.money_taken()
    print("\nsettlement:", row.settlement, "| due:", row.amount_due_cents, "| taken at Stripe:", taken, "| results:", out)
    assert taken in (fee, total), f"taken {taken}: the fee and the booked amount were both charged"
    assert taken == row.amount_due_cents == row.charged_cents


def test_f1_a_charge_for_money_the_hold_already_gave_is_refused_before_stripe_is_asked(client, env):
    """The second line of defence, on its own: whatever a caller believes,
    the charge primitive itself refuses an amount the decision no longer
    owes, and a charge for an outcome that is not the one in force."""
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=65))
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/charge", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["charged_cents"] == 33_300      # captured from the hold
    calls = len(env.stripe.calls)
    db = SessionLocal()
    again = money.charge_saved_card(db, db.get(ConsultBooking, b["id"]), 33_300, "meeting", actor="someone")
    other = money.charge_saved_card(db, db.get(ConsultBooking, b["id"]), 6_660, "no_show_fee", actor="someone")
    db.close()
    assert (again.ok, again.status, again.code) == (False, "error", "not_owed")
    assert (other.ok, other.status, other.code) == (False, "error", "decision_changed")
    assert len(env.stripe.calls) == calls and env.stripe.money_taken() == 33_300
    assert [(c.kind, c.status) for c in charges_of(b["id"])] == [("hold", "captured")]     # no ledger row either


# -----------------------------------------------------------------------------
# 2. The owner's button in a browser that is signed in to the admin
# -----------------------------------------------------------------------------

def _ended_call_with_links(client, env) -> tuple[dict, dict]:
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    tick(client)
    summary = [m for m in to(env.outbox, OWNER) if "confirm the outcome" in m["subject"]][-1]
    tokens = re.findall(r"/api/consult/decision\?token=([A-Za-z0-9_.\-]+)", summary["html"])
    assert len(tokens) == 3, tokens
    return b, {"charge": tokens[0], "no_show": tokens[1], "waive": tokens[2]}


@pytest.mark.parametrize("cookie", ["admin_session", "learner_session"])
def test_f2_the_decision_button_works_with_origin_null_and_a_session_cookie(client, env, cookie):
    from app.learner_auth import LEARNER_COOKIE_NAME
    from app.deps import SESSION_COOKIE_NAME

    b, links = _ended_call_with_links(client, env)
    url = f"{PUBLIC}/decision?token={links['waive']}"
    assert client.get(url).status_code == 200
    name = SESSION_COOKIE_NAME if cookie == "admin_session" else LEARNER_COOKIE_NAME
    r = client.post(url, headers={"Origin": "null"}, cookies={name: make_session_token(conftest.ADMIN_EMAIL)})
    row = booking_row(b["ref"])
    assert r.status_code == 200, "the owner's button was refused"
    assert (row.owner_choice, row.settlement, row.status) == ("waive", "waived", "completed")


def test_f2_the_guard_still_refuses_a_foreign_site_on_the_admin_api(client, env):
    b, links = _ended_call_with_links(client, env)
    cookies = {"admin_session": make_session_token(conftest.ADMIN_EMAIL)}
    for origin in ("https://evil.example", "null"):
        r = client.post(f"{ADMIN_API}/bookings/{b['id']}/charge", json={}, headers={"Origin": origin}, cookies=cookies)
        assert r.status_code == 403, origin
    assert booking_row(b["ref"]).settlement == ""


# -----------------------------------------------------------------------------
# 3. A request Stripe refuses as a request is not the client's card
# -----------------------------------------------------------------------------

def test_f3_the_off_session_request_names_cards_only(client, env):
    b = confirmed(client, env, TOMORROW, 60)                       # hold at card save
    hold = env.stripe.last("PaymentIntent.create")
    assert hold["payment_method_types"] == ["card"] and hold["capture_method"] == "manual"
    assert "automatic_payment_methods" not in hold and "return_url" not in hold
    c = confirmed(client, env, NEXT_WEEK, 60, email="later@example.com", ip="203.0.113.7")
    env.clock.set(NEXT_WEEK + timedelta(minutes=61))
    r = client.post(f"{ADMIN_API}/bookings/{c['id']}/charge", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["action"]["ok"], r.text
    charge = env.stripe.last("PaymentIntent.create")
    assert charge["payment_method_types"] == ["card"] and charge["capture_method"] == "automatic"
    assert b["id"] != c["id"]


def _view(client, ref: str, token: str) -> dict:
    return client.get(f"{PUBLIC}/booking/{ref}", params={"t": token}).json()


@pytest.mark.parametrize("refusal, words", [
    ("invalid", "The payment method does not belong to this customer."),
    ("bad_key", "Invalid API Key provided"),
    ("forbidden", "does not have the required permissions"),
])
def test_f3_a_request_stripe_refuses_is_never_blamed_on_the_card_and_never_cancels(client, env, refusal, words):
    start = ny(2031, 6, 2, 15)                                      # today, five hours ahead
    data = book(client, start, 60).json()
    ref, token = data["ref"], data["manage_token"]
    env.stripe.card = refusal
    assert save_card(client, env, ref).status_code == 200
    row = booking_row(ref)
    assert (row.status, row.hold_state) == ("confirmed", "")        # not 'failed': no card was refused
    (hold,) = charges_of(row.id)
    assert (hold.kind, hold.status, hold.error_code) == ("hold", "needs_review", "request_refused")
    assert "hold_request_refused" in events_of(row.id) and "hold_failed" not in events_of(row.id)
    # the client hears nothing about a card; the owner is told what it is, once
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call is confirmed ({ref})"]
    assert _view(client, ref, token)["card_problem"] is False
    alerts = [m for m in to(env.outbox, OWNER) if "Stripe refused" in m["subject"]]
    assert [m["subject"] for m in alerts] == ["[Consulting] Stripe refused the hold request (not the card): Casey Client"]
    assert words in alerts[0]["html"] and "the client has not been told anything" in alerts[0]["html"]
    assert not any("The hold on the card was refused" in s for s in subjects(env.outbox, OWNER))
    a = client.get(f"{ADMIN_API}/bookings/{row.id}", headers=ADMIN).json()
    assert [(x["kind"], x["reason"]) for x in a["needs_review"]] == [("hold", "hold")] and a["actions"]["can_review"]
    assert a["payment_state"] == "card_saved"

    # every tick up to the start: no second alert, nothing to the client, and no cancellation
    env.outbox.clear()
    at = env.clock()
    while at < start:
        at += timedelta(minutes=25)
        env.clock.set(min(at, start - timedelta(minutes=1)))
        tick(client)
    row = booking_row(ref)
    assert row.status == "confirmed", "a request error at Stripe cancelled the client's booking"
    assert [s for s in subjects(env.outbox, CLIENT) if "starts in about" not in s] == []
    assert [s for s in subjects(env.outbox, OWNER) if "Stripe refused" in s] == []
    assert env.stripe.count("PaymentIntent.create") == 1            # a refused request is not sent again by itself

    # after the call the charge is refused the same way: parked, the owner told once, the client not at all
    env.clock.set(start + timedelta(minutes=61))
    r = client.post(f"{ADMIN_API}/bookings/{row.id}/charge", headers=ADMIN, json={})
    assert r.status_code == 200
    assert r.json()["action"]["status"] == "needs_review" and r.json()["action"]["code"] == "request_refused"
    assert (r.json()["charge_state"], r.json()["payment_state"]) == ("review", "payment_failed")
    owner = [s for s in subjects(env.outbox, OWNER) if "Stripe refused" in s]
    assert owner == ["[Consulting] Charge for the call: Stripe refused the request (not the card): Casey Client"] \
        or (len(owner) == 1 and owner[0].endswith("Stripe refused the request (not the card): Casey Client"))
    view = _view(client, ref, token)
    assert view["card_problem"] is False and view["can_replace_card"] is False and view["charged_cents"] is None
    assert not any("Receipt" in s or "Action needed" in s for s in subjects(env.outbox, CLIENT))
    for _ in range(3):
        env.clock.advance(minutes=5)
        tick(client)
    assert len([s for s in subjects(env.outbox, OWNER) if "Stripe refused" in s]) == 1
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0

    # the cause is put right; he clears both attempts and charges
    env.stripe.card = "ok"
    a = client.get(f"{ADMIN_API}/bookings/{row.id}", headers=ADMIN).json()
    for parked in a["needs_review"]:
        r = client.post(f"{ADMIN_API}/bookings/{row.id}/review-not-charged", headers=ADMIN,
                        json={"charge_id": parked["charge_id"]})
        assert r.status_code == 200, r.text
    assert r.json()["charge_state"] == "open" and _view(client, ref, token)["card_problem"] is False
    r = client.post(f"{ADMIN_API}/bookings/{row.id}/charge", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["action"]["ok"] and r.json()["charge_state"] == "paid"
    assert env.stripe.money_taken() == booking_row(ref).total_cents
    assert len([s for s in subjects(env.outbox, CLIENT) if s.startswith("Receipt")]) == 1


def test_f3_a_passing_fault_at_stripe_is_asked_again_by_the_tick_with_the_same_key(client, env):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.outbox.clear()
    for fault in ("rate_limit", "network_before"):
        env.stripe.card = fault
        tick(client)
        row = booking_row(b["ref"])
        assert (row.status, row.hold_state) == ("confirmed", "") and charges_of(b["id"])[0].status == "pending"
        env.clock.advance(minutes=5)
    assert env.outbox == []                                          # nobody is told about a passing fault
    env.stripe.card = "ok"
    tick(client)
    assert booking_row(b["ref"]).hold_state == "authorized"
    keys = {kw["idempotency_key"] for n, kw in env.stripe.calls if n == "PaymentIntent.create"}
    assert env.stripe.count("PaymentIntent.create") == 3 and len(keys) == 1
    assert env.stripe.authorized() == booking_row(b["ref"]).total_cents


def test_f3_a_declined_card_is_still_a_declined_card(client, env):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=24))
    env.stripe.card = "declined"
    tick(client)
    row = booking_row(b["ref"])
    assert row.hold_state == "failed" and _view(client, b["ref"], b["token"])["card_problem"] is True
    assert any("Action needed" in s for s in subjects(env.outbox, CLIENT))


# -----------------------------------------------------------------------------
# 4. An earlier "card saved" event delivered again
# -----------------------------------------------------------------------------

def test_f4_a_redelivered_first_event_does_not_undo_a_card_replacement(client, env):
    b = confirmed(client, env, NEXT_WEEK)                            # session A, visa 4242
    row = booking_row(b["ref"])
    session_a, pm_a = row.stripe_checkout_session_id, row.stripe_payment_method_id
    event_a = env.stripe.card_saved_event(session_a)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    session_b = booking_row(b["ref"]).stripe_checkout_session_id
    assert session_b != session_a
    assert post_webhook(client, env, env.stripe.card_saved_event(session_b, brand="mastercard", last4="5555")).status_code == 200
    pm_b = booking_row(b["ref"]).stripe_payment_method_id
    assert pm_b != pm_a
    before = (events_of(b["id"]), len(env.outbox))
    assert post_webhook(client, env, event_a).status_code == 200    # Stripe delivers A again
    row = booking_row(b["ref"])
    assert (row.card_brand, row.card_last4, row.stripe_payment_method_id) == ("mastercard", "5555", pm_b), \
        "card reverted to the replaced one"
    assert (events_of(b["id"]), len(env.outbox)) == before           # a replay: nothing written, nothing sent
    env.clock.set(NEXT_WEEK - timedelta(hours=23, minutes=55))
    tick(client)
    assert env.stripe.last("PaymentIntent.create")["payment_method"] == pm_b, "the hold went to the replaced card"


# -----------------------------------------------------------------------------
# 5. Where the webhook's consulting work runs
# -----------------------------------------------------------------------------

def test_f5_the_webhook_does_the_consulting_work_off_the_event_loop(client, env, monkeypatch):
    where = {}

    def spy(name, real):
        def run(*a, **kw):
            try:
                asyncio.get_running_loop()
                where[name] = "event loop"
            except RuntimeError:
                where[name] = "worker thread"
            return real(*a, **kw)
        return run

    monkeypatch.setattr(consult, "on_checkout_completed", spy("card saved", consult.on_checkout_completed))
    monkeypatch.setattr(money, "note_stripe_refund", spy("refund", money.note_stripe_refund))
    monkeypatch.setattr(consult_auto, "note_dispute", spy("dispute", consult_auto.note_dispute))
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    assert client.post(f"{ADMIN_API}/bookings/{b['id']}/charge", headers=ADMIN, json={}).status_code == 200
    pi = charges_of(b["id"])[-1].stripe_payment_intent_id
    post_webhook(client, env, {"type": "charge.refunded", "data": {"object": {
        "id": "ch_1", "object": "charge", "payment_intent": pi, "amount_refunded": 0}}})
    post_webhook(client, env, {"type": "charge.dispute.created", "data": {"object": {
        "id": "dp_1", "object": "dispute", "payment_intent": pi, "amount": 100, "status": "needs_response"}}})
    assert where == {"card saved": "worker thread", "refund": "worker thread", "dispute": "worker thread"}


# -----------------------------------------------------------------------------
# 6. A hold whose answer was lost, on a booking that is then cancelled
# -----------------------------------------------------------------------------

def test_f6_a_hold_with_a_lost_answer_is_found_and_released_after_the_cancellation(client, env):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=23, minutes=58))
    env.stripe.card = "network_after"                # Stripe authorizes; the answer is lost
    tick(client)
    env.stripe.card = "ok"
    assert env.stripe.authorized() == booking_row(b["ref"]).total_cents
    env.clock.advance(minutes=1)
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    for _ in range(4):
        env.clock.advance(minutes=5)
        tick(client)
    assert env.stripe.authorized() == 0, "an authorization for the whole amount is still on the cancelled client's card"
    assert env.stripe.money_taken() == booking_row(b["ref"]).fee_cents      # the late-cancellation fee, once


# -----------------------------------------------------------------------------
# 7. A refund whose answer was lost
# -----------------------------------------------------------------------------

def test_f7_a_lost_refund_answer_never_becomes_a_second_refund(client, env):
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    assert client.post(f"{ADMIN_API}/bookings/{b['id']}/charge", headers=ADMIN, json={}).json()["action"]["ok"]
    env.stripe.refund_mode = "network_after"         # Stripe makes the refund; the answer is lost
    client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": 5000})
    assert env.stripe.money_returned() == 5000
    env.clock.advance(days=3)
    for _ in range(3):
        tick(client)
    env.stripe.idem.clear()                          # Stripe keeps a key for about 24 hours
    env.stripe.refund_mode = "ok"
    client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": 5000})
    assert env.stripe.money_returned() == 5000, "one $50 refund was asked for; the card got it twice"
    assert booking_row(b["ref"]).refunded_cents == 5000


# -----------------------------------------------------------------------------
# 8. The automatic outcome
# -----------------------------------------------------------------------------

def test_f8a_the_default_outcome_waits_for_the_summary_to_have_been_sent(client, env, monkeypatch):
    b = confirmed(client, env, TOMORROW, 60)         # Meet permission not granted: attendance is 'unknown'
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    env.clock.set(TOMORROW + timedelta(minutes=60))
    for _ in range(26):                              # every five minutes until ten minutes past the old deadline
        tick(client)
        env.clock.advance(minutes=5)
    row = booking_row(b["ref"])
    assert row.summary_sent_at is None and row.charged_cents == 0 and row.settlement == "", \
        "charged in full by default; the owner was never asked"
    assert env.stripe.money_taken() == 0


def test_f8b_the_owners_other_device_on_the_same_google_account_is_the_host(client, env):
    grant_meet_scope()
    b = confirmed(client, env, TOMORROW, 60)
    row = booking_row(b["ref"])
    end = TOMORROW + timedelta(minutes=60)
    env.google.conference(row.meet_url, TOMORROW, end,
                          ("host", "Bassam Abdelnabi", TOMORROW, end),
                          ("host", "Bassam Abdelnabi (phone)", TOMORROW + timedelta(minutes=2), end))
    env.clock.set(end + timedelta(minutes=1))
    tick(client)
    env.clock.set(end + timedelta(hours=2, minutes=2))
    tick(client)
    row = booking_row(b["ref"])
    assert row.attendance_state == "client_absent"
    assert row.charged_cents == row.fee_cents, "a client who did not join was charged the full amount"


# -----------------------------------------------------------------------------
# 9. The confirmation email
# -----------------------------------------------------------------------------

def test_f9_a_confirmation_email_that_failed_is_sent_by_the_tick(client, env, monkeypatch):
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    ref = book(client, NEXT_WEEK, 60).json()["ref"]
    assert save_card(client, env, ref).status_code == 200
    row = booking_row(ref)
    assert row.status == "confirmed" and row.confirmation_sent_at is None
    monkeypatch.setattr(E, "_resend_post", real)     # the email service is back a minute later
    for _ in range(3):
        env.clock.advance(minutes=5)
        tick(client)
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call is confirmed ({ref})"]
    assert len([s for s in subjects(env.outbox, OWNER) if "New booking" in s]) == 1
    assert booking_row(ref).confirmation_sent_at is not None


# -----------------------------------------------------------------------------
# 11. Tokens in the access log
# -----------------------------------------------------------------------------

def test_f11_the_access_log_carries_neither_the_manage_token_nor_a_decision_token(client, env):
    b, links = _ended_call_with_links(client, env)
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    keep = Keep()
    access = logging.getLogger("uvicorn.access")
    access.addHandler(keep)
    level = access.level
    access.setLevel(logging.INFO)
    try:
        # exactly what uvicorn's HTTP protocol classes log for a request
        for path in (f"/api/consult/booking/{b['ref']}?t={b['token']}",
                     f"/api/consult/decision?token={links['charge']}",
                     f"/api/consult/booking/{b['ref']}?tz=UTC&t={b['token']}&x=1"):
            access.info('%s - "%s %s HTTP/%s" %d', "203.0.113.9:51234", "GET", path, "1.1", 200)
    finally:
        access.removeHandler(keep)
        access.setLevel(level)
    assert len(lines) == 3 and all(f"/api/consult/" in line and "200" in line for line in lines)
    kept = "\n".join(lines)
    assert b["token"] not in kept and links["charge"] not in kept, "a token is in the server log"
    assert b["ref"] in kept and "tz=UTC" in kept and "x=1" in kept      # the rest of the line is kept


# -----------------------------------------------------------------------------
# 12. The daily cap
# -----------------------------------------------------------------------------

def test_f12_a_settled_call_still_counts_toward_the_daily_cap(client, env):
    assert client.put(f"{ADMIN_API}/settings", json={"max_per_day": 1}, headers=ADMIN).status_code == 200
    first = confirmed(client, env, ny(2031, 6, 2, 13), 30)            # today 13:00

    def today() -> list[str]:
        return [s for s in slot_starts(client) if s < "2031-06-03T04:00:00Z"]

    assert today() == []
    env.clock.set(ny(2031, 6, 2, 13, 35))
    r = client.post(f"{ADMIN_API}/bookings/{first['id']}/charge", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    assert today() == [], "the daily cap let the day reopen once the call was charged"
    second = book(client, ny(2031, 6, 2, 17), 30, email="second@example.com", ip="198.51.100.9")
    assert second.status_code == 409


# =============================================================================
# Beyond the proofs: the rest of each fix
# =============================================================================

def _owner(env, words: str) -> list[dict]:
    return [m for m in to(env.outbox, OWNER) if words in m["subject"]]


# ---- 4. card events in any order --------------------------------------------

def _two_card_pages(client, env) -> tuple[dict, str, str]:
    """A pending booking with two card pages open (the second from "Continue to card entry")."""
    data = book(client, NEXT_WEEK, 60).json()
    session_a = booking_row(data["ref"]).stripe_checkout_session_id
    r = client.post(f"{PUBLIC}/booking/{data['ref']}/card", json={"t": data["manage_token"]})
    assert r.status_code == 200, r.text
    session_b = booking_row(data["ref"]).stripe_checkout_session_id
    assert session_a != session_b
    return data, session_a, session_b


def test_f4_an_earlier_card_page_reported_late_does_not_replace_the_newer_card(client, env):
    data, session_a, session_b = _two_card_pages(client, env)
    event_a = env.stripe.card_saved_event(session_a)                 # finished first; Stripe is slow to say so
    env.clock.advance(minutes=1)
    event_b = env.stripe.card_saved_event(session_b, brand="mastercard", last4="5555")
    assert event_a["created"] < event_b["created"]
    assert post_webhook(client, env, event_b).status_code == 200
    row = booking_row(data["ref"])
    assert (row.status, row.card_last4) == ("confirmed", "5555")
    pm_b = row.stripe_payment_method_id
    mails = len(env.outbox)
    assert post_webhook(client, env, event_a).status_code == 200     # arrives for the first time, after B
    row = booking_row(data["ref"])
    assert (row.card_brand, row.card_last4, row.stripe_payment_method_id) == ("mastercard", "5555", pm_b)
    assert events_of(row.id).count("card_saved_ignored") == 1 and "card_replaced" not in events_of(row.id)
    assert len(env.outbox) == mails
    kinds = events_of(row.id)
    for _ in range(2):                                               # and again: a replay, nothing at all
        assert post_webhook(client, env, event_a).status_code == 200
        assert post_webhook(client, env, event_b).status_code == 200
    assert events_of(row.id) == kinds and len(env.outbox) == mails


def test_f4_the_card_page_finished_last_is_the_card_whichever_page_was_opened_first(client, env):
    data, session_a, session_b = _two_card_pages(client, env)
    event_b = env.stripe.card_saved_event(session_b, brand="mastercard", last4="5555")
    env.clock.advance(minutes=3)
    event_a = env.stripe.card_saved_event(session_a)                 # the older page, finished later
    for event in (event_b, event_a):
        assert post_webhook(client, env, event).status_code == 200
    row = booking_row(data["ref"])
    assert (row.status, row.card_brand, row.card_last4) == ("confirmed", "visa", "4242")
    assert events_of(row.id).count("card_replaced") == 1


def test_f4_a_card_event_for_a_closed_booking_is_remembered_too(client, env):
    b = confirmed(client, env, NEXT_WEEK)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]}).status_code == 200
    session_b = booking_row(b["ref"]).stripe_checkout_session_id
    client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    event_b = env.stripe.card_saved_event(session_b, last4="1881")
    for _ in range(3):
        assert post_webhook(client, env, event_b).status_code == 200
    assert events_of(b["id"]).count("card_saved_ignored") == 1      # once, however often it is delivered
    assert booking_row(b["ref"]).card_last4 == "4242"


# ---- 5. the answer to Stripe does not wait for the follow-up -----------------

def test_f5_what_follows_a_confirmation_runs_after_the_answer_and_the_tick_does_it_if_it_never_ran(
        client, env, monkeypatch):
    ran = []
    monkeypatch.setattr(consult, "finish_confirmation_later", lambda booking_id: ran.append(booking_id))
    data = book(client, TOMORROW, 60).json()                         # inside 24 h: a hold is due at once
    assert save_card(client, env, data["ref"]).status_code == 200
    row = booking_row(data["ref"])
    assert ran == [row.id]                                           # handed to a background task
    # the webhook itself only confirmed the booking: no email, no hold yet
    assert row.status == "confirmed" and row.hold_state == "" and row.confirmation_sent_at is None
    assert env.outbox == [] and env.stripe.count("PaymentIntent.create") == 0
    # the server stopped before that task ran: the tick does all of it
    env.clock.advance(minutes=5)
    tick(client)
    row = booking_row(data["ref"])
    assert row.hold_state == "authorized" and row.confirmation_sent_at and row.owner_notified_at
    assert subjects(env.outbox, CLIENT)[0] == f"Your consulting call is confirmed ({data['ref']})"
    assert len(_owner(env, "New booking")) == 1


# ---- 6. holds that were lost ---------------------------------------------------

def _lost_hold_then_cancelled(client, env, lost: str) -> dict:
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=25))                   # cancelling is still free
    db = SessionLocal()
    db.get(ConsultBooking, b["id"]).hold_due_at = env.clock()        # the hold falls due now
    db.commit()
    db.close()
    env.stripe.card = lost
    tick(client)
    env.stripe.card = "ok"
    assert charges_of(b["id"])[0].status == "pending"
    env.clock.advance(minutes=1)
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]}).json()["status"] == "cancelled"
    env.outbox.clear()
    return b


def test_f6_a_lost_hold_that_never_reached_stripe_is_closed_quietly(client, env):
    b = _lost_hold_then_cancelled(client, env, "network_before")
    env.clock.advance(minutes=5)
    assert "lost_hold:cleared" not in tick(client)["done"]           # too soon to believe "Stripe has nothing"
    assert charges_of(b["id"])[0].status == "pending"
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["lost_hold:cleared"] == 1
    hold = charges_of(b["id"])[0]
    assert (hold.status, hold.error_code) == ("failed", "never_placed")
    assert "hold_not_placed" in events_of(b["id"]) and env.outbox == []
    assert tick(client)["done"] == {}                                # and that is the end of it


def test_f6_when_stripe_cannot_confirm_the_release_the_owner_is_told_once_and_it_is_still_released(client, env):
    b = _lost_hold_then_cancelled(client, env, "network_after")
    assert env.stripe.authorized() == 11_100
    env.stripe.list_fails = True                                     # Stripe cannot be asked
    env.clock.advance(hours=19)
    tick(client)
    assert env.outbox == [] and charges_of(b["id"])[0].status == "pending"
    env.clock.advance(hours=1, minutes=5)                            # twenty hours and more
    assert tick(client)["done"]["lost_hold:parked"] == 1
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] A hold may still be on the client's card: Casey Client"
    assert "cancel it there if it exists" in alert["html"] and b["ref"] in alert["html"]
    assert to(env.outbox, CLIENT) == []
    for _ in range(3):
        env.clock.advance(minutes=5)
        tick(client)
    assert len(to(env.outbox, OWNER)) == 1 and env.stripe.authorized() == 11_100
    env.stripe.list_fails = False                                    # Stripe answers again
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["lost_hold:released"] == 1
    assert env.stripe.authorized() == 0 and env.stripe.money_taken() == 0
    assert charges_of(b["id"])[0].status == "released"
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    assert a["needs_review"] == [] and a["actions"]["can_review"] is False


def test_f6_a_lost_hold_is_released_when_the_owner_cancels_the_call(client, env):
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(hours=3))
    db = SessionLocal()
    db.get(ConsultBooking, b["id"]).hold_due_at = env.clock()
    db.commit()
    db.close()
    env.stripe.card = "network_after"
    tick(client)
    env.stripe.card = "ok"
    assert env.stripe.authorized() == 11_100 and charges_of(b["id"])[0].status == "pending"
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/cancel", headers=ADMIN, json={"note": "I am ill."})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["lost_hold:released"] == 1
    assert env.stripe.authorized() == 0 and env.stripe.money_taken() == 0
    assert "hold_released" in events_of(b["id"])


def test_f6_a_call_cannot_be_settled_past_a_hold_whose_answer_is_unknown(client, env):
    """The other way a hold could be left behind: deciding the outcome while
    the hold's answer is still unknown. That is refused; the next tick asks
    Stripe with the same key, finds the hold, and the outcome then uses it."""
    b = confirmed(client, env, NEXT_WEEK, 60)
    env.clock.set(NEXT_WEEK - timedelta(minutes=30))
    db = SessionLocal()
    db.get(ConsultBooking, b["id"]).hold_due_at = env.clock()
    db.commit()
    db.close()
    env.stripe.card = "network_after"
    tick(client)
    env.stripe.card = "ok"
    env.clock.set(NEXT_WEEK + timedelta(minutes=61))
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/waive", headers=ADMIN, json={})
    assert r.status_code == 409 and "still being confirmed" in r.json()["detail"]
    tick(client)                                                     # asks about the hold again: it is there
    assert booking_row(b["ref"]).hold_state == "authorized"
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/waive", headers=ADMIN, json={})
    assert r.status_code == 200 and env.stripe.authorized() == 0 and env.stripe.money_taken() == 0


def test_f6_a_release_stripe_never_confirms_is_reported_to_the_owner_once(client, env):
    b = confirmed(client, env, TOMORROW, 60)                         # hold authorized at card save
    env.clock.set(TOMORROW + timedelta(minutes=61))
    env.stripe.cancel_fails = True
    assert client.post(f"{ADMIN_API}/bookings/{b['id']}/waive", headers=ADMIN, json={}).status_code == 200
    env.outbox.clear()
    for _ in range(12):
        env.clock.advance(minutes=5)
        tick(client)
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] A hold could not be released: Casey Client"
    assert "$333" in alert["html"] and "lapses by itself within about a week" in alert["html"]   # tomorrow's rate
    assert events_of(b["id"]).count("hold_release_unconfirmed") == 1 and to(env.outbox, CLIENT) == []


# ---- 7. refunds ------------------------------------------------------------------

def _charged(client, env) -> dict:
    b = confirmed(client, env, TOMORROW, 60)
    env.clock.set(TOMORROW + timedelta(minutes=61))
    assert client.post(f"{ADMIN_API}/bookings/{b['id']}/charge", headers=ADMIN, json={}).json()["action"]["ok"]
    env.outbox.clear()
    return b


def _refund(client, b: dict, cents: int):
    return client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": cents})


def test_f7_the_tick_finds_a_refund_whose_answer_was_lost_and_a_repeat_is_answered_not_sent(client, env):
    b = _charged(client, env)
    env.stripe.refund_mode = "network_after"
    r = _refund(client, b, 5_000)
    assert r.json()["action"]["ok"] is False and r.json()["refunded_cents"] == 0
    env.stripe.refund_mode = "ok"
    env.clock.advance(minutes=1)
    assert "refund:refunded" not in tick(client)["done"]             # the request may still be on its way
    env.clock.advance(minutes=4)
    assert tick(client)["done"]["refund:refunded"] == 1
    row = booking_row(b["ref"])
    assert row.refunded_cents == 5_000 and env.stripe.count("Refund.create") == 1
    (told,) = to(env.outbox, OWNER)
    assert "Refund" in told["subject"] and "$50" in told["subject"]
    # days later he asks for the same $50 again: answered once with what happened, nothing sent
    env.clock.advance(days=3)
    env.stripe.idem.clear()
    r = _refund(client, b, 5_000)
    assert r.status_code == 200 and r.json()["action"]["status"] == "noop"
    assert "was already made" in r.json()["action"]["message"] and r.json()["refunded_cents"] == 5_000
    assert env.stripe.money_returned() == 5_000 and env.stripe.count("Refund.create") == 1
    # asked once more, it is a new refund
    r = _refund(client, b, 5_000)
    assert r.json()["action"]["ok"] is True and r.json()["refunded_cents"] == 10_000
    assert env.stripe.money_returned() == 10_000


def test_f7_a_refund_that_never_reached_stripe_is_not_sent_after_its_key_is_too_old(client, env):
    b = _charged(client, env)
    env.stripe.refund_mode = "network_before"
    _refund(client, b, 5_000)
    env.stripe.refund_mode = "ok"
    env.clock.advance(hours=21)                                      # the tick was down; the key may be forgotten
    env.stripe.idem.clear()
    assert tick(client)["done"]["refund:not_made"] == 1
    (row,) = [c for c in charges_of(b["id"]) if c.kind == "refund"]
    assert (row.status, row.error_code) == ("failed", "not_made")
    assert env.stripe.count("Refund.create") == 1 and env.stripe.money_returned() == 0
    (told,) = to(env.outbox, OWNER)
    assert told["subject"] == "[Consulting] Refund: NOT made: Casey Client"
    assert "Nothing was returned to the card" in told["html"]
    # a new press is a new refund, under a new key
    assert _refund(client, b, 5_000).json()["refunded_cents"] == 5_000
    keys = [kw["idempotency_key"] for n, kw in env.stripe.calls if n == "Refund.create"]
    assert len(keys) == 2 and keys[0] != keys[1] and env.stripe.money_returned() == 5_000


def test_f7_while_stripe_cannot_be_asked_nothing_is_sent_and_after_a_day_the_owner_is_told(client, env):
    b = _charged(client, env)
    env.stripe.refund_mode = "network_after"                         # made at Stripe; the answer is lost
    _refund(client, b, 5_000)
    env.stripe.refund_mode = "ok"
    env.stripe.list_fails = True
    env.clock.advance(hours=21)
    env.stripe.idem.clear()
    assert tick(client)["done"]["refund:parked"] == 1
    (row,) = [c for c in charges_of(b["id"]) if c.kind == "refund"]
    assert row.status == "needs_review"
    (told,) = to(env.outbox, OWNER)
    assert told["subject"] == "[Consulting] A refund needs checking in Stripe: Casey Client"
    # pressing Refund now sends nothing either
    r = _refund(client, b, 5_000)
    assert r.json()["action"]["ok"] is False and env.stripe.count("Refund.create") == 1
    for _ in range(3):
        env.clock.advance(minutes=5)
        tick(client)
    assert len(to(env.outbox, OWNER)) == 1 and env.stripe.money_returned() == 5_000
    env.stripe.list_fails = False
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["refund:refunded"] == 1
    assert booking_row(b["ref"]).refunded_cents == 5_000 and env.stripe.count("Refund.create") == 1


def test_f7_a_refund_stripe_reports_as_pending_is_not_money_returned_until_stripe_says_so(client, env):
    b = _charged(client, env)
    env.stripe.refund_status = "pending"
    r = _refund(client, b, 5_000)
    assert r.json()["action"]["ok"] is False and r.json()["action"]["code"] == "refund_pending"
    assert r.json()["refunded_cents"] == 0
    (refund,) = env.stripe.refunds.values()
    env.clock.advance(minutes=5)
    assert "refund:refunded" not in tick(client)["done"]
    refund["status"] = "failed"                                      # the bank sent it back
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["refund:not_made"] == 1
    assert booking_row(b["ref"]).refunded_cents == 0
    assert _owner(env, "Refund: NOT made")
    # a second one that completes is recorded when it does
    env.stripe.refund_status = "pending"
    _refund(client, b, 2_000)
    list(env.stripe.refunds.values())[-1]["status"] = "succeeded"
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["refund:refunded"] == 1
    assert booking_row(b["ref"]).refunded_cents == 2_000 and env.stripe.count("Refund.create") == 2


# ---- 8. the summary and who counts ---------------------------------------------

def test_f8a_once_the_summary_gets_through_his_time_to_choose_counts_from_then(client, env, monkeypatch):
    b = confirmed(client, env, TOMORROW, 60)
    end = TOMORROW + timedelta(minutes=60)
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    env.clock.set(end)
    for _ in range(36):                                              # three hours of refusals
        tick(client)
        env.clock.advance(minutes=5)
    status = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert status["summaries_unsent"] == 1 and "has not accepted the summary email yet" in status["summaries_unsent_note"]
    assert booking_row(b["ref"]).settlement == "" and env.stripe.money_taken() == 0
    monkeypatch.setattr(E, "_resend_post", real)
    # after a dozen refusals the summary is tried once an hour (review 2): it goes out with the next such try
    sent_at = None
    for _ in range(12):
        if tick(client)["done"].get("summary") == 1:
            sent_at = env.clock()
            break
        env.clock.advance(minutes=5)
    assert sent_at is not None, "the summary did not go out within an hour of the email service coming back"
    (mail,) = _owner(env, "confirm the outcome")
    row = booking_row(b["ref"])
    assert money.aware(row.settle_due_at) == sent_at + timedelta(hours=2)
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["summaries_unsent"] == 0
    env.clock.set(sent_at + timedelta(hours=1, minutes=59))
    assert tick(client)["done"] == {} and env.stripe.money_taken() == 0
    env.clock.set(sent_at + timedelta(hours=2))
    assert tick(client)["done"]["settled:charge"] == 1
    assert env.stripe.money_taken() == booking_row(b["ref"]).total_cents


def test_f8b_someone_who_was_not_in_the_call_together_with_the_host_is_not_the_client(client, env):
    grant_meet_scope()
    b = confirmed(client, env, TOMORROW, 60)
    row = booking_row(b["ref"])
    end = TOMORROW + timedelta(minutes=60)
    m = lambda n: TOMORROW + timedelta(minutes=n)  # noqa: E731
    env.google.conference(row.meet_url, TOMORROW, end,
                          ("host", "Bassam Abdelnabi", m(0), m(20)),
                          ("guest", "Passing By", m(17), m(21)),            # three minutes together
                          ("118000000000000000009", "Late Arrival", m(40), m(55)))   # after the host had left
    env.clock.set(end)
    tick(client)
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()["attendance"]
    assert (a["state"], a["host_joined"], a["others_joined"]) == ("client_absent", True, 0)
    assert "none of them together with you for at least 5 minutes" in a["note"]
    assert any("Passing By" in p and "not counted as the client" in p for p in a["participants"])
    assert any("Late Arrival" in p and "0 min in the call with you: not counted" in p for p in a["participants"])
    (summary,) = _owner(env, "confirm the outcome")
    assert "Passing By" in summary["html"] and "Late Arrival" in summary["html"]      # every name is listed
    env.clock.set(end + timedelta(hours=2))
    tick(client)
    row = booking_row(b["ref"])
    assert (row.settlement, row.charged_cents) == ("no_show", row.fee_cents)


def test_f8b_five_minutes_together_is_enough_and_time_is_added_up_across_reconnects(client, env):
    grant_meet_scope()
    b = confirmed(client, env, TOMORROW, 60)
    row = booking_row(b["ref"])
    m = lambda n: TOMORROW + timedelta(minutes=n)  # noqa: E731
    dana = "118000000000000000009"                                   # signed in: the same person in both records
    env.google.conference(row.meet_url, TOMORROW, m(10),
                          ("host", "Bassam Abdelnabi", m(0), m(10)), (dana, "Dana Client", m(7), m(10)),
                          ("guest", "Phone in a pocket", m(8), m(10)))
    env.google.conference(row.meet_url, m(12), m(30),               # the call dropped and was started again
                          ("host", "Bassam Abdelnabi", m(12), m(30)), (dana, "Dana Client", m(12), m(15)),
                          ("guest", "Phone in a pocket", m(12), m(14)))
    env.clock.set(TOMORROW + timedelta(minutes=60))
    tick(client)
    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()["attendance"]
    # Dana: three minutes and three minutes. The guest: two and two, and a guest
    # has no identity that carries from one conference record to the next.
    assert (a["state"], a["others_joined"]) == ("both", 1)
    assert any("Dana Client" in p and "(5 min in the call with you)" in p for p in a["participants"]) \
        or any("Dana Client" in p and "(6 min in the call with you)" in p for p in a["participants"])
    assert sum("not counted as the client" in p for p in a["participants"]) == 2


def test_f8b_the_overlap_is_measured_on_merged_spans():
    from datetime import datetime, timezone

    t = lambda n: datetime(2031, 6, 3, 14, 0, tzinfo=timezone.utc) + timedelta(minutes=n)  # noqa: E731
    together = consult_auto._together
    assert together([(t(0), t(10))], [(t(5), t(20))]) == timedelta(minutes=5)
    assert together([(t(0), t(10))], [(t(10), t(20))]) == timedelta(0)
    assert together([(t(0), t(10)), (t(5), t(15))], [(t(0), t(30))]) == timedelta(minutes=15)   # not counted twice
    assert together([(t(0), t(4)), (t(6), t(9))], [(t(0), t(3)), (t(2), t(8))]) == timedelta(minutes=6)
    assert together([], [(t(0), t(30))]) == timedelta(0) and together([(t(5), t(5))], [(t(0), t(30))]) == timedelta(0)
    assert consult_auto.CLIENT_MIN_OVERLAP == timedelta(minutes=5)


def test_f8b_a_different_google_account_cannot_be_told_from_a_client_and_the_summary_says_so(client, env):
    """The reviewer's second scenario exactly: the owner's phone on his
    PERSONAL Google account is in the call for the whole hour and the client
    never joins. Meet gives no email address, so the site cannot know this is
    not the client: it still reads 'both joined'. What the fix adds is in the
    summary: every participant by name, and the sentence that says to check."""
    grant_meet_scope()
    b = confirmed(client, env, TOMORROW, 60)
    row = booking_row(b["ref"])
    end = TOMORROW + timedelta(minutes=60)
    env.google.conference(row.meet_url, TOMORROW, end,
                          ("host", "Bassam Abdelnabi", TOMORROW, end),
                          ("104999999999999999999", "Bassam (phone, personal account)", TOMORROW, end))
    env.clock.set(end)
    tick(client)
    assert booking_row(b["ref"]).attendance_state == "both"          # not detectable
    (summary,) = _owner(env, "confirm the outcome")
    assert "Bassam (phone, personal account)" in summary["html"]
    assert "Check the names" in summary["html"]
    assert "a second Google account of your own, looks the same to the site" in summary["html"]
    # and he can say so with one press, in a signed-in browser too (finding 2)
    link = re.findall(r"/api/consult/decision\?token=([A-Za-z0-9_.\-]+)", summary["html"])[1]     # no-show
    r = client.post(f"{PUBLIC}/decision?token={link}", headers={"Origin": "null"},
                    cookies={"admin_session": make_session_token(conftest.ADMIN_EMAIL)})
    assert r.status_code == 200
    row = booking_row(b["ref"])
    assert (row.settlement, row.charged_cents) == ("no_show", row.fee_cents)


# ---- 9. the confirmation, each half on its own -----------------------------------

def test_f9_only_the_email_that_failed_is_sent_again_and_never_twice(client, env, monkeypatch):
    real = E._resend_post

    def owner_only_fails(url, payload, key):
        if OWNER in payload["to"]:
            return _Down()
        return real(url, payload, key)

    monkeypatch.setattr(E, "_resend_post", owner_only_fails)
    b = confirmed(client, env, NEXT_WEEK, 60)
    row = booking_row(b["ref"])
    assert row.confirmation_sent_at is not None and row.owner_notified_at is None
    assert len(to(env.outbox, CLIENT)) == 1 and to(env.outbox, OWNER) == []
    monkeypatch.setattr(E, "_resend_post", real)
    env.clock.advance(minutes=1)
    assert "confirmation" not in tick(client)["done"]                # the first two minutes belong to the webhook
    for _ in range(6):
        env.clock.advance(minutes=5)
        tick(client)
    assert len(to(env.outbox, CLIENT)) == 1 and len(_owner(env, "New booking")) == 1
    assert booking_row(b["ref"]).owner_notified_at is not None


def test_f9_four_senders_at_once_send_each_confirmation_email_once(client, env, monkeypatch):
    """The webhook's follow-up and the tick can reach the same booking at the
    same moment: each email goes to whoever claims its marker."""
    monkeypatch.setattr(consult, "finish_confirmation_later", lambda booking_id: None)   # nothing sent yet
    data = book(client, NEXT_WEEK, 60).json()
    assert save_card(client, env, data["ref"]).status_code == 200
    booking_id = booking_row(data["ref"]).id
    assert env.outbox == []
    go = threading.Barrier(4)

    def send():
        db = SessionLocal()
        try:
            go.wait(10)
            consult.send_confirmation(db, booking_id)
        finally:
            db.close()

    threads = [threading.Thread(target=send) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert len(to(env.outbox, CLIENT)) == 1 and len(_owner(env, "New booking")) == 1


def test_f9_a_confirmation_is_not_sent_after_the_call_has_started_or_was_cancelled(client, env, monkeypatch):
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    first = book(client, NEXT_WEEK, 60).json()["ref"]
    second = book(client, NEXT_WEEK + timedelta(days=1), 60, email="second@example.com", ip="203.0.113.9").json()
    assert save_card(client, env, first).status_code == 200
    assert save_card(client, env, second["ref"]).status_code == 200
    client.post(f"{PUBLIC}/booking/{second['ref']}/cancel", json={"t": second["manage_token"]})
    monkeypatch.setattr(E, "_resend_post", real)
    env.outbox.clear()
    env.clock.set(NEXT_WEEK + timedelta(minutes=1))                  # the tick comes back after the first call began
    tick(client)
    assert not any("is confirmed" in m["subject"] for m in env.outbox)


# ---- 10. whose address, and how much of the calendar a stranger can hold ---------

def test_f10_the_address_the_edge_reports_is_the_one_that_counts(client, env):
    codes = [
        get_quote(client, NEXT_WEEK, 60, headers={
            "CF-Connecting-IP": "203.0.113.5", "X-Forwarded-For": f"198.51.100.{i}"}).status_code
        for i in range(41)
    ]
    assert codes[:40] == [200] * 40 and codes[40] == 429             # a new X-Forwarded-For each time did not help
    assert get_quote(client, NEXT_WEEK, 60, headers={"CF-Connecting-IP": "203.0.113.6"}).status_code == 200
    # the consent record keeps that address too
    r = client.post(f"{PUBLIC}/book", headers={"CF-Connecting-IP": "203.0.113.77", "X-Forwarded-For": "10.9.8.7"}, json={
        "start": NEXT_WEEK.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes": 60, "full_name": "Casey Client",
        "email": CLIENT, "topic": "A question about a combustor.", "timezone": "Europe/London",
        "terms_version": get_quote(client, NEXT_WEEK, 60, headers={"CF-Connecting-IP": "203.0.113.77"}).json()["terms_version"],
        "agree": True, "website": "",
    })
    assert r.status_code == 200, r.text
    assert booking_row(r.json()["ref"]).consent_ip == "203.0.113.77"


def test_f10_without_that_header_the_existing_rule_applies(client, env):
    codes = [get_quote(client, NEXT_WEEK, 60, headers={"X-Forwarded-For": "203.0.113.5"}).status_code for _ in range(41)]
    assert codes[-1] == 429
    assert get_quote(client, NEXT_WEEK, 60, headers={"X-Forwarded-For": "203.0.113.6"}).status_code == 200


def test_f10_a_stranger_can_hold_three_times_for_fifteen_minutes_and_no_more(client, env):
    """New address, new email every time. Before the first review: eight
    free holds, renewed every 20 minutes, kept two days closed. Now three
    reservations at once is all there is, each for 15 minutes; they do not
    count toward the day's cap, and a fourth booking ends the oldest of them
    (review 2, N3) instead of being refused."""
    settings = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert settings["pending_hold_minutes"] == 15 and settings["max_per_day"] == 4
    today = [ny(2031, 6, 2, h) for h in (15, 17, 19, 21)]
    made = []
    for i, at in enumerate(today):
        r = book(client, at, 30, email=f"s{i}@example.com", ip=f"192.0.2.{i}")
        assert r.status_code == 200, r.text
        made.append(r.json()["ref"])
        env.clock.advance(seconds=10)
    assert [booking_row(ref).status for ref in made] == ["expired", "pending_card", "pending_card", "pending_card"]
    open_today = [s for s in slot_starts(client) if s < "2031-06-03T04:00:00Z"]
    assert "2031-06-02T19:00:00Z" in open_today                       # 15:00 New York: the first one's time is free again
    # a real client books that time and saves a card: it is theirs
    real = book(client, today[0], 30, email="real@example.com", ip="192.0.2.50")
    assert real.status_code == 200 and save_card(client, env, real.json()["ref"]).status_code == 200
    assert booking_row(real.json()["ref"]).status == "confirmed"


# ---- 14. when the automation stops -------------------------------------------------

@pytest.fixture()
def watch(monkeypatch):
    monkeypatch.setattr(consult_routes, "TICK_WATCH_SECONDS", 0)
    monkeypatch.setattr(consult_routes, "_last_watch", [-1.0])


def _stopped(env) -> list[dict]:
    return _owner(env, "The automation has stopped")


def test_f14_the_owner_is_told_once_a_day_that_the_tick_has_stopped(client, env, watch):
    b = confirmed(client, env, TOMORROW, 60)                         # starts within 48 hours
    assert _stopped(env) == []                                       # nobody has asked the site anything since
    assert client.get(f"{PUBLIC}/availability").status_code == 200
    (mail,) = _stopped(env)                                          # no tick has ever run
    assert "has never run" in mail["html"] and "Casey Client" in mail["html"]
    assert "no hold on the card, no reminder to the client" in mail["html"]
    for _ in range(5):                                               # every request looks; one email a day
        env.clock.advance(minutes=30)
        assert client.get(f"{PUBLIC}/availability").status_code == 200
        assert client.get(f"{ADMIN_API}/status", headers=ADMIN).status_code == 200
    assert len(_stopped(env)) == 1
    env.clock.set(NOW + timedelta(days=1, minutes=1))                # still stopped a day later, a call still ahead
    c = confirmed(client, env, NOW + timedelta(days=2), 60, email="next@example.com", ip="203.0.113.4")
    client.get(f"{ADMIN_API}/bookings/{c['id']}", headers=ADMIN)
    assert len(_stopped(env)) == 2
    assert b["id"] != c["id"]


def test_f14_a_running_tick_or_no_call_within_two_days_means_no_email(client, env, watch):
    confirmed(client, env, NEXT_WEEK, 60)                            # eight days ahead
    client.get(f"{PUBLIC}/availability")
    assert _stopped(env) == []
    confirmed(client, env, TOMORROW, 60, email="soon@example.com", ip="203.0.113.4")
    env.outbox.clear()
    tick(client)                                                     # the tick itself is not what raises the alarm
    assert _stopped(env) == []
    env.clock.advance(minutes=29)
    client.get(f"{PUBLIC}/availability")
    assert _stopped(env) == []                                       # it ran 29 minutes ago
    env.clock.advance(minutes=2)
    client.get(f"{ADMIN_API}/bookings", headers=ADMIN)
    (mail,) = _stopped(env)
    assert "has not completed a run since" in mail["html"]


def test_f14_an_alert_that_could_not_be_sent_is_tried_again_by_the_next_request(client, env, watch, monkeypatch):
    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: _Down())
    confirmed(client, env, TOMORROW, 60)
    assert _stopped(env) == []
    monkeypatch.setattr(E, "_resend_post", real)
    client.get(f"{PUBLIC}/availability")
    assert len(_stopped(env)) == 1


def test_f14_the_watch_is_looked_at_once_a_minute_at_most(client, env, monkeypatch):
    looks = []
    monkeypatch.setattr(consult, "watch_tick_later", lambda: looks.append(1))
    monkeypatch.setattr(consult_routes, "TICK_WATCH_SECONDS", 60.0)
    monkeypatch.setattr(consult_routes, "_last_watch", [-1e9])
    for _ in range(5):
        client.get(f"{PUBLIC}/availability")
    assert looks == [1]
    client.post(f"{ADMIN_API}/tick", headers=ADMIN)
    assert looks == [1]
