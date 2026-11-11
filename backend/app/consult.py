"""Paid consulting calls: settings, slots, prices, bookings and their life.

One expert, meetings on Google Meet. The calendar side is exam_calendar's
(the same Google connection, FreeBusy over the same calendars, the same
slot arithmetic, the same lock); nothing about oral examinations changes.

What blocks a time: busy time on the checked Google calendars, other
consulting bookings (a pending one holds its slot until its hold runs out),
oral examinations, and the site's own live course sessions. A calendar that
cannot be read blocks every time.

The life of a booking:

  POST /book            pending_card: the slot is held for 20 minutes while
                        the client saves a card on Stripe (Checkout, setup
                        mode). Nothing is charged.
  Stripe webhook        confirmed: card saved, event with a Meet link on the
                        calendar, emails to both sides.
  cancel                cancelled: free until the free-cancellation moment,
                        the fee after it. The owner cancels at no charge.
  settle (admin / W1b)  completed or no_show: the outcome is decided and
                        the money collected (consult_money.collect).
  no card in time       expired: the slot goes back.

Prices exist in two places only: the quote and the booking. The terms the
client is shown carry the rate and the total, and the `terms_version` the
quote returns ends with a digest of that exact text; /book refuses unless
the digest it is sent matches the terms in force at that moment. So a
booking can never be stored at a price the client was not shown.

Money moves only through consult_money. What happens by itself after a
booking is confirmed (the hold, the reminders, attendance, the automatic
outcome, the cron tick) is in consult_auto, which calls back into this
module for every decision.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, object_session

from . import consult_money as money
from . import exam_calendar as xcal
from .config import get_settings
from .consult_models import ConsultBooking, ConsultBookingEvent, ConsultCharge, ConsultSettings
from .consult_money import PayResult, add_event, aware, charge_saved_card  # noqa: F401  (re-exported)
from .emailer import (
    consult_cancelled_html,
    consult_confirmed_html,
    consult_owner_new_html,
    consult_owner_update_html,
    consult_receipt_html,
    send_email,
)
from .models import ExamCalendar

log = logging.getLogger(__name__)

# The base version of the terms wording below. Bump it when the wording
# changes; the digest appended to it changes by itself with the numbers.
TERMS_VERSION = "2026-11-v1"
# A pending booking holds its slot this long while the card is entered.
PENDING_HOLD_MINUTES = 15
# Stripe will not let a Checkout Session expire sooner than 30 minutes
# after it is made; a card saved between the two limits is confirmed only
# if the slot is still free (see on_checkout_completed).
CHECKOUT_SESSION_MINUTES = 31
# A booking made inside the free-cancellation limit can still be cancelled
# free of charge for this long after it is confirmed.
GRACE_MINUTES = 15
# A cancellation whose follow-up (fee, calendar, emails) has not finished
# after this long was cut short; asking again then finishes it. Sooner than
# this, a repeat of the request is a repeat (a double click) and does nothing.
CANCEL_RESUME_AFTER = timedelta(minutes=2)
# Slot-hoarding guard: unfinished bookings one visitor may have at once
# (above that the visitor is refused), and how many reservations are kept
# open in all. An unfinished booking costs nothing, and the address and the
# email are whatever the visitor says they are, so the last number is the one
# that holds: at most three times are reserved by people who have not
# entered a card, for PENDING_HOLD_MINUTES each.
#
# At that ceiling a new booking is NOT refused (a stranger who keeps three
# open would then stop everybody from booking): it is let in, and the oldest
# unfinished booking's reservation ends early. That client can still finish:
# a card saved after the reservation ended is confirmed if the time is still
# free, and they are told plainly if it is not. Unfinished bookings do not
# count toward the day's cap either (three of them would close a day).
MAX_PENDING_PER_IP = 3
MAX_PENDING_PER_EMAIL = 2
MAX_PENDING_TOTAL = 3
# Google busy time is cached this long for the public availability list.
# Booking never uses the cache: it reads the calendars live, under the lock.
BUSY_CACHE_SECONDS = 30
# The cron tick runs every five minutes; the admin status strip calls it
# stopped when the last complete run is older than this.
TICK_STALE_AFTER = timedelta(minutes=30)
# When the tick has stopped and a confirmed call is this close, the owner
# is emailed, at most this often (see watch_tick).
TICK_ALERT_HORIZON = timedelta(hours=48)
TICK_ALERT_EVERY = timedelta(days=1)

TIERS = ("same_day", "next_day", "priority", "standard")
TIER_LABELS = {
    "same_day": "Same day",
    "next_day": "Next day",
    "priority": "Priority",
    "standard": "Standard",
}
STATUSES = ("pending_card", "confirmed", "cancelled", "completed", "no_show", "expired")
# The owner's default (10 Nov 2026): every day of the week, 08:00 to 23:00
# on the business clock. Editable in the admin panel.
DEFAULT_HOURS = {d: [["08:00", "23:00"]] for d in xcal.DAYS}
DEFAULT_DURATIONS = [30, 60, 90, 120]
MEET_SCOPE = xcal.MEET_SCOPE

# Second layer under the database lock: bookings made by this process are
# checked and written one at a time (SQLite has no row locks at all).
_BOOKING_MUTEX = threading.Lock()
# The same for a booking's own turning points (cancelled, outcome decided):
# the row lock decides in production; this decides where there is none. It
# is held only while the decision is read and written, never across a call
# to Stripe or Google.
_STATE_MUTEX = threading.Lock()
_BUSY_CACHE: dict = {}
_BUSY_CACHE_LOCK = threading.Lock()


class ConsultError(Exception):
    """A refusal with words fit to show. `status_code` is the HTTP answer."""

    status_code = 409

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SlotGone(ConsultError):
    """The chosen time is no longer free."""


class TermsChanged(ConsultError):
    """The price or terms for this time are not the ones the client saw."""


class Refused(ConsultError):
    """The booking is not in a state that allows this."""


class Unavailable(ConsultError):
    """Booking cannot be offered right now (switched off, calendar unreadable)."""

    status_code = 503


class TooMany(ConsultError):
    status_code = 429


class CheckoutFailed(ConsultError):
    """Stripe would not start card entry."""

    status_code = 502


class InvalidInput(ConsultError):
    """A field is wrong. `field` names it for the 422 answer."""

    status_code = 422

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def utcnow() -> datetime:
    return money.utcnow()


def _iso(dt: datetime | None) -> str | None:
    return aware(dt).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def usd(cents: int) -> str:
    """'$45', '$62.50', '$1,234'."""
    cents = int(cents or 0)
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def valid_zone(name: str) -> bool:
    try:
        ZoneInfo((name or "").strip())
        return bool((name or "").strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def stripe_configured() -> bool:
    return bool(get_settings().STRIPE_SECRET_KEY)


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------

def settings_row(db: Session) -> ConsultSettings:
    cs = db.get(ConsultSettings, 1)
    if cs is None:
        # No rate and switched off: this repository is public, so the rates
        # exist only in the database, entered by the owner in the admin panel.
        cs = ConsultSettings(
            id=1, enabled=False, timezone="America/New_York",
            weekly_hours={d: [list(w) for w in ws] for d, ws in DEFAULT_HOURS.items()},
            durations=list(DEFAULT_DURATIONS),
        )
        db.add(cs)
        db.commit()
        db.refresh(cs)
    return cs


def zone(cs: ConsultSettings) -> ZoneInfo:
    return xcal.zone(cs)


def durations(cs: ConsultSettings) -> list[int]:
    out = sorted({int(d) for d in (cs.durations or DEFAULT_DURATIONS)})
    return out or list(DEFAULT_DURATIONS)


def rates(cs: ConsultSettings) -> dict[str, int]:
    return {
        "same_day": int(cs.rate_same_day_cents or 0),
        "next_day": int(cs.rate_next_day_cents or 0),
        "priority": int(cs.rate_priority_cents or 0),
        "standard": int(cs.rate_standard_cents or 0),
    }


def rates_set(cs: ConsultSettings) -> bool:
    """Every tier has a rate. Until then nothing is quoted or booked: the
    code carries no rate of its own (0 means "not set")."""
    return all(cents > 0 for cents in rates(cs).values())


def bookable(cs: ConsultSettings) -> bool:
    """Booking is switched on and has prices to quote."""
    return bool(cs.enabled) and rates_set(cs)


def settings_out(cs: ConsultSettings) -> dict:
    return {
        "enabled": bool(cs.enabled),
        "timezone": cs.timezone,
        "weekly_hours": {d: list((cs.weekly_hours or {}).get(d, [])) for d in xcal.DAYS},
        "step_minutes": cs.step_minutes,
        "durations": durations(cs),
        "buffer_minutes": cs.buffer_minutes,
        "min_notice_hours": cs.min_notice_hours,
        "horizon_days": cs.horizon_days,
        "max_per_day": cs.max_per_day,
        "rates_cents_per_hour": rates(cs),
        # Read-only: false until all four rates have been saved. Booking
        # cannot be switched on before that.
        "rates_set": rates_set(cs),
        "standard_from_days": cs.standard_from_days,
        "fee_percent": cs.fee_percent,
        "free_cancel_hours": cs.free_cancel_hours,
        "hold_lead_hours": cs.hold_lead_hours,
        "auto_settle_hours": cs.auto_settle_hours,
        # Client reminders: the first, this many hours before the booking's
        # free-cancellation deadline; the last, this many before the start.
        "reminder_before_deadline_hours": cs.reminder_before_deadline_hours,
        "reminder_before_start_hours": cs.reminder_before_start_hours,
        # Fixed in code; shown so the admin screen can state them.
        "pending_hold_minutes": PENDING_HOLD_MINUTES,
        "grace_minutes": GRACE_MINUTES,
        "terms_version": TERMS_VERSION,
    }


def update_settings(db: Session, data: dict) -> ConsultSettings:
    """Apply the admin's changes; anything absent stays. ValueError says, in
    words, what is wrong. Existing bookings keep the terms they were made on."""
    cs = settings_row(db)
    if "enabled" in data:
        cs.enabled = bool(data["enabled"])
    if "timezone" in data:
        name = str(data["timezone"] or "").strip()
        if not valid_zone(name):
            raise ValueError(f"Unknown time zone {name!r}.")
        cs.timezone = name
    if "weekly_hours" in data:
        hours = data["weekly_hours"] or {}
        if not isinstance(hours, dict):
            raise ValueError("Consulting hours must be given per weekday.")
        clean: dict[str, list[list[str]]] = {}
        for d in xcal.DAYS:
            windows = hours.get(d) or []
            if not isinstance(windows, (list, tuple)) or len(windows) > 4:
                raise ValueError("At most four time windows per day.")
            day_windows = []
            for w in windows:
                if not (isinstance(w, (list, tuple)) and len(w) == 2):
                    raise ValueError("Each window is a start and an end time.")
                a, b = str(w[0]).strip(), str(w[1]).strip()
                if not (xcal._HHMM.match(a) and xcal._HHMM.match(b)):
                    raise ValueError(f"Times must look like 09:00 ({d}: {a} to {b}).")
                if a >= b:
                    raise ValueError(f"A window must end after it starts ({d}: {a} to {b}).")
                day_windows.append([a, b])
            day_windows.sort()
            for (_, end_prev), (start_next, _) in zip(day_windows, day_windows[1:]):
                if start_next < end_prev:
                    raise ValueError(f"The time windows on {d} overlap.")
            clean[d] = day_windows
        cs.weekly_hours = clean
    if "step_minutes" in data:
        step = xcal._bounded(data["step_minutes"], 15, 60, "Start times every (minutes)")
        if step not in (15, 30, 60):
            raise ValueError("Start times can be every 15, 30 or 60 minutes.")
        cs.step_minutes = step
    if "durations" in data:
        raw = data["durations"]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError("Give at least one call length.")
        values = sorted({xcal._bounded(v, 30, 480, "A call length (minutes)") for v in raw})
        if any(v % 30 for v in values):
            raise ValueError("Call lengths are billed in 30-minute steps: use 30, 60, 90, ...")
        if len(values) > 8:
            raise ValueError("At most eight call lengths.")
        cs.durations = values
    if "buffer_minutes" in data:
        cs.buffer_minutes = xcal._bounded(data["buffer_minutes"], 0, 240, "The gap around busy time (minutes)")
    if "min_notice_hours" in data:
        cs.min_notice_hours = xcal._bounded(data["min_notice_hours"], 0, 720, "The minimum notice (hours)")
    if "horizon_days" in data:
        cs.horizon_days = xcal._bounded(data["horizon_days"], 1, 365, "How far ahead (days)")
    if "max_per_day" in data:
        cs.max_per_day = xcal._bounded(data["max_per_day"], 0, 20, "Calls per day")
    if "rates_cents_per_hour" in data:
        given = data["rates_cents_per_hour"] or {}
        if not isinstance(given, dict):
            raise ValueError("Rates are given per tier.")
        unknown = set(given) - set(TIERS)
        if unknown:
            raise ValueError(f"Unknown tier {sorted(unknown)[0]!r}.")
        for tier, value in given.items():
            if value in (0, None) and not getattr(cs, f"rate_{tier}_cents"):
                continue  # still not set: the form sent back the empty value it was given
            cents = xcal._bounded(value, 100, 10_000_000, f"The {TIER_LABELS[tier].lower()} rate (cents per hour)")
            if cents % 100:
                raise ValueError("Rates are whole dollars per hour.")
            setattr(cs, f"rate_{tier}_cents", cents)
    if "standard_from_days" in data:
        cs.standard_from_days = xcal._bounded(data["standard_from_days"], 2, 60, "Standard rate from (days ahead)")
    if "fee_percent" in data:
        cs.fee_percent = xcal._bounded(data["fee_percent"], 0, 100, "The fee (percent)")
    if "free_cancel_hours" in data:
        cs.free_cancel_hours = xcal._bounded(data["free_cancel_hours"], 0, 720, "Free cancellation until (hours before)")
    if "hold_lead_hours" in data:
        # Card authorizations lapse within days; a hold is never placed
        # earlier than four days before the call.
        cs.hold_lead_hours = xcal._bounded(data["hold_lead_hours"], 1, 96, "The hold (hours before)")
    if "auto_settle_hours" in data:
        cs.auto_settle_hours = xcal._bounded(data["auto_settle_hours"], 0, 72, "The default outcome (hours after)")
    if "reminder_before_deadline_hours" in data:
        cs.reminder_before_deadline_hours = xcal._bounded(
            data["reminder_before_deadline_hours"], 1, 168,
            "The first reminder (hours before the free-cancellation deadline)")
    if "reminder_before_start_hours" in data:
        cs.reminder_before_start_hours = xcal._bounded(
            data["reminder_before_start_hours"], 1, 48, "The last reminder (hours before the start)")
    if (cs.hold_lead_hours or 0) + (cs.auto_settle_hours or 0) > 120:
        # From the hold to the default outcome must fit inside the life of
        # a card authorization, or there is nothing left to capture.
        raise ValueError(
            "The hold (hours before) plus the default outcome (hours after) can be at most 120 hours "
            "together: a card authorization lapses after about five to seven days."
        )
    if cs.enabled and not rates_set(cs):
        missing = ", ".join(TIER_LABELS[t].lower() for t, cents in rates(cs).items() if cents <= 0)
        raise ValueError(
            f"Booking cannot be switched on until every hourly rate is set. Still missing: {missing}."
        )
    db.commit()
    db.refresh(cs)
    return cs


# -----------------------------------------------------------------------------
# Price and terms
# -----------------------------------------------------------------------------

def tier_for(cs: ConsultSettings, start: datetime, now: datetime) -> str:
    """Urgency, by the slot's calendar date on the business clock."""
    tz = zone(cs)
    days = (aware(start).astimezone(tz).date() - aware(now).astimezone(tz).date()).days
    if days <= 0:
        return "same_day"
    if days == 1:
        return "next_day"
    if days < (cs.standard_from_days or 7):
        return "priority"
    return "standard"


def amount_for(rate_cents_per_hour: int, minutes: int) -> int:
    """Billing is in 30-minute steps: 30 minutes is half the hourly rate."""
    half_hours = int(minutes) // 30
    return int(rate_cents_per_hour) * half_hours // 2


def fee_for(total_cents: int, fee_percent: int) -> int:
    return (int(total_cents) * int(fee_percent) + 50) // 100


def build_terms(
    *, tier: str, rate_cents_per_hour: int, minutes: int, total_cents: int,
    fee_percent: int, fee_cents: int, free_cancel_hours: int, hold_lead_hours: int,
) -> list[str]:
    """The terms shown before card entry, in plain words. This exact text is
    what the client agrees to; its hash goes on the booking."""
    return [
        f"Your rate is {usd(rate_cents_per_hour)} per hour ({TIER_LABELS[tier].lower()} booking), "
        f"billed in 30-minute steps. This {minutes}-minute call comes to {usd(total_cents)}.",
        "Nothing is charged today. Your card is saved securely with Stripe and is charged only "
        "after the meeting.",
        f"A temporary hold for {usd(total_cents)} is placed on your card {hold_lead_hours} hours before "
        "the call, or right after you save the card when the call is sooner than that. A hold is "
        "not a charge.",
        f"You can cancel free of charge until {free_cancel_hours} hours before the call. If you book "
        f"less than {free_cancel_hours} hours ahead, you can cancel free of charge within "
        f"{GRACE_MINUTES} minutes of booking.",
        f"If you cancel later than that, or do not join the call, a fee of {fee_percent}% of the booked "
        f"amount ({usd(fee_cents)}) is charged and the rest of the hold is released.",
        "To contest a charge, reply to your receipt email. Our support team handles every request.",
        "Do not share third-party proprietary information or export-controlled information, in "
        "the call or in any message. Such information will not be discussed.",
    ]


def free_cancel_deadline(start: datetime, free_cancel_hours: int, grace_minutes: int, booked_at: datetime) -> datetime:
    """Until when cancelling is free: `free_cancel_hours` before the start,
    or `grace_minutes` after the booking, whichever is later.

    On a booking, `booked_at` is the moment the card was saved. Before that
    (a quote, a pending booking) it is "now", which makes the answer the
    earliest the real deadline can turn out to be: never a promise the
    booking will not keep."""
    return max(start - timedelta(hours=free_cancel_hours), booked_at + timedelta(minutes=grace_minutes))


def terms_hash(terms: list[str]) -> str:
    return hashlib.sha256("\n".join(terms).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Quote:
    start: datetime
    minutes: int
    tier: str
    rate_cents_per_hour: int
    total_cents: int
    fee_percent: int
    fee_cents: int
    free_cancel_until: datetime | None
    hold_at: datetime
    terms: list[str]
    terms_hash: str
    terms_version: str

    def out(self) -> dict:
        return {
            "start": _iso(self.start),
            "minutes": self.minutes,
            "tier": self.tier,
            "tier_label": TIER_LABELS[self.tier],
            "rate_cents_per_hour": self.rate_cents_per_hour,
            "total_cents": self.total_cents,
            "fee_percent": self.fee_percent,
            "fee_cents": self.fee_cents,
            "free_cancel_until": _iso(self.free_cancel_until),
            "hold_at": _iso(self.hold_at),
            "terms_version": self.terms_version,
            "terms": list(self.terms),
        }


def make_quote(cs: ConsultSettings, start: datetime, minutes: int, now: datetime) -> Quote:
    """The price and terms for `minutes` starting at `start`, as of `now`."""
    start = aware(start).astimezone(timezone.utc)
    tier = tier_for(cs, start, now)
    rate = rates(cs)[tier]
    if rate <= 0:
        # No price, no quote, and so no booking: never a call stored at zero.
        raise Unavailable("Booking is temporarily unavailable.")
    total = amount_for(rate, minutes)
    fee = fee_for(total, cs.fee_percent)
    terms = build_terms(
        tier=tier, rate_cents_per_hour=rate, minutes=minutes, total_cents=total,
        fee_percent=cs.fee_percent, fee_cents=fee,
        free_cancel_hours=cs.free_cancel_hours, hold_lead_hours=cs.hold_lead_hours,
    )
    digest = terms_hash(terms)
    hold_at = start - timedelta(hours=cs.hold_lead_hours)
    return Quote(
        start=start, minutes=minutes, tier=tier, rate_cents_per_hour=rate, total_cents=total,
        fee_percent=cs.fee_percent, fee_cents=fee,
        free_cancel_until=free_cancel_deadline(start, cs.free_cancel_hours, GRACE_MINUTES, now),
        hold_at=hold_at if hold_at > now else now,
        terms=terms, terms_hash=digest,
        # The version names the exact text: /book must send this back.
        terms_version=f"{TERMS_VERSION}.{digest[:16]}",
    )


# -----------------------------------------------------------------------------
# Busy time
# -----------------------------------------------------------------------------

Block = tuple[datetime, datetime]


def _google_busy(db: Session, low: datetime, high: datetime, *, live: bool) -> list[Block]:
    """Busy time on every checked Google calendar. Raises xcal.CalendarError
    when the calendar is not connected or any calendar cannot be read.
    Makes no database write (it runs inside the booking lock)."""
    cal = db.get(ExamCalendar, 1)
    if cal is None or not cal.refresh_token_encrypted:
        raise xcal.CalendarError("The calendar is not connected.")
    ids = tuple(cal.check_calendars or ["primary"])
    if not live:
        with _BUSY_CACHE_LOCK:
            hit = dict(_BUSY_CACHE)
        if (
            hit and hit["ids"] == ids and time.monotonic() - hit["at"] < BUSY_CACHE_SECONDS
            and hit["low"] <= low and hit["high"] >= high
        ):
            return list(hit["busy"])
    # Asked a little wider than needed, so the cached answer still covers
    # the window a few seconds later.
    wide_low, wide_high = low - timedelta(hours=1), high + timedelta(hours=1)
    busy = xcal.busy_blocks(cal, wide_low, wide_high)
    with _BUSY_CACHE_LOCK:
        _BUSY_CACHE.clear()
        _BUSY_CACHE.update(ids=ids, at=time.monotonic(), low=wide_low, high=wide_high, busy=list(busy))
    return busy


def clear_cache() -> None:
    with _BUSY_CACHE_LOCK:
        _BUSY_CACHE.clear()


def _holding(now: datetime):
    """SQL condition: bookings that occupy their slot at `now`."""
    return or_(
        ConsultBooking.status == "confirmed",
        (ConsultBooking.status == "pending_card") & (ConsultBooking.hold_expires_at > now),
    )


def consult_blocks(db: Session, now: datetime, *, exclude_id: int | None = None) -> list[Block]:
    """Consulting bookings that hold a slot: confirmed ones, and pending ones
    whose hold has not run out."""
    db.flush()
    rows = db.execute(
        select(ConsultBooking.id, ConsultBooking.start_at, ConsultBooking.end_at)
        .where(_holding(now), ConsultBooking.end_at > now - timedelta(days=1))
    ).all()
    return [(aware(s), aware(e)) for row_id, s, e in rows if row_id != exclude_id]


def exam_blocks(db: Session) -> list[Block]:
    minutes = get_settings().ADVANCED_INTERVIEW_MINUTES
    return [(s, s + timedelta(minutes=minutes)) for s in xcal.booked_exam_starts(db)]


def course_blocks(db: Session, low: datetime, high: datetime) -> list[Block]:
    """The site's own live course sessions: every Course day at the session
    clock time, for the session length. A day with no clock time blocks
    whole; a session with no length blocks to the end of its day. One
    source for both calendars: oral-exam slots use the same function."""
    return xcal.course_blocks(db, low, high)


def busy_blocks(
    db: Session, cs: ConsultSettings, now: datetime, *, live: bool, exclude_id: int | None = None,
) -> list[Block]:
    """Everything that blocks a consulting slot inside the booking window."""
    pad = timedelta(minutes=cs.buffer_minutes or 0, hours=1)
    low = now - pad
    high = now + timedelta(days=cs.horizon_days or 60) + pad
    blocks = list(_google_busy(db, low, high, live=live))
    blocks += consult_blocks(db, now, exclude_id=exclude_id)
    blocks += exam_blocks(db)
    blocks += course_blocks(db, low, high)
    return blocks


def _day_counts(db: Session, cs: ConsultSettings, now: datetime, *, exclude_id: int | None = None) -> Counter:
    """Consulting calls per business-clock date (for the daily cap): every
    booking of that day with a card on it that was not cancelled. A call
    that has taken place (or was a no-show) still counts: "at most N a day"
    is about the day. An unfinished booking (no card yet) does not count: it
    costs nothing to make, and three of them must not close a day. The cap
    is checked again when the card is saved (_cannot_confirm)."""
    tz = zone(cs)
    db.flush()
    rows = db.execute(
        select(ConsultBooking.id, ConsultBooking.start_at)
        .where(
            ConsultBooking.status.in_(("confirmed", "completed", "no_show")),
            ConsultBooking.end_at > now - timedelta(days=1),
        )
    ).all()
    return Counter(aware(s).astimezone(tz).date() for row_id, s in rows if row_id != exclude_id)


def _rules(cs: ConsultSettings, minutes: int) -> xcal.Rules:
    # exam_calendar's rules() reads the same attribute names off either
    # settings row. The daily cap is applied here (it counts consulting
    # calls only), so the shared arithmetic gets none.
    return replace(
        xcal.rules(cs, minutes),
        minutes=minutes,
        notice_hours=cs.min_notice_hours or 0,
        horizon_days=cs.horizon_days or 60,
        max_per_day=0,
    )


def open_slots(
    db: Session, cs: ConsultSettings, now: datetime, *, live: bool, only_minutes: int | None = None,
) -> dict[datetime, int]:
    """{start (UTC): longest call that fits there}. Raises CalendarError."""
    blocks = busy_blocks(db, cs, now, live=live)
    counts = _day_counts(db, cs, now)
    cap = cs.max_per_day or 0
    tz = zone(cs)
    out: dict[datetime, int] = {}
    wanted = [only_minutes] if only_minutes else durations(cs)
    for i, minutes in enumerate(wanted):
        for start in xcal.compute_slots(_rules(cs, minutes), now=now, busy=blocks, booked=[]):
            if cap > 0 and counts[start.astimezone(tz).date()] >= cap:
                continue
            # A longer call fits only where every shorter one does.
            if i == 0 or out.get(start) == wanted[i - 1]:
                out[start] = minutes
    return out


def _calendar_failed(db: Session, exc: Exception) -> None:
    """A connected calendar could not be read: record it and tell the owner
    through the existing calendar alert (at most twice a day)."""
    db.rollback()
    if not xcal.connected(db):
        return
    try:
        from . import advanced_cert  # noqa: PLC0415 — heavy module, needed only here

        advanced_cert.calendar_trouble(db, str(exc))
    except Exception:  # noqa: BLE001 — the alert must not break the request
        log.exception("Could not record the calendar failure")
        db.rollback()


def availability(db: Session, tz_name: str = "", now: datetime | None = None) -> dict:
    """The public list of open times. Never a price."""
    cs = settings_row(db)
    now = now or utcnow()
    out = {
        "enabled": bookable(cs) and stripe_configured(),
        "business_timezone": cs.timezone,
        "step_minutes": cs.step_minutes,
        "durations": durations(cs),
        "days": [],
        "next_available": None,
    }
    if not out["enabled"]:
        return out
    expire_stale(db, now)
    try:
        slots = open_slots(db, cs, now, live=False)
    except xcal.CalendarError as exc:
        _calendar_failed(db, exc)
        out["enabled"] = False
        return out
    view = ZoneInfo(tz_name.strip()) if valid_zone(tz_name) else zone(cs)
    days: dict[str, list[dict]] = {}
    for start in sorted(slots):
        days.setdefault(start.astimezone(view).date().isoformat(), []).append({
            "start": _iso(start), "max_minutes": slots[start], "tier": tier_for(cs, start, now),
        })
    out["days"] = [{"date": d, "slots": s} for d, s in days.items()]
    if slots:
        first = min(slots)
        out["next_available"] = {"start": _iso(first), "tier": tier_for(cs, first, now)}
    return out


def _normal_start(start: datetime) -> datetime:
    if start.tzinfo is None:
        raise InvalidInput("start", "The start time must carry a time zone, for example 2026-11-12T15:00:00Z.")
    return start.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _check_minutes(cs: ConsultSettings, minutes: int) -> None:
    if minutes not in durations(cs):
        allowed = ", ".join(str(d) for d in durations(cs))
        raise InvalidInput("minutes", f"Choose one of these call lengths, in minutes: {allowed}.")


def quote_for(db: Session, start: datetime, minutes: int, now: datetime | None = None) -> Quote:
    """The quote for an open slot. SlotGone when the time is not open."""
    cs = settings_row(db)
    now = now or utcnow()
    if not bookable(cs) or not stripe_configured():
        raise Unavailable("Booking is temporarily unavailable.")
    start = _normal_start(start)
    _check_minutes(cs, minutes)
    try:
        slots = open_slots(db, cs, now, live=False, only_minutes=minutes)
    except xcal.CalendarError as exc:
        _calendar_failed(db, exc)
        raise Unavailable("Booking is temporarily unavailable.") from exc
    if start not in slots:
        raise SlotGone("That time is no longer available. Please pick another one.")
    return make_quote(cs, start, minutes, now)


# -----------------------------------------------------------------------------
# The manage token
# -----------------------------------------------------------------------------

def _token_secret() -> bytes:
    s = get_settings()
    return (s.SESSION_SECRET or s.ADMIN_TOKEN or "dev-only").encode("utf-8")


def _derive_token(ref: str, salt: str) -> str:
    mac = hmac.new(_token_secret(), f"consult-manage:{ref}:{salt}".encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def check_token(booking: ConsultBooking, token: str) -> bool:
    if not token or not booking.manage_token_hash:
        return False
    return hmac.compare_digest(_token_hash(token), booking.manage_token_hash)


def manage_token(db: Session, booking: ConsultBooking) -> str:
    """The booking's manage token, minted again for an email. Only its hash
    is stored. If the server secret has changed since the booking was made,
    the old token cannot be reproduced: a new one replaces it (the caller is
    about to send the client the new link)."""
    token = _derive_token(booking.ref, booking.manage_token_salt)
    if not check_token(booking, token):
        booking.manage_token_salt = secrets.token_hex(16)
        token = _derive_token(booking.ref, booking.manage_token_salt)
        booking.manage_token_hash = _token_hash(token)
        add_event(db, booking, "manage_link_renewed", note="The server secret changed; a new manage link was issued.")
        db.commit()
    return token


def booking_url(booking: ConsultBooking, token: str) -> str:
    return f"{get_settings().SITE_URL.rstrip('/')}/consult/booking/{booking.ref}?t={token}"


def find_booking(db: Session, ref: str, token: str) -> ConsultBooking | None:
    """The booking for a public request, or None unless the token fits."""
    ref = (ref or "").strip().upper()
    if not ref or len(ref) > 16:
        return None
    booking = db.execute(select(ConsultBooking).where(ConsultBooking.ref == ref)).scalar_one_or_none()
    if booking is None or not check_token(booking, token):
        return None
    return booking


_REF_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _new_ref(db: Session) -> str:
    for _ in range(20):
        ref = "C-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))
        if db.execute(select(ConsultBooking.id).where(ConsultBooking.ref == ref)).first() is None:
            return ref
    raise RuntimeError("Could not make a booking reference.")


# -----------------------------------------------------------------------------
# Booking
# -----------------------------------------------------------------------------

def _end_oldest_reservations(db: Session, now: datetime, *, keep: int) -> int:
    """End the reservation of the oldest unfinished bookings until at most
    `keep` are left (the caller holds the booking lock and commits). Such a
    booking is 'expired' from now on: its time is free again, and if its
    client still saves a card the booking is confirmed when the time is
    still free (on_checkout_completed), and they are emailed when it is not."""
    live = db.execute(
        select(ConsultBooking).where(
            ConsultBooking.status == "pending_card", ConsultBooking.hold_expires_at > now,
        ).order_by(ConsultBooking.created_at, ConsultBooking.id)
    ).scalars().all()
    ended = live[:max(len(live) - keep, 0)]
    for booking in ended:
        booking.status = "expired"
        booking.hold_expires_at = now
        add_event(db, booking, "expired", at=now, note=(
            "The reservation was ended early: several people were booking at the same moment and it was "
            "the oldest without a card. The time is confirmed all the same if it is still free when the "
            "card is saved."))
    if ended:
        log.warning("Consult: %d unfinished booking(s) had their reservation ended early", len(ended))
    return len(ended)


def expire_stale(db: Session, now: datetime | None = None, *, commit: bool = True) -> int:
    """Pending bookings whose hold ran out become 'expired'. Their slots were
    free from the moment the hold ended (nothing counts a lapsed hold); this
    only records it. Idempotent."""
    now = now or utcnow()
    db.flush()
    # In id order, skipping rows another sweep holds: two sweeps at once
    # (this runs on public requests) never wait on each other.
    rows = db.execute(
        select(ConsultBooking).where(
            ConsultBooking.status == "pending_card", ConsultBooking.hold_expires_at <= now,
        ).order_by(ConsultBooking.id).with_for_update(skip_locked=True)
    ).scalars().all()
    for booking in rows:
        booking.status = "expired"
        add_event(db, booking, "expired", at=now,
                  note=f"No card was saved within {PENDING_HOLD_MINUTES} minutes; the time was released.")
    if rows and commit:
        db.commit()
    return len(rows)


def _start_card_setup(db: Session, booking: ConsultBooking, token: str, *, purpose: str) -> str:
    """A Stripe Checkout Session in setup mode for this booking: the card is
    saved to the booking's own Customer for off-session use, and nothing is
    charged. Returns the hosted page's URL. `purpose`: 'book' | 'card'."""
    stripe = money._stripe()
    base = booking_url(booking, token)
    try:
        if not booking.stripe_customer_id:
            customer = stripe.Customer.create(
                email=booking.email, name=booking.full_name,
                metadata={"kind": "consult", "booking_ref": booking.ref},
            )
            booking.stripe_customer_id = str(money._g(customer, "id", ""))
            db.commit()
        page = dict(
            mode="setup",
            customer=booking.stripe_customer_id,
            payment_method_types=["card"],
            success_url=f"{base}&card=ok",
            cancel_url=f"{base}&card=cancelled",
            client_reference_id=booking.ref,
            metadata={
                "kind": "consult", "booking_id": str(booking.id),
                "booking_ref": booking.ref, "purpose": purpose,
            },
            setup_intent_data={"metadata": {"kind": "consult", "booking_ref": booking.ref}},
        )
        # Two things the page is better with and works without:
        #   expires_at      the short life only narrows the window in which a
        #                   card can be saved after the hold has run out, and
        #                   that case is handled either way
        #                   (on_checkout_completed checks the time again);
        #   wallet_options  a card page, as the terms say: without this
        #                   Stripe's page also offers Link, and through it a
        #                   bank account, wherever cards are accepted. Apple
        #                   Pay and Google Pay stay: they are cards.
        # Should Stripe refuse either one, the page is made without it.
        extras = {
            "expires_at": int(time.time()) + CHECKOUT_SESSION_MINUTES * 60,
            "wallet_options": {"link": {"display": "never"}},
        }
        while True:
            try:
                session = stripe.checkout.Session.create(**page, **extras)
                break
            except Exception as exc:
                refused = str(getattr(exc, "param", None) or "").split("[")[0]
                if refused not in extras:
                    raise
                log.warning("Stripe refused %s on a setup session (%s); making the page without it", refused, exc)
                del extras[refused]
    except Exception as exc:
        log.error("Stripe would not start card setup for %s: %s", booking.ref, exc)
        raise CheckoutFailed("Could not open card entry. Please try again.") from exc
    url = str(money._g(session, "url", "") or "")
    if not url:
        raise CheckoutFailed("Could not open card entry. Please try again.")
    booking.stripe_checkout_session_id = str(money._g(session, "id", ""))[:128]
    db.commit()
    return url


def create_booking(
    db: Session, *, start: datetime, minutes: int, full_name: str, email: str, topic: str,
    timezone_name: str, terms_version: str, company: str = "", phone: str = "",
    ip: str = "", user_agent: str = "", now: datetime | None = None,
) -> tuple[ConsultBooking, str, str]:
    """Hold the slot and open card entry. Returns (booking, manage token,
    Stripe URL).

    The slot is checked against the live calendars and written under the
    calendar lock, so two people cannot both be given the same time. The
    price stored is the one in force now, and only if it is the one the
    client was shown (terms_version)."""
    cs = settings_row(db)
    now = now or utcnow()
    if not bookable(cs):
        raise Unavailable("Booking is temporarily unavailable.")
    money._stripe()  # 503 here, before anything is held, when payments are not set up
    start = _normal_start(start)
    _check_minutes(cs, minutes)
    if not valid_zone(timezone_name):
        raise InvalidInput("timezone", "Unknown time zone.")
    quote = make_quote(cs, start, minutes, now)
    if terms_version != quote.terms_version:
        raise TermsChanged(
            "The price or terms for this time have changed since they were shown. "
            "Please choose your time again to see the current quote."
        )
    email = email.strip().lower()

    with _BOOKING_MUTEX:
        xcal.lock(db)
        expire_stale(db, now, commit=False)
        waiting = db.execute(
            select(ConsultBooking.consent_ip, ConsultBooking.email).where(
                ConsultBooking.status == "pending_card", ConsultBooking.hold_expires_at > now,
            )
        ).all()
        if (ip and sum(1 for w in waiting if w.consent_ip == ip) >= MAX_PENDING_PER_IP) or (
            sum(1 for w in waiting if w.email == email) >= MAX_PENDING_PER_EMAIL
        ):
            db.commit()
            raise TooMany(
                "You already have a booking waiting for a card. Finish that one, or wait "
                f"{PENDING_HOLD_MINUTES} minutes for it to lapse."
            )
        try:
            slots = open_slots(db, cs, now, live=True, only_minutes=minutes)
        except xcal.CalendarError as exc:
            _calendar_failed(db, exc)
            raise Unavailable("Booking is temporarily unavailable.") from exc
        if start not in slots:
            db.commit()  # keeps the expiries just recorded; lets go of the lock
            raise SlotGone("That time is no longer available. Please pick another one.")
        # This booking will be made. If that takes the reservations past the
        # ceiling, the oldest ones end now (never this visitor's refusal).
        _end_oldest_reservations(db, now, keep=MAX_PENDING_TOTAL - 1)
        salt = secrets.token_hex(16)
        ref = _new_ref(db)
        token = _derive_token(ref, salt)
        booking = ConsultBooking(
            ref=ref, manage_token_hash=_token_hash(token), manage_token_salt=salt,
            status="pending_card", start_at=start, end_at=start + timedelta(minutes=minutes),
            minutes=minutes, hold_expires_at=now + timedelta(minutes=PENDING_HOLD_MINUTES),
            full_name=full_name.strip(), email=email, company=(company or "").strip(),
            phone=(phone or "").strip(), topic=topic.strip(), timezone=timezone_name.strip(),
            tier=quote.tier, rate_cents_per_hour=quote.rate_cents_per_hour,
            total_cents=quote.total_cents, currency="usd",
            fee_percent=quote.fee_percent, fee_cents=quote.fee_cents,
            free_cancel_hours=cs.free_cancel_hours, grace_minutes=GRACE_MINUTES,
            hold_lead_hours=cs.hold_lead_hours, auto_settle_hours=cs.auto_settle_hours,
            terms_version=quote.terms_version, terms_hash=quote.terms_hash,
            terms_text=list(quote.terms), consent_at=now, consent_ip=(ip or "")[:64],
            consent_user_agent=(user_agent or "")[:400], created_at=now,
        )
        db.add(booking)
        db.flush()
        add_event(db, booking, "created", actor="client", at=now, amount_cents=quote.total_cents,
                  note=f"{minutes} minutes, {TIER_LABELS[quote.tier].lower()} rate. Terms {quote.terms_version} accepted.")
        db.commit()  # the slot is held; the lock is released

    booking_id = booking.id
    try:
        url = _start_card_setup(db, booking, token, purpose="book")
    except Exception:
        # No card page, so no way to finish: give the slot back at once.
        db.rollback()
        booking = money.lock_booking(db, booking_id)
        if booking is not None and booking.status == "pending_card":
            booking.status = "expired"
            add_event(db, booking, "checkout_failed", note="Stripe did not open card entry; the time was released.")
        db.commit()
        raise
    return booking, token, url


def card_page_purpose(booking: ConsultBooking, now: datetime) -> str:
    """Why this booking may open a card page now: 'book' (finish a pending
    booking), 'card' (replace the card on one that still has, or may have,
    something to pay), or '' (it may not)."""
    status = effective_status(booking, now)
    if status == "pending_card":
        return "book"
    if hold_fixes_the_card(booking, now):
        return ""
    if status == "confirmed" or (
        status in ("completed", "no_show", "cancelled")
        and booking.charge_state in ("failed", "requires_action")
    ):
        return "card"
    return ""


def hold_fixes_the_card(booking: ConsultBooking, now: datetime) -> bool:
    """A confirmed call with an authorized hold: the hold's card is the card
    for this call, and no other card can be saved from the booking page (a
    new card would not get the hold, and the call would still be charged to
    the first). If the hold is lost, released or refused, this is false
    again and the card page opens as before."""
    return effective_status(booking, now) == "confirmed" and booking.hold_state == "authorized"


def card_problem(booking: ConsultBooking, now: datetime) -> bool:
    """The card on file was refused, for the hold or for a charge, and the
    money is still expected: the client should be asked for another card."""
    if booking.charge_state in ("failed", "requires_action"):
        return True
    return (
        effective_status(booking, now) == "confirmed"
        and booking.hold_state in ("failed", "requires_action")
    )


def card_setup_url(db: Session, booking: ConsultBooking, token: str, now: datetime | None = None) -> str:
    """A fresh card page: to finish a pending booking ("continue to card
    entry"), or to replace the card on a confirmed one."""
    now = now or utcnow()
    purpose = card_page_purpose(booking, now)
    if not purpose:
        if effective_status(booking, now) == "expired":
            raise Refused("The hold on this time ran out before a card was saved. Please book again.")
        if hold_fixes_the_card(booking, now):
            _, last4 = money_card(money.ledger(db, booking.id))
            last4 = last4 or booking.card_last4
            raise Refused(
                "A temporary hold for this call is already on your card"
                + (f" ending {last4}" if last4 else "")
                + ". To use a different card, reply to your confirmation email before the call."
            )
        raise Refused("This booking does not need a card any more.")
    return _start_card_setup(db, booking, token, purpose=purpose)


# -----------------------------------------------------------------------------
# Confirmation: the card was saved (Stripe webhook)
# -----------------------------------------------------------------------------

def _overlaps(start: datetime, end: datetime, blocks: list[Block], pad: timedelta) -> bool:
    return any(bs - pad < end and start < be + pad for bs, be in blocks)


def _cannot_confirm(
    db: Session, cs: ConsultSettings, booking: ConsultBooking, now: datetime, *, lapsed: bool,
) -> str:
    """Why this booking can no longer take its slot ('' when it can).

    While its hold stands the booking only has to be clear of what the hold
    does not keep out: an oral examination booked meanwhile. Once the hold
    has run out the whole check runs again, live calendars included
    (CalendarError propagates: Stripe redelivers the webhook later)."""
    start, end = aware(booking.start_at), aware(booking.end_at)
    if start <= now:
        return "the time has passed"
    pad = timedelta(minutes=cs.buffer_minutes or 0)
    if _overlaps(start, end, exam_blocks(db), pad):
        return "an oral examination was booked at that time"
    # The day's cap counts calls with a card on them, so it is decided here,
    # at the moment this one would become one, reservation standing or not.
    cap = cs.max_per_day or 0
    if cap > 0 and _day_counts(db, cs, now, exclude_id=booking.id)[start.astimezone(zone(cs)).date()] >= cap:
        return "the day filled up"
    if not lapsed:
        return ""
    if _overlaps(start, end, consult_blocks(db, now, exclude_id=booking.id), pad):
        return "another booking took the time"
    low, high = start - pad - timedelta(hours=1), end + pad + timedelta(hours=1)
    if _overlaps(start, end, course_blocks(db, low, high), pad):
        return "a course session is at that time"
    if _overlaps(start, end, _google_busy(db, low, high, live=True), pad):
        return "the calendar is no longer free at that time"
    return ""


def _event_text(booking: ConsultBooking) -> tuple[str, str]:
    """Title and description of the calendar event. The client is a guest
    and sees both: no price, no topic, no manage link."""
    summary = f"ProReadyEngineer consulting call: {booking.full_name}"
    description = (
        f"One-to-one consulting call with {get_settings().INSTRUCTOR_NAME}, {booking.minutes} minutes, "
        f"on Google Meet. Booking reference {booking.ref}.\n\n"
        "To cancel, use the link in your confirmation email.\n\n"
        "Please do not share third-party proprietary or export-controlled information."
    )
    return summary, description


# A retry that keeps failing writes its timeline line this often, not on
# every tick.
CALENDAR_FAILURE_NOTE_EVERY = timedelta(hours=6)


def _create_calendar_event(db: Session, booking: ConsultBooking, *, sparse: bool = False) -> bool:
    """Put the call on the calendar with a Meet link and the client invited.
    Fills the booking's event fields; the caller commits. False (and a
    timeline line) when Google refused. `sparse`: a repeated try (the cron
    tick) writes that line only every CALENDAR_FAILURE_NOTE_EVERY."""
    summary, description = _event_text(booking)
    try:
        event = xcal.create_event(
            db, start=aware(booking.start_at), minutes=booking.minutes, summary=summary,
            description=description, guest_email=booking.email, guest_name=booking.full_name,
        )
    except xcal.CalendarError as exc:
        log.error("Calendar event for consult %s failed: %s", booking.ref, exc)
        last = None
        if sparse:
            db.flush()
            last = aware(db.execute(
                select(func.max(ConsultBookingEvent.at)).where(
                    ConsultBookingEvent.booking_id == booking.id,
                    ConsultBookingEvent.kind == "calendar_event_failed",
                )
            ).scalar())
        if last is None or utcnow() - last >= CALENDAR_FAILURE_NOTE_EVERY:
            add_event(db, booking, "calendar_event_failed", note=str(exc)[:500])
        return False
    booking.google_event_id = str(event.get("id") or "")[:256]
    booking.meet_url = str(event.get("meeting_url") or "")[:500]
    booking.calendar_link = str(event.get("html_link") or "")[:1000]
    add_event(db, booking, "calendar_event_created", note=booking.meet_url)
    return True


def ensure_calendar_event(db: Session, booking: ConsultBooking) -> bool:
    """Create the calendar event of a confirmed booking that has none (the
    first try failed). Idempotent; for the cron tick and the admin."""
    with _BOOKING_MUTEX:
        booking = money.lock_booking(db, booking.id)
        if booking is None or booking.status != "confirmed" or booking.google_event_id:
            db.commit()
            return bool(booking and booking.google_event_id)
        ok = _create_calendar_event(db, booking)
        db.commit()
        return ok


def retry_calendar_event(db: Session, booking_id: int) -> str:
    """The cron tick's try at a missing calendar event. Returns 'created'
    (by this call: the owner is told), 'exists', 'failed' or 'closed' (the
    booking is no longer confirmed). Safe to repeat."""
    with _BOOKING_MUTEX:
        booking = money.lock_booking(db, booking_id)
        if booking is None or booking.status != "confirmed":
            db.commit()
            return "closed"
        if booking.google_event_id:
            db.commit()
            return "exists"
        ok = _create_calendar_event(db, booking, sparse=True)
        db.commit()
    if not ok:
        return "failed"
    clear_cache()
    booking = db.get(ConsultBooking, booking_id)
    notify_owner(
        db, booking, template="consult_owner_calendar_fixed",
        headline="The meeting is on your calendar now",
        detail=(
            "The calendar event that could not be created when this call was booked has now been "
            "created. Google has sent the client the invitation with the Meet link. If you had "
            "already made a meeting by hand, remove one of the two."
        ),
        extra_rows=[("Meeting link", booking.meet_url or "not returned by Google")],
    )
    return "created"


def _card_details(setup_intent) -> tuple[str, str, str]:
    """(payment method id, brand, last4) from a SetupIntent with its
    payment method expanded."""
    pm = money._g(setup_intent, "payment_method")
    if isinstance(pm, str):
        return pm, "", ""
    card = money._g(pm, "card")
    return (
        str(money._g(pm, "id", "") or ""),
        str(money._g(card, "brand", "") or "")[:24],
        str(money._g(card, "last4", "") or "")[:4],
    )


def _event_time(value) -> datetime | None:
    """Stripe's `created` on an event (seconds since 1970) as a UTC time."""
    try:
        return datetime.fromtimestamp(int(value), timezone.utc) if value else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _setup_intent_seen(db: Session, booking: ConsultBooking, setup_intent_id: str) -> bool:
    """Has this booking already handled this card page's setup intent? Every
    one it ever handled counts, not only the last: Stripe may deliver an
    earlier page's event again after a later page's event was processed."""
    if booking.stripe_setup_intent_id == setup_intent_id:
        return True
    earlier = db.execute(
        select(ConsultBookingEvent.data).where(
            ConsultBookingEvent.booking_id == booking.id,
            ConsultBookingEvent.kind.in_(("card_saved", "card_replaced", "slot_lost", "card_saved_ignored")),
        )
    ).scalars().all()
    return any((d or {}).get("setup_intent") == setup_intent_id for d in earlier)


def on_checkout_completed(
    db: Session, session_obj: dict, now: datetime | None = None, *,
    event_created=None, defer_confirmation: bool = False,
) -> str:
    """checkout.session.completed for a consulting card page (the webhook
    has verified Stripe's signature). Saves the card and confirms the
    booking; for a booking that is already confirmed, replaces its card.

    Safe to deliver any number of times and in any order: a card page that
    was already handled changes nothing and sends nothing ('replay'), and an
    event Stripe created before the one the booking's card came from is
    never applied over it ('stale'; `event_created` is the event's own
    `created`). Returns what happened, for the log: 'confirmed' | 'replay' |
    'stale' | 'card_replaced' | 'slot_lost' | 'ignored'.

    `defer_confirmation`: the caller sends the confirmation emails and
    places a due hold itself, after answering Stripe (finish_confirmation;
    the tick does the same should that never run).

    A failure to read the saved card from Stripe, or to read the calendars
    for a booking whose hold has lapsed, raises: the webhook answers 5xx and
    Stripe delivers the event again."""
    metadata = session_obj.get("metadata") or {}
    try:
        booking_id = int(metadata.get("booking_id") or 0)
    except (TypeError, ValueError):
        booking_id = 0
    setup_intent_id = str(session_obj.get("setup_intent") or "")
    if not booking_id or not setup_intent_id or session_obj.get("mode") not in (None, "setup"):
        log.error("Consult checkout %s is not a card setup we can use", session_obj.get("id"))
        return "ignored"
    stripe = money._stripe()
    setup_intent = stripe.SetupIntent.retrieve(setup_intent_id, expand=["payment_method"])
    if str(money._g(setup_intent, "status", "")) != "succeeded":
        log.warning("Consult checkout %s: setup intent is not succeeded", session_obj.get("id"))
        return "ignored"
    pm_id, brand, last4 = _card_details(setup_intent)
    if not pm_id:
        log.error("Consult checkout %s: no payment method on the setup intent", session_obj.get("id"))
        return "ignored"
    customer = str(session_obj.get("customer") or money._g(setup_intent, "customer", "") or "")
    now = now or utcnow()
    cs = settings_row(db)

    outcome = "ignored"
    with _BOOKING_MUTEX:
        xcal.lock(db)
        booking = money.lock_booking(db, booking_id)
        if booking is None:
            db.rollback()
            log.error("Consult checkout %s names an unknown booking %s", session_obj.get("id"), booking_id)
            return "ignored"
        if booking.stripe_customer_id and customer and customer != booking.stripe_customer_id:
            db.rollback()
            log.error("Consult checkout %s: customer does not match booking %s", session_obj.get("id"), booking.ref)
            return "ignored"
        if _setup_intent_seen(db, booking, setup_intent_id):
            db.rollback()
            return "replay"
        created = _event_time(event_created)
        seen = {"setup_intent": setup_intent_id}
        if created is not None and aware(booking.card_event_at) is not None and created < aware(booking.card_event_at):
            # An earlier card page, finished before the one the card on the
            # booking came from, whose event arrives only now: the newer
            # card stays. Remembered, so a redelivery is a replay.
            add_event(db, booking, "card_saved_ignored", actor="stripe", at=now, data=seen, note=(
                "A card page finished earlier was reported by Stripe after a newer card had been saved. "
                "The newer card is kept."))
            db.commit()
            return "stale"

        def save_card() -> None:
            booking.stripe_customer_id = customer or booking.stripe_customer_id
            booking.stripe_setup_intent_id = setup_intent_id
            booking.stripe_payment_method_id = pm_id
            booking.card_brand, booking.card_last4 = brand, last4
            booking.card_saved_at = now
            booking.card_event_at = created or now

        lapsed = booking.status == "expired" or (
            booking.status == "pending_card" and aware(booking.hold_expires_at) <= now
        )
        if booking.status == "pending_card" or lapsed:
            try:
                why_not = _cannot_confirm(db, cs, booking, now, lapsed=lapsed)
            except xcal.CalendarError:
                db.rollback()
                raise
            if why_not:
                booking.status = "expired"
                # Remembered so a redelivery is recognised; the card is not kept.
                booking.stripe_setup_intent_id = setup_intent_id
                add_event(db, booking, "slot_lost", actor="stripe", at=now, data=seen, note=(
                    f"The card was saved after the hold on the time had run out, and {why_not}. "
                    if lapsed else f"Before the card was saved, {why_not}. "
                ) + "Nothing was charged.")
                db.commit()
                outcome = "slot_lost"
            else:
                save_card()
                start, end = aware(booking.start_at), aware(booking.end_at)
                booking.status = "confirmed"
                booking.confirmed_at = now
                booking.hold_expires_at = None
                booking.free_cancel_until = free_cancel_deadline(
                    start, booking.free_cancel_hours, booking.grace_minutes, now)
                booking.hold_due_at = max(start - timedelta(hours=booking.hold_lead_hours), now)
                booking.settle_due_at = end + timedelta(hours=booking.auto_settle_hours)
                card = f"{brand} ending {last4}".strip() if last4 else "card"
                add_event(db, booking, "card_saved", actor="stripe", at=now, note=card, data=seen)
                add_event(db, booking, "confirmed", actor="stripe", at=now,
                          note="Revived: the hold had run out but the time was still free." if lapsed else "")
                _create_calendar_event(db, booking)
                event_id = booking.google_event_id
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    if event_id:
                        try:
                            xcal.delete_event(db, event_id)
                        except xcal.CalendarError:
                            log.error("Consult %s failed to save after event %s was created", booking_id, event_id)
                    raise
                outcome = "confirmed"
        elif booking.status == "confirmed" or (
            booking.status in ("completed", "no_show", "cancelled")
            and booking.charge_state in ("failed", "requires_action")
        ):
            held_on = ""
            if booking.status == "confirmed" and booking.hold_state == "authorized":
                # The card page was open before the hold was placed. The new
                # card is kept on the booking; the hold is not moved, and no
                # second hold is placed.
                held_on = _card_words(*money_card(money.ledger(db, booking.id))) or _card_text(booking) or "the first card"
            save_card()
            card = f"{brand} ending {last4}".strip() if last4 else ""
            add_event(db, booking, "card_replaced", actor="stripe", at=now, data=seen, note=(
                f"{card}. The hold of {usd(booking.hold_cents)} stays on the previous card ({held_on}): "
                "a call that takes place is charged to that card, not to the new one."
                if held_on else card))
            db.commit()
            outcome = "card_replaced"
        else:
            booking.stripe_setup_intent_id = setup_intent_id
            add_event(db, booking, "card_saved_ignored", actor="stripe", at=now, data=seen,
                      note=f"A card was saved for a booking that is {booking.status}; it is not used.")
            db.commit()
            outcome = "ignored"

    booking = db.get(ConsultBooking, booking_id)
    if outcome == "confirmed":
        clear_cache()
        if not defer_confirmation:
            finish_confirmation(db, booking_id)
    elif outcome == "slot_lost":
        # Told plainly, now; and by the tick if the email does not go out.
        send_slot_lost_notice(db, booking_id)
    elif outcome == "card_replaced":
        after_card_replaced(db, booking)
    return outcome


def finish_confirmation(db: Session, booking_id: int) -> None:
    """What follows a confirmation: the two emails, and the hold when the
    call starts inside the hold lead time (the confirmation says so). Each
    part happens at most once however often this runs, and the tick does
    whatever of it is still missing, so the Stripe webhook can answer first
    and run this afterwards."""
    try:
        send_confirmation(db, booking_id)
    except Exception:  # noqa: BLE001 — the tick sends what is missing
        log.exception("Confirmation emails for consult booking %s failed; the tick will retry", booking_id)
        db.rollback()
    _hold_after_card(db, booking_id, replaced=False)


def finish_confirmation_later(booking_id: int) -> None:
    """finish_confirmation on a session of its own: run as a background
    task, after the webhook's answer has gone to Stripe."""
    from .db import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        finish_confirmation(db, booking_id)
    finally:
        db.close()


def _hold_after_card(db: Session, booking_id: int, *, replaced: bool) -> None:
    """Place the hold that is due on a card that was just saved. Whatever
    goes wrong here is logged and left to the cron tick: the webhook that
    saved the card must still answer Stripe 200. The tick places a first
    hold that is due (place_due_hold), and tries a refused hold, or a
    refused amount, on a card saved after the refusal
    (consult_auto.retry_on_new_card): that second step also covers a webhook
    that stopped between saving the card and this follow-up."""
    try:
        from . import consult_auto  # noqa: PLC0415 — consult_auto imports this module

        consult_auto.hold_after_card(db, booking_id, replaced=replaced)
    except Exception:  # noqa: BLE001
        log.exception("Hold after card setup failed for consult booking %s; the tick will retry", booking_id)
        db.rollback()


def after_card_replaced(db: Session, booking: ConsultBooking) -> PayResult | None:
    """A new card is on the booking. If a decided amount could not be taken
    from the old card, it is taken now. If the pre-meeting hold was refused
    on the old card, it is tried on the new one."""
    if booking.settlement and booking.charge_state in ("failed", "requires_action"):
        result = money.collect(db, booking, actor="system")
        booking = db.get(ConsultBooking, booking.id)
        db.refresh(booking)
        if result.fresh:
            notify_owner_payment(db, booking, result, what="Retried on the new card")
        return result
    if booking.status == "confirmed" and not booking.settlement:
        _hold_after_card(db, booking.id, replaced=True)
    return None


# -----------------------------------------------------------------------------
# Cancelling
# -----------------------------------------------------------------------------

def _remove_calendar_event(db: Session, booking: ConsultBooking) -> None:
    """Delete the event (Google tells the guest). Best effort, recorded."""
    booking = money.lock_booking(db, booking.id)
    if booking is None or not booking.google_event_id:
        db.commit()
        return
    event_id = booking.google_event_id
    try:
        xcal.delete_event(db, event_id)
    except xcal.CalendarError as exc:
        log.error("Could not remove calendar event %s of consult %s: %s", event_id, booking.ref, exc)
        add_event(db, booking, "calendar_event_remove_failed", note=str(exc)[:500])
        db.commit()
        return
    booking.google_event_id = ""
    add_event(db, booking, "calendar_event_removed")
    db.commit()
    clear_cache()


def cancel_fee_now(booking: ConsultBooking, now: datetime) -> int:
    """What cancelling at `now` costs the client."""
    if booking.status != "confirmed":
        return 0
    limit = aware(booking.free_cancel_until)
    return 0 if (limit is not None and now <= limit) else int(booking.fee_cents or 0)


def _stalled(booking: ConsultBooking, now: datetime) -> bool:
    """A cancelled booking whose follow-up never finished (the request that
    cancelled it died after recording the decision)."""
    return (
        booking.cancel_notice_sent_at is None
        and booking.cancelled_at is not None
        and booking.confirmed_at is not None
        and now - aware(booking.cancelled_at) > CANCEL_RESUME_AFTER
    )


def finish_cancellation(db: Session, booking_id: int, *, actor: str = "") -> ConsultBooking:
    """Everything that follows the decision to cancel a confirmed booking:
    the late fee if one is due (otherwise any hold is released), the
    calendar event, and the emails. Every part is safe to repeat, and the
    emails go out once: the request that claims cancel_notice_sent_at sends
    them. Also the way a cancellation that was cut short is completed (a
    repeated request after CANCEL_RESUME_AFTER, or W1b's tick)."""
    booking = db.get(ConsultBooking, booking_id)
    by_client = booking.cancelled_by == "client"
    by_system = booking.cancelled_by == "system"
    result = money.collect(db, booking, actor=actor or ("client" if by_client else "system"))
    _remove_calendar_event(db, booking)
    claimed = db.execute(
        update(ConsultBooking)
        .where(ConsultBooking.id == booking_id, ConsultBooking.cancel_notice_sent_at.is_(None))
        .values(cancel_notice_sent_at=utcnow())
    ).rowcount == 1
    db.commit()
    booking = db.get(ConsultBooking, booking_id)
    db.refresh(booking)
    if claimed:
        kind = "client" if by_client else ("hold_failed" if by_system else "owner")
        _send_cancellation(db, booking, kind=kind, result=result)
        if by_client:
            _notify_owner_cancelled(db, booking, result)
        elif by_system:
            notify_owner(
                db, booking, template="consult_owner_hold_cancelled",
                headline="Cancelled automatically: no hold could be placed",
                detail=(
                    "The hold on the client's card was refused and no working card was provided in "
                    "time, so the call was cancelled and the time is open again. The client has been "
                    "told. Nothing was charged."
                ),
                extra_rows=[("What the bank said", booking.hold_error or "no reason given")],
            )
    return booking


def cancel_by_client(db: Session, booking: ConsultBooking, now: datetime | None = None) -> ConsultBooking:
    """The client cancels from their manage page. Free until the booking's
    free-cancellation moment; after it the fee is collected (from the hold
    when there is one). Asking again changes nothing and charges nothing."""
    now = now or utcnow()
    booking_id = booking.id
    with _STATE_MUTEX:
        booking = money.lock_booking(db, booking_id)
        if booking.status == "cancelled":
            proceed = _stalled(booking, now)
            db.commit()
        elif booking.status == "pending_card":
            lapsed = aware(booking.hold_expires_at) <= now
            booking.status = "expired" if lapsed else "cancelled"
            if not lapsed:
                booking.cancelled_at, booking.cancelled_by = now, "client"
            add_event(db, booking, "expired" if lapsed else "cancelled", actor="client", at=now,
                      note="Cancelled before a card was saved." if not lapsed else "")
            db.commit()
            proceed = False  # no card, no calendar event, no confirmation was ever sent
        elif booking.status != "confirmed":
            db.commit()
            raise Refused("This booking can no longer be cancelled.")
        elif now >= aware(booking.start_at):
            db.commit()
            raise Refused("This call has already started, so it can no longer be cancelled here.")
        else:
            fee = cancel_fee_now(booking, now)
            booking.status = "cancelled"
            booking.cancelled_at, booking.cancelled_by, booking.cancel_fee_cents = now, "client", fee
            if fee > 0:
                booking.settlement, booking.settled_at, booking.settled_by = "late_cancel", now, "client"
                booking.amount_due_cents, booking.charge_state = fee, "pending"
            add_event(db, booking, "cancelled", actor="client", at=now, amount_cents=fee,
                      note=f"Late cancellation: the {booking.fee_percent}% fee applies." if fee else "Free cancellation.")
            db.commit()  # the slot is free from here, whatever happens next
            proceed = True
    if not proceed:
        return db.get(ConsultBooking, booking_id)
    return finish_cancellation(db, booking_id)


def cancel_by_owner(
    db: Session, booking: ConsultBooking, *, actor: str, note: str = "", now: datetime | None = None,
    by: str = "owner",
) -> ConsultBooking:
    """The owner calls the booking off. Never a charge. `by="system"` is the
    automatic cancellation when no hold could be placed on the card: the
    same steps, with its own words to the client and a notice to the owner."""
    now = now or utcnow()
    by = "system" if by == "system" else "owner"
    booking_id = booking.id
    tell_unconfirmed = False
    with _STATE_MUTEX:
        booking = money.lock_booking(db, booking_id)
        if booking.status == "cancelled":
            proceed = _stalled(booking, now)
            db.commit()
        else:
            status = effective_status(booking, now)
            if status not in ("pending_card", "confirmed"):
                db.commit()
                raise Refused(
                    f"This booking is {status.replace('_', ' ')} and cannot be cancelled. To return money, use a refund."
                )
            proceed = booking.status == "confirmed"
            # Never confirmed: nothing to collect or to remove from the
            # calendar. The client may still be on the card page, so they
            # are told; the notice is claimed here, with the decision.
            tell_unconfirmed = not proceed
            booking.status = "cancelled"
            booking.cancelled_at, booking.cancelled_by = now, by
            booking.cancel_note, booking.cancel_fee_cents = (note or "").strip()[:2000], 0
            if tell_unconfirmed:
                booking.cancel_notice_sent_at = now
            add_event(db, booking, "cancelled", actor=actor, at=now,
                      note=(note or "").strip()[:2000] or "Cancelled by the owner at no charge.")
            db.commit()
    if tell_unconfirmed:
        booking = db.get(ConsultBooking, booking_id)
        _send_cancellation(db, booking, kind="owner")
    if not proceed:
        return db.get(ConsultBooking, booking_id)
    return finish_cancellation(db, booking_id, actor=actor)


# -----------------------------------------------------------------------------
# Deciding the outcome (the admin's buttons; W1b's automatic settlement)
# -----------------------------------------------------------------------------

OUTCOMES = {"charge": "charged", "no_show": "no_show", "waive": "waived"}
# What a decided outcome is called in the owner's emails.
OUTCOME_LABELS = {
    "charged": "Charge for the call", "no_show": "No-show fee",
    "waived": "Not charged", "late_cancel": "Late-cancellation fee",
}


class AlreadyDecided(Refused):
    """An automatic step found the outcome decided by someone else first."""


def _decide_outcome(
    db: Session, booking_id: int, outcome: str, *, actor: str, minutes: int | None, now: datetime,
    only_undecided: bool = False, expect_choice: str | None = None, reason: str = "",
) -> tuple[str, bool]:
    """Write the decision on the booking (under its lock) and commit.
    Returns (the settlement recorded, whether it was already exactly that).
    Refused when the booking's state does not allow the decision.

    The automatic paths pass two guards, checked under the same lock that
    writes the decision. `only_undecided`: act only on a booking nobody has
    decided yet (never change a person's decision). `expect_choice`: the
    owner's choice from his email must still be this ('' for the default
    outcome, which must not run once he has chosen)."""
    booking = money.lock_booking(db, booking_id)
    money.recompute(db, booking)
    target = OUTCOMES[outcome]
    late_fee = booking.status == "cancelled" and booking.settlement == "late_cancel"
    if only_undecided and (booking.settlement or booking.status != "confirmed"):
        db.commit()
        raise AlreadyDecided("This booking has already been decided.")
    if expect_choice is not None and (booking.owner_choice or "") != expect_choice:
        db.commit()
        raise AlreadyDecided("The owner has made a choice for this booking.")

    if late_fee:
        if outcome == "no_show":
            db.commit()
            raise Refused("This booking was cancelled late. Charge the fee again, or waive it.")
        if outcome == "waive":
            if booking.charged_cents > 0:
                db.commit()
                raise Refused(f"The fee of {usd(booking.charged_cents)} was already charged. Use a refund to return it.")
            target, amount, billed = "waived", 0, 0
        else:
            target, amount, billed = "late_cancel", booking.amount_due_cents, 0
    else:
        if booking.status not in ("confirmed", "completed", "no_show"):
            status = effective_status(booking, now).replace("_", " ")
            db.commit()
            raise Refused(f"This booking is {status}: there is no meeting to settle.")
        if booking.status == "confirmed" and now < aware(booking.start_at):
            db.commit()
            raise Refused("This call has not started yet. To call it off, cancel it.")
        if outcome == "charge":
            billed = booking.minutes if minutes is None else int(minutes)
            if billed <= 0 or billed % 30 or billed > booking.minutes:
                db.commit()
                raise Refused(
                    f"Minutes to charge must be a multiple of 30, from 30 up to the {booking.minutes} booked."
                )
            amount = amount_for(booking.rate_cents_per_hour, billed)
        elif outcome == "no_show":
            amount, billed = int(booking.fee_cents or 0), 0
        else:
            amount, billed = 0, 0

    same = booking.settlement == target and booking.amount_due_cents == amount
    if not same:
        # A hold whose answer was lost for good ('needs_review') authorized
        # at most; it never took money and can no longer be captured, so it
        # does not stand in the way of deciding. Every other unanswered row
        # (a charge, a capture, a hold still being asked about) does.
        blocking = [
            r for r in money.unsettled_rows(db, booking.id)
            if not (r.kind == "hold" and r.status == "needs_review")
        ]
        if blocking:
            db.commit()
            raise Refused("A payment for this booking is still being confirmed. Try again in a minute.")
        if booking.settlement and booking.charged_cents > 0:
            db.commit()
            raise Refused(
                f"This booking was already charged {usd(booking.charged_cents)}. "
                "Use a refund to return money."
            )
        first = not booking.settlement
        booking.settlement, booking.amount_due_cents, booking.billed_minutes = target, amount, billed
        booking.settled_at, booking.settled_by = now, actor[:320]
        if not late_fee:
            booking.status = "no_show" if target == "no_show" else "completed"
        booking.charge_state, booking.charge_error = ("pending" if amount > 0 else ""), ""
        add_event(
            db, booking, "outcome_decided" if first else "outcome_changed", actor=actor, at=now,
            amount_cents=amount,
            note=" ".join(part for part in ({
                "charged": f"Charge for {billed} minutes.",
                "no_show": f"No-show: the {booking.fee_percent}% fee.",
                "waived": "Do not charge.",
                "late_cancel": "Late-cancellation fee.",
            }[target], (reason or "").strip()[:500]) if part),
        )
    db.commit()
    return target, same


def settle(
    db: Session, booking: ConsultBooking, outcome: str, *, actor: str,
    minutes: int | None = None, now: datetime | None = None,
    only_undecided: bool = False, expect_choice: str | None = None,
    reason: str = "", label: str = "",
) -> tuple[ConsultBooking, PayResult]:
    """Decide what the meeting costs and collect it.

      charge    the booked amount, or `minutes` of it (never more than booked)
      no_show   the fee; the rest of any hold is released
      waive     nothing; any hold is released

    Deciding the same thing twice collects once. A decision can be changed
    only while no money has been taken for it; after that, money goes back
    through a refund. A cancelled booking whose late fee could not be taken
    accepts 'charge' (try again) and 'waive' (let the fee go).

    For the automatic outcome and the owner's email links: `only_undecided`
    and `expect_choice` (see _decide_outcome; AlreadyDecided when a person
    got there first), `reason` (why, for the timeline and the owner's
    email) and `label` (what the owner's email calls it)."""
    if outcome not in OUTCOMES:
        raise Refused("Unknown outcome.")
    now = now or utcnow()
    booking_id = booking.id
    with _STATE_MUTEX:
        target, same = _decide_outcome(
            db, booking_id, outcome, actor=actor, minutes=minutes, now=now,
            only_undecided=only_undecided, expect_choice=expect_choice, reason=reason,
        )
    booking = db.get(ConsultBooking, booking_id)

    result = money.collect(db, booking, actor=actor)
    booking = db.get(ConsultBooking, booking_id)
    db.refresh(booking)
    # The owner hears of money taken from the one request that took it
    # (`fresh`), and of a decision that owes nothing from the request that
    # made it. A request that decided, and then found the amount already
    # collected by another request a moment earlier, has nothing to tell:
    # "nothing to charge" would be untrue.
    nothing_owed = (booking.amount_due_cents or 0) <= 0
    if result.fresh or (not same and result.status == "noop" and nothing_owed):
        notify_owner_payment(db, booking, result, what=label or OUTCOME_LABELS[target], reason=reason)
    return booking, result


def resolve_review(
    db: Session, booking: ConsultBooking, outcome: str, *, actor: str,
    cents: int | None = None, charge_id: int | None = None,
) -> tuple[ConsultBooking, PayResult]:
    """The owner closes a payment attempt that was parked for him to check
    in Stripe. outcome 'settled' (it was paid; `cents` is what Stripe shows)
    or 'not_charged' (nothing was taken; Charge may be tried again). Stripe
    is asked to confirm first, and a statement that does not fit what it
    shows is Refused; Unavailable when Stripe cannot be asked. No money is
    moved. A payment confirmed as paid gets the client their receipt."""
    booking_id = booking.id
    result = money.resolve_review(db, booking, outcome, actor=actor, cents=cents, charge_id=charge_id)
    if result.status == "refused":
        raise Refused(result.message)
    if result.status == "error":
        raise Unavailable(result.message)
    booking = db.get(ConsultBooking, booking_id)
    db.refresh(booking)
    if outcome == "settled" and result.fresh:
        try:
            _send_client_receipt(db, booking, result, charged_at=result.at)
        except Exception:  # noqa: BLE001 — the ledger is right; the email is secondary
            log.exception("Receipt email for consult %s failed", booking.ref)
            db.rollback()
    return booking, result


def refund(
    db: Session, booking: ConsultBooking, cents: int, *, actor: str, note: str = "",
) -> tuple[ConsultBooking, PayResult]:
    booking_id = booking.id
    result = money.refund(db, booking, cents, actor=actor, note=note)
    if result.code in ("invalid_amount", "refund_unresolved"):
        raise Refused(result.message)
    booking = db.get(ConsultBooking, booking_id)
    db.refresh(booking)
    if result.fresh:
        notify_owner_payment(db, booking, result, what="Refund")
    return booking, result


# -----------------------------------------------------------------------------
# Views
# -----------------------------------------------------------------------------

def effective_status(booking: ConsultBooking, now: datetime) -> str:
    """The status as it stands at `now`: a pending booking whose hold has
    run out is expired even before the sweep has recorded it."""
    if booking.status == "pending_card" and aware(booking.hold_expires_at) is not None \
            and aware(booking.hold_expires_at) <= now:
        return "expired"
    return booking.status


def public_view(booking: ConsultBooking, now: datetime | None = None) -> dict:
    """What the client's manage page shows. Their own booking, so the
    amounts are here; nothing about other bookings or the owner's notes."""
    now = now or utcnow()
    status = effective_status(booking, now)
    start = aware(booking.start_at)
    # free_cancel_until is the deadline while a free cancellation is still
    # open, and null once there is none (it has passed, or the booking is
    # closed).
    free_until: datetime | None = None
    if status == "confirmed":
        can_cancel = now < start
        cancel_fee = cancel_fee_now(booking, now) if can_cancel else 0
        if can_cancel and cancel_fee == 0:
            free_until = aware(booking.free_cancel_until)
    elif status == "pending_card":
        can_cancel, cancel_fee = True, 0
        # No card yet, so cancelling costs nothing; this is the earliest the
        # deadline can be once the card is saved.
        free_until = free_cancel_deadline(start, booking.free_cancel_hours, booking.grace_minutes, now)
    else:
        can_cancel, cancel_fee = False, 0
    kept = kept_cents(booking)
    session = object_session(booking)
    held_brand, held_last4 = money_card(money.ledger(session, booking.id)) if session is not None else ("", "")
    return {
        "ref": booking.ref,
        "status": status,
        "start": _iso(start),
        "minutes": booking.minutes,
        "timezone": booking.timezone,
        "tier_label": TIER_LABELS.get(booking.tier, booking.tier),
        "total_cents": booking.total_cents,
        "fee_cents": booking.fee_cents,
        "free_cancel_until": _iso(free_until),
        "meet_url": (booking.meet_url or None) if status == "confirmed" else None,
        "can_cancel": can_cancel,
        "cancel_fee_cents": cancel_fee,
        # What was taken and kept (after refunds and after any dispute the
        # bank decided for the cardholder); null until a charge exists.
        "charged_cents": kept if (booking.charged_cents or 0) > 0 else None,
        # The card the hold is on, or the money was taken from, when there is
        # one; otherwise the saved card.
        "card_brand": (held_brand if held_last4 else booking.card_brand) or None,
        "card_last4": (held_last4 or booking.card_last4) or None,
        # POST /booking/{ref}/card will be accepted now: to continue to card
        # entry (pending_card) or to replace the card.
        "can_replace_card": bool(card_page_purpose(booking, now)),
        # The card on file was refused (hold or charge): ask for another one.
        "card_problem": card_problem(booking, now),
    }


def kept_cents(booking: ConsultBooking) -> int:
    """What the booking has actually kept: charged, less refunds, less what
    a lost dispute sent back to the cardholder."""
    return max(
        (booking.charged_cents or 0) - (booking.refunded_cents or 0) - (booking.dispute_lost_cents or 0), 0)


def payment_state(booking: ConsultBooking) -> str:
    """One word for where the money stands, for the admin list."""
    charged, refunded = booking.charged_cents or 0, booking.refunded_cents or 0
    if charged > 0 and refunded >= charged:
        return "refunded"
    if refunded > 0:
        return "partly_refunded"
    if booking.charge_state == "paid":
        return "paid"
    if booking.charge_state in ("failed", "requires_action", "review", "open"):
        # 'review' (an attempt is parked for the owner) and 'open' (owed,
        # nothing in flight) are unpaid too; the admin's word is the same.
        return "payment_failed"
    if booking.charge_state == "pending":
        return "payment_pending"
    if booking.settlement == "waived":
        return "not_charged"
    if booking.hold_state == "authorized":
        return "hold_placed"
    if booking.hold_state in ("failed", "requires_action"):
        return "hold_failed"
    if booking.stripe_payment_method_id:
        return "card_saved"
    return "no_card"


def attendance_out(booking: ConsultBooking) -> dict:
    """Attendance as the admin screen reads it. Until the Meet API has been
    asked (W1b), and whenever it cannot say, the state is 'unknown'.

    W1b stores booking.attendance as {host_joined, others_joined,
    participants, note} and sets attendance_state / attendance_checked_at."""
    data = booking.attendance or {}
    return {
        "state": booking.attendance_state or "unknown",
        "host_joined": data.get("host_joined"),
        "others_joined": data.get("others_joined"),
        "participants": [str(p) for p in (data.get("participants") or [])],
        "checked_at": _iso(booking.attendance_checked_at),
        "note": str(data.get("note") or ""),
    }


def _actions(booking: ConsultBooking, status: str, now: datetime) -> dict:
    started = now >= aware(booking.start_at)
    open_meeting = status == "confirmed" and started
    unpaid = booking.charge_state in ("failed", "requires_action", "pending", "review", "open")
    late_fee_unpaid = status == "cancelled" and booking.settlement == "late_cancel" and unpaid
    nothing_taken = (booking.charged_cents or 0) == 0
    decided = status in ("completed", "no_show")
    return {
        "can_charge": open_meeting or late_fee_unpaid or (decided and nothing_taken),
        "can_no_show": open_meeting or (decided and nothing_taken),
        "can_waive": open_meeting or (late_fee_unpaid and nothing_taken) or (decided and nothing_taken),
        "can_cancel": status in ("pending_card", "confirmed"),
        "can_refund": money.refundable_cents(booking) > 0,
        "refundable_cents": money.refundable_cents(booking),
    }


def admin_view(
    booking: ConsultBooking, events: list[ConsultBookingEvent], charges: list[ConsultCharge],
    cs: ConsultSettings, now: datetime | None = None,
) -> dict:
    now = now or utcnow()
    status = effective_status(booking, now)
    return {
        "id": booking.id,
        "ref": booking.ref,
        "status": status,
        "created_at": _iso(booking.created_at),
        "confirmed_at": _iso(booking.confirmed_at),
        "start": _iso(booking.start_at),
        "end": _iso(booking.end_at),
        "minutes": booking.minutes,
        "business_timezone": cs.timezone,
        "timezone": booking.timezone,
        "full_name": booking.full_name,
        "email": booking.email,
        "company": booking.company,
        "phone": booking.phone,
        "topic": booking.topic,
        "tier": booking.tier,
        "tier_label": TIER_LABELS.get(booking.tier, booking.tier),
        "rate_cents_per_hour": booking.rate_cents_per_hour,
        "total_cents": booking.total_cents,
        "fee_percent": booking.fee_percent,
        "fee_cents": booking.fee_cents,
        "free_cancel_until": _iso(booking.free_cancel_until),
        "hold_at": _iso(booking.hold_due_at),
        "settle_due_at": _iso(booking.settle_due_at),
        "hold_expires_at": _iso(booking.hold_expires_at),
        "meet_url": booking.meet_url or None,
        "calendar_link": booking.calendar_link or None,
        "calendar_event": bool(booking.google_event_id),
        "card_brand": booking.card_brand or None,
        "card_last4": booking.card_last4 or None,
        # The card the hold is on, or the money was taken from (it can differ
        # from the saved card above); null while no money is held or taken.
        "money_card_brand": money_card(charges)[0] or None,
        "money_card_last4": money_card(charges)[1] or None,
        "payment_state": payment_state(booking),
        "hold_state": booking.hold_state,
        "hold_cents": booking.hold_cents,
        "hold_error": booking.hold_error,
        "settlement": booking.settlement,
        "settled_at": _iso(booking.settled_at),
        "settled_by": booking.settled_by,
        "billed_minutes": booking.billed_minutes,
        "amount_due_cents": booking.amount_due_cents,
        "charge_state": booking.charge_state,
        "charge_error": booking.charge_error,
        # null until money has actually been taken (gross; refunds are below)
        "charged_cents": booking.charged_cents if (booking.charged_cents or 0) > 0 else None,
        "refunded_cents": booking.refunded_cents or 0,
        # Disputes at the client's bank (recorded from Stripe; no money is
        # moved here): what is open or was lost, the lost part, and where
        # it stands ('' | open | won | lost | closed).
        "disputed_cents": booking.disputed_cents or 0,
        "dispute_lost_cents": booking.dispute_lost_cents or 0,
        "dispute_state": booking.dispute_state or "",
        # charged, less refunds, less a lost dispute
        "kept_cents": kept_cents(booking),
        # Payment attempts with no answer from Stripe that it is too late to
        # ask about again: the owner settles each with one of the two review
        # actions (see resolve_review).
        "needs_review": [
            {
                "charge_id": c.id, "kind": c.kind, "reason": c.reason,
                "amount_cents": c.amount_cents, "created_at": _iso(c.created_at),
            }
            for c in charges if c.status == "needs_review" and c.kind in ("charge", "hold")
        ],
        "attendance": attendance_out(booking),
        "cancelled_at": _iso(booking.cancelled_at),
        "cancelled_by": booking.cancelled_by,
        "cancel_note": booking.cancel_note,
        "cancel_fee_cents": booking.cancel_fee_cents,
        "consent": {
            "terms_version": booking.terms_version,
            "terms_hash": booking.terms_hash,
            "terms": list(booking.terms_text or []),
            "at": _iso(booking.consent_at),
            "ip": booking.consent_ip,
            "user_agent": booking.consent_user_agent,
        },
        # The timeline, oldest first.
        "events": [
            {
                "at": _iso(e.at), "kind": e.kind, "detail": e.note, "actor": e.actor,
                "cents": e.amount_cents,
            }
            for e in events
        ],
        "charges": [
            {
                "id": c.id, "kind": c.kind, "reason": c.reason, "attempt": c.attempt,
                "status": c.status, "amount_cents": c.amount_cents,
                "captured_cents": c.captured_cents, "error_code": c.error_code,
                "decline_code": c.decline_code, "error_message": c.error_message,
                "card_brand": c.card_brand or None, "card_last4": c.card_last4 or None,
                "stripe_payment_intent_id": c.stripe_payment_intent_id or None,
                "stripe_refund_id": c.stripe_refund_id or None,
                "actor": c.actor, "note": c.note, "created_at": _iso(c.created_at),
            }
            for c in charges
        ],
        "actions": {
            **_actions(booking, status, now),
            "can_review": any(c.status == "needs_review" and c.kind in ("charge", "hold") for c in charges),
        },
    }


def admin_bookings(
    db: Session, *, status: str = "", q: str = "", booking_id: int | None = None,
    now: datetime | None = None, limit: int = 500,
) -> list[dict]:
    now = now or utcnow()
    expire_stale(db, now)
    cs = settings_row(db)
    query = select(ConsultBooking)
    if booking_id is not None:
        query = query.where(ConsultBooking.id == booking_id)
    status = (status or "").strip().lower()
    if status == "expired":
        query = query.where(ConsultBooking.status == "expired")
    elif status in STATUSES:
        query = query.where(ConsultBooking.status == status)
    term = (q or "").strip().lower()
    if term:
        like = f"%{term}%"
        query = query.where(or_(
            func.lower(ConsultBooking.full_name).like(like),
            func.lower(ConsultBooking.email).like(like),
            func.lower(ConsultBooking.company).like(like),
            func.lower(ConsultBooking.ref).like(like),
            func.lower(ConsultBooking.topic).like(like),
        ))
    rows = db.execute(query.order_by(ConsultBooking.start_at.desc(), ConsultBooking.id.desc()).limit(limit)).scalars().all()
    if not rows:
        return []
    ids = [b.id for b in rows]
    events: dict[int, list[ConsultBookingEvent]] = {i: [] for i in ids}
    for e in db.execute(
        select(ConsultBookingEvent).where(ConsultBookingEvent.booking_id.in_(ids))
        .order_by(ConsultBookingEvent.at, ConsultBookingEvent.id)
    ).scalars().all():
        events[e.booking_id].append(e)
    charges: dict[int, list[ConsultCharge]] = {i: [] for i in ids}
    for c in db.execute(
        select(ConsultCharge).where(ConsultCharge.booking_id.in_(ids)).order_by(ConsultCharge.id)
    ).scalars().all():
        charges[c.booking_id].append(c)
    return [admin_view(b, events[b.id], charges[b.id], cs, now) for b in rows]


def system_status(db: Session, now: datetime | None = None) -> dict:
    """The admin's status strip: can a client book right now, and what is
    missing if not."""
    now = now or utcnow()
    cs = settings_row(db)
    s = get_settings()
    cal = db.get(ExamCalendar, 1)
    calendar_ok, calendar_error, next_available = False, "", None
    try:
        slots = open_slots(db, cs, now, live=True)
        calendar_ok = True
        if slots:
            first = min(slots)
            next_available = {"start": _iso(first), "tier": tier_for(cs, first, now)}
    except xcal.CalendarError as exc:
        db.rollback()
        calendar_error = str(exc)
    return {
        "calendar_ok": calendar_ok,
        "calendar_error": calendar_error,
        "calendar_account": (cal.account_email if cal else "") or "",
        # Attendance is read from the Google Meet API once this scope has
        # been granted; until then it is 'unknown'.
        "meet_scope_ok": xcal.has_scope(cal, MEET_SCOPE),
        "stripe_ok": bool(s.STRIPE_SECRET_KEY and s.STRIPE_WEBHOOK_SECRET),
        # On = switched on AND every rate is set. Nothing can be booked
        # without prices, whatever the switch says.
        "enabled": bookable(cs),
        "rates_set": rates_set(cs),
        "next_available": next_available,
        # The cron tick places holds, sends reminders and charges. If it has
        # not run lately, none of that is happening.
        "last_tick_at": _iso(cs.last_tick_at),
        "tick_ok": bool(cs.last_tick_at and now - aware(cs.last_tick_at) <= TICK_STALE_AFTER),
        **_summary_status(db, now),
    }


def watch_tick(db: Session, now: datetime | None = None) -> bool:
    """Tell the owner that the automation has stopped: no complete run of
    the tick for TICK_STALE_AFTER while a call is waiting for it (a confirmed
    call that starts within TICK_ALERT_HORIZON or has started and is not
    settled, or a settled one whose payment Stripe has not confirmed yet).
    At most one email per TICK_ALERT_EVERY, whoever notices first (an UPDATE
    claims the day). True when the email went out.

    Nothing else would say so: with the cron job stopped there are no holds,
    no reminders, no summary and no automatic charge, and no error either.
    Called (off the request, at most once a minute per process) from every
    consulting request, public or admin, which is what still runs then."""
    now = now or utcnow()
    settings = get_settings()
    if not settings.ADMIN_NOTIFY_EMAIL:
        return False
    cs = settings_row(db)
    settings_id, business_zone = cs.id, cs.timezone
    last = aware(cs.last_tick_at)
    if last is not None and now - last <= TICK_STALE_AFTER:
        return False
    alerted = aware(cs.tick_alert_at)
    if alerted is not None and now - alerted < TICK_ALERT_EVERY:
        return False
    B = ConsultBooking
    # Every call the automation still owes something: a confirmed one that
    # starts within the horizon; one that has started or ended and is not
    # settled (its summary and its charge are waiting for the tick); and one
    # that is settled but whose payment has no answer from Stripe yet (the
    # owner was told "it is asked again within a few minutes", and the tick
    # is what asks).
    soon = db.execute(
        select(B).where(or_(
            and_(B.status == "confirmed", B.settlement == "", B.start_at <= now + TICK_ALERT_HORIZON),
            and_(B.settlement.in_(tuple(money.SETTLEMENT_REASON)), B.charge_state == "pending"),
        )).order_by(B.start_at)
    ).scalars().all()
    if not soon:
        db.rollback()
        return False
    claimed = db.execute(
        update(ConsultSettings).where(
            ConsultSettings.id == settings_id,
            or_(ConsultSettings.tick_alert_at.is_(None), ConsultSettings.tick_alert_at <= now - TICK_ALERT_EVERY),
        ).values(tick_alert_at=now)
        # the database decides; the row in this session is read again after the commit
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if claimed.rowcount != 1:
        return False
    first = soon[0]
    since = f"since {when_text(last, business_zone)}" if last is not None else "yet: it has never run"
    sent = False
    try:
        sent = send_email(
            to=settings.ADMIN_NOTIFY_EMAIL,
            subject="[Consulting] The automation has stopped: holds, reminders and charges are not running",
            html=consult_owner_update_html(
                headline="The consulting automation has stopped",
                detail=(
                    f"The job that runs every five minutes has not completed a run {since}. Until it runs "
                    "again nothing happens by itself: no hold on the card, no reminder to the client, no "
                    "summary after the call, no automatic charge."
                    "\n\n"
                    f"{len(soon)} call{'s are' if len(soon) != 1 else ' is'} waiting for it: confirmed and "
                    "starting within 48 hours, already started and not settled, or settled with a payment "
                    "that Stripe has not confirmed yet. Check the cron job "
                    "(proreadyengineer-consult-tick) on Render: its last runs and their output. The admin "
                    "buttons on each booking work without it. You get this email at most once a day while "
                    "it lasts."
                ),
                rows=[
                    ("Last complete run", when_text(last, business_zone) if last is not None else "never"),
                    ("Earliest call waiting", f"{first.full_name}, {when_text(first.start_at, business_zone)}"),
                    ("Calls waiting", str(len(soon))),
                ],
                admin_url=f"{settings.SITE_URL.rstrip('/')}/admin#consult",
            ),
            db=db, scope_kind="system", scope_code="consult", audience="admin",
            template="consult_owner_tick_stopped",
        )
    except Exception:  # noqa: BLE001 — a watch must never break the request that ran it
        log.exception("The 'automation has stopped' email failed")
        db.rollback()
    if not sent:
        # Not told: the next request tries again.
        db.execute(update(ConsultSettings).where(ConsultSettings.id == settings_id).values(tick_alert_at=alerted)
                   .execution_options(synchronize_session=False))
        db.commit()
    return bool(sent)


def watch_tick_later() -> None:
    """watch_tick on a session of its own (a background task)."""
    from .db import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        watch_tick(db)
    except Exception:  # noqa: BLE001
        log.exception("Watching the consulting tick failed")
        db.rollback()
    finally:
        db.close()


def _summary_status(db: Session, now: datetime) -> dict:
    """Calls that have ended and whose "confirm the outcome" email has not
    gone out. Nothing is charged automatically for them until it has: the
    owner decides each from the admin, or the email gets through."""
    from . import consult_auto  # noqa: PLC0415 — consult_auto imports this module

    waiting = consult_auto.unsent_summaries(db, now)
    s = get_settings()
    if not waiting:
        note = ""
    elif not s.ADMIN_NOTIFY_EMAIL:
        note = "No owner address is set (ADMIN_NOTIFY_EMAIL), so the summary email cannot be sent."
    elif not s.RESEND_API_KEY:
        note = "No email service is set up (RESEND_API_KEY), so the summary email cannot be sent."
    else:
        note = "The email service has not accepted the summary email yet. It is tried again every few minutes."
    return {
        "summaries_unsent": len(waiting),
        "summaries_unsent_since": _iso(waiting[0].end_at) if waiting else None,
        "summaries_unsent_note": (
            f"{note} Nothing is charged automatically for these calls until it has gone out: "
            "decide each one from its booking." if waiting else ""
        ),
    }


# -----------------------------------------------------------------------------
# Emails
# -----------------------------------------------------------------------------

def when_text(at: datetime, tz_name: str) -> str:
    """'Tuesday, November 10, 2026 at 3:00 PM EST (America/New_York)'."""
    name = tz_name if valid_zone(tz_name) else "UTC"
    local = aware(at).astimezone(ZoneInfo(name))
    return f"{local.strftime('%A, %B %-d, %Y at %-I:%M %p %Z')} ({name})"


def _admin_url(booking: ConsultBooking | None = None) -> str:
    """The admin screen's own address for a booking (#consult/booking/<id>)."""
    base = f"{get_settings().SITE_URL.rstrip('/')}/admin#consult"
    return f"{base}/booking/{booking.id}" if booking is not None else base


def _card_text(booking: ConsultBooking) -> str:
    """The card saved on the booking, as words. Not necessarily the card
    the money is on: see card_in_use_text and charged_card_text."""
    return _card_words(booking.card_brand, booking.card_last4)


def _card_words(brand: str | None, last4: str | None) -> str:
    if not last4:
        return ""
    return f"{(brand or 'card').capitalize()} ending {last4}"


# Once a hold is authorized on a card, that card is the card for the call:
# the hold stays where it is, and what is charged is captured from it. The
# booking's saved card can still come to differ from it (a card page that
# was already open is finished after the hold was placed). Every ledger row
# therefore keeps the card it used, and whatever names "the card" where
# money is concerned reads it from the ledger, never from the booking.

def money_card(charges: list[ConsultCharge]) -> tuple[str, str]:
    """(brand, last four digits) of the card this booking's money is on:
    the card its hold is authorized on or was captured from, else the card
    of the last charge that went through. ("", "") when no money has been
    held or taken, and for rows written before the card was kept."""
    for row in reversed(charges):
        if row.kind == "hold" and row.status in ("authorized", "capturing", "captured"):
            return row.card_brand or "", row.card_last4 or ""
    for row in reversed(charges):
        if row.kind == "charge" and row.status == "succeeded":
            return row.card_brand or "", row.card_last4 or ""
    return "", ""


def card_in_use_text(db: Session, booking: ConsultBooking) -> str:
    """The card a charge for this booking would be, or was, taken from:
    the hold's card when there is one, otherwise the saved card."""
    return _card_words(*money_card(money.ledger(db, booking.id))) or _card_text(booking)


def charged_card_text(db: Session, booking: ConsultBooking, charge_id: int | None) -> str:
    """The card of one ledger row (the one that took the money a receipt is
    for). Falls back to the saved card for a row that did not keep its card."""
    row = db.get(ConsultCharge, charge_id) if charge_id else None
    if row is not None and row.booking_id == booking.id and row.card_last4:
        return _card_words(row.card_brand, row.card_last4)
    return _card_text(booking)


def refused_hold_card_text(db: Session, booking: ConsultBooking) -> str:
    """The card the last hold attempt was made on (the one that was refused)."""
    holds = [r for r in money.ledger(db, booking.id) if r.kind == "hold"]
    if holds and holds[-1].card_last4:
        return _card_words(holds[-1].card_brand, holds[-1].card_last4)
    return _card_text(booking)


def _claim_marker(db: Session, booking_id: int, column: str, now: datetime) -> bool:
    """Set an empty marker column. True for the one caller that set it: that
    caller sends the email the marker stands for."""
    done = db.execute(
        update(ConsultBooking)
        .where(ConsultBooking.id == booking_id, getattr(ConsultBooking, column).is_(None))
        .values({column: now})
    )
    db.commit()
    return done.rowcount == 1


def _return_marker(db: Session, booking_id: int, column: str) -> None:
    """Give a marker back: the email it stands for was not sent, and the
    tick tries again. (Where no email service is set up at all there is
    nothing to try again, and the marker is kept.)"""
    if not get_settings().RESEND_API_KEY:
        return
    db.execute(update(ConsultBooking).where(ConsultBooking.id == booking_id).values({column: None}))
    db.commit()


# An email the service keeps refusing is tried this many times at the
# tick's own pace (every five minutes), then once per EMAIL_SLOW_EVERY: the
# email log gets one line an hour for it, not one every five minutes.
EMAIL_QUICK_TRIES = 12
EMAIL_SLOW_EVERY = timedelta(hours=1)


def email_try_allowed(booking: ConsultBooking, name: str, now: datetime) -> bool:
    """May this email be tried now? `name` is the email's marker column, or
    'summary' / 'slot_lost'."""
    tried = (booking.email_tries or {}).get(name) or {}
    if int(tried.get("n") or 0) < EMAIL_QUICK_TRIES:
        return True
    try:
        last = aware(datetime.fromisoformat(str(tried.get("last"))))
    except (TypeError, ValueError):
        return True
    return now - last >= EMAIL_SLOW_EVERY


def note_email_try(db: Session, booking_id: int, name: str, now: datetime, *, sent: bool) -> None:
    """Count a try the email service refused; forget the count once it is sent."""
    booking = db.get(ConsultBooking, booking_id)
    if booking is None:
        return
    tries = dict(booking.email_tries or {})
    if sent:
        if name not in tries:
            return
        tries.pop(name)
    else:
        tries[name] = {"n": int((tries.get(name) or {}).get("n") or 0) + 1, "last": now.isoformat()}
    booking.email_tries = tries
    db.commit()


def send_slot_lost_notice(db: Session, booking_id: int, now: datetime | None = None) -> bool:
    """To a client who saved a card for a time that could no longer be
    theirs: the booking was not confirmed and nothing was charged. Sent
    once, by whoever claims the booking's notice marker; a send the email
    service refuses gives the marker back, and the tick tries again."""
    now = now or utcnow()
    booking = db.get(ConsultBooking, booking_id)
    if booking is None or booking.status != "expired" or booking.cancel_notice_sent_at is not None:
        return False
    if not email_try_allowed(booking, "slot_lost", now):
        return False
    if not _claim_marker(db, booking_id, "cancel_notice_sent_at", now):
        return False
    try:
        sent = bool(_send_cancellation(db, db.get(ConsultBooking, booking_id), kind="slot_lost"))
    except Exception:  # noqa: BLE001 — the webhook must still answer; the tick sends it
        log.exception("The 'could not be confirmed' email for consult booking %s failed", booking_id)
        db.rollback()
        sent = False
    if not sent:
        _return_marker(db, booking_id, "cancel_notice_sent_at")
    note_email_try(db, booking_id, "slot_lost", now, sent=sent)
    return sent


def send_confirmation(db: Session, booking_id: int) -> bool:
    """Booking confirmed: to the client (Meet link, their time, the terms,
    the manage link) and to the owner (who booked, what about, how much).

    Each of the two is sent at most once, by whoever claims its marker
    (confirmation_sent_at, owner_notified_at), and a send the email service
    refuses gives the marker back, so the tick sends it later. True when
    this call sent something."""
    sent_any = False
    for column, send in (("confirmation_sent_at", _confirmation_to_client), ("owner_notified_at", _confirmation_to_owner)):
        booking = db.get(ConsultBooking, booking_id)
        if booking is None or booking.status != "confirmed" or getattr(booking, column) is not None:
            continue
        if column == "owner_notified_at" and not get_settings().ADMIN_NOTIFY_EMAIL:
            continue
        now = utcnow()
        if not email_try_allowed(booking, column, now):
            continue
        if not _claim_marker(db, booking_id, column, now):
            continue
        try:
            sent = send(db, db.get(ConsultBooking, booking_id))
        except Exception:  # noqa: BLE001 — the other email, and the hold, must still go
            log.exception("Confirmation email (%s) for consult booking %s failed", column, booking_id)
            db.rollback()
            sent = False
        if sent:
            sent_any = True
        else:
            _return_marker(db, booking_id, column)
        note_email_try(db, booking_id, column, now, sent=bool(sent))
    return sent_any


def _confirmation_to_client(db: Session, booking: ConsultBooking) -> bool:
    settings = get_settings()
    cal = db.get(ExamCalendar, 1)
    link = booking_url(booking, manage_token(db, booking))
    hold_now = aware(booking.hold_due_at) is not None and aware(booking.hold_due_at) <= aware(booking.confirmed_at)
    return send_email(
        to=booking.email,
        subject=f"Your consulting call is confirmed ({booking.ref})",
        html=consult_confirmed_html(
            full_name=booking.full_name,
            when=when_text(booking.start_at, booking.timezone),
            minutes=booking.minutes,
            meet_url=booking.meet_url,
            manage_url=link,
            ref=booking.ref,
            total=usd(booking.total_cents),
            card=_card_text(booking),
            hold_when="shortly" if hold_now else when_text(booking.hold_due_at, booking.timezone),
            free_cancel_until=when_text(booking.free_cancel_until, booking.timezone),
            fee=usd(booking.fee_cents),
            fee_percent=booking.fee_percent,
            terms=list(booking.terms_text or []),
            invite_from=(cal.account_email if cal else "") or "",
            expert=settings.INSTRUCTOR_NAME,
        ),
        db=db, scope_kind="system", scope_code="consult", audience="client",
        template="consult_confirmed",
    )


def _confirmation_to_owner(db: Session, booking: ConsultBooking) -> bool:
    settings = get_settings()
    cs = settings_row(db)
    return send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Consulting] New booking: {booking.full_name}, {when_text(booking.start_at, cs.timezone)}",
        html=consult_owner_new_html(
            rows=[
                ("Client", booking.full_name),
                ("Email", booking.email),
                ("Company", booking.company or "not given"),
                ("Phone", booking.phone or "not given"),
                ("When", when_text(booking.start_at, cs.timezone)),
                ("Their time", when_text(booking.start_at, booking.timezone)),
                ("Length", f"{booking.minutes} minutes"),
                ("Rate", f"{usd(booking.rate_cents_per_hour)} per hour ({TIER_LABELS.get(booking.tier, booking.tier)})"),
                ("Total", usd(booking.total_cents)),
                ("Card", _card_text(booking) or "saved"),
                ("Reference", booking.ref),
            ],
            topic=booking.topic,
            meet_url=booking.meet_url,
            calendar_problem="" if booking.google_event_id else (
                "The calendar event could not be created, so the client has no Meet link yet. "
                "It is tried again every few minutes, and you get an email when it works. "
                "Create the meeting by hand and send it to them only if the call is close and "
                "that email has not come."
            ),
            admin_url=_admin_url(booking),
        ),
        db=db, scope_kind="system", scope_code="consult", audience="admin",
        template="consult_owner_new",
    )


def _send_cancellation(
    db: Session, booking: ConsultBooking, *, kind: str, result: PayResult | None = None,
) -> bool:
    """Cancellation, to the client. kind: 'client' | 'owner' | 'slot_lost' |
    'hold_failed'. True when the email service accepted it."""
    fee = int(booking.cancel_fee_cents or 0)
    if kind == "client" and fee > 0:
        if result is not None and result.ok:
            money_line = (
                f"Because the call was cancelled after the free-cancellation time, the "
                f"{booking.fee_percent}% fee of {usd(fee)} was charged to your card"
                + (f" ({charged_card_text(db, booking, result.charge_id)})"
                   if charged_card_text(db, booking, result.charge_id) else "") + ". "
                "Any hold on the rest of the amount has been released. "
                "To contest this charge, reply to this email; our support team handles every request."
            )
        else:
            money_line = (
                f"Because the call was cancelled after the free-cancellation time, the "
                f"{booking.fee_percent}% fee of {usd(fee)} applies. We could not charge your card "
                "for it; we will be in touch about settling it."
            )
    elif kind == "slot_lost":
        money_line = "Nothing was charged, and the card you entered will not be used."
    elif kind == "hold_failed":
        money_line = "Nothing was charged. You are welcome to book again with another card."
    else:
        money_line = "Nothing was charged. Any hold on your card has been released."
    return send_email(
        to=booking.email,
        subject=(
            f"Your consulting call could not be confirmed ({booking.ref})" if kind == "slot_lost"
            else f"Your consulting call is cancelled ({booking.ref})"
        ),
        html=consult_cancelled_html(
            full_name=booking.full_name,
            when=when_text(booking.start_at, booking.timezone),
            kind=kind,
            money_line=money_line,
            note=booking.cancel_note if kind == "owner" else "",
            rebook_url=f"{get_settings().SITE_URL.rstrip('/')}/consult",
            ref=booking.ref,
        ),
        db=db, scope_kind="system", scope_code="consult", audience="client",
        template="consult_slot_lost" if kind == "slot_lost" else "consult_cancelled",
    )


def _owner_rows(booking: ConsultBooking, cs: ConsultSettings) -> list[tuple[str, str]]:
    rows = [
        ("Client", f"{booking.full_name} ({booking.email})"),
        ("Call", f"{when_text(booking.start_at, cs.timezone)}, {booking.minutes} minutes"),
        ("Booked amount", usd(booking.total_cents)),
        ("Charged so far", usd(booking.charged_cents)),
        ("Refunded", usd(booking.refunded_cents)),
        ("Reference", booking.ref),
    ]
    if booking.dispute_state:
        words = {
            "open": "in dispute at the client's bank", "lost": "lost to a dispute",
            "won": "disputed, decided for you", "closed": "inquiry closed",
        }.get(booking.dispute_state, booking.dispute_state)
        rows.insert(5, ("Dispute", f"{usd(booking.disputed_cents)} {words}" if booking.disputed_cents else words))
    return rows


def _notify_owner_cancelled(db: Session, booking: ConsultBooking, result: PayResult | None) -> None:
    settings = get_settings()
    if not settings.ADMIN_NOTIFY_EMAIL:
        return
    cs = settings_row(db)
    fee = int(booking.cancel_fee_cents or 0)
    if fee <= 0:
        headline, detail = "A client cancelled a call", "Cancelled inside the free-cancellation time: no fee."
    elif result is not None and result.ok:
        headline = "A client cancelled late: the fee was charged"
        detail = f"The {booking.fee_percent}% late-cancellation fee of {usd(fee)} was charged."
    else:
        headline = "A client cancelled late: the fee could NOT be charged"
        detail = (
            f"The {booking.fee_percent}% late-cancellation fee of {usd(fee)} is owed, but the card was "
            f"refused: {(result.message or result.code) if result else 'no answer from Stripe'}. "
            "Charge it again from the booking, or waive it."
        )
    send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Consulting] {headline}: {booking.full_name}",
        html=consult_owner_update_html(
            headline=headline, detail=detail, rows=_owner_rows(booking, cs), admin_url=_admin_url(booking),
        ),
        db=db, scope_kind="system", scope_code="consult", audience="admin",
        template="consult_owner_cancelled",
    )


def notify_owner(
    db: Session, booking: ConsultBooking, *, template: str, headline: str, detail: str,
    extra_rows: list[tuple[str, str]] | None = None, extra_link: tuple[str, str] | None = None,
) -> bool:
    """One of the owner's notices about a booking, in the shared shape:
    what happened, the booking's facts, a button to it. False when there is
    nobody to tell or the email did not go out."""
    settings = get_settings()
    if not settings.ADMIN_NOTIFY_EMAIL:
        return False
    cs = settings_row(db)
    return send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Consulting] {headline}: {booking.full_name}",
        html=consult_owner_update_html(
            headline=headline, detail=detail, rows=_owner_rows(booking, cs) + list(extra_rows or []),
            admin_url=_admin_url(booking), extra_link=extra_link,
        ),
        db=db, scope_kind="system", scope_code="consult", audience="admin", template=template,
    )


def _send_client_receipt(
    db: Session, booking: ConsultBooking, result: PayResult, *, charged_at: datetime | None = None,
) -> None:
    """To the client, once, when money was actually taken: the receipt for
    the call, or the fee notice (no-show, late cancellation). Each says how
    to contest the charge. Called only by the one caller that settled the
    ledger row (`result.fresh`), so a repeat never sends it twice."""
    kind = money.SETTLEMENT_REASON.get(booking.settlement or "")
    if kind is None or result.amount_cents <= 0:
        return
    minutes_line = ""
    if kind == "meeting":
        billed = booking.billed_minutes or booking.minutes
        minutes_line = (
            f"{billed} minutes" if billed == booking.minutes
            else f"{billed} of the {booking.minutes} minutes booked"
        )
    subject = {
        "meeting": f"Receipt for your consulting call ({booking.ref})",
        "no_show_fee": f"No-show fee for your consulting call ({booking.ref})",
        "late_cancel_fee": f"Cancellation fee for your consulting call ({booking.ref})",
    }[kind]
    send_email(
        to=booking.email,
        subject=subject,
        html=consult_receipt_html(
            full_name=booking.full_name, kind=kind,
            when=when_text(booking.start_at, booking.timezone),
            amount=usd(result.amount_cents), card=charged_card_text(db, booking, result.charge_id),
            charged_on=when_text(charged_at or utcnow(), booking.timezone), ref=booking.ref,
            minutes_line=minutes_line, fee_percent=booking.fee_percent,
            from_hold=result.status == "captured",
        ),
        db=db, scope_kind="system", scope_code="consult", audience="client",
        template="consult_receipt" if kind == "meeting" else "consult_fee_notice",
    )


def notify_owner_payment(
    db: Session, booking: ConsultBooking, result: PayResult, *, what: str, reason: str = "",
) -> None:
    """Charge result, to the owner: what was asked, and what the card did.
    `reason` is why an automatic step decided it (who joined, or his own
    choice from the email).

    The client's receipt or fee notice leaves from here too, when money was
    taken by this very call."""
    if result.ok and result.fresh and what != "Refund" and result.status in ("succeeded", "captured"):
        try:
            _send_client_receipt(db, booking, result)
        except Exception:  # noqa: BLE001 — the owner's notice below must still go
            log.exception("Receipt email for consult %s failed", booking.ref)
            db.rollback()
    settings = get_settings()
    if not settings.ADMIN_NOTIFY_EMAIL:
        return
    cs = settings_row(db)
    if result.status == "noop":
        headline, detail = f"{what}: nothing to charge", "No money was taken. Any hold on the card was released."
    elif result.ok:
        headline = f"{what}: {usd(result.amount_cents)} went through"
        detail = f"{usd(result.amount_cents)} was " + ("refunded." if what == "Refund" else "charged.")
    elif result.status == "requires_action":
        headline = f"{what}: the card needs the client's authentication"
        detail = (
            "The bank wants the cardholder to approve the payment, which cannot happen without them. "
            "Nothing was taken. Ask the client to replace the card from their booking page; the amount "
            "is taken as soon as they do."
        )
    elif what == "Refund" and result.status == "needs_review":
        headline = "A refund needs checking in Stripe"
        detail = (
            "A refund was asked for on this booking and no answer from Stripe was ever recorded; since "
            "then Stripe could not be asked whether it was made. Nothing new is sent to the card "
            "meanwhile. The site asks again every few minutes and records the answer when it comes. To "
            "be sure now, look at the payment in Stripe."
        )
    elif what == "Refund" and result.status == "failed":
        headline = "Refund: NOT made"
        detail = f"Nothing was returned to the card. {result.message or result.code or 'No reason was given'}"
    elif result.status == "needs_review" and result.code == money.REQUEST_REFUSED:
        headline = f"{what}: Stripe refused the request (not the card)"
        detail = (
            f"Stripe refused the request itself: {result.message or 'no reason given'}. Nothing was taken, "
            "and the client has not been told anything: this is about the site's Stripe setup, not about "
            "their card."
            "\n\n"
            "When the cause is put right, open the booking, press \"Not charged\" to clear this attempt "
            "(the site checks with Stripe that nothing was taken), then press Charge again."
        )
    elif result.status == "needs_review":
        headline = f"{what}: an earlier attempt needs checking in Stripe"
        detail = (
            "An earlier attempt at this payment got no answer from Stripe and it is too late to ask "
            "again safely, so it is not known whether the card was charged. Nothing new was sent to "
            "the card. Look the payment up in Stripe by the booking reference, then open the booking "
            "and press \"Paid in Stripe\" or \"Not charged\"."
        )
    elif result.status == "failed":
        headline = f"{what}: FAILED"
        detail = f"Nothing was taken. Stripe said: {result.message or result.code or 'no reason given'}."
    elif what == "Refund":
        headline = "Refund: no answer from Stripe yet"
        detail = (
            "Stripe could not be reached, or reports the refund as not completed yet, so the outcome is "
            "not known. Nothing is refunded twice: the site asks Stripe again every few minutes, and "
            "before anything is sent again it asks whether the refund was already made."
        )
    else:
        headline = f"{what}: no answer from Stripe yet"
        detail = (
            "Stripe could not be reached, so the outcome is not known. Nothing is charged twice: "
            "press the same button again and the same request is repeated."
        )
    if reason:
        detail = f"{reason}\n\n{detail}"
    send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Consulting] {headline}: {booking.full_name}",
        html=consult_owner_update_html(
            headline=headline, detail=detail, rows=_owner_rows(booking, cs), admin_url=_admin_url(booking),
        ),
        db=db, scope_kind="system", scope_code="consult", audience="admin",
        template="consult_owner_charge_result",
    )
