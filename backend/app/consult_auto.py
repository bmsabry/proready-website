"""Consulting calls: everything that happens by itself after a booking is
confirmed.

  the hold        an authorization for the booked amount, `hold_lead_hours`
                  before the start (at once, when the card is saved inside
                  that time). Refused: the client is asked for another card
                  and the hold is tried again when they save one. Still
                  refused HOLD_FAIL_CANCEL_HOURS before the start: the call
                  is cancelled, the time released, both sides told.
  reminders       to the client: the first while cancelling is still free
                  (24 hours before the free-cancellation deadline, so 48
                  hours before the start with the default terms), the last
                  an hour before the start. Both lead times are settings.
  attendance      at the scheduled end, from the Google Meet REST API
                  (conference records for the meeting code, then their
                  participants). Without the Meet permission, or when Google
                  will not answer, it is 'unknown'.
  the summary     to the owner at the scheduled end: who joined, what will
                  happen by itself and when, and three links to decide
                  otherwise. A link is signed, expires when the automatic
                  outcome runs, and is spent by the first choice; opening it
                  shows a page and changes nothing (mail scanners open links),
                  only the button on that page acts.
  the outcome     `auto_settle_hours` after the scheduled end, unless he
                  chose: both joined, charge; client absent, the fee; host
                  absent, nothing; unknown, charge.
  disputes        a Stripe dispute on a consulting payment goes on the
                  booking's timeline and to the owner.

`run_tick` drives all of it. A cron job calls it every five minutes
(POST /api/admin/consult/tick). Every step is written to be repeated: it
reads the state, does what the state still lacks, and records that it did.
Emails are sent by the one call that claims the booking's marker for them
(an UPDATE that only succeeds while the marker is empty), and the marker is
given back when the email did not go out, so the next tick tries again.

Money is never moved here. Every hold, charge and release goes through
consult_money, by way of consult.settle / consult.cancel_by_owner.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import Session

from . import consult
from . import consult_money as money
from . import exam_calendar as xcal
from .config import get_settings
from .consult_models import ConsultBooking, ConsultBookingEvent, ConsultCharge
from .consult_money import add_event, aware
from .emailer import (
    consult_hold_failed_html,
    consult_hold_placed_html,
    consult_owner_summary_html,
    consult_reminder_html,
    send_email,
)
from .models import ExamCalendar

log = logging.getLogger(__name__)

# A booking whose hold is still refused this long before the start is
# cancelled (at once, when the refusal comes later than that).
HOLD_FAIL_CANCEL_HOURS = 2
# The two client reminders. When each goes out is a setting
# (reminder_before_deadline_hours, reminder_before_start_hours); the marker
# columns keep the names of the first design.
REMINDER_COLUMN = {"first": "reminder_24h_sent_at", "last": "reminder_1h_sent_at"}
# A reminder is skipped when the booking was confirmed less than this long
# before it would go out: the confirmation email has only just arrived.
REMINDER_MIN_GAP = timedelta(minutes=30)
# The first reminder exists to leave the client time to cancel at no charge.
# Late (the tick was down), it is not sent once less than this is left before
# the free-cancellation deadline (or less than half its lead time, if shorter).
REMINDER_FIRST_MIN_LEFT = timedelta(hours=2)
# Someone else in the meeting counts as the client only if they were in the
# call together with the host for at least this long (in all). A device that
# connected for a moment, or someone who came after the host had left, does
# not make the call "both joined".
CLIENT_MIN_OVERLAP = timedelta(minutes=5)
# Conference records count for a booking when they overlap its time by this
# much on either side (a link opened to try it the day before does not).
ATTENDANCE_WINDOW = timedelta(hours=1)
# Attendance is not asked for any more this long after the scheduled end.
ATTENDANCE_GIVE_UP = timedelta(days=3)
# A release Stripe did not confirm is asked again this many times, then left
# to lapse by itself.
RELEASE_RETRY_LIMIT = 6

MEET_API = "https://meet.googleapis.com/v2"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_MEET_CODE = re.compile(r"meet\.google\.com/([a-z0-9][a-z0-9-]{2,60})", re.I)

# What happens by itself, by who joined.
DEFAULT_OUTCOME = {"both": "charge", "client_absent": "no_show", "host_absent": "waive", "unknown": "charge"}
ATTENDANCE_WORDS = {
    "both": "You and at least one other participant joined",
    "client_absent": "You joined; nobody else did",
    "host_absent": "Google Meet has no record of you joining",
    "unknown": "Not known",
}
CHOICE_WORDS = {"charge": "Charge in full", "no_show": "No-show fee", "waive": "Do not charge"}

_TICK_LOCK = threading.Lock()


# -----------------------------------------------------------------------------
# Small tools
# -----------------------------------------------------------------------------

def _load(db: Session, booking_id: int) -> ConsultBooking | None:
    """The booking as the database has it now (never a stale copy)."""
    return db.execute(
        select(ConsultBooking).where(ConsultBooking.id == booking_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _claim(db: Session, booking_id: int, column: str, now: datetime, **also) -> bool:
    """Set an empty marker column. True for the one caller that set it: that
    caller sends the email the marker stands for."""
    done = db.execute(
        update(ConsultBooking)
        .where(ConsultBooking.id == booking_id, getattr(ConsultBooking, column).is_(None))
        .values({column: now, **also})
    )
    db.commit()
    return done.rowcount == 1


def _unclaim(db: Session, booking_id: int, column: str, **also) -> bool:
    """Give a marker back, so that the next tick sends the email it stands
    for: the email service refused it or could not be reached. Where no
    email service is set up at all (a development machine) there is nothing
    to try again, and the marker is kept. True when it was given back."""
    if not get_settings().RESEND_API_KEY:
        return False
    db.execute(
        update(ConsultBooking).where(ConsultBooking.id == booking_id).values({column: None, **also})
    )
    db.commit()
    return True


def _to_client(db: Session, booking: ConsultBooking, *, subject: str, html: str, template: str) -> bool:
    return send_email(
        to=booking.email, subject=subject, html=html, db=db,
        scope_kind="system", scope_code="consult", audience="client", template=template,
    )


def _manage_url(db: Session, booking: ConsultBooking) -> str:
    return consult.booking_url(booking, consult.manage_token(db, booking))


def _note(db: Session, booking_id: int, kind: str, *, actor: str = "auto", note: str = "",
          amount_cents: int | None = None, data: dict | None = None) -> None:
    booking = _load(db, booking_id)
    if booking is not None:
        add_event(db, booking, kind, actor=actor, note=note, amount_cents=amount_cents, data=data)
        db.commit()


def _note_once(db: Session, booking_id: int, kind: str, *, note: str = "",
               amount_cents: int | None = None, data: dict | None = None) -> bool:
    """Write a timeline line of this kind unless the booking already has
    one. True for the one caller that wrote it (who then tells the owner)."""
    with consult._STATE_MUTEX:
        booking = money.lock_booking(db, booking_id)
        if booking is None:
            return False
        seen = db.execute(
            select(ConsultBookingEvent.id).where(
                ConsultBookingEvent.booking_id == booking_id, ConsultBookingEvent.kind == kind,
            )
        ).first()
        if seen is not None:
            db.commit()
            return False
        add_event(db, booking, kind, actor="auto", note=note, amount_cents=amount_cents, data=data)
        db.commit()
        return True


def owner_actor() -> str:
    """Who the timeline names when the owner decides from his email."""
    return f"{get_settings().ADMIN_EMAIL or 'owner'} (email link)"


def _ask_for_review(db: Session, booking_id: int, what: str) -> bool:
    """A hold or a charge was sent to Stripe, no answer ever came back, and
    it is too late to ask again safely (consult_money parks it as 'needs
    review'). Nobody pressed a button, so nobody saw that: tell the owner,
    once per parked attempt. `what`: 'hold' | 'charge'."""
    kind = f"{what}_review_requested"
    with consult._STATE_MUTEX:
        booking = money.lock_booking(db, booking_id)
        parked = [r for r in money.review_rows(db, booking_id) if r.kind == what] if booking is not None else []
        told = set() if not parked else {
            (d or {}).get("ledger_id") for d in db.execute(
                select(ConsultBookingEvent.data).where(
                    ConsultBookingEvent.booking_id == booking_id, ConsultBookingEvent.kind == kind,
                )
            ).scalars().all()
        }
        fresh = [r for r in parked if r.id not in told]
        for row in fresh:
            add_event(db, booking, kind, actor="auto", amount_cents=row.amount_cents,
                      note=f"The owner was asked to look this {what} up in Stripe.",
                      data={"ledger_id": row.id})
        db.commit()
    if not fresh:
        return False
    booking = _load(db, booking_id)
    refused = [r for r in fresh if r.error_code == money.REQUEST_REFUSED]
    if refused:
        # Stripe answered, and what it refused was the request, not the card.
        words = refused[0].error_message or "no reason given"
        consult.notify_owner(
            db, booking, template="consult_owner_needs_review",
            headline=f"Stripe refused the {what} request (not the card)",
            detail=(
                f"Stripe refused the request for this booking's {what} itself: {words}. Nothing was taken or "
                "held, the booking stands, and the client has not been told anything: this is about the "
                "site's Stripe setup, not about their card."
                "\n\n"
                + (
                    "Without a hold, the call's outcome is charged to the card directly. "
                    if what == "hold" else ""
                )
                + "When the cause is put right, open the booking and press \"Not charged\" to clear this "
                "attempt (the site checks with Stripe that nothing was taken); "
                + ("the next run then places the hold again." if what == "hold" else "then press Charge again.")
            ),
            extra_rows=[("Stripe said", words)],
            extra_link=("Open Stripe payments", "https://dashboard.stripe.com/payments"),
        )
        return True
    closed = booking.status != "confirmed" or bool(booking.settlement)
    if what == "hold" and any(r.error_code == "captured_elsewhere" for r in fresh):
        headline = "A hold was captured in Stripe by hand"
        detail = (
            "A hold for this booking got no answer when it was placed. Stripe now shows that its "
            "authorization was captured there, which this site did not do: the client has paid that "
            "amount outside this booking, and the booking does not show it."
            "\n\n"
            "If it should not have been taken, refund it in Stripe."
        )
    elif what == "hold" and closed:
        headline = "A hold may still be on the client's card"
        detail = (
            "A hold for this booking was sent to Stripe and no answer was ever recorded. The booking is "
            "closed now, so the hold is not wanted, but Stripe could not confirm that nothing is "
            "authorized on the client's card."
            "\n\n"
            "Look for it in Stripe by the booking reference and cancel it there if it exists. The site "
            "keeps asking as well, and lets it go by itself as soon as Stripe answers. An authorization "
            "that nobody cancels lapses by itself within about a week."
        )
    elif what == "hold":
        headline = "A hold needs checking in Stripe"
        detail = (
            "A hold for this booking was sent to Stripe and no answer ever came back; it is now too "
            "late to ask again safely. If it did go through, the client's card shows a pending "
            "authorization that cannot be captured or released from here: find it in Stripe by the "
            "booking reference and cancel it there. Then open the booking and press \"Not charged\" "
            "to clear it."
            "\n\n"
            "The call itself is not affected. Its outcome will be charged to the card directly."
        )
    else:
        headline = "A charge needs checking in Stripe"
        detail = (
            "A charge for this booking was sent to Stripe and no answer ever came back; it is now too "
            "late to ask again safely, so the booking shows the payment as failed. Look for it in "
            "Stripe by the booking reference."
            "\n\n"
            "Then open the booking and say what you found. \"Paid in Stripe\", with the amount, if "
            "the payment is there: the client has paid and nothing more is owed. \"Not charged\" if "
            "it is not: the Charge button then works again. Either way the site asks Stripe to confirm "
            "before it changes anything."
        )
    consult.notify_owner(
        db, booking, template="consult_owner_needs_review", headline=headline, detail=detail,
        extra_rows=[("Search Stripe for", booking.ref)],
        extra_link=("Open Stripe payments", "https://dashboard.stripe.com/payments"),
    )
    return True


# -----------------------------------------------------------------------------
# The hold
# -----------------------------------------------------------------------------

def hold_deadline(booking: ConsultBooking) -> datetime:
    """Until when a refused hold may still be put right."""
    return aware(booking.start_at) - timedelta(hours=HOLD_FAIL_CANCEL_HOURS)


def _has_pending_hold(db: Session, booking_id: int) -> bool:
    return any(r.kind == "hold" and r.status == "pending" for r in money.ledger(db, booking_id))


def place_due_hold(db: Session, booking_id: int, *, now: datetime | None = None, announce: bool = True) -> str:
    """Place the hold of a confirmed booking if it is due and not yet tried,
    then do what its result calls for (follow_hold). Safe to repeat: a hold
    that exists is returned, not placed again, and an attempt whose answer
    was lost is asked about with the same key."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.status != "confirmed" or booking.settlement or booking.hold_state:
        return "closed"
    due = aware(booking.hold_due_at)
    if due is None or due > now:
        return "not_due"
    if now >= aware(booking.start_at) and not _has_pending_hold(db, booking_id):
        # The call has started: a hold serves nothing now. The outcome is
        # charged to the card directly. (An attempt still unanswered is
        # asked about all the same, so that it does not stay open.)
        return "closed"
    result = money.place_hold(db, booking, actor="auto")
    if result.status == "needs_review":
        _ask_for_review(db, booking_id, "hold")
    return follow_hold(db, booking_id, now=now, announce=announce)


def follow_hold(db: Session, booking_id: int, *, now: datetime | None = None, announce: bool = True) -> str:
    """Act on where the hold stands. Authorized: tell the client, once.
    Refused: ask the client for another card, once per card; from
    HOLD_FAIL_CANCEL_HOURS before the start, cancel instead. Returns what
    was done: 'hold_notice', 'hold_failed_notice', 'cancelled', or the state
    it found ('authorized', 'failed', 'open', 'closed')."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.status != "confirmed" or booking.settlement:
        return "closed"
    started = now >= aware(booking.start_at)
    if booking.hold_state == "authorized":
        if booking.hold_notice_sent_at is not None:
            return "authorized"
        if not announce or started:
            # Right after the card was saved the confirmation email has just
            # said the hold is being placed: no second email for it.
            _claim(db, booking_id, "hold_notice_sent_at", now)
            return "authorized"
        return "hold_notice" if _send_hold_notice(db, booking, now) else "authorized"
    if booking.hold_state in ("failed", "requires_action"):
        if started:
            return "failed"
        if _new_card_untried(booking):
            # The client has already saved another card and nothing has been
            # tried on it yet (retry_on_new_card does that): this is not the
            # moment to ask for a card again, or to cancel for want of one.
            return "open"
        if now >= hold_deadline(booking):
            _cancel_without_hold(db, booking, now)
            return "cancelled"
        if booking.hold_failed_notice_sent_at is None and _send_hold_failed(db, booking, now):
            return "hold_failed_notice"
        return "failed"
    return "open"  # no verdict yet (Stripe did not answer): the next tick asks again


def hold_after_card(db: Session, booking_id: int, *, replaced: bool, now: datetime | None = None) -> str:
    """A card was just saved on a confirmed booking. First card: place the
    hold if the call starts inside the hold lead time. Replacement card: if
    the hold was refused on the old one, try it on this one."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.status != "confirmed" or booking.settlement:
        return "closed"
    if now >= aware(booking.start_at):
        return "closed"
    if replaced and booking.hold_state in ("failed", "requires_action"):
        # Back to "due, not yet placed": the new card gets its own attempt,
        # and its own notice should it be refused too. If Stripe gives no
        # answer now, the tick finds the booking in that state and asks again.
        db.execute(
            update(ConsultBooking)
            .where(ConsultBooking.id == booking_id, ConsultBooking.hold_state.in_(("failed", "requires_action")))
            .values(hold_state="", hold_error="", hold_failed_notice_sent_at=None)
        )
        db.commit()
        return place_due_hold(db, booking_id, now=now, announce=True)
    if not booking.hold_state:
        return place_due_hold(db, booking_id, now=now, announce=replaced)
    return "closed"


def _new_card_untried(booking: ConsultBooking) -> bool:
    """The hold was refused, and the card on the booking was saved after
    that refusal: nothing has been tried on it yet. (The request that saves
    a card resets the refused hold at once; only one that stopped in between
    leaves this state behind.)"""
    saved, refused = aware(booking.card_saved_at), aware(booking.hold_failed_at)
    return (booking.hold_state in ("failed", "requires_action")
            and saved is not None and refused is not None and saved > refused)


def retry_on_new_card(db: Session, booking_id: int, *, now: datetime | None = None) -> str:
    """A card was saved AFTER the last refusal, and nothing has been tried on
    it: the webhook that saved it stopped before its follow-up ran (a
    restart), and Stripe's redelivery of the event is a replay that does
    nothing. Do what the follow-up would have done: try the refused hold on
    the new card, or collect the refused amount from it.

    Once per saved card: an attempt on the new card that is refused too
    records a refusal later than the card, and this finds nothing more to
    do. A card saved in the last two minutes is left to the request that
    saved it, which is most likely still doing this very thing. Returns
    'hold', 'charge', 'waiting' or 'closed'."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.card_saved_at is None:
        return "closed"
    saved = aware(booking.card_saved_at)
    if now - saved < consult.CANCEL_RESUME_AFTER:
        return "waiting"
    if booking.status == "confirmed" and not booking.settlement:
        if _new_card_untried(booking) and now < aware(booking.start_at):
            hold_after_card(db, booking_id, replaced=True, now=now)
            return "hold"
        return "closed"
    if booking.settlement and booking.charge_state in ("failed", "requires_action"):
        attempts = [
            aware(r.created_at) for r in money.ledger(db, booking_id)
            if r.kind == "charge" and r.status in ("failed", "requires_action")
        ]
        if attempts and saved > max(attempts):
            consult.after_card_replaced(db, booking)
            return "charge"
    return "closed"


def _send_hold_notice(db: Session, booking: ConsultBooking, now: datetime) -> bool:
    if not _claim(db, booking.id, "hold_notice_sent_at", now):
        return False
    sent = _to_client(
        db, booking,
        subject=f"A temporary hold is on your card for your consulting call ({booking.ref})",
        html=consult_hold_placed_html(
            full_name=booking.full_name, when=consult.when_text(booking.start_at, booking.timezone),
            amount=consult.usd(booking.hold_cents or booking.total_cents),
            card=consult.card_in_use_text(db, booking),
            manage_url=_manage_url(db, booking), ref=booking.ref,
            fee_percent=booking.fee_percent, fee=consult.usd(booking.fee_cents),
        ),
        template="consult_hold_placed",
    )
    if not sent:
        _unclaim(db, booking.id, "hold_notice_sent_at")
    return sent


def _send_hold_failed(db: Session, booking: ConsultBooking, now: datetime) -> bool:
    """Ask the client for another card (and tell the owner). Once per card."""
    if not _claim(db, booking.id, "hold_failed_notice_sent_at", now):
        return False
    deadline = hold_deadline(booking)
    needs_them = booking.hold_state == "requires_action"
    reason = (
        "Your bank wants you to approve this payment yourself. Saving the card again lets you do that."
        if needs_them else (booking.hold_error or "The card was declined.")
    )
    sent = _to_client(
        db, booking,
        subject=f"Action needed: your card for your consulting call ({booking.ref})",
        html=consult_hold_failed_html(
            full_name=booking.full_name, when=consult.when_text(booking.start_at, booking.timezone),
            amount=consult.usd(booking.total_cents), card=consult.refused_hold_card_text(db, booking),
            reason=reason,
            deadline=consult.when_text(deadline, booking.timezone),
            manage_url=_manage_url(db, booking), ref=booking.ref,
        ),
        template="consult_hold_failed",
    )
    if not sent:
        _unclaim(db, booking.id, "hold_failed_notice_sent_at")
        return False
    _note(db, booking.id, "card_requested", note="The hold was refused; the client was asked for another card.")
    cs = consult.settings_row(db)
    consult.notify_owner(
        db, booking, template="consult_owner_hold_failed",
        headline="The hold on the card was refused",
        detail=(
            "The temporary hold for this call could not be placed. The client has been emailed a link "
            "to give another card; the hold is placed as soon as they do. If no hold can be placed by "
            f"{consult.when_text(deadline, cs.timezone)}, the call is cancelled automatically and "
            "both of you are told. You do not need to do anything."
        ),
        extra_rows=[("What the bank said", booking.hold_error or "no reason given")],
    )
    return True


def _cancel_without_hold(db: Session, booking: ConsultBooking, now: datetime) -> None:
    why = booking.hold_error or "the card was refused"
    try:
        consult.cancel_by_owner(
            db, booking, actor="auto", by="system", now=now,
            note=(
                f"No hold could be placed on the card ({why}) and no other card was provided by "
                f"{HOLD_FAIL_CANCEL_HOURS} hours before the call."
            ),
        )
    except consult.Refused:
        db.rollback()  # someone closed the booking a moment ago: nothing left to do


# -----------------------------------------------------------------------------
# Reminders
# -----------------------------------------------------------------------------

_COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _days_away(start: datetime, now: datetime, tz_name: str) -> str:
    """'today', 'tomorrow', 'in two days': by the calendar on the client's
    own clock, so the words match the date printed under them."""
    tz = ZoneInfo(tz_name if consult.valid_zone(tz_name) else "UTC")
    days = (start.astimezone(tz).date() - now.astimezone(tz).date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {_COUNT_WORDS[days] if days < len(_COUNT_WORDS) else days} days"


def _soon(left: timedelta) -> str:
    """'in about an hour', 'in about 3 hours', 'in about 25 minutes'."""
    minutes = max(int(left.total_seconds() // 60), 0)
    if minutes >= 90:
        return f"in about {round(minutes / 60)} hours"
    if minutes >= 45:
        return "in about an hour"
    return f"in about {max(5 * round(minutes / 5), 5)} minutes"


def reminder_window(booking: ConsultBooking, cs, which: str) -> tuple[datetime, datetime] | None:
    """When a reminder may go out: (from, until). which 'first' | 'last'.

    The first one is timed from the free-cancellation deadline, not from the
    start: `reminder_before_deadline_hours` before it (24, so 48 hours before
    the start with the default terms), so that the client is reminded while
    cancelling still costs nothing and has that long to act. It is not sent
    any more once little of that time is left. The last one goes out
    `reminder_before_start_hours` before the start."""
    start = aware(booking.start_at)
    if which == "first":
        deadline = aware(booking.free_cancel_until)
        if deadline is None:
            return None
        lead = timedelta(hours=cs.reminder_before_deadline_hours or 24)
        return deadline - lead, deadline - min(REMINDER_FIRST_MIN_LEFT, lead / 2)
    return start - timedelta(hours=cs.reminder_before_start_hours or 1), start


def send_reminder(db: Session, booking_id: int, which: str, *, now: datetime | None = None) -> bool:
    """The first reminder ('first': while cancelling is still free) or the
    last ('last': shortly before the start), at most once each.

    A reminder is skipped when the booking was confirmed after its time, or
    less than REMINDER_MIN_GAP before it: the confirmation email has only
    just arrived and already states the free-cancellation deadline."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.status != "confirmed":
        return False
    cs = consult.settings_row(db)
    window = reminder_window(booking, cs, which)
    column = REMINDER_COLUMN[which]
    if window is None or getattr(booking, column) is not None:
        return False
    opens, closes = window
    if not (opens <= now < closes):
        return False
    confirmed_at = aware(booking.confirmed_at)
    if confirmed_at is not None and confirmed_at > opens - REMINDER_MIN_GAP:
        return False
    if not _claim(db, booking_id, column, now):
        return False
    start = aware(booking.start_at)
    fee = consult.cancel_fee_now(booking, now)
    deadline = aware(booking.free_cancel_until)
    after = (
        f" After that the {booking.fee_percent}% fee ({consult.usd(booking.fee_cents)}) applies, "
        "as set out in your booking terms." if booking.fee_cents else ""
    )
    if fee > 0:
        cancel_line = (
            f"If you need to cancel now, the {booking.fee_percent}% fee ({consult.usd(fee)}) applies, "
            "as set out in your booking terms."
        )
    elif deadline is not None:
        cancel_line = (
            f"You can cancel free of charge until {consult.when_text(deadline, booking.timezone)}.{after}"
        )
    else:
        cancel_line = ""
    if which == "first":
        in_words = _days_away(start, now, booking.timezone)
        subject = f"Reminder: your consulting call is {in_words} ({booking.ref})"
    else:
        in_words = _soon(start - now)
        subject = f"Your consulting call starts {in_words} ({booking.ref})"
    sent = _to_client(
        db, booking, subject=subject,
        html=consult_reminder_html(
            full_name=booking.full_name, when=consult.when_text(start, booking.timezone),
            minutes=booking.minutes, kind=which, in_words=in_words, meet_url=booking.meet_url,
            manage_url=_manage_url(db, booking), ref=booking.ref, cancel_line=cancel_line,
            expert=get_settings().INSTRUCTOR_NAME,
        ),
        template="consult_reminder_first" if which == "first" else "consult_reminder_last",
    )
    if not sent:
        _unclaim(db, booking_id, column)
        return False
    _note(db, booking_id, "reminder_sent", note=(
        "While cancelling is still free." if which == "first" else "Shortly before the call."
    ))
    return True


# -----------------------------------------------------------------------------
# Attendance (Google Meet REST API)
# -----------------------------------------------------------------------------

@dataclass
class Attendance:
    """Who joined. state: 'both' | 'client_absent' | 'host_absent' | 'unknown'."""

    state: str
    host_joined: bool | None = None
    others_joined: int | None = None
    participants: list[str] = field(default_factory=list)
    note: str = ""


class _MeetRefused(Exception):
    """Google answered the attendance question with a refusal."""


def _unknown(why: str) -> Attendance:
    return Attendance("unknown", note=why[:500])


_EXTRA_DIGITS = re.compile(r"(\.\d{6})\d+")


def _time(value) -> datetime | None:
    """A Google timestamp ('2031-06-11T14:00:05.123456789Z') as a UTC time."""
    if not value:
        return None
    try:
        # Google writes up to nine fractional digits; datetime keeps six.
        return xcal._parse(_EXTRA_DIGITS.sub(r"\1", str(value)))
    except (TypeError, ValueError):
        return None


def _pages(cal: ExamCalendar, url: str, key: str, params: dict) -> list[dict]:
    """Every item of a paged Meet API list (at most ten pages)."""
    out: list[dict] = []
    token = ""
    for _ in range(10):
        status, body = xcal.google_get(cal, url, params={**params, **({"pageToken": token} if token else {})})
        if status != 200:
            raise _MeetRefused(f"Google Meet refused the attendance check: {xcal._google_error(body)}")
        out += [item for item in (body.get(key) or []) if isinstance(item, dict)]
        token = str(body.get("nextPageToken") or "")
        if not token:
            break
    return out


def read_attendance(db: Session, booking: ConsultBooking, now: datetime | None = None) -> Attendance:
    """Ask Google Meet who joined this booking's meeting. Never raises: when
    the question cannot be asked or answered, the state is 'unknown' and the
    note says why.

    The host is the connected Google account (its id comes from Google's
    userinfo endpoint and is the id Meet reports for a signed-in user).
    Anyone else in the meeting, signed in or not, by phone or not, is "another
    participant"."""
    now = now or consult.utcnow()
    cal = db.get(ExamCalendar, 1)
    if cal is None or not cal.refresh_token_encrypted:
        return _unknown("The Google calendar is not connected, so attendance cannot be read.")
    if not xcal.has_scope(cal, xcal.MEET_SCOPE):
        return _unknown(
            "The Google connection does not include the Meet permission yet. Connect the calendar "
            "again in the admin panel to grant it."
        )
    found = _MEET_CODE.search(booking.meet_url or "")
    if not found:
        return _unknown("This booking has no Google Meet link, so attendance cannot be read.")
    code = found.group(1).lower()
    start, end = aware(booking.start_at), aware(booking.end_at)
    try:
        status, me = xcal.google_get(cal, USERINFO_URL)
        host = str(me.get("sub") or "") if status == 200 else ""
        if not host:
            return _unknown(f"Google did not say which account is connected ({xcal._google_error(me)}).")
        records = _pages(
            cal, f"{MEET_API}/conferenceRecords", "conferenceRecords",
            {"filter": f'space.meeting_code = "{code}"', "pageSize": 100},
        )
        people: dict[str, dict] = {}
        for record in records:
            began, finished = _time(record.get("startTime")), _time(record.get("endTime"))
            name = str(record.get("name") or "")
            if not name.startswith("conferenceRecords/") or began is None:
                continue
            if began >= end + ATTENDANCE_WINDOW or (finished or now) <= start - ATTENDANCE_WINDOW:
                continue  # the link was opened at some other time: not this call
            for p in _pages(cal, f"{MEET_API}/{name}/participants", "participants", {"pageSize": 250}):
                signed, guest, phone = p.get("signedinUser"), p.get("anonymousUser"), p.get("phoneUser")
                is_host = False
                if isinstance(signed, dict):
                    user = str(signed.get("user") or "")
                    key = user or str(p.get("name") or "")
                    label = str(signed.get("displayName") or "Signed-in participant")
                    is_host = bool(user) and user == f"users/{host}"
                elif isinstance(guest, dict):
                    key = str(p.get("name") or "")
                    label = f"{guest.get('displayName') or 'Guest'} (not signed in)"
                elif isinstance(phone, dict):
                    key = str(p.get("name") or "")
                    label = f"{phone.get('displayName') or 'Caller'} (by phone)"
                else:
                    key, label = str(p.get("name") or ""), "Participant"
                if not key:
                    continue
                joined, left = _time(p.get("earliestStartTime")), _time(p.get("latestEndTime"))
                seen = people.setdefault(
                    key, {"label": label, "host": is_host, "joined": joined, "left": left, "in": False, "spans": []})
                if joined and (seen["joined"] is None or joined < seen["joined"]):
                    seen["joined"] = joined
                if left is None:
                    seen["in"] = True
                elif seen["left"] is None or left > seen["left"]:
                    seen["left"] = left
                if joined:
                    # still in the call: until the conference ended, or now
                    seen["spans"].append((joined, left or finished or now))
    except xcal.CalendarError as exc:
        return _unknown(f"Google could not be asked who joined: {exc}")
    except _MeetRefused as exc:
        return _unknown(str(exc))
    except Exception as exc:  # noqa: BLE001 — an answer in a shape we do not know is "unknown", not a crash
        log.exception("Reading Meet attendance for consult %s failed", booking.ref)
        return _unknown(f"Google's answer about who joined could not be read ({exc.__class__.__name__}).")

    tz = consult.zone(consult.settings_row(db))

    def clock(at: datetime | None) -> str:
        return at.astimezone(tz).strftime("%-I:%M %p %Z") if at else "time not given"

    # The host is the connected Google account on however many devices (the
    # same Google user is one person here). Anyone else counts as the client
    # only if they were in the call together with the host for
    # CLIENT_MIN_OVERLAP in all.
    host_spans = [span for p in people.values() if p["host"] for span in p["spans"]]
    lines = []
    counted = 0
    for person in sorted(people.values(), key=lambda x: (not x["host"], x["joined"] or now)):
        who = f"You ({person['label']})" if person["host"] else person["label"]
        left = "still in the call" if person["in"] else f"left {clock(person['left'])}"
        line = f"{who}: joined {clock(person['joined'])}, {left}"
        if not person["host"] and host_spans:
            together = _together(person["spans"], host_spans)
            minutes = int(together.total_seconds() // 60)
            if together >= CLIENT_MIN_OVERLAP:
                counted += 1
                line += f" ({minutes} min in the call with you)"
            else:
                line += f" ({minutes} min in the call with you: not counted as the client)"
        lines.append(line)
    host_joined = bool(host_spans) or any(p["host"] for p in people.values())
    others = sum(1 for p in people.values() if not p["host"])
    if host_joined and counted:
        return Attendance("both", True, counted, lines)
    if host_joined and others:
        return Attendance("client_absent", True, 0, lines, (
            "Others were in the call, but none of them together with you for at least "
            f"{int(CLIENT_MIN_OVERLAP.total_seconds() // 60)} minutes, so nobody counts as the client."))
    if host_joined:
        return Attendance("client_absent", True, 0, lines, "You joined; nobody else did.")
    note = (
        "Google Meet has no record of anyone joining this meeting." if not people
        else "Others joined, but Google Meet has no record of the connected account joining. "
             "If you joined from another Google account, decide the outcome yourself."
    )
    return Attendance("host_absent", False, others, lines, note)


def _together(a: list[tuple[datetime, datetime]], b: list[tuple[datetime, datetime]]) -> timedelta:
    """How long two people were in the call at the same time: the length of
    the overlap of their (merged) spans."""
    def merged(spans):
        out: list[list[datetime]] = []
        for start, end in sorted((s, e) for s, e in spans if e > s):
            if out and start <= out[-1][1]:
                out[-1][1] = max(out[-1][1], end)
            else:
                out.append([start, end])
        return out

    total = timedelta(0)
    for s1, e1 in merged(a):
        for s2, e2 in merged(b):
            low, high = max(s1, s2), min(e1, e2)
            if high > low:
                total += high - low
    return total


def record_attendance(db: Session, booking_id: int, found: Attendance, now: datetime | None = None) -> str:
    """Store what was read. A read that could not tell ('unknown') never
    replaces an earlier one that could. Returns the state now on the booking."""
    now = now or consult.utcnow()
    booking = money.lock_booking(db, booking_id)
    if booking is None:
        db.commit()
        return "unknown"
    before = booking.attendance_state or ""
    if found.state == "unknown" and before in ("both", "client_absent", "host_absent"):
        db.commit()
        return before
    booking.attendance = {
        "host_joined": found.host_joined, "others_joined": found.others_joined,
        "participants": list(found.participants), "note": found.note,
    }
    booking.attendance_state = found.state
    booking.attendance_checked_at = now
    if found.state != before:
        add_event(
            db, booking, "attendance_read", actor="google" if found.state != "unknown" else "system",
            note=f"{ATTENDANCE_WORDS[found.state]}." + (f" {found.note}" if found.state == "unknown" else ""),
        )
    db.commit()
    return found.state


def check_attendance(db: Session, booking_id: int, *, now: datetime | None = None) -> str:
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None:
        return "unknown"
    return record_attendance(db, booking_id, read_attendance(db, booking, now), now)


# -----------------------------------------------------------------------------
# The owner's links: signed, expiring, spent by the first choice
# -----------------------------------------------------------------------------

def links_available() -> bool:
    """The links decide what a client pays, with no sign-in, so they are
    signed with a real server secret or not issued at all (the development
    fallback consult._token_secret would use is public knowledge)."""
    s = get_settings()
    return bool(s.SESSION_SECRET or s.ADMIN_TOKEN)


def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(
        consult._token_secret(), salt="consult-owner-decision",
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def decision_token(booking: ConsultBooking, outcome: str, expires: datetime) -> str:
    return _signer().dumps([booking.id, booking.ref, outcome, int(aware(expires).timestamp())])


def decision_url(token: str) -> str:
    # `token` is a parameter name the email log already blanks (email_copies).
    return f"{get_settings().API_PUBLIC_URL.rstrip('/')}/api/consult/decision?token={token}"


@dataclass
class Decision:
    """What the confirm page shows. state: 'ready' (GET: nothing done yet) |
    'done' | 'recorded' (chosen, not carried out yet) | 'decided' (someone
    got there first) | 'expired' | 'invalid'."""

    state: str
    http: int
    title: str
    lines: list[str] = field(default_factory=list)
    button: str = ""
    admin_url: str = ""
    booking_id: int | None = None
    outcome: str = ""


def _what_it_does(db: Session, booking: ConsultBooking, outcome: str) -> tuple[str, str, str]:
    """(title, sentence, button) for one of the three choices."""
    name = booking.full_name
    total, fee = consult.usd(booking.total_cents), consult.usd(booking.fee_cents)
    card = consult.card_in_use_text(db, booking) or "the saved card"
    if outcome == "charge":
        return (
            f"Charge {name} in full?",
            f"{total} will be charged to {card} for the {booking.minutes}-minute call.",
            f"Yes, charge {total}",
        )
    if outcome == "no_show":
        return (
            f"Record a no-show for {name}?",
            f"The no-show fee of {booking.fee_percent}% ({fee}) will be charged to {card}. "
            "The rest of any hold is released.",
            f"Yes, charge the {fee} fee",
        )
    return (
        f"Do not charge {name}?",
        "Nothing will be charged, and any hold on the card is released.",
        "Yes, do not charge",
    )


def _how_it_stands(booking: ConsultBooking, cs_zone: str) -> list[str]:
    """Plain words for a booking that is already decided or closed."""
    if booking.settlement:
        words = {
            "charged": "charged in full", "no_show": "recorded as a no-show (the fee)",
            "waived": "not charged", "late_cancel": "cancelled late (the fee)",
        }.get(booking.settlement, booking.settlement)
        when = consult.when_text(booking.settled_at, cs_zone) if booking.settled_at else "earlier"
        lines = [f"This call was already decided: {words}, by {booking.settled_by or 'the system'}, {when}."]
        taken = (booking.charged_cents or 0) - (booking.refunded_cents or 0)
        lines.append(
            f"{consult.usd(taken)} has been charged." if taken > 0
            else "Nothing has been charged so far."
        )
        lines.append("To change it, open the booking in the admin panel. Money that was taken goes back through a refund.")
        return lines
    if booking.owner_choice:
        return [
            f"You already chose: {CHOICE_WORDS.get(booking.owner_choice, booking.owner_choice).lower()}.",
            "It is being carried out; you get an email with the result.",
        ]
    return [f"This booking is {booking.status.replace('_', ' ')}: there is nothing to decide."]


def look_at_decision(db: Session, token: str, now: datetime | None = None) -> Decision:
    """Read a link from the summary email. Changes nothing."""
    now = now or consult.utcnow()
    bad = Decision("invalid", 400, "This link is not valid", [
        "The link is incomplete or was changed. Open the booking in the admin panel instead.",
    ], admin_url=consult._admin_url())
    if not links_available():
        return bad
    try:
        booking_id, ref, outcome, expires = _signer().loads(token or "")
        booking_id, expires = int(booking_id), int(expires)
    except (BadSignature, TypeError, ValueError):
        return bad
    if outcome not in consult.OUTCOMES:
        return bad
    booking = _load(db, booking_id)
    if booking is None or booking.ref != ref:
        return bad
    zone = consult.settings_row(db).timezone
    admin_url = consult._admin_url(booking)
    if booking.settlement or booking.owner_choice or booking.status != "confirmed":
        return Decision("decided", 409, "Already decided", _how_it_stands(booking, zone),
                        admin_url=admin_url, booking_id=booking.id, outcome=outcome)
    if now.timestamp() >= expires:
        return Decision("expired", 410, "This link has expired", [
            f"It could be used until {consult.when_text(datetime.fromtimestamp(expires, timezone.utc), zone)}.",
            "The automatic outcome applies now. To decide differently, open the booking in the admin panel.",
        ], admin_url=admin_url, booking_id=booking.id, outcome=outcome)
    title, sentence, button = _what_it_does(db, booking, outcome)
    return Decision("ready", 200, title, [
        f"Call: {consult.when_text(booking.start_at, zone)}, {booking.minutes} minutes. Reference {booking.ref}.",
        sentence,
        "Nothing has been done yet. Press the button to confirm.",
    ], button=button, admin_url=admin_url, booking_id=booking.id, outcome=outcome)


def decide(db: Session, token: str, now: datetime | None = None) -> Decision:
    """The button on the confirm page was pressed: record the owner's choice
    (once: the first choice for a booking spends all three links) and carry
    it out."""
    now = now or consult.utcnow()
    seen = look_at_decision(db, token, now)
    if seen.state != "ready":
        return seen
    booking_id, outcome = seen.booking_id, seen.outcome
    actor = owner_actor()
    with consult._STATE_MUTEX:
        claimed = db.execute(
            update(ConsultBooking)
            .where(
                ConsultBooking.id == booking_id, ConsultBooking.owner_choice == "",
                ConsultBooking.settlement == "", ConsultBooking.status == "confirmed",
            )
            .values(owner_choice=outcome, owner_choice_at=now)
        ).rowcount == 1
        if claimed:
            booking = _load(db, booking_id)
            add_event(db, booking, "owner_chose", actor=actor, at=now,
                      note=f"{CHOICE_WORDS[outcome]}, from the summary email.")
        db.commit()
    if not claimed:
        return look_at_decision(db, token, now)
    return _carry_out(db, booking_id, outcome, now)


def _carry_out(db: Session, booking_id: int, outcome: str, now: datetime) -> Decision:
    booking = _load(db, booking_id)
    admin_url = consult._admin_url(booking)
    try:
        booking, result = consult.settle(
            db, booking, outcome, actor=owner_actor(), now=now, only_undecided=True, expect_choice=outcome,
            reason="You chose this from the summary email.",
        )
    except consult.AlreadyDecided:
        booking = _load(db, booking_id)
        return Decision("decided", 409, "Already decided",
                        _how_it_stands(booking, consult.settings_row(db).timezone),
                        admin_url=admin_url, booking_id=booking_id, outcome=outcome)
    except consult.Refused as exc:
        db.rollback()
        return Decision("recorded", 200, "Your choice is recorded", [
            f"You chose: {CHOICE_WORDS[outcome].lower()}.",
            f"It could not be carried out this minute: {exc.message}",
            "It is tried again within a few minutes, and you get an email with the result.",
        ], admin_url=admin_url, booking_id=booking_id, outcome=outcome)
    if result.ok and result.amount_cents > 0:
        card = consult.charged_card_text(db, booking, result.charge_id) or "the saved card"
        lines = [f"{consult.usd(result.amount_cents)} was charged to {card}."]
    elif result.ok:
        lines = ["Nothing was charged. Any hold on the card was released."]
    else:
        lines = [
            f"Your choice is recorded, but the card did not pay: {result.message or result.code or 'no reason given'}.",
            "Nothing was taken. The booking in the admin panel shows what to do next.",
        ]
    lines.append("You also get this by email.")
    return Decision("done", 200, f"Done: {CHOICE_WORDS[outcome].lower()}", lines,
                    admin_url=admin_url, booking_id=booking_id, outcome=outcome)


# -----------------------------------------------------------------------------
# The summary and the automatic outcome
# -----------------------------------------------------------------------------

def _default_line(booking: ConsultBooking, state: str) -> str:
    total, fee = consult.usd(booking.total_cents), consult.usd(booking.fee_cents)
    if state == "both":
        return f"The booked amount, {total}, is charged."
    if state == "client_absent":
        return f"The no-show fee of {booking.fee_percent}% ({fee}) is charged and the rest of the hold is released."
    if state == "host_absent":
        return "Nothing is charged and any hold is released, because Google Meet has no record of you joining."
    return f"Attendance could not be read, so the booked amount, {total}, is charged in full."


def summary_can_be_sent() -> bool:
    """Is there an owner address and an email service to send the summary
    with? Without both he cannot be asked, and nothing is charged by itself."""
    settings = get_settings()
    return bool(settings.ADMIN_NOTIFY_EMAIL and settings.RESEND_API_KEY)


# The summary's mark (summary_sent_at) is set BEFORE the email is sent, so
# that two runs cannot both send it. The mark alone therefore does not say
# the owner was asked: a run stopped between the mark and the email service's
# answer leaves it set and nothing sent. What says "sent" is the timeline
# line `summary_sent`, written after the send. A mark this old without that
# line is given back and the summary is sent again (review 2, N4).
SUMMARY_MARK_STALE = timedelta(minutes=10)


def _summary_line():
    """SQL condition: this booking has its `summary_sent` timeline line."""
    return exists().where(
        ConsultBookingEvent.booking_id == ConsultBooking.id, ConsultBookingEvent.kind == "summary_sent",
    )


def _summary_not_sent(now: datetime):
    """SQL condition: no summary has gone out for this booking: no mark, or
    a stale mark with no `summary_sent` line behind it."""
    B = ConsultBooking
    return or_(
        B.summary_sent_at.is_(None),
        and_(B.summary_sent_at <= now - SUMMARY_MARK_STALE, ~_summary_line()),
    )


def summary_was_sent(db: Session, booking: ConsultBooking) -> bool:
    """Has the owner's summary email for this call actually gone out?"""
    if booking.summary_sent_at is None:
        return False
    return db.execute(
        select(ConsultBookingEvent.id).where(
            ConsultBookingEvent.booking_id == booking.id, ConsultBookingEvent.kind == "summary_sent",
        ).limit(1)
    ).first() is not None


def unsent_summaries(db: Session, now: datetime | None = None) -> list[ConsultBooking]:
    """Calls that ended at least ten minutes ago, with a time for the owner
    to choose in, whose summary email has not gone out: their automatic
    outcome is waiting for it."""
    now = now or consult.utcnow()
    B = ConsultBooking
    return list(db.execute(
        select(B).where(
            B.status == "confirmed", B.settlement == "", B.owner_choice == "", _summary_not_sent(now),
            B.auto_settle_hours > 0, B.end_at <= now - timedelta(minutes=10),
        ).order_by(B.end_at)
    ).scalars().all())


def send_summary(db: Session, booking_id: int, *, now: datetime | None = None) -> bool:
    """The owner's email at the scheduled end, at most once: who joined, what
    happens by itself and when, and the three links."""
    now = now or consult.utcnow()
    settings = get_settings()
    if not summary_can_be_sent():
        return False  # nothing is charged automatically meanwhile (settle_due); the admin status says so
    booking = _load(db, booking_id)
    if booking is None or booking.status != "confirmed" or booking.settlement or booking.owner_choice:
        return False
    end = aware(booking.end_at)
    window = timedelta(hours=booking.auto_settle_hours or 0)
    if now < end or window <= timedelta(0):
        return False  # no time to choose in: the outcome email says what happened
    if booking.summary_sent_at is not None:
        if summary_was_sent(db, booking) or now - aware(booking.summary_sent_at) < SUMMARY_MARK_STALE:
            return False  # sent; or another run is sending it this minute
        # Marked, never sent: the run that set the mark was stopped before
        # the email went out. The mark goes back (one run wins the new claim
        # below) and the time to choose starts over.
        db.execute(
            update(ConsultBooking)
            .where(ConsultBooking.id == booking_id, ConsultBooking.summary_sent_at.is_not(None),
                   ConsultBooking.summary_sent_at <= now - SUMMARY_MARK_STALE)
            .values(summary_sent_at=None, settle_due_at=end + window)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        booking = _load(db, booking_id)
        if booking is None or booking.summary_sent_at is not None:
            return False
    if not consult.email_try_allowed(booking, "summary", now):
        return False  # refused a dozen times already: once an hour from here on
    due = aware(booking.settle_due_at) or end + window
    # His time to choose counts from the moment the email is actually sent,
    # never from the scheduled end alone: sent at the end it is the same
    # time; sent later (the tick or the email service was down) it moves.
    deadline = max(due, now + window)
    if not _claim(db, booking_id, "summary_sent_at", now, settle_due_at=deadline):
        return False
    booking = _load(db, booking_id)
    cs = consult.settings_row(db)
    state = booking.attendance_state or "unknown"
    attendance = booking.attendance or {}
    total, fee = consult.usd(booking.total_cents), consult.usd(booking.fee_cents)
    hold = (
        f"{consult.usd(booking.hold_cents)} authorized on {consult.card_in_use_text(db, booking) or 'the card'}"
        if booking.hold_state == "authorized" else "None: the card is charged directly"
    )
    rows = [
        ("Client", f"{booking.full_name} ({booking.email})"),
        ("Call", f"{consult.when_text(booking.start_at, cs.timezone)}, {booking.minutes} minutes"),
        ("Booked amount", total),
        ("Hold", hold),
        ("Attendance", ATTENDANCE_WORDS.get(state, state)),
        ("Reference", booking.ref),
    ]
    if attendance.get("note"):
        rows.insert(5, ("Note", str(attendance["note"])))
    if state == "both":
        # The site cannot tell who a participant is: say so where it matters.
        rows.insert(5, ("Check the names", (
            "Everyone Google Meet saw in the call is listed below. Whoever was in it with you for "
            f"{int(CLIENT_MIN_OVERLAP.total_seconds() // 60)} minutes or more counts as the client: a "
            "note-taking bot, or a second Google account of your own, looks the same to the site. If the "
            "client is not among them, choose \"No-show\" or \"Do not charge\" below.")))
    sent = send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Consulting] Call ended: confirm the outcome: {booking.full_name}",
        html=consult_owner_summary_html(
            intro=(
                "This consulting call has reached its scheduled end. Unless you choose otherwise, "
                f"the outcome below is applied at {consult.when_text(deadline, cs.timezone)}."
            ),
            rows=rows,
            participants=[str(p) for p in (attendance.get("participants") or [])],
            default_line=_default_line(booking, state),
            deadline=consult.when_text(deadline, cs.timezone),
            choices=[
                (f"Charge in full: {total}", decision_url(decision_token(booking, "charge", deadline))),
                (f"No-show: charge the {booking.fee_percent}% fee, {fee}",
                 decision_url(decision_token(booking, "no_show", deadline))),
                ("Do not charge", decision_url(decision_token(booking, "waive", deadline))),
            ] if links_available() else [],
            admin_url=consult._admin_url(booking),
        ),
        db=db, scope_kind="system", scope_code="consult", audience="admin",
        template="consult_owner_summary",
    )
    consult.note_email_try(db, booking_id, "summary", now, sent=bool(sent))
    if not sent:
        # Not sent: he has not been asked. The marker goes back, whatever
        # the reason, so that the automatic outcome keeps waiting.
        db.execute(update(ConsultBooking).where(ConsultBooking.id == booking_id)
                   .values(summary_sent_at=None, settle_due_at=due))
        db.commit()
        return False
    # This line, not the mark, is what says he was asked (see settle_due).
    _note(db, booking_id, "summary_sent", note=(
        f"The owner was asked to confirm the outcome. Default at {consult._iso(deadline)}: "
        f"{CHOICE_WORDS[DEFAULT_OUTCOME.get(state, 'charge')].lower()}."
    ))
    return True


_AUTO_REASON = {
    "both": "Google Meet shows that you and the client both joined, and you made no other choice in time.",
    "client_absent": "Google Meet shows that you joined and nobody else did, and you made no other choice in time.",
    "host_absent": (
        "Google Meet has no record of you joining this call, so the client was not charged and any hold "
        "was released. If that is not right, open the booking and press Charge."
    ),
    "unknown": (
        "Attendance could not be read, and you made no choice in time, so the rule for that case "
        "applied: charge in full."
    ),
}
_AUTO_LABEL = {
    "both": "Automatic charge for the call",
    "client_absent": "Automatic no-show fee",
    "host_absent": "Not charged: Meet has no record of you joining",
    "unknown": "Automatic charge for the call (attendance unknown)",
}


def settle_due(db: Session, booking_id: int, *, now: datetime | None = None) -> str:
    """Apply the owner's choice if he made one, or the default outcome once
    its time has come. Returns the outcome applied ('charge' | 'no_show' |
    'waive'), 'waiting' or 'closed'. A refusal from consult.settle is raised
    (the tick reports it and tries again next time)."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.status != "confirmed" or booking.settlement:
        return "closed"
    end = aware(booking.end_at)
    if now < end:
        return "waiting"
    if booking.owner_choice:
        outcome = booking.owner_choice
        try:
            consult.settle(
                db, booking, outcome, actor=owner_actor(), now=now, only_undecided=True,
                expect_choice=outcome, reason="You chose this from the summary email.",
            )
        except consult.AlreadyDecided:
            return "closed"
        return outcome
    window = timedelta(hours=booking.auto_settle_hours or 0)
    if window > timedelta(0) and not summary_was_sent(db, booking):
        # He has not been asked: the summary email has not gone out (the
        # email service refused it, no address or service is set up, or the
        # run that marked it was stopped before it was sent). Nothing is
        # decided for him until it has, and his time to choose counts from
        # then. The admin buttons work meanwhile.
        return "waiting"
    due = aware(booking.settle_due_at) or end + window
    if now < due:
        return "waiting"
    state = booking.attendance_state or ""
    if state != "both":
        # One last look: Meet's record can arrive after the scheduled end.
        state = check_attendance(db, booking_id, now=now)
        booking = _load(db, booking_id)
    outcome = DEFAULT_OUTCOME.get(state, "charge")
    reason = _AUTO_REASON.get(state, _AUTO_REASON["unknown"])
    if state == "unknown" and (booking.attendance or {}).get("note"):
        reason = f"{reason} ({booking.attendance['note']})"
    try:
        consult.settle(
            db, booking, outcome, actor="auto", now=now, only_undecided=True, expect_choice="",
            reason=reason, label=_AUTO_LABEL.get(state, _AUTO_LABEL["unknown"]),
        )
    except consult.AlreadyDecided:
        return "closed"
    return outcome


# -----------------------------------------------------------------------------
# Money steps that were cut short
# -----------------------------------------------------------------------------

def finish_collection(db: Session, booking_id: int, *, now: datetime | None = None) -> str:
    """A decided amount whose payment got no answer from Stripe: ask again
    (the same idempotency key, so never a second charge).

    Left alone: a decision made in the last two minutes (the request that
    made it is most likely still collecting), and a cancellation whose
    follow-up has not finished (finish_cancellation collects its fee and
    words its emails accordingly)."""
    now = now or consult.utcnow()
    booking = _load(db, booking_id)
    if booking is None or booking.charge_state != "pending" or booking.settlement not in money.SETTLEMENT_REASON:
        return "closed"
    if booking.status == "cancelled" and booking.cancel_notice_sent_at is None:
        return "closed"
    if booking.settled_at is not None and now - aware(booking.settled_at) < consult.CANCEL_RESUME_AFTER:
        return "waiting"
    result = money.collect(db, booking, actor="auto")
    booking = _load(db, booking_id)
    if result.fresh:
        consult.notify_owner_payment(db, booking, result, what=consult.OUTCOME_LABELS[booking.settlement])
    elif result.status == "needs_review":
        _ask_for_review(db, booking_id, "charge")
    return "collected" if result.ok else "open"


def finish_release(db: Session, booking_id: int) -> str:
    """A hold that should be gone (the booking is closed and nothing is
    owed) but whose release Stripe did not confirm: ask again, a few times."""
    booking = _load(db, booking_id)
    if (
        booking is None or booking.hold_state != "authorized"
        or booking.status not in ("cancelled", "completed", "no_show")
        or booking.charge_state not in ("", "paid")
    ):
        return "closed"
    tries = db.execute(
        select(ConsultBookingEvent.id).where(
            ConsultBookingEvent.booking_id == booking_id, ConsultBookingEvent.kind == "hold_release_failed",
        )
    ).all()
    if len(tries) >= RELEASE_RETRY_LIMIT:
        # It lapses by itself within days, but not silently: he is told once.
        if _note_once(db, booking_id, "hold_release_unconfirmed", amount_cents=booking.hold_cents, note=(
            f"Stripe did not confirm the release of the hold after {RELEASE_RETRY_LIMIT} tries. "
            "The owner was told."
        )):
            booking = _load(db, booking_id)
            consult.notify_owner(
                db, booking, template="consult_owner_needs_review",
                headline="A hold could not be released",
                detail=(
                    f"This booking is closed and nothing more is owed, but Stripe did not confirm the release "
                    f"of the hold of {consult.usd(booking.hold_cents)} on the client's card "
                    f"({RELEASE_RETRY_LIMIT} tries). It is still authorized as far as this site knows."
                    "\n\n"
                    "Cancel it in Stripe (the uncaptured payment for this booking reference). If nobody "
                    "does, the authorization lapses by itself within about a week."
                ),
                extra_rows=[("Search Stripe for", booking.ref), ("Payment", booking.hold_payment_intent_id or "not known")],
                extra_link=("Open Stripe payments", "https://dashboard.stripe.com/payments"),
            )
            return "alerted"
        return "left"
    return "released" if money.release_hold(db, booking, actor="auto") else "open"


def release_lost_hold(db: Session, booking_id: int) -> str:
    """A hold whose answer from Stripe was lost, on a booking that has since
    been cancelled or settled: nothing would ever ask about it again, and an
    authorization for the whole amount could stay on the client's card. Ask
    Stripe, let go of what is found, and tell the owner when that cannot be
    confirmed (once per attempt)."""
    booking = _load(db, booking_id)
    if booking is None:
        return "closed"
    verdict = money.settle_lost_holds(db, booking, actor="auto")
    if verdict in ("parked", "kept"):
        _ask_for_review(db, booking_id, "hold")
    return verdict


def finish_refunds(db: Session, booking_id: int) -> str:
    """A refund that has no recorded answer from Stripe: ask Stripe whether
    it was made, and record that. Nothing is sent again without asking."""
    booking = _load(db, booking_id)
    if booking is None:
        return "closed"
    result = money.finish_refunds(db, booking, actor="auto", found_later=True)
    if result is None:
        return "closed"
    booking = _load(db, booking_id)
    if result.fresh:
        consult.notify_owner_payment(db, booking, result, what="Refund")
    if result.ok:
        return "refunded"
    return {"needs_review": "parked", "failed": "not_made"}.get(result.status, "open")


# -----------------------------------------------------------------------------
# Stripe disputes
# -----------------------------------------------------------------------------

def dispute_totals(events: list[tuple[str, dict, int | None]]) -> tuple[int, int, str]:
    """(disputed cents, lost cents, state) from a booking's dispute lines on
    the timeline, each (kind, data, amount). Pure.

    A dispute is 'open' from its opening until a closing line names it;
    then it is 'won', 'lost', or 'closed' (an inquiry that came to nothing).
    Disputed is what is open or lost; lost is what the bank gave back to the
    cardholder. The order the lines arrived in does not matter (Stripe may
    deliver the closing first)."""
    amount: dict[str, int] = {}
    ended: dict[str, str] = {}
    for kind, data, cents in events:
        dispute_id = str((data or {}).get("dispute_id") or "")
        amount[dispute_id] = max(amount.get(dispute_id, 0), int(cents or 0))
        if kind == "dispute_closed":
            ended[dispute_id] = {"won": "won", "lost": "lost"}.get(str((data or {}).get("status") or ""), "closed")
    states = {d: ended.get(d, "open") for d in amount}
    lost = sum(amount[d] for d, s in states.items() if s == "lost")
    still_open = sum(amount[d] for d, s in states.items() if s == "open")
    found = set(states.values())
    state = next((s for s in ("open", "lost", "won", "closed") if s in found), "")
    return still_open + lost, lost, state


def _record_dispute_totals(db: Session, booking: ConsultBooking) -> None:
    """Set the booking's dispute fields from its timeline (the caller holds
    the booking's lock and commits). No money is moved by this: the amounts
    only say what Stripe and the bank have done."""
    db.flush()
    lines = db.execute(
        select(ConsultBookingEvent.kind, ConsultBookingEvent.data, ConsultBookingEvent.amount_cents).where(
            ConsultBookingEvent.booking_id == booking.id,
            ConsultBookingEvent.kind.in_(("dispute_opened", "dispute_closed")),
        ).order_by(ConsultBookingEvent.id)
    ).all()
    disputed, lost, state = dispute_totals([(k, d, c) for k, d, c in lines])
    money.recompute(db, booking)
    # Never more than this booking was actually charged.
    ceiling = max(booking.charged_cents or 0, 0)
    booking.disputed_cents = min(disputed, ceiling)
    booking.dispute_lost_cents = min(lost, ceiling)
    booking.dispute_state = state


def note_dispute(db: Session, event_type: str, dispute: dict) -> bool:
    """charge.dispute.created / charge.dispute.closed (the webhook has
    verified Stripe's signature). True when the disputed payment belongs to
    a consulting booking: it is written on the booking's timeline, the
    booking's dispute amounts are set from it (no money is moved), and the
    owner is told, once per dispute and event however often Stripe delivers
    it. False for any other payment, which the caller handles as before."""
    payment_intent = dispute.get("payment_intent")
    if isinstance(payment_intent, dict):
        payment_intent = payment_intent.get("id")
    payment_intent = str(payment_intent or "")
    if not payment_intent:
        return False
    found = db.execute(
        select(ConsultCharge.id, ConsultCharge.booking_id).where(
            ConsultCharge.stripe_payment_intent_id == payment_intent,
            ConsultCharge.kind.in_(("charge", "hold")),
        )
    ).first()
    if found is None:
        return False
    closed = event_type == "charge.dispute.closed"
    kind = "dispute_closed" if closed else "dispute_opened"
    dispute_id = str(dispute.get("id") or "")[:64]
    status = str(dispute.get("status") or "")[:48]
    reason = str(dispute.get("reason") or "").replace("_", " ")[:80]
    amount = int(dispute.get("amount") or 0)
    with consult._STATE_MUTEX:
        booking = money.lock_booking(db, found.booking_id)
        if booking is None:
            db.commit()
            return True
        known = db.execute(
            select(ConsultBookingEvent.data).where(
                ConsultBookingEvent.booking_id == booking.id, ConsultBookingEvent.kind == kind,
            )
        ).scalars().all()
        if any((d or {}).get("dispute_id") == dispute_id for d in known):
            db.commit()
            return True  # delivered before
        if closed:
            note = {
                "won": "The dispute was decided in your favour: the money stays.",
                "lost": "The dispute was lost: Stripe returned the money to the cardholder.",
                "warning_closed": "The inquiry was closed without becoming a dispute.",
            }.get(status, f"The dispute was closed with the status '{status or 'not given'}'.")
        else:
            note = f"The cardholder disputed this payment with their bank. Reason given: {reason or 'none'}."
        add_event(db, booking, kind, actor="stripe", amount_cents=amount, note=note,
                  data={"dispute_id": dispute_id, "status": status, "ledger_id": found.id})
        _record_dispute_totals(db, booking)
        db.commit()
    booking = _load(db, found.booking_id)
    due_by = (dispute.get("evidence_details") or {}).get("due_by") if isinstance(dispute.get("evidence_details"), dict) else None
    rows = [("Disputed amount", consult.usd(amount)), ("Stripe dispute", dispute_id or "not given")]
    if closed:
        headline = {
            "won": "Dispute won", "lost": "Dispute LOST",
        }.get(status, "Dispute closed")
        detail = note + (
            " Stripe also keeps its dispute fee. The booking now shows this amount as lost to the "
            "dispute, and no longer as kept."
            if status == "lost" else ""
        )
    else:
        headline = "A client's bank has opened a dispute"
        detail = (
            f"{note} Stripe has taken the disputed amount out of your balance until the bank decides. "
            "Answer in the Stripe dashboard with your evidence: the booking's consent record (the terms "
            "the client agreed to, with time and address), the attendance record and the emails are in "
            "the admin panel."
        )
        if due_by:
            try:
                when = consult.when_text(datetime.fromtimestamp(int(due_by), timezone.utc), consult.settings_row(db).timezone)
                rows.append(("Evidence due by", when))
            except (TypeError, ValueError, OverflowError, OSError):
                pass
    consult.notify_owner(
        db, booking, template="consult_owner_dispute", headline=headline, detail=detail, extra_rows=rows,
        extra_link=("Open the dispute in Stripe", f"https://dashboard.stripe.com/disputes/{dispute_id}") if dispute_id else None,
    )
    return True


# -----------------------------------------------------------------------------
# The tick
# -----------------------------------------------------------------------------

def _ids(db: Session, *conditions) -> list[int]:
    return list(db.execute(
        select(ConsultBooking.id).where(*conditions).order_by(ConsultBooking.start_at, ConsultBooking.id)
    ).scalars().all())


def run_tick(db: Session, now: datetime | None = None) -> dict:
    """Do everything that is due. Called every five minutes by the cron job;
    calling it more often, or twice at once, changes nothing more.

    One booking's failure never stops the others: it is logged, listed under
    `problems` in the answer, and tried again on the next tick."""
    if not _TICK_LOCK.acquire(blocking=False):
        return {"ok": True, "busy": True, "problems": []}
    try:
        return _tick(db, now or consult.utcnow())
    finally:
        _TICK_LOCK.release()


def _tick(db: Session, now: datetime) -> dict:
    B = ConsultBooking
    done: Counter = Counter()
    problems: list[str] = []

    def each(step: str, ids: list[int], fn) -> None:
        for booking_id in ids:
            try:
                result = fn(booking_id)
            except Exception as exc:  # noqa: BLE001 — isolate one booking from the next
                db.rollback()
                log.exception("Consult tick: %s failed for booking %s", step, booking_id)
                problems.append(f"{step}: booking {booking_id}: {str(getattr(exc, 'message', exc))[:200]}")
                continue
            if result is True:
                done[step] += 1
            elif isinstance(result, str) and result:
                done[f"{step}:{result}"] += 1

    open_ = (B.status == "confirmed", B.settlement == "")
    upcoming = (B.status == "confirmed", B.start_at > now)

    # 1. Bookings whose card was never saved.
    try:
        done["expired"] = consult.expire_stale(db, now)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Consult tick: expiring stale bookings failed")
        problems.append(f"expire: {str(exc)[:200]}")

    # 2. Cancellations that were cut short (fee, calendar, emails).
    each("cancellation_finished", _ids(
        db, B.status == "cancelled", B.confirmed_at.is_not(None), B.cancel_notice_sent_at.is_(None),
        B.cancelled_at <= now - consult.CANCEL_RESUME_AFTER,
    ), lambda i: bool(consult.finish_cancellation(db, i)))

    # 3. Confirmed bookings Google has no event for yet.
    each("calendar", _ids(db, *upcoming, B.google_event_id == ""),
         lambda i: consult.retry_calendar_event(db, i))

    # 3b. Confirmation emails that did not go out when the card was saved
    #     (the email service refused them, or the server stopped in between).
    waiting = B.confirmation_sent_at.is_(None)
    if get_settings().ADMIN_NOTIFY_EMAIL:
        waiting = or_(waiting, B.owner_notified_at.is_(None))
    each("confirmation", _ids(db, *upcoming, waiting, B.confirmed_at <= now - consult.CANCEL_RESUME_AFTER),
         lambda i: consult.send_confirmation(db, i))

    # 3c. A client who saved a card for a time that could no longer be
    #     theirs, and whose "could not be confirmed" email did not go out.
    each("slot_lost_notice", _ids(
        db, B.status == "expired", B.cancel_notice_sent_at.is_(None), B.start_at > now - timedelta(days=1),
        exists().where(ConsultBookingEvent.booking_id == B.id, ConsultBookingEvent.kind == "slot_lost"),
    ), lambda i: consult.send_slot_lost_notice(db, i, now))

    # 4. Holds: place the ones that are due; then see to every hold that was
    #    refused (ask for a card, or cancel) or placed but not yet announced.
    each("hold", _ids(db, *open_, B.hold_state == "", B.hold_due_at <= now),
         lambda i: place_due_hold(db, i, now=now))
    # A card saved after the refusal and never tried (the webhook that saved
    # it stopped before its follow-up): the hold, or the refused amount, is
    # tried on it now. Before the step below, which would cancel for want of
    # a card.
    C = ConsultCharge
    last_refused = select(func.max(C.created_at)).where(
        C.booking_id == B.id, C.kind == "charge", C.status.in_(("failed", "requires_action")),
    ).scalar_subquery()
    each("new_card", _ids(db, B.card_saved_at <= now - consult.CANCEL_RESUME_AFTER, or_(
        and_(*open_, B.start_at > now, B.hold_state.in_(("failed", "requires_action")),
             B.card_saved_at > B.hold_failed_at),
        and_(B.settlement != "", B.charge_state.in_(("failed", "requires_action")),
             B.card_saved_at > last_refused),
    )), lambda i: retry_on_new_card(db, i, now=now))
    each("hold", _ids(
        db, *open_, B.start_at > now,
        or_(
            B.hold_state.in_(("failed", "requires_action")),
            (B.hold_state == "authorized") & B.hold_notice_sent_at.is_(None),
        ),
    ), lambda i: follow_hold(db, i, now=now))

    # 5. Reminders: the first while cancelling is still free, the last
    #    shortly before the start (send_reminder checks the exact window).
    cs = consult.settings_row(db)
    each("reminder_first", _ids(
        db, *upcoming, B.reminder_24h_sent_at.is_(None), B.free_cancel_until.is_not(None),
        B.free_cancel_until > now,
        B.free_cancel_until <= now + timedelta(hours=cs.reminder_before_deadline_hours or 24),
    ), lambda i: send_reminder(db, i, "first", now=now))
    each("reminder_last", _ids(
        db, *upcoming, B.reminder_1h_sent_at.is_(None),
        B.start_at <= now + timedelta(hours=cs.reminder_before_start_hours or 1),
    ), lambda i: send_reminder(db, i, "last", now=now))

    # 6. Calls that have reached their scheduled end: who joined, the
    #    owner's summary, then his choice or the default outcome.
    each("attendance", _ids(
        db, B.status.in_(("confirmed", "completed", "no_show")), B.end_at <= now,
        B.end_at > now - ATTENDANCE_GIVE_UP, B.attendance_checked_at.is_(None),
    ), lambda i: check_attendance(db, i, now=now))
    each("summary", _ids(db, *open_, B.end_at <= now, _summary_not_sent(now), B.owner_choice == ""),
         lambda i: send_summary(db, i, now=now))
    each("settled", _ids(
        db, *open_, B.end_at <= now, or_(B.owner_choice != "", B.settle_due_at <= now),
    ), lambda i: settle_due(db, i, now=now))

    # 7. Money steps that got no answer from Stripe the first time.
    each("collection", _ids(
        db, B.settlement.in_(tuple(money.SETTLEMENT_REASON)), B.charge_state == "pending",
    ), lambda i: finish_collection(db, i, now=now))
    each("release", _ids(
        db, B.hold_state == "authorized", B.status.in_(("cancelled", "completed", "no_show")),
        B.charge_state.in_(("", "paid")),
    ), lambda i: finish_release(db, i))
    # A hold whose answer was lost, on a booking that no longer wants one:
    # found at Stripe and let go. A refund whose answer was lost: Stripe is
    # asked whether it was made (requests of the last two minutes are left
    # to the request that is making them).
    C = ConsultCharge
    each("lost_hold", _ids(
        db, or_(B.status != "confirmed", B.settlement != ""),
        B.id.in_(select(C.booking_id).where(
            C.kind == "hold", C.status.in_(("pending", "needs_review")), C.error_code != "captured_elsewhere",
        )),
    ), lambda i: release_lost_hold(db, i))
    each("refund", _ids(db, B.id.in_(select(C.booking_id).where(
        C.kind == "refund", C.status.in_(("pending", "needs_review")),
        C.created_at <= now - consult.CANCEL_RESUME_AFTER,
    ))), lambda i: finish_refunds(db, i))

    try:
        cs = consult.settings_row(db)
        cs.last_tick_at = now
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        problems.append(f"last_tick_at: {str(exc)[:200]}")

    quiet = ("closed", "not_due", "open", "waiting", "exists", "authorized", "failed", "left", "kept")
    return {
        "ok": not problems,
        "at": consult._iso(now),
        "done": {k: v for k, v in sorted(done.items()) if v and k.split(":")[-1] not in quiet},
        "problems": problems,
    }
