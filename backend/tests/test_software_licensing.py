"""Desktop software licensing, 15-day trial & Stripe subscription tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest  # noqa: E402

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import SoftwareActivation, SoftwareLicense, SoftwareTrial  # noqa: E402
from app.routes import checkout as checkout_routes  # noqa: E402
from app.software_licensing import verify_envelope  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_plans_catalog_and_ed25519_public_key(client):
    r = client.get("/api/software/plans?product=pro3dworks")
    assert r.status_code == 200
    body = r.json()
    assert body["product"] == "pro3dworks"
    assert body["trial_days"] == 15
    assert len(body["public_key_b64"]) == 44  # 32-byte base64
    codes = {p["code"]: p for p in body["plans"]}
    assert codes["pro_monthly"]["amount_cents"] == 2900
    assert codes["pro_yearly"]["amount_cents"] == 24900
    assert codes["shop_monthly"]["amount_cents"] == 14900
    assert codes["shop_yearly"]["amount_cents"] == 139000
    assert codes["perpetual"]["amount_cents"] == 59900
    assert codes["perpetual"]["interval"] is None


def test_trial_15_day_lifecycle_and_single_trial_enforcement(client):
    c = client
    if True:
        # 1. Start fresh 15-day trial
        r = c.post(
            "/api/software/trial/start",
            json={
                "product": "pro3dworks",
                "email": "machinist1@shop.com",
                "full_name": "Alex Machinist",
                "machine_id": "mach-aaa-11111111",
                "machine_name": "OMAX-PC-01",
                "app_version": "3.0.0",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "started"
        assert data["days_remaining"] == 15
        claims = verify_envelope(data["token"])
        assert claims is not None
        assert claims["kind"] == "trial"
        assert claims["machine_id"] == "mach-aaa-11111111"
        assert claims["exp"] - claims["iat"] >= 14 * 86400

        # Tampered token must fail signature verification
        parts = data["token"].split(".")
        bad = f"{parts[0]}.{parts[1]}.{'A' * len(parts[2])}"
        assert verify_envelope(bad) is None

        # 2. Same email + same machine while active -> idempotent resume
        r2 = c.post(
            "/api/software/trial/start",
            json={
                "product": "pro3dworks",
                "email": "machinist1@shop.com",
                "machine_id": "mach-aaa-11111111",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "resumed"

        # 3. Different email on same machine -> blocked (409)
        r3 = c.post(
            "/api/software/trial/start",
            json={
                "product": "pro3dworks",
                "email": "other@shop.com",
                "machine_id": "mach-aaa-11111111",
            },
        )
        assert r3.status_code == 409

        # 4. Same email on different machine -> blocked (409)
        r4 = c.post(
            "/api/software/trial/start",
            json={
                "product": "pro3dworks",
                "email": "machinist1@shop.com",
                "machine_id": "mach-bbb-22222222",
            },
        )
        assert r4.status_code == 409

        # 5. Once expired -> same machine + email refused (409)
        db = SessionLocal()
        try:
            row = db.query(SoftwareTrial).filter(SoftwareTrial.email == "machinist1@shop.com").one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()
        finally:
            db.close()

        r5 = c.post(
            "/api/software/trial/start",
            json={
                "product": "pro3dworks",
                "email": "machinist1@shop.com",
                "machine_id": "mach-aaa-11111111",
            },
        )
        assert r5.status_code == 409


def test_stripe_checkout_webhook_activation_renewal_and_portal(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_software")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_software")

    created_sessions = []

    class FakeStripe:
        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    created_sessions.append(kwargs)
                    return SimpleNamespace(
                        id="cs_sw_pro_yearly_1",
                        url="https://checkout.stripe.com/pay/cs_sw_pro_yearly_1",
                    )

        class billing_portal:
            class Session:
                @staticmethod
                def create(**kwargs):
                    return SimpleNamespace(url="https://billing.stripe.com/p/session_test_1")

        class Subscription:
            @staticmethod
            def retrieve(sub_id, **kwargs):
                return {
                    "id": sub_id,
                    "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=365)).timestamp()),
                }

        class Webhook:
            @staticmethod
            def construct_event(payload, sig, secret):
                raise AssertionError("overridden per call")

    monkeypatch.setattr(checkout_routes, "_stripe", lambda: FakeStripe)

    c = client
    if True:
        # 1. Create Checkout Session for Pro Yearly + Perpetual
        r = c.post(
            "/api/software/checkout",
            json={
                "product": "pro3dworks",
                "plan": "pro_yearly",
                "email": "buyer@waterjet.io",
                "machine_id": "mach-waterjet-01",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] == "cs_sw_pro_yearly_1"
        assert created_sessions[-1]["mode"] == "subscription"
        assert created_sessions[-1]["line_items"][0]["price_data"]["unit_amount"] == 24900
        assert created_sessions[-1]["line_items"][0]["price_data"]["recurring"] == {"interval": "year"}

        r_perp = c.post(
            "/api/software/checkout",
            json={"product": "pro3dworks", "plan": "perpetual", "email": "own@shop.io"},
        )
        assert r_perp.status_code == 200
        assert created_sessions[-1]["mode"] == "payment"
        assert created_sessions[-1]["customer_creation"] == "always"
        assert created_sessions[-1]["line_items"][0]["price_data"]["unit_amount"] == 59900

        # 2. Checkout poll starts pending before webhook fires
        r_poll = c.get("/api/software/checkout/cs_sw_pro_yearly_1")
        assert r_poll.status_code == 200
        assert r_poll.json()["status"] == "pending"
        assert r_poll.json()["paid"] is False

        # 3. Fire checkout.session.completed on existing /api/academy/webhook/stripe
        event_completed = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_sw_pro_yearly_1",
                    "payment_status": "paid",
                    "amount_total": 24900,
                    "currency": "usd",
                    "customer": "cus_sw_1",
                    "subscription": "sub_sw_1",
                    "payment_intent": "pi_sw_1",
                    "customer_details": {"email": "buyer@waterjet.io", "name": "Waterjet Owner"},
                    "metadata": {
                        "kind": "software_license",
                        "product": "pro3dworks",
                        "plan": "pro_yearly",
                        "machine_id": "mach-waterjet-01",
                        "machine_name": "CAM-DESK",
                    },
                }
            },
        }
        monkeypatch.setattr(FakeStripe.Webhook, "construct_event", lambda p, s, sec: event_completed)
        wh = c.post("/api/academy/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"})
        assert wh.status_code == 200

        # Replay must be idempotent (only 1 license created)
        wh2 = c.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"})
        assert wh2.status_code == 200
        db = SessionLocal()
        try:
            lics = db.query(SoftwareLicense).filter(SoftwareLicense.stripe_checkout_session_id == "cs_sw_pro_yearly_1").all()
            assert len(lics) == 1
            lic_key = lics[0].license_key
        finally:
            db.close()

        # 4. Checkout poll now returns license key
        r_poll2 = c.get("/api/software/checkout/cs_sw_pro_yearly_1")
        assert r_poll2.json()["status"] == "active"
        assert r_poll2.json()["paid"] is True
        assert r_poll2.json()["license_key"] == lic_key

        # 5. Pre-activated PC refreshes/activates, plus up to 3 seats total, 4th blocked
        for idx, mid in enumerate(["mach-waterjet-01", "mach-waterjet-02", "mach-waterjet-03"], start=1):
            ra = c.post(
                "/api/software/license/activate",
                json={"product": "pro3dworks", "license_key": lic_key, "machine_id": mid},
            )
            assert ra.status_code == 200, ra.text
            assert ra.json()["seats_used"] == idx
            claims = verify_envelope(ra.json()["token"])
            assert claims["kind"] == "license"
            assert claims["license_key"] == lic_key
            assert claims["grace_until"] > claims["exp"]

        ra4 = c.post(
            "/api/software/license/activate",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-04"},
        )
        assert ra4.status_code == 409

        # Deactivating one machine opens seat for 4th PC
        rd = c.post(
            "/api/software/license/deactivate",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-02"},
        )
        assert rd.status_code == 200 and rd.json()["released"] is True

        ra4_ok = c.post(
            "/api/software/license/activate",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-04"},
        )
        assert ra4_ok.status_code == 200

        # Deactivated PC refresh shows seat_deactivated
        ref_old = c.post(
            "/api/software/license/refresh",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-02"},
        )
        assert ref_old.status_code == 200
        assert ref_old.json()["entitled"] is False
        assert ref_old.json()["status"] == "seat_deactivated"

        # 6. Billing portal via license key returns URL directly; email sends message without leaking URL
        bp_key = c.post("/api/software/billing-portal", json={"license_key": lic_key})
        assert bp_key.status_code == 200
        assert bp_key.json()["url"] == "https://billing.stripe.com/p/session_test_1"

        bp_email = c.post("/api/software/billing-portal", json={"email": "unknown@example.com"})
        assert bp_email.status_code == 200
        assert bp_email.json()["sent"] is True
        assert bp_email.json()["url"] is None

        # 7. Payment failure -> past_due; invoice.paid -> active; subscription.deleted -> canceled
        monkeypatch.setattr(
            FakeStripe.Webhook,
            "construct_event",
            lambda p, s, sec: {"type": "invoice.payment_failed", "data": {"object": {"subscription": "sub_sw_1"}}},
        )
        assert c.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200
        ref_pd = c.post(
            "/api/software/license/refresh",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-01"},
        )
        assert ref_pd.json()["status"] == "past_due"

        future_end = int((datetime.now(timezone.utc) + timedelta(days=400)).timestamp())
        monkeypatch.setattr(
            FakeStripe.Webhook,
            "construct_event",
            lambda p, s, sec: {
                "type": "invoice.paid",
                "data": {"object": {"subscription": "sub_sw_1", "payment_intent": "pi_sw_2", "lines": {"data": [{"period": {"end": future_end}}]}}},
            },
        )
        assert c.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200

        # Also verify Stripe 2025-03-31.basil / 2026-02-25.clover invoice shape (no top-level subscription)
        monkeypatch.setattr(
            FakeStripe.Webhook,
            "construct_event",
            lambda p, s, sec: {
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "parent": {
                            "type": "subscription_details",
                            "subscription_details": {"subscription": "sub_sw_1"},
                        }
                    }
                },
            },
        )
        assert c.post("/api/academy/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200
        assert (
            c.post(
                "/api/software/license/refresh",
                json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-01"},
            ).json()["status"]
            == "past_due"
        )

        monkeypatch.setattr(
            FakeStripe.Webhook,
            "construct_event",
            lambda p, s, sec: {
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "parent": {
                            "type": "subscription_details",
                            "subscription_details": {"subscription": "sub_sw_1"},
                        },
                        "payments": {"data": [{"payment": {"payment_intent": "pi_sw_clover_3"}}]},
                        "lines": {"data": [{"period": {"end": future_end}}]},
                    }
                },
            },
        )
        assert c.post("/api/academy/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200
        ref_clover_ok = c.post(
            "/api/software/license/refresh",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-01"},
        )
        assert ref_clover_ok.json()["status"] == "active"
        db = SessionLocal()
        try:
            assert (
                db.query(SoftwareLicense).filter(SoftwareLicense.license_key == lic_key).one().stripe_payment_intent_id
                == "pi_sw_clover_3"
            )
        finally:
            db.close()

        monkeypatch.setattr(
            FakeStripe.Webhook,
            "construct_event",
            lambda p, s, sec: {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_sw_1"}}},
        )
        assert c.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200

        # Expire period_end and verify refresh reports entitled=False
        db = SessionLocal()
        try:
            row = db.query(SoftwareLicense).filter(SoftwareLicense.license_key == lic_key).one()
            row.current_period_end = datetime.now(timezone.utc) - timedelta(days=1)
            db.commit()
        finally:
            db.close()

        ref_dead = c.post(
            "/api/software/license/refresh",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-waterjet-01"},
        )
        assert ref_dead.json()["status"] == "canceled"
        assert ref_dead.json()["entitled"] is False


def test_admin_comp_perpetual_offline_file_and_revoke(client):
    c = client
    if True:
        r = c.post(
            "/api/admin/software/licenses/comp",
            headers=ADMIN,
            json={
                "product": "pro3dworks",
                "plan": "perpetual",
                "email": "itar-lab@defense.org",
                "full_name": "ITAR Lab",
                "max_seats": 5,
                "allow_offline_file": True,
                "notes": "Air-gapped workstation test",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["plan"] == "perpetual"
        claims = verify_envelope(body["offline_token"])
        assert claims is not None
        assert claims["exp"] is None
        assert claims["machine_id"] == "*"
        assert claims["max_seats"] == 5

        lic_id = body["id"]
        listed = c.get("/api/admin/software/licenses", headers=ADMIN).json()
        assert any(row["id"] == lic_id for row in listed)

        trials = c.get("/api/admin/software/trials", headers=ADMIN).json()
        assert isinstance(trials, list)

        rev = c.post(f"/api/admin/software/licenses/{lic_id}/revoke", headers=ADMIN, json={"reason": "test"})
        assert rev.status_code == 200
        assert rev.json()["license"]["status"] == "revoked"

        off = c.get(f"/api/admin/software/licenses/{lic_id}/offline-token", headers=ADMIN)
        assert off.status_code == 409


def test_software_email_templates_render_cleanly():
    from app import emailer as E

    samples = [
        E.software_trial_welcome_html(
            full_name="Sam <Shop>",
            product_name="Pro3DWorks",
            expires_at=datetime(2026, 12, 9, tzinfo=timezone.utc),
            machine_name="SHOP-PC",
            buy_url="https://proreadyengineer.com/products/pro3dworks#pricing",
            download_url="https://proreadyengineer.com/download/pro3dworks-installer",
        ),
        E.software_license_delivered_html(
            full_name="Sam <Shop>",
            product_name="Pro3DWorks",
            plan_label="Pro Individual (Yearly)",
            license_key="P3DW-2345-6789-ABCD-EFGH",
            max_seats=3,
            download_url="https://proreadyengineer.com/download/pro3dworks-installer",
            portal_url="https://proreadyengineer.com/products/pro3dworks#manage-license",
            current_period_end=datetime(2027, 11, 24, tzinfo=timezone.utc),
        ),
        E.software_payment_failed_html(
            full_name="Sam",
            product_name="Pro3DWorks",
            plan_label="Pro Monthly",
            license_key="P3DW-2345-6789-ABCD-EFGH",
            portal_url="https://proreadyengineer.com/products/pro3dworks#manage-license",
        ),
        E.software_billing_portal_html(
            product_name="Pro3DWorks",
            license_key="P3DW-2345-6789-ABCD-EFGH",
            plan_label="Pro Monthly",
            portal_url="https://billing.stripe.com/session/123",
        ),
        E.software_admin_sale_html(
            product_name="Pro3DWorks",
            plan_label="Pro Yearly",
            license_key="P3DW-2345-6789-ABCD-EFGH",
            buyer_email="sam@shop.com",
            amount_display="$249.00 USD",
        ),
    ]
    for html in samples:
        assert "linear-gradient" not in html
        assert "color:" in html
        assert "<script" not in html
        assert "<Shop>" not in html
        text = E.html_to_text(html)
        assert len(text) > 60


def test_revoked_license_refresh_without_seat_and_checkout_status_redaction(client):
    """P5-01 & P5-13: revoked license reports status='revoked' even with no seat,
    and checkout status hides license_key when not active/past_due."""
    r = client.post(
        "/api/admin/software/licenses/comp",
        headers=ADMIN,
        json={
            "product": "pro3dworks",
            "plan": "pro_yearly",
            "email": "revoked-no-seat@shop.com",
        },
    )
    assert r.status_code == 201
    lic_id = r.json()["id"]
    lic_key = r.json()["license_key"]

    db = SessionLocal()
    try:
        lic = db.get(SoftwareLicense, lic_id)
        assert lic is not None
        lic.stripe_checkout_session_id = "cs_revoked_check_1"
        db.commit()
    finally:
        db.close()

    # Before revocation, checkout status reveals license_key
    st_active = client.get("/api/software/checkout/cs_revoked_check_1")
    assert st_active.status_code == 200
    assert st_active.json()["paid"] is True
    assert st_active.json()["license_key"] == lic_key

    # Revoke without any SoftwareActivation seats attached
    rev = client.post(
        f"/api/admin/software/licenses/{lic_id}/revoke",
        headers=ADMIN,
        json={"reason": "chargeback"},
    )
    assert rev.status_code == 200

    # P5-01: refresh_license returns status='revoked' (not 'seat_deactivated')
    ref = client.post(
        "/api/software/license/refresh",
        json={
            "product": "pro3dworks",
            "license_key": lic_key,
            "machine_id": "mach-never-activated-1",
        },
    )
    assert ref.status_code == 200
    body = ref.json()
    assert body["ok"] is True
    assert body["entitled"] is False
    assert body["status"] == "revoked"
    assert body["token"] is None

    # P5-13: checkout status omits license_key when revoked
    st_rev = client.get("/api/software/checkout/cs_revoked_check_1")
    assert st_rev.status_code == 200
    assert st_rev.json()["paid"] is False
    assert st_rev.json()["status"] == "revoked"
    assert st_rev.json()["license_key"] is None


def test_revoked_license_never_resurrected_by_stripe_webhooks(client, monkeypatch):
    """P5-03: invoice.paid and customer.subscription.updated ignore revoked licenses."""
    settings = get_settings()
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_software")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_software")

    r = client.post(
        "/api/admin/software/licenses/comp",
        headers=ADMIN,
        json={
            "product": "pro3dworks",
            "plan": "pro_monthly",
            "email": "no-resurrect@shop.com",
        },
    )
    assert r.status_code == 201
    lic_id = r.json()["id"]
    lic_key = r.json()["license_key"]

    db = SessionLocal()
    try:
        lic = db.get(SoftwareLicense, lic_id)
        assert lic is not None
        lic.stripe_subscription_id = "sub_revoked_guard_1"
        lic.status = "revoked"
        db.commit()
    finally:
        db.close()

    events = [
        {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": "sub_revoked_guard_1",
                    "payment_intent": "pi_late_1",
                }
            },
        },
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_revoked_guard_1",
                    "status": "active",
                }
            },
        },
    ]

    class HookStripe:
        class Webhook:
            current_event: dict = {}

            @staticmethod
            def construct_event(payload, sig, secret):
                return HookStripe.Webhook.current_event

    monkeypatch.setattr(checkout_routes, "_stripe", lambda: HookStripe)

    for evt in events:
        HookStripe.Webhook.current_event = evt
        resp = client.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"})
        assert resp.status_code == 200
        assert resp.json()["handled"] is True

    db = SessionLocal()
    try:
        lic = db.query(SoftwareLicense).filter(SoftwareLicense.license_key == lic_key).one()
        assert lic.status == "revoked"
    finally:
        db.close()


def test_duplicate_seat_deactivation_and_partial_unique_index(client):
    """P5-04: duplicate legacy seats deactivate cleanly without MultipleResultsFound,
    and active (license_id, machine_id) partial unique index allows reactivation after release."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as SASession
    from app.models import Base
    from app.routes.software_billing import LicenseDeactivateIn, deactivate_license
    from app.software_licensing import activate_machine_seat

    # 1. Verify partial unique index & reactivation after deactivation on main DB
    r = client.post(
        "/api/admin/software/licenses/comp",
        headers=ADMIN,
        json={"product": "pro3dworks", "plan": "pro_yearly", "email": "seat-uniq@shop.com"},
    )
    assert r.status_code == 201
    lic_id = r.json()["id"]
    lic_key = r.json()["license_key"]

    assert (
        client.post(
            "/api/software/license/activate",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-uniq-001"},
        ).status_code
        == 200
    )

    db = SessionLocal()
    try:
        with pytest.raises(IntegrityError):
            db.add(SoftwareActivation(license_id=lic_id, machine_id="mach-uniq-001"))
            db.commit()
        db.rollback()
    finally:
        db.close()

    assert (
        client.post(
            "/api/software/license/deactivate",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-uniq-001"},
        ).json()["released"]
        is True
    )
    # Re-activating the same machine after deactivation succeeds under partial unique index
    assert (
        client.post(
            "/api/software/license/activate",
            json={"product": "pro3dworks", "license_key": lic_key, "machine_id": "mach-uniq-001"},
        ).status_code
        == 200
    )

    # 2. Verify deactivate_license handles pre-existing duplicate active rows without MultipleResultsFound
    mem_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(mem_engine)
    with mem_engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX ix_software_activations_active_lic_machine")

    with SASession(mem_engine) as mem_db:
        lic = SoftwareLicense(
            product="pro3dworks",
            license_key="P3DW-DUP1-DUP2-DUP3-DUP4",
            plan="pro_yearly",
            status="active",
            email="dup@shop.com",
            max_seats=3,
        )
        mem_db.add(lic)
        mem_db.commit()
        mem_db.refresh(lic)

        mem_db.add(SoftwareActivation(license_id=lic.id, machine_id="mach-dup-001"))
        mem_db.add(SoftwareActivation(license_id=lic.id, machine_id="mach-dup-001"))
        mem_db.commit()

        res1 = deactivate_license(
            LicenseDeactivateIn(
                product="pro3dworks",
                license_key=lic.license_key,
                machine_id="mach-dup-001",
            ),
            db=mem_db,
        )
        assert res1 == {"ok": True, "released": True}
        remaining_active = (
            mem_db.query(SoftwareActivation)
            .filter(
                SoftwareActivation.license_id == lic.id,
                SoftwareActivation.machine_id == "mach-dup-001",
                SoftwareActivation.deactivated_at.is_(None),
            )
            .all()
        )
        assert remaining_active == []

        res2 = deactivate_license(
            LicenseDeactivateIn(
                product="pro3dworks",
                license_key=lic.license_key,
                machine_id="mach-dup-001",
            ),
            db=mem_db,
        )
        assert res2 == {"ok": True, "released": False}

    # 3. Verify activate_machine_seat recovers idempotently if commit raises IntegrityError
    db = SessionLocal()
    try:
        lic_obj = db.get(SoftwareLicense, lic_id)
        assert lic_obj is not None
        ok, reason, used = activate_machine_seat(
            db, lic_obj, machine_id="mach-uniq-001", machine_name="WORKSTATION"
        )
        assert ok is True and reason == "reused" and used == 1
    finally:
        db.close()


def test_checkout_rejects_empty_payment_status_and_extracts_sub_pi(client, monkeypatch):
    """P5-05: empty payment_status must not fulfill; subscription checkout extracts initial PI."""
    settings = get_settings()
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_software")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_software")

    seen_expand = []

    class SubStripe:
        class Subscription:
            @staticmethod
            def retrieve(sub_id, **kwargs):
                seen_expand.append(kwargs.get("expand"))
                return {
                    "id": sub_id,
                    "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
                    "latest_invoice": {
                        "id": "in_init_1",
                        "payments": {"data": [{"payment_intent": "pi_from_sub_payments_1"}]},
                    },
                }

        class Webhook:
            current_event: dict = {}

            @staticmethod
            def construct_event(payload, sig, secret):
                return SubStripe.Webhook.current_event

    monkeypatch.setattr(checkout_routes, "_stripe", lambda: SubStripe)

    # Empty payment_status must NOT create a license
    SubStripe.Webhook.current_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_empty_pay_status_1",
                "payment_status": "",
                "customer_details": {"email": "unpaid-empty@shop.com"},
                "metadata": {"kind": "software_license", "product": "pro3dworks", "plan": "pro_monthly"},
            }
        },
    }
    wh_empty = client.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"})
    assert wh_empty.status_code == 200
    assert wh_empty.json()["handled"] is True
    db = SessionLocal()
    try:
        assert (
            db.query(SoftwareLicense)
            .filter(SoftwareLicense.stripe_checkout_session_id == "cs_empty_pay_status_1")
            .one_or_none()
            is None
        )
    finally:
        db.close()

    # Paid subscription checkout with empty session payment_intent extracts PI from expanded invoice
    SubStripe.Webhook.current_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_sub_pi_extract_1",
                "payment_status": "paid",
                "customer": "cus_pi_1",
                "subscription": "sub_pi_extract_1",
                "payment_intent": "",
                "customer_details": {"email": "sub-pi@shop.com", "name": "PI Test"},
                "metadata": {"kind": "software_license", "product": "pro3dworks", "plan": "pro_monthly"},
            }
        },
    }
    wh_paid = client.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"})
    assert wh_paid.status_code == 200
    assert seen_expand == [["latest_invoice.payment_intent", "latest_invoice.payments"]]

    db = SessionLocal()
    try:
        lic = (
            db.query(SoftwareLicense)
            .filter(SoftwareLicense.stripe_checkout_session_id == "cs_sub_pi_extract_1")
            .one()
        )
        assert lic.stripe_payment_intent_id == "pi_from_sub_payments_1"
    finally:
        db.close()

    # Refund on extracted PI revokes the subscription license
    SubStripe.Webhook.current_event = {
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_from_sub_payments_1", "refunded": True}},
    }
    assert client.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200
    db = SessionLocal()
    try:
        lic = (
            db.query(SoftwareLicense)
            .filter(SoftwareLicense.stripe_checkout_session_id == "cs_sub_pi_extract_1")
            .one()
        )
        assert lic.status == "revoked"
    finally:
        db.close()

    # Also verify expanded latest_invoice.payment_intent object extraction
    SubStripe.Subscription.retrieve = staticmethod(
        lambda sub_id, **kwargs: {
            "id": sub_id,
            "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
            "latest_invoice": {"id": "in_init_2", "payment_intent": {"id": "pi_from_expanded_obj_2"}},
        }
    )
    SubStripe.Webhook.current_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_sub_pi_extract_2",
                "payment_status": "paid",
                "customer": "cus_pi_2",
                "subscription": "sub_pi_extract_2",
                "payment_intent": "",
                "customer_details": {"email": "sub-pi2@shop.com", "name": "PI Test 2"},
                "metadata": {"kind": "software_license", "product": "pro3dworks", "plan": "pro_monthly"},
            }
        },
    }
    assert client.post("/api/software/webhook/stripe", json={}, headers={"Stripe-Signature": "sig"}).status_code == 200
    db = SessionLocal()
    try:
        lic2 = (
            db.query(SoftwareLicense)
            .filter(SoftwareLicense.stripe_checkout_session_id == "cs_sub_pi_extract_2")
            .one()
        )
        assert lic2.stripe_payment_intent_id == "pi_from_expanded_obj_2"
    finally:
        db.close()


def test_concurrent_integrity_error_recovery_paths(monkeypatch):
    """P5-04: real IntegrityError during concurrent fulfillment, trial start, and seat activation
    rolls back cleanly and returns the existing record idempotently."""
    from app import software_licensing as sl

    # 1. fulfill_software_checkout race recovery
    def racing_fetch(sub_id: str):
        other = SessionLocal()
        try:
            other.add(
                SoftwareLicense(
                    product="pro3dworks",
                    license_key="P3DW-RACE-1111-2222-3333",
                    plan="pro_monthly",
                    status="active",
                    email="race-fulfill@shop.com",
                    max_seats=3,
                    stripe_customer_id="cus_race_1",
                    stripe_subscription_id=sub_id,
                    stripe_checkout_session_id="cs_race_fulfill_1",
                )
            )
            other.commit()
        finally:
            other.close()
        return {"id": sub_id}

    monkeypatch.setattr(sl, "_fetch_stripe_subscription", racing_fetch)
    db = SessionLocal()
    try:
        lic = sl.fulfill_software_checkout(
            db,
            {
                "id": "cs_race_fulfill_1",
                "subscription": "sub_race_fulfill_1",
                "customer": "cus_race_1",
                "customer_details": {"email": "race-fulfill@shop.com", "name": "Race"},
                "metadata": {"product": "pro3dworks", "plan": "pro_monthly"},
            },
        )
        assert lic is not None
        assert lic.license_key == "P3DW-RACE-1111-2222-3333"
    finally:
        db.close()

    # 2. start_or_resume_trial race recovery
    orig_token_hex = sl.secrets.token_hex
    inserted_trial = False

    def racing_token_hex(nbytes: int) -> str:
        nonlocal inserted_trial
        if not inserted_trial:
            inserted_trial = True
            other = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                other.add(
                    SoftwareTrial(
                        product="pro3dworks",
                        email="race-trial@shop.com",
                        machine_id="mach-race-trial-1",
                        started_at=now,
                        expires_at=now + timedelta(days=15),
                        token_jti="race_jti_1",
                    )
                )
                other.commit()
            finally:
                other.close()
        return orig_token_hex(nbytes)

    monkeypatch.setattr(sl.secrets, "token_hex", racing_token_hex)
    db = SessionLocal()
    try:
        outcome, trial_row, meta = sl.start_or_resume_trial(
            db,
            product="pro3dworks",
            email="race-trial@shop.com",
            machine_id="mach-race-trial-1",
        )
        assert outcome == "resumed"
        assert trial_row.token_jti == "race_jti_1"
        assert meta["days_remaining"] >= 1
    finally:
        db.close()

    # 3. activate_machine_seat race recovery on commit IntegrityError
    db = SessionLocal()
    try:
        lic_obj = (
            db.query(SoftwareLicense)
            .filter(SoftwareLicense.license_key == "P3DW-RACE-1111-2222-3333")
            .one()
        )
        orig_commit = db.commit
        raced_seat = False

        def racing_commit():
            nonlocal raced_seat
            if not raced_seat:
                raced_seat = True
                other = SessionLocal()
                try:
                    other.add(SoftwareActivation(license_id=lic_obj.id, machine_id="mach-race-seat-1"))
                    other.commit()
                finally:
                    other.close()
            orig_commit()

        monkeypatch.setattr(db, "commit", racing_commit)
        ok, reason, used = sl.activate_machine_seat(
            db, lic_obj, machine_id="mach-race-seat-1", machine_name="RACE-PC"
        )
        assert ok is True and reason == "reused" and used == 1
    finally:
        db.close()
