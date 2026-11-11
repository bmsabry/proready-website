"""Money for consulting bookings: the ledger, and the only code that asks
Stripe to move any.

Everything here is safe to call twice. The rules that make it so:

  * A ledger row (consult_charges) is written and committed BEFORE Stripe
    is called, carrying the idempotency key the call will use. If the
    answer never arrives, the next call sends the same key and Stripe
    returns its first answer instead of charging again.
  * One successful row per (booking, kind, reason). A second call for the
    same thing returns that row and never reaches Stripe.
  * A declined card took no money, so the next call may try again: a new
    attempt, a new key.
  * booking.charged_cents and refunded_cents are recomputed from the ledger
    after every change, never incremented.
  * No function here raises because a payment failed. A decline, a card
    that needs authentication and an unreachable Stripe all come back as a
    PayResult the caller reads.

Primitives:

  charge_saved_card(db, booking, cents, reason)  take money off-session now
  place_hold(db, booking)       authorize the booked amount (manual capture)
  collect(db, booking)          take what the booking's decided outcome says
                                is owed: captured from the hold when there
                                is one, charged to the saved card otherwise
  release_hold(db, booking)     let an authorization go
  refund(db, booking, cents)    send money back
  resolve_review(db, booking, outcome)
                                close an attempt parked as 'needs_review'
                                on what Stripe shows now: it was paid, or
                                it took nothing and may be tried again.
                                Moves no money.

Stripe is reached only through `_stripe()` (routes/checkout.py's seam, which
the tests replace).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .consult_models import ConsultBooking, ConsultBookingEvent, ConsultCharge

log = logging.getLogger(__name__)

# Stripe keeps an idempotency key for at least 24 hours. A row whose answer
# was lost and that nobody retried inside that time cannot be asked about
# safely any more: it is parked for a person to look at.
PENDING_REVIEW_AFTER = timedelta(hours=20)
# error_code of an attempt parked because Stripe refused the request itself
# (as opposed to one whose answer never came).
REQUEST_REFUSED = "request_refused"
# The same refund asked for twice inside this window is one refund.
REFUND_REPLAY_WINDOW = timedelta(seconds=120)

# The ledger reason for each decided outcome (booking.settlement).
SETTLEMENT_REASON = {
    "charged": "meeting",
    "no_show": "no_show_fee",
    "late_cancel": "late_cancel_fee",
}
REASON_LABEL = {
    "meeting": "consulting call",
    "no_show_fee": "no-show fee",
    "late_cancel_fee": "late-cancellation fee",
    "hold": "pre-meeting hold",
}


def utcnow() -> datetime:
    """The clock of the whole consulting feature (replaced in tests)."""
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; they were stored as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _g(obj, key: str, default=None):
    """A field of a Stripe object or of a plain dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
    else:
        value = getattr(obj, key, default)
    return default if value is None else value


def _stripe():
    # Lazy: routes.checkout owns the SDK seam, and importing it at module
    # level would make this domain module depend on the route layer.
    from .routes.checkout import _stripe as base  # noqa: PLC0415

    return base()


def _errors():
    """Stripe's exception classes (the SDK is a pinned requirement)."""
    import stripe  # noqa: PLC0415

    return stripe.CardError, stripe.InvalidRequestError, stripe.StripeError


def _refused_as_request(exc) -> bool:
    """Stripe refused the REQUEST, and asking again will not help: a
    parameter it does not accept, a key it does not know, a permission the
    key lacks, an idempotency key reused with other parameters. That is a
    fault of the site's setup, never of the client's card.

    Everything else that is not a card error (no connection, a rate limit, a
    5xx from Stripe) is passing: the attempt stays 'pending' and is asked
    again with the same key."""
    import stripe  # noqa: PLC0415

    return isinstance(exc, (
        stripe.InvalidRequestError, stripe.AuthenticationError, stripe.PermissionError, stripe.IdempotencyError,
    ))


@dataclass
class PayResult:
    """What a money step did. `ok` means the step is done as asked.

    status: 'succeeded' | 'authorized' | 'captured' | 'released' | 'noop'
            | 'failed' | 'requires_action' | 'error' | 'needs_review'
            | 'refused' (resolve_review: what was asked does not fit what
              Stripe shows, or there is nothing to resolve)
    fresh:  this call is the one that settled the ledger row (the caller
            that sees fresh=True sends the emails; a replay does not).
    at:     when Stripe took the money, where that is not "now"
            (resolve_review).
    """

    ok: bool
    status: str
    amount_cents: int = 0
    code: str = ""
    message: str = ""
    fresh: bool = False
    charge_id: int | None = None
    at: datetime | None = None


def add_event(
    db: Session, booking: ConsultBooking, kind: str, *, actor: str = "system",
    note: str = "", amount_cents: int | None = None, data: dict | None = None,
    at: datetime | None = None,
) -> None:
    """Append one line to the booking's timeline (the caller commits)."""
    db.add(ConsultBookingEvent(
        booking_id=booking.id, at=at or utcnow(), kind=kind[:48], actor=(actor or "system")[:320],
        note=note or "", amount_cents=amount_cents, data=data or {},
    ))


def lock_booking(db: Session, booking_id: int) -> ConsultBooking | None:
    """The booking row, locked until this transaction ends and read fresh
    (SQLite, used in tests and local runs, has no row locks and ignores it)."""
    return db.execute(
        select(ConsultBooking).where(ConsultBooking.id == booking_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _settle_row(db: Session, row_id: int, was: str, *, was_code: str | None = None, **values) -> bool:
    """Move a ledger row out of status `was`, if it is still there (and, with
    `was_code`, only if it was closed with that error code). True for the
    one caller that moved it.

    One UPDATE with the old status in its WHERE clause: of two calls that
    both learned the outcome from Stripe (the same idempotency key gives
    both the same answer), exactly one records it, on any database. That
    caller writes the timeline line and is the one told `fresh`."""
    where = [ConsultCharge.id == row_id, ConsultCharge.status == was]
    if was_code is not None:
        where.append(ConsultCharge.error_code == was_code)
    done = db.execute(update(ConsultCharge).where(*where).values(**values))
    return done.rowcount == 1


# What Stripe says it DID is recorded whatever has been concluded about the
# row meanwhile. A row can be moved on the strength of a reading that a
# request still on its way to Stripe then makes stale: parked because no
# answer had come ('needs_review'), or closed because Stripe had nothing for
# it at that moment ('failed' with one of the codes below: by the tick for a
# lost hold, by finish_refunds for a refund, or by the owner's "not charged"
# after a look at Stripe). When that request comes back with a payment, an
# authorization or a refund, that is the truth, and losing it would have the
# same money asked for again (review 2, N1).
CLOSED_BY_INFERENCE = ("never_placed", "not_made", "review_not_charged")
# A request that is on its way cannot outlive the SDK's own timeouts and
# retries; a conclusion drawn from "Stripe has nothing" waits this long past
# the last moment such a request could have been sent.
IN_FLIGHT_MARGIN = timedelta(minutes=10)


def _record_success(db: Session, row_id: int, was: str, **values) -> bool:
    """Record what Stripe did for this row, from `was` or from any state a
    stale reading may have moved it to meanwhile. True for the one caller
    that wrote it."""
    if _settle_row(db, row_id, was, **values):
        return True
    for other in ("pending", "needs_review"):
        if other != was and _settle_row(db, row_id, other, **values):
            return True
    return any(_settle_row(db, row_id, "failed", was_code=code, **values) for code in CLOSED_BY_INFERENCE)


def _row(db: Session, row_id: int) -> ConsultCharge:
    return db.execute(
        select(ConsultCharge).where(ConsultCharge.id == row_id).execution_options(populate_existing=True)
    ).scalar_one()


def ledger(db: Session, booking_id: int) -> list[ConsultCharge]:
    db.flush()
    return list(db.execute(
        select(ConsultCharge).where(ConsultCharge.booking_id == booking_id)
        .order_by(ConsultCharge.id).execution_options(populate_existing=True)
    ).scalars().all())


def _paid(row: ConsultCharge) -> int:
    """What a ledger row actually took from the card."""
    if row.kind == "charge" and row.status == "succeeded":
        return row.amount_cents
    if row.kind == "hold" and row.status == "captured":
        return row.captured_cents
    return 0


def _refunded_by_payment(rows: list[ConsultCharge]) -> dict[int, int]:
    """{payment row id: cents refunded on it}, from two sources that must
    not be counted twice: our own refund rows, and refunds made outside the
    admin panel (the Stripe dashboard).

    Stripe only ever tells us its running total for a payment
    (stripe_refunded_cents). Whatever part of that total is not explained by
    a refund of ours, finished or still in flight, was made elsewhere; that
    part is kept in external_refunded_cents and only ever grows. Counting an
    in-flight refund of ours as explained means the webhook for our own
    refund, arriving before our row is settled, is never mistaken for an
    outside refund."""
    done: dict[int, int] = defaultdict(int)
    in_flight: dict[int, int] = defaultdict(int)
    for r in rows:
        if r.kind == "refund" and r.parent_id is not None:
            if r.status == "succeeded":
                done[r.parent_id] += r.amount_cents
            elif r.status in ("pending", "needs_review"):
                in_flight[r.parent_id] += r.amount_cents
    out: dict[int, int] = {}
    for r in rows:
        if r.kind not in ("charge", "hold"):
            continue
        elsewhere = (r.stripe_refunded_cents or 0) - done[r.id] - in_flight[r.id]
        if elsewhere > (r.external_refunded_cents or 0):
            r.external_refunded_cents = elsewhere
        out[r.id] = done[r.id] + (r.external_refunded_cents or 0)
    return out


def recompute(db: Session, booking: ConsultBooking) -> None:
    """Set charged_cents and refunded_cents from the ledger."""
    rows = ledger(db, booking.id)
    by_id = {r.id: r for r in rows}
    refunded = sum(min(cents, _paid(by_id[row_id])) for row_id, cents in _refunded_by_payment(rows).items())
    booking.charged_cents = sum(_paid(r) for r in rows)
    booking.refunded_cents = refunded


def unsettled_rows(db: Session, booking_id: int) -> list[ConsultCharge]:
    """Ledger rows whose outcome is not known yet."""
    return [r for r in ledger(db, booking_id) if r.status in ("pending", "capturing", "needs_review")]


def _card_error(exc) -> tuple[str, str, str, str]:
    """(code, decline_code, message, payment_intent id) of a card error."""
    code = str(getattr(exc, "code", "") or "card_declined")
    body = getattr(exc, "json_body", None)
    err = (body.get("error") if isinstance(body, dict) else None) or {}
    decline = str(err.get("decline_code") or "")
    pi = err.get("payment_intent") or {}
    pi_id = str(pi.get("id") or "") if isinstance(pi, dict) else ""
    if not pi_id:
        pi_id = str(_g(_g(getattr(exc, "error", None), "payment_intent"), "id", "") or "")
    message = str(getattr(exc, "user_message", None) or exc or "")[:300]
    return code, decline, message, pi_id


def _cancel_quietly(stripe, pi_id: str) -> None:
    """A PaymentIntent that failed is left 'incomplete' at Stripe; cancel it
    so nothing can be confirmed on it later. Best effort."""
    if not pi_id:
        return
    try:
        stripe.PaymentIntent.cancel(pi_id)
    except Exception as exc:  # noqa: BLE001 — tidying up must never fail the caller
        log.info("Could not cancel failed PaymentIntent %s: %s", pi_id, exc)


# -----------------------------------------------------------------------------
# Taking money: a charge, or a hold
# -----------------------------------------------------------------------------

def _not_owed(booking: ConsultBooking, cents: int, reason: str, rows: list[ConsultCharge]) -> PayResult | None:
    """Called with the booking locked, right before money is asked for: is
    `cents` for `reason` still what the booking's decision says is owed?
    `rows` is the booking's whole ledger as the caller has just read it (the
    one reading its other checks use: on a database without row locks a
    second reading could differ).

    collect() reads what is owed and lets go of the lock before it asks for
    the money, so by the time the request is built another request may have
    collected the same amount, or the owner may have changed the outcome.
    None when the charge may go ahead; otherwise the refusal to return. A
    booking with no outcome decided is not judged here (nothing says what
    it owes)."""
    if not booking.settlement:
        return None
    if SETTLEMENT_REASON.get(booking.settlement) != reason:
        return PayResult(
            False, "error", code="decision_changed",
            message="The outcome of this booking was changed a moment ago. Nothing was charged by this "
                    "request; look at the booking again.",
        )
    owed = (booking.amount_due_cents or 0) - sum(_paid(r) for r in rows)
    if cents > owed:
        return PayResult(
            False, "error", code="not_owed",
            message="This amount is no longer owed on this booking: it was collected a moment ago, or the "
                    "outcome changed. Nothing was charged by this request.",
        )
    return None


def _take(
    db: Session, booking: ConsultBooking, cents: int, reason: str, *, actor: str, hold: bool,
    _again: bool = True,
) -> PayResult:
    cents = int(cents or 0)
    if cents <= 0:
        return PayResult(True, "noop")
    kind = "hold" if hold else "charge"
    done_states = ("authorized", "capturing", "captured", "released") if hold else ("succeeded",)
    now = utcnow()

    booking = lock_booking(db, booking.id)
    if booking is None:
        return PayResult(False, "error", code="no_booking", message="The booking no longer exists.")
    everything = ledger(db, booking.id)
    rows = [r for r in everything if r.kind == kind and r.reason == reason]
    done = next((r for r in rows if r.status in done_states), None)
    if done is not None:
        db.commit()
        return PayResult(
            done.status != "released", done.status,
            amount_cents=done.captured_cents if done.status == "captured" else done.amount_cents,
            charge_id=done.id,
        )
    last = rows[-1] if rows else None
    if last is not None and last.status == "needs_review":
        db.commit()
        if last.error_code == REQUEST_REFUSED:
            return PayResult(
                False, "needs_review", code=REQUEST_REFUSED, charge_id=last.id,
                message=f"Stripe refused an earlier attempt as a request, not the card ({last.error_message}). "
                        "Once the cause is put right, clear that attempt with \"Not charged\", then try again.",
            )
        return PayResult(
            False, "needs_review", code="needs_review", charge_id=last.id,
            message="An earlier attempt has an unknown outcome. Check it in Stripe before trying again.",
        )
    if not hold:
        refusal = _not_owed(booking, cents, reason, everything)
        if refusal is not None:
            db.commit()
            return refusal
    try:
        stripe = _stripe()
        card_error, invalid_request, stripe_error = _errors()
    except Exception as exc:  # noqa: BLE001 — not configured, or the SDK is missing
        db.commit()
        log.error("Stripe is unavailable for booking %s: %s", booking.ref, getattr(exc, "detail", exc))
        return PayResult(False, "error", code="stripe_unavailable", message="Payments are not available right now.")

    if last is not None and last.status == "pending":
        row = last
        if row.amount_cents != cents:
            db.commit()
            return PayResult(
                False, "error", code="in_progress", charge_id=row.id,
                message="Another payment for this booking is still being confirmed.",
            )
        if not row.stripe_payment_intent_id and now - aware(row.created_at) > PENDING_REVIEW_AFTER:
            row.status = "needs_review"
            row.error_message = "No answer from Stripe was recorded and it is too late to ask again safely."
            add_event(db, booking, f"{kind}_needs_review", actor=actor, amount_cents=cents,
                      note=f"The {REASON_LABEL.get(reason, reason)} of an earlier attempt has an unknown outcome.")
            db.commit()
            return PayResult(False, "needs_review", code="needs_review", charge_id=row.id,
                             message=row.error_message)
    else:
        if not booking.stripe_customer_id or not booking.stripe_payment_method_id:
            db.commit()
            return PayResult(False, "failed", code="no_card", message="No card is saved on this booking.")
        attempt = (last.attempt if last is not None else 0) + 1
        row = ConsultCharge(
            booking_id=booking.id, kind=kind, reason=reason, attempt=attempt,
            idempotency_key=f"consult:{booking.ref}:{kind}:{reason}:{attempt}",
            amount_cents=cents, currency=booking.currency or "usd", status="pending",
            payment_method_id=booking.stripe_payment_method_id, actor=actor[:320],
            card_brand=(booking.card_brand or "")[:32], card_last4=(booking.card_last4 or "")[:8],
            created_at=now,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            # Another call wrote this very attempt a moment ago (the key is
            # unique). Start over: this time its row is found, and its key
            # is the one that is used.
            db.rollback()
            if _again:
                return _take(db, booking, cents, reason, actor=actor, hold=hold, _again=False)
            return PayResult(False, "error", code="in_progress",
                             message="Another payment for this booking is still being confirmed.")

    row_id, key, pi_known = row.id, row.idempotency_key, row.stripe_payment_intent_id
    create = dict(
        amount=cents,
        currency=row.currency or "usd",
        customer=booking.stripe_customer_id,
        payment_method=row.payment_method_id,
        off_session=True,
        confirm=True,
        capture_method="manual" if hold else "automatic",
        # Cards only, said outright. Without this the intent accepts "the
        # payment methods enabled in the Dashboard", some of which redirect,
        # and Stripe then wants a return_url before it will confirm: a
        # request with nobody present to be sent back anywhere. The card page
        # (setup mode, payment_method_types=["card"]) only ever saves a card.
        payment_method_types=["card"],
        description=f"ProReadyEngineer {REASON_LABEL.get(reason, reason)} ({booking.ref})",
        metadata={
            "kind": "consult", "booking_id": str(booking.id), "booking_ref": booking.ref,
            "ledger_id": str(row_id), "reason": reason,
        },
        idempotency_key=key,
    )
    booking_id, ref = booking.id, booking.ref
    # The ledger row is durable before Stripe hears anything. This also lets
    # go of the row lock: no database lock is held across the network call.
    db.commit()

    status, code, decline, message, pi_id = "", "", "", "", pi_known
    try:
        if pi_known:
            pi = stripe.PaymentIntent.retrieve(pi_known)
        else:
            pi = stripe.PaymentIntent.create(**create)
        pi_id = str(_g(pi, "id", "") or pi_id)
        pi_status = str(_g(pi, "status", ""))
        if pi_status == "succeeded" and not hold:
            status = "succeeded"
        elif pi_status == "requires_capture" and hold:
            status = "authorized"
        elif pi_status == "processing":
            status = "pending"
            code, message = "processing", "Stripe is still processing this payment."
        elif pi_status == "requires_action":
            status, code = "requires_action", "authentication_required"
            message = "The card needs its owner to authenticate the payment."
            _cancel_quietly(stripe, pi_id)
        elif pi_status == "canceled":
            status, code, message = "failed", "canceled", "The payment was cancelled at Stripe."
        else:
            status, code = "failed", pi_status or "unexpected_status"
            message = f"Stripe answered with the unexpected status {pi_status!r}."
            _cancel_quietly(stripe, pi_id)
    except card_error as exc:
        code, decline, message, err_pi = _card_error(exc)
        pi_id = err_pi or pi_id
        status = "requires_action" if code == "authentication_required" else "failed"
        _cancel_quietly(stripe, pi_id)
    except stripe_error as exc:
        if _refused_as_request(exc):
            # The request itself was refused: the site's fault, not the
            # card's. Never recorded as a declined card (the client would be
            # asked for another card and the booking cancelled for it). The
            # attempt is parked for the owner, who is told once.
            log.error("Stripe refused the request for %s (%s): %s", ref, key, exc)
            status, code = "needs_review", REQUEST_REFUSED
            decline = str(getattr(exc, "code", "") or type(exc).__name__)
            message = str(getattr(exc, "user_message", None) or exc)[:300]
        else:
            # No verdict: the answer is unknown. The row stays 'pending' and
            # the next call asks again with the same key.
            log.error("Stripe did not answer for %s (%s): %s", ref, key, exc)
            return PayResult(False, "error", code="stripe_error", charge_id=row_id,
                             message="Stripe could not be reached. Nothing was changed; try again.")
    except Exception as exc:  # noqa: BLE001 — same: unknown outcome, keep the key
        log.exception("Unexpected failure charging %s (%s)", ref, key)
        return PayResult(False, "error", code="unexpected", charge_id=row_id, message=str(exc)[:300])

    booking = lock_booking(db, booking_id)
    recorded = dict(error_code=code[:64], decline_code=decline[:64], error_message=message[:300])
    if pi_id:
        recorded["stripe_payment_intent_id"] = pi_id
    # While the outcome is still unknown the row stays 'pending' (it only
    # learns its PaymentIntent, so the next call looks it up).
    if status in ("succeeded", "authorized"):
        moved = _record_success(db, row_id, "pending", status=status, **recorded)
    else:
        moved = _settle_row(db, row_id, "pending", status=status, **recorded)
    fresh = moved and status != "pending"
    row = _row(db, row_id)
    if not moved:
        # A concurrent call settled the row first; report what it recorded.
        status, code, message = row.status, row.error_code, row.error_message
    if hold and fresh:
        booking.hold_payment_intent_id = row.stripe_payment_intent_id
        if status == "authorized":
            booking.hold_state, booking.hold_cents = "authorized", cents
            booking.hold_placed_at, booking.hold_error = utcnow(), ""
        elif status == "needs_review":
            # Not the card's doing: the booking is not marked as having a
            # refused hold (that would ask the client for a card and cancel).
            booking.hold_error = f"Stripe refused the request: {message or code}"[:300]
        else:
            booking.hold_state = status  # 'failed' | 'requires_action'
            booking.hold_failed_at, booking.hold_error = utcnow(), (message or code)[:300]
    recompute(db, booking)
    if fresh:
        label = REASON_LABEL.get(reason, reason)
        if status in ("succeeded", "authorized"):
            add_event(db, booking, "hold_placed" if hold else "charge_succeeded", actor=actor,
                      amount_cents=cents, note=f"{label}", data={"ledger_id": row_id})
        elif status == "needs_review":
            add_event(db, booking, "hold_request_refused" if hold else "charge_request_refused", actor=actor,
                      amount_cents=cents,
                      note=f"{label}: Stripe refused the request itself, not the card ({message or code}). "
                           "Nothing was taken. Parked for the owner.",
                      data={"ledger_id": row_id, "code": decline})
        else:
            add_event(db, booking, "hold_failed" if hold else "charge_failed", actor=actor,
                      amount_cents=cents, note=f"{label}: {message or code}",
                      data={"ledger_id": row_id, "code": code, "decline_code": decline})
    db.commit()
    ok = status in ("succeeded", "authorized")
    out_status = "error" if status == "pending" else status
    return PayResult(ok, out_status, amount_cents=cents if ok else 0, code=code, message=message,
                     fresh=fresh, charge_id=row_id)


def charge_saved_card(
    db: Session, booking: ConsultBooking, cents: int, reason: str, *, actor: str = "system",
) -> PayResult:
    """Take `cents` now, off-session, from the card saved on `booking`.

    Idempotent on (booking, reason): once it has succeeded, calling it again
    returns the same success without reaching Stripe. A decline or a card
    that needs authentication comes back as ok=False with `code` set
    ('card_declined', 'authentication_required', ...); it is never raised.
    """
    return _take(db, booking, cents, reason, actor=actor, hold=False)


def place_hold(db: Session, booking: ConsultBooking, *, actor: str = "system") -> PayResult:
    """Authorize the booked amount on the saved card without capturing it.

    For a confirmed booking with no outcome yet. One hold per booking: a
    second call returns the first. After a failed hold a new call tries
    again (W1b calls it once the client has replaced the card).
    """
    booking = lock_booking(db, booking.id)
    if booking is None or booking.status != "confirmed" or booking.settlement:
        db.commit()
        return PayResult(False, "error", code="not_open", message="This booking is not waiting for a hold.")
    db.commit()
    return _take(db, booking, booking.total_cents, "hold", actor=actor, hold=True)


# -----------------------------------------------------------------------------
# The hold: capture, release
# -----------------------------------------------------------------------------

def _hold_row(db: Session, booking_id: int, states: tuple[str, ...]) -> ConsultCharge | None:
    rows = [r for r in ledger(db, booking_id) if r.kind == "hold" and r.status in states]
    return rows[-1] if rows else None


def _capture_hold(
    db: Session, booking: ConsultBooking, cents: int, reason: str, *, actor: str,
) -> PayResult:
    """Capture `cents` of the authorization; Stripe lets the rest go.

    status 'hold_lost' means the authorization no longer exists (it expired
    or was cancelled at Stripe): the caller charges the card directly.
    """
    booking = lock_booking(db, booking.id)
    if booking is None:
        return PayResult(False, "error", code="no_booking", message="The booking no longer exists.")
    everything = ledger(db, booking.id)
    holds = [r for r in everything if r.kind == "hold"]
    row = next((r for r in reversed(holds) if r.status in ("authorized", "capturing")), None)
    if row is None or not row.stripe_payment_intent_id:
        # Not there to capture. If that is because another request captured
        # it a moment ago (collect lets go of the lock before it calls
        # here), the money has been taken: say so. 'hold_lost' would send
        # the caller on to charge the card directly, a second time.
        taken = next((r for r in reversed(holds) if r.status == "captured"), None)
        db.commit()
        if taken is not None:
            return PayResult(True, "captured", amount_cents=taken.captured_cents, charge_id=taken.id)
        return PayResult(False, "hold_lost", code="hold_lost")
    if row.status == "authorized":
        # A new capture (not the end of one already on its way to Stripe):
        # only for the decision in force now, and never above what it owes.
        refusal = _not_owed(booking, cents, reason, everything)
        if refusal is not None:
            db.commit()
            return refusal
    try:
        stripe = _stripe()
        _, _, stripe_error = _errors()
    except Exception:  # noqa: BLE001
        db.commit()
        return PayResult(False, "error", code="stripe_unavailable", message="Payments are not available right now.")
    resumed = row.status == "capturing"
    if resumed:
        cents = row.capture_requested_cents or cents  # finish what was started
    if cents > row.amount_cents:
        db.commit()
        return PayResult(False, "error", code="exceeds_hold",
                         message="The amount is larger than the hold on the card.")
    row.status, row.capture_requested_cents, row.capture_reason = "capturing", cents, reason[:48]
    row_id, pi_id, key, booking_id = row.id, row.stripe_payment_intent_id, row.idempotency_key, booking.id
    db.commit()

    captured: int | None = None
    lost = False
    # Did Stripe say, for certain, that THIS request's capture was not made?
    # Only then may the row go back to 'authorized'. An error that leaves it
    # open (no connection, a 5xx, a 409 because the same key is already in
    # flight) does not say so: another request's capture, or this one's own,
    # may still complete a moment after Stripe was asked where it stands.
    refused = False
    try:
        if resumed:
            # The first answer was lost: ask what happened before asking again.
            pi = stripe.PaymentIntent.retrieve(pi_id)
            if str(_g(pi, "status", "")) == "requires_capture":
                pi = stripe.PaymentIntent.capture(
                    pi_id, amount_to_capture=cents, idempotency_key=f"{key}:capture:{cents}")
        else:
            pi = stripe.PaymentIntent.capture(
                pi_id, amount_to_capture=cents, idempotency_key=f"{key}:capture:{cents}")
        state = str(_g(pi, "status", ""))
        if state == "succeeded":
            captured = int(_g(pi, "amount_received", cents) or cents)
        elif state == "canceled":
            lost = True
    except stripe_error as exc:
        log.warning("Capture of %s failed (%s); asking Stripe where it stands", pi_id, exc)
        refused = _refused_as_request(exc)
        try:
            pi = stripe.PaymentIntent.retrieve(pi_id)
            state = str(_g(pi, "status", ""))
            if state == "succeeded":
                captured = int(_g(pi, "amount_received", cents) or cents)
            elif state == "canceled":
                lost = True
        except Exception as again:  # noqa: BLE001 — still unknown: stay 'capturing'
            log.error("Could not read PaymentIntent %s after a failed capture: %s", pi_id, again)
            return PayResult(False, "error", code="stripe_error", charge_id=row_id,
                             message="Stripe could not be reached. Nothing was changed; try again.")
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected failure capturing %s", pi_id)
        return PayResult(False, "error", code="unexpected", charge_id=row_id, message=str(exc)[:300])

    booking = lock_booking(db, booking_id)
    if captured is not None:
        # Stripe says the money was taken. That is recorded whatever state
        # the row is in by now: 'capturing', or 'authorized' if a request
        # that could not tell had put it back while this capture was still
        # on its way. A capture that is not written down here would be taken
        # a second time by the next collection (review 2, N1).
        fresh = (
            _settle_row(db, row_id, "capturing", status="captured", captured_cents=captured)
            or _settle_row(db, row_id, "authorized", status="captured", captured_cents=captured,
                           capture_requested_cents=cents, capture_reason=reason[:48])
        )
        row = _row(db, row_id)
        if row.status != "captured":
            # No state this code knows leads here. The booking is not marked
            # as captured for money the ledger does not show.
            log.error("Stripe captured %s cents on %s but ledger row %s is '%s'", captured, pi_id, row_id, row.status)
            add_event(db, booking, "capture_unrecorded", actor="auto", amount_cents=captured,
                      note=f"Stripe shows this hold as captured, but its ledger line is '{row.status}'. "
                           "Check the payment in Stripe.",
                      data={"ledger_id": row_id})
            db.commit()
            return PayResult(False, "error", code="unrecorded", charge_id=row_id,
                             message="Stripe shows the hold as captured, but it could not be recorded. "
                                     "Check the payment in Stripe before doing anything else.")
        captured = row.captured_cents
        booking.hold_state = "captured"
        recompute(db, booking)
        if fresh:
            add_event(db, booking, "charge_succeeded", actor=actor, amount_cents=captured,
                      note=f"{REASON_LABEL.get(reason, reason)}, captured from the hold",
                      data={"ledger_id": row_id})
        db.commit()
        return PayResult(True, "captured", amount_cents=captured, fresh=fresh, charge_id=row_id)
    if lost:
        if _settle_row(db, row_id, "capturing", status="released") or _settle_row(
                db, row_id, "authorized", status="released"):
            booking.hold_state = "released"
            add_event(db, booking, "hold_lost", actor="stripe",
                      note="The authorization was no longer there when it was captured.",
                      data={"ledger_id": row_id})
        db.commit()
        return PayResult(False, "hold_lost", code="hold_lost", charge_id=row_id)
    if refused and not resumed:
        # Stripe refused this request's capture outright and still shows the
        # authorization: it was not made, and this request is the one that
        # marked the row, so it may put it back.
        _settle_row(db, row_id, "capturing", status="authorized", capture_requested_cents=0)
        db.commit()
        return PayResult(False, "error", code="capture_failed", charge_id=row_id,
                         message="The hold could not be captured. Nothing was changed; try again.")
    # Not known. The row stays 'capturing': the next call asks Stripe where
    # the payment stands before it asks for anything, and nothing else
    # (another outcome, a direct charge) can start meanwhile.
    db.commit()
    return PayResult(False, "error", code="capture_unconfirmed", charge_id=row_id,
                     message="Stripe has not confirmed the capture yet. Nothing was charged twice; "
                             "it is asked again within a few minutes.")


def release_hold(db: Session, booking: ConsultBooking, *, actor: str = "system") -> bool:
    """Let go of an authorization that will not be captured. True when the
    booking holds nothing afterwards. Never raises."""
    booking = lock_booking(db, booking.id)
    if booking is None:
        return True
    row = _hold_row(db, booking.id, ("authorized",))
    if row is None or not row.stripe_payment_intent_id:
        db.commit()
        return True
    try:
        stripe = _stripe()
        _, _, stripe_error = _errors()
    except Exception:  # noqa: BLE001
        db.commit()
        return False
    row_id, pi_id, key, booking_id = row.id, row.stripe_payment_intent_id, row.idempotency_key, booking.id
    db.commit()
    released = False
    try:
        pi = stripe.PaymentIntent.cancel(pi_id, idempotency_key=f"{key}:cancel")
        released = str(_g(pi, "status", "canceled")) == "canceled"
    except stripe_error as exc:
        try:
            released = str(_g(stripe.PaymentIntent.retrieve(pi_id), "status", "")) == "canceled"
        except Exception:  # noqa: BLE001
            released = False
        if not released:
            log.error("Could not release hold %s on booking %s: %s", pi_id, booking_id, exc)
    except Exception:  # noqa: BLE001
        log.exception("Unexpected failure releasing hold %s", pi_id)
    booking = lock_booking(db, booking_id)
    if released:
        if _settle_row(db, row_id, "authorized", status="released"):
            booking.hold_state = "released"
            add_event(db, booking, "hold_released", actor=actor, amount_cents=_row(db, row_id).amount_cents,
                      data={"ledger_id": row_id})
    elif _row(db, row_id).status == "authorized":
        add_event(db, booking, "hold_release_failed", actor=actor, amount_cents=_row(db, row_id).amount_cents,
                  note="Stripe did not confirm the release. The authorization lapses by itself within days.",
                  data={"ledger_id": row_id})
    db.commit()
    return released


# A hold attempt with no answer is given this long before "Stripe has no
# such payment" is believed (the request may still be on its way).
LOST_HOLD_SETTLES_AFTER = timedelta(minutes=10)


def lost_hold_rows(db: Session, booking_id: int) -> list[ConsultCharge]:
    """Hold attempts with no settled outcome: no answer came ('pending'),
    or the attempt was parked for the owner (the answer was lost for good,
    or Stripe refused the request). An authorization found captured by hand
    is not among them: only a person can put that right."""
    return [
        r for r in ledger(db, booking_id)
        if r.kind == "hold" and (
            r.status == "pending" or (r.status == "needs_review" and r.error_code != "captured_elsewhere")
        )
    ]


def settle_lost_holds(db: Session, booking: ConsultBooking, *, actor: str = "system") -> str:
    """For a booking that no longer wants a hold (cancelled, or its outcome
    decided): find every hold attempt whose answer was lost, and make sure
    nothing stays authorized on the client's card.

    Stripe is asked for the booking's payments; the attempt's own (it
    carries the ledger row's id) is cancelled if it is an authorization, and
    the row is closed. Returns 'released' (an authorization was found and
    let go), 'cleared' (Stripe has nothing for it), 'waiting' (too soon to
    tell, or Stripe is still processing), 'parked' (Stripe could not be
    asked, or would not confirm the release, for PENDING_REVIEW_AFTER: the
    row is now 'needs_review' and the caller tells the owner), 'open'
    (same, not yet that long), 'kept' (the authorization was captured in
    Stripe by hand: only a person can put that right) or 'closed' (nothing
    to do). No money is taken by this."""
    booking = lock_booking(db, booking.id)
    if booking is None:
        return "closed"
    if booking.status == "confirmed" and not booking.settlement:
        db.commit()
        return "closed"  # still wanted: place_hold asks about it with the same key
    rows = lost_hold_rows(db, booking.id)
    if not rows:
        db.commit()
        return "closed"
    try:
        stripe = _stripe()
    except Exception:  # noqa: BLE001
        db.commit()
        return "open"
    now = utcnow()
    todo = [(r.id, r.status, r.idempotency_key, r.amount_cents, now - aware(r.created_at)) for r in rows]
    booking_id, ref, customer = booking.id, booking.ref, booking.stripe_customer_id
    db.commit()  # no database lock is held across the calls to Stripe

    try:
        payments = _stripe_payments(stripe, customer) if customer else []
        asked = True
    except Exception as exc:  # noqa: BLE001
        log.error("Stripe could not list the payments of %s to look for a lost hold: %s", ref, exc)
        payments, asked = [], False

    results: list[str] = []
    for row_id, was, key, amount, age in todo:
        old = age >= PENDING_REVIEW_AFTER
        mine = [p for p in payments if str(_g(_g(p, "metadata"), "ledger_id", "") or "") == str(row_id)]
        states = [str(_g(p, "status", "")) for p in mine]
        verdict, values, event, note = "", {}, "", ""
        if not asked:
            verdict = "parked" if old else "open"
        elif any(st == "succeeded" and int(_g(p, "amount_received", 0) or 0) > 0 for p, st in zip(mine, states)):
            verdict = "kept"
            values = dict(status="needs_review", error_code="captured_elsewhere",
                          error_message="Stripe shows this hold was captured there by hand. Refund it in Stripe if it should not have been taken.")
            event, note = "hold_needs_review", values["error_message"]
        elif "processing" in states:
            verdict = "parked" if old else "waiting"
        elif "requires_capture" in states:
            released = True
            pi_id = ""
            for p, st in zip(mine, states):
                if st != "requires_capture":
                    continue
                pi_id = str(_g(p, "id", "") or "")
                try:
                    answer = stripe.PaymentIntent.cancel(pi_id, idempotency_key=f"{key}:cancel")
                    released = released and str(_g(answer, "status", "canceled")) == "canceled"
                except Exception as exc:  # noqa: BLE001
                    try:
                        released = released and str(_g(stripe.PaymentIntent.retrieve(pi_id), "status", "")) == "canceled"
                    except Exception:  # noqa: BLE001
                        released = False
                    if not released:
                        log.error("Could not release the lost hold %s of %s: %s", pi_id, ref, exc)
            if released:
                verdict = "released"
                values = dict(status="released", stripe_payment_intent_id=pi_id, error_code="", error_message="")
                event = "hold_released"
                note = "Its answer from Stripe had been lost; it was found there and let go."
            else:
                verdict = "parked" if old else "open"
        elif age < LOST_HOLD_SETTLES_AFTER:
            verdict = "waiting"
        else:
            verdict = "cleared"
            values = dict(status="failed", error_code="never_placed",
                          error_message="Stripe has no authorization for this attempt: nothing is on the card.")
            event, note = "hold_not_placed", "Its answer had been lost; Stripe has no authorization for it."
        if verdict == "parked" and was == "pending":
            values = dict(status="needs_review", error_code="release_unconfirmed", error_message=(
                "No answer was recorded for this hold, and Stripe could not confirm that nothing is "
                "authorized on the card."))
            event, note = "hold_needs_review", values["error_message"]
        if values:
            booking = lock_booking(db, booking_id)
            if _settle_row(db, row_id, was, **values) and event:
                add_event(db, booking, event, actor=actor, amount_cents=amount, note=note,
                          data={"ledger_id": row_id})
            db.commit()
        results.append(verdict)
    for word in ("parked", "kept", "open", "waiting", "released", "cleared"):
        if word in results:
            return word
    return "closed"


# -----------------------------------------------------------------------------
# Collecting what a decided outcome says is owed
# -----------------------------------------------------------------------------

def collect(db: Session, booking: ConsultBooking, *, actor: str = "system") -> PayResult:
    """Take booking.amount_due_cents (less what was already taken) for the
    outcome in booking.settlement: captured from the hold when one is
    authorized, charged to the saved card otherwise. With nothing owed, any
    hold is released. Updates charge_state / charge_error. Safe to repeat.
    """
    booking = lock_booking(db, booking.id)
    if booking is None:
        return PayResult(False, "error", code="no_booking")
    recompute(db, booking)
    outstanding = (booking.amount_due_cents or 0) - (booking.charged_cents or 0)
    booking_id = booking.id
    if outstanding <= 0:
        booking.charge_state = "paid" if (booking.amount_due_cents or 0) > 0 else ""
        booking.charge_error = ""
        db.commit()
        release_hold(db, booking, actor=actor)
        return PayResult(True, "noop")
    reason = SETTLEMENT_REASON.get(booking.settlement or "")
    if reason is None:
        db.commit()
        return PayResult(False, "error", code="no_outcome", message="No outcome has been decided for this booking.")
    has_hold = booking.hold_state == "authorized" or _hold_row(db, booking.id, ("capturing",)) is not None
    booking.charge_state = "pending"
    db.commit()

    result: PayResult | None = None
    if has_hold:
        result = _capture_hold(db, booking, outstanding, reason, actor=actor)
        if result.status == "hold_lost":
            result = None
    if result is None:
        result = charge_saved_card(db, booking, outstanding, reason, actor=actor)

    booking = lock_booking(db, booking_id)
    recompute(db, booking)
    if (booking.amount_due_cents or 0) - (booking.charged_cents or 0) <= 0:
        booking.charge_state, booking.charge_error = "paid", ""
    elif result.status == "needs_review" or result.code == "unrecorded":
        # Parked for the owner: an answer that never came, or a request
        # Stripe refused. Not 'failed': that word means the card was refused
        # and shows the client a card problem. 'unrecorded' (Stripe took a
        # capture the ledger could not take) is parked too: left 'pending',
        # the next tick would collect again and, finding no hold it can
        # capture, charge the card on top of that capture (review 3, R2).
        booking.charge_state = "review"
        booking.charge_error = (result.message or result.code)[:300]
    elif result.status in ("failed", "requires_action"):
        booking.charge_state = "requires_action" if result.status == "requires_action" else "failed"
        booking.charge_error = (result.message or result.code)[:300]
    else:
        booking.charge_state = "pending"  # unknown yet: the next call asks again
        booking.charge_error = (result.message or result.code)[:300]
    db.commit()
    return result


# -----------------------------------------------------------------------------
# Refunds
# -----------------------------------------------------------------------------

def refundable_cents(booking: ConsultBooking) -> int:
    """What can still be sent back from here: charged, less refunds, less
    anything a dispute holds or has taken (Stripe has already withdrawn that
    money; it is not ours to refund)."""
    return max(
        (booking.charged_cents or 0) - (booking.refunded_cents or 0) - (booking.disputed_cents or 0), 0)


def _stripe_refunds(stripe, payment_intent: str) -> list:
    """Every refund Stripe has on this payment."""
    out: list = []
    after = ""
    for _ in range(10):
        page = stripe.Refund.list(
            payment_intent=payment_intent, limit=100, **({"starting_after": after} if after else {}))
        data = list(_g(page, "data", []) or [])
        out += data
        if not data or not _g(page, "has_more", False):
            break
        after = str(_g(data[-1], "id", "") or "")
    return out


def _refund_verdict(answer) -> tuple[str, str, str, str]:
    """(our status, refund id, code, message) for a refund as Stripe shows it."""
    state = str(_g(answer, "status", "") or "succeeded")
    refund_id = str(_g(answer, "id", "") or "")
    if state == "succeeded":
        return "succeeded", refund_id, "", ""
    if state in ("pending", "requires_action"):
        # Accepted, not completed: it can still fail. Not recorded as money
        # returned until Stripe says so; the tick asks again.
        return "pending", refund_id, "refund_pending", f"Stripe reports this refund as {state}: it is not completed yet."
    return "failed", refund_id, state[:64], f"Stripe reported the refund as {state}. Nothing was returned to the card."


def _send_refund(stripe, ref: str, row_id: int, pi_id: str, amount: int, key: str) -> tuple[str, str, str, str]:
    """Ask Stripe for the refund of one ledger row. Never raises."""
    _, _, stripe_error = _errors()
    try:
        return _refund_verdict(stripe.Refund.create(
            payment_intent=pi_id, amount=amount, reason="requested_by_customer",
            metadata={"kind": "consult", "booking_ref": ref, "ledger_id": str(row_id)},
            idempotency_key=key,
        ))
    except stripe_error as exc:
        if _refused_as_request(exc):
            return ("failed", "", str(getattr(exc, "code", "") or "invalid_request"),
                    str(getattr(exc, "user_message", None) or exc)[:300])
        log.error("Refund %s for %s got no answer: %s", key, ref, exc)
        return "pending", "", "stripe_error", "Stripe could not be reached."
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected failure refunding %s", key)
        return "pending", "", "unexpected", str(exc)[:300]


def _record_refunds(
    db: Session, booking_id: int, outcomes: dict[int, tuple[str, str, str, str, str]], *, actor: str,
    found_later: bool = False,
) -> PayResult:
    """Write what was learned about each refund row: {row id: (status it
    had, new status, refund id, code, message)}. One caller moves a row.
    `found_later`: this is not the request that asked for the refund but a
    later look at Stripe (see _repeat_of_found_refund)."""
    booking = lock_booking(db, booking_id)
    done, fresh, parked = 0, False, False
    problem = ("", "")
    for row_id, (was, state, refund_id, code, message) in outcomes.items():
        values = dict(status=state, stripe_refund_id=refund_id[:64],
                      error_code=code[:64], error_message=message[:300])
        if state == "succeeded":
            # Stripe made it: written down whatever the row was moved to meanwhile.
            moved = _record_success(db, row_id, was, **values)
        else:
            moved = state != was and _settle_row(db, row_id, was, **values)
        if state == was and refund_id:
            db.execute(update(ConsultCharge).where(
                ConsultCharge.id == row_id, ConsultCharge.status == was, ConsultCharge.stripe_refund_id == "",
            ).values(stripe_refund_id=refund_id[:64]))
        row = _row(db, row_id)
        if moved and state == "succeeded":
            fresh = True
            add_event(db, booking, "refunded", actor=row.actor or actor, amount_cents=row.amount_cents,
                      note=row.note, data={"ledger_id": row_id, "group": row.attempt, "found_later": found_later})
        elif moved and state == "failed":
            fresh = True
            add_event(db, booking, "refund_failed", actor=actor, amount_cents=row.amount_cents,
                      note=message or code, data={"ledger_id": row_id})
        elif moved and state == "needs_review":
            parked = True
            add_event(db, booking, "refund_needs_review", actor=actor, amount_cents=row.amount_cents,
                      note=message or code, data={"ledger_id": row_id})
        if row.status == "succeeded":
            done += row.amount_cents
        elif not problem[0]:
            problem = (code or row.error_code, message or row.error_message)
    recompute(db, booking)
    db.commit()
    if problem[0]:
        states = {_row(db, row_id).status for row_id in outcomes}
        db.commit()
        status = "needs_review" if "needs_review" in states else "error" if "pending" in states else "failed"
        return PayResult(False, status, amount_cents=done, code=problem[0], message=problem[1], fresh=fresh or parked)
    return PayResult(True, "succeeded", amount_cents=done, fresh=fresh)


def open_refunds(db: Session, booking_id: int) -> list[ConsultCharge]:
    """Refund rows whose outcome is not recorded: asked for, answer unknown."""
    return [r for r in ledger(db, booking_id) if r.kind == "refund" and r.status in ("pending", "needs_review")]


def finish_refunds(
    db: Session, booking: ConsultBooking, *, actor: str = "system", found_later: bool = False,
) -> PayResult | None:
    """Settle this booking's refunds that have no recorded outcome, by
    asking Stripe what it has for that payment. None when there are none.

    A refund's answer can be lost after Stripe has made it. Sending the
    request again is only safe while Stripe still remembers the idempotency
    key (about a day): after that the same key makes a second refund. So:

      * Stripe is asked first for the refunds on the payment; a refund
        carries its ledger row's id, so ours is recognised and recorded.
      * Not there, and the row is younger than PENDING_REVIEW_AFTER: the
        request is repeated with the same key (it either never arrived, or
        Stripe answers with the refund it already made).
      * Not there, and older: nothing is sent. Once IN_FLIGHT_MARGIN more
        has passed (a request sent just before the limit may still be on its
        way) it was never made: the row is closed as failed. A new refund is
        a new decision. A refund Stripe reports later all the same is still
        recorded (_record_success).
      * Stripe cannot be asked: nothing is sent. Past the time limit the row
        is parked ('needs_review') so the owner is told; it is still asked
        about on every later call and settles when Stripe answers."""
    booking = lock_booking(db, booking.id)
    if booking is None:
        return None
    rows = open_refunds(db, booking.id)
    if not rows:
        db.commit()
        return None
    try:
        stripe = _stripe()
    except Exception:  # noqa: BLE001
        db.commit()
        return PayResult(False, "error", code="stripe_unavailable", message="Payments are not available right now.")
    now = utcnow()
    todo = [(r.id, r.status, r.stripe_payment_intent_id, r.amount_cents, r.idempotency_key,
             now - aware(r.created_at) >= PENDING_REVIEW_AFTER,
             now - aware(r.created_at) >= PENDING_REVIEW_AFTER + IN_FLIGHT_MARGIN) for r in rows]
    booking_id, ref = booking.id, booking.ref
    db.commit()  # no database lock is held across the calls to Stripe

    listed: dict[str, list | None] = {}
    outcomes: dict[int, tuple[str, str, str, str, str]] = {}
    for row_id, was, pi_id, amount, key, old, long_old in todo:
        if pi_id not in listed:
            try:
                listed[pi_id] = _stripe_refunds(stripe, pi_id)
            except Exception as exc:  # noqa: BLE001 — no answer: send nothing
                log.error("Stripe could not list the refunds on %s for %s: %s", pi_id, ref, exc)
                listed[pi_id] = None
        refunds = listed[pi_id]
        if refunds is None:
            outcomes[row_id] = (was, "needs_review" if old else was, "", "stripe_error", (
                "Stripe could not be asked whether this refund was made. No new refund is sent until it answers."
                if old else "Stripe could not be reached."
            ))
            continue
        mine = [x for x in refunds if str(_g(_g(x, "metadata"), "ledger_id", "") or "") == str(row_id)]
        if mine:
            state, refund_id, code, message = _refund_verdict(mine[0])
            if state == "pending" and old:
                state = "needs_review"
            elif state == "pending":
                state = was
            outcomes[row_id] = (was, state, refund_id, code, message)
        elif old and not long_old:
            # Too old to send again, and a request sent just before that
            # moment may still be on its way: neither sent nor closed yet.
            outcomes[row_id] = (was, was, "", "stripe_wait", "Stripe has no such refund yet. It is asked again shortly.")
        elif old:
            outcomes[row_id] = (was, "failed", "", "not_made", (
                "Stripe has no such refund: the request never reached it. Nothing was returned to the card."))
        else:
            state, refund_id, code, message = _send_refund(stripe, ref, row_id, pi_id, amount, key)
            outcomes[row_id] = (was, was if state == "pending" else state, refund_id, code, message)
    return _record_refunds(db, booking_id, outcomes, actor=actor, found_later=found_later)


def _repeat_of_found_refund(db: Session, booking: ConsultBooking, cents: int, actor: str) -> PayResult | None:
    """The owner asked for a refund, was told "Stripe could not be reached",
    and the tick later found that Stripe had made it. If he now asks for
    the same amount again, that is most likely the same refund asked for a
    second time: once, it is answered with what happened and nothing is
    sent. Asking again after that is a new refund."""
    events = db.execute(
        select(ConsultBookingEvent.kind, ConsultBookingEvent.data, ConsultBookingEvent.amount_cents).where(
            ConsultBookingEvent.booking_id == booking.id,
            ConsultBookingEvent.kind.in_(("refunded", "refund_repeat_answered")),
        ).order_by(ConsultBookingEvent.id)
    ).all()
    answered = {(d or {}).get("group") for kind, d, _ in events if kind == "refund_repeat_answered"}
    found: dict[int, int] = defaultdict(int)
    for kind, data, amount in events:
        if kind == "refunded" and (data or {}).get("found_later") and (data or {}).get("group") not in answered:
            found[int((data or {}).get("group") or 0)] += int(amount or 0)
    group = next((g for g, total in found.items() if total == cents), None)
    if group is None:
        return None
    add_event(db, booking, "refund_repeat_answered", actor=actor, amount_cents=cents, data={"group": group},
              note="The same refund was asked for again; it had already been made. Nothing was sent.")
    db.commit()
    return PayResult(
        True, "noop", amount_cents=cents,
        message=f"This refund of {_dollars(cents)} was already made: its answer from Stripe had been lost and "
                "was found later. Nothing new was sent. To refund a further amount, press Refund again.",
    )


def refund(
    db: Session, booking: ConsultBooking, cents: int, *, actor: str, note: str = "",
) -> PayResult:
    """Send `cents` back to the card, against what this booking was charged.

    Nothing new is sent while an earlier refund has no recorded outcome (see
    finish_refunds). Asked again for the same amount, that earlier refund is
    finished and its result returned; asked for another amount, the press is
    refused with a sentence ('refund_unresolved'), never answered with the
    earlier refund's result. The same amount asked again inside
    REFUND_REPLAY_WINDOW is treated as a repeat of the click, not a second
    refund.
    """
    cents = int(cents or 0)
    now = utcnow()
    booking = lock_booking(db, booking.id)
    if booking is None:
        return PayResult(False, "error", code="no_booking")
    recompute(db, booking)
    rows = ledger(db, booking.id)
    refunds = [r for r in rows if r.kind == "refund"]
    unresolved = [r for r in refunds if r.status in ("pending", "needs_review")]
    if unresolved:
        earlier = sum(r.amount_cents for r in unresolved)
        db.commit()
        if cents <= 0:
            return PayResult(False, "error", code="invalid_amount", message="Enter an amount to refund.")
        if cents != earlier:
            # A different amount is a different refund. It is neither made
            # nor answered with the earlier one's result (which would read
            # as "done" for an amount that was not sent).
            return PayResult(
                False, "error", code="refund_unresolved",
                message=f"A refund of {_dollars(earlier)} asked for earlier has no answer from Stripe yet, so "
                        f"nothing new was sent. It is checked again within a few minutes. Refund "
                        f"{_dollars(cents)} once that one shows as refunded or as not made.",
            )
        return finish_refunds(db, booking, actor=actor) or PayResult(True, "noop")
    try:
        stripe = _stripe()
    except Exception:  # noqa: BLE001
        db.commit()
        return PayResult(False, "error", code="stripe_unavailable", message="Payments are not available right now.")

    recent = [
        r for r in refunds
        if r.status == "succeeded" and now - aware(r.created_at) <= REFUND_REPLAY_WINDOW
    ]
    groups: dict[int, int] = defaultdict(int)
    for r in recent:
        groups[r.attempt] += r.amount_cents
    if cents > 0 and cents in groups.values():
        db.commit()
        return PayResult(True, "noop", amount_cents=cents, message="This refund was already made a moment ago.")
    repeat = _repeat_of_found_refund(db, booking, cents, actor) if cents > 0 else None
    if repeat is not None:
        return repeat
    available = refundable_cents(booking)
    if cents <= 0:
        db.commit()
        return PayResult(False, "error", code="invalid_amount", message="Enter an amount to refund.")
    if cents > available:
        held = min(booking.disputed_cents or 0, (booking.charged_cents or 0) - (booking.refunded_cents or 0))
        db.commit()
        return PayResult(
            False, "error", code="invalid_amount",
            message=f"At most ${available / 100:,.2f} can be refunded on this booking." + (
                f" ${held / 100:,.2f} is held by, or was lost to, a dispute at the client's bank and "
                "cannot be refunded from here." if held > 0 else ""
            ),
        )
    already = _refunded_by_payment(rows)
    group = max((r.attempt for r in refunds), default=0) + 1
    left = cents
    pending: list[ConsultCharge] = []
    for parent in reversed(rows):  # newest payment first
        if left <= 0:
            break
        room = _paid(parent) - already.get(parent.id, 0)
        if room <= 0 or not parent.stripe_payment_intent_id:
            continue
        part = min(room, left)
        left -= part
        row = ConsultCharge(
            booking_id=booking.id, kind="refund", reason="refund", attempt=group,
            idempotency_key=f"consult:{booking.ref}:refund:{group}:{parent.id}",
            amount_cents=part, currency=parent.currency, status="pending", parent_id=parent.id,
            stripe_payment_intent_id=parent.stripe_payment_intent_id, actor=actor[:320],
            note=(note or "")[:300], created_at=now,
        )
        db.add(row)
        pending.append(row)
    if left > 0:
        db.rollback()
        return PayResult(False, "error", code="invalid_amount",
                         message="That amount cannot be matched to a payment on this booking.")
    try:
        db.flush()
    except IntegrityError:
        # The same refund is being written by another request right now.
        db.rollback()
        return PayResult(False, "error", code="in_progress",
                         message="This refund is already being made. Reload the booking in a moment.")

    todo = [(r.id, r.stripe_payment_intent_id, r.amount_cents, r.idempotency_key) for r in pending]
    booking_id, ref = booking.id, booking.ref
    db.commit()

    outcomes: dict[int, tuple[str, str, str, str, str]] = {}
    for row_id, pi_id, amount, key in todo:
        outcomes[row_id] = ("pending", *_send_refund(stripe, ref, row_id, pi_id, amount, key))
    return _record_refunds(db, booking_id, outcomes, actor=actor)


# -----------------------------------------------------------------------------
# An attempt parked as 'needs_review': closed by the owner, on what Stripe shows
# -----------------------------------------------------------------------------
# A request went to Stripe, the answer never came, and the idempotency key
# has since expired, so the same request can no longer be repeated safely.
# The owner looks in Stripe and says which it was. Before anything is
# changed, Stripe is asked for this booking's payments (the booking has its
# own Stripe customer, and every payment carries its ledger row's id), and a
# statement that does not fit what Stripe shows is refused:
#
#   "it was paid"       needs a completed payment of exactly that amount for
#                       that attempt. The ledger row becomes 'succeeded'.
#   "it was not paid"   is refused while Stripe shows a payment, an
#                       authorization or a payment in progress for that
#                       attempt (trying again would take the money twice).
#                       Otherwise the row becomes 'failed', and the next
#                       Charge is a new attempt with a new key.
#
# Neither moves money.

def review_rows(db: Session, booking_id: int) -> list[ConsultCharge]:
    """The booking's attempts that are waiting for a person."""
    return [r for r in ledger(db, booking_id) if r.status == "needs_review" and r.kind in ("charge", "hold")]


def _stripe_payments(stripe, customer_id: str) -> list:
    """Every PaymentIntent on this booking's own Stripe customer."""
    out: list = []
    after = ""
    for _ in range(10):
        page = stripe.PaymentIntent.list(customer=customer_id, limit=100, **({"starting_after": after} if after else {}))
        data = list(_g(page, "data", []) or [])
        out += data
        if not data or not _g(page, "has_more", False):
            break
        after = str(_g(data[-1], "id", "") or "")
    return out


def _dollars(cents: int) -> str:
    return f"${int(cents) / 100:,.2f}"


def resolve_review(
    db: Session, booking: ConsultBooking, outcome: str, *, actor: str,
    cents: int | None = None, charge_id: int | None = None,
) -> PayResult:
    """Close the booking's parked attempt. outcome: 'settled' (Stripe shows
    it was paid; `cents` is the amount the owner read there) or
    'not_charged' (Stripe shows nothing was taken; it may be tried again).

    Returns status 'refused' with words fit to show when the statement does
    not fit what Stripe shows or there is nothing to resolve, 'error' when
    Stripe could not be asked (nothing changed), 'succeeded' / 'noop' when
    done. Safe to repeat: the row leaves 'needs_review' exactly once."""
    def refused(code: str, message: str, row_id: int | None = None) -> PayResult:
        return PayResult(False, "refused", code=code, message=message, charge_id=row_id)

    if outcome not in ("settled", "not_charged"):
        return refused("unknown", "Unknown review action.")
    booking = lock_booking(db, booking.id)
    if booking is None:
        return refused("no_booking", "The booking no longer exists.")
    rows = review_rows(db, booking.id)
    if charge_id is not None:
        rows = [r for r in rows if r.id == charge_id]
    if not rows:
        db.commit()
        return refused("nothing_to_review", "Nothing on this booking is waiting to be checked in Stripe.")
    if len(rows) > 1:
        db.commit()
        return refused("choose", "More than one payment attempt on this booking is waiting to be checked. "
                                 "Say which one (charge_id).")
    row = rows[0]
    row_id, kind, reason, amount = row.id, row.kind, row.reason, int(row.amount_cents)
    label = REASON_LABEL.get(reason, reason)
    if outcome == "settled":
        if kind == "hold":
            db.commit()
            return refused("is_hold", (
                "This attempt was a hold, not a charge. A hold takes no money, so it cannot be marked as "
                "paid. If Stripe shows an authorization for it, cancel it there, then mark this as not charged."
            ), row_id)
        if int(cents or 0) != amount:
            db.commit()
            return refused("invalid_amount", (
                f"This attempt was for {_dollars(amount)}. Enter the amount Stripe shows for it; if Stripe "
                "shows a different amount, do not mark it here."
            ), row_id)
    try:
        stripe = _stripe()
    except Exception as exc:  # noqa: BLE001 — not configured, or the SDK is missing
        db.commit()
        log.error("Stripe is unavailable for the review of booking %s: %s", booking.ref, getattr(exc, "detail", exc))
        return PayResult(False, "error", code="stripe_unavailable", charge_id=row_id,
                         message="Payments are not available right now.")
    booking_id, ref, customer = booking.id, booking.ref, booking.stripe_customer_id
    db.commit()  # no database lock is held across the call to Stripe

    try:
        payments = _stripe_payments(stripe, customer) if customer else []
    except Exception as exc:  # noqa: BLE001 — no answer: change nothing
        log.error("Stripe could not list the payments of %s for a review: %s", ref, exc)
        return PayResult(False, "error", code="stripe_error", charge_id=row_id,
                         message="Stripe could not be reached to check this payment. Nothing was changed; try again.")
    mine = [p for p in payments if str(_g(_g(p, "metadata"), "ledger_id", "") or "") == str(row_id)]
    paid = [p for p in mine if str(_g(p, "status", "")) == "succeeded" and int(_g(p, "amount_received", 0) or 0) > 0]
    authorized = [p for p in mine if str(_g(p, "status", "")) == "requires_capture"]
    processing = [p for p in mine if str(_g(p, "status", "")) == "processing"]

    if outcome == "settled":
        match = next((p for p in paid if int(_g(p, "amount_received", 0) or 0) == amount), None)
        if match is None:
            if processing:
                return refused("processing", "Stripe is still processing this payment. Look again later.", row_id)
            return refused("not_found_at_stripe", (
                f"Stripe shows no completed payment of {_dollars(amount)} for this attempt, so it was not "
                "marked as paid. If Stripe shows nothing for it at all, mark it as not charged."
            ), row_id)
        pi_id = str(_g(match, "id", "") or "")
        created = _g(match, "created")
        try:
            taken_at = datetime.fromtimestamp(int(created), timezone.utc) if created else None
        except (TypeError, ValueError, OverflowError, OSError):
            taken_at = None
        booking = lock_booking(db, booking_id)
        elsewhere = [
            r for r in ledger(db, booking_id)
            if r.id != row_id and r.kind in ("charge", "hold") and r.stripe_payment_intent_id == pi_id
        ]
        if elsewhere:
            db.commit()
            return refused("already_recorded", "That payment is already recorded on this booking.", row_id)
        moved = _settle_row(
            db, row_id, "needs_review", status="succeeded", stripe_payment_intent_id=pi_id,
            error_code="", error_message="",
        )
        recompute(db, booking)
        if moved:
            due = booking.amount_due_cents or 0
            if due > 0 and due - (booking.charged_cents or 0) <= 0:
                booking.charge_state, booking.charge_error = "paid", ""
            add_event(
                db, booking, "review_settled", actor=actor, amount_cents=amount,
                note=f"{label}: Stripe shows it was paid ({pi_id}). Marked as paid; no money was moved.",
                data={"ledger_id": row_id, "payment_intent": pi_id},
            )
        db.commit()
        return PayResult(True, "succeeded", amount_cents=amount, fresh=moved, charge_id=row_id, at=taken_at,
                         message=f"Marked as paid: Stripe shows {_dollars(amount)} for this attempt.")

    # outcome == "not_charged"
    if paid:
        p = paid[0]
        taken = f"{_g(p, 'id', '')}, {_dollars(int(_g(p, 'amount_received', 0) or 0))}"
        if kind == "hold":
            # Only a capture made by hand in Stripe gets a parked hold here.
            return refused("paid_at_stripe", (
                f"Stripe shows this hold was captured there ({taken}), which this site did not do, so the "
                "client has paid that amount outside this booking. Nothing was changed here. If it should "
                "not have been taken, refund it in Stripe."
            ), row_id)
        return refused("paid_at_stripe", (
            f"Stripe shows this payment went through ({taken}). Mark it as paid instead: charging again "
            "would take the money twice."
        ), row_id)
    if processing:
        return refused("processing", "Stripe is still processing this payment. Look again later.", row_id)
    if authorized:
        p = authorized[0]
        return refused("authorized_at_stripe", (
            f"Stripe shows an authorization of {_dollars(int(_g(p, 'amount', 0) or 0))} on the card "
            f"({_g(p, 'id', '')}). Cancel it in Stripe first, then mark this as not charged."
        ), row_id)
    booking = lock_booking(db, booking_id)
    moved = _settle_row(
        db, row_id, "needs_review", status="failed", error_code="review_not_charged",
        error_message="Checked in Stripe: this attempt took no money.",
    )
    if moved:
        if kind == "charge":
            recompute(db, booking)
            if (booking.amount_due_cents or 0) - (booking.charged_cents or 0) > 0:
                # 'open': owed, nothing in flight, and not a refused card
                # (the client's page shows no card problem for it).
                booking.charge_state = "open"
                booking.charge_error = "An earlier attempt took no money (checked in Stripe). Charge can be tried again."
        add_event(
            db, booking, "review_not_charged", actor=actor, amount_cents=amount,
            note=f"{label}: Stripe shows no payment for this attempt. Marked as not charged; it can be tried again.",
            data={"ledger_id": row_id},
        )
    db.commit()
    return PayResult(True, "noop", fresh=moved, charge_id=row_id,
                     message="Marked as not charged. Stripe shows no payment for this attempt; it can be tried again.")


def note_stripe_refund(db: Session, payment_intent: str, amount_refunded: int) -> bool:
    """charge.refunded webhook: Stripe's own total for a PaymentIntent of
    ours (covers a refund made in the Stripe dashboard). True when the
    PaymentIntent belongs to a consulting booking. Idempotent."""
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
    # Same lock order as everywhere else: the booking, then the ledger row.
    booking = lock_booking(db, found.booking_id)
    row = db.execute(
        select(ConsultCharge).where(ConsultCharge.id == found.id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    amount = max(int(amount_refunded or 0), 0)
    if booking is not None and amount > (row.stripe_refunded_cents or 0):
        recompute(db, booking)
        before = booking.refunded_cents or 0
        row.stripe_refunded_cents = amount
        recompute(db, booking)
        if booking.refunded_cents > before:
            add_event(db, booking, "refund_seen_at_stripe", actor="stripe",
                      amount_cents=booking.refunded_cents - before,
                      note="A refund made outside the admin panel.", data={"ledger_id": row.id})
    db.commit()
    return True
