"""Consulting calls: a payment attempt parked as "needs review", closed by the owner.

A request went to Stripe, no answer ever came back, and by the time anyone
could ask again the idempotency key was too old to repeat safely. The
attempt is parked: the site does not know whether the card was charged. The
owner looks in Stripe and tells the site which it was, from the booking in
the admin:

  POST /api/admin/consult/bookings/{id}/review-settled      {cents, charge_id?}
       "Paid in Stripe": the payment is there. The site asks Stripe for a
       completed payment of exactly that amount made by that very attempt,
       and only then records it. The client gets their receipt.
  POST /api/admin/consult/bookings/{id}/review-not-charged  {charge_id?}
       "Not charged": Stripe has no such payment. The site asks Stripe to
       confirm that nothing was taken or is held for that attempt, and only
       then closes it, so that Charge can be pressed again.

Neither moves money. What the owner says is never taken on trust: a wrong
"paid" would leave a debt written off, and a wrong "not charged" followed by
Charge would take the money twice. FakeStripe.money_taken() is what cards
were really charged.
"""
from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    OWNER,
    PUBLIC,
    Obj,
    booking_row,
    charges_of,
    client,
    confirmed,
    env,
    events_of,
    iso,
    ny,
    state_of_everything,
    subjects,
    tick,
    to,
    world,
)

from app import consult
from app import consult_money as money
from app.consult_models import ConsultBooking
from app.db import SessionLocal

START = ny(2031, 6, 11, 10)                 # Wednesday 10:00 New York
END = START + timedelta(hours=1)
DUE = END + timedelta(hours=2)              # when the automatic outcome runs
HOLD_AT = START - timedelta(hours=24)
CLIENT = "client@example.com"
NOTHING = "Nothing on this booking is waiting to be checked in Stripe."


def _admin(client, b: dict, action: str, body: dict | None = None):
    return client.post(f"{ADMIN_API}/bookings/{b['id']}/{action}", headers=ADMIN, json=body or {})


def _a(client, b: dict) -> dict:
    return client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()


def _parked_charge(client, env, lost: str, **kw) -> dict:
    """A call that took place, whose automatic charge of $111 got no answer,
    with the tick then down for 21 hours: the attempt is parked.

    lost='network_after':  Stripe did take the money; only the answer was lost.
    lost='network_before': the request never reached Stripe; nothing was taken."""
    b = confirmed(client, env, START, **kw)
    env.clock.set(END)
    tick(client)
    env.clock.set(DUE)
    env.stripe.card = lost
    tick(client)
    assert booking_row(b["ref"]).charge_state == "pending"
    env.stripe.card = "ok"
    env.clock.advance(hours=21)
    tick(client)
    (row,) = [c for c in charges_of(b["id"]) if c.status == "needs_review"]
    assert (row.kind, row.reason, row.amount_cents) == ("charge", "meeting", 11_100)
    assert env.stripe.money_taken() == (11_100 if lost == "network_after" else 0)
    env.outbox.clear()
    b["row"] = row.id
    return b


def _parked_hold(client, env, lost: str) -> dict:
    """A confirmed call whose hold got no answer the day before, parked
    three hours before the start."""
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = lost
    tick(client)
    env.stripe.card = "ok"
    env.clock.set(START - timedelta(hours=3))
    tick(client)
    (row,) = charges_of(b["id"])
    assert (row.kind, row.status) == ("hold", "needs_review") and booking_row(b["ref"]).hold_state == ""
    env.outbox.clear()
    b["row"] = row.id
    return b


def _stripe_payment(env, b: dict, *, ledger_id, status: str = "succeeded", amount: int = 11_100,
                    received: int | None = None, customer: str | None = None) -> Obj:
    """A payment as Stripe would list it, put there by the test."""
    pid = env.stripe._id("pi")
    env.stripe.payment_intents[pid] = Obj(
        id=pid, amount=amount, currency="usd",
        customer=customer or booking_row(b["ref"]).stripe_customer_id, payment_method="pm_x",
        capture_method="automatic", metadata={"ledger_id": str(ledger_id)} if ledger_id is not None else {},
        amount_received=(amount if status == "succeeded" else 0) if received is None else received,
        refunded=0, status=status, created=int(DUE.timestamp()),
    )
    return env.stripe.payment_intents[pid]


def _lines(client, b: dict, kind: str) -> list[dict]:
    return [e for e in _a(client, b)["events"] if e["kind"] == kind]


# -----------------------------------------------------------------------------
# What the admin is shown
# -----------------------------------------------------------------------------

def test_a_parked_charge_is_listed_on_the_booking_with_what_can_be_done(client, env):
    b = _parked_charge(client, env, "network_before")
    a = _a(client, b)
    assert a["needs_review"] == [{
        "charge_id": b["row"], "kind": "charge", "reason": "meeting", "amount_cents": 11_100,
        "created_at": iso(DUE),
    }]
    assert a["actions"]["can_review"] is True
    # 'review', not 'failed': no card was refused, and the client's page shows no card problem
    assert (a["charge_state"], a["charged_cents"], a["settlement"]) == ("review", None, "charged")
    assert a["payment_state"] == "payment_failed"
    assert client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()["card_problem"] is False
    # a booking with nothing parked says so
    other = confirmed(client, env, ny(2031, 6, 16, 10), email="other@example.com", ip="203.0.113.5")
    a = _a(client, other)
    assert a["needs_review"] == [] and a["actions"]["can_review"] is False


def test_pressing_charge_on_a_parked_attempt_sends_nothing_to_the_card_and_says_why(client, env):
    b = _parked_charge(client, env, "network_after")
    before = state_of_everything(env)
    r = _admin(client, b, "charge")
    assert r.status_code == 200
    assert r.json()["action"] == {
        "ok": False, "status": "needs_review", "amount_cents": 0, "code": "needs_review",
        "message": "An earlier attempt has an unknown outcome. Check it in Stripe before trying again.",
    }
    assert r.json()["actions"]["can_review"] is True
    assert state_of_everything(env)[2:5] == before[2:5]            # the ledger, the emails, the calls to Stripe
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 11_100
    assert booking_row(b["ref"]).charge_state == "review"


def test_a_notice_about_a_parked_attempt_does_not_claim_that_nothing_was_taken(client, env):
    b = _parked_charge(client, env, "network_after")
    db = SessionLocal()
    consult.notify_owner_payment(
        db, db.get(ConsultBooking, b["id"]),
        money.PayResult(False, "needs_review", code="needs_review"), what="Charge")
    db.close()
    (mail,) = to(env.outbox, OWNER)
    assert mail["subject"] == "[Consulting] Charge: an earlier attempt needs checking in Stripe: Casey Client"
    assert "it is not known whether the card was charged" in mail["html"]
    assert "Nothing was taken" not in mail["html"]                 # that is exactly what is not known
    assert "&quot;Paid in Stripe&quot; or &quot;Not charged&quot;" in mail["html"]


# -----------------------------------------------------------------------------
# "Paid in Stripe"
# -----------------------------------------------------------------------------

def test_paid_in_stripe_records_the_payment_and_takes_nothing(client, env):
    b = _parked_charge(client, env, "network_after")
    (pi,) = env.stripe.payment_intents.values()
    env.clock.advance(hours=5)                                     # he gets to it on Thursday evening
    r = _admin(client, b, "review-settled", {"cents": 11_100})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["action"] == {
        "ok": True, "status": "succeeded", "amount_cents": 11_100, "code": "",
        "message": "Marked as paid: Stripe shows $111.00 for this attempt.",
    }
    assert (a["charged_cents"], a["charge_state"], a["charge_error"], a["payment_state"]) == (11_100, "paid", "", "paid")
    assert a["needs_review"] == [] and a["actions"]["can_review"] is False and a["kept_cents"] == 11_100
    (row,) = charges_of(b["id"])
    assert (row.status, row.stripe_payment_intent_id, row.error_code, row.error_message) == (
        "succeeded", pi["id"], "", "")
    # the timeline says who did it, what Stripe showed, and that no money moved
    (line,) = _lines(client, b, "review_settled")
    assert line["cents"] == 11_100 and line["actor"] not in ("", "auto", "stripe", "client", "system")
    assert pi["id"] in line["detail"] and "Stripe shows it was paid" in line["detail"]
    assert "no money was moved" in line["detail"]
    # Stripe was asked one question, about this booking's own customer, and nothing else
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.count("Refund.create") == 0
    assert env.stripe.count("PaymentIntent.capture") == 0 and env.stripe.count("PaymentIntent.cancel") == 0
    assert [kw["customer"] for n, kw in env.stripe.calls if n == "PaymentIntent.list"] == [
        booking_row(b["ref"]).stripe_customer_id]
    assert env.stripe.money_taken() == 11_100
    # the client gets the receipt they never had, dated when the card was charged
    (receipt,) = to(env.outbox, CLIENT)
    assert receipt["subject"] == f"Receipt for your consulting call ({b['ref']})"
    assert "$111" in receipt["html"] and "Wednesday, June 11, 2031 at 6:00 PM BST" in receipt["html"]
    assert "June 12" not in receipt["html"]                        # not the day he pressed the button
    assert to(env.outbox, OWNER) == []


def test_paid_in_stripe_a_second_time_changes_nothing(client, env):
    b = _parked_charge(client, env, "network_after")
    assert _admin(client, b, "review-settled", {"cents": 11_100}).status_code == 200
    before = state_of_everything(env)
    for action, body in (("review-settled", {"cents": 11_100}), ("review-not-charged", {})):
        r = _admin(client, b, action, body)
        assert r.status_code == 409 and r.json()["detail"] == NOTHING
    assert state_of_everything(env) == before
    assert events_of(b["id"]).count("review_settled") == 1 and len(to(env.outbox, CLIENT)) == 1


def test_after_paid_in_stripe_the_booking_is_settled_for_every_later_step(client, env):
    b = _parked_charge(client, env, "network_after")
    (pi,) = env.stripe.payment_intents.values()
    _admin(client, b, "review-settled", {"cents": 11_100})
    # Charge again: there is nothing left to take
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100
    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 11_100
    # and a refund goes back against the payment that was found
    r = _admin(client, b, "refund", {"cents": 1_000})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 1_000
    assert env.stripe.last("Refund.create")["payment_intent"] == pi["id"]
    assert env.stripe.money_returned() == 1_000


def test_paid_in_stripe_is_refused_when_stripe_shows_no_such_payment(client, env):
    b = _parked_charge(client, env, "network_before")
    before = state_of_everything(env)
    r = _admin(client, b, "review-settled", {"cents": 11_100})
    assert r.status_code == 409
    assert "Stripe shows no completed payment of $111.00 for this attempt" in r.json()["detail"]
    assert "mark it as not charged" in r.json()["detail"]
    after = state_of_everything(env)
    assert after[:4] == before[:4]                                 # no row, no email changed
    assert [n for n, _ in after[4][len(before[4]):]] == ["PaymentIntent.list"]   # Stripe was only asked
    a = _a(client, b)
    assert a["charged_cents"] is None and a["charge_state"] == "review" and a["actions"]["can_review"] is True


@pytest.mark.parametrize("cents", [11_099, 11_101, 1, 22_200])
def test_paid_in_stripe_needs_the_amount_of_the_attempt(client, env, cents):
    b = _parked_charge(client, env, "network_after")
    before = state_of_everything(env)
    r = _admin(client, b, "review-settled", {"cents": cents})
    assert r.status_code == 409 and "This attempt was for $111.00" in r.json()["detail"]
    assert state_of_everything(env) == before                      # refused before Stripe is even asked


@pytest.mark.parametrize("body", [{}, {"cents": 0}, {"cents": -5}, {"cents": "all"}, {"cents": 10**9}])
def test_paid_in_stripe_without_a_proper_amount_is_not_accepted(client, env, body):
    b = _parked_charge(client, env, "network_after")
    before = state_of_everything(env)
    assert _admin(client, b, "review-settled", body).status_code == 422
    assert state_of_everything(env) == before


def test_only_a_completed_payment_of_that_amount_made_by_that_attempt_counts(client, env):
    """Stripe never heard of the parked attempt. Other payments that look
    like it are on the account; none of them is this attempt's payment."""
    b = _parked_charge(client, env, "network_before")
    other = confirmed(client, env, ny(2031, 6, 16, 10), email="other@example.com", ip="203.0.113.5")
    theirs = booking_row(other["ref"]).stripe_customer_id

    def refused(words: str) -> None:
        r = _admin(client, b, "review-settled", {"cents": 11_100})
        assert r.status_code == 409 and words in r.json()["detail"], r.text
        assert charges_of(b["id"])[0].status == "needs_review" and booking_row(b["ref"]).charged_cents == 0

    _stripe_payment(env, b, ledger_id=None)                         # same client, same amount, no attempt named
    refused("no completed payment of $111.00")
    _stripe_payment(env, b, ledger_id=b["row"] + 1000)              # same client, same amount, another attempt
    refused("no completed payment of $111.00")
    _stripe_payment(env, b, ledger_id=b["row"], customer=theirs)    # this attempt's number, on another client
    refused("no completed payment of $111.00")
    _stripe_payment(env, b, ledger_id=b["row"], amount=5_000)       # this attempt, another amount
    refused("no completed payment of $111.00")
    _stripe_payment(env, b, ledger_id=b["row"], status="requires_payment_method")   # this attempt, refused by the card
    refused("no completed payment of $111.00")
    _stripe_payment(env, b, ledger_id=b["row"], status="canceled")
    refused("no completed payment of $111.00")
    still = _stripe_payment(env, b, ledger_id=b["row"], status="processing")
    refused("Stripe is still processing this payment")
    assert events_of(b["id"]).count("review_settled") == 0 and to(env.outbox, CLIENT) == []
    # the bank finishes: now it is there
    still["status"], still["amount_received"] = "succeeded", 11_100
    r = _admin(client, b, "review-settled", {"cents": 11_100})
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100
    assert charges_of(b["id"])[0].stripe_payment_intent_id == still["id"]


def test_the_payment_is_found_however_many_pages_stripe_answers_in(client, env):
    b = _parked_charge(client, env, "network_after")
    (pi,) = list(env.stripe.payment_intents.values())
    for _ in range(3):                                              # newer payments of the same client come first
        _stripe_payment(env, b, ledger_id=None, amount=700)
    env.stripe.list_page = 1
    r = _admin(client, b, "review-settled", {"cents": 11_100})
    assert r.status_code == 200 and charges_of(b["id"])[0].stripe_payment_intent_id == pi["id"]
    pages = [kw for n, kw in env.stripe.calls if n == "PaymentIntent.list"]
    assert len(pages) == 4 and "starting_after" not in pages[0]
    assert [p["starting_after"] for p in pages[1:]] == [x["id"] for x in list(env.stripe.payment_intents.values())[:0:-1]]


# -----------------------------------------------------------------------------
# "Not charged"
# -----------------------------------------------------------------------------

def test_not_charged_closes_the_attempt_and_charge_then_takes_the_money_once(client, env):
    b = _parked_charge(client, env, "network_before")
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["action"] == {
        "ok": True, "status": "noop", "amount_cents": 0, "code": "",
        "message": "Marked as not charged. Stripe shows no payment for this attempt; it can be tried again.",
    }
    assert (a["charged_cents"], a["charge_state"], a["payment_state"]) == (None, "open", "payment_failed")
    assert client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()["card_problem"] is False
    assert a["charge_error"] == "An earlier attempt took no money (checked in Stripe). Charge can be tried again."
    assert a["needs_review"] == [] and a["actions"]["can_review"] is False and a["actions"]["can_charge"] is True
    (row,) = charges_of(b["id"])
    assert (row.status, row.error_code) == ("failed", "review_not_charged")
    (line,) = _lines(client, b, "review_not_charged")
    assert line["cents"] == 11_100 and line["actor"] not in ("", "auto", "stripe", "client", "system")
    assert "Stripe shows no payment for this attempt" in line["detail"] and "it can be tried again" in line["detail"]
    assert env.outbox == [] and env.stripe.money_taken() == 0
    assert env.stripe.count("PaymentIntent.create") == 1           # the lost one; nothing new was sent

    # retrying is his to do: the tick does not charge by itself
    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 0

    # Charge works again: a new attempt, under a new key
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100 and r.json()["charge_state"] == "paid"
    keys = [kw["idempotency_key"] for n, kw in env.stripe.calls if n == "PaymentIntent.create"]
    assert keys == [f"consult:{b['ref']}:charge:meeting:1", f"consult:{b['ref']}:charge:meeting:2"]
    assert [(c.attempt, c.status) for c in charges_of(b["id"])] == [(1, "failed"), (2, "succeeded")]
    assert subjects(env.outbox, CLIENT) == [f"Receipt for your consulting call ({b['ref']})"]
    # and once: pressing it again takes nothing more
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    assert env.stripe.money_taken() == 11_100 and env.stripe.count("PaymentIntent.create") == 2
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 409 and r.json()["detail"] == NOTHING


def test_not_charged_is_refused_when_stripe_shows_the_payment_went_through(client, env):
    """The dangerous mistake: he does not find the payment, says "not
    charged", presses Charge, and the client pays twice."""
    b = _parked_charge(client, env, "network_after")
    (pi,) = env.stripe.payment_intents.values()
    before = state_of_everything(env)
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 409
    assert r.json()["detail"] == (
        f"Stripe shows this payment went through ({pi['id']}, $111.00). Mark it as paid instead: "
        "charging again would take the money twice."
    )
    after = state_of_everything(env)
    assert after[:4] == before[:4] and [n for n, _ in after[4][len(before[4]):]] == ["PaymentIntent.list"]
    # still parked, so Charge still sends nothing
    assert _admin(client, b, "charge").json()["action"]["status"] == "needs_review"
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 11_100
    assert events_of(b["id"]).count("review_not_charged") == 0


def test_not_charged_waits_while_stripe_is_still_processing_the_payment(client, env):
    b = _parked_charge(client, env, "network_before")
    still = _stripe_payment(env, b, ledger_id=b["row"], status="processing")
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 409 and "Stripe is still processing this payment. Look again later." == r.json()["detail"]
    assert charges_of(b["id"])[0].status == "needs_review"
    still["status"] = "canceled"                                    # it came to nothing
    assert _admin(client, b, "review-not-charged").status_code == 200
    assert charges_of(b["id"])[0].status == "failed"


def test_a_payment_the_card_refused_counts_as_not_charged(client, env):
    b = _parked_charge(client, env, "network_before")
    _stripe_payment(env, b, ledger_id=b["row"], status="requires_payment_method")
    _stripe_payment(env, b, ledger_id=b["row"] + 1000)              # somebody else's attempt, paid: not this one
    assert _admin(client, b, "review-not-charged").status_code == 200
    assert charges_of(b["id"])[0].status == "failed" and booking_row(b["ref"]).charged_cents == 0


# -----------------------------------------------------------------------------
# A parked hold
# -----------------------------------------------------------------------------

def test_a_parked_hold_cannot_be_marked_as_paid(client, env):
    b = _parked_hold(client, env, "network_after")
    before = state_of_everything(env)
    r = _admin(client, b, "review-settled", {"cents": 11_100})
    assert r.status_code == 409 and "This attempt was a hold, not a charge" in r.json()["detail"]
    assert state_of_everything(env) == before


def test_a_parked_hold_that_stripe_did_place_must_be_cancelled_there_first(client, env):
    b = _parked_hold(client, env, "network_after")
    (pi,) = env.stripe.payment_intents.values()
    assert pi["status"] == "requires_capture" and env.stripe.authorized() == 11_100
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 409
    assert r.json()["detail"] == (
        f"Stripe shows an authorization of $111.00 on the card ({pi['id']}). Cancel it in Stripe first, "
        "then mark this as not charged."
    )
    assert charges_of(b["id"])[0].status == "needs_review"
    assert env.stripe.count("PaymentIntent.cancel") == 0            # the site does not cancel it for him
    pi["status"] = "canceled"                                       # he cancels it in the Stripe dashboard
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 200 and r.json()["needs_review"] == [] and r.json()["hold_state"] == ""
    (line,) = _lines(client, b, "review_not_charged")
    assert "Hold" in line["detail"] or "hold" in line["detail"]
    # the call is still three hours away: the next tick places the hold afresh, once
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["hold:hold_notice"] == 1
    assert booking_row(b["ref"]).hold_state == "authorized" and env.stripe.authorized() == 11_100
    assert [(c.attempt, c.status) for c in charges_of(b["id"])] == [(1, "failed"), (2, "authorized")]
    assert env.stripe.money_taken() == 0


def test_a_parked_hold_that_never_reached_stripe_is_simply_cleared(client, env):
    b = _parked_hold(client, env, "network_before")
    # the button sends no body at all: that is accepted too
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/review-not-charged", headers=ADMIN)
    assert r.status_code == 200 and r.json()["actions"]["can_review"] is False
    assert charges_of(b["id"])[0].status == "failed" and booking_row(b["ref"]).charge_state == ""
    assert env.stripe.authorized() == 0 and env.stripe.money_taken() == 0


def test_a_parked_hold_captured_by_hand_in_stripe_is_not_cleared_as_if_nothing_happened(client, env):
    b = _parked_hold(client, env, "network_after")
    (pi,) = env.stripe.payment_intents.values()
    pi["status"], pi["amount_received"] = "succeeded", 11_100       # captured in the Stripe dashboard
    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 409 and "this hold was captured there" in r.json()["detail"]
    assert "refund it in Stripe" in r.json()["detail"] and "Mark it as paid" not in r.json()["detail"]
    assert charges_of(b["id"])[0].status == "needs_review"


# -----------------------------------------------------------------------------
# Which attempt, whose booking, and when Stripe cannot be asked
# -----------------------------------------------------------------------------

def test_with_two_attempts_parked_he_says_which_one(client, env):
    """Two at once is rare: once a booking is settled the tick clears a parked
    hold by itself. It happens when Stripe refuses the requests themselves:
    the hold the day before, then the charge he presses after the call."""
    b = _parked_hold(client, env, "invalid")
    hold_row = b["row"]
    env.clock.set(END)
    env.stripe.card = "invalid"
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["action"]["code"] == "request_refused"
    env.stripe.card = "ok"
    a = _a(client, b)
    assert [(x["kind"], x["reason"]) for x in a["needs_review"]] == [("hold", "hold"), ("charge", "meeting")]
    charge_row = a["needs_review"][1]["charge_id"]

    r = _admin(client, b, "review-not-charged")
    assert r.status_code == 409 and "More than one payment attempt" in r.json()["detail"]
    assert "charge_id" in r.json()["detail"]
    assert _admin(client, b, "review-not-charged", {"charge_id": 987_654}).status_code == 409
    assert [c.status for c in charges_of(b["id"])] == ["needs_review", "needs_review"]

    r = _admin(client, b, "review-not-charged", {"charge_id": charge_row})
    assert r.status_code == 200
    assert [x["charge_id"] for x in r.json()["needs_review"]] == [hold_row]
    assert [c.status for c in charges_of(b["id"])] == ["needs_review", "failed"]
    r = _admin(client, b, "review-not-charged")                     # one is left: no need to name it
    assert r.status_code == 200 and r.json()["needs_review"] == []
    assert events_of(b["id"]).count("review_not_charged") == 2


def test_a_parked_hold_on_a_settled_booking_is_cleared_by_the_tick_itself(client, env):
    b = _parked_hold(client, env, "invalid")
    env.clock.set(END)
    assert _admin(client, b, "waive").status_code == 200
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["lost_hold:cleared"] == 1            # Stripe has nothing for it: closed
    assert _a(client, b)["needs_review"] == [] and charges_of(b["id"])[0].status == "failed"


def test_an_attempt_of_another_booking_cannot_be_named(client, env):
    b = _parked_charge(client, env, "network_after")
    other = confirmed(client, env, ny(2031, 6, 16, 10), email="other@example.com", ip="203.0.113.5")
    for action, body in (("review-settled", {"cents": 11_100, "charge_id": b["row"]}),
                         ("review-not-charged", {"charge_id": b["row"]})):
        r = _admin(client, other, action, body)
        assert r.status_code == 409 and r.json()["detail"] == NOTHING
    assert charges_of(b["id"])[0].status == "needs_review" and charges_of(other["id"]) == []


@pytest.mark.parametrize("action, body", [("review-settled", {"cents": 11_100}), ("review-not-charged", {})])
def test_when_stripe_cannot_be_asked_nothing_is_changed(client, env, action, body):
    b = _parked_charge(client, env, "network_after")
    env.stripe.list_fails = True
    before = state_of_everything(env)
    r = _admin(client, b, action, body)
    assert r.status_code == 503
    assert r.json()["detail"] == "Stripe could not be reached to check this payment. Nothing was changed; try again."
    after = state_of_everything(env)
    assert after[:4] == before[:4] and [n for n, _ in after[4][len(before[4]):]] == ["PaymentIntent.list"]
    assert charges_of(b["id"])[0].status == "needs_review"


@pytest.mark.parametrize("action, body", [("review-settled", {"cents": 11_100}), ("review-not-charged", {})])
def test_the_review_actions_are_the_admins_alone(client, env, action, body):
    b = _parked_charge(client, env, "network_after")
    before = state_of_everything(env)
    url = f"{ADMIN_API}/bookings/{b['id']}/{action}"
    assert client.post(url, json=body).status_code in (401, 403)
    assert client.post(url, json=body, headers={"Authorization": "Bearer wrong"}).status_code in (401, 403)
    assert client.post(url, json=body, headers={"X-Cron-Secret": "anything"}).status_code in (401, 403)
    assert client.post(f"{ADMIN_API}/bookings/999999/{action}", json=body, headers=ADMIN).status_code == 404
    assert state_of_everything(env) == before
    # and nothing of it is reachable from the client's side
    assert client.post(f"{PUBLIC}/booking/{b['ref']}/{action}", json={"t": b["token"], **body}).status_code in (404, 405)


def test_a_booking_with_nothing_parked_refuses_both(client, env):
    b = confirmed(client, env, START)
    before = state_of_everything(env)
    for action, body in (("review-settled", {"cents": 11_100}), ("review-not-charged", {})):
        r = _admin(client, b, action, body)
        assert r.status_code == 409 and r.json()["detail"] == NOTHING
    assert state_of_everything(env) == before                      # Stripe is not even asked


# -----------------------------------------------------------------------------
# Safe to repeat, also at the same instant
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("outcome, lost", [("settled", "network_after"), ("not_charged", "network_before")])
def test_four_presses_at_once_are_one(client, env, outcome, lost):
    b = _parked_charge(client, env, lost)
    go = threading.Barrier(4)
    results: list = []

    def run() -> None:
        db = SessionLocal()
        try:
            go.wait(timeout=10)
            _, result = consult.resolve_review(
                db, db.get(ConsultBooking, b["id"]), outcome, actor="admin",
                cents=11_100 if outcome == "settled" else None)
            results.append(result.fresh)
        except consult.Refused as exc:
            results.append(str(exc))
        except Exception as exc:  # noqa: BLE001
            results.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == 4 and all(r in (True, False, NOTHING) for r in results), results
    assert results.count(True) == 1                                 # exactly one of them did it
    kind = "review_settled" if outcome == "settled" else "review_not_charged"
    assert events_of(b["id"]).count(kind) == 1
    assert len(to(env.outbox, CLIENT)) == (1 if outcome == "settled" else 0)
    assert [c.status for c in charges_of(b["id"])] == ["succeeded" if outcome == "settled" else "failed"]
    assert env.stripe.count("PaymentIntent.create") == 1


def test_the_owner_is_asked_once_per_parked_attempt_and_again_for_a_new_one(client, env):
    b = confirmed(client, env, START)
    env.clock.set(END)
    tick(client)
    env.clock.set(DUE)
    env.stripe.card = "network_before"
    tick(client)
    env.clock.advance(hours=21)
    env.outbox.clear()
    for _ in range(3):
        tick(client)
        env.clock.advance(minutes=5)
    assert len(to(env.outbox, OWNER)) == 1 and events_of(b["id"]).count("charge_review_requested") == 1
    # he clears it and presses Charge; Stripe is still unreachable, and stays so for a day
    assert _admin(client, b, "review-not-charged").status_code == 200
    env.outbox.clear()
    r = _admin(client, b, "charge")
    assert r.status_code == 200 and r.json()["charge_state"] == "pending"
    env.clock.advance(hours=21)
    for _ in range(3):
        tick(client)
        env.clock.advance(minutes=5)
    asked = [m for m in to(env.outbox, OWNER) if "needs checking in Stripe" in m["subject"]]
    assert len(asked) == 1 and events_of(b["id"]).count("charge_review_requested") == 2
    assert [(c.attempt, c.status) for c in charges_of(b["id"])] == [(1, "failed"), (2, "needs_review")]
    assert env.stripe.money_taken() == 0


def test_the_ledger_function_refuses_an_action_it_does_not_know(client, env):
    b = _parked_charge(client, env, "network_after")
    db = SessionLocal()
    result = money.resolve_review(db, db.get(ConsultBooking, b["id"]), "forgive", actor="admin")
    db.close()
    assert (result.ok, result.status, result.code) == (False, "refused", "unknown")
    assert charges_of(b["id"])[0].status == "needs_review"
