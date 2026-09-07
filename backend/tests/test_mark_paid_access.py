"""Mark paid → the learner can get in, and the admin is told so.

What Bassam asked on 2026-09-06: "if I mark an attendee as Paid do they
immediately get access to the course material via the portal and an email
notification?" These tests pin the answer to yes, and pin the two things
that make it true in practice: the email's link lives long enough to be
read tomorrow, and the mark-paid response says what happened so the admin
never has to go and check.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import emailer as E
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Course, EmailLog, Enrollment, Learner, LoginToken, Product, Registration

from conftest import ADMIN_TOKEN

ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
PRODUCT = "mark-paid-test-product"
LINKED = "mark-paid-linked-course"
UNLINKED = "mark-paid-unlinked-course"


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-1"}


@pytest.fixture(autouse=True)
def resend_stub(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1])
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def world(client, db):
    """One product, one course linked to it, one course not linked."""
    for code in (LINKED, UNLINKED):
        db.execute(delete(Registration).where(Registration.course_code == code))
        db.execute(delete(EmailLog).where(EmailLog.scope_code == code))
        db.execute(delete(Course).where(Course.code == code))
    for l in db.execute(select(Learner).where(Learner.email.like("paid-%@example.com"))).scalars():
        db.execute(delete(Enrollment).where(Enrollment.learner_id == l.id))
        db.execute(delete(LoginToken).where(LoginToken.learner_id == l.id))
        db.delete(l)
    db.commit()
    if db.get(Product, PRODUCT) is None:
        r = client.post(
            "/api/admin/academy/products",
            json={"code": PRODUCT, "title": "Mark-paid Test Product", "status": "draft"},
            headers=ADMIN,
        )
        assert r.status_code == 200, r.text
    db.add(Course(code=LINKED, title="Linked cohort", start_date=date(2030, 1, 1), total_seats=10,
                  recorded_product_code=PRODUCT))
    db.add(Course(code=UNLINKED, title="Unlinked cohort", start_date=date(2030, 1, 1), total_seats=10))
    db.commit()


def _register(client, course, email, name="Paid Person"):
    r = client.post("/api/register", json={
        "course_code": course, "full_name": name, "email": email, "job_title": "Engineer",
        "company": "Co", "years_experience": "10", "location": "Mason, OH",
    })
    assert r.status_code == 200, r.text
    return r.json()["registration_id"]


def test_mark_paid_grants_access_and_emails_a_working_link(client, db, world, resend_stub):
    reg_id = _register(client, LINKED, "paid-one@example.com")

    r = client.post("/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["registration"]["status"] == "paid"
    assert body["transitioned"] is True
    assert body["materials_granted"] is True
    assert body["materials_email_sent"] is True
    assert body["materials_product"] == "Mark-paid Test Product"
    assert body["materials_note"] == ""

    # the email
    (payload,) = [p for p in resend_stub if p["subject"].startswith("Your course materials are ready")]
    assert payload["to"] == ["paid-one@example.com"]
    assert payload["subject"] == "Your course materials are ready — Mark-paid Test Product"
    assert "works for the next 7 days" in payload["html"]
    token = payload["html"].split("signin?token=")[1].split('"')[0]

    # it is logged for the comms tab
    row = db.execute(select(EmailLog).where(EmailLog.recipient == "paid-one@example.com",
                                            EmailLog.template == "materials_ready")).scalar_one()
    assert row.ok and row.scope_code == LINKED

    # the link signs the learner in and the course is open to them
    s = TestClient(app, base_url="https://testserver")
    v = s.post("/api/academy/auth/verify", json={"token": token})
    assert v.status_code == 200, v.text
    assert v.json()["next_path"] == f"/learn/{PRODUCT}"
    me = s.get("/api/academy/me").json()
    assert any(e["product_code"] == PRODUCT for e in me["enrollments"])
    assert s.get(f"/api/academy/course/{PRODUCT}").status_code == 200


def test_the_welcome_link_lives_seven_days_not_thirty_minutes(client, db, world):
    reg_id = _register(client, LINKED, "paid-two@example.com")
    before = datetime.now(timezone.utc)
    client.post("/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN)
    learner = db.execute(select(Learner).where(Learner.email == "paid-two@example.com")).scalar_one()
    tok = db.execute(select(LoginToken).where(LoginToken.learner_id == learner.id)).scalar_one()
    expires = tok.expires_at if tok.expires_at.tzinfo else tok.expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(days=6, hours=23) < expires - before <= timedelta(days=7, minutes=1)

    # a plain sign-in link a learner asks for keeps the short lifetime
    r = client.post("/api/academy/auth/request-link", json={"email": "paid-two@example.com"})
    assert r.status_code == 200
    toks = db.execute(select(LoginToken).where(LoginToken.learner_id == learner.id)
                      .order_by(LoginToken.id.desc())).scalars().all()
    newest = toks[0].expires_at if toks[0].expires_at.tzinfo else toks[0].expires_at.replace(tzinfo=timezone.utc)
    assert newest - datetime.now(timezone.utc) < timedelta(minutes=31)


def test_marking_paid_twice_does_not_resend(client, db, world, resend_stub):
    reg_id = _register(client, LINKED, "paid-three@example.com")
    client.post("/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN)
    n = len(resend_stub)
    r = client.post("/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["transitioned"] is False
    assert "already marked paid" in r.json()["materials_note"]
    assert len(resend_stub) == n


def test_a_course_with_no_product_says_so_instead_of_pretending(client, db, world, resend_stub):
    reg_id = _register(client, UNLINKED, "paid-four@example.com")
    r = client.post("/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["registration"]["status"] == "paid"
    assert body["materials_granted"] is False and body["materials_email_sent"] is False
    assert "no course-materials product is linked" in body["materials_note"]
    assert not [p for p in resend_stub if p["subject"].startswith("Your course materials")]


def test_an_email_failure_is_reported_not_hidden(client, db, world, monkeypatch):
    reg_id = _register(client, LINKED, "paid-five@example.com")
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: None)  # provider down
    r = client.post("/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["registration"]["status"] == "paid"  # the payment is never lost
    assert body["materials_granted"] is True          # access is live regardless
    assert body["materials_email_sent"] is False
    assert "could not be sent" in body["materials_note"]
    row = db.execute(select(EmailLog).where(EmailLog.recipient == "paid-five@example.com",
                                            EmailLog.template == "materials_ready")).scalar_one()
    assert row.ok is False
