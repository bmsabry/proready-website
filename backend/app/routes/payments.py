"""Buyer-facing payment endpoints (no auth — these are public by design).

Two product lines, two providers:

  LIVE cohort seats (registrations table)
    POST /api/payments/live/paypal/create-order   → PayPal order for a pending registration
    POST /api/payments/live/paypal/capture        → capture + mark registration paid
    POST /api/payments/live/stripe/checkout       → Stripe Checkout Session (metadata.kind='live_course';
                                                    fulfilled by the existing /api/academy/webhook/stripe)

  RECORDED academy products (academy_orders/enrollments)
    POST /api/payments/recorded/paypal/create-order
    POST /api/payments/recorded/paypal/capture    → capture + grant enrollment, exactly
                                                    like the Stripe webhook path

  GET  /api/payments/config                       → which providers are usable right now

Graceful degradation: every PayPal endpoint returns 503 'PayPal not
configured' until PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET are set, and the
config endpoint reports paypal_enabled=False — the frontend simply hides
the buttons. Stripe live-cohort checkout reuses checkout._stripe(), which
503s the same way when Stripe keys are absent.

Both capture paths are idempotent: live replays short-circuit on
(status='paid', payment_ref=order_id); recorded replays short-circuit on
the unique academy_orders.provider_ref.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as svc
from .. import paypal
from ..config import get_settings
from ..db import get_db
from ..emailer import live_bank_failed_html, payment_receipt_html, send_email
from ..emailer import settlement_failed_admin_html
from ..models import Course, Order, Product, Registration
from ..settlement import SETTLEMENT_MARGIN_BUSINESS_DAYS, add_business_days
from .admin import mark_registration_paid
from .checkout import _stripe, grant_and_welcome

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


# ----- Request bodies --------------------------------------------------------

class LiveOrderIn(BaseModel):
    registration_id: int


class LiveCaptureIn(BaseModel):
    registration_id: int
    order_id: str = Field(min_length=1, max_length=64)


class RecordedOrderIn(BaseModel):
    product_code: str = Field(min_length=1, max_length=64)
    email: EmailStr
    full_name: str = Field(default="", max_length=200)


class RecordedCaptureIn(RecordedOrderIn):
    order_id: str = Field(min_length=1, max_length=64)


# ----- Helpers ---------------------------------------------------------------

def _require_paypal() -> None:
    if not get_settings().paypal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PayPal not configured",
        )


def _load_payable(db: Session, registration_id: int) -> tuple[Registration, Course]:
    """A registration that is allowed to start an online payment."""
    reg = db.get(Registration, registration_id)
    if reg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found."
        )
    if reg.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This registration is not awaiting payment.",
        )
    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    if course is None or course.price_cents <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Online payment is not enabled for this course.",
        )
    return reg, course


def _load_live_product(db: Session, product_code: str) -> Product:
    """A recorded academy product that is allowed to be bought."""
    product = db.get(Product, product_code)
    if product is None or product.status != "live":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not available."
        )
    if product.price_cents <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This course has no price set yet.",
        )
    return product


def _capture_details(capture: dict) -> tuple[str, int, str, str]:
    """(custom_id, amount_cents, currency, capture_id) from an Orders v2
    capture response. Tolerant of missing pieces — callers fall back to the
    DB price when the amount can't be read."""
    pu = (capture.get("purchase_units") or [{}])[0]
    cap = ((pu.get("payments") or {}).get("captures") or [{}])[0]
    custom_id = str(cap.get("custom_id") or pu.get("custom_id") or "")
    amount = cap.get("amount") or pu.get("amount") or {}
    try:
        cents = int(round(float(str(amount.get("value") or "0")) * 100))
    except ValueError:
        cents = 0
    currency = str(amount.get("currency_code") or "").lower()
    capture_id = str(cap.get("id") or "")
    return custom_id, cents, currency, capture_id


def _amount_display(amount_cents: int | None, currency: str) -> str:
    if not amount_cents:
        return ""
    return f"{amount_cents // 100:,}.{amount_cents % 100:02d} {currency.upper()}"


def _recorded_custom_id(product_code: str, email: str) -> str:
    # PayPal truncates custom_id at 127 chars; build the comparison value
    # the same way so create-order and capture always agree.
    return f"product:{product_code}:{email}"[:127]


def _settle_live(
    db: Session,
    reg: Registration,
    course: Course,
    *,
    provider: str,
    ref: str,
    amount_cents: int,
) -> bool:
    """Mark a live-cohort registration paid (same side effects as admin
    mark-paid, via the shared core) and send the buyer a receipt.

    Returns True when the row transitioned; replays return False and send
    nothing, so a buyer never receives two receipts."""
    transitioned = mark_registration_paid(
        db, reg, provider=provider, payment_ref=ref, amount_cents=amount_cents
    )
    if transitioned:
        settings = get_settings()
        send_email(
            to=reg.email,
            subject=f"Payment received — {course.title}",
            html=payment_receipt_html(
                reg.full_name,
                course.title,
                _amount_display(amount_cents, course.currency),
                ref,
            ),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db,
            scope_kind="course",
            scope_code=course.code,
            audience="payer",
            template="payment_receipt",
        )
    return transitioned


# ----- Config ---------------------------------------------------------------

@router.get("/config")
def payments_config() -> dict:
    """What the payment UI may render. The PayPal client id is public by
    design (it's embedded in the JS SDK URL); the secret never leaves env."""
    settings = get_settings()
    return {
        "paypal_enabled": settings.paypal_enabled,
        "paypal_client_id": (
            settings.PAYPAL_CLIENT_ID if settings.paypal_enabled else ""
        ),
        "paypal_mode": settings.PAYPAL_MODE,
        "currency": settings.PAYPAL_CURRENCY,
        "stripe_enabled": bool(settings.STRIPE_SECRET_KEY),
    }


# ----- LIVE cohorts: PayPal --------------------------------------------------

@router.post("/live/paypal/create-order")
def live_paypal_create_order(body: LiveOrderIn, db: Session = Depends(get_db)) -> dict:
    _require_paypal()
    reg, course = _load_payable(db, body.registration_id)
    try:
        order_id = paypal.create_order(
            course.price_cents,
            course.currency,
            description=course.title,
            custom_id=f"livereg:{reg.id}",
        )
    except paypal.PayPalError as exc:
        log.error("PayPal create-order failed for registration %s: %s", reg.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start PayPal checkout. Please try again.",
        ) from exc
    return {"order_id": order_id}


@router.post("/live/paypal/capture")
def live_paypal_capture(body: LiveCaptureIn, db: Session = Depends(get_db)) -> dict:
    _require_paypal()
    reg = db.get(Registration, body.registration_id)
    if reg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found."
        )

    # Idempotent replay — the buyer double-clicked or the page refreshed
    # after a successful capture. Nothing to re-do, nothing to re-email.
    if reg.status == "paid" and reg.payment_ref == body.order_id:
        return {"ok": True, "status": "paid"}

    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course not found for this registration.",
        )

    try:
        capture = paypal.capture_order(body.order_id)
    except paypal.PayPalError as exc:
        log.error("PayPal capture failed for registration %s: %s", reg.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal could not complete this payment. Please try again.",
        ) from exc

    custom_id, cents, _currency, _capture_id = _capture_details(capture)
    if custom_id != f"livereg:{reg.id}":
        log.error(
            "PayPal order %s custom_id %r does not match registration %s",
            body.order_id, custom_id, reg.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment does not match this registration.",
        )

    _settle_live(
        db, reg, course,
        provider="paypal",
        ref=body.order_id,
        amount_cents=cents or course.price_cents,
    )
    return {"ok": True, "status": "paid"}


# ----- LIVE cohorts: Stripe --------------------------------------------------

@router.post("/live/stripe/checkout")
def live_stripe_checkout(body: LiveOrderIn, db: Session = Depends(get_db)) -> dict:
    """Stripe Checkout Session for a pending registration. Fulfilment rides
    the existing /api/academy/webhook/stripe via metadata.kind='live_course'."""
    settings = get_settings()
    stripe = _stripe()  # 503s when Stripe keys are absent
    reg, course = _load_payable(db, body.registration_id)

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": course.currency,
                        "unit_amount": course.price_cents,
                        "product_data": {"name": course.title},
                    },
                }
            ],
            customer_email=reg.email,
            success_url=f"{settings.SITE_URL}/training/{course.code}?paid=1",
            cancel_url=f"{settings.SITE_URL}/training/{course.code}?cancelled=1",
            client_reference_id=f"livereg:{reg.id}",
            metadata={"kind": "live_course", "registration_id": str(reg.id)},
        )
    except Exception as exc:
        log.error("Stripe live-cohort Checkout create failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout. Please try again.",
        ) from exc

    return {"url": session.url}


def _live_session_registration(
    db: Session, session_obj: dict
) -> tuple[Registration, Course] | None:
    """Resolve a live_course-tagged Checkout Session to its registration and
    course, or None (with logging) when the metadata is broken."""
    session_id = str(session_obj.get("id") or "")
    raw_reg_id = (session_obj.get("metadata") or {}).get("registration_id")
    try:
        reg_id = int(raw_reg_id)
    except (TypeError, ValueError):
        log.error(
            "live_course session %s has bad registration_id %r",
            session_id, raw_reg_id,
        )
        return None

    reg = db.get(Registration, reg_id)
    if reg is None:
        log.error(
            "live_course session %s references unknown registration %s",
            session_id, reg_id,
        )
        return None
    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    if course is None:
        log.error(
            "live_course session %s: course %r missing", session_id, reg.course_code
        )
        return None
    return reg, course


# Lines a bank-payment event may write into Registration.admin_notes. Each
# event replaces the other kind's line, so the note always reflects the
# latest state of the debit — and an already-present line of the same kind
# is the webhook-replay guard.
_BANK_NOTE_PREFIXES = ("bank payment processing", "bank payment failed")


def _swap_bank_note(reg: Registration, note: str) -> bool:
    """Replace any prior bank-payment note line with `note`, preserving the
    admin's own notes. Returns False (no change) when a line of the same
    kind is already present — i.e. a webhook replay."""
    prefix = next(pfx for pfx in _BANK_NOTE_PREFIXES if note.startswith(pfx))
    lines = [l for l in (reg.admin_notes or "").splitlines() if l.strip()]
    if any(l.startswith(prefix) for l in lines):
        return False
    lines = [l for l in lines if not l.startswith(_BANK_NOTE_PREFIXES)]
    lines.append(note)
    reg.admin_notes = "\n".join(lines)[:2000]
    return True


def fulfil_live_session(db: Session, session_obj: dict) -> None:
    """Handle checkout.session.completed / async_payment_succeeded for a
    live-cohort seat. Called by the webhook after signature verification;
    must never raise — Stripe would retry a permanent condition forever.

    The registration flips to paid ONLY when the session's payment_status is
    'paid': a card at completed, or an ACH debit at async_payment_succeeded.
    A completed-but-unpaid session (ACH pending) leaves the row pending —
    the seat is already held by the pending registration — notes the
    expected settlement date for the admin, and sends no receipt yet."""
    session_id = str(session_obj.get("id") or "")
    loaded = _live_session_registration(db, session_obj)
    if loaded is None:
        return
    reg, course = loaded

    if str(session_obj.get("payment_status") or "") != "paid":
        # ACH delayed notification: funds unconfirmed for 4-5 business days.
        if reg.status != "pending":
            log.info(
                "live_course session %s unpaid but registration %s is %s — ignoring",
                session_id, reg.id, reg.status,
            )
            return
        deadline = add_business_days(
            datetime.now(timezone.utc), SETTLEMENT_MARGIN_BUSINESS_DAYS
        )
        if _swap_bank_note(
            reg, f"bank payment processing, expected by {deadline.date().isoformat()}"
        ):
            db.commit()
            log.info(
                "live_course session %s: bank payment pending for registration %s",
                session_id, reg.id,
            )
        return

    amount = int(session_obj.get("amount_total") or course.price_cents)
    try:
        _settle_live(
            db, reg, course, provider="stripe", ref=session_id, amount_cents=amount
        )
    except HTTPException as exc:
        # Money arrived but the row can't flip (e.g. capacity was shrunk
        # under a paid cohort). Log loudly for the admin; ack the webhook.
        log.error(
            "live_course session %s could not be marked paid: %s",
            session_id, exc.detail,
        )


def live_payment_failed(db: Session, session_obj: dict) -> None:
    """checkout.session.async_payment_failed for a live-cohort seat.

    No auto-cancel: a pending registration IS the held-seat pre-payment
    state, so the row stays pending and the owner releases it by hand if
    needed. The admin note flips from 'processing' to 'failed', and the
    buyer (seat still held — pay by card or contact us) plus the admin are
    emailed once; the note swap doubles as the replay guard."""
    session_id = str(session_obj.get("id") or "")
    loaded = _live_session_registration(db, session_obj)
    if loaded is None:
        return
    reg, course = loaded

    if reg.status == "paid":
        # Funds were already confirmed; a late failure event must not touch it.
        log.warning(
            "async_payment_failed for paid registration %s (%s) — ignoring",
            reg.id, session_id,
        )
        return

    today = datetime.now(timezone.utc).date().isoformat()
    if not _swap_bank_note(reg, f"bank payment failed {today}"):
        return  # replay — already recorded and already emailed
    db.commit()

    settings = get_settings()
    course_url = f"{settings.SITE_URL}/training/{course.code}"
    send_email(
        to=reg.email,
        subject=f"Your bank payment didn't clear — {course.title}",
        html=live_bank_failed_html(reg.full_name, course.title, course_url),
        db=db,
        scope_kind="course",
        scope_code=course.code,
        audience="payer",
        template="live_bank_failed",
    )
    if settings.ADMIN_NOTIFY_EMAIL:
        send_email(
            to=settings.ADMIN_NOTIFY_EMAIL,
            subject=(
                f"Bank payment failed — live seat still pending: "
                f"{reg.email} / {course.code}"
            ),
            html=settlement_failed_admin_html(
                reg.email,
                course.title,
                f"Live-cohort seat: the ACH debit failed on {today}. The "
                "registration stays pending (seat held) — no auto-cancel.",
            ),
            db=db,
            scope_kind="course",
            scope_code=course.code,
            audience="admin",
            template="live_bank_failed_admin",
        )
    log.info(
        "live_course session %s: bank payment failed for registration %s",
        session_id, reg.id,
    )


# ----- RECORDED products: PayPal --------------------------------------------

@router.post("/recorded/paypal/create-order")
def recorded_paypal_create_order(
    body: RecordedOrderIn, db: Session = Depends(get_db)
) -> dict:
    _require_paypal()
    product = _load_live_product(db, body.product_code)
    email = str(body.email).lower().strip()
    try:
        order_id = paypal.create_order(
            product.price_cents,
            product.currency,
            description=product.title,
            custom_id=_recorded_custom_id(product.code, email),
        )
    except paypal.PayPalError as exc:
        log.error("PayPal create-order failed for product %s: %s", product.code, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start PayPal checkout. Please try again.",
        ) from exc
    return {"order_id": order_id}


@router.post("/recorded/paypal/capture")
def recorded_paypal_capture(
    body: RecordedCaptureIn, db: Session = Depends(get_db)
) -> dict:
    _require_paypal()

    # Idempotency rides the unique academy_orders.provider_ref, exactly like
    # the Stripe webhook: a replayed capture of a fulfilled order is a no-op.
    existing = db.execute(
        select(Order).where(Order.provider_ref == body.order_id)
    ).scalar_one_or_none()
    if existing is not None and existing.status == "paid":
        return {"ok": True, "next": "/learn"}

    product = _load_live_product(db, body.product_code)
    email = str(body.email).lower().strip()

    try:
        capture = paypal.capture_order(body.order_id)
    except paypal.PayPalError as exc:
        log.error("PayPal capture failed for product %s: %s", product.code, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal could not complete this payment. Please try again.",
        ) from exc

    custom_id, cents, currency, capture_id = _capture_details(capture)
    if custom_id != _recorded_custom_id(product.code, email):
        log.error(
            "PayPal order %s custom_id %r does not match product %s / %s",
            body.order_id, custom_id, product.code, email,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment does not match this purchase.",
        )

    # Same fulfilment sequence as checkout._fulfil, with PayPal identifiers:
    # upsert learner → settle the Order row → grant enrollment → welcome email.
    learner = svc.upsert_learner(db, email, body.full_name or "")

    order = existing
    if order is None:
        order = Order(
            product_code=product.code,
            provider="paypal",
            provider_ref=body.order_id,
            currency=product.currency,
        )
        db.add(order)
    order.learner_id = learner.id
    order.email = email
    order.provider = "paypal"
    order.amount_cents = cents or product.price_cents
    order.currency = (currency or product.currency).lower()
    order.payment_ref = capture_id
    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)

    grant_and_welcome(db, order, product, learner)
    log.info(
        "Fulfilled PayPal order %s for %s (%s)", order.id, email, product.code
    )
    return {"ok": True, "next": "/learn"}
