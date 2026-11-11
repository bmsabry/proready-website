"""Consulting calls: a client's bank disputes a payment.

Stripe sends `charge.dispute.created` when a cardholder disputes a payment
and `charge.dispute.closed` when the bank has decided. For a consulting
payment both go on the booking's timeline and to the owner, once each
however often Stripe delivers them, and the booking records what is in
dispute and what was lost (`disputed_cents`, `dispute_lost_cents`,
`dispute_state`), so that a lost dispute no longer shows as money kept. No
money is moved by any of this. A dispute on any other payment still reaches
the course-purchase code exactly as before.
"""
from __future__ import annotations

from datetime import timedelta

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    OWNER,
    PUBLIC,
    booking_row,
    charges_of,
    client,
    confirmed,
    env,
    events_of,
    ny,
    post_webhook,
    tick,
    to,
    world,
)

from app import consult_auto
from app.routes import checkout as checkout_routes

START = ny(2031, 6, 11, 10)
DUE_BY = int(ny(2031, 6, 25, 20).timestamp())


def _charged(client, env, *, with_hold: bool = False) -> tuple[dict, str]:
    """A call that took place and was charged $111. Returns it and the
    PaymentIntent the money was taken on."""
    b = confirmed(client, env, START)
    if with_hold:
        env.clock.set(START - timedelta(hours=24))
        tick(client)
    env.clock.set(START + timedelta(minutes=61))
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/charge", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["charged_cents"] == 11_100
    env.outbox.clear()
    return b, charges_of(b["id"])[-1].stripe_payment_intent_id


def _dispute(
    pi: str, kind: str = "created", *, status: str = "needs_response", dispute_id: str = "dp_test_1",
    amount: int = 11_100,
) -> dict:
    return {"type": f"charge.dispute.{kind}", "data": {"object": {
        "id": dispute_id, "object": "dispute", "charge": "ch_test_1", "payment_intent": pi,
        "amount": amount, "currency": "usd", "reason": "product_not_received", "status": status,
        "evidence_details": {"due_by": DUE_BY, "has_evidence": False},
    }}}


def _a(client, b: dict) -> dict:
    return client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()


def _amounts(client, b: dict) -> tuple:
    """(disputed, lost, state, kept, refundable) as the admin screen is given them."""
    a = _a(client, b)
    return (a["disputed_cents"], a["dispute_lost_cents"], a["dispute_state"], a["kept_cents"],
            a["actions"]["refundable_cents"])


def _public(client, b: dict) -> dict:
    return client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()


def test_a_dispute_goes_on_the_timeline_and_to_the_owner(client, env):
    b, pi = _charged(client, env)
    r = post_webhook(client, env, _dispute(pi))
    assert r.status_code == 200 and r.json() == {"received": True}

    a = client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()
    (line,) = [e for e in a["events"] if e["kind"] == "dispute_opened"]
    assert line["actor"] == "stripe" and line["cents"] == 11_100
    assert "disputed this payment with their bank" in line["detail"] and "product not received" in line["detail"]
    # the booking's own amounts are what was charged through the site: unchanged
    assert a["charged_cents"] == 11_100 and a["refunded_cents"] == 0 and a["status"] == "completed"
    # and beside them, what the bank now holds
    assert (a["disputed_cents"], a["dispute_lost_cents"], a["dispute_state"]) == (11_100, 0, "open")
    assert a["kept_cents"] == 11_100                                   # nothing is lost until the bank decides

    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] A client's bank has opened a dispute: Casey Client"
    for needle in ("product not received", "$111", "dp_test_1",
                   "Wednesday, June 25, 2031 at 8:00 PM EDT",          # when the evidence is due, his clock
                   'href="https://dashboard.stripe.com/disputes/dp_test_1"',
                   f"/admin#consult/booking/{b['id']}", "consent record"):
        assert needle in alert["html"], needle
    assert to(env.outbox, "client@example.com") == []                  # the client is not written to


def test_the_same_dispute_delivered_again_is_recorded_once(client, env):
    b, pi = _charged(client, env)
    for _ in range(3):
        assert post_webhook(client, env, _dispute(pi)).status_code == 200
    assert events_of(b["id"]).count("dispute_opened") == 1 and len(to(env.outbox, OWNER)) == 1
    # a second, different dispute on the same payment is its own line
    assert post_webhook(client, env, _dispute(pi, dispute_id="dp_test_2")).status_code == 200
    assert events_of(b["id"]).count("dispute_opened") == 2 and len(to(env.outbox, OWNER)) == 2


def test_the_end_of_a_dispute_is_recorded_lost_or_won(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi))
    env.outbox.clear()
    for _ in range(2):
        assert post_webhook(client, env, _dispute(pi, "closed", status="lost")).status_code == 200
    assert events_of(b["id"])[-2:] == ["dispute_opened", "dispute_closed"]
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] Dispute LOST: Casey Client"
    assert "Stripe returned the money to the cardholder" in alert["html"] and "dispute fee" in alert["html"]
    assert "The booking now shows this amount as lost to the dispute, and no longer as kept." in alert["html"]
    assert "$111 lost to a dispute" in alert["html"]                    # the row among the booking's facts
    row = booking_row(b["ref"])
    assert (row.status, row.charged_cents) == ("completed", 11_100)     # the ledger is not rewritten
    assert (row.disputed_cents, row.dispute_lost_cents, row.dispute_state) == (11_100, 11_100, "lost")

    c, pi2 = _charged_second(client, env)
    post_webhook(client, env, _dispute(pi2, dispute_id="dp_test_9"))
    env.outbox.clear()
    post_webhook(client, env, _dispute(pi2, "closed", status="won", dispute_id="dp_test_9"))
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] Dispute won: Dana Second"
    assert "decided in your favour" in alert["html"] and "no longer as kept" not in alert["html"]
    assert "disputed, decided for you" in alert["html"]
    assert _amounts(client, c) == (0, 0, "won", 33_300, 33_300)        # booked a day ahead: the next-day rate


def _charged_second(client, env) -> tuple[dict, str]:
    start = ny(2031, 6, 12, 10)
    env.clock.set(ny(2031, 6, 11, 12))
    c = confirmed(client, env, start, email="second@example.com", ip="203.0.113.2", name="Dana Second")
    env.clock.set(start + timedelta(minutes=61))
    client.post(f"{ADMIN_API}/bookings/{c['id']}/charge", headers=ADMIN, json={})
    return c, charges_of(c["id"])[-1].stripe_payment_intent_id


def test_a_dispute_on_money_captured_from_a_hold_is_found_too(client, env):
    b, pi = _charged(client, env, with_hold=True)
    assert charges_of(b["id"])[0].kind == "hold" and booking_row(b["ref"]).hold_payment_intent_id == pi
    assert post_webhook(client, env, _dispute(pi)).status_code == 200
    assert "dispute_opened" in events_of(b["id"]) and len(to(env.outbox, OWNER)) == 1


def test_a_dispute_on_any_other_payment_goes_to_the_course_code_as_before(client, env, monkeypatch):
    b, pi = _charged(client, env)
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(checkout_routes, "_revoke_for_payment",
                        lambda db, payment_intent, reason: seen.append((payment_intent, reason)))
    assert post_webhook(client, env, _dispute("pi_a_course_purchase")).status_code == 200
    assert seen == [("pi_a_course_purchase", "disputed")]              # the existing branch ran
    assert post_webhook(client, env, _dispute("pi_a_course_purchase", "closed", status="lost")).status_code == 200
    assert seen == [("pi_a_course_purchase", "disputed")]              # 'closed' was, and is, ignored there
    assert "dispute_opened" not in events_of(b["id"]) and env.outbox == []
    # and a consulting dispute never reaches the course code
    assert post_webhook(client, env, _dispute(pi)).status_code == 200
    assert seen == [("pi_a_course_purchase", "disputed")]
    # a dispute that names no payment at all is not ours either
    nameless = _dispute("")
    nameless["data"]["object"]["payment_intent"] = None
    assert post_webhook(client, env, nameless).status_code == 200
    assert seen[-1] == ("", "disputed")


# -----------------------------------------------------------------------------
# What the booking shows: disputed, lost, kept
# -----------------------------------------------------------------------------

def test_a_lost_dispute_is_no_longer_shown_as_money_kept(client, env):
    b, pi = _charged(client, env)
    assert _amounts(client, b) == (0, 0, "", 11_100, 11_100)
    assert _public(client, b)["charged_cents"] == 11_100
    calls_before = list(env.stripe.calls)

    post_webhook(client, env, _dispute(pi))
    assert _amounts(client, b) == (11_100, 0, "open", 11_100, 0)       # held by the bank: not refundable from here
    assert _a(client, b)["actions"]["can_refund"] is False
    assert _public(client, b)["charged_cents"] == 11_100

    post_webhook(client, env, _dispute(pi, "closed", status="lost"))
    a = _a(client, b)
    assert (a["disputed_cents"], a["dispute_lost_cents"], a["dispute_state"], a["kept_cents"]) == (
        11_100, 11_100, "lost", 0)
    assert a["charged_cents"] == 11_100 and a["refunded_cents"] == 0    # what the site did is not rewritten
    assert a["actions"]["refundable_cents"] == 0 and a["actions"]["can_refund"] is False
    assert a["payment_state"] == "paid" and a["status"] == "completed"
    assert _public(client, b)["charged_cents"] == 0                     # the client's page: they got it back
    # no money was moved by any of it: Stripe was not called once
    assert env.stripe.calls == calls_before
    assert env.stripe.money_taken() == 11_100 and env.stripe.money_returned() == 0
    assert [(c.kind, c.status, c.amount_cents) for c in charges_of(b["id"])] == [("charge", "succeeded", 11_100)]


def test_a_dispute_won_leaves_the_money_kept_and_refundable_again(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi))
    post_webhook(client, env, _dispute(pi, "closed", status="won"))
    assert _amounts(client, b) == (0, 0, "won", 11_100, 11_100)
    assert _public(client, b)["charged_cents"] == 11_100


def test_an_inquiry_closed_without_a_dispute_leaves_nothing_behind(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi, status="warning_needs_response"))
    assert _amounts(client, b) == (11_100, 0, "open", 11_100, 0)
    post_webhook(client, env, _dispute(pi, "closed", status="warning_closed"))
    assert _amounts(client, b) == (0, 0, "closed", 11_100, 11_100)


def test_the_end_of_a_dispute_arriving_before_its_beginning_still_counts(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi, "closed", status="lost"))    # Stripe does not promise the order
    assert _amounts(client, b) == (11_100, 11_100, "lost", 0, 0)
    post_webhook(client, env, _dispute(pi))
    assert _amounts(client, b) == (11_100, 11_100, "lost", 0, 0)       # the late opening does not reopen it
    for _ in range(2):                                                  # and repeats change nothing
        post_webhook(client, env, _dispute(pi, "closed", status="lost"))
        post_webhook(client, env, _dispute(pi))
    assert _amounts(client, b) == (11_100, 11_100, "lost", 0, 0)
    assert events_of(b["id"]).count("dispute_opened") == 1 and events_of(b["id"]).count("dispute_closed") == 1


def test_a_dispute_for_what_was_left_after_a_refund(client, env):
    b, pi = _charged(client, env)
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": 5_000})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 5_000
    post_webhook(client, env, _dispute(pi, amount=6_100))
    assert _amounts(client, b) == (6_100, 0, "open", 6_100, 0)
    post_webhook(client, env, _dispute(pi, "closed", status="lost", amount=6_100))
    assert _amounts(client, b) == (6_100, 6_100, "lost", 0, 0)
    assert _public(client, b)["charged_cents"] == 0


def test_a_part_of_the_payment_lost_leaves_the_rest_kept_and_refundable(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi, amount=4_000))
    post_webhook(client, env, _dispute(pi, "closed", status="lost", amount=4_000))
    assert _amounts(client, b) == (4_000, 4_000, "lost", 7_100, 7_100)
    assert _public(client, b)["charged_cents"] == 7_100
    # more than is left cannot be refunded, and the answer says why
    calls = env.stripe.count("Refund.create")
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": 7_101})
    assert r.status_code == 409 and env.stripe.count("Refund.create") == calls
    assert "At most $71.00 can be refunded on this booking." in r.json()["detail"]
    assert "$40.00 is held by, or was lost to, a dispute" in r.json()["detail"]
    # the rest can
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": 7_100})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 7_100
    assert _amounts(client, b) == (4_000, 4_000, "lost", 0, 0)
    assert env.stripe.money_returned() == 7_100


def test_a_refund_is_not_sent_while_the_bank_holds_the_money(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi))
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/refund", headers=ADMIN, json={"cents": 1_000})
    assert r.status_code == 409 and env.stripe.count("Refund.create") == 0
    assert "At most $0.00 can be refunded" in r.json()["detail"] and "$111.00 is held by" in r.json()["detail"]
    assert booking_row(b["ref"]).refunded_cents == 0


def test_the_disputed_amount_is_never_more_than_was_charged(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi, amount=99_999))
    assert _amounts(client, b) == (11_100, 0, "open", 11_100, 0)
    post_webhook(client, env, _dispute(pi, "closed", status="lost", amount=99_999))
    assert _amounts(client, b) == (11_100, 11_100, "lost", 0, 0)


def test_two_disputes_on_one_booking_are_added_up(client, env):
    b, pi = _charged(client, env)
    post_webhook(client, env, _dispute(pi, amount=4_000, dispute_id="dp_a"))
    post_webhook(client, env, _dispute(pi, "closed", status="lost", amount=4_000, dispute_id="dp_a"))
    post_webhook(client, env, _dispute(pi, amount=3_000, dispute_id="dp_b"))
    assert _amounts(client, b) == (7_000, 4_000, "open", 7_100, 4_100)  # one lost, one still open
    post_webhook(client, env, _dispute(pi, "closed", status="won", dispute_id="dp_b", amount=3_000))
    assert _amounts(client, b) == (4_000, 4_000, "lost", 7_100, 7_100)


def test_the_dispute_sums_on_their_own():
    totals = consult_auto.dispute_totals
    opened = lambda d, cents: ("dispute_opened", {"dispute_id": d, "status": "needs_response"}, cents)  # noqa: E731
    closed = lambda d, how, cents: ("dispute_closed", {"dispute_id": d, "status": how}, cents)          # noqa: E731
    assert totals([]) == (0, 0, "")
    assert totals([opened("a", 500)]) == (500, 0, "open")
    assert totals([opened("a", 500), closed("a", "lost", 500)]) == (500, 500, "lost")
    assert totals([closed("a", "lost", 500), opened("a", 500)]) == (500, 500, "lost")
    assert totals([opened("a", 500), closed("a", "won", 500)]) == (0, 0, "won")
    assert totals([opened("a", 500), closed("a", "warning_closed", 500)]) == (0, 0, "closed")
    assert totals([opened("a", 500), closed("a", "charge_refunded", 500)]) == (0, 0, "closed")
    assert totals([closed("a", "lost", 500)]) == (500, 500, "lost")
    # the larger of the two amounts Stripe named for one dispute; never the sum of both lines
    assert totals([opened("a", 500), closed("a", "lost", 450)]) == (500, 500, "lost")
    # several: open outranks lost outranks won in the one word shown
    assert totals([opened("a", 500), closed("a", "lost", 500), opened("b", 200)]) == (700, 500, "open")
    assert totals([opened("a", 500), closed("a", "lost", 500), opened("b", 200), closed("b", "won", 200)]) == (
        500, 500, "lost")
    assert totals([opened("a", 500), closed("a", "won", 500), opened("b", 200), closed("b", "warning_closed", 200)]) == (
        0, 0, "won")
    assert totals([("dispute_opened", None, None)]) == (0, 0, "open")   # a line with nothing in it does not break it
