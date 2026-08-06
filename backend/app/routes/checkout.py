"""Stripe Checkout for self-serve academy purchases.

Scope note: the cohort registration flow (`/api/register`) deliberately has
NO inline Stripe — cohort seats are invoiced by hand and flipped to paid from
the admin dashboard, and that decision stands. This module is a separate
product line: on-demand courses that must provision access the instant the
card clears, with no human in the loop.

Flow:
  1. POST /api/academy/checkout        → Stripe Checkout Session, returns URL
  2. Stripe hosts the card form
  3. POST /api/academy/webhook/stripe  → on checkout.session.completed:
        upsert learner → mark order paid → grant lifetime enrollment →
        email a sign-in link
  4. Buyer lands on /learn/welcome, already entitled

Idempotency: `academy_orders.provider_ref` is unique on the Checkout Session
id, so Stripe's at-least-once webhook delivery can replay the same event
without double-granting or double-emailing.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as svc
from ..config import get_settings
from ..db import get_db
from ..emailer import purchase_welcome_html, send_email
from ..learner_auth import issue_login_token
from ..models import Learner, Order, Product

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/academy", tags=["academy-checkout"])


class CheckoutIn(BaseModel):
    product_code: str
    email: EmailStr | None = None


def _stripe():
    """Import and configure the SDK lazily.

    Kept out of module scope so a missing/broken Stripe install degrades to a
    503 on checkout instead of taking the whole API — including registrations
    and the admin dashboard — down at import time.
    """
    settings = get_settings()
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are not configured yet.",
        )
    try:
        import stripe  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        log.error("stripe SDK missing: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are temporarily unavailable.",
        ) from exc
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


@router.post("/checkout")
def create_checkout(
    body: CheckoutIn, db: Session = Depends(get_db)
) -> dict:
    """Create a Stripe Checkout Session and hand back its hosted URL."""
    settings = get_settings()
    stripe = _stripe()

    product = db.get(Product, body.product_code)
    if product is None or product.status != "live":
        raise HTTPException(status_code=404, detail="Course not available.")
    if product.price_cents <= 0:
        raise HTTPException(status_code=409, detail="This course has no price set yet.")

    # A pre-made Price wins when configured (keeps Stripe reporting tidy);
    # otherwise build the line item inline from the DB so Bassam can change
    # the price in the admin UI without touching Stripe.
    if product.stripe_price_id:
        line_items = [{"price": product.stripe_price_id, "quantity": 1}]
    else:
        line_items = [
            {
                "quantity": 1,
                "price_data": {
                    "currency": product.currency,
                    "unit_amount": product.price_cents,
                    "product_data": {
                        "name": product.title,
                        "description": (product.subtitle or "")[:300] or None,
                    },
                },
            }
        ]

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=line_items,
            customer_email=str(body.email) if body.email else None,
            success_url=(
                f"{settings.SITE_URL}/learn/welcome"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{settings.SITE_URL}/training/{product.code}",
            client_reference_id=product.code,
            metadata={"product_code": product.code},
            # Lets a buyer who mistypes their address still reach support,
            # and gives Stripe Tax something to work with later.
            billing_address_collection="auto",
            allow_promotion_codes=True,
        )
    except Exception as exc:
        log.error("Stripe Checkout create failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout. Please try again.",
        ) from exc

    db.add(
        Order(
            product_code=product.code,
            email=(str(body.email).lower().strip() if body.email else ""),
            provider="stripe",
            provider_ref=session.id,
            amount_cents=product.price_cents,
            currency=product.currency,
            status="pending",
        )
    )
    db.commit()

    return {"url": session.url, "session_id": session.id}


def _fulfil(db: Session, session_obj: dict) -> None:
    """Turn a completed Checkout Session into access. Idempotent.

    Called only from the webhook, only after signature verification.
    """
    settings = get_settings()
    session_id = session_obj.get("id") or ""
    email = (
        (session_obj.get("customer_details") or {}).get("email")
        or session_obj.get("customer_email")
        or ""
    ).lower().strip()
    product_code = (session_obj.get("metadata") or {}).get(
        "product_code"
    ) or session_obj.get("client_reference_id")

    if not email or not product_code:
        log.error("Webhook missing email or product_code for session %s", session_id)
        return

    order = db.execute(
        select(Order).where(Order.provider_ref == session_id)
    ).scalar_one_or_none()
    if order is not None and order.status == "paid":
        log.info("Webhook replay for already-fulfilled session %s — ignoring", session_id)
        return

    product = db.get(Product, product_code)
    if product is None:
        log.error("Webhook references unknown product %r", product_code)
        return

    learner = svc.upsert_learner(
        db, email, (session_obj.get("customer_details") or {}).get("name") or ""
    )

    if order is None:
        # Session created outside our /checkout endpoint (e.g. a Payment Link).
        order = Order(
            product_code=product_code,
            provider="stripe",
            provider_ref=session_id,
            currency=product.currency,
        )
        db.add(order)

    order.learner_id = learner.id
    order.email = email
    order.amount_cents = int(session_obj.get("amount_total") or product.price_cents)
    order.currency = (session_obj.get("currency") or product.currency).lower()
    order.payment_ref = str(session_obj.get("payment_intent") or "")
    order.status = "paid"
    from datetime import datetime, timezone as _tz

    order.paid_at = datetime.now(_tz.utc)
    db.commit()
    db.refresh(order)

    svc.grant_enrollment(
        db, learner, product_code, source="stripe", order_id=order.id
    )

    raw = issue_login_token(db, learner, next_path=f"/learn/{product_code}")
    link = f"{settings.SITE_URL}/learn/signin?token={raw}"
    send_email(
        to=learner.email,
        subject=f"You're in — {product.title}",
        html=purchase_welcome_html(
            learner.full_name or "", product.title, link,
            settings.LOGIN_LINK_TTL_SECONDS // 60,
        ),
        bcc=settings.ADMIN_NOTIFY_EMAIL or None,
    )
    log.info("Fulfilled order %s for %s (%s)", order.id, email, product_code)


def _revoke_for_payment(db: Session, payment_intent: str, reason: str) -> None:
    """Pull access after a refund or dispute."""
    if not payment_intent:
        return
    order = db.execute(
        select(Order).where(Order.payment_ref == payment_intent)
    ).scalar_one_or_none()
    if order is None or order.learner_id is None:
        return
    order.status = "refunded"
    from ..models import Enrollment

    enrollment = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == order.learner_id,
            Enrollment.product_code == order.product_code,
        )
    ).scalar_one_or_none()
    if enrollment is not None:
        enrollment.status = "revoked"
        enrollment.note = reason
    db.commit()
    log.info("Revoked access for order %s (%s)", order.id, reason)


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    """Stripe event sink.

    The raw body is required for signature verification — read it before
    anything parses it as JSON. An unverified body is never acted on.
    """
    settings = get_settings()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhooks are not configured.",
        )

    payload = await request.body()
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        log.warning("Rejected Stripe webhook: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature."
        ) from exc

    kind = event["type"]
    obj = event["data"]["object"]

    if kind == "checkout.session.completed":
        if obj.get("payment_status") == "paid":
            _fulfil(db, dict(obj))
        else:
            log.info("Checkout completed but unpaid (%s) — waiting", obj.get("id"))
    elif kind == "checkout.session.async_payment_succeeded":
        _fulfil(db, dict(obj))
    elif kind == "charge.refunded":
        _revoke_for_payment(db, str(obj.get("payment_intent") or ""), "refunded")
    elif kind == "charge.dispute.created":
        _revoke_for_payment(db, str(obj.get("payment_intent") or ""), "disputed")
    else:
        log.debug("Ignoring Stripe event %s", kind)

    return {"received": True}


@router.get("/checkout/{session_id}")
def checkout_status(session_id: str, db: Session = Depends(get_db)) -> dict:
    """Poll target for the post-purchase page.

    The success page lands before the webhook may have fired, so it polls
    here until the order flips to paid, then tells the buyer to check email.
    """
    order = db.execute(
        select(Order).where(Order.provider_ref == session_id)
    ).scalar_one_or_none()
    if order is None:
        return {"status": "unknown"}
    learner = db.get(Learner, order.learner_id) if order.learner_id else None
    return {
        "status": order.status,
        "product_code": order.product_code,
        "email": learner.email if learner else order.email,
    }
