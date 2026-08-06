"""ACH settlement guard: provisional access for delayed-notification (US bank
debit) payments, the 7-business-day drop-dead deadline, and auto-revoke.

Recorded products grant access immediately at checkout.session.completed even
when payment_status != 'paid' (ACH pending), but the enrollment is settlement-
pending with a deadline; async_payment_succeeded settles it, _failed (or the
lazy deadline check in academy.settlement_ok) revokes it and emails buyer +
admin exactly once. Live-cohort seats never flip to paid until funds actually
clear. Card payments are untouched: paid at completed, settled instantly.

Same webhook faking pattern as test_payments (checkout._stripe seam); every
code/email here is unique to this file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import academy as svc  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import EmailLog, Enrollment, Learner, Order, Product, Registration  # noqa: E402
from app.routes import checkout as checkout_routes  # noqa: E402
from app.settlement import SETTLEMENT_MARGIN_BUSINESS_DAYS, add_business_days  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}

REC_PRODUCT = "ach-recorded-prod"
LIVE_COURSE = "ach-live-2028"

CARD_BUYER = "ach-card-buyer@example.com"     # card control: settles instantly
ACH_BUYER = "ach-ok-buyer@example.com"        # ACH pending -> async success
ACH_FAIL_BUYER = "ach-fail-buyer@example.com" # ACH pending -> async failure
ACH_LAPSE_BUYER = "ach-lapse-buyer@example.com"  # ACH pending -> deadline lapses
ACH_DIRECT_BUYER = "ach-direct-buyer@example.com"  # async success, completed missed
LIVE_ACH_BUYER = "ach-live-ok@example.com"    # live seat: ACH pending -> success
LIVE_FAIL_BUYER = "ach-live-fail@example.com" # live seat: ACH pending -> failure

STATE: dict = {}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


# ----- helpers ---------------------------------------------------------------

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


def _recorded_event(kind: str, session_id: str, email: str, payment_status: str):
    return {
        "type": kind,
        "data": {
            "object": {
                "id": session_id,
                "payment_status": payment_status,
                "amount_total": 49900,
                "currency": "usd",
                "payment_intent": f"pi_{session_id}",
                "customer_details": {"email": email, "name": "ACH Tester"},
                "metadata": {"product_code": REC_PRODUCT},
            }
        },
    }


def _live_event(kind: str, session_id: str, reg_id: int, payment_status: str):
    return {
        "type": kind,
        "data": {
            "object": {
                "id": session_id,
                "payment_status": payment_status,
                "amount_total": 195000,
                "metadata": {"kind": "live_course", "registration_id": str(reg_id)},
            }
        },
    }


def _order(session_id: str) -> Order:
    db = SessionLocal()
    try:
        return db.query(Order).filter(Order.provider_ref == session_id).one()
    finally:
        db.close()


def _enrollment(email: str) -> Enrollment | None:
    db = SessionLocal()
    try:
        learner = db.query(Learner).filter(Learner.email == email).one()
        return (
            db.query(Enrollment)
            .filter(
                Enrollment.learner_id == learner.id,
                Enrollment.product_code == REC_PRODUCT,
            )
            .one_or_none()
        )
    finally:
        db.close()


def _has_access(email: str) -> bool:
    """The central access rule, exactly as lesson access and /me consume it."""
    db = SessionLocal()
    try:
        learner = db.query(Learner).filter(Learner.email == email).one()
        return svc.has_access(db, learner, REC_PRODUCT)
    finally:
        db.close()


def _logs(template: str, recipient: str) -> list[EmailLog]:
    db = SessionLocal()
    try:
        return (
            db.query(EmailLog)
            .filter(EmailLog.template == template, EmailLog.recipient == recipient)
            .all()
        )
    finally:
        db.close()


def _admin_logs(template: str, about_buyer: str) -> list[EmailLog]:
    """Admin notifications share one recipient across every test; the buyer's
    address in the subject line tells them apart."""
    return [
        row
        for row in _logs(template, get_settings().ADMIN_NOTIFY_EMAIL)
        if about_buyer in row.subject
    ]


def _reg(reg_id: int) -> Registration:
    db = SessionLocal()
    try:
        return db.get(Registration, reg_id)
    finally:
        db.close()


def _register(client, email: str) -> int:
    r = client.post(
        "/api/register",
        json={
            "full_name": "ACH Live Tester",
            "email": email,
            "job_title": "Engineer",
            "company": "Settlement Co",
            "years_experience": "5-10",
            "location": "Houston",
            "course_code": LIVE_COURSE,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["registration_id"]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@pytest.fixture
def welcome_recorder(monkeypatch):
    """Capture grant_and_welcome's outbound mail (it isn't EmailLog'd)."""
    calls: list[dict] = []

    def fake_send(to, subject, html, **kwargs):
        calls.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(checkout_routes, "send_email", fake_send)
    return calls


# -----------------------------------------------------------------------------
# A. Business-day math
# -----------------------------------------------------------------------------

def test_add_business_days_skips_weekends():
    fri = datetime(2026, 8, 7, 12, 30, tzinfo=timezone.utc)  # a Friday
    assert fri.weekday() == 4
    # Fri + 7 business days spans two weekends -> Tuesday week after next.
    assert add_business_days(fri, 7) == datetime(2026, 8, 18, 12, 30, tzinfo=timezone.utc)
    # Fri + 1 -> Monday, never Saturday.
    assert add_business_days(fri, 1) == datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)
    # Weekend start rolls onto weekdays: Sat + 1 -> Monday.
    sat = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
    assert add_business_days(sat, 1) == datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    # Zero is the identity.
    assert add_business_days(fri, 0) == fri
    assert SETTLEMENT_MARGIN_BUSINESS_DAYS == 7


# -----------------------------------------------------------------------------
# B. Fixtures: product, course, registrations
# -----------------------------------------------------------------------------

def test_setup(client):
    db = SessionLocal()
    db.add(
        Product(
            code=REC_PRODUCT,
            title="ACH Recorded Course",
            price_cents=49900,
            currency="usd",
            status="live",
        )
    )
    db.commit()
    db.close()

    r = client.post(
        "/api/admin/courses",
        headers=ADMIN,
        json={
            "code": LIVE_COURSE,
            "title": "ACH Live Cohort",
            "start_date": "2028-03-01",
            "total_seats": 5,
            "price_cents": 195000,
            "currency": "usd",
        },
    )
    assert r.status_code == 201, r.text

    STATE["reg_live_ok"] = _register(client, LIVE_ACH_BUYER)
    STATE["reg_live_fail"] = _register(client, LIVE_FAIL_BUYER)


# -----------------------------------------------------------------------------
# C. Card path unchanged: paid at completed, settled instantly
# -----------------------------------------------------------------------------

def test_card_payment_settles_immediately(client, monkeypatch):
    event = _recorded_event(
        "checkout.session.completed", "cs_ach_card", CARD_BUYER, "paid"
    )
    assert _post_webhook(client, monkeypatch, event).status_code == 200

    order = _order("cs_ach_card")
    assert order.status == "paid"
    assert order.paid_at is not None
    enr = _enrollment(CARD_BUYER)
    assert enr.status == "active"
    assert enr.settlement_status == "settled"
    assert enr.settlement_deadline is None
    assert _has_access(CARD_BUYER) is True


# -----------------------------------------------------------------------------
# D. ACH completed-unpaid: provisional grant with the 7-business-day deadline
# -----------------------------------------------------------------------------

def test_ach_completed_unpaid_grants_provisional_access(
    client, monkeypatch, welcome_recorder
):
    event = _recorded_event(
        "checkout.session.completed", "cs_ach_ok", ACH_BUYER, "unpaid"
    )
    t0 = datetime.now(timezone.utc)
    assert _post_webhook(client, monkeypatch, event).status_code == 200
    t1 = datetime.now(timezone.utc)

    order = _order("cs_ach_ok")
    assert order.status == "processing"
    assert order.paid_at is None

    enr = _enrollment(ACH_BUYER)
    assert enr.status == "active"
    assert enr.settlement_status == "pending"
    deadline = _aware(enr.settlement_deadline)
    assert add_business_days(t0, 7) <= deadline <= add_business_days(t1, 7)

    # Access is live right now — that's the provisional-access model.
    assert _has_access(ACH_BUYER) is True

    # Welcome email went out once, with the bank-processing note appended.
    assert len(welcome_recorder) == 1
    assert welcome_recorder[0]["to"] == ACH_BUYER
    assert "bank transfer" in welcome_recorder[0]["html"]
    assert "Bank payment processing" in welcome_recorder[0]["html"]

    # Stripe delivers at-least-once: a replay must not re-grant or re-email.
    assert _post_webhook(client, monkeypatch, event).status_code == 200
    assert len(welcome_recorder) == 1
    assert _order("cs_ach_ok").status == "processing"


def test_admin_learners_surface_pending_settlement(client):
    r = client.get(
        f"/api/admin/academy/learners?product_code={REC_PRODUCT}", headers=ADMIN
    )
    assert r.status_code == 200
    by_email = {l["email"]: l for l in r.json()["learners"]}
    pending = next(
        e for e in by_email[ACH_BUYER]["enrollments"]
        if e["product_code"] == REC_PRODUCT
    )
    assert pending["settlement_status"] == "pending"
    assert pending["settlement_deadline"] is not None
    settled = next(
        e for e in by_email[CARD_BUYER]["enrollments"]
        if e["product_code"] == REC_PRODUCT
    )
    assert settled["settlement_status"] == "settled"
    assert settled["settlement_deadline"] is None


# -----------------------------------------------------------------------------
# E. async_payment_succeeded settles the provisional grant (no second welcome)
# -----------------------------------------------------------------------------

def test_async_success_settles_enrollment(client, monkeypatch, welcome_recorder):
    event = _recorded_event(
        "checkout.session.async_payment_succeeded", "cs_ach_ok", ACH_BUYER, "paid"
    )
    assert _post_webhook(client, monkeypatch, event).status_code == 200

    order = _order("cs_ach_ok")
    assert order.status == "paid"
    assert order.paid_at is not None
    enr = _enrollment(ACH_BUYER)
    assert enr.status == "active"
    assert enr.settlement_status == "settled"
    assert enr.settlement_deadline is None
    assert _has_access(ACH_BUYER) is True
    # Already welcomed when the provisional grant was made.
    assert welcome_recorder == []


def test_async_success_does_full_grant_when_completed_was_missed(
    client, monkeypatch, welcome_recorder
):
    event = _recorded_event(
        "checkout.session.async_payment_succeeded",
        "cs_ach_direct", ACH_DIRECT_BUYER, "paid",
    )
    assert _post_webhook(client, monkeypatch, event).status_code == 200

    assert _order("cs_ach_direct").status == "paid"
    enr = _enrollment(ACH_DIRECT_BUYER)
    assert enr.status == "active"
    assert enr.settlement_status == "settled"
    # Nobody welcomed this buyer yet, so the full grant does it here.
    assert len(welcome_recorder) == 1
    assert welcome_recorder[0]["to"] == ACH_DIRECT_BUYER
    assert "bank transfer" not in welcome_recorder[0]["html"]


# -----------------------------------------------------------------------------
# F. async_payment_failed revokes + emails buyer and admin exactly once
# -----------------------------------------------------------------------------

def test_async_failure_revokes_and_emails(client, monkeypatch):
    completed = _recorded_event(
        "checkout.session.completed", "cs_ach_bad", ACH_FAIL_BUYER, "unpaid"
    )
    assert _post_webhook(client, monkeypatch, completed).status_code == 200
    assert _has_access(ACH_FAIL_BUYER) is True

    failed = _recorded_event(
        "checkout.session.async_payment_failed", "cs_ach_bad", ACH_FAIL_BUYER, "unpaid"
    )
    assert _post_webhook(client, monkeypatch, failed).status_code == 200

    assert _order("cs_ach_bad").status == "failed"
    enr = _enrollment(ACH_FAIL_BUYER)
    assert enr.status == "revoked"
    assert enr.settlement_status == "failed"
    assert enr.settlement_deadline is None
    assert _has_access(ACH_FAIL_BUYER) is False

    buyer_logs = _logs("settlement_failed", ACH_FAIL_BUYER)
    assert len(buyer_logs) == 1
    assert buyer_logs[0].scope_kind == "product"
    assert buyer_logs[0].scope_code == REC_PRODUCT
    assert len(_admin_logs("settlement_failed_admin", ACH_FAIL_BUYER)) == 1

    # Replay of the failure event: no double revoke, no double email.
    assert _post_webhook(client, monkeypatch, failed).status_code == 200
    assert len(_logs("settlement_failed", ACH_FAIL_BUYER)) == 1
    assert len(_admin_logs("settlement_failed_admin", ACH_FAIL_BUYER)) == 1


# -----------------------------------------------------------------------------
# G. Lazy deadline enforcement: pending past deadline is revoked on read
# -----------------------------------------------------------------------------

def test_deadline_lapse_revokes_on_read_and_emails_once(client, monkeypatch):
    completed = _recorded_event(
        "checkout.session.completed", "cs_ach_lapse", ACH_LAPSE_BUYER, "unpaid"
    )
    assert _post_webhook(client, monkeypatch, completed).status_code == 200
    assert _has_access(ACH_LAPSE_BUYER) is True

    # Rewind the clock: the 7-business-day deadline passed unconfirmed.
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == ACH_LAPSE_BUYER).one()
    enr = (
        db.query(Enrollment)
        .filter(
            Enrollment.learner_id == learner.id,
            Enrollment.product_code == REC_PRODUCT,
        )
        .one()
    )
    enr.settlement_deadline = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    db.close()

    # First access check trips the write-on-read revoke + emails.
    assert _has_access(ACH_LAPSE_BUYER) is False
    enr = _enrollment(ACH_LAPSE_BUYER)
    assert enr.status == "revoked"
    assert enr.settlement_status == "failed"

    assert len(_logs("settlement_failed", ACH_LAPSE_BUYER)) == 1
    assert len(_admin_logs("settlement_failed_admin", ACH_LAPSE_BUYER)) == 1

    # Second consecutive access check: still denied, still exactly one email.
    assert _has_access(ACH_LAPSE_BUYER) is False
    assert len(_logs("settlement_failed", ACH_LAPSE_BUYER)) == 1
    assert len(_admin_logs("settlement_failed_admin", ACH_LAPSE_BUYER)) == 1


def test_admin_learners_show_failed_buyer_for_followup(client):
    r = client.get(
        f"/api/admin/academy/learners?product_code={REC_PRODUCT}", headers=ADMIN
    )
    assert r.status_code == 200
    by_email = {l["email"]: l for l in r.json()["learners"]}
    # Revoked-for-failed-settlement buyers stay visible so the dashboard can
    # badge them red instead of silently dropping them.
    assert ACH_LAPSE_BUYER in by_email
    failed = next(
        e for e in by_email[ACH_LAPSE_BUYER]["enrollments"]
        if e["product_code"] == REC_PRODUCT
    )
    assert failed["status"] == "revoked"
    assert failed["settlement_status"] == "failed"


# -----------------------------------------------------------------------------
# H. Live cohort: seat flips to paid only when funds actually clear
# -----------------------------------------------------------------------------

def test_live_completed_unpaid_holds_seat_without_receipt(client, monkeypatch):
    reg_id = STATE["reg_live_ok"]
    event = _live_event(
        "checkout.session.completed", "cs_ach_live_ok", reg_id, "unpaid"
    )
    t0 = datetime.now(timezone.utc)
    assert _post_webhook(client, monkeypatch, event).status_code == 200
    t1 = datetime.now(timezone.utc)

    reg = _reg(reg_id)
    assert reg.status == "pending"  # seat held, NOT paid
    assert reg.paid_at is None
    lo = add_business_days(t0, 7).date().isoformat()
    hi = add_business_days(t1, 7).date().isoformat()
    assert any(
        f"bank payment processing, expected by {d}" in (reg.admin_notes or "")
        for d in {lo, hi}
    )
    assert _logs("payment_receipt", LIVE_ACH_BUYER) == []

    # Replay keeps a single note line and still no receipt.
    assert _post_webhook(client, monkeypatch, event).status_code == 200
    reg = _reg(reg_id)
    assert (reg.admin_notes or "").count("bank payment processing") == 1
    assert _logs("payment_receipt", LIVE_ACH_BUYER) == []


def test_live_async_success_marks_paid_and_sends_receipt(client, monkeypatch):
    reg_id = STATE["reg_live_ok"]
    event = _live_event(
        "checkout.session.async_payment_succeeded", "cs_ach_live_ok", reg_id, "paid"
    )
    assert _post_webhook(client, monkeypatch, event).status_code == 200

    reg = _reg(reg_id)
    assert reg.status == "paid"
    assert reg.payment_provider == "stripe"
    assert reg.payment_ref == "cs_ach_live_ok"
    assert reg.amount_cents == 195000
    assert len(_logs("payment_receipt", LIVE_ACH_BUYER)) == 1

    # Replay: no double receipt.
    assert _post_webhook(client, monkeypatch, event).status_code == 200
    assert len(_logs("payment_receipt", LIVE_ACH_BUYER)) == 1


def test_live_async_failure_keeps_seat_pending_and_emails(client, monkeypatch):
    reg_id = STATE["reg_live_fail"]
    completed = _live_event(
        "checkout.session.completed", "cs_ach_live_bad", reg_id, "unpaid"
    )
    assert _post_webhook(client, monkeypatch, completed).status_code == 200
    assert "bank payment processing" in (_reg(reg_id).admin_notes or "")

    failed = _live_event(
        "checkout.session.async_payment_failed", "cs_ach_live_bad", reg_id, "unpaid"
    )
    assert _post_webhook(client, monkeypatch, failed).status_code == 200

    reg = _reg(reg_id)
    assert reg.status == "pending"  # no auto-cancel: the owner decides
    notes = reg.admin_notes or ""
    assert "bank payment failed" in notes
    assert "bank payment processing" not in notes  # note swapped, not stacked
    assert _logs("payment_receipt", LIVE_FAIL_BUYER) == []

    buyer_logs = _logs("live_bank_failed", LIVE_FAIL_BUYER)
    assert len(buyer_logs) == 1
    assert buyer_logs[0].scope_kind == "course"
    assert buyer_logs[0].scope_code == LIVE_COURSE
    assert len(_admin_logs("live_bank_failed_admin", LIVE_FAIL_BUYER)) == 1

    # Replay: still pending, still exactly one email pair.
    assert _post_webhook(client, monkeypatch, failed).status_code == 200
    assert len(_logs("live_bank_failed", LIVE_FAIL_BUYER)) == 1
    assert len(_admin_logs("live_bank_failed_admin", LIVE_FAIL_BUYER)) == 1
