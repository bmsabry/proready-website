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

ACH (US bank debit) is delayed-notification: `completed` arrives with
payment_status='unpaid' and the money confirms 4-5 business days later via
`async_payment_succeeded` / fails via `async_payment_failed`. Recorded
products grant provisional access at completed (Order 'processing',
enrollment settlement-pending with a 7-business-day deadline enforced
lazily by academy.settlement_ok); live-cohort seats only flip to paid when
payment_status is actually 'paid'.
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
from ..settlement import SETTLEMENT_MARGIN_BUSINESS_DAYS, add_business_days

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


def _session_identity(session_obj: dict) -> tuple[str, str, str]:
    """(session_id, buyer_email, product_code) from a Checkout Session."""
    session_id = session_obj.get("id") or ""
    email = (
        (session_obj.get("customer_details") or {}).get("email")
        or session_obj.get("customer_email")
        or ""
    ).lower().strip()
    product_code = (session_obj.get("metadata") or {}).get(
        "product_code"
    ) or session_obj.get("client_reference_id")
    return session_id, email, str(product_code or "")


def _fulfil(db: Session, session_obj: dict, *, provisional: bool = False) -> None:
    """Turn a completed Checkout Session into access. Idempotent.

    Called only from the webhook, only after signature verification.

    provisional=True is the ACH path: `checkout.session.completed` arrived
    with payment_status != 'paid', so the money is 4-5 business days out.
    Access is granted immediately anyway (owner's call: digital goods, low
    fraud surface) but marked settlement-pending with a 7-business-day
    drop-dead date, and the Order sits at 'processing' until the bank
    answers via async_payment_succeeded/_failed — or the deadline lapses
    and academy.settlement_ok revokes on read.
    """
    session_id, email, product_code = _session_identity(session_obj)

    if not email or not product_code:
        log.error("Webhook missing email or product_code for session %s", session_id)
        return

    order = db.execute(
        select(Order).where(Order.provider_ref == session_id)
    ).scalar_one_or_none()
    if order is not None and order.status == "paid":
        log.info("Webhook replay for already-fulfilled session %s — ignoring", session_id)
        return
    if provisional and order is not None and order.status == "processing":
        log.info("Replay of unpaid completed event %s — ignoring", session_id)
        return
    # async_payment_succeeded after a processed completed event: the welcome
    # email already went out with the provisional grant — settle silently.
    was_provisional = order is not None and order.status == "processing"

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
    from datetime import datetime, timezone as _tz

    if provisional:
        order.status = "processing"
    else:
        order.status = "paid"
        order.paid_at = datetime.now(_tz.utc)
    db.commit()
    db.refresh(order)

    grant_and_welcome(
        db, order, product, learner,
        bank_pending=provisional,
        send_welcome=provisional or not was_provisional,
    )
    log.info(
        "%s order %s for %s (%s)",
        "Provisionally granted" if provisional else "Fulfilled",
        order.id, email, product_code,
    )


def _payment_failed(db: Session, session_obj: dict) -> None:
    """checkout.session.async_payment_failed for a recorded product: the ACH
    debit bounced after provisional access was granted. Idempotent — the
    Order status flip guards the whole path, and the enrollment flip inside
    revoke_for_failed_settlement guards the emails.
    """
    session_id, email, product_code = _session_identity(session_obj)

    order = db.execute(
        select(Order).where(Order.provider_ref == session_id)
    ).scalar_one_or_none()
    if order is None:
        # completed never reached us either — nothing was granted.
        log.info("async_payment_failed for unknown session %s — ignoring", session_id)
        return
    if order.status == "failed":
        return  # replay
    if order.status == "paid":
        # Funds were already confirmed; a late failure event must not un-pay.
        log.warning(
            "async_payment_failed for already-paid session %s — ignoring", session_id
        )
        return
    order.status = "failed"
    db.commit()

    learner = (
        db.get(Learner, order.learner_id) if order.learner_id is not None else None
    )
    if learner is None and email:
        learner = db.execute(
            select(Learner).where(Learner.email == email)
        ).scalar_one_or_none()
    enrollment = None
    if learner is not None:
        from ..models import Enrollment

        enrollment = db.execute(
            select(Enrollment).where(
                Enrollment.learner_id == learner.id,
                Enrollment.product_code == (order.product_code or product_code),
            )
        ).scalar_one_or_none()
    if enrollment is None:
        log.info("async_payment_failed %s: no enrollment to revoke", session_id)
        return

    from datetime import datetime, timezone as _tz

    today = datetime.now(_tz.utc).date().isoformat()
    svc.revoke_for_failed_settlement(
        db,
        enrollment,
        note=f"bank payment failed {today}",
        detail=f"Stripe reported the ACH debit failed on {today} — access revoked.",
    )
    log.info("Revoked provisional access for failed session %s", session_id)


def grant_and_welcome(
    db: Session, order: Order, product: Product, learner: Learner,
    *, bank_pending: bool = False, send_welcome: bool = True,
) -> None:
    """Grant access + send the purchase-welcome email for a paid order.

    Shared by the Stripe webhook (`_fulfil`) and the PayPal recorded-course
    capture path so both providers provision access identically. The
    enrollment source is the order's provider ('stripe' | 'paypal').

    bank_pending=True (ACH awaiting settlement) grants provisionally with a
    7-business-day deadline and appends the processing note to the welcome
    email. send_welcome=False settles an existing provisional grant without
    re-mailing a buyer who was already welcomed at checkout time.
    """
    settings = get_settings()
    if bank_pending:
        from datetime import datetime, timezone as _tz

        svc.grant_enrollment(
            db, learner, order.product_code,
            source=order.provider, order_id=order.id,
            settlement_status="pending",
            settlement_deadline=add_business_days(
                datetime.now(_tz.utc), SETTLEMENT_MARGIN_BUSINESS_DAYS
            ),
        )
    else:
        svc.grant_enrollment(
            db, learner, order.product_code, source=order.provider, order_id=order.id
        )

    if not send_welcome:
        return
    raw = issue_login_token(db, learner, next_path=f"/learn/{order.product_code}")
    link = f"{settings.SITE_URL}/learn/signin?token={raw}"
    send_email(
        to=learner.email,
        subject=f"You're in — {product.title}",
        html=purchase_welcome_html(
            learner.full_name or "", product.title, link,
            settings.LOGIN_LINK_TTL_SECONDS // 60,
            bank_pending=bank_pending,
        ),
        bcc=settings.ADMIN_NOTIFY_EMAIL or None,
    )


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
    if order.kind == "advanced_cert":
        # The examined tier was refunded: close the examination, leave the
        # course enrollment and any completion certificate untouched.
        from .. import advanced_cert as adv  # noqa: PLC0415
        from ..models import AdvancedCertification  # noqa: PLC0415

        row = db.execute(
            select(AdvancedCertification).where(AdvancedCertification.order_id == order.id)
        ).scalar_one_or_none()
        if row is not None and row.status not in adv.TERMINAL:
            adv.cancel(db, row, reason)
        db.commit()
        log.info("Advanced certification cancelled for order %s (%s)", order.id, reason)
        return
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


def fulfil_advanced_cert(db: Session, session_obj: dict) -> None:
    """Turn a paid examined-tier Checkout Session into an open examination.

    Idempotent through Order.status and AdvancedCertification.order_id.
    """
    from .. import advanced_cert as adv  # noqa: PLC0415

    session_id, email, product_code = _session_identity(session_obj)
    order = db.execute(
        select(Order).where(Order.provider_ref == session_id)
    ).scalar_one_or_none()
    if order is not None and order.status == "paid":
        log.info("Replay of fulfilled advanced-cert session %s — ignoring", session_id)
        return
    product = db.get(Product, product_code)
    if product is None:
        log.error("Advanced-cert webhook references unknown product %r", product_code)
        return
    learner = None
    learner_id = (session_obj.get("metadata") or {}).get("learner_id")
    if learner_id:
        learner = db.get(Learner, int(learner_id))
    if learner is None and email:
        learner = svc.upsert_learner(
            db, email, (session_obj.get("customer_details") or {}).get("name") or ""
        )
    if learner is None:
        log.error("Advanced-cert webhook %s has no learner", session_id)
        return
    if order is None:
        order = Order(
            learner_id=learner.id, product_code=product_code, email=learner.email,
            provider="stripe", provider_ref=session_id, currency=product.currency,
            kind="advanced_cert",
        )
        db.add(order)
    from datetime import datetime, timezone as _tz

    order.kind = "advanced_cert"
    order.learner_id = learner.id
    order.amount_cents = int(session_obj.get("amount_total") or product.advanced_cert_price_cents)
    order.currency = (session_obj.get("currency") or product.currency).lower()
    order.payment_ref = str(session_obj.get("payment_intent") or "")
    order.status = "paid"
    order.paid_at = datetime.now(_tz.utc)
    db.commit()
    db.refresh(order)
    adv.create(
        db, learner, product,
        source="stripe", order_id=order.id,
        amount_cents=order.amount_cents, currency=order.currency,
    )
    log.info("Advanced certification opened for %s (%s), order %s", learner.email, product_code, order.id)


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

    # Live-cohort seats ride the same webhook: their sessions are tagged
    # metadata.kind == 'live_course' by /api/payments/live/stripe/checkout.
    # Lazy import — payments.py imports _stripe from this module at import
    # time, so importing it back at module level would be circular.
    def _is_live_course(session_obj: dict) -> bool:
        return (session_obj.get("metadata") or {}).get("kind") == "live_course"

    def _is_advanced_cert(session_obj: dict) -> bool:
        return (session_obj.get("metadata") or {}).get("kind") == "advanced_cert"

    if kind == "checkout.session.completed" and _is_advanced_cert(obj):
        # Examined-tier purchase: no enrollment to grant — open the written
        # examination. Card only in practice; an unpaid (ACH) completion is
        # held until async_payment_succeeded.
        if obj.get("payment_status") == "paid":
            fulfil_advanced_cert(db, dict(obj))
        else:
            log.info("Advanced-cert checkout %s completed unpaid — waiting", obj.get("id"))
    elif kind == "checkout.session.async_payment_succeeded" and _is_advanced_cert(obj):
        fulfil_advanced_cert(db, dict(obj))
    elif kind == "checkout.session.async_payment_failed" and _is_advanced_cert(obj):
        order = db.execute(
            select(Order).where(Order.provider_ref == obj.get("id"))
        ).scalar_one_or_none()
        if order is not None and order.status != "paid":
            order.status = "failed"
            db.commit()
    elif kind == "checkout.session.completed":
        if _is_live_course(obj):
            # fulfil_live_session inspects payment_status itself: paid (card)
            # settles the seat now; unpaid (ACH pending) holds it with a note.
            from .payments import fulfil_live_session  # noqa: PLC0415

            fulfil_live_session(db, dict(obj))
        elif obj.get("payment_status") == "paid":
            _fulfil(db, dict(obj))
        else:
            # ACH delayed notification: grant provisional access now; the bank
            # confirms via async_payment_succeeded/_failed in ~4-5 business
            # days, and settlement_ok revokes at 7 if it never answers.
            log.info(
                "Checkout completed unpaid (%s) — provisional grant", obj.get("id")
            )
            _fulfil(db, dict(obj), provisional=True)
    elif kind == "checkout.session.async_payment_succeeded":
        if _is_live_course(obj):
            from .payments import fulfil_live_session  # noqa: PLC0415

            fulfil_live_session(db, dict(obj))
        else:
            _fulfil(db, dict(obj))
    elif kind == "checkout.session.async_payment_failed":
        if _is_live_course(obj):
            from .payments import live_payment_failed  # noqa: PLC0415

            live_payment_failed(db, dict(obj))
        else:
            _payment_failed(db, dict(obj))
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
