"""Private offers: sell one course to one person below the list price.

Admin makes the offer → the buyer gets a link → Stripe Checkout opens at the
offer price with their email fixed → the webhook grants access exactly like a
full-price sale and closes the offer. Stripe is faked at the `_stripe()` seam
as in test_payments.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CourseOffer, EmailLog, Enrollment, Learner, Order, Product  # noqa: E402
from app.routes import checkout as checkout_routes  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "offer-course-2027"
DRAFT = "offer-draft-2027"
BUYER = "offer-buyer@example.com"
OTHER = "offer-other@example.com"
LATE = "offer-late@example.com"

STATE: dict = {}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def products():
    db = SessionLocal()
    for code, status in ((PRODUCT, "live"), (DRAFT, "draft")):
        if db.get(Product, code) is None:
            db.add(Product(code=code, title="Offer Test Course", price_cents=100000,
                           currency="usd", status=status))
    db.commit()
    db.close()


def _offer(client, **kw):
    body = {"email": BUYER, "full_name": "Offer Buyer", "product_code": PRODUCT,
            "price_cents": 65000, "valid_days": 14, "note": "As agreed on our call."}
    body.update(kw)
    return client.post("/api/admin/academy/offers", headers=ADMIN, json=body)


def _token(link: str) -> str:
    return link.rsplit("/", 1)[1]


def _fake_checkout(monkeypatch, captured: dict, session_id: str):
    class FakeSession:
        id = session_id
        url = f"https://checkout.stripe.com/pay/{session_id}"

    class FakeStripe:
        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return FakeSession()

    monkeypatch.setattr(checkout_routes, "_stripe", lambda: FakeStripe)


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
    return client.post("/api/academy/webhook/stripe", json={},
                       headers={"Stripe-Signature": "t=1,v1=test"})


def test_only_the_admin_can_make_offers(client):
    r = client.post("/api/admin/academy/offers", json={
        "email": BUYER, "product_code": PRODUCT, "price_cents": 65000})
    assert r.status_code == 401
    assert client.get("/api/admin/academy/offers").status_code == 401


@pytest.mark.parametrize("kw, code, words", [
    ({"price_cents": 100000}, 409, "below the regular price ($1,000)"),
    ({"price_cents": 120000}, 409, "below the regular price"),
    ({"price_cents": 50}, 409, "at least $1"),
    ({"product_code": DRAFT}, 409, "not live"),
    ({"product_code": "no-such-course"}, 404, "not found"),
    ({"valid_days": 61}, 422, ""),
    ({"email": "not-an-email"}, 422, ""),
])
def test_bad_offers_are_refused(client, kw, code, words):
    r = _offer(client, **kw)
    assert r.status_code == code, r.text
    if words:
        assert words in r.json()["detail"]


def test_an_offer_makes_a_link_and_emails_the_buyer(client):
    r = _offer(client)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["state"] == "open"
    assert o["price_cents"] == 65000 and o["list_price_cents"] == 100000
    assert o["percent_off"] == 35
    assert o["link"].startswith("https://proreadyengineer.com/learn/offer/")
    assert len(_token(o["link"])) >= 30, "the link must be unguessable"
    expires = datetime.fromisoformat(o["expires_at"])
    assert timedelta(days=13, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=14)
    STATE["first"] = o
    db = SessionLocal()
    try:
        mail = db.query(EmailLog).filter(
            EmailLog.recipient == BUYER, EmailLog.template == "course_offer").all()
        assert len(mail) == 1
        assert mail[0].subject == "Your private price for Offer Test Course"
        assert "$650" in mail[0].body_html and "$1,000" in mail[0].body_html
        assert "As agreed on our call." in mail[0].body_html
    finally:
        db.close()


def test_the_buyer_sees_the_offer(client):
    r = client.get(f"/api/academy/offer/{_token(STATE['first']['link'])}")
    assert r.status_code == 200
    v = r.json()
    assert v["state"] == "open"
    assert v["product"]["title"] == "Offer Test Course"
    assert (v["price_cents"], v["list_price_cents"], v["percent_off"]) == (65000, 100000, 35)
    assert v["email"] == BUYER and v["note"] == "As agreed on our call."
    assert client.get("/api/academy/offer/not-a-real-token").status_code == 404


def test_a_new_price_replaces_the_old_link(client):
    r = _offer(client, price_cents=60000, send_email=False)
    assert r.status_code == 200
    STATE["second"] = r.json()
    old = client.get(f"/api/academy/offer/{_token(STATE['first']['link'])}").json()
    assert old["state"] == "revoked" and "no longer available" in old["message"]
    r = client.post(f"/api/academy/offer/{_token(STATE['first']['link'])}/checkout")
    assert r.status_code == 410


def test_checkout_charges_the_offer_price_to_the_buyers_email(client, monkeypatch):
    captured: dict = {}
    _fake_checkout(monkeypatch, captured, "cs_test_offer_1")
    token = _token(STATE["second"]["link"])
    r = client.post(f"/api/academy/offer/{token}/checkout")
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "https://checkout.stripe.com/pay/cs_test_offer_1"
    item = captured["line_items"][0]["price_data"]
    assert item["unit_amount"] == 60000 and item["currency"] == "usd"
    assert captured["customer_email"] == BUYER
    assert captured["metadata"] == {"product_code": PRODUCT, "offer_id": str(STATE["second"]["id"])}
    assert captured["allow_promotion_codes"] is False
    assert captured["cancel_url"] == STATE["second"]["link"]
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.provider_ref == "cs_test_offer_1").one()
        assert (order.status, order.amount_cents, order.email) == ("pending", 60000, BUYER)
    finally:
        db.close()


def _paid_event(session_id: str, offer_id: int, amount: int, email: str = BUYER) -> dict:
    return {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "payment_status": "paid",
            "amount_total": amount,
            "currency": "usd",
            "payment_intent": f"pi_{session_id}",
            "customer_details": {"email": email, "name": "Offer Buyer"},
            "metadata": {"product_code": PRODUCT, "offer_id": str(offer_id)},
        }},
    }


def test_payment_grants_access_and_closes_the_offer(client, monkeypatch):
    event = _paid_event("cs_test_offer_1", STATE["second"]["id"], 60000)
    assert _post_webhook(client, monkeypatch, event).status_code == 200
    assert _post_webhook(client, monkeypatch, event).status_code == 200  # Stripe replays
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.provider_ref == "cs_test_offer_1").one()
        assert (order.status, order.amount_cents) == ("paid", 60000)
        learner = db.query(Learner).filter(Learner.email == BUYER).one()
        rows = db.query(Enrollment).filter(
            Enrollment.learner_id == learner.id, Enrollment.product_code == PRODUCT).all()
        assert len(rows) == 1 and rows[0].status == "active" and rows[0].source == "stripe"
        offer = db.get(CourseOffer, STATE["second"]["id"])
        assert offer.status == "paid" and offer.order_id == order.id and offer.paid_at
        welcome = db.query(EmailLog).filter(
            EmailLog.recipient == BUYER, EmailLog.template == "purchase_welcome").all()
        assert len(welcome) == 1, "one welcome email, even when Stripe replays"
    finally:
        db.close()
    token = _token(STATE["second"]["link"])
    v = client.get(f"/api/academy/offer/{token}").json()
    assert v["state"] == "paid" and "already been used" in v["message"]
    assert client.post(f"/api/academy/offer/{token}/checkout").status_code == 410


def test_no_offer_for_someone_who_already_has_the_course(client):
    r = _offer(client)
    assert r.status_code == 409 and "already has access" in r.json()["detail"]


def test_an_expired_offer_cannot_be_paid(client, monkeypatch):
    r = _offer(client, email=LATE, send_email=False)
    assert r.status_code == 200
    db = SessionLocal()
    try:
        offer = db.get(CourseOffer, r.json()["id"])
        offer.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    _fake_checkout(monkeypatch, {}, "cs_never")
    token = _token(r.json()["link"])
    v = client.get(f"/api/academy/offer/{token}").json()
    assert v["state"] == "expired" and "expired" in v["message"]
    assert client.post(f"/api/academy/offer/{token}/checkout").status_code == 410


def test_revoke_list_and_resend(client):
    r = _offer(client, email=OTHER, price_cents=70000, send_email=False)
    assert r.status_code == 200
    oid = r.json()["id"]
    r = client.post(f"/api/admin/academy/offers/{oid}/resend", headers=ADMIN)
    # No email key in tests, so the send fails and the admin is told to copy the link.
    assert r.status_code == 502 and "copy the link" in r.json()["detail"]
    r = client.post(f"/api/admin/academy/offers/{oid}/revoke", headers=ADMIN)
    assert r.status_code == 200 and r.json()["state"] == "revoked"
    r = client.post(f"/api/admin/academy/offers/{STATE['second']['id']}/revoke", headers=ADMIN)
    assert r.status_code == 409, "a paid offer stays paid"
    listed = client.get(f"/api/admin/academy/offers?product_code={PRODUCT}", headers=ADMIN).json()
    states = {o["email"] + ":" + str(o["price_cents"]): o["state"] for o in listed["offers"]}
    assert states[f"{BUYER}:65000"] == "revoked"
    assert states[f"{BUYER}:60000"] == "paid"
    assert states[f"{OTHER}:70000"] == "revoked"
    assert states[f"{LATE}:65000"] == "expired"
    assert all(o["product_title"] == "Offer Test Course" for o in listed["offers"])
