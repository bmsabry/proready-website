"""Payments coverage: PayPal Orders v2 for live cohorts + recorded products,
Stripe Checkout for live cohorts, course pricing CRUD, and graceful
degradation while PayPal credentials are absent.

PayPal's wire is never touched: tests monkeypatch app.paypal's create/capture
functions (the routes call them via the module attribute, so patching works).
Stripe is faked at the `_stripe()` seam, mirroring how the emailer tests fake
`_resend_post`. Runs against the same throwaway SQLite DB as the other
modules, so every code/email here is unique to this file.
"""
from __future__ import annotations

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import paypal  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    EmailLog,
    Enrollment,
    Learner,
    Order,
    Product,
    Registration,
)
from app.routes import checkout as checkout_routes  # noqa: E402
from app.routes import payments as payments_routes  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}

LIVE_COURSE = "pay-live-2027"
FREE_COURSE = "pay-free-2027"          # price_cents=0 → invoice-only
RECORDED_PRODUCT = "pay-recorded-prod"
DRAFT_PRODUCT = "pay-recorded-draft"

BUYER = "paypal-live-buyer@example.com"       # pays live seat via PayPal
BUYER2 = "stripe-live-buyer@example.com"      # pays live seat via Stripe webhook
MANUAL = "manual-invoice@example.com"         # admin mark-paid (no provider)
CANCELLED = "cancelled-lead@example.com"
REC_BUYER = "recorded-paypal-buyer@example.com"
REC_STRIPE_BUYER = "recorded-stripe-buyer@example.com"

STATE: dict = {}  # registration ids etc., shared across ordered tests


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def paypal_creds(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "PAYPAL_CLIENT_ID", "test-paypal-client")
    monkeypatch.setattr(s, "PAYPAL_CLIENT_SECRET", "test-paypal-secret")
    return s


def _register(client, email: str, course_code: str) -> int:
    r = client.post(
        "/api/register",
        json={
            "full_name": "Pay Tester",
            "email": email,
            "job_title": "Engineer",
            "company": "Payments Co",
            "years_experience": "5-10",
            "location": "Riyadh",
            "course_code": course_code,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["registration_id"]


def _reg(reg_id: int) -> Registration:
    db = SessionLocal()
    try:
        return db.get(Registration, reg_id)
    finally:
        db.close()


def _receipt_logs(recipient: str) -> list[EmailLog]:
    db = SessionLocal()
    try:
        return (
            db.query(EmailLog)
            .filter(
                EmailLog.template == "payment_receipt",
                EmailLog.recipient == recipient,
            )
            .all()
        )
    finally:
        db.close()


def _capture_response(order_id: str, custom_id: str, value: str = "1950.00",
                      currency: str = "USD") -> dict:
    """Shape of a real Orders v2 capture response, trimmed to what we read."""
    return {
        "id": order_id,
        "status": "COMPLETED",
        "purchase_units": [
            {
                "reference_id": "default",
                "payments": {
                    "captures": [
                        {
                            "id": f"CAP-{order_id}",
                            "status": "COMPLETED",
                            "amount": {"currency_code": currency, "value": value},
                            "custom_id": custom_id,
                        }
                    ]
                },
            }
        ],
    }


def _fail_capture(order_id):  # pragma: no cover - failing is the assertion
    raise AssertionError("capture_order must not be called on a replay")


# -----------------------------------------------------------------------------
# A. Config endpoint + graceful degradation
# -----------------------------------------------------------------------------

def test_config_reports_everything_disabled_by_default(client):
    body = client.get("/api/payments/config").json()
    assert body == {
        "paypal_enabled": False,
        "paypal_client_id": "",
        "paypal_mode": "live",
        "currency": "USD",
        "stripe_enabled": False,
    }


def test_every_paypal_endpoint_503s_without_credentials(client):
    cases = [
        ("/api/payments/live/paypal/create-order", {"registration_id": 1}),
        ("/api/payments/live/paypal/capture",
         {"registration_id": 1, "order_id": "X"}),
        ("/api/payments/recorded/paypal/create-order",
         {"product_code": "x", "email": "a@b.com"}),
        ("/api/payments/recorded/paypal/capture",
         {"product_code": "x", "email": "a@b.com", "order_id": "X"}),
    ]
    for path, payload in cases:
        r = client.post(path, json=payload)
        assert r.status_code == 503, path
        assert r.json()["detail"] == "PayPal not configured"


def test_live_stripe_checkout_503s_without_stripe_keys(client):
    r = client.post(
        "/api/payments/live/stripe/checkout", json={"registration_id": 1}
    )
    assert r.status_code == 503


def test_config_reports_enabled_providers(client, paypal_creds, monkeypatch):
    monkeypatch.setattr(get_settings(), "STRIPE_SECRET_KEY", "sk_test_123")
    body = client.get("/api/payments/config").json()
    assert body["paypal_enabled"] is True
    assert body["paypal_client_id"] == "test-paypal-client"  # public by design
    assert body["stripe_enabled"] is True


# -----------------------------------------------------------------------------
# B. Course pricing CRUD
# -----------------------------------------------------------------------------

def test_course_created_with_price(client):
    r = client.post(
        "/api/admin/courses",
        headers=ADMIN,
        json={
            "code": LIVE_COURSE,
            "title": "Live Payments Cohort",
            "start_date": "2027-09-01",
            "total_seats": 5,
            "price_cents": 100000,
            "currency": "usd",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["price_cents"] == 100000
    assert r.json()["currency"] == "usd"

    # Second course without a price → stays invoice-only (default 0).
    r = client.post(
        "/api/admin/courses",
        headers=ADMIN,
        json={
            "code": FREE_COURSE,
            "title": "Invoice Only Cohort",
            "start_date": "2027-10-01",
            "total_seats": 5,
        },
    )
    assert r.status_code == 201
    assert r.json()["price_cents"] == 0


def test_course_price_patch_and_public_exposure(client):
    r = client.patch(
        f"/api/admin/courses/{LIVE_COURSE}",
        headers=ADMIN,
        json={"price_cents": 195000},
    )
    assert r.status_code == 200
    assert r.json()["price_cents"] == 195000

    pub = client.get(f"/api/courses/{LIVE_COURSE}").json()
    assert pub["price_cents"] == 195000
    assert pub["currency"] == "usd"


# -----------------------------------------------------------------------------
# C. Live cohort — PayPal
# -----------------------------------------------------------------------------

def test_register_buyers(client):
    STATE["reg_buyer"] = _register(client, BUYER, LIVE_COURSE)
    STATE["reg_buyer2"] = _register(client, BUYER2, LIVE_COURSE)
    STATE["reg_cancelled"] = _register(client, CANCELLED, LIVE_COURSE)
    STATE["reg_free"] = _register(client, "free-lead@example.com", FREE_COURSE)
    r = client.post(
        "/api/admin/cancel",
        headers=ADMIN,
        json={"registration_id": STATE["reg_cancelled"]},
    )
    assert r.status_code == 200


def test_live_create_order_validations(client, paypal_creds):
    # Unknown registration.
    r = client.post(
        "/api/payments/live/paypal/create-order", json={"registration_id": 999999}
    )
    assert r.status_code == 404

    # Non-pending registration (cancelled) is not payable.
    r = client.post(
        "/api/payments/live/paypal/create-order",
        json={"registration_id": STATE["reg_cancelled"]},
    )
    assert r.status_code == 409

    # Priceless course → invoice-only, no online payment.
    r = client.post(
        "/api/payments/live/paypal/create-order",
        json={"registration_id": STATE["reg_free"]},
    )
    assert r.status_code == 409


def test_live_paypal_create_order(client, paypal_creds, monkeypatch):
    created = {}

    def fake_create(amount_cents, currency, description, custom_id):
        created.update(
            amount_cents=amount_cents, currency=currency,
            description=description, custom_id=custom_id,
        )
        return "PP-LIVE-1"

    monkeypatch.setattr(paypal, "create_order", fake_create)
    r = client.post(
        "/api/payments/live/paypal/create-order",
        json={"registration_id": STATE["reg_buyer"]},
    )
    assert r.status_code == 200
    assert r.json() == {"order_id": "PP-LIVE-1"}
    assert created == {
        "amount_cents": 195000,
        "currency": "usd",
        "description": "Live Payments Cohort",
        "custom_id": f"livereg:{STATE['reg_buyer']}",
    }


def test_live_paypal_capture_marks_paid_with_receipt(client, paypal_creds, monkeypatch):
    before = client.get(f"/api/courses/{LIVE_COURSE}").json()
    assert before["seats_paid"] == 0

    monkeypatch.setattr(
        paypal,
        "capture_order",
        lambda order_id: _capture_response(
            order_id, f"livereg:{STATE['reg_buyer']}"
        ),
    )
    r = client.post(
        "/api/payments/live/paypal/capture",
        json={"registration_id": STATE["reg_buyer"], "order_id": "PP-LIVE-1"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "paid"}

    reg = _reg(STATE["reg_buyer"])
    assert reg.status == "paid"
    assert reg.payment_provider == "paypal"
    assert reg.payment_ref == "PP-LIVE-1"
    assert reg.amount_cents == 195000
    assert reg.paid_at is not None
    STATE["buyer_paid_at"] = reg.paid_at

    # Seat math: pending → paid keeps the active count, grows the paid count.
    after = client.get(f"/api/courses/{LIVE_COURSE}").json()
    assert after["seats_paid"] == 1
    assert after["seats_taken"] == before["seats_taken"]

    # Branded receipt is logged in the comms log.
    logs = _receipt_logs(BUYER)
    assert len(logs) == 1
    assert logs[0].scope_kind == "course"
    assert logs[0].scope_code == LIVE_COURSE
    assert logs[0].audience == "payer"

    # Admin listing shows how the row was paid.
    rows = client.get(
        f"/api/admin/registrations?course={LIVE_COURSE}", headers=ADMIN
    ).json()
    by_email = {row["email"]: row for row in rows}
    assert by_email[BUYER]["payment_provider"] == "paypal"


def test_live_paypal_capture_is_idempotent(client, paypal_creds, monkeypatch):
    monkeypatch.setattr(paypal, "capture_order", _fail_capture)
    r = client.post(
        "/api/payments/live/paypal/capture",
        json={"registration_id": STATE["reg_buyer"], "order_id": "PP-LIVE-1"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "paid"}

    reg = _reg(STATE["reg_buyer"])
    assert reg.paid_at == STATE["buyer_paid_at"]  # not double-written
    assert len(_receipt_logs(BUYER)) == 1        # no second receipt


def test_live_paypal_capture_rejects_mismatched_custom_id(client, paypal_creds, monkeypatch):
    monkeypatch.setattr(
        paypal,
        "capture_order",
        lambda order_id: _capture_response(order_id, "livereg:999999"),
    )
    r = client.post(
        "/api/payments/live/paypal/capture",
        json={"registration_id": STATE["reg_buyer2"], "order_id": "PP-EVIL-1"},
    )
    assert r.status_code == 409
    assert _reg(STATE["reg_buyer2"]).status == "pending"


# -----------------------------------------------------------------------------
# D. Live cohort — Stripe
# -----------------------------------------------------------------------------

def test_live_stripe_checkout_session(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "STRIPE_SECRET_KEY", "sk_test_123")
    captured = {}

    class FakeSession:
        url = "https://checkout.stripe.com/pay/cs_test_live_1"
        id = "cs_test_live_1"

    class FakeStripe:
        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return FakeSession()

    monkeypatch.setattr(payments_routes, "_stripe", lambda: FakeStripe)
    r = client.post(
        "/api/payments/live/stripe/checkout",
        json={"registration_id": STATE["reg_buyer2"]},
    )
    assert r.status_code == 200
    assert r.json() == {"url": "https://checkout.stripe.com/pay/cs_test_live_1"}

    assert captured["mode"] == "payment"
    assert captured["metadata"] == {
        "kind": "live_course",
        "registration_id": str(STATE["reg_buyer2"]),
    }
    item = captured["line_items"][0]["price_data"]
    assert item["unit_amount"] == 195000
    assert item["product_data"]["name"] == "Live Payments Cohort"
    assert (
        captured["success_url"]
        == f"https://proreadyengineer.com/training/{LIVE_COURSE}?paid=1"
    )
    assert (
        captured["cancel_url"]
        == f"https://proreadyengineer.com/training/{LIVE_COURSE}?cancelled=1"
    )


def _post_webhook(client, monkeypatch, event: dict):
    s = get_settings()
    monkeypatch.setattr(s, "STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setattr(s, "STRIPE_WEBHOOK_SECRET", "whsec_test")

    class FakeStripe:
        class Webhook:
            @staticmethod
            def construct_event(payload, sig, secret):
                return event

    monkeypatch.setattr(checkout_routes, "_stripe", lambda: FakeStripe)
    return client.post(
        "/api/academy/webhook/stripe",
        json={},
        headers={"Stripe-Signature": "t=1,v1=test"},
    )


def test_stripe_webhook_live_course_marks_registration_paid(client, monkeypatch):
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_live_1",
                "payment_status": "paid",
                "amount_total": 195000,
                "metadata": {
                    "kind": "live_course",
                    "registration_id": str(STATE["reg_buyer2"]),
                },
            }
        },
    }
    r = _post_webhook(client, monkeypatch, event)
    assert r.status_code == 200

    reg = _reg(STATE["reg_buyer2"])
    assert reg.status == "paid"
    assert reg.payment_provider == "stripe"
    assert reg.payment_ref == "cs_test_live_1"
    assert reg.amount_cents == 195000
    assert len(_receipt_logs(BUYER2)) == 1

    # Stripe delivers at-least-once — a replay must not re-mark or re-email.
    r = _post_webhook(client, monkeypatch, event)
    assert r.status_code == 200
    assert len(_receipt_logs(BUYER2)) == 1


# -----------------------------------------------------------------------------
# E. Admin mark-paid still works (shared core, no provider attribution)
# -----------------------------------------------------------------------------

def test_admin_mark_paid_unchanged_by_refactor(client):
    reg_id = _register(client, MANUAL, LIVE_COURSE)
    r = client.post(
        "/api/admin/mark-paid", headers=ADMIN, json={"registration_id": reg_id}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["registration"]["status"] == "paid"
    assert body["registration"]["payment_provider"] == ""  # manual invoice
    # Idempotent second call.
    r = client.post(
        "/api/admin/mark-paid", headers=ADMIN, json={"registration_id": reg_id}
    )
    assert r.status_code == 200


# -----------------------------------------------------------------------------
# F. Recorded products — PayPal
# -----------------------------------------------------------------------------

def test_setup_recorded_products():
    db = SessionLocal()
    db.add(
        Product(
            code=RECORDED_PRODUCT,
            title="Recorded Payments Course",
            price_cents=49900,
            currency="usd",
            status="live",
        )
    )
    db.add(Product(code=DRAFT_PRODUCT, title="Draft Course", price_cents=10000))
    db.commit()
    db.close()


def test_recorded_create_order_validations(client, paypal_creds):
    r = client.post(
        "/api/payments/recorded/paypal/create-order",
        json={"product_code": "nope", "email": REC_BUYER},
    )
    assert r.status_code == 404
    r = client.post(
        "/api/payments/recorded/paypal/create-order",
        json={"product_code": DRAFT_PRODUCT, "email": REC_BUYER},
    )
    assert r.status_code == 404  # draft products are not purchasable


def test_recorded_paypal_create_order(client, paypal_creds, monkeypatch):
    created = {}

    def fake_create(amount_cents, currency, description, custom_id):
        created.update(amount_cents=amount_cents, custom_id=custom_id)
        return "PP-REC-1"

    monkeypatch.setattr(paypal, "create_order", fake_create)
    r = client.post(
        "/api/payments/recorded/paypal/create-order",
        json={
            "product_code": RECORDED_PRODUCT,
            "email": REC_BUYER,
            "full_name": "Recorded Buyer",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"order_id": "PP-REC-1"}
    assert created["amount_cents"] == 49900
    assert created["custom_id"] == f"product:{RECORDED_PRODUCT}:{REC_BUYER}"


def test_recorded_paypal_capture_grants_enrollment(client, paypal_creds, monkeypatch):
    monkeypatch.setattr(
        paypal,
        "capture_order",
        lambda order_id: _capture_response(
            order_id, f"product:{RECORDED_PRODUCT}:{REC_BUYER}", value="499.00"
        ),
    )
    r = client.post(
        "/api/payments/recorded/paypal/capture",
        json={
            "product_code": RECORDED_PRODUCT,
            "email": REC_BUYER,
            "full_name": "Recorded Buyer",
            "order_id": "PP-REC-1",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "next": "/learn"}

    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.provider_ref == "PP-REC-1").one()
        assert order.provider == "paypal"
        assert order.status == "paid"
        assert order.amount_cents == 49900
        assert order.payment_ref == "CAP-PP-REC-1"
        learner = db.query(Learner).filter(Learner.email == REC_BUYER).one()
        assert order.learner_id == learner.id
        enrollment = (
            db.query(Enrollment)
            .filter(
                Enrollment.learner_id == learner.id,
                Enrollment.product_code == RECORDED_PRODUCT,
            )
            .one()
        )
        assert enrollment.status == "active"
        assert enrollment.source == "paypal"
        assert enrollment.order_id == order.id
    finally:
        db.close()


def test_recorded_paypal_capture_is_idempotent(client, paypal_creds, monkeypatch):
    monkeypatch.setattr(paypal, "capture_order", _fail_capture)
    r = client.post(
        "/api/payments/recorded/paypal/capture",
        json={
            "product_code": RECORDED_PRODUCT,
            "email": REC_BUYER,
            "order_id": "PP-REC-1",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "next": "/learn"}

    db = SessionLocal()
    try:
        assert db.query(Order).filter(Order.provider_ref == "PP-REC-1").count() == 1
        learner = db.query(Learner).filter(Learner.email == REC_BUYER).one()
        assert (
            db.query(Enrollment)
            .filter(
                Enrollment.learner_id == learner.id,
                Enrollment.product_code == RECORDED_PRODUCT,
            )
            .count()
            == 1
        )
    finally:
        db.close()


def test_recorded_paypal_capture_rejects_mismatched_custom_id(client, paypal_creds, monkeypatch):
    monkeypatch.setattr(
        paypal,
        "capture_order",
        lambda order_id: _capture_response(
            order_id, "product:some-other-product:evil@example.com"
        ),
    )
    r = client.post(
        "/api/payments/recorded/paypal/capture",
        json={
            "product_code": RECORDED_PRODUCT,
            "email": "victim@example.com",
            "order_id": "PP-REC-EVIL",
        },
    )
    assert r.status_code == 409


# -----------------------------------------------------------------------------
# G. Recorded products — the untagged Stripe webhook path is unchanged
# -----------------------------------------------------------------------------

def test_stripe_webhook_recorded_path_still_fulfils(client, monkeypatch):
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_rec_1",
                "payment_status": "paid",
                "amount_total": 49900,
                "currency": "usd",
                "payment_intent": "pi_rec_1",
                "customer_details": {
                    "email": REC_STRIPE_BUYER,
                    "name": "Stripe Rec Buyer",
                },
                "metadata": {"product_code": RECORDED_PRODUCT},
            }
        },
    }
    r = _post_webhook(client, monkeypatch, event)
    assert r.status_code == 200

    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.provider_ref == "cs_test_rec_1").one()
        assert order.provider == "stripe"
        assert order.status == "paid"
        learner = db.query(Learner).filter(Learner.email == REC_STRIPE_BUYER).one()
        enrollment = (
            db.query(Enrollment)
            .filter(
                Enrollment.learner_id == learner.id,
                Enrollment.product_code == RECORDED_PRODUCT,
            )
            .one()
        )
        assert enrollment.source == "stripe"
    finally:
        db.close()
