"""Private offers: one course, one buyer, one price (2026-11-27).

The instructor sells a course to a named person below the listed price:

  1. Admin → Academy → "Sell at a private price": email, course, price,
     how many days the offer stays open, an optional note.
  2. The site makes a link (/learn/offer/<token>) and, by default, emails it
     to the buyer. The link is unguessable, works for that email only, and
     works once.
  3. The buyer opens it, sees the course and their price, and pays with the
     same Stripe Checkout as every purchase: the email is fixed to theirs and
     the amount is the offer price.
  4. The Stripe webhook fulfils it exactly like a full-price sale (access,
     welcome email with a sign-in link, the instructor copied), and marks the
     offer paid so the link cannot be used again.

Free access stays with "Give someone free access"; an offer is always a paid
sale, at least $1 and below the regular price.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import academy as svc
from .config import get_settings
from .emailer import course_offer_html, send_email
from .models import CourseOffer, Learner, Order, Product

log = logging.getLogger(__name__)

MIN_PRICE_CENTS = 100       # an offer is a sale; free access has its own form
MAX_VALID_DAYS = 60
DEFAULT_VALID_DAYS = 14


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def money(cents: int, currency: str = "usd") -> str:
    """'$650', '$650.50', '650 EUR'."""
    cents = int(cents or 0)
    amount = f"{cents / 100:,.0f}" if cents % 100 == 0 else f"{cents / 100:,.2f}"
    cur = (currency or "usd").upper()
    return f"${amount}" if cur == "USD" else f"{amount} {cur}"


def percent_off(offer: CourseOffer) -> int:
    if not offer.list_price_cents or offer.list_price_cents <= offer.price_cents:
        return 0
    return round(100 * (1 - offer.price_cents / offer.list_price_cents))


def state(offer: CourseOffer, now: Optional[datetime] = None) -> str:
    """'open' | 'expired' | 'paid' | 'revoked'."""
    if offer.status in ("paid", "revoked"):
        return offer.status
    if (now or _now()) >= _aware(offer.expires_at):
        return "expired"
    return "open"


def link(offer: CourseOffer) -> str:
    return f"{get_settings().SITE_URL.rstrip('/')}/learn/offer/{offer.token}"


def expires_display(offer: CourseOffer) -> str:
    return _aware(offer.expires_at).strftime("%B %d, %Y")


def by_token(db: Session, token: str) -> Optional[CourseOffer]:
    token = (token or "").strip()
    if not token or len(token) > 64:
        return None
    return db.execute(select(CourseOffer).where(CourseOffer.token == token)).scalar_one_or_none()


def has_active_access(db: Session, email: str, product_code: str) -> bool:
    learner = db.execute(
        select(Learner).where(Learner.email == email.lower().strip())
    ).scalar_one_or_none()
    return learner is not None and svc.has_access(db, learner, product_code)


def create(
    db: Session,
    *,
    product: Product,
    email: str,
    full_name: str,
    price_cents: int,
    valid_days: int,
    note: str,
    by: str,
    send: bool = True,
) -> CourseOffer:
    """Make an offer. Raises ValueError with a message for the admin."""
    email = email.lower().strip()
    if product.status != "live":
        raise ValueError("This course is not live, so it cannot be bought. Publish it first.")
    if (product.price_cents or 0) <= 0:
        raise ValueError("Set the course's regular price first.")
    if price_cents < MIN_PRICE_CENTS:
        raise ValueError(
            "The offer price must be at least $1. To give the course for free, "
            "use “Give someone free access” instead."
        )
    if price_cents >= product.price_cents:
        raise ValueError(
            f"The offer price must be below the regular price "
            f"({money(product.price_cents, product.currency)})."
        )
    if not 1 <= valid_days <= MAX_VALID_DAYS:
        raise ValueError(f"An offer can stay open for 1 to {MAX_VALID_DAYS} days.")
    if has_active_access(db, email, product.code):
        raise ValueError(f"{email} already has access to this course.")

    now = _now()
    # One live offer per person per course: a new price replaces the old link.
    for old in db.execute(
        select(CourseOffer).where(
            CourseOffer.email == email,
            CourseOffer.product_code == product.code,
            CourseOffer.status == "open",
        )
    ).scalars().all():
        if state(old, now) == "open":
            old.status = "revoked"
            old.revoked_at = now
    offer = CourseOffer(
        token=secrets.token_urlsafe(24),
        product_code=product.code,
        email=email,
        full_name=" ".join((full_name or "").split())[:200],
        price_cents=int(price_cents),
        list_price_cents=int(product.price_cents),
        currency=(product.currency or "usd").lower(),
        note=(note or "").strip()[:500],
        status="open",
        created_by=by or "",
        expires_at=now + timedelta(days=valid_days),
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    log.info("Offer %s: %s for %s at %s by %s", offer.id, product.code, email,
             money(offer.price_cents, offer.currency), by)
    if send:
        email_offer(db, offer, product)
    return offer


def email_offer(db: Session, offer: CourseOffer, product: Product) -> bool:
    sent = send_email(
        to=offer.email,
        subject=f"Your private price for {product.title}",
        html=course_offer_html(
            offer.full_name,
            product.title,
            money(offer.price_cents, offer.currency),
            money(offer.list_price_cents, offer.currency) if offer.list_price_cents else "",
            link(offer),
            expires_display(offer),
            offer.note,
        ),
        db=db, scope_kind="product", scope_code=product.code,
        audience="buyer", template="course_offer",
    )
    if sent:
        offer.emailed_at = _now()
        db.commit()
    return bool(sent)


def revoke(db: Session, offer: CourseOffer) -> CourseOffer:
    if offer.status == "paid":
        raise ValueError("This offer is already paid; refund it in Stripe if needed.")
    if offer.status != "revoked":
        offer.status = "revoked"
        offer.revoked_at = _now()
        db.commit()
    return offer


def mark_paid(db: Session, offer_id: str | int, order: Order) -> None:
    """Called by the Stripe webhook once the offer's session is paid (or, for
    a bank debit, accepted). Idempotent; never reopens a link."""
    try:
        offer = db.get(CourseOffer, int(offer_id))
    except (TypeError, ValueError):
        offer = None
    if offer is None:
        log.error("Paid session names unknown offer %r", offer_id)
        return
    if offer.product_code != order.product_code:
        log.error("Offer %s is for %s but order %s is for %s; not marked",
                  offer.id, offer.product_code, order.id, order.product_code)
        return
    if offer.status == "paid":
        return
    offer.status = "paid"
    offer.order_id = order.id
    offer.paid_at = _now()
    db.commit()
    log.info("Offer %s paid by order %s", offer.id, order.id)


def public_out(db: Session, offer: CourseOffer) -> dict:
    product = db.get(Product, offer.product_code)
    return {
        "state": state(offer),
        "product": {
            "code": offer.product_code,
            "title": product.title if product else offer.product_code,
            "subtitle": product.subtitle if product else "",
        },
        "email": offer.email,
        "full_name": offer.full_name,
        "price_cents": offer.price_cents,
        "list_price_cents": offer.list_price_cents,
        "currency": offer.currency,
        "percent_off": percent_off(offer),
        "note": offer.note,
        "expires_at": _aware(offer.expires_at).isoformat(),
    }


def admin_out(db: Session, offer: CourseOffer, titles: Optional[dict] = None) -> dict:
    title = (titles or {}).get(offer.product_code)
    if title is None:
        product = db.get(Product, offer.product_code)
        title = product.title if product else offer.product_code
    return {
        "id": offer.id,
        "state": state(offer),
        "link": link(offer),
        "product_code": offer.product_code,
        "product_title": title,
        "email": offer.email,
        "full_name": offer.full_name,
        "price_cents": offer.price_cents,
        "list_price_cents": offer.list_price_cents,
        "currency": offer.currency,
        "percent_off": percent_off(offer),
        "note": offer.note,
        "created_by": offer.created_by,
        "created_at": _aware(offer.created_at).isoformat() if offer.created_at else None,
        "expires_at": _aware(offer.expires_at).isoformat(),
        "emailed_at": _aware(offer.emailed_at).isoformat() if offer.emailed_at else None,
        "paid_at": _aware(offer.paid_at).isoformat() if offer.paid_at else None,
        "revoked_at": _aware(offer.revoked_at).isoformat() if offer.revoked_at else None,
        "order_id": offer.order_id,
    }
