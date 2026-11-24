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
            def retrieve(sub_id):
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
