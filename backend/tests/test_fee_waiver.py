"""Fee waivers on the instructor-examined tier.

The owner asked (2026-10-10) for a way to waive the examination fee. Under
the register button a candidate can ask for a waiver; the instructor is
emailed and decides in the admin panel:

  * waive                     — the written examination opens at no charge
  * pay before the interview  — it opens now; the interview stays locked
                                until the fee is paid (or waived after all)
  * ask them to pay now       — nothing opens; they are emailed a link to
                                register and pay

While a request waits the candidate may still pay by card, which closes it.
Every decision is recorded on the row (who, when, why) and nothing is
decided by an email link.

Runs on the shared SQLite DB (see conftest); emails are captured at the
Resend seam and Stripe is faked at the `_stripe()` seam.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import emailer as E  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.learner_auth import issue_login_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AdvancedCertification,
    Certificate,
    Course,
    Learner,
    Order,
    Product,
    QuizItem,
)
from app.routes import checkout as checkout_routes  # noqa: E402

PRODUCT = conftest.TEST_ADVANCED_PRODUCT
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
ADMIN_API = "/api/admin/academy/certification"
COURSE_CODE = "mgt-waiver-test-cohort"
DEEP_LINK = f"https://proreadyengineer.com/admin#courses/{COURSE_CODE}/certification"

WAIVE = "waiver.waived@example.com"
DEFER = "waiver.deferred@example.com"
DECLINE = "waiver.declined@example.com"
PAYS = "waiver.pays@example.com"
RACE = "waiver.race@example.com"
COMP = "waiver.comp@example.com"
LATER = "waiver.later@example.com"
NAMES = {
    WAIVE: "Wendy Waived", DEFER: "Dan Deferred", DECLINE: "Dee Declined",
    PAYS: "Paula Pays", RACE: "Rae Race", COMP: "Cal Comp", LATER: "Lee Later",
}
CERT_CODES = {email: f"PRE-C-WAIV-{n:04d}" for n, email in enumerate(NAMES, 1)}


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-waiver"}


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1]
    )
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


_SESSION_NUMBERS = itertools.count(1)  # session ids stay unique across tests


class _FakeStripe:
    """Stripe at the `_stripe()` seam: records every Checkout Session asked
    for, and hands the webhook route whichever event `deliver` is sending."""

    def __init__(self):
        self.sessions: list[dict] = []
        self.event: dict = {}
        fake = self

        class _Session:
            def __init__(self, n):
                self.id = f"cs_test_waiver_{n}"
                self.url = f"https://checkout.stripe.com/pay/{self.id}"

        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    fake.sessions.append(kwargs)
                    return _Session(next(_SESSION_NUMBERS))

        class Webhook:
            @staticmethod
            def construct_event(payload, sig, secret):
                return fake.event

        self.checkout = checkout
        self.Webhook = Webhook

    def deliver(self, session_obj: dict) -> None:
        """POST a paid checkout.session.completed through the real route."""
        self.event = {"type": "checkout.session.completed", "data": {"object": session_obj}}
        with TestClient(app, base_url="https://testserver") as c:
            r = c.post("/api/academy/webhook/stripe", json={}, headers={"Stripe-Signature": "t=1,v1=x"})
        assert r.status_code == 200, r.text


@pytest.fixture()
def stripe(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setattr(s, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    fake = _FakeStripe()
    monkeypatch.setattr(checkout_routes, "_stripe", lambda: fake)
    return fake


@pytest.fixture(scope="module", autouse=True)
def candidates():
    """Six finishers with access and an issued Certificate of Completion, the
    tier switched on at $300, and a course that links the product (so the
    admin deep links have a course to point at). All undone afterwards: the
    suite shares one database."""
    with TestClient(app, base_url="https://testserver") as c:
        for email, name in NAMES.items():
            r = c.post(
                "/api/admin/academy/grant",
                json={"email": email, "product_code": PRODUCT, "full_name": name,
                      "send_email_invite": False},
                headers=ADMIN,
            )
            assert r.status_code == 200, r.text
    db = SessionLocal()
    product = db.get(Product, PRODUCT)
    was = (product.advanced_cert_enabled, product.advanced_cert_price_cents)
    product.advanced_cert_enabled = True
    product.advanced_cert_price_cents = 30000
    ids = {l.email: l.id for l in db.query(Learner).filter(Learner.email.in_(NAMES)).all()}
    for email, code in CERT_CODES.items():
        db.add(Certificate(
            learner_id=ids[email], product_code=PRODUCT, code=code, learner_name=NAMES[email],
            tier="completion", status="issued", course_title=product.title,
            issued_at=datetime.now(timezone.utc),
        ))
    # The newest cohort on the product is the one the links name; other test
    # modules add cohorts of their own, so this one starts far in the future.
    db.add(Course(code=COURSE_CODE, title="MGT waiver test cohort",
                  start_date=(datetime.now(timezone.utc) + timedelta(days=3650)).date(),
                  recorded_product_code=PRODUCT))
    db.commit()
    db.close()

    clients: dict[str, TestClient] = {}
    for email in NAMES:
        c = TestClient(app, base_url="https://testserver")
        c.__enter__()
        db = SessionLocal()
        raw = issue_login_token(db, db.query(Learner).filter(Learner.email == email).one())
        db.close()
        assert c.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
        me = c.get("/api/academy/me").json()
        c.post("/api/academy/accept-terms", json={"version": me["terms_version"]})
        clients[email] = c
    yield clients

    for c in clients.values():
        c.__exit__(None, None, None)
    from app.progress_guard import allow_progress_loss

    db = SessionLocal()
    learner_ids = list(ids.values())
    db.query(AdvancedCertification).filter(
        AdvancedCertification.learner_id.in_(learner_ids)
    ).delete(synchronize_session=False)
    db.query(Order).filter(Order.learner_id.in_(learner_ids), Order.kind == "advanced_cert").delete(
        synchronize_session=False
    )
    with allow_progress_loss("test fixture: remove synthetic certificates"):
        db.query(Certificate).filter(Certificate.code.in_(CERT_CODES.values())).delete(
            synchronize_session=False
        )
        db.commit()
    db.query(Course).filter(Course.code == COURSE_CODE).delete(synchronize_session=False)
    product = db.get(Product, PRODUCT)
    product.advanced_cert_enabled, product.advanced_cert_price_cents = was
    db.commit()
    db.close()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _advanced(c: TestClient) -> dict:
    r = c.get(f"/api/academy/certification/{PRODUCT}")
    assert r.status_code == 200, r.text
    return r.json()["advanced"]


def _ask(c: TestClient, reason="employer", note="My employer, Acme Turbines, is paying."):
    return c.post(f"/api/academy/advanced/{PRODUCT}/waiver", json={"reason": reason, "note": note})


def _candidate(email: str) -> dict:
    with TestClient(app, base_url="https://testserver") as admin:
        overview = admin.get(f"{ADMIN_API}/{PRODUCT}", headers=ADMIN).json()
    rows = [c for c in overview["candidates"] if c["email"] == email]
    assert rows, f"no candidate row for {email}"
    return rows[0]


def _decide(row_id: int, decision: str, note: str = ""):
    with TestClient(app, base_url="https://testserver") as admin:
        return admin.post(f"{ADMIN_API}/advanced/{row_id}/waiver",
                          json={"decision": decision, "note": note}, headers=ADMIN)


def _row(row_id: int) -> AdvancedCertification:
    db = SessionLocal()
    row = db.get(AdvancedCertification, row_id)
    db.expunge(row)
    db.close()
    return row


def _pass_written_exam(c: TestClient) -> None:
    items = c.get(f"/api/academy/advanced/{PRODUCT}/exam").json()["items"]
    db = SessionLocal()
    key = {
        i.code: i.answer.get("key")
        for i in db.query(QuizItem).filter(QuizItem.product_code == PRODUCT, QuizItem.item_set == "advanced")
    }
    db.close()
    r = c.post(f"/api/academy/advanced/{PRODUCT}/exam",
               json={"responses": {i["code"]: key[i["code"]] for i in items}})
    assert r.status_code == 200 and r.json()["passed"] is True, r.text


def _webhook(session_id: str, learner_email: str, amount: int, row_id: int | None = None) -> dict:
    db = SessionLocal()
    learner_id = db.query(Learner).filter(Learner.email == learner_email).one().id
    db.close()
    meta = {"kind": "advanced_cert", "product_code": PRODUCT, "learner_id": str(learner_id)}
    if row_id is not None:
        meta["row_id"] = str(row_id)
    return {
        "id": session_id, "payment_status": "paid", "amount_total": amount, "currency": "usd",
        "payment_intent": f"pi_{session_id}",
        "customer_details": {"email": learner_email, "name": NAMES[learner_email]},
        "metadata": meta,
    }


def _to(outbox: list[dict], addr: str) -> list[dict]:
    return [m for m in outbox if addr in m["to"]]


# -----------------------------------------------------------------------------
# Asking
# -----------------------------------------------------------------------------

def test_an_eligible_candidate_is_offered_the_request(candidates):
    adv = _advanced(candidates[WAIVE])
    assert adv["state"] is None and adv["can_purchase"] is True
    assert adv["waiver"]["can_request"] is True
    assert [r["key"] for r in adv["waiver"]["reasons"]] == ["employer", "training_contract", "other"]


def test_asking_opens_nothing_and_tells_the_instructor(candidates, outbox):
    c = candidates[WAIVE]
    # "Another reason" must say what it is.
    assert _ask(c, reason="other", note="").status_code == 409

    r = _ask(c)
    assert r.status_code == 200, r.text
    state = r.json()["state"]
    assert state["status"] == "waiver_requested" and state["waiver_reason"] == "employer"
    assert state["exam_open"] is False
    # The written examination stays closed...
    assert c.get(f"/api/academy/advanced/{PRODUCT}/exam").status_code == 409
    # ...the candidate may still pay instead, but may not ask twice.
    adv = _advanced(c)
    assert adv["can_purchase"] is True and adv["waiver"]["can_request"] is False
    assert _ask(c).status_code == 409

    mails = _to(outbox, get_settings().ADMIN_NOTIFY_EMAIL)
    assert len(mails) == 1
    mail = mails[0]
    assert mail["subject"].startswith("[Fee waiver] Wendy Waived — ")
    assert "Their employer is paying" in mail["html"] and "Acme Turbines" in mail["html"]
    assert "$300" in mail["html"] and CERT_CODES[WAIVE] in mail["html"]
    # The email links to the course's Certification tab and decides nothing.
    assert DEEP_LINK in mail["html"]
    assert "/waiver" not in mail["html"]


def test_the_request_waits_at_the_top_for_the_instructor(candidates):
    with TestClient(app, base_url="https://testserver") as admin:
        overview = admin.get(f"{ADMIN_API}/{PRODUCT}", headers=ADMIN).json()
        summary = admin.get(ADMIN_API, headers=ADMIN).json()
        assert admin.get(ADMIN_API).status_code == 401  # admin only
    first = overview["candidates"][0]
    assert first["email"] == WAIVE and first["status"] == "waiver_requested"
    assert first["waiver_reason_label"] == "Their employer is paying"
    assert overview["counts"]["waiver_requests"] == 1
    assert overview["counts"]["awaiting_action"] >= 1

    course = next(x for x in summary["courses"] if x["product_code"] == PRODUCT)
    assert course["course_code"] == COURSE_CODE and course["counts"]["waiver_requests"] == 1
    assert summary["needs_you"] >= 1
    waiting = summary["waiting"][0]
    assert waiting["email"] == WAIVE and waiting["waiting_reason"].startswith("Fee-waiver request")

    # A request is answered, never silently cancelled.
    with TestClient(app, base_url="https://testserver") as admin:
        r = admin.post(f"{ADMIN_API}/advanced/{first['id']}/cancel", json={"note": "x"}, headers=ADMIN)
    assert r.status_code == 409


# -----------------------------------------------------------------------------
# Waive
# -----------------------------------------------------------------------------

def test_waive_opens_the_examination_free_and_records_who_and_why(candidates, outbox):
    row_id = _candidate(WAIVE)["id"]
    assert _decide(row_id, "maybe").status_code == 409
    r = _decide(row_id, "waive", "Acme has a training agreement with us.")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "purchased" and body["fee_status"] == "waived"
    assert body["amount_cents"] == 0 and body["waiver_decision"] == "waived"
    assert body["waiver_decided_by"] == conftest.ADMIN_EMAIL
    assert [e["event"] for e in body["fee_log"]] == ["requested", "waived"]
    assert body["fee_log"][1]["by"] == conftest.ADMIN_EMAIL
    # Answered once only.
    assert _decide(row_id, "decline").status_code == 409

    adv = _advanced(candidates[WAIVE])
    assert adv["state"]["status"] == "purchased" and adv["state"]["exam_open"] is True
    assert adv["state"]["fee_status"] == "waived" and adv["state"]["fee_due_cents"] == 0
    assert candidates[WAIVE].get(f"/api/academy/advanced/{PRODUCT}/exam").status_code == 200

    mail = _to(outbox, WAIVE)[-1]
    assert mail["subject"].startswith("Your examination fee is waived")
    assert "Acme has a training agreement with us." in mail["html"]
    assert "Start the written examination" in mail["html"]
    assert f"https://proreadyengineer.com/learn/{PRODUCT}" in mail["html"]


# -----------------------------------------------------------------------------
# Pay before the interview
# -----------------------------------------------------------------------------

def test_defer_opens_the_exam_but_locks_the_interview_until_paid(candidates, outbox, stripe):
    c = candidates[DEFER]
    assert _ask(c, reason="training_contract", note="").status_code == 200
    row_id = _candidate(DEFER)["id"]
    r = _decide(row_id, "defer", "Pay when your contract invoice clears.")
    assert r.status_code == 200, r.text
    assert r.json()["fee_status"] == "due" and r.json()["fee_due"] is True
    assert r.json()["amount_cents"] == 30000  # the amount owed, fixed now
    mail = _to(outbox, DEFER)[-1]
    assert mail["subject"].startswith("Your written examination is open")
    assert "due before you book your oral examination" in mail["html"]

    # A later price change does not move what this candidate owes.
    db = SessionLocal()
    db.get(Product, PRODUCT).advanced_cert_price_cents = 45000
    db.commit()
    db.close()

    state = _advanced(c)["state"]
    assert state["exam_open"] is True and state["fee_due_cents"] == 30000
    _pass_written_exam(c)
    passed = _to(outbox, DEFER)[-1]
    assert passed["subject"].startswith("Written examination passed")
    assert "Pay and book your interview" in passed["html"] and "$300" in passed["html"]

    state = _advanced(c)["state"]
    assert state["status"] == "exam_passed" and state["can_propose"] is False
    assert "Pay the $300 examination fee" in state["propose_blocked_reason"]
    future = [(datetime.now(timezone.utc) + timedelta(days=3)).isoformat()]
    assert c.post(f"/api/academy/advanced/{PRODUCT}/slots",
                  json={"slots": future, "timezone": "UTC"}).status_code == 409
    with TestClient(app, base_url="https://testserver") as admin:
        r = admin.post(f"{ADMIN_API}/advanced/{row_id}/schedule",
                       json={"at": future[0], "meeting_url": "https://zoom.us/j/1"}, headers=ADMIN)
    assert r.status_code == 409 and "fee is still due" in r.json()["detail"]
    # Normal registration stays closed: this candidate pays the deferred fee.
    assert c.post(f"/api/academy/advanced/{PRODUCT}/checkout").status_code == 409

    r = c.post(f"/api/academy/advanced/{PRODUCT}/pay")
    assert r.status_code == 200, r.text
    session = stripe.sessions[-1]
    assert session["metadata"]["row_id"] == str(row_id)
    assert session["line_items"][0]["price_data"]["unit_amount"] == 30000
    assert session["success_url"].endswith(f"/learn/{PRODUCT}?advanced=paid")

    stripe.deliver(_webhook(r.json()["session_id"], DEFER, 30000, row_id=row_id))
    stripe.deliver(_webhook(r.json()["session_id"], DEFER, 30000, row_id=row_id))  # Stripe retries
    row = _row(row_id)
    assert row.fee_status == "paid" and row.amount_cents == 30000 and row.order_id
    assert row.status == "exam_passed"
    assert [e["event"] for e in row.fee_log] == ["requested", "deferred", "paid"]
    db = SessionLocal()
    assert db.query(AdvancedCertification).filter(
        AdvancedCertification.learner_id == row.learner_id
    ).count() == 1, "the payment settled the open examination; it did not open another"
    db.get(Product, PRODUCT).advanced_cert_price_cents = 30000
    db.commit()
    db.close()

    receipts = [m for m in _to(outbox, DEFER) if m["subject"].startswith("Payment received")]
    assert len(receipts) == 1
    assert "Propose your interview times" in receipts[0]["html"]
    assert receipts[0].get("bcc") == [get_settings().ADMIN_NOTIFY_EMAIL]

    state = _advanced(c)["state"]
    assert state["can_propose"] is True and state["fee_status"] == "paid"
    assert c.post(f"/api/academy/advanced/{PRODUCT}/slots",
                  json={"slots": future, "timezone": "UTC"}).status_code == 200
    assert c.post(f"/api/academy/advanced/{PRODUCT}/pay").status_code == 409  # nothing due now


def test_a_due_fee_can_still_be_waived_later(candidates, outbox):
    c = candidates[LATER]
    assert _ask(c, reason="other", note="Between jobs right now.").status_code == 200
    row_id = _candidate(LATER)["id"]
    assert _decide(row_id, "defer").status_code == 200
    with TestClient(app, base_url="https://testserver") as admin:
        r = admin.post(f"{ADMIN_API}/advanced/{row_id}/waive-fee",
                       json={"note": "Good luck in the new role."}, headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["fee_status"] == "waived" and r.json()["fee_due"] is False
        # Nothing left to waive.
        assert admin.post(f"{ADMIN_API}/advanced/{row_id}/waive-fee",
                          json={"note": ""}, headers=ADMIN).status_code == 409
    assert [e["event"] for e in r.json()["fee_log"]] == ["requested", "deferred", "fee_waived"]
    mail = _to(outbox, LATER)[-1]
    assert mail["subject"].startswith("Your examination fee is waived")
    assert "Nothing is owed" in mail["html"] and "Good luck in the new role." in mail["html"]
    # Still sitting the written exam, so the email does not invite a booking yet.
    assert "Once you pass the written examination" in mail["html"]


# -----------------------------------------------------------------------------
# Ask them to pay now
# -----------------------------------------------------------------------------

def test_decline_opens_nothing_and_offers_registration(candidates, outbox):
    c = candidates[DECLINE]
    assert _ask(c, reason="other", note="Please, I am a student.").status_code == 200
    row_id = _candidate(DECLINE)["id"]
    r = _decide(row_id, "decline", "The fee covers a live hour with me; I cannot waive it.")
    assert r.status_code == 200 and r.json()["status"] == "waiver_declined"

    adv = _advanced(c)
    assert adv["state"] is None, "a declined request is not a journey"
    assert adv["can_purchase"] is True
    assert adv["waiver"]["declined"] is True and adv["waiver"]["can_request"] is False
    assert adv["waiver"]["message"].startswith("The fee covers a live hour")
    assert c.get(f"/api/academy/advanced/{PRODUCT}/exam").status_code == 409
    assert _ask(c).status_code == 409

    mail = _to(outbox, DECLINE)[-1]
    assert mail["subject"].startswith("About your fee-waiver request")
    assert "I cannot waive it." in mail["html"]
    assert f"/learn/{PRODUCT}?advanced=start" in mail["html"]
    assert "Register for the examination" in mail["html"]


# -----------------------------------------------------------------------------
# Paying while the request waits, and the race with a waiver
# -----------------------------------------------------------------------------

def test_paying_while_the_request_waits_closes_it(candidates, stripe):
    c = candidates[PAYS]
    assert _ask(c).status_code == 200
    request_id = _candidate(PAYS)["id"]
    r = c.post(f"/api/academy/advanced/{PRODUCT}/checkout")
    assert r.status_code == 200, r.text
    assert "row_id" not in stripe.sessions[-1]["metadata"]
    stripe.deliver(_webhook(r.json()["session_id"], PAYS, 30000))

    closed = _row(request_id)
    assert closed.status == "waiver_withdrawn" and closed.waiver_decision == "paid"
    adv = _advanced(c)
    assert adv["state"]["status"] == "purchased" and adv["state"]["fee_status"] == "paid"
    assert adv["state"]["id"] != request_id
    # Answering a request that closed itself is refused.
    assert _decide(request_id, "waive").status_code == 409


def test_a_payment_after_a_waiver_is_flagged_and_its_refund_keeps_the_exam(candidates, outbox, stripe):
    c = candidates[RACE]
    assert _ask(c).status_code == 200
    r = c.post(f"/api/academy/advanced/{PRODUCT}/checkout")  # starts paying...
    assert r.status_code == 200
    row_id = _candidate(RACE)["id"]
    assert _decide(row_id, "waive").status_code == 200  # ...while the instructor waives
    stripe.deliver(_webhook(r.json()["session_id"], RACE, 30000))

    row = _row(row_id)
    assert row.status == "purchased" and row.fee_status == "waived"
    assert row.order_id is None, "the payment is kept off the row"
    assert row.fee_log[-1]["event"] == "extra_payment"
    db = SessionLocal()
    assert db.query(AdvancedCertification).filter(
        AdvancedCertification.learner_id == row.learner_id,
        AdvancedCertification.status == "purchased",
    ).count() == 1, "no second examination was opened"
    db.close()
    alert = [m for m in _to(outbox, get_settings().ADMIN_NOTIFY_EMAIL)
             if m["subject"].startswith("[Examination fee] Payment not owed")]
    assert len(alert) == 1 and "Refund it in Stripe" in alert[0]["html"]
    assert DEEP_LINK in alert[0]["html"]

    # The refund of that payment must not cancel the examination.
    db = SessionLocal()
    checkout_routes._revoke_for_payment(db, f"pi_{r.json()['session_id']}", "refunded")
    db.close()
    assert _row(row_id).status == "purchased"


# -----------------------------------------------------------------------------
# Neighbouring fixes
# -----------------------------------------------------------------------------

def test_a_comp_is_recorded_and_its_email_does_not_thank_anyone_for_a_payment(candidates, outbox):
    """'Comp candidate' used the paid-registration email, which opens with
    "Thank you. Your payment ... went through." A comp says it is free."""
    with TestClient(app, base_url="https://testserver") as admin:
        r = admin.post(f"{ADMIN_API}/comp", json={"email": COMP, "product_code": PRODUCT},
                       headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["fee_status"] == "waived"
    assert r.json()["fee_log"][0]["event"] == "comped"
    assert r.json()["fee_log"][0]["by"] == conftest.ADMIN_EMAIL
    mail = _to(outbox, COMP)[-1]
    assert "Your payment" not in mail["html"] and "at no charge" in mail["html"]
    assert "Start the written examination" in mail["html"]
    paid = E.advanced_purchased_html("Ada", "Course X", "https://x/learn", "$300")
    assert "Your payment" in paid and "$300" in paid


def test_the_oral_exam_alert_links_to_the_course_tab(candidates, outbox):
    """The '[Oral exam]' email linked to #courses/<product code>/certification,
    which is no course at all; it must name the course that sells the product."""
    c = candidates[DEFER]  # paid, written exam passed: may propose windows
    future = [(datetime.now(timezone.utc) + timedelta(days=4)).isoformat()]
    assert c.post(f"/api/academy/advanced/{PRODUCT}/slots",
                  json={"slots": future, "timezone": "UTC"}).status_code == 200
    alerts = [m for m in outbox if m["subject"].startswith("[Oral exam]")]
    assert len(alerts) == 1 and DEEP_LINK in alerts[0]["html"]
    assert f"#courses/{PRODUCT}/certification" not in alerts[0]["html"]
