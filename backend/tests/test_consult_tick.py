"""Consulting calls: the cron tick before the meeting.

  POST /api/admin/consult/tick    every five minutes, with the cron secret

  the hold       placed `hold_lead_hours` before the start (at once when the
                 card is saved inside that time); refused: the client is
                 asked for another card, the hold is tried on the new one,
                 and 2 hours before the start a booking still without a hold
                 is cancelled, its time released, both sides told
  reminders      24 hours and 1 hour before, once each
  repairs        a calendar event Google refused, a cancellation cut short,
                 a hold Stripe did not answer about
  idempotency    a second tick right after the first changes nothing

Rates are consult_support's artificial ones: the Wednesday call below is
60 minutes at $111, fee $22.20. What happens after the meeting is in
test_consult_settlement.py.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

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
    iso,
    ny,
    save_card,
    slot_starts,
    state_of_everything,
    subjects,
    tick,
    to,
    world,
)

from app import consult
from app import consult_auto
from app import emailer as E
from app.config import get_settings
from app.consult_models import ConsultBooking
from app.consult_money import aware
from app.db import SessionLocal
from app.models import EmailLog

START = ny(2031, 6, 11, 10)                 # Wednesday, nine days ahead
HOLD_AT = START - timedelta(hours=24)
CLIENT = "client@example.com"


def _mails(env, addr: str, words: str) -> list[dict]:
    return [m for m in to(env.outbox, addr) if words in m["subject"]]


def _view(client, b: dict) -> dict:
    return client.get(f"{PUBLIC}/booking/{b['ref']}", params={"t": b["token"]}).json()


def _replace_card(client, env, b: dict, **card):
    r = client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    assert r.status_code == 200, r.text
    return save_card(client, env, b["ref"], **card)


# -----------------------------------------------------------------------------
# Who may run the tick
# -----------------------------------------------------------------------------

def test_the_tick_needs_the_cron_secret_or_the_admin(client, env, monkeypatch):
    assert client.post(f"{ADMIN_API}/tick").status_code == 401
    monkeypatch.setattr(get_settings(), "CRON_SECRET", "cron-secret-for-tests")
    assert client.post(f"{ADMIN_API}/tick", headers={"X-Cron-Secret": "wrong"}).status_code == 401
    r = client.post(f"{ADMIN_API}/tick", headers={"X-Cron-Secret": "cron-secret-for-tests"})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["problems"] == []
    assert client.post(f"{ADMIN_API}/tick", headers=ADMIN).status_code == 200      # by hand, as the admin
    assert client.get(f"{ADMIN_API}/tick", headers=ADMIN).status_code == 405       # never by opening a link


def test_the_status_strip_says_whether_the_tick_is_running(client, env):
    s = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert s["tick_ok"] is False and s["last_tick_at"] is None                     # the cron job is not set up
    tick(client)
    s = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert s["tick_ok"] is True and s["last_tick_at"] == iso(NOW)
    env.clock.advance(minutes=31)
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["tick_ok"] is False   # it stopped


# -----------------------------------------------------------------------------
# The hold: when it is placed
# -----------------------------------------------------------------------------

def test_the_hold_is_placed_24_hours_before_the_start_and_not_a_minute_sooner(client, env):
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(HOLD_AT - timedelta(minutes=1))
    assert tick(client)["done"] == {}
    assert env.stripe.count("PaymentIntent.create") == 0 and booking_row(b["ref"]).hold_state == ""

    env.clock.set(HOLD_AT)
    out = tick(client)
    assert out["ok"] is True and out["done"]["hold:hold_notice"] == 1
    call = env.stripe.last("PaymentIntent.create")
    assert call["amount"] == 11_100 and call["capture_method"] == "manual"         # the booked amount, not captured
    assert call["off_session"] is True and call["confirm"] is True
    row = booking_row(b["ref"])
    assert (row.hold_state, row.hold_cents, row.charged_cents) == ("authorized", 11_100, 0)
    assert env.stripe.authorized() == 11_100 and env.stripe.money_taken() == 0

    (mail,) = _mails(env, CLIENT, "temporary hold")
    assert mail["subject"] == f"A temporary hold is on your card for your consulting call ({b['ref']})"
    assert "$111" in mail["html"] and "Visa ending 4242" in mail["html"]
    assert "A hold is not a charge" in mail["html"] and "20% ($22.20)" in mail["html"]
    assert "Wednesday, June 11, 2031 at 3:00 PM BST (Europe/London)" in mail["html"]   # their clock
    assert f"/consult/booking/{b['ref']}?t={b['token']}" in mail["html"]
    assert _mails(env, OWNER, "hold") == []                                        # nothing for him to do

    # The next ticks find the hold there: no second authorization, no second email.
    for _ in range(3):
        env.clock.advance(minutes=5)
        tick(client)
    assert env.stripe.count("PaymentIntent.create") == 1 and len(_mails(env, CLIENT, "temporary hold")) == 1
    assert events_of(b["id"]).count("hold_placed") == 1


def test_the_hold_lead_time_is_the_one_the_booking_was_made_under(client, env):
    r = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={"hold_lead_hours": 48})
    assert r.status_code == 200
    b = confirmed(client, env, START)
    client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={"hold_lead_hours": 12})   # changed afterwards
    env.clock.set(START - timedelta(hours=48, minutes=1))
    tick(client)
    assert booking_row(b["ref"]).hold_state == ""
    env.clock.set(START - timedelta(hours=48))
    tick(client)
    assert booking_row(b["ref"]).hold_state == "authorized"


def test_a_call_booked_inside_the_hold_time_gets_its_hold_when_the_card_is_saved(client, env):
    """Five hours ahead: the hold cannot wait for '24 hours before'. It is
    placed by the webhook that saves the card. The confirmation email has
    just said so, so there is no second email about it."""
    today = ny(2031, 6, 2, 15)
    b = confirmed(client, env, today)                              # same day: $444
    row = booking_row(b["ref"])
    assert (row.hold_state, row.hold_cents) == ("authorized", 44_400)
    call = env.stripe.last("PaymentIntent.create")
    assert call["amount"] == 44_400 and call["capture_method"] == "manual"
    assert env.stripe.authorized() == 44_400 and env.stripe.money_taken() == 0
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call is confirmed ({b['ref']})"]
    assert "placed on your card shortly" in to(env.outbox, CLIENT)[0]["html"]
    tick(client)
    env.clock.advance(minutes=5)
    tick(client)
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call is confirmed ({b['ref']})"]
    assert env.stripe.count("PaymentIntent.create") == 1


def test_a_hold_stripe_did_not_answer_about_is_asked_again_with_the_same_key(client, env):
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "network_after"                              # authorized at Stripe; the answer is lost
    tick(client)
    row = booking_row(b["ref"])
    assert row.hold_state == "" and row.status == "confirmed"      # no verdict: nobody is told anything
    assert _mails(env, CLIENT, "hold") == [] and _mails(env, CLIENT, "Action needed") == []
    env.stripe.card = "ok"
    env.clock.advance(minutes=5)
    tick(client)
    keys = [kw["idempotency_key"] for name, kw in env.stripe.calls if name == "PaymentIntent.create"]
    assert keys == [f"consult:{b['ref']}:hold:hold:1"] * 2 and len(env.stripe.payment_intents) == 1
    assert booking_row(b["ref"]).hold_state == "authorized" and env.stripe.authorized() == 11_100
    assert len(_mails(env, CLIENT, "temporary hold")) == 1


# -----------------------------------------------------------------------------
# The hold is refused
# -----------------------------------------------------------------------------

def test_a_refused_hold_asks_the_client_for_another_card_once(client, env):
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(HOLD_AT)
    env.stripe.card = "declined"
    out = tick(client)
    assert out["done"]["hold:hold_failed_notice"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.hold_state, row.charged_cents) == ("confirmed", "failed", 0)

    (mail,) = _mails(env, CLIENT, "Action needed")
    assert mail["subject"] == f"Action needed: your card for your consulting call ({b['ref']})"
    assert "$111" in mail["html"] and "Nothing was charged" in mail["html"]
    assert "Your card was declined." in mail["html"]
    assert f'href="https://proreadyengineer.com/consult/booking/{b["ref"]}?t={b["token"]}"' in mail["html"]
    # until two hours before the call, on their clock
    assert "Wednesday, June 11, 2031 at 1:00 PM BST (Europe/London)" in mail["html"]
    (alert,) = _mails(env, OWNER, "refused")
    assert alert["subject"] == "[Consulting] The hold on the card was refused: Casey Client"
    assert "Your card was declined." in alert["html"] and "cancelled automatically" in alert["html"]
    assert "Wednesday, June 11, 2031 at 8:00 AM EDT" in alert["html"]             # the same moment, his clock

    v = _view(client, b)
    assert v["status"] == "confirmed" and v["card_problem"] is True and v["can_replace_card"] is True
    assert "card_requested" in events_of(b["id"])

    # More ticks: the card is not tried again and nobody is emailed again.
    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert env.stripe.count("PaymentIntent.create") == 1
    assert len(_mails(env, CLIENT, "Action needed")) == 1 and len(_mails(env, OWNER, "refused")) == 1


def test_a_replaced_card_gets_the_hold_at_once(client, env):
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "declined"
    tick(client)
    env.outbox.clear()
    env.stripe.card = "ok"
    env.clock.advance(hours=3)
    assert _replace_card(client, env, b, brand="mastercard", last4="5454").status_code == 200

    row = booking_row(b["ref"])
    assert (row.status, row.hold_state, row.hold_cents, row.hold_error) == ("confirmed", "authorized", 11_100, "")
    holds = [c for c in charges_of(b["id"]) if c.kind == "hold"]
    assert [(c.attempt, c.status) for c in holds] == [(1, "failed"), (2, "authorized")]
    assert holds[1].payment_method_id != holds[0].payment_method_id               # the new card
    assert env.stripe.authorized() == 11_100 and env.stripe.money_taken() == 0
    (mail,) = _mails(env, CLIENT, "temporary hold")
    assert "Mastercard ending 5454" in mail["html"]
    v = _view(client, b)
    assert v["card_problem"] is False and v["status"] == "confirmed"
    env.clock.advance(minutes=5)
    assert tick(client)["done"] == {}
    assert env.stripe.count("PaymentIntent.create") == 2


def test_a_replacement_card_that_is_refused_too_is_asked_about_again(client, env):
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "declined"
    tick(client)
    env.clock.advance(hours=1)
    _replace_card(client, env, b, last4="0002")                    # still declined
    row = booking_row(b["ref"])
    assert (row.status, row.hold_state) == ("confirmed", "failed")
    assert len(_mails(env, CLIENT, "Action needed")) == 2          # one per card, not one per tick
    assert "ending 0002" in _mails(env, CLIENT, "Action needed")[1]["html"]
    assert [c.status for c in charges_of(b["id"])] == ["failed", "failed"]
    env.clock.advance(minutes=5)
    tick(client)
    assert len(_mails(env, CLIENT, "Action needed")) == 2 and env.stripe.count("PaymentIntent.create") == 2


def test_a_card_that_needs_its_owner_is_asked_about_in_those_words(client, env):
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "auth"
    tick(client)
    assert booking_row(b["ref"]).hold_state == "requires_action"
    (mail,) = _mails(env, CLIENT, "Action needed")
    assert "wants you to approve this payment yourself" in mail["html"]


def test_a_hold_still_refused_two_hours_before_cancels_the_booking(client, env):
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "declined"
    tick(client)
    env.outbox.clear()

    env.clock.set(START - timedelta(hours=2, minutes=1))           # one minute left to put it right
    assert tick(client)["done"] == {}
    assert booking_row(b["ref"]).status == "confirmed" and len(env.google.events) == 1

    env.clock.set(START - timedelta(hours=2))
    out = tick(client)
    assert out["ok"] is True and out["done"]["hold:cancelled"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.cancelled_by, row.cancel_fee_cents, row.settlement) == ("cancelled", "system", 0, "")
    assert "2 hours before the call" in row.cancel_note
    assert row.charged_cents == 0 and env.stripe.money_taken() == 0 and env.stripe.authorized() == 0
    assert env.google.events == {}                                 # the event is gone (Google tells the guest)
    assert iso(START) in slot_starts(client) or iso(START + timedelta(days=1)) in slot_starts(client)
    # the time itself is inside the 2-hour notice now; the day's count is free again
    db = SessionLocal()
    assert consult.consult_blocks(db, consult.utcnow()) == []
    db.close()

    (mail,) = to(env.outbox, CLIENT)
    assert mail["subject"] == f"Your consulting call is cancelled ({b['ref']})"
    assert "could not place the temporary hold on your card" in mail["html"]
    assert "Nothing was charged" in mail["html"] and "book again with another card" in mail["html"]
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] Cancelled automatically: no hold could be placed: Casey Client"
    assert "Your card was declined." in alert["html"] and "Nothing was charged" in alert["html"]

    v = _view(client, b)
    assert v["status"] == "cancelled" and v["charged_cents"] is None and v["can_replace_card"] is False
    # and again: nothing more
    env.clock.advance(minutes=5)
    assert tick(client)["done"] == {}
    assert len(to(env.outbox, CLIENT)) == 1 and len(to(env.outbox, OWNER)) == 1
    assert events_of(b["id"]).count("cancelled") == 1


def test_a_hold_refused_inside_two_hours_cancels_at_once(client, env):
    """Booked at the two-hour limit; the card is saved five minutes later
    and refuses the hold. There is no time left to ask for another card."""
    soon = ny(2031, 6, 2, 12)                                      # exactly two hours from now
    data = book(client, soon).json()
    env.clock.advance(minutes=5)
    env.stripe.card = "declined"
    assert save_card(client, env, data["ref"]).status_code == 200  # Stripe still gets its 200
    row = booking_row(data["ref"])
    assert (row.status, row.cancelled_by, row.hold_state) == ("cancelled", "system", "failed")
    assert env.stripe.money_taken() == 0 and env.google.events == {}
    assert subjects(env.outbox, CLIENT) == [
        f"Your consulting call is confirmed ({data['ref']})",
        f"Your consulting call is cancelled ({data['ref']})",
    ]
    assert _mails(env, CLIENT, "Action needed") == []
    new, cancelled = subjects(env.outbox, OWNER)
    assert new.startswith("[Consulting] New booking: Casey Client")
    assert cancelled == "[Consulting] Cancelled automatically: no hold could be placed: Casey Client"
    assert tick(client)["done"] == {}


def test_a_refused_hold_never_cancels_a_call_that_has_started(client, env):
    """The tick was down from the refusal until after the start. The call
    took place (or not): that is for the outcome to say, not for the hold."""
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "declined"
    tick(client)
    env.clock.set(START + timedelta(minutes=10))
    tick(client)
    row = booking_row(b["ref"])
    assert row.status == "confirmed" and row.cancelled_at is None and len(env.google.events) == 1


def test_the_hold_steps_themselves_refuse_what_the_tick_never_asks_of_them(client, env):
    """The tick's own queries already leave these bookings alone. The steps
    are called directly here, as a second tick running a moment too late or
    a future caller might: they must refuse by themselves."""
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    env.stripe.card = "declined"
    tick(client)
    assert booking_row(b["ref"]).hold_state == "failed" and env.stripe.count("PaymentIntent.create") == 1
    db = SessionLocal()
    # a refused hold is not placed again on the same card
    env.stripe.card = "ok"
    assert consult_auto.place_due_hold(db, b["id"]) == "closed"
    assert env.stripe.count("PaymentIntent.create") == 1 and booking_row(b["ref"]).hold_state == "failed"
    # and once the call has started, a refused hold cancels nothing
    env.clock.set(START + timedelta(minutes=1))
    assert consult_auto.follow_hold(db, b["id"]) == "failed"
    assert consult_auto.hold_after_card(db, b["id"], replaced=True) == "closed"
    db.close()
    row = booking_row(b["ref"])
    assert row.status == "confirmed" and row.cancelled_at is None and len(env.google.events) == 1


def test_no_new_hold_is_placed_once_the_call_has_started(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START + timedelta(minutes=1))                    # the tick never ran before the start
    tick(client)
    assert booking_row(b["ref"]).hold_state == "" and env.stripe.count("PaymentIntent.create") == 0


def test_the_owner_cancelling_releases_a_hold_the_tick_placed(client, env):
    b = confirmed(client, env, START)
    env.clock.set(HOLD_AT)
    tick(client)
    assert env.stripe.authorized() == 11_100
    r = client.post(f"{ADMIN_API}/bookings/{b['id']}/cancel", headers=ADMIN, json={"note": "Unwell."})
    assert r.status_code == 200 and r.json()["hold_state"] == "released"
    assert env.stripe.authorized() == 0 and env.stripe.money_taken() == 0


# -----------------------------------------------------------------------------
# Reminders
# -----------------------------------------------------------------------------

FIRST_AT = START - timedelta(hours=48)       # 24 hours before free cancellation ends
LAST_AT = START - timedelta(hours=1)


def test_the_first_reminder_goes_two_days_before_while_cancelling_is_still_free(client, env):
    b = confirmed(client, env, START)
    row = booking_row(b["ref"])
    assert aware(row.free_cancel_until) == START - timedelta(hours=24)
    env.outbox.clear()
    env.clock.set(FIRST_AT - timedelta(minutes=1))
    tick(client)
    assert _mails(env, CLIENT, "Reminder") == []
    env.clock.set(FIRST_AT)
    assert tick(client)["done"]["reminder_first"] == 1
    (mail,) = to(env.outbox, CLIENT)
    assert mail["subject"] == f"Reminder: your consulting call is in two days ({b['ref']})"
    assert "A reminder that your consulting call with " in mail["html"] and " is in two days." in mail["html"]
    assert "Wednesday, June 11, 2031 at 3:00 PM BST (Europe/London)" in mail["html"]
    assert f'href="{row.meet_url}"' in mail["html"] and "60 minutes" in mail["html"]
    assert f"/consult/booking/{b['ref']}?t={b['token']}" in mail["html"]
    assert "export-controlled" in mail["html"]
    # a whole day is left to cancel at no charge, and the email says until when and what follows
    assert (
        "You can cancel free of charge until Tuesday, June 10, 2031 at 3:00 PM BST (Europe/London). "
        "After that the 20% fee ($22.20) applies, as set out in your booking terms."
    ) in mail["html"]
    assert "If you need to cancel now" not in mail["html"]
    assert "$111" not in mail["html"]                              # their own fee, nothing else about money
    for _ in range(4):
        env.clock.advance(minutes=5)
        tick(client)
    assert len(to(env.outbox, CLIENT)) == 1
    assert booking_row(b["ref"]).reminder_24h_sent_at is not None
    assert events_of(b["id"]).count("reminder_sent") == 1
    # nothing more is sent when the free time ends, a day before the call
    env.clock.set(HOLD_AT - timedelta(minutes=5))
    tick(client)
    assert len(to(env.outbox, CLIENT)) == 1


def test_no_reminder_is_sent_at_the_moment_free_cancellation_ends(client, env):
    """The old design reminded at exactly 24 hours before: the moment the
    client could no longer cancel at no charge. Nothing but the hold notice
    leaves at that time now."""
    b = confirmed(client, env, START)
    env.clock.set(FIRST_AT)
    tick(client)
    env.outbox.clear()
    env.clock.set(HOLD_AT)
    out = tick(client)["done"]
    assert "reminder_first" not in out and "reminder_last" not in out
    assert subjects(env.outbox, CLIENT) == [
        f"A temporary hold is on your card for your consulting call ({b['ref']})"]


def test_a_first_reminder_that_is_late_uses_the_words_of_its_own_day(client, env):
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=30))                     # the tick was down for 18 hours
    assert tick(client)["done"]["reminder_first"] == 1
    (mail,) = to(env.outbox, CLIENT)
    assert mail["subject"] == f"Reminder: your consulting call is tomorrow ({b['ref']})"
    assert "You can cancel free of charge until Tuesday, June 10, 2031 at 3:00 PM BST" in mail["html"]


def test_a_first_reminder_too_late_to_be_of_use_is_not_sent(client, env):
    """Under two hours before the free time ends, a "you can still cancel
    free" email would arrive too late to act on: it is dropped, not sent at
    the deadline."""
    b = confirmed(client, env, START)
    env.outbox.clear()
    for at in (
        START - timedelta(hours=26),                               # exactly two hours left: the window has closed
        START - timedelta(hours=25), HOLD_AT - timedelta(minutes=1), HOLD_AT + timedelta(minutes=1),
        START - timedelta(hours=20),
    ):
        env.clock.set(at)
        assert "reminder_first" not in tick(client)["done"], at
    assert _mails(env, CLIENT, "Reminder") == [] and booking_row(b["ref"]).reminder_24h_sent_at is None
    env.clock.set(LAST_AT)
    assert tick(client)["done"]["reminder_last"] == 1               # the last one is not affected


def test_just_inside_the_first_reminders_time_it_is_still_sent(client, env):
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=26, minutes=1))
    assert tick(client)["done"]["reminder_first"] == 1
    assert len(_mails(env, CLIENT, "Reminder")) == 1


def test_the_last_reminder_goes_an_hour_before_once(client, env):
    b = confirmed(client, env, START)
    env.clock.set(FIRST_AT)
    tick(client)
    env.clock.set(HOLD_AT)
    tick(client)
    env.outbox.clear()
    env.clock.set(LAST_AT - timedelta(minutes=1))
    tick(client)
    assert to(env.outbox, CLIENT) == []
    env.clock.set(LAST_AT)
    assert tick(client)["done"]["reminder_last"] == 1
    (mail,) = to(env.outbox, CLIENT)
    assert mail["subject"] == f"Your consulting call starts in about an hour ({b['ref']})"
    assert "starts in about an hour" in mail["html"] and booking_row(b["ref"]).meet_url in mail["html"]
    # cancelling is no longer free by now, and the email does not pretend otherwise
    assert "If you need to cancel now, the 20% fee ($22.20) applies" in mail["html"]
    assert "free of charge" not in mail["html"]
    env.clock.advance(minutes=30)
    tick(client)
    env.clock.set(START + timedelta(minutes=1))
    tick(client)
    assert len(to(env.outbox, CLIENT)) == 1
    assert events_of(b["id"]).count("reminder_sent") == 2          # the first one and this one


def test_a_call_booked_the_same_day_gets_only_the_last_reminder(client, env):
    today = ny(2031, 6, 2, 15)                                     # five hours ahead
    b = confirmed(client, env, today)
    env.outbox.clear()
    tick(client)
    env.clock.set(today - timedelta(hours=3))
    tick(client)
    assert to(env.outbox, CLIENT) == []                            # no first reminder five hours before
    env.clock.set(today - timedelta(minutes=55))
    tick(client)
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call starts in about an hour ({b['ref']})"]
    assert booking_row(b["ref"]).reminder_24h_sent_at is None


def test_a_call_booked_too_late_for_the_first_reminder_gets_none(client, env):
    """Booked after the first reminder's time (or minutes before it): the
    confirmation email has just told them the deadline. No first reminder,
    then or later."""
    # 40 hours ahead: the reminder's time was eight hours ago, the free time has 16 hours left
    env.clock.set(START - timedelta(hours=40))
    late = confirmed(client, env, START)
    confirmation = to(env.outbox, CLIENT)[-1]                      # it has just told them the deadline
    assert "You can cancel free of charge until Tuesday, June 10, 2031 at 3:00 PM BST" in confirmation["html"]
    # ten minutes before the reminder's time
    env.clock.set(ny(2031, 6, 10, 13, 50))
    close = confirmed(client, env, ny(2031, 6, 12, 14), email="close@example.com", ip="203.0.113.8")
    env.outbox.clear()
    for at in (ny(2031, 6, 10, 14), ny(2031, 6, 10, 15), ny(2031, 6, 10, 20), ny(2031, 6, 11, 8)):
        env.clock.set(at)
        assert "reminder_first" not in tick(client)["done"], at
    assert _mails(env, CLIENT, "Reminder") == [] and _mails(env, "close@example.com", "Reminder") == []
    assert booking_row(late["ref"]).reminder_24h_sent_at is None
    assert booking_row(close["ref"]).reminder_24h_sent_at is None


def test_a_call_booked_forty_minutes_before_the_first_reminders_time_gets_it(client, env):
    env.clock.set(ny(2031, 6, 10, 13, 20))
    confirmed(client, env, ny(2031, 6, 12, 14), email="early@example.com", ip="203.0.113.9")
    env.outbox.clear()
    env.clock.set(ny(2031, 6, 10, 14))
    assert tick(client)["done"]["reminder_first"] == 1
    assert len(_mails(env, "early@example.com", "Reminder")) == 1


def test_the_reminder_times_are_settings_shown_and_changed_from_the_admin(client, env):
    shown = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert shown["reminder_before_deadline_hours"] == 24 and shown["reminder_before_start_hours"] == 1
    saved = client.put(
        f"{ADMIN_API}/settings", headers=ADMIN,
        json={"reminder_before_deadline_hours": 48, "reminder_before_start_hours": 3},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["reminder_before_deadline_hours"] == 48 and saved.json()["reminder_before_start_hours"] == 3
    assert client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()["reminder_before_deadline_hours"] == 48
    others = {k: v for k, v in shown.items() if not k.startswith("reminder_before_")}
    assert {k: v for k, v in saved.json().items() if k in others} == others     # nothing else moved
    # with those: the first one 72 hours before the start, the last one three hours before
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=72, minutes=1))
    assert tick(client)["done"] == {}
    env.clock.set(START - timedelta(hours=72))
    assert tick(client)["done"] == {"reminder_first": 1}
    assert subjects(env.outbox, CLIENT) == [f"Reminder: your consulting call is in three days ({b['ref']})"]
    env.clock.set(HOLD_AT)
    tick(client)
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=3, minutes=1))
    assert tick(client)["done"] == {}
    env.clock.set(START - timedelta(hours=3))
    assert tick(client)["done"] == {"reminder_last": 1}
    assert subjects(env.outbox, CLIENT) == [f"Your consulting call starts in about 3 hours ({b['ref']})"]


@pytest.mark.parametrize("field, value", [
    ("reminder_before_deadline_hours", 0), ("reminder_before_deadline_hours", -1),
    ("reminder_before_deadline_hours", 169), ("reminder_before_start_hours", 0),
    ("reminder_before_start_hours", 49),
])
def test_a_reminder_time_out_of_range_is_refused_and_nothing_is_saved(client, env, field, value):
    before = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    answer = client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={field: value})
    assert answer.status_code in (409, 422), answer.text
    assert client.get(f"{ADMIN_API}/settings", headers=ADMIN).json() == before


def test_the_reminder_words_follow_the_clients_own_calendar(client, env):
    from zoneinfo import ZoneInfo

    words = consult_auto._days_away
    start = ny(2031, 6, 11, 10)                                    # Wed 23:00 in Tokyo, Wed 04:00 in Honolulu
    assert words(start, start - timedelta(hours=48), "Asia/Tokyo") == "in two days"
    assert words(start, start - timedelta(hours=48), "Pacific/Honolulu") == "in two days"
    assert words(start, start - timedelta(hours=30), "Asia/Tokyo") == "tomorrow"       # Tue 17:00 there
    assert words(start, start - timedelta(hours=30), "Pacific/Honolulu") == "in two days"   # Mon 22:00 there
    assert words(start, start - timedelta(hours=3), "Europe/London") == "today"
    assert words(start, start - timedelta(hours=72), "Europe/London") == "in three days"
    assert words(start, start - timedelta(days=12), "Europe/London") == "in 12 days"
    assert words(start, start - timedelta(hours=48), "Not/AZone") == "in two days"      # falls back to UTC
    assert ZoneInfo("Asia/Tokyo")                                   # the zones named above exist here
    soon = consult_auto._soon
    assert soon(timedelta(minutes=60)) == "in about an hour" and soon(timedelta(minutes=50)) == "in about an hour"
    assert soon(timedelta(hours=3)) == "in about 3 hours" and soon(timedelta(minutes=100)) == "in about 2 hours"
    assert soon(timedelta(minutes=27)) == "in about 25 minutes" and soon(timedelta(minutes=1)) == "in about 5 minutes"


def test_a_cancelled_call_gets_no_reminder_and_no_hold(client, env):
    b = confirmed(client, env, START)
    client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    env.outbox.clear()
    for at in (HOLD_AT, START - timedelta(hours=1), START + timedelta(hours=4)):
        env.clock.set(at)
        assert tick(client)["done"] == {}
    assert env.outbox == [] and env.stripe.count("PaymentIntent.create") == 0


def test_a_reminder_that_did_not_go_out_is_sent_by_the_next_tick(client, env, monkeypatch):
    b = confirmed(client, env, START)
    env.outbox.clear()
    env.clock.set(FIRST_AT)

    class Refused(_Resp):
        status_code = 500
        text = "upstream error"

    real = E._resend_post
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: Refused())
    out = tick(client)
    assert "reminder_first" not in out["done"] and booking_row(b["ref"]).reminder_24h_sent_at is None
    monkeypatch.setattr(E, "_resend_post", real)
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["reminder_first"] == 1
    assert len(_mails(env, CLIENT, "Reminder")) == 1


def test_the_copies_kept_in_the_email_log_hide_the_manage_link(client, env):
    b = confirmed(client, env, START)
    for at in (FIRST_AT, HOLD_AT, LAST_AT):
        env.clock.set(at)
        tick(client)
    db = SessionLocal()
    mine = ("consult_reminder_first", "consult_hold_placed", "consult_reminder_last")
    kept = db.query(EmailLog).filter(EmailLog.template.in_(mine)).all()
    assert sorted(k.template for k in kept) == sorted(mine)
    for row in kept:
        assert row.recipient == CLIENT and row.scope_code == "consult" and row.audience == "client"
        assert b["token"] not in row.body_html and b["token"] not in row.body_text
        assert f"/consult/booking/{b['ref']}?t=(hidden)" in row.body_html
    db.close()


# -----------------------------------------------------------------------------
# Repairs
# -----------------------------------------------------------------------------

def test_a_calendar_event_google_refused_is_created_by_a_later_tick(client, env):
    env.google.event_fails = True
    data = book(client, START).json()
    save_card(client, env, data["ref"])
    row = booking_row(data["ref"])
    assert row.status == "confirmed" and row.google_event_id == ""
    assert "tried again every few minutes" in _mails(env, OWNER, "New booking")[0]["html"]
    env.outbox.clear()
    for _ in range(3):                                              # still refused: tried, quietly
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert events_of(row.id).count("calendar_event_failed") == 1   # one line on the timeline, not four
    assert env.outbox == []

    env.google.event_fails = False
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["calendar:created"] == 1
    row = booking_row(data["ref"])
    assert row.google_event_id and row.meet_url.startswith("https://meet.google.com/")
    assert len(env.google.events) == 1
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] The meeting is on your calendar now: Casey Client"
    assert row.meet_url in alert["html"]
    env.clock.advance(minutes=5)
    tick(client)
    assert len(env.google.events) == 1 and len(to(env.outbox, OWNER)) == 1


def test_a_cancellation_cut_short_is_finished_by_the_tick(client, env, monkeypatch):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=2, minutes=30))
    env.outbox.clear()
    real_finish = consult.finish_cancellation
    monkeypatch.setattr(consult, "finish_cancellation", lambda db, booking_id: (_ for _ in ()).throw(RuntimeError("died")))
    with pytest.raises(RuntimeError):
        client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    monkeypatch.setattr(consult, "finish_cancellation", real_finish)
    assert booking_row(b["ref"]).status == "cancelled" and env.stripe.money_taken() == 0

    env.clock.advance(minutes=1)
    assert tick(client)["done"] == {}                              # too soon to call it cut short
    env.clock.advance(minutes=2)
    assert tick(client)["done"]["cancellation_finished"] == 1
    assert env.stripe.money_taken() == 2_220 and env.google.events == {}
    assert len(to(env.outbox, CLIENT)) == 1 and len(_mails(env, OWNER, "cancelled late")) == 1
    env.clock.advance(minutes=5)
    assert tick(client)["done"] == {}
    assert env.stripe.money_taken() == 2_220 and len(to(env.outbox, CLIENT)) == 1


def test_the_tick_records_bookings_whose_card_never_came(client, env):
    data = book(client, START).json()
    env.clock.advance(minutes=21)
    assert tick(client)["done"]["expired"] == 1
    assert booking_row(data["ref"]).status == "expired"
    assert "expired" not in tick(client)["done"]


def test_one_booking_that_fails_does_not_stop_the_others(client, env, monkeypatch):
    bad = confirmed(client, env, START, email="bad@example.com", ip="203.0.113.1")
    good = confirmed(client, env, ny(2031, 6, 11, 14), email="good@example.com", ip="203.0.113.2")
    env.outbox.clear()
    env.clock.set(ny(2031, 6, 10, 14))                             # both holds are due
    real = consult_auto.place_due_hold

    def flaky(db, booking_id, **kw):
        if booking_id == bad["id"]:
            raise RuntimeError("this one booking is broken")
        return real(db, booking_id, **kw)

    monkeypatch.setattr(consult_auto, "place_due_hold", flaky)
    out = tick(client)
    assert out["ok"] is False and len(out["problems"]) == 1
    assert f"booking {bad['id']}" in out["problems"][0] and "broken" in out["problems"][0]
    assert booking_row(good["ref"]).hold_state == "authorized"     # the other one went through
    monkeypatch.setattr(consult_auto, "place_due_hold", real)
    env.clock.advance(minutes=5)
    assert tick(client)["ok"] is True
    assert booking_row(bad["ref"]).hold_state == "authorized"      # and the broken one, next time


# -----------------------------------------------------------------------------
# Idempotency: the second tick changes nothing
# -----------------------------------------------------------------------------

def test_a_second_tick_right_after_the_first_changes_nothing_at_any_point(client, env):
    """Five bookings in different situations, walked in 35-minute steps from
    two days before to the evening after (both reminders, holds, refusals, a
    replaced card, the automatic cancellation, and on past the meetings to
    the summary and the automatic charge). At every step the tick runs twice:
    the first run may act, the second must leave every row, email and Stripe
    call exactly as it found them."""
    ok = confirmed(client, env, START, email="ok@example.com", ip="203.0.113.1")
    declined = confirmed(client, env, ny(2031, 6, 11, 13), email="declined@example.com", ip="203.0.113.2")
    replaced = confirmed(client, env, ny(2031, 6, 11, 16), email="replaced@example.com", ip="203.0.113.3")
    gone = confirmed(client, env, ny(2031, 6, 11, 19), email="gone@example.com", ip="203.0.113.4")
    pending = book(client, ny(2031, 6, 12, 10), email="pending@example.com", ip="203.0.113.5").json()
    client.post(f"{PUBLIC}/booking/{gone['ref']}/cancel", json={"t": gone["token"]})

    acted = 0
    card_replaced = False
    tz = consult.zone(_settings())
    at = ny(2031, 6, 9, 9, 20)
    while at <= ny(2031, 6, 11, 21):
        env.clock.set(at)
        # the cards behave differently per booking: the 13:00 and 16:00
        # calls have their holds refused the day before
        local = at.astimezone(tz)
        env.stripe.card = "declined" if (local.day == 10 and local.hour in (13, 16)) else "ok"
        if not card_replaced and at >= ny(2031, 6, 10, 18):
            _replace_card(client, env, replaced, last4="1881")
            card_replaced = True
        first = tick(client)
        assert first["ok"] is True, first
        acted += bool(first["done"])
        before = state_of_everything(env)
        second = tick(client)
        assert second["done"] == {} and second["problems"] == [], (at, second)
        assert state_of_everything(env) == before, at
        at += timedelta(minutes=35)

    assert acted >= 13                                              # the walk did exercise the tick
    rows = {name: booking_row(b["ref"]) for name, b in
            (("ok", ok), ("declined", declined), ("replaced", replaced), ("gone", gone))}
    assert rows["ok"].reminder_24h_sent_at and rows["ok"].reminder_1h_sent_at and rows["ok"].summary_sent_at
    assert (rows["ok"].status, rows["ok"].hold_state, rows["ok"].charged_cents) == ("completed", "captured", 11_100)
    assert (rows["declined"].status, rows["declined"].cancelled_by) == ("cancelled", "system")
    assert (rows["replaced"].status, rows["replaced"].hold_state, rows["replaced"].charged_cents) == (
        "completed", "captured", 11_100)
    assert rows["gone"].status == "cancelled" and rows["gone"].hold_state == ""
    assert booking_row(pending["ref"]).status == "expired"
    # two calls took place and were charged once each; no hold is left standing
    assert env.stripe.money_taken() == 11_100 * 2 and env.stripe.authorized() == 0
    assert len(env.stripe.payment_intents) == 4                    # two refused holds, two captured ones
    for b in (ok, declined, replaced, gone):
        client_subjects = subjects(env.outbox, booking_row(b["ref"]).email)
        assert len(client_subjects) == len(set(client_subjects)), client_subjects   # no email twice
    # the three open calls were each reminded two days before; the cancelled one never
    for b, n in ((ok, 1), (declined, 1), (replaced, 1), (gone, 0)):
        addr = booking_row(b["ref"]).email
        assert len([x for x in subjects(env.outbox, addr) if "is in two days" in x]) == n, addr


def _settings():
    db = SessionLocal()
    try:
        cs = consult.settings_row(db)
        db.expunge(cs)
        return cs
    finally:
        db.close()


def test_two_ticks_at_the_same_instant_do_the_work_of_one(client, env):
    import threading

    b = confirmed(client, env, START)
    env.outbox.clear()

    def storm() -> None:
        go = threading.Barrier(4)
        results: list = []

        def run() -> None:
            db = SessionLocal()
            try:
                go.wait(timeout=10)
                results.append(consult_auto._tick(db, consult.utcnow()))   # past the in-process lock, on purpose
            except Exception as exc:  # noqa: BLE001
                results.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert all(isinstance(r, dict) for r in results), results

    env.clock.set(FIRST_AT)
    storm()
    assert len(_mails(env, CLIENT, "Reminder")) == 1 and events_of(b["id"]).count("reminder_sent") == 1
    env.clock.set(HOLD_AT)
    storm()
    assert len(env.stripe.payment_intents) == 1 and env.stripe.authorized() == 11_100
    assert events_of(b["id"]).count("hold_placed") == 1
    assert len(_mails(env, CLIENT, "temporary hold")) == 1 and len(_mails(env, CLIENT, "Reminder")) == 1
