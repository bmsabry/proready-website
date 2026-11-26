"""Desktop software trials, license activation, Stripe Checkout & Billing Portal."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..emailer import (
    send_email,
    software_billing_portal_html,
    software_license_delivered_html,
)
from ..models import SoftwareActivation, SoftwareLicense, SoftwareTrial
from ..software_licensing import (
    CURRENT_MAJOR_VERSION,
    PLAN_CATALOG,
    activate_machine_seat,
    generate_license_key,
    handle_software_stripe_event,
    issue_license_token,
    issue_trial_token,
    mask_license_key,
    public_key_b64,
    start_or_resume_trial,
)
from . import checkout as checkout_routes

log = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/software", tags=["software-billing"])

admin_router = APIRouter(
    prefix="/api/admin/software",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

ALLOWED_PRODUCTS = frozenset({"pro3dworks"})


def _validate_product(product: str) -> str:
    clean = str(product or "").strip().lower()
    if clean not in ALLOWED_PRODUCTS:
        raise HTTPException(status_code=404, detail="Software product not found.")
    return clean


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _is_license_entitled(lic: SoftwareLicense, now: Optional[datetime] = None) -> bool:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    if lic.status == "revoked":
        return False
    if lic.plan == "perpetual":
        return lic.status == "active"
    period_end = _ensure_utc(lic.current_period_end)
    grace_days = max(1, int(settings.SOFTWARE_OFFLINE_GRACE_DAYS))
    if lic.status == "active":
        return period_end is None or (period_end + timedelta(days=grace_days)) > now
    if lic.status == "past_due":
        return period_end is not None and (period_end + timedelta(days=grace_days)) > now
    if lic.status == "canceled":
        return period_end is not None and period_end > now
    return False


def _license_summary(lic: SoftwareLicense, used_seats: Optional[int] = None) -> dict:
    info = PLAN_CATALOG.get(lic.plan, {})
    return {
        "id": lic.id,
        "product": lic.product,
        "license_key": lic.license_key,
        "license_key_masked": mask_license_key(lic.license_key),
        "plan": lic.plan,
        "plan_label": info.get("label", lic.plan),
        "tier": info.get("tier", "pro"),
        "status": lic.status,
        "email": lic.email,
        "full_name": lic.full_name,
        "company": lic.company,
        "max_seats": lic.max_seats,
        "seats_used": used_seats,
        "amount_cents": lic.amount_cents,
        "currency": lic.currency,
        "current_period_end": lic.current_period_end.isoformat() if lic.current_period_end else None,
        "updates_until": lic.updates_until.isoformat() if lic.updates_until else None,
        "valid_major_version": lic.valid_major_version,
        "allow_offline_file": lic.allow_offline_file,
        "created_at": lic.created_at.isoformat() if lic.created_at else None,
    }


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class TrialStartIn(BaseModel):
    product: str = Field(default="pro3dworks", max_length=64)
    email: EmailStr
    full_name: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=200)
    machine_id: str = Field(min_length=8, max_length=128)
    machine_name: str = Field(default="", max_length=200)
    app_version: str = Field(default="", max_length=32)


class LicenseActivateIn(BaseModel):
    product: str = Field(default="pro3dworks", max_length=64)
    license_key: str = Field(min_length=8, max_length=64)
    machine_id: str = Field(min_length=8, max_length=128)
    machine_name: str = Field(default="", max_length=200)
    app_version: str = Field(default="", max_length=32)


class LicenseDeactivateIn(BaseModel):
    product: str = Field(default="pro3dworks", max_length=64)
    license_key: str = Field(min_length=8, max_length=64)
    machine_id: str = Field(min_length=8, max_length=128)


class SoftwareCheckoutIn(BaseModel):
    product: str = Field(default="pro3dworks", max_length=64)
    plan: str = Field(min_length=3, max_length=32)
    email: Optional[EmailStr] = None
    full_name: str = Field(default="", max_length=200)
    machine_id: str = Field(default="", max_length=128)
    machine_name: str = Field(default="", max_length=200)


class BillingPortalIn(BaseModel):
    license_key: str = Field(default="", max_length=64)
    email: Optional[EmailStr] = None


class AdminCompLicenseIn(BaseModel):
    product: str = Field(default="pro3dworks", max_length=64)
    plan: str = Field(default="perpetual", max_length=32)
    email: EmailStr
    full_name: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=200)
    max_seats: Optional[int] = Field(default=None, ge=1, le=500)
    days_valid: Optional[int] = Field(default=None, ge=1, le=3650)
    allow_offline_file: Optional[bool] = None
    notes: str = Field(default="", max_length=1000)
    send_email_to_user: bool = False


class AdminRevokeIn(BaseModel):
    reason: str = Field(default="", max_length=300)


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@public_router.get("/plans")
def get_plans(product: str = "pro3dworks") -> dict:
    clean = _validate_product(product)
    settings = get_settings()
    plans = [
        {
            "code": p["code"],
            "tier": p["tier"],
            "label": p["label"],
            "short_label": p["short_label"],
            "amount_cents": p["amount_cents"],
            "regular_cents": p["regular_cents"],
            "currency": p["currency"],
            "interval": p["interval"],
            "max_seats": p["max_seats"],
            "allow_offline_file": p["allow_offline_file"],
            "description": p["description"],
        }
        for p in PLAN_CATALOG.values()
        if p["product"] == clean
    ]
    return {
        "product": clean,
        "trial_days": settings.SOFTWARE_TRIAL_DAYS,
        "offline_grace_days": settings.SOFTWARE_OFFLINE_GRACE_DAYS,
        "stripe_enabled": bool(settings.STRIPE_SECRET_KEY),
        "public_key_b64": public_key_b64(),
        "plans": plans,
    }


@public_router.post("/trial/start")
def start_trial(body: TrialStartIn, db: Session = Depends(get_db)) -> dict:
    product = _validate_product(body.product)
    outcome, row, meta = start_or_resume_trial(
        db,
        product=product,
        email=str(body.email),
        machine_id=body.machine_id,
        full_name=body.full_name,
        company=body.company,
        machine_name=body.machine_name,
        app_version=body.app_version,
    )
    if outcome == "expired":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Your 15-day free trial has ended. Purchase Pro, Shop, or Perpetual "
                "to unlock full Pro features, or continue with the Free Basic 3D Viewer."
            ),
        )
    if outcome == "machine_used":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A 15-day free trial has already been used on this computer. "
                "Activate an existing license key or purchase a plan to continue."
            ),
        )
    if outcome == "email_used":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A 15-day free trial has already been claimed for this email address."
            ),
        )

    token = issue_trial_token(row)
    return {
        "ok": True,
        "status": outcome,
        "token": token,
        "email": row.email,
        "machine_id": row.machine_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "days_remaining": meta["days_remaining"],
    }


@public_router.post("/license/activate")
def activate_license(body: LicenseActivateIn, db: Session = Depends(get_db)) -> dict:
    product = _validate_product(body.product)
    key = body.license_key.strip().upper()
    lic = db.execute(
        select(SoftwareLicense).where(
            SoftwareLicense.product == product,
            SoftwareLicense.license_key == key,
        )
    ).scalar_one_or_none()
    if lic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="License key not found. Check for typos or contact support.",
        )
    if lic.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This license key has been revoked.",
        )
    if not _is_license_entitled(lic):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This subscription is inactive or expired. Renew in the Customer "
                "Billing Portal or purchase a new plan."
            ),
        )

    ok, reason, used_seats = activate_machine_seat(
        db,
        lic,
        machine_id=body.machine_id,
        machine_name=body.machine_name,
        app_version=body.app_version,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"All {lic.max_seats} workstation seats for this license are currently "
                "active. Deactivate an unused PC from Pro3DWorks -> License Manager "
                "before activating another computer."
            ),
        )

    token = issue_license_token(lic, machine_id=body.machine_id.strip().lower())
    return {
        "ok": True,
        "activation": reason,
        "token": token,
        "entitled": True,
        "seats_used": used_seats,
        "max_seats": lic.max_seats,
        "license": _license_summary(lic, used_seats),
    }


@public_router.post("/license/refresh")
def refresh_license(body: LicenseActivateIn, db: Session = Depends(get_db)) -> dict:
    product = _validate_product(body.product)
    key = body.license_key.strip().upper()
    clean_machine = body.machine_id.strip().lower()

    lic = db.execute(
        select(SoftwareLicense).where(
            SoftwareLicense.product == product,
            SoftwareLicense.license_key == key,
        )
    ).scalar_one_or_none()
    if lic is None:
        raise HTTPException(status_code=404, detail="License key not found.")

    active_rows = db.execute(
        select(SoftwareActivation).where(
            SoftwareActivation.license_id == lic.id,
            SoftwareActivation.deactivated_at.is_(None),
        )
    ).scalars().all()
    seat = next((r for r in active_rows if r.machine_id == clean_machine), None)
    if seat is None:
        return {
            "ok": True,
            "entitled": False,
            "status": "seat_deactivated",
            "token": None,
            "seats_used": len(active_rows),
            "max_seats": lic.max_seats,
        }

    seat.last_seen_at = datetime.now(timezone.utc)
    if body.app_version.strip():
        seat.app_version = body.app_version.strip()[:32]
    db.commit()

    entitled = _is_license_entitled(lic)
    token = issue_license_token(lic, machine_id=clean_machine) if entitled else None
    return {
        "ok": True,
        "entitled": entitled,
        "status": lic.status,
        "token": token,
        "seats_used": len(active_rows),
        "max_seats": lic.max_seats,
        "license": _license_summary(lic, len(active_rows)),
    }


@public_router.post("/license/deactivate")
def deactivate_license(body: LicenseDeactivateIn, db: Session = Depends(get_db)) -> dict:
    product = _validate_product(body.product)
    key = body.license_key.strip().upper()
    clean_machine = body.machine_id.strip().lower()

    lic = db.execute(
        select(SoftwareLicense).where(
            SoftwareLicense.product == product,
            SoftwareLicense.license_key == key,
        )
    ).scalar_one_or_none()
    if lic is None:
        raise HTTPException(status_code=404, detail="License key not found.")

    row = db.execute(
        select(SoftwareActivation).where(
            SoftwareActivation.license_id == lic.id,
            SoftwareActivation.machine_id == clean_machine,
            SoftwareActivation.deactivated_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        return {"ok": True, "released": False}

    row.deactivated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "released": True}


@public_router.post("/checkout")
def create_software_checkout(
    body: SoftwareCheckoutIn, db: Session = Depends(get_db)  # noqa: ARG001
) -> dict:
    product = _validate_product(body.product)
    plan_info = PLAN_CATALOG.get(body.plan)
    if plan_info is None or plan_info["product"] != product:
        raise HTTPException(status_code=404, detail="Plan not found.")

    settings = get_settings()
    stripe = checkout_routes._stripe()

    configured_price = str(getattr(settings, plan_info["price_setting"], "") or "").strip()
    if configured_price:
        line_items = [{"price": configured_price, "quantity": 1}]
    else:
        price_data: dict = {
            "currency": plan_info["currency"],
            "unit_amount": plan_info["amount_cents"],
            "product_data": {
                "name": plan_info["label"],
                "description": plan_info["description"][:300],
            },
        }
        if plan_info["interval"]:
            price_data["recurring"] = {"interval": plan_info["interval"]}
        line_items = [{"quantity": 1, "price_data": price_data}]

    mode = "subscription" if plan_info["interval"] else "payment"
    meta = {
        "kind": "software_license",
        "product": product,
        "plan": plan_info["code"],
        "machine_id": body.machine_id.strip().lower()[:128],
        "machine_name": body.machine_name.strip()[:120],
        "full_name": body.full_name.strip()[:120],
    }

    kwargs: dict = {
        "mode": mode,
        "line_items": line_items,
        "success_url": (
            f"{settings.SITE_URL}/products/pro3dworks/welcome"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),
        "cancel_url": f"{settings.SITE_URL}/products/pro3dworks#pricing",
        "metadata": meta,
        "billing_address_collection": "auto",
        "allow_promotion_codes": True,
        "tax_id_collection": {"enabled": True},
    }
    if body.email:
        kwargs["customer_email"] = str(body.email).strip().lower()
    if settings.STRIPE_AUTOMATIC_TAX:
        kwargs["automatic_tax"] = {"enabled": True}
    if mode == "subscription":
        kwargs["subscription_data"] = {
            "metadata": {
                "kind": "software_license",
                "product": product,
                "plan": plan_info["code"],
            }
        }
    else:
        kwargs["customer_creation"] = "always"

    try:
        session = stripe.checkout.Session.create(**kwargs)
    except Exception as exc:
        log.error("Stripe software checkout create failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start Stripe checkout. Please try again.",
        ) from exc

    return {"url": session.url, "session_id": session.id}


@public_router.get("/checkout/{session_id}")
def software_checkout_status(session_id: str, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    lic = db.execute(
        select(SoftwareLicense).where(
            SoftwareLicense.stripe_checkout_session_id == session_id.strip()
        )
    ).scalar_one_or_none()
    if lic is None:
        return {"status": "pending", "paid": False}
    info = PLAN_CATALOG.get(lic.plan, {})
    return {
        "paid": lic.status in ("active", "past_due"),
        "status": lic.status,
        "license_key": lic.license_key,
        "plan": lic.plan,
        "plan_label": info.get("label", lic.plan),
        "email": lic.email,
        "max_seats": lic.max_seats,
        "current_period_end": lic.current_period_end.isoformat() if lic.current_period_end else None,
        "updates_until": lic.updates_until.isoformat() if lic.updates_until else None,
        "allow_offline_file": lic.allow_offline_file,
        "download_url": f"{settings.SITE_URL}/download/pro3dworks-installer",
    }


@public_router.post("/billing-portal")
def create_billing_portal(body: BillingPortalIn, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    stripe = checkout_routes._stripe()

    key = body.license_key.strip().upper()
    if key:
        lic = db.execute(
            select(SoftwareLicense).where(SoftwareLicense.license_key == key)
        ).scalar_one_or_none()
        if lic is None or not lic.stripe_customer_id:
            raise HTTPException(
                status_code=404,
                detail="No Stripe billing customer found for this license key.",
            )
        try:
            portal = stripe.billing_portal.Session.create(
                customer=lic.stripe_customer_id,
                return_url=f"{settings.SITE_URL}/products/pro3dworks",
            )
        except Exception as exc:
            log.error("Stripe billing portal create failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not open Customer Billing Portal. Please try again.",
            ) from exc
        return {"url": portal.url, "sent": False}

    if body.email:
        clean_email = str(body.email).strip().lower()
        lic = db.execute(
            select(SoftwareLicense)
            .where(
                SoftwareLicense.email == clean_email,
                SoftwareLicense.stripe_customer_id != "",
                SoftwareLicense.status != "revoked",
            )
            .order_by(SoftwareLicense.created_at.desc(), SoftwareLicense.id.desc())
        ).scalars().first()
        if lic is not None:
            try:
                portal = stripe.billing_portal.Session.create(
                    customer=lic.stripe_customer_id,
                    return_url=f"{settings.SITE_URL}/products/pro3dworks",
                )
                info = PLAN_CATALOG.get(lic.plan, {"label": lic.plan})
                send_email(
                    to=clean_email,
                    subject="Manage your Pro3DWorks billing & invoices",
                    html=software_billing_portal_html(
                        product_name="Pro3DWorks",
                        license_key=lic.license_key,
                        plan_label=info["label"],
                        portal_url=portal.url,
                    ),
                    db=db,
                    scope_kind="software",
                    scope_code=lic.product,
                    audience="buyer",
                    template="software_billing_portal",
                )
            except Exception as exc:
                log.warning("Email billing portal failed for %s: %s", clean_email, exc)
        return {
            "url": None,
            "sent": True,
            "message": (
                "If a Stripe subscription or purchase exists for that email, we have sent "
                "your secure Customer Billing Portal link to your inbox."
            ),
        }

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Provide either a license key or an email address.",
    )


@public_router.post("/webhook/stripe")
async def software_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhooks are not configured.",
        )
    payload = await request.body()
    stripe = checkout_routes._stripe()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        log.warning("Rejected software Stripe webhook: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature."
        ) from exc

    handled = handle_software_stripe_event(db, event["type"], dict(event["data"]["object"]))
    return {"received": True, "handled": handled}


# ---------------------------------------------------------------------------
# Admin license & trial endpoints
# ---------------------------------------------------------------------------


@admin_router.get("/licenses")
def admin_list_licenses(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(SoftwareLicense).order_by(
            SoftwareLicense.created_at.desc(), SoftwareLicense.id.desc()
        )
    ).scalars().all()
    counts = {
        lic_id: int(n)
        for lic_id, n in db.execute(
            select(SoftwareActivation.license_id, func.count(SoftwareActivation.id))
            .where(SoftwareActivation.deactivated_at.is_(None))
            .group_by(SoftwareActivation.license_id)
        ).all()
    }
    return [_license_summary(r, counts.get(r.id, 0)) for r in rows]


@admin_router.post("/licenses/comp", status_code=status.HTTP_201_CREATED)
def admin_issue_comp_license(
    body: AdminCompLicenseIn, db: Session = Depends(get_db)
) -> dict:
    product = _validate_product(body.product)
    plan_info = PLAN_CATALOG.get(body.plan)
    if plan_info is None:
        raise HTTPException(status_code=404, detail="Unknown plan.")

    settings = get_settings()
    now = datetime.now(timezone.utc)
    lic_key = generate_license_key()
    while db.execute(
        select(SoftwareLicense.id).where(SoftwareLicense.license_key == lic_key)
    ).first() is not None:
        lic_key = generate_license_key()

    period_end = (
        None
        if body.plan == "perpetual"
        else now + timedelta(days=int(body.days_valid or (366 if "yearly" in body.plan else 32)))
    )
    updates_until = now + timedelta(days=365) if body.plan == "perpetual" else period_end

    lic = SoftwareLicense(
        product=product,
        license_key=lic_key,
        plan=body.plan,
        status="active",
        email=str(body.email).strip().lower(),
        full_name=body.full_name.strip()[:200],
        company=body.company.strip()[:200],
        max_seats=int(body.max_seats or plan_info["max_seats"]),
        amount_cents=0,
        currency="usd",
        current_period_end=period_end,
        updates_until=updates_until,
        valid_major_version=CURRENT_MAJOR_VERSION,
        allow_offline_file=(
            bool(body.allow_offline_file)
            if body.allow_offline_file is not None
            else bool(plan_info["allow_offline_file"])
        ),
        notes=body.notes.strip()[:1000],
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)

    if body.send_email_to_user:
        send_email(
            to=lic.email,
            subject=f"Your Pro3DWorks license key ({plan_info['short_label']})",
            html=software_license_delivered_html(
                full_name=lic.full_name,
                product_name="Pro3DWorks",
                plan_label=plan_info["label"],
                license_key=lic.license_key,
                max_seats=lic.max_seats,
                download_url=f"{settings.SITE_URL}/download/pro3dworks-installer",
                portal_url="",
                current_period_end=lic.current_period_end,
                updates_until=lic.updates_until,
            ),
            db=db,
            scope_kind="software",
            scope_code=product,
            audience="buyer",
            template="software_license_delivered",
        )

    out = _license_summary(lic, 0)
    if lic.allow_offline_file:
        out["offline_token"] = issue_license_token(lic, machine_id="*")
    return out


@admin_router.get("/licenses/{license_id}/offline-token")
def admin_export_offline_token(
    license_id: int, machine_id: str = "*", db: Session = Depends(get_db)
) -> dict:
    lic = db.get(SoftwareLicense, license_id)
    if lic is None:
        raise HTTPException(status_code=404, detail="License not found.")
    if not _is_license_entitled(lic):
        raise HTTPException(status_code=409, detail="License is not currently active.")
    target = machine_id.strip().lower() or "*"
    return {
        "license_key": lic.license_key,
        "machine_id": target,
        "filename": f"{lic.license_key.lower()}.p3dwlic",
        "token": issue_license_token(lic, machine_id=target),
    }


@admin_router.post("/licenses/{license_id}/revoke")
def admin_revoke_license(
    license_id: int, body: AdminRevokeIn, db: Session = Depends(get_db)
) -> dict:
    lic = db.get(SoftwareLicense, license_id)
    if lic is None:
        raise HTTPException(status_code=404, detail="License not found.")
    lic.status = "revoked"
    if body.reason.strip():
        lic.notes = (lic.notes + f"\nRevoked: {body.reason.strip()}").strip()
    db.commit()
    return {"ok": True, "license": _license_summary(lic)}


@admin_router.get("/trials")
def admin_list_trials(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(SoftwareTrial)
        .order_by(SoftwareTrial.created_at.desc(), SoftwareTrial.id.desc())
        .limit(200)
    ).scalars().all()
    return [
        {
            "id": t.id,
            "product": t.product,
            "email": t.email,
            "full_name": t.full_name,
            "company": t.company,
            "machine_id": t.machine_id[:12] + "…" if len(t.machine_id) > 12 else t.machine_id,
            "machine_name": t.machine_name,
            "app_version": t.app_version,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        }
        for t in rows
    ]
