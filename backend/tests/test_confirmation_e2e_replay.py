"""End-to-end replay of the confirmation that got lost in production.

This is deliberately NOT a unit test of confirm_attendance. It drives the
whole chain the way a real reply drives it:

    Resend `email.received` webhook  (real payload shape: metadata only)
      -> GET /emails/receiving/{id}  (the body fetch, stubbed at the HTTP layer)
      -> is_for_us() recipient guard
      -> ingest_inbound()            (threading, ticket creation)
      -> triage                      (classifier output copied VERBATIM from
                                      production ticket 54D8E46F)
      -> confirm_attendance()
      -> registrations.attendance_confirmed_at

The classifier result below is not invented for the test. It is exactly what
the model returned for the real reply on 2026-08-18 — including
`can_auto_resolve: false`, which is what used to make the confirmation
disappear.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import support_service as svc
from app.db import SessionLocal
from app.main import app
from app.models import (
    Course,
    Registration,
    SupportTicket,
    SupportTicketEvent,
    SupportTicketMessage,
)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def captured_mail(monkeypatch):
    """Capture outbound mail instead of sending it — this replay must never
    put a real message in front of a real person."""
    sent: list[dict] = []

    def fake_send(to, subject, html, **kw):
        sent.append({"to": to, "subject": subject, "html": html, **kw})
        return True

    from app import emailer

    monkeypatch.setattr(emailer, "send_email", fake_send)
    monkeypatch.setattr(svc, "send_email", fake_send, raising=False)
    return sent

# Verbatim from production: GET /api/admin/support/tickets/54D8E46F -> ai_result
PRODUCTION_CLASSIFIER_OUTPUT = {
    "category": "attendance",
    "priority": 8,
    "is_spam": False,
    "confidence": 0.98,
    "summary": "Customer is confirming their attendance for the Gas Turbine Emissions Mapping cohort.",
    "reply_html": (
        "<p>Hi Sabry,</p><p>Thank you for confirming your attendance for the "
        "Gas Turbine Emissions Mapping cohort starting August 29, 2026. We have "
        "noted your confirmation and look forward to having you join us.</p>"
    ),
    "can_auto_resolve": False,
    "escalation_reason": (
        "Customer is replying on an existing ticket thread; attendance status "
        "update requires human handling."
    ),
    "source": "llm",
}

# The shape Resend actually POSTs for email.received: metadata, no body.
RESEND_INBOUND_PAYLOAD = {
    "type": "email.received",
    "created_at": "2026-08-18T20:46:34.000Z",
    "data": {
        "email_id": "b7c1e0f2-0000-4a00-9000-replayfixture",
        "from": "Sabry Hassan <replay@example.invalid>",
        "to": ["info@mail.proreadyengineer.com"],
        "received_for": "info@mail.proreadyengineer.com",
        "subject": "Re: Confirm Your Seat: Gas Turbine Emissions Mapping Training",
        "created_at": "2026-08-18T20:46:34.000Z",
    },
}

OTHER_BRAND_EMAIL_ID = "other-brand-id"

# What GET /emails/receiving/{id} returns — the part the webhook does not carry.
RECEIVED_EMAIL_BODY = {
    "id": "b7c1e0f2-0000-4a00-9000-replayfixture",
    "from": "Sabry Hassan <replay@example.invalid>",
    "to": ["info@mail.proreadyengineer.com"],
    "received_for": "info@mail.proreadyengineer.com",
    "subject": "Re: Confirm Your Seat: Gas Turbine Emissions Mapping Training",
    "text": "Confirmed and thank you\r\n\r\nSent from my iPhone",
    "html": "<div>Confirmed and thank you&nbsp;<div>Sent from my iPhone</div></div>",
    "headers": {
        "Message-ID": "<replay-inbound@mail.yahoo.com>",
        "In-Reply-To": "<broadcast-abc123@mail.proreadyengineer.com>",
    },
}


@pytest.fixture
def replay_registration(db):
    """One active registration for the address the replay replies from."""
    existing = db.execute(
        select(Course).where(Course.code == "e2e-replay-course")
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Course(
                code="e2e-replay-course",
                title="Gas Turbine Emissions Mapping",
                start_date=date(2026, 8, 29),
                total_seats=15,
                status="open",
                day_dates=["2026-08-29", "2026-08-30", "2026-09-05", "2026-09-06"],
            )
        )
    for old in db.execute(
        select(Registration).where(Registration.email == "replay@example.invalid")
    ).scalars().all():
        db.delete(old)
    db.commit()

    reg = Registration(
        course_code="e2e-replay-course",
        full_name="Sabry Hassan",
        email="replay@example.invalid",
        job_title="Engineer",
        company="Self Company",
        years_experience="10",
        location="Canada",
        status="pending",
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    yield reg

    # The test DB is shared across the whole session. Leaving this row behind
    # changes the counts other modules assert on, which shows up as an
    # unrelated test failing somewhere else.
    for t in db.execute(
        select(SupportTicket).where(
            SupportTicket.submitter_email == "replay@example.invalid"
        )
    ).scalars().all():
        # Messages and events too: inbound ingest dedupes on Message-ID, so a
        # surviving message row would make the next replay a no-op.
        for m in db.execute(
            select(SupportTicketMessage).where(
                SupportTicketMessage.ticket_id == t.id
            )
        ).scalars().all():
            db.delete(m)
        for e in db.execute(
            select(SupportTicketEvent).where(SupportTicketEvent.ticket_id == t.id)
        ).scalars().all():
            db.delete(e)
        db.delete(t)
    db.delete(reg)
    course = db.execute(
        select(Course).where(Course.code == "e2e-replay-course")
    ).scalar_one_or_none()
    if course is not None:
        db.delete(course)
    db.commit()


@pytest.fixture
def stub_resend_and_llm(monkeypatch):
    """Stub only the two external services: Resend's receiving API and the LLM.

    Everything between them — the route, the recipient guard, threading,
    ticket creation, triage branching, confirm_attendance — is the real code.
    """
    from app.routes import support as support_routes

    def fake_fetch(email_id: str):
        # The handler merges the recipients from the fetched record, because
        # that record is authoritative. So the stub has to stay consistent with
        # the id it was asked for, or the cross-brand case would quietly get our
        # own address handed back to it.
        if email_id == OTHER_BRAND_EMAIL_ID:
            return {
                **RECEIVED_EMAIL_BODY,
                "id": OTHER_BRAND_EMAIL_ID,
                "to": ["support@promechdirectory.com"],
                "received_for": "support@promechdirectory.com",
                "headers": {"Message-ID": "<other-brand-inbound@example.invalid>"},
            }
        return RECEIVED_EMAIL_BODY

    monkeypatch.setattr(support_routes, "_fetch_received_email", fake_fetch)
    monkeypatch.setattr(
        svc,
        "classify_ticket",
        lambda db, ticket, messages: dict(PRODUCTION_CLASSIFIER_OUTPUT),
    )


def test_a_real_reply_flips_the_registration(
    client, db, replay_registration, stub_resend_and_llm
):
    """The whole point: an inbound "Confirmed and thank you" must land on the row."""
    assert replay_registration.attendance_confirmed_at is None

    r = client.post("/api/webhooks/resend-inbound", json=RESEND_INBOUND_PAYLOAD)
    assert r.status_code == 200

    db.expire_all()
    db.refresh(replay_registration)
    assert replay_registration.attendance_confirmed_at is not None, (
        "the registration must be marked confirmed by the inbound reply alone"
    )


def test_the_reply_is_readable_in_the_desk(
    client, db, replay_registration, stub_resend_and_llm
):
    """The body has to survive the metadata-only webhook, or the ticket is blank."""
    client.post("/api/webhooks/resend-inbound", json=RESEND_INBOUND_PAYLOAD)

    ticket = db.execute(
        select(SupportTicket).where(
            SupportTicket.submitter_email == "replay@example.invalid"
        )
    ).scalars().first()
    assert ticket is not None, "the reply must become a ticket"
    assert ticket.category == "attendance"
    assert "Confirmed" in ticket.body


def test_another_brands_reply_is_ignored(
    client, db, replay_registration, stub_resend_and_llm
):
    """Resend fans every inbound in the account out to every endpoint. A reply
    addressed to promechdirectory.com must not touch this registration."""
    payload = {
        "type": "email.received",
        "data": {
            **RESEND_INBOUND_PAYLOAD["data"],
            "email_id": OTHER_BRAND_EMAIL_ID,
            "to": ["support@promechdirectory.com"],
            "received_for": "support@promechdirectory.com",
        },
    }
    r = client.post("/api/webhooks/resend-inbound", json=payload)
    assert r.status_code == 200

    db.expire_all()
    db.refresh(replay_registration)
    assert replay_registration.attendance_confirmed_at is None, (
        "another brand's inbound must never confirm a ProReadyEngineer seat"
    )


def test_it_is_the_reply_doing_the_work_not_the_fixture(
    client, db, replay_registration, monkeypatch
):
    """Negative control: with no inbound reply, nothing gets confirmed.

    Without this, a fixture bug that pre-confirmed the row would make the test
    above pass while proving nothing.
    """
    db.expire_all()
    db.refresh(replay_registration)
    assert replay_registration.attendance_confirmed_at is None
