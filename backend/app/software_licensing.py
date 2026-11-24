"""Desktop software Ed25519 license signing, plan catalog & lifecycle helpers.

Signed license envelope format:
    P3DW1.<base64url(payload_json)>.<base64url(ed25519_sig_over_"P3DW1."+payload_b64u)>

Security & key management:
  `SOFTWARE_LICENSE_SIGNING_KEY` holds Base64 of the 32-byte Ed25519 private
  seed. The public key is compiled into Pro3DWorks desktop builds so verification
  works 100% offline. In local dev/pytest where `SOFTWARE_LICENSE_SIGNING_KEY`
  is empty, a deterministic test key is derived from SESSION_SECRET with a
  warning — never deploy to production with `SOFTWARE_LICENSE_SIGNING_KEY` empty.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import (
    send_email,
    software_admin_sale_html,
    software_license_delivered_html,
    software_payment_failed_html,
    software_trial_welcome_html,
)
from .models import SoftwareActivation, SoftwareLicense, SoftwareTrial

log = logging.getLogger(__name__)

ENVELOPE_PREFIX = "P3DW1"
KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CURRENT_MAJOR_VERSION = 3

PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "pro_monthly": {
        "code": "pro_monthly",
        "product": "pro3dworks",
        "tier": "pro",
        "label": "Pro Individual (Monthly — Founding Launch)",
        "short_label": "Pro Monthly",
        "amount_cents": 2900,
        "regular_cents": 3900,
        "currency": "usd",
        "interval": "month",
        "max_seats": 3,
        "allow_offline_file": False,
        "price_setting": "STRIPE_PRICE_P3DW_PRO_MONTHLY",
        "description": (
            "Full Pro3DWorks v3 suite for solo engineers and waterjet/CNC shops: "
            "unlimited PDF-to-DXF/DWG Waterjet exports, Native SolidWorks & NX bridge, "
            "B-Rep inspection, 1D Tolerance Stack-Up, PMI, Photoreal Studio & BYOK AI "
            "(up to 3 workstations)."
        ),
    },
    "pro_yearly": {
        "code": "pro_yearly",
        "product": "pro3dworks",
        "tier": "pro",
        "label": "Pro Individual (Yearly — Founding Launch)",
        "short_label": "Pro Yearly",
        "amount_cents": 24900,
        "regular_cents": 34900,
        "currency": "usd",
        "interval": "year",
        "max_seats": 3,
        "allow_offline_file": False,
        "price_setting": "STRIPE_PRICE_P3DW_PRO_YEARLY",
        "description": (
            "Annual Pro3DWorks v3 license at Founding Launch savings (~28% off). "
            "Includes unlimited PDF-to-Waterjet DXF/DWG exports, SolidWorks & NX "
            "native viewer support, and all 3D inspection tools (up to 3 workstations)."
        ),
    },
    "shop_monthly": {
        "code": "shop_monthly",
        "product": "pro3dworks",
        "tier": "shop",
        "label": "Shop / Team 5-Pack (Monthly)",
        "short_label": "Shop 5-Seat Monthly",
        "amount_cents": 14900,
        "regular_cents": 14900,
        "currency": "usd",
        "interval": "month",
        "max_seats": 5,
        "allow_offline_file": True,
        "price_setting": "STRIPE_PRICE_P3DW_SHOP_MONTHLY",
        "description": (
            "5 transferable team seats across office estimators, engineers & shop-floor "
            "waterjet controllers, plus air-gapped offline license file option."
        ),
    },
    "shop_yearly": {
        "code": "shop_yearly",
        "product": "pro3dworks",
        "tier": "shop",
        "label": "Shop / Team 5-Pack (Yearly)",
        "short_label": "Shop 5-Seat Yearly",
        "amount_cents": 139000,
        "regular_cents": 139000,
        "currency": "usd",
        "interval": "year",
        "max_seats": 5,
        "allow_offline_file": True,
        "price_setting": "STRIPE_PRICE_P3DW_SHOP_YEARLY",
        "description": (
            "Annual 5-seat fabrication shop & engineering team pack (saves 2 months vs. "
            "monthly) with ITAR-friendly air-gapped offline activation."
        ),
    },
    "perpetual": {
        "code": "perpetual",
        "product": "pro3dworks",
        "tier": "perpetual",
        "label": "Perpetual v3 (One-Time — Own Forever)",
        "short_label": "Perpetual v3",
        "amount_cents": 59900,
        "regular_cents": 59900,
        "currency": "usd",
        "interval": None,
        "max_seats": 3,
        "allow_offline_file": True,
        "price_setting": "STRIPE_PRICE_P3DW_PERPETUAL",
        "description": (
            "Permanent offline license for Pro3DWorks v3.x (zero recurring fees to keep "
            "running forever) + 12 months of updates included, up to 3 workstations."
        ),
    },
}


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _private_key_from_settings() -> Ed25519PrivateKey:
    settings = get_settings()
    raw = (settings.SOFTWARE_LICENSE_SIGNING_KEY or "").strip()
    if raw:
        seed = base64.b64decode(raw)
        if len(seed) != 32:
            raise RuntimeError(
                "SOFTWARE_LICENSE_SIGNING_KEY must be the base64 of a 32-byte seed"
            )
        return Ed25519PrivateKey.from_private_bytes(seed)
    log.warning(
        "SOFTWARE_LICENSE_SIGNING_KEY unset — deriving software signing key from "
        "SESSION_SECRET. Set SOFTWARE_LICENSE_SIGNING_KEY in production."
    )
    seed = hashlib.sha256(
        b"proreadyengineer-software-license:" + (settings.SESSION_SECRET or "dev").encode()
    ).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_b64() -> str:
    pub = _private_key_from_settings().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(pub).decode("ascii")


def sign_envelope(payload: dict[str, Any]) -> str:
    """Sign a canonical JSON license payload into P3DW1.<b64u>.<sig_b64u>."""
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    payload_b64u = _b64u_encode(raw)
    signing_input = f"{ENVELOPE_PREFIX}.{payload_b64u}".encode("ascii")
    sig = _private_key_from_settings().sign(signing_input)
    return f"{ENVELOPE_PREFIX}.{payload_b64u}.{_b64u_encode(sig)}"


def verify_envelope(token: str) -> Optional[dict[str, Any]]:
    """Verify P3DW1.<payload>.<sig> against our public key; return dict or None."""
    try:
        parts = str(token or "").strip().split(".")
        if len(parts) != 3 or parts[0] != ENVELOPE_PREFIX:
            return None
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        sig = _b64u_decode(parts[2])
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64()))
        pub.verify(sig, signing_input)
        data = json.loads(_b64u_decode(parts[1]).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (InvalidSignature, ValueError, KeyError, UnicodeDecodeError):
        return None


def generate_license_key() -> str:
    """Generate a high-entropy, readable P3DW-XXXX-XXXX-XXXX-XXXX license key."""
    groups = [
        "".join(secrets.choice(KEY_ALPHABET) for _ in range(4)) for _ in range(4)
    ]
    return "P3DW-" + "-".join(groups)


def mask_license_key(key: str) -> str:
    parts = key.split("-")
    if len(parts) >= 5:
        return f"{parts[0]}-****-****-****-{parts[-1]}"
    return "P3DW-****"


def issue_trial_token(trial: SoftwareTrial) -> str:
    started = _ensure_utc(trial.started_at) or datetime.now(timezone.utc)
    expires = _ensure_utc(trial.expires_at)
    exp_ts = int(expires.timestamp()) if expires else int((started + timedelta(days=15)).timestamp())
    payload = {
        "v": 1,
        "product": trial.product,
        "kind": "trial",
        "plan": "trial_15d",
        "status": "active",
        "license_key": "",
        "email": trial.email,
        "machine_id": trial.machine_id,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": exp_ts,
        "grace_until": exp_ts,
        "updates_until": exp_ts,
        "valid_major": CURRENT_MAJOR_VERSION,
        "max_seats": 1,
        "jti": trial.token_jti,
        "issuer": "ProReadyEngineer LLC",
    }
    return sign_envelope(payload)


def issue_license_token(lic: SoftwareLicense, *, machine_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    grace_days = max(1, int(settings.SOFTWARE_OFFLINE_GRACE_DAYS))

    exp_ts: Optional[int] = None
    grace_ts: Optional[int] = None
    if lic.plan != "perpetual":
        period_end = _ensure_utc(lic.current_period_end)
        if period_end is None:
            fallback_days = 366 if "yearly" in lic.plan else 32
            period_end = now + timedelta(days=fallback_days)
        exp_ts = int(period_end.timestamp())
        if lic.status == "active":
            grace_ts = int((period_end + timedelta(days=grace_days)).timestamp())
        elif lic.status == "past_due":
            grace_ts = int((period_end + timedelta(days=grace_days)).timestamp())
        else:
            grace_ts = exp_ts

    updates_dt = _ensure_utc(lic.updates_until)
    payload = {
        "v": 1,
        "product": lic.product,
        "kind": "license",
        "plan": lic.plan,
        "status": lic.status,
        "license_key": lic.license_key,
        "email": lic.email,
        "machine_id": machine_id,
        "iat": int(now.timestamp()),
        "exp": exp_ts,
        "grace_until": grace_ts,
        "updates_until": int(updates_dt.timestamp()) if updates_dt else None,
        "valid_major": int(lic.valid_major_version or CURRENT_MAJOR_VERSION),
        "max_seats": int(lic.max_seats or 3),
        "issuer": "ProReadyEngineer LLC",
    }
    return sign_envelope(payload)


def start_or_resume_trial(
    db: Session,
    *,
    product: str,
    email: str,
    machine_id: str,
    full_name: str = "",
    company: str = "",
    machine_name: str = "",
    app_version: str = "",
) -> tuple[str, SoftwareTrial, dict[str, Any]]:
    """Enforce 1x 15-day full-Pro trial per email AND per machine_id.

    Returns ("started"|"resumed"|"expired"|"email_used"|"machine_used", row, meta).
    """
    settings = get_settings()
    clean_email = email.strip().lower()
    clean_machine = machine_id.strip().lower()
    now = datetime.now(timezone.utc)

    matches = db.execute(
        select(SoftwareTrial).where(
            SoftwareTrial.product == product,
            or_(
                SoftwareTrial.email == clean_email,
                SoftwareTrial.machine_id == clean_machine,
            ),
        )
    ).scalars().all()

    exact = next(
        (t for t in matches if t.email == clean_email and t.machine_id == clean_machine),
        None,
    )
    if exact is not None:
        exp = _ensure_utc(exact.expires_at)
        if exp is not None and exp > now:
            days_left = max(1, int((exp - now).total_seconds() // 86400) + 1)
            return "resumed", exact, {"days_remaining": min(settings.SOFTWARE_TRIAL_DAYS, days_left)}
        return "expired", exact, {"days_remaining": 0}

    machine_taken = next((t for t in matches if t.machine_id == clean_machine), None)
    if machine_taken is not None:
        return "machine_used", machine_taken, {"days_remaining": 0}

    email_taken = next((t for t in matches if t.email == clean_email), None)
    if email_taken is not None:
        return "email_used", email_taken, {"days_remaining": 0}

    trial_days = max(1, int(settings.SOFTWARE_TRIAL_DAYS))
    expires_at = now + timedelta(days=trial_days)
    row = SoftwareTrial(
        product=product,
        email=clean_email,
        full_name=full_name.strip()[:200],
        company=company.strip()[:200],
        machine_id=clean_machine,
        machine_name=machine_name.strip()[:200],
        app_version=app_version.strip()[:32],
        started_at=now,
        expires_at=expires_at,
        token_jti=secrets.token_hex(16),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    buy_url = f"{settings.SITE_URL}/products/pro3dworks#pricing"
    download_url = f"{settings.SITE_URL}/download/pro3dworks-installer"
    send_email(
        to=clean_email,
        subject="Your 15-day Pro3DWorks v3 trial is active",
        html=software_trial_welcome_html(
            full_name=row.full_name,
            product_name="Pro3DWorks",
            expires_at=expires_at,
            machine_name=row.machine_name,
            buy_url=buy_url,
            download_url=download_url,
        ),
        db=db,
        scope_kind="software",
        scope_code=product,
        audience="trial",
        template="software_trial_welcome",
    )
    return "started", row, {"days_remaining": trial_days}


def activate_machine_seat(
    db: Session,
    lic: SoftwareLicense,
    *,
    machine_id: str,
    machine_name: str = "",
    app_version: str = "",
) -> tuple[bool, str, int]:
    """Attach `machine_id` to `lic` if within `max_seats`. Returns (ok, reason, used_seats)."""
    clean_machine = machine_id.strip().lower()
    now = datetime.now(timezone.utc)

    active_rows = db.execute(
        select(SoftwareActivation).where(
            SoftwareActivation.license_id == lic.id,
            SoftwareActivation.deactivated_at.is_(None),
        )
    ).scalars().all()

    existing = next((r for r in active_rows if r.machine_id == clean_machine), None)
    if existing is not None:
        existing.last_seen_at = now
        if machine_name.strip():
            existing.machine_name = machine_name.strip()[:200]
        if app_version.strip():
            existing.app_version = app_version.strip()[:32]
        db.commit()
        return True, "reused", len(active_rows)

    if len(active_rows) >= int(lic.max_seats or 1):
        return False, "seat_limit", len(active_rows)

    db.add(
        SoftwareActivation(
            license_id=lic.id,
            machine_id=clean_machine,
            machine_name=machine_name.strip()[:200],
            app_version=app_version.strip()[:32],
            first_activated_at=now,
            last_seen_at=now,
        )
    )
    db.commit()
    return True, "activated", len(active_rows) + 1


def plan_from_stripe_price_id(price_id: str) -> Optional[str]:
    if not price_id:
        return None
    settings = get_settings()
    for plan_code, info in PLAN_CATALOG.items():
        configured = str(getattr(settings, info["price_setting"], "") or "").strip()
        if configured and configured == price_id:
            return plan_code
    return None


def _plan_period_fallback(plan: str, from_dt: datetime) -> Optional[datetime]:
    if plan == "perpetual":
        return None
    if "yearly" in plan:
        return from_dt + timedelta(days=366)
    return from_dt + timedelta(days=32)


def _fetch_stripe_subscription(sub_id: str) -> Optional[dict[str, Any]]:
    settings = get_settings()
    if not sub_id or not settings.STRIPE_SECRET_KEY:
        return None
    try:
        from .routes.checkout import _stripe  # noqa: PLC0415

        stripe = _stripe()
        sub = stripe.Subscription.retrieve(sub_id)
        return dict(sub)
    except Exception as exc:
        log.info("Could not retrieve subscription %s (using fallback): %s", sub_id, exc)
        return None


def _extract_sub_period_end(sub_obj: Optional[dict[str, Any]]) -> Optional[datetime]:
    if not sub_obj:
        return None
    ts = sub_obj.get("current_period_end")
    if ts is None:
        items = ((sub_obj.get("items") or {}).get("data") or [])
        if items and isinstance(items[0], dict):
            ts = items[0].get("current_period_end")
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return None


def fulfill_software_checkout(db: Session, session_obj: dict[str, Any]) -> Optional[SoftwareLicense]:
    """Turn a paid software Checkout Session into a SoftwareLicense + email. Idempotent."""
    settings = get_settings()
    session_id = str(session_obj.get("id") or "").strip()
    meta = session_obj.get("metadata") or {}
    product = str(meta.get("product") or "pro3dworks").strip().lower()
    plan = str(meta.get("plan") or "").strip()
    if plan not in PLAN_CATALOG:
        log.error("Software webhook unknown plan %r on session %s", plan, session_id)
        return None

    existing = db.execute(
        select(SoftwareLicense).where(
            SoftwareLicense.stripe_checkout_session_id == session_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        log.info("Replay of fulfilled software checkout %s — ignoring", session_id)
        return existing

    email = (
        (session_obj.get("customer_details") or {}).get("email")
        or session_obj.get("customer_email")
        or meta.get("email")
        or ""
    ).strip().lower()
    full_name = str(
        (session_obj.get("customer_details") or {}).get("name")
        or meta.get("full_name")
        or ""
    ).strip()
    if not email:
        log.error("Software checkout %s missing customer email", session_id)
        return None

    plan_info = PLAN_CATALOG[plan]
    now = datetime.now(timezone.utc)
    sub_id = str(session_obj.get("subscription") or "").strip() or None
    period_end: Optional[datetime] = None
    updates_until: Optional[datetime] = None

    if plan == "perpetual":
        updates_until = now + timedelta(days=365)
    else:
        sub_obj = _fetch_stripe_subscription(sub_id) if sub_id else None
        period_end = _extract_sub_period_end(sub_obj) or _plan_period_fallback(plan, now)

    lic_key = generate_license_key()
    while db.execute(
        select(SoftwareLicense.id).where(SoftwareLicense.license_key == lic_key)
    ).first() is not None:
        lic_key = generate_license_key()

    lic = SoftwareLicense(
        product=product,
        license_key=lic_key,
        plan=plan,
        status="active",
        email=email,
        full_name=full_name[:200],
        max_seats=int(plan_info["max_seats"]),
        stripe_customer_id=str(session_obj.get("customer") or ""),
        stripe_subscription_id=sub_id,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=str(session_obj.get("payment_intent") or ""),
        amount_cents=int(session_obj.get("amount_total") or plan_info["amount_cents"]),
        currency=str(session_obj.get("currency") or plan_info["currency"]).lower(),
        current_period_end=period_end,
        updates_until=updates_until,
        valid_major_version=CURRENT_MAJOR_VERSION,
        allow_offline_file=bool(plan_info["allow_offline_file"]),
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)

    pre_machine = str(meta.get("machine_id") or "").strip().lower()
    if pre_machine and len(pre_machine) >= 8:
        activate_machine_seat(
            db,
            lic,
            machine_id=pre_machine,
            machine_name=str(meta.get("machine_name") or ""),
        )

    download_url = f"{settings.SITE_URL}/download/pro3dworks-installer"
    portal_url = f"{settings.SITE_URL}/products/pro3dworks#manage-license"
    send_email(
        to=email,
        subject=f"Your Pro3DWorks license key ({plan_info['short_label']})",
        html=software_license_delivered_html(
            full_name=full_name,
            product_name="Pro3DWorks",
            plan_label=plan_info["label"],
            license_key=lic.license_key,
            max_seats=lic.max_seats,
            download_url=download_url,
            portal_url=portal_url,
            current_period_end=lic.current_period_end,
            updates_until=lic.updates_until,
        ),
        db=db,
        scope_kind="software",
        scope_code=product,
        audience="buyer",
        template="software_license_delivered",
    )

    if settings.ADMIN_NOTIFY_EMAIL:
        amount_str = f"${lic.amount_cents / 100:,.2f} {lic.currency.upper()}"
        send_email(
            to=settings.ADMIN_NOTIFY_EMAIL,
            subject=f"New Pro3DWorks sale: {plan_info['short_label']} ({amount_str})",
            html=software_admin_sale_html(
                product_name="Pro3DWorks",
                plan_label=plan_info["label"],
                license_key=lic.license_key,
                buyer_email=email,
                amount_display=amount_str,
            ),
            db=db,
            scope_kind="software",
            scope_code=product,
            audience="admin",
            template="software_admin_sale",
        )

    log.info("Fulfilled software license %s (%s) for %s", lic.license_key, plan, email)
    return lic


def handle_software_stripe_event(
    db: Session, event_type: str, obj: dict[str, Any]
) -> bool:
    """Process software-license Stripe webhook events.

    Returns True when the event belonged to a software product/license (handled),
    or False so callers can continue routing consulting/academy/cohort events.
    """
    settings = get_settings()
    meta = obj.get("metadata") or {}

    if event_type == "checkout.session.completed" and meta.get("kind") == "software_license":
        pay_status = str(obj.get("payment_status") or "").lower()
        if pay_status in ("paid", "no_payment_required", ""):
            fulfill_software_checkout(db, obj)
        else:
            log.info("Software checkout %s completed unpaid (%s); waiting for async success", obj.get("id"), pay_status)
        return True

    if event_type == "checkout.session.async_payment_succeeded" and meta.get("kind") == "software_license":
        fulfill_software_checkout(db, obj)
        return True

    if event_type == "checkout.session.async_payment_failed" and meta.get("kind") == "software_license":
        sid = str(obj.get("id") or "")
        lic = db.execute(
            select(SoftwareLicense).where(SoftwareLicense.stripe_checkout_session_id == sid)
        ).scalar_one_or_none()
        if lic is not None and lic.status != "revoked":
            lic.status = "revoked"
            db.commit()
        return True

    if event_type in ("invoice.paid", "invoice.payment_failed"):
        sub_id = str(obj.get("subscription") or "").strip()
        if not sub_id:
            return False
        lic = db.execute(
            select(SoftwareLicense).where(SoftwareLicense.stripe_subscription_id == sub_id)
        ).scalar_one_or_none()
        if lic is None:
            return False
        if event_type == "invoice.paid":
            lic.status = "active"
            period_ts = None
            lines = ((obj.get("lines") or {}).get("data") or [])
            if lines and isinstance(lines[0], dict):
                period_ts = (lines[0].get("period") or {}).get("end")
            if isinstance(period_ts, (int, float)) and period_ts > 0:
                lic.current_period_end = datetime.fromtimestamp(float(period_ts), tz=timezone.utc)
            else:
                lic.current_period_end = _plan_period_fallback(lic.plan, datetime.now(timezone.utc))
            pi = str(obj.get("payment_intent") or "").strip()
            if pi:
                lic.stripe_payment_intent_id = pi
            db.commit()
        else:
            lic.status = "past_due"
            db.commit()
            plan_info = PLAN_CATALOG.get(lic.plan, {"label": lic.plan})
            send_email(
                to=lic.email,
                subject="Action needed: Pro3DWorks renewal payment failed",
                html=software_payment_failed_html(
                    full_name=lic.full_name,
                    product_name="Pro3DWorks",
                    plan_label=plan_info["label"],
                    license_key=lic.license_key,
                    portal_url=f"{settings.SITE_URL}/products/pro3dworks#manage-license",
                ),
                db=db,
                scope_kind="software",
                scope_code=lic.product,
                audience="buyer",
                template="software_payment_failed",
            )
        return True

    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub_id = str(obj.get("id") or "").strip()
        if not sub_id:
            return False
        lic = db.execute(
            select(SoftwareLicense).where(SoftwareLicense.stripe_subscription_id == sub_id)
        ).scalar_one_or_none()
        if lic is None:
            return False
        if event_type == "customer.subscription.deleted":
            lic.status = "canceled"
        else:
            st = str(obj.get("status") or "").lower()
            if st in ("active", "trialing"):
                lic.status = "active"
            elif st in ("past_due", "unpaid", "incomplete"):
                lic.status = "past_due"
            elif st in ("canceled", "incomplete_expired"):
                lic.status = "canceled"
            period_end = _extract_sub_period_end(obj)
            if period_end is not None:
                lic.current_period_end = period_end
            items = ((obj.get("items") or {}).get("data") or [])
            if items and isinstance(items[0], dict):
                price_id = str(((items[0].get("price") or {}).get("id")) or "").strip()
                mapped_plan = plan_from_stripe_price_id(price_id)
                if mapped_plan and mapped_plan in PLAN_CATALOG:
                    lic.plan = mapped_plan
                    lic.max_seats = int(PLAN_CATALOG[mapped_plan]["max_seats"])
                    lic.allow_offline_file = bool(PLAN_CATALOG[mapped_plan]["allow_offline_file"])
        db.commit()
        return True

    if event_type in ("charge.refunded", "charge.dispute.created"):
        pi = str(obj.get("payment_intent") or "").strip()
        if not pi:
            return False
        if event_type == "charge.refunded":
            partial = obj.get("refunded") is False and int(obj.get("amount_refunded") or 0) < int(obj.get("amount") or 0)
            if partial:
                return False
        lic = db.execute(
            select(SoftwareLicense).where(SoftwareLicense.stripe_payment_intent_id == pi)
        ).scalar_one_or_none()
        if lic is None:
            return False
        lic.status = "revoked"
        db.commit()
        log.info("Revoked software license %s (%s)", lic.license_key, event_type)
        return True

    return False
