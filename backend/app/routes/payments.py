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
from ..emailer import payment_receipt_html, send_email
from ..models import Course, Order, Product, Registration
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


def fulfil_live_session(db: Session, session_obj: dict) -> None:
    """Mark a live-cohort registration paid from a completed Stripe Checkout
    Session. Called by the webhook after signature verification; must never
    raise — Stripe would retry a permanent condition forever."""
    session_id = str(session_obj.get("id") or "")
    raw_reg_id = (session_obj.get("metadata") or {}).get("registration_id")
    try:
        reg_id = int(raw_reg_id)
    except (TypeError, ValueError):
        log.error(
            "live_course session %s has bad registration_id %r",
            session_id, raw_reg_id,
        )
        return

    reg = db.get(Registration, reg_id)
    if reg is None:
        log.error(
            "live_course session %s references unknown registration %s",
            session_id, reg_id,
        )
        return
    course = db.execute(
        select(Course).where(Course.code == reg.course_code)
    ).scalar_one_or_none()
    if course is None:
        log.error(
            "live_course session %s: course %r missing", session_id, reg.course_code
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
