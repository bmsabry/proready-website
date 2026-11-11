"""Tables of the paid consulting-call feature (2026-11).

Four tables, all new (create_all builds them complete; a column added to
any of them in a LATER release needs an `_ensure_column` line in main.py):

  consult_settings        one row (id 1): hours, durations, rates, policy
  consult_bookings        one row per booking attempt, with its whole life
  consult_booking_events  append-only timeline of a booking
  consult_charges         the money ledger: every hold, charge and refund

Booking status (the public contract's set):

  pending_card  the slot is held for PENDING_HOLD_MINUTES while the client
                saves a card on Stripe; nothing can be charged yet
  confirmed     card saved, meeting on the calendar
  cancelled     called off (by the client, the owner, or the system)
  completed     the meeting is over and the outcome is decided: charged in
                full (or for fewer minutes), or not charged at all
  no_show       the client did not join: the fee applies
  expired       the card was never saved in time; the slot went back

Money never lives in the status. What was decided is `settlement`, what is
owed is `amount_due_cents`, what was actually taken is `charged_cents`
(always recomputed from the ledger, never incremented), and what went back
is `refunded_cents`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ConsultSettings(Base):
    """Admin-editable rules of the consulting calendar: one row (id 1).

    Attribute names for hours, step, buffer, notice, horizon and daily cap
    match ExamCalendar on purpose, so the slot arithmetic in exam_calendar
    reads either row.
    """

    __tablename__ = "consult_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Off until the owner has saved the four hourly rates in the admin panel
    # and switched booking on there (see consult.rates_set).
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    # {"mon": [["08:00", "23:00"]], ..., "sun": [["08:00", "23:00"]]} on the
    # business clock (the default: every day, 08:00 to 23:00).
    weekly_hours: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    step_minutes: Mapped[int] = mapped_column(Integer, default=30)
    durations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=15)
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=2)
    horizon_days: Mapped[int] = mapped_column(Integer, default=60)
    max_per_day: Mapped[int] = mapped_column(Integer, default=4)

    # Hourly rates in cents, by urgency tier. 0 = not set. This repository is
    # public, so no rate lives in the code: the owner enters them in the admin
    # panel, and until all four are set nothing can be quoted or booked.
    rate_same_day_cents: Mapped[int] = mapped_column(Integer, default=0)
    rate_next_day_cents: Mapped[int] = mapped_column(Integer, default=0)
    rate_priority_cents: Mapped[int] = mapped_column(Integer, default=0)
    rate_standard_cents: Mapped[int] = mapped_column(Integer, default=0)
    # A slot this many calendar days ahead (business zone) or more is 'standard'.
    standard_from_days: Mapped[int] = mapped_column(Integer, default=7)

    # No-show and late-cancellation fee, percent of the booked amount.
    fee_percent: Mapped[int] = mapped_column(Integer, default=20)
    # Cancelling is free until this many hours before the start.
    free_cancel_hours: Mapped[int] = mapped_column(Integer, default=24)
    # The hold is placed this many hours before the start.
    hold_lead_hours: Mapped[int] = mapped_column(Integer, default=24)
    # The default outcome runs this many hours after the scheduled end.
    auto_settle_hours: Mapped[int] = mapped_column(Integer, default=2)

    # Client reminders (consult_auto.send_reminder). The first goes out this
    # many hours before the booking's free-cancellation deadline, so the
    # client still has that long to cancel at no charge (with the defaults:
    # 48 hours before the start). The last goes out this many hours before
    # the start.
    reminder_before_deadline_hours: Mapped[int] = mapped_column(Integer, default=24)
    reminder_before_start_hours: Mapped[int] = mapped_column(Integer, default=1)

    # When the settlement tick last ran to the end (consult_auto.run_tick).
    # The admin status strip warns when this goes stale: without the tick no
    # hold is placed, no reminder sent and nothing is charged by itself.
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When the owner was last emailed that the tick has stopped (at most
    # once a day).
    tick_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConsultBooking(Base):
    __tablename__ = "consult_bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Public reference, in URLs and emails ("C-7F3K9Q2A").
    ref: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    # The manage token itself is never stored: only its SHA-256. It can be
    # minted again for an email from the server secret and this salt.
    manage_token_hash: Mapped[str] = mapped_column(String(64), default="")
    manage_token_salt: Mapped[str] = mapped_column(String(32), default="")

    # 'pending_card' | 'confirmed' | 'cancelled' | 'completed' | 'no_show' | 'expired'
    status: Mapped[str] = mapped_column(String(16), default="pending_card", index=True)

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    minutes: Mapped[int] = mapped_column(Integer)
    # While pending_card: the slot is held until this instant.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # The client, as typed.
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), index=True)
    company: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    topic: Mapped[str] = mapped_column(Text, default="")
    # The client's IANA zone (their emails read in it).
    timezone: Mapped[str] = mapped_column(String(64), default="")

    # Price, fixed at booking: what the client was shown and agreed to.
    # 'same_day' | 'next_day' | 'priority' | 'standard'
    tier: Mapped[str] = mapped_column(String(16), default="")
    rate_cents_per_hour: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    # Policy in force at booking (later settings changes do not reach back).
    fee_percent: Mapped[int] = mapped_column(Integer, default=20)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    free_cancel_hours: Mapped[int] = mapped_column(Integer, default=24)
    grace_minutes: Mapped[int] = mapped_column(Integer, default=15)
    hold_lead_hours: Mapped[int] = mapped_column(Integer, default=24)
    auto_settle_hours: Mapped[int] = mapped_column(Integer, default=2)
    # Set at confirmation.
    free_cancel_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When the pre-meeting hold is due (W1b places it).
    hold_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    # When the default outcome runs unless the owner chose (W1b).
    settle_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)

    # Consent record: which terms, the hash of the exact text shown, when,
    # from where. The text itself is kept too, so the record can be read.
    terms_version: Mapped[str] = mapped_column(String(64), default="")
    terms_hash: Mapped[str] = mapped_column(String(64), default="")
    terms_text: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    consent_ip: Mapped[str] = mapped_column(String(64), default="")
    consent_user_agent: Mapped[str] = mapped_column(String(400), default="")

    # Stripe: the customer made for this booking and the card saved on it.
    stripe_customer_id: Mapped[str] = mapped_column(String(64), default="")
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    stripe_setup_intent_id: Mapped[str] = mapped_column(String(64), default="")
    stripe_payment_method_id: Mapped[str] = mapped_column(String(64), default="")
    card_brand: Mapped[str] = mapped_column(String(24), default="")
    card_last4: Mapped[str] = mapped_column(String(4), default="")
    card_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When Stripe created the "card saved" event the card above came from.
    # An event older than this is never applied over it (Stripe can deliver
    # an earlier card page's event late, or again).
    card_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # The pre-meeting hold (a manual-capture PaymentIntent). hold_state:
    # '' none yet | 'authorized' | 'failed' | 'requires_action' |
    # 'captured' | 'released'
    hold_payment_intent_id: Mapped[str] = mapped_column(String(64), default="")
    hold_state: Mapped[str] = mapped_column(String(16), default="", index=True)
    hold_cents: Mapped[int] = mapped_column(Integer, default=0)
    hold_placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    hold_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    hold_error: Mapped[str] = mapped_column(String(300), default="")

    # Attendance, from the Google Meet API (W1b). {} = not checked yet.
    attendance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # '' not checked | 'both' | 'client_absent' | 'host_absent' | 'unknown'
    attendance_state: Mapped[str] = mapped_column(String(16), default="")
    attendance_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # What was decided once the meeting was over or the booking called off:
    # '' open | 'charged' | 'no_show' | 'waived' | 'late_cancel'
    settlement: Mapped[str] = mapped_column(String(16), default="")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Who decided: an admin email, 'auto', 'client' (late cancellation).
    settled_by: Mapped[str] = mapped_column(String(320), default="")
    # Minutes billed (may be fewer than booked when the owner says so).
    billed_minutes: Mapped[int] = mapped_column(Integer, default=0)
    # What the decision says is owed, and where collecting it stands:
    # '' nothing asked | 'pending' | 'paid' | 'failed' | 'requires_action'
    amount_due_cents: Mapped[int] = mapped_column(Integer, default=0)
    charge_state: Mapped[str] = mapped_column(String(16), default="")
    charge_error: Mapped[str] = mapped_column(String(300), default="")
    # Recomputed from consult_charges after every ledger change.
    charged_cents: Mapped[int] = mapped_column(Integer, default=0)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)

    # Disputes (chargebacks) the client's bank opened on this booking's
    # payments, from Stripe's webhook. Nothing here moves money: Stripe and
    # the bank do that. disputed_cents is what is open or was lost;
    # dispute_lost_cents is the part the bank returned to the cardholder,
    # which the booking no longer shows as kept.
    # dispute_state: '' none | 'open' | 'won' | 'lost' | 'closed' (an inquiry
    # that never became a dispute).
    disputed_cents: Mapped[int] = mapped_column(Integer, default=0)
    dispute_lost_cents: Mapped[int] = mapped_column(Integer, default=0)
    dispute_state: Mapped[str] = mapped_column(String(16), default="")

    # The owner's choice from the post-meeting email (W1b): '' | 'charge' |
    # 'no_show' | 'waive'.
    owner_choice: Mapped[str] = mapped_column(String(16), default="")
    owner_choice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Google Calendar event with the Meet link.
    google_event_id: Mapped[str] = mapped_column(String(256), default="")
    meet_url: Mapped[str] = mapped_column(String(500), default="")
    calendar_link: Mapped[str] = mapped_column(String(1000), default="")

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # 'client' | 'owner' | 'system' (no hold could be placed on the card)
    cancelled_by: Mapped[str] = mapped_column(String(16), default="")
    cancel_note: Mapped[str] = mapped_column(Text, default="")
    cancel_fee_cents: Mapped[int] = mapped_column(Integer, default=0)

    # Email markers (the ones after confirmation are W1b's): set when the
    # email went out, so a retried job never sends it twice.
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Emails the service refused, per email: {"<name>": {"n": tries, "last": ISO time}}.
    # After a dozen tries an email is tried once an hour (consult.email_try_allowed).
    email_tries: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    # The owner's "new booking" email (its own marker: either can fail alone).
    owner_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Claimed (set) by the one request that sends the cancellation emails.
    cancel_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # The two client reminders. The names are from the first design (24 hours
    # and 1 hour before the start); they now mark the first reminder (before
    # the free-cancellation deadline) and the last one (before the start).
    reminder_24h_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reminder_1h_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    hold_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    hold_failed_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    summary_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


Index("ix_consult_bookings_status_start", ConsultBooking.status, ConsultBooking.start_at)


class ConsultBookingEvent(Base):
    """One line of a booking's timeline. Rows are only ever added."""

    __tablename__ = "consult_booking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(Integer, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 'created', 'card_saved', 'confirmed', 'calendar_event_created',
    # 'cancelled', 'charge_succeeded', 'charge_failed', 'refunded', ...
    kind: Mapped[str] = mapped_column(String(48))
    # 'client' | 'system' | 'stripe' | 'auto' | an admin's email
    actor: Mapped[str] = mapped_column(String(320), default="system")
    note: Mapped[str] = mapped_column(Text, default="")
    amount_cents: Mapped[int | None] = mapped_column(Integer, default=None)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ConsultCharge(Base):
    """The money ledger: one row per attempt to move money for a booking.

    kind 'charge'  an off-session payment captured at once
         'hold'    a manual-capture authorization; captured or released later
         'refund'  money sent back against one of the rows above (parent_id)

    A row is written (status 'pending') and committed BEFORE Stripe is
    called, with the idempotency key that call will carry. If the answer is
    lost, the same key is sent again and Stripe returns the first result
    instead of charging twice. One successful row per (booking, kind,
    reason) is the rule that makes every money step safe to retry.

    status: 'pending' | 'succeeded' | 'authorized' (hold) | 'capturing' (hold)
            | 'captured' (hold) | 'released' (hold) | 'failed'
            | 'requires_action'
            | 'needs_review' (outcome unknown and too old to ask again)
    """

    __tablename__ = "consult_charges"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    # 'meeting' | 'no_show_fee' | 'late_cancel_fee' | 'hold' | 'refund'
    reason: Mapped[str] = mapped_column(String(48))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # The card this attempt used (a replaced card starts a new attempt).
    payment_method_id: Mapped[str] = mapped_column(String(64), default="")
    # The card that payment method is, as the client knows it: kept on the
    # row because the booking's saved card can change afterwards, and a
    # receipt must name the card the money was taken from.
    card_brand: Mapped[str] = mapped_column(String(32), default="")
    card_last4: Mapped[str] = mapped_column(String(8), default="")
    stripe_payment_intent_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    stripe_refund_id: Mapped[str] = mapped_column(String(64), default="")
    # Refund rows: the charge or hold row the money goes back against.
    parent_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Hold rows: what was captured from the authorization, and why.
    # While a capture is in flight (status 'capturing') the amount asked for
    # is kept, so a lost answer can be reconciled against Stripe.
    capture_requested_cents: Mapped[int] = mapped_column(Integer, default=0)
    captured_cents: Mapped[int] = mapped_column(Integer, default=0)
    capture_reason: Mapped[str] = mapped_column(String(48), default="")
    # Charge / hold rows: Stripe's own running total of what was refunded on
    # this PaymentIntent (charge.refunded webhook), and the part of it that
    # did not come from a refund row of ours, i.e. a refund made in the
    # Stripe dashboard. See consult_money.recompute.
    stripe_refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    external_refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    decline_code: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(String(300), default="")
    actor: Mapped[str] = mapped_column(String(320), default="system")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
