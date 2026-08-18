"""Support desk: intake, triage, threading, and the admin panel.

The LLM is faked throughout — these tests are about the routing rules that
sit around it, which are the part that can quietly lose a customer. What
is actually asserted:

  * A customer always hears back. Every intake path sends something, and
    the paths that exist *because* the model failed still send something.
  * Money and access questions never get an automated answer, however
    confident the model is.
  * A reply threads back onto its ticket rather than opening a new one —
    through the Message-ID, the [#REF] tag, or the subject, because real
    mail clients drop any given one of them.
  * A webhook retry does not become a second ticket.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import support_service as svc
from app.db import SessionLocal
from app.main import app
from app.models import SupportTicket, SupportTicketEvent, SupportTicketMessage
from tests.conftest import ADMIN_TOKEN

AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


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
    """Capture outbound mail instead of sending it.

    Patched at emailer.send_email — the seam every support send goes
    through — so the assertions cover what would actually leave.
    """
    sent: list[dict] = []

    def fake_send(to, subject, html, **kw):
        sent.append({"to": to, "subject": subject, "html": html, **kw})
        return True

    monkeypatch.setattr(svc, "send_email", fake_send)
    return sent


def fake_llm(monkeypatch, payload):
    """Make the classifier return `payload` (or None to simulate an outage)."""
    monkeypatch.setattr(svc, "_call_support_llm", lambda *a, **k: payload)


def ticket_by_ref(db, ref) -> SupportTicket:
    return db.execute(
        select(SupportTicket).where(SupportTicket.ref == ref)
    ).scalar_one()


def messages(db, ticket_id):
    return list(
        db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == ticket_id)
            .order_by(SupportTicketMessage.id)
        )
        .scalars()
        .all()
    )


def events(db, ticket_id):
    return [
        e.event_type
        for e in db.execute(
            select(SupportTicketEvent)
            .where(SupportTicketEvent.ticket_id == ticket_id)
            .order_by(SupportTicketEvent.id)
        )
        .scalars()
        .all()
    ]


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def test_contact_form_creates_ticket_and_auto_answers(client, db, monkeypatch, captured_mail):
    fake_llm(
        monkeypatch,
        {
            "category": "course_info",
            "priority": 6,
            "is_spam": False,
            "confidence": 0.9,
            "summary": "Asking how long the course runs.",
            "reply_html": "<p>It runs over five days.</p>",
            "can_auto_resolve": True,
            "escalation_reason": "",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={
            "name": "Dana Reed",
            "email": "dana@example.com",
            "subject": "Quick question",
            "message": "How many days is the gas turbine course?",
        },
    )
    assert r.status_code == 201
    ref = r.json()["ref"]
    assert len(ref) == 8

    t = ticket_by_ref(db, ref)
    assert t.status == "auto_resolved"
    assert t.category == "course_info"
    assert t.priority == 6
    assert t.resolved_at is not None
    assert t.first_responded_at is not None

    kinds = [m.sender_kind for m in messages(db, t.id)]
    assert kinds == ["customer", "ai"]
    assert "auto_resolved" in events(db, t.id)

    # The answer actually went out, tagged so a reply comes back to us.
    assert len(captured_mail) == 1
    assert captured_mail[0]["to"] == "dana@example.com"
    assert f"[#{ref}]" in captured_mail[0]["subject"]
    assert "five days" in captured_mail[0]["html"]


@pytest.mark.parametrize("category", sorted(svc.ESCALATE_ALWAYS))
def test_sensitive_categories_never_auto_resolve(
    client, db, monkeypatch, captured_mail, category
):
    """Money, access, faults and sales leads go to a human.

    The model is deliberately made maximally wrong here — high confidence,
    can_auto_resolve=True — because the whole point is that the routing
    rule overrides the model rather than trusting it.
    """
    fake_llm(
        monkeypatch,
        {
            "category": category,
            "priority": svc.CATEGORY_PRIORITY[category],
            "is_spam": False,
            "confidence": 0.99,
            "summary": "Model is sure it can handle this.",
            "reply_html": "<p>All sorted, no need to worry.</p>",
            "can_auto_resolve": True,
            "escalation_reason": "",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={
            "email": f"{category}@example.com",
            "subject": "Help",
            "message": "Something is wrong.",
        },
    )
    t = ticket_by_ref(db, r.json()["ref"])
    assert t.status == "escalated", f"{category} must reach a human"
    assert t.resolved_at is None
    # The customer still heard back immediately, and Bassam was alerted.
    assert any(m["to"] == f"{category}@example.com" for m in captured_mail)
    assert any(m.get("audience") == "admin" for m in captured_mail)


def test_low_confidence_blocks_auto_reply(client, db, monkeypatch):
    """A model unsure what it is reading doesn't get to answer alone."""
    fake_llm(
        monkeypatch,
        {
            "category": "general",
            "priority": 8,
            "is_spam": False,
            "confidence": 0.2,
            "summary": "Unclear.",
            "reply_html": "<p>Possibly this?</p>",
            "can_auto_resolve": True,
            "escalation_reason": "",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={"email": "vague@example.com", "subject": "hm", "message": "?"},
    )
    assert ticket_by_ref(db, r.json()["ref"]).status == "escalated"


def test_llm_outage_still_answers_and_escalates(client, db, monkeypatch, captured_mail):
    """The model being down must not mean silence."""
    fake_llm(monkeypatch, None)
    r = client.post(
        "/api/support/contact",
        json={
            "name": "Sam",
            "email": "sam@example.com",
            "subject": "Question",
            "message": "Are seats still open?",
        },
    )
    t = ticket_by_ref(db, r.json()["ref"])
    assert t.status == "escalated"
    assert t.first_responded_at is not None
    assert [m.sender_kind for m in messages(db, t.id)] == ["customer", "ai"]
    assert any("reached us" in m["html"] for m in captured_mail)


def test_spam_is_parked_without_replying(client, db, monkeypatch, captured_mail):
    """Never answer spam — a reply confirms the address is live."""
    fake_llm(
        monkeypatch,
        {
            "category": "general",
            "priority": 8,
            "is_spam": True,
            "confidence": 0.95,
            "summary": "SEO pitch.",
            "reply_html": "<p>ignored</p>",
            "can_auto_resolve": False,
            "escalation_reason": "",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={"email": "seo@spam.example", "subject": "Rank #1", "message": "Buy links"},
    )
    t = ticket_by_ref(db, r.json()["ref"])
    assert t.status == "spam" and t.is_spam is True
    assert captured_mail == []


def test_honeypot_is_accepted_and_discarded(client, db, captured_mail):
    """A bot gets a success page and nothing is created."""
    before = db.execute(select(SupportTicket)).scalars().all()
    r = client.post(
        "/api/support/contact",
        json={
            "email": "bot@example.com",
            "subject": "hi",
            "message": "hi",
            "website": "http://spam.example",
        },
    )
    assert r.status_code == 201
    assert r.json()["ref"] == "00000000"
    db.expire_all()
    assert len(db.execute(select(SupportTicket)).scalars().all()) == len(before)
    assert captured_mail == []


# ---------------------------------------------------------------------------
# Inbound email
# ---------------------------------------------------------------------------


def _inbound(client, **kw):
    payload = {
        "from": kw.get("from_", "Rae Lin <rae@example.com>"),
        "subject": kw.get("subject", "Hello"),
        "text": kw.get("text", "A question."),
        "headers": {
            "message-id": kw.get("message_id", "<abc@mail.example>"),
            "in-reply-to": kw.get("in_reply_to", ""),
            "references": kw.get("references", ""),
        },
    }
    return client.post("/api/webhooks/resend-inbound", json=payload)


def test_inbound_email_opens_a_ticket(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    assert _inbound(client, message_id="<new-1@mail.example>").status_code == 200
    t = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "rae@example.com")
    ).scalars().first()
    assert t is not None
    assert t.source == "inbound_email"
    assert t.submitter_name == "Rae Lin"


def test_reply_threads_onto_the_same_ticket(client, db, monkeypatch, captured_mail):
    """The core promise: a reply continues the conversation."""
    fake_llm(monkeypatch, None)
    r = client.post(
        "/api/support/contact",
        json={"email": "loop@example.com", "subject": "Access", "message": "First message."},
    )
    ref = r.json()["ref"]
    t = ticket_by_ref(db, ref)
    parent_message_id = t.email_message_id
    assert parent_message_id, "the outbound reply must carry a Message-ID to thread against"

    _inbound(
        client,
        from_="loop@example.com",
        subject=f"Re: Access [#{ref}]",
        text="Thanks, that worked.",
        message_id="<reply-1@mail.example>",
        in_reply_to=parent_message_id,
    )

    db.expire_all()
    assert len(db.execute(select(SupportTicket)).scalars().all()) >= 1
    same = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "loop@example.com")
    ).scalars().all()
    assert len(same) == 1, "a reply must not open a second ticket"
    assert any(
        m.sender_kind == "customer" and "that worked" in (m.body_text or "")
        for m in messages(db, same[0].id)
    )


def test_threading_survives_a_client_that_strips_headers(client, db, monkeypatch):
    """Only the [#REF] subject tag survives — it must be enough."""
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "tagonly@example.com", "subject": "Invoice", "message": "Hi."},
    ).json()["ref"]

    _inbound(
        client,
        from_="tagonly@example.com",
        subject=f"Re: Invoice [#{ref}]",
        text="Following up.",
        message_id="<bare-1@mail.example>",
        in_reply_to="",
        references="",
    )
    db.expire_all()
    found = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "tagonly@example.com")
    ).scalars().all()
    assert len(found) == 1


def test_duplicate_webhook_delivery_is_ignored(client, db, monkeypatch):
    """Resend retries on any non-2xx — retries must not multiply tickets."""
    fake_llm(monkeypatch, None)
    for _ in range(3):
        _inbound(client, from_="dupe@example.com", message_id="<same-id@mail.example>")
    db.expire_all()
    found = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "dupe@example.com")
    ).scalars().all()
    assert len(found) == 1
    assert sum(1 for m in messages(db, found[0].id) if m.sender_kind == "customer") == 1


def test_mail_from_our_own_address_is_dropped(client, db):
    """The loop guard: never auto-reply to ourselves."""
    before = len(db.execute(select(SupportTicket)).scalars().all())
    _inbound(client, from_="info@mail.proreadyengineer.com", message_id="<self@x>")
    db.expire_all()
    assert len(db.execute(select(SupportTicket)).scalars().all()) == before


def test_reply_on_an_escalated_ticket_does_not_re_trigger_the_bot(
    client, db, monkeypatch, captured_mail
):
    """Once a human owns the thread, the bot stops talking over him."""
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "human@example.com", "subject": "Refund", "message": "Please refund."},
    ).json()["ref"]
    t = ticket_by_ref(db, ref)
    assert t.status == "escalated"
    before = len([m for m in messages(db, t.id) if m.sender_kind == "ai"])

    _inbound(
        client,
        from_="human@example.com",
        subject=f"Re: Refund [#{ref}]",
        text="Any update?",
        message_id="<chase-1@mail.example>",
    )
    db.expire_all()
    t = ticket_by_ref(db, ref)
    after = len([m for m in messages(db, t.id) if m.sender_kind == "ai"])
    assert after == before, "no automated reply once escalated"


# ---------------------------------------------------------------------------
# Quoted-reply stripping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "My new question.\n\nOn Mon, 5 May 2026 at 10:00, Support <info@x.com> wrote:\n> old text\n> more old",
        "My new question.\n\n-----Original Message-----\nFrom: Support\nold text",
        "My new question.\n\n> quoted\n> quoted more",
    ],
)
def test_quoted_history_is_stripped(raw):
    assert svc.strip_quoted_reply(raw).strip() == "My new question."


def test_stripping_never_empties_a_message():
    """If the markers would eat everything, keep the original.

    A message shown with quote noise is cosmetic. A message shown as blank
    is a customer who thinks they were ignored.
    """
    only_quote = "On Mon, someone <a@b.c> wrote:\n> everything is quoted"
    assert svc.strip_quoted_reply(only_quote).strip() != ""


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------


def test_admin_endpoints_require_auth(client):
    for method, path in [
        ("get", "/api/admin/support/tickets"),
        ("get", "/api/admin/support/stats"),
        ("get", "/api/admin/support/settings"),
    ]:
        assert getattr(client, method)(path).status_code == 401


def test_admin_inbox_lists_and_sorts_by_priority(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    client.post(
        "/api/support/contact",
        json={"email": "p8@example.com", "subject": "Chat", "message": "hi"},
    )
    # Force one ticket to P1 so ordering is observable.
    low = client.post(
        "/api/support/contact",
        json={"email": "p1@example.com", "subject": "Charged twice", "message": "help"},
    ).json()["ref"]
    client.patch(
        f"/api/admin/support/tickets/{low}",
        json={"category": "payment"},
        headers=AUTH,
    )

    r = client.get("/api/admin/support/tickets", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "inbox should not be empty"
    assert items[0]["priority"] <= items[-1]["priority"]
    assert items[0]["ref"] == low


def test_admin_reply_sends_and_records(client, db, monkeypatch, captured_mail):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "reply@example.com", "subject": "Question", "message": "hi"},
    ).json()["ref"]
    captured_mail.clear()

    r = client.post(
        f"/api/admin/support/tickets/{ref}/reply",
        json={"body_html": "<p>Here is the answer.</p>", "set_status": "resolved"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["delivered"] is True
    assert r.json()["status"] == "resolved"

    db.expire_all()
    t = ticket_by_ref(db, ref)
    assert t.resolved_at is not None
    assert [m.sender_kind for m in messages(db, t.id)][-1] == "admin"
    assert "Here is the answer." in captured_mail[-1]["html"]
    assert f"[#{ref}]" in captured_mail[-1]["subject"]


def test_failed_send_leaves_the_ticket_open(client, db, monkeypatch):
    """A reply Resend refused has reached nobody — don't close the ticket."""
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "bounce@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    monkeypatch.setattr(svc, "send_email", lambda *a, **k: False)
    r = client.post(
        f"/api/admin/support/tickets/{ref}/reply",
        json={"body_html": "<p>Answer.</p>", "set_status": "resolved"},
        headers=AUTH,
    )
    assert r.json()["delivered"] is False
    assert r.json()["status"] == "escalated"
    assert r.json()["warning"]
    db.expire_all()
    assert ticket_by_ref(db, ref).resolved_at is None


def test_internal_note_is_never_emailed(client, db, monkeypatch, captured_mail):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "note@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]
    captured_mail.clear()

    assert client.post(
        f"/api/admin/support/tickets/{ref}/note",
        json={"body": "Called him, sending an invoice."},
        headers=AUTH,
    ).status_code == 200

    assert captured_mail == [], "notes must not leave the building"
    db.expire_all()
    t = ticket_by_ref(db, ref)
    assert messages(db, t.id)[-1].sender_kind == "note"


def test_notes_are_hidden_from_the_model(db, monkeypatch):
    """An internal note must not end up quoted back to the customer."""
    ticket = SupportTicket(ref="TESTNOTE", submitter_email="x@y.z", subject="s")
    msgs = [
        SupportTicketMessage(sender_kind="customer", body_text="the question"),
        SupportTicketMessage(sender_kind="note", body_text="he still owes us money"),
    ]
    rendered = svc._thread_for_prompt(msgs)
    assert "the question" in rendered
    assert "owes us money" not in rendered


def test_category_override_resets_priority(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "cat@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    r = client.patch(
        f"/api/admin/support/tickets/{ref}",
        json={"category": "payment"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["ticket"]["priority"] == svc.CATEGORY_PRIORITY["payment"]

    bad = client.patch(
        f"/api/admin/support/tickets/{ref}", json={"category": "nonsense"}, headers=AUTH
    )
    assert bad.status_code == 400


def test_ticket_detail_carries_customer_context(client, db, monkeypatch):
    """The thread view answers "who is this?" without a second lookup."""
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "ctx@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    body = client.get(f"/api/admin/support/tickets/{ref}", headers=AUTH).json()
    assert body["ticket"]["ref"] == ref
    assert "customer" in body
    assert body["customer"]["email"] == "ctx@example.com"
    assert body["messages"]
    assert body["events"]


def test_settings_roundtrip_keeps_the_key_when_left_blank(client, monkeypatch):
    """Saving the knowledge base must not wipe the stored credential."""
    monkeypatch.setenv("AI_SETTINGS_KEY", "u5Ml1_hZ8b7cQvVQ0M6RH8HRlqYRIbNJ0lWfR0dO5vE=")
    from app import crypto

    crypto._fernet.cache_clear()

    first = client.put(
        "/api/admin/support/settings",
        json={
            "api_url": "https://api.deepinfra.com/v1/openai",
            "api_key": "secret-key-1234",
            "model_name": "moonshotai/Kimi-K2.5",
            "kb_text": "Refunds within 14 days.",
        },
        headers=AUTH,
    )
    assert first.status_code == 200
    assert first.json()["api_key_masked"].endswith("1234")
    assert first.json()["is_configured"] is True

    second = client.put(
        "/api/admin/support/settings",
        json={
            "api_url": "https://api.deepinfra.com/v1/openai",
            "api_key": "",  # untouched
            "model_name": "moonshotai/Kimi-K2.5",
            "kb_text": "Refunds within 30 days.",
        },
        headers=AUTH,
    )
    assert second.json()["api_key_masked"].endswith("1234")
    assert second.json()["kb_text"] == "Refunds within 30 days."
    assert second.json()["is_configured"] is True


def test_support_settings_do_not_collide_with_the_assistant(client, db, monkeypatch):
    """Two rows, two scopes. Saving one must not overwrite the other."""
    monkeypatch.setenv("AI_SETTINGS_KEY", "u5Ml1_hZ8b7cQvVQ0M6RH8HRlqYRIbNJ0lWfR0dO5vE=")
    from app import crypto
    from app.models import AISettings

    crypto._fernet.cache_clear()

    client.put(
        "/api/admin/ai/settings",
        json={
            "api_url": "https://assistant.example/v1",
            "api_key": "assistant-key",
            "model_name": "assistant-model",
        },
        headers=AUTH,
    )
    client.put(
        "/api/admin/support/settings",
        json={
            "api_url": "https://support.example/v1",
            "api_key": "support-key",
            "model_name": "support-model",
            "kb_text": "",
        },
        headers=AUTH,
    )

    db.expire_all()
    rows = {
        r.scope: r for r in db.execute(select(AISettings)).scalars().all()
    }
    assert rows["assistant"].model_name == "assistant-model"
    assert rows["support"].model_name == "support-model"

    assert client.get("/api/admin/ai/settings", headers=AUTH).json()["model_name"] == "assistant-model"
    assert client.get("/api/admin/support/settings", headers=AUTH).json()["model_name"] == "support-model"


def test_support_falls_back_to_assistant_credentials(client, db, monkeypatch):
    """Support works the moment the assistant is configured."""
    monkeypatch.setenv("AI_SETTINGS_KEY", "u5Ml1_hZ8b7cQvVQ0M6RH8HRlqYRIbNJ0lWfR0dO5vE=")
    from app import crypto
    from app.models import AISettings

    crypto._fernet.cache_clear()
    for row in db.execute(select(AISettings)).scalars().all():
        db.delete(row)
    db.commit()

    assert svc.get_support_settings(db) is None

    client.put(
        "/api/admin/ai/settings",
        json={
            "api_url": "https://assistant.example/v1",
            "api_key": "assistant-key",
            "model_name": "assistant-model",
        },
        headers=AUTH,
    )
    db.expire_all()
    active = svc.get_support_settings(db)
    assert active is not None and active.model_name == "assistant-model"


def test_bulk_actions_only_touch_named_refs(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    keep = client.post(
        "/api/support/contact",
        json={"email": "keep@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]
    drop = client.post(
        "/api/support/contact",
        json={"email": "drop@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    r = client.post(
        "/api/admin/support/tickets/bulk",
        json={"refs": [drop], "action": "archive"},
        headers=AUTH,
    )
    assert r.json()["updated"] == 1
    db.expire_all()
    assert ticket_by_ref(db, drop).status == "archived"
    assert ticket_by_ref(db, keep).status != "archived"


def test_archived_and_spam_are_hidden_from_the_default_inbox(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "hidden@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]
    client.post(
        "/api/admin/support/tickets/bulk",
        json={"refs": [ref], "action": "archive"},
        headers=AUTH,
    )

    default = client.get("/api/admin/support/tickets", headers=AUTH).json()
    assert ref not in [i["ref"] for i in default["items"]]

    archived = client.get(
        "/api/admin/support/tickets?status_filter=archived", headers=AUTH
    ).json()
    assert ref in [i["ref"] for i in archived["items"]]


def test_search_matches_ref_email_and_subject(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={
            "name": "Priya Nandan",
            "email": "priya@findme.example",
            "subject": "Turbine mapping enquiry",
            "message": "hi",
        },
    ).json()["ref"]

    for q in (ref, "priya@findme", "turbine mapping", "Priya"):
        found = client.get(
            f"/api/admin/support/tickets?q={q}&status_filter=", headers=AUTH
        ).json()["items"]
        assert ref in [i["ref"] for i in found], f"search for {q!r} missed the ticket"


def test_stats_counts_what_needs_a_human(client, db, monkeypatch):
    fake_llm(monkeypatch, None)  # every ticket escalates
    client.post(
        "/api/support/contact",
        json={"email": "stat@example.com", "subject": "Q", "message": "hi"},
    )
    stats = client.get("/api/admin/support/stats", headers=AUTH).json()
    assert stats["needs_human"] >= 1
    assert stats["open"] >= 1
    assert stats["total"] >= 1


def test_draft_reports_a_clear_error_when_unconfigured(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "draft@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    monkeypatch.setattr(svc, "get_support_settings", lambda db: None)
    r = client.post(
        f"/api/admin/support/tickets/{ref}/draft", json={"instruction": ""}, headers=AUTH
    )
    assert r.status_code == 412
    assert "not configured" in r.json()["detail"].lower()


def test_draft_returns_editable_html_and_flags_gaps(client, db, monkeypatch):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "gap@example.com", "subject": "Refund", "message": "Can I refund?"},
    ).json()["ref"]

    fake_llm(
        monkeypatch,
        {
            "reply_html": "<p>Hi — about your refund…</p>",
            "needs_from_admin": ["Confirm whether the 14-day window applies here."],
            "suggested_status": "resolved",
        },
    )
    r = client.post(
        f"/api/admin/support/tickets/{ref}/draft",
        json={"instruction": "Be warm, offer a call."},
        headers=AUTH,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "<p>" in body["reply_html"]
    assert body["needs_from_admin"] == ["Confirm whether the 14-day window applies here."]
    # Drafting is not sending: the thread is unchanged.
    db.expire_all()
    t = ticket_by_ref(db, ref)
    assert all(m.sender_kind != "admin" for m in messages(db, t.id))
    assert "ai_draft" in events(db, t.id)


def test_retriage_lets_the_ai_try_again(client, db, monkeypatch, captured_mail):
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "retry@example.com", "subject": "Dates?", "message": "When?"},
    ).json()["ref"]
    assert ticket_by_ref(db, ref).status == "escalated"

    fake_llm(
        monkeypatch,
        {
            "category": "enrollment",
            "priority": 5,
            "is_spam": False,
            "confidence": 0.9,
            "summary": "Wants the dates.",
            "reply_html": "<p>The next cohort starts in May.</p>",
            "can_auto_resolve": True,
            "escalation_reason": "",
        },
    )
    assert client.post(
        f"/api/admin/support/tickets/{ref}/retriage", headers=AUTH
    ).status_code == 200

    db.expire_all()
    t = ticket_by_ref(db, ref)
    assert t.status == "auto_resolved"
    assert t.category == "enrollment"


def test_ai_gives_up_after_the_attempt_cap(client, db, monkeypatch):
    """A customer going round in circles with a bot gets a human."""
    answerable = {
        "category": "general",
        "priority": 8,
        "is_spam": False,
        "confidence": 0.95,
        "summary": "Keeps asking.",
        "reply_html": "<p>Here you go.</p>",
        "can_auto_resolve": True,
        "escalation_reason": "",
    }
    fake_llm(monkeypatch, answerable)
    ref = client.post(
        "/api/support/contact",
        json={"email": "circles@example.com", "subject": "Still stuck", "message": "one"},
    ).json()["ref"]
    assert ticket_by_ref(db, ref).status == "auto_resolved"

    for n in range(2, 5):
        _inbound(
            client,
            from_="circles@example.com",
            subject=f"Re: Still stuck [#{ref}]",
            text=f"message {n}",
            message_id=f"<circle-{n}@mail.example>",
        )
        db.expire_all()

    t = ticket_by_ref(db, ref)
    assert t.status == "escalated", "the bot must hand over rather than loop forever"


def test_ref_is_not_guessable_from_the_id(client, db, monkeypatch):
    """Refs are random, not sequential — they appear in customer email."""
    fake_llm(monkeypatch, None)
    refs = [
        client.post(
            "/api/support/contact",
            json={"email": f"r{i}@example.com", "subject": "Q", "message": "hi"},
        ).json()["ref"]
        for i in range(3)
    ]
    assert len(set(refs)) == 3
    assert all(re.fullmatch(r"[0-9A-F]{8}", r) for r in refs)


# ---------------------------------------------------------------------------
# The admin AI assistant's ticket tools
# ---------------------------------------------------------------------------


def test_assistant_can_read_but_not_silently_send(client, db, monkeypatch):
    """Reading the inbox is free; speaking for Bassam is not.

    The whole safety story for the assistant is this asymmetry: it can
    triage all day without asking, but a customer-facing email pauses for
    an explicit Approve click.
    """
    from app.ai_tools import TOOL_HANDLERS, is_high_stakes

    assert is_high_stakes("reply_to_ticket", {"ref": "AB", "body": "hi"}) is True
    for read_only in ("list_tickets", "get_ticket", "get_support_stats", "add_ticket_note"):
        assert is_high_stakes(read_only, {}) is False
        assert read_only in TOOL_HANDLERS


def test_assistant_tools_see_the_thread_and_the_customer(client, db, monkeypatch):
    from app.ai_tools import get_ticket, get_support_stats, list_tickets

    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={
            "name": "Omar Haddad",
            "email": "omar@example.com",
            "subject": "Invoice question",
            "message": "Can I pay by bank transfer?",
        },
    ).json()["ref"]

    listed = list_tickets(db)
    assert listed["ok"] is True
    assert ref in [t["ref"] for t in listed["tickets"]]

    detail = get_ticket(db, ref=ref)
    assert detail["ok"] is True
    assert detail["ticket"]["from"] == "omar@example.com"
    assert any("bank transfer" in m["text"] for m in detail["thread"])
    assert detail["customer"]["email"] == "omar@example.com"

    assert get_support_stats(db)["open"] >= 1


def test_assistant_unknown_ref_returns_an_error_not_an_exception(db):
    """Handlers hand the agent an error it can reason about."""
    from app.ai_tools import get_ticket, reply_to_ticket, update_ticket

    for call in (
        lambda: get_ticket(db, ref="ZZZZZZZZ"),
        lambda: reply_to_ticket(db, ref="ZZZZZZZZ", body="hi"),
        lambda: update_ticket(db, ref="ZZZZZZZZ", status="resolved"),
    ):
        out = call()
        assert out["ok"] is False
        assert "ZZZZZZZZ" in out["error"]


def test_assistant_reply_records_and_can_resolve(client, db, monkeypatch, captured_mail):
    from app.ai_tools import reply_to_ticket

    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "agent@example.com", "subject": "Dates", "message": "When?"},
    ).json()["ref"]
    captured_mail.clear()

    out = reply_to_ticket(
        db, ref=ref, body="The next cohort starts on 15 May.", resolve=True
    )
    assert out["ok"] is True and out["delivered"] is True
    assert out["status"] == "resolved"
    assert "15 May" in captured_mail[-1]["html"]

    db.expire_all()
    t = ticket_by_ref(db, ref)
    assert messages(db, t.id)[-1].sender_kind == "admin"


def test_assistant_reply_does_not_resolve_on_a_failed_send(client, db, monkeypatch):
    from app.ai_tools import reply_to_ticket

    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "agentfail@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    monkeypatch.setattr(svc, "send_email", lambda *a, **k: False)
    out = reply_to_ticket(db, ref=ref, body="Answer.", resolve=True)
    assert out["delivered"] is False
    assert out["status"] == "escalated"
    assert "FAILED" in out["note"]


def test_assistant_rejects_invalid_status_and_category(client, db, monkeypatch):
    from app.ai_tools import update_ticket

    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "val@example.com", "subject": "Q", "message": "hi"},
    ).json()["ref"]

    assert update_ticket(db, ref=ref, status="banana")["ok"] is False
    assert update_ticket(db, ref=ref, category="banana")["ok"] is False

    ok = update_ticket(db, ref=ref, category="payment")
    assert ok["ok"] is True
    assert ok["ticket"]["priority"] == svc.CATEGORY_PRIORITY["payment"]


# ---------------------------------------------------------------------------
# Resend's real webhook shape
# ---------------------------------------------------------------------------


def test_metadata_only_webhook_fetches_the_body(client, db, monkeypatch):
    """Resend's email.received carries metadata only — no body, no headers.

    Without the follow-up fetch every inbound reply would land as an empty
    message, which looks to Bassam like the customer sent nothing.
    """
    fake_llm(monkeypatch, None)
    from app.routes import support as routes

    monkeypatch.setattr(
        routes,
        "_fetch_received_email",
        lambda email_id: {
            "subject": "Re: my order",
            "text": "The link still doesn't work for me.",
            "html": "<p>The link still doesn't work for me.</p>",
            "headers": {"Message-ID": "<fetched-1@mail.example>"},
        },
    )

    r = client.post(
        "/api/webhooks/resend-inbound",
        json={
            "type": "email.received",
            "created_at": "2026-08-17T10:00:00Z",
            "data": {
                "email_id": "abc-123",
                "from": "Nadia Aziz <nadia@example.com>",
                "to": ["info@mail.proreadyengineer.com"],
                "subject": "Re: my order",
                # No text, no html, no headers — exactly what Resend sends.
            },
        },
    )
    assert r.status_code == 200

    db.expire_all()
    t = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "nadia@example.com")
    ).scalars().first()
    assert t is not None
    assert "still doesn't work" in t.body
    assert any("still doesn't work" in (m.body_text or "") for m in messages(db, t.id))


def test_body_fetch_failure_still_creates_the_ticket(client, db, monkeypatch):
    """A dropped body is recoverable. A dropped ticket is not."""
    fake_llm(monkeypatch, None)
    from app.routes import support as routes

    monkeypatch.setattr(routes, "_fetch_received_email", lambda email_id: None)

    r = client.post(
        "/api/webhooks/resend-inbound",
        json={
            "data": {
                "email_id": "broken-1",
                "from": "quiet@example.com",
                "subject": "Something went wrong",
            }
        },
    )
    assert r.status_code == 200
    db.expire_all()
    t = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "quiet@example.com")
    ).scalars().first()
    assert t is not None, "the ticket must exist even with no body"
    assert t.subject == "Something went wrong"


def test_webhook_always_returns_200(client, db, monkeypatch):
    """A non-2xx makes Resend retry forever on a payload that cannot parse."""
    fake_llm(monkeypatch, None)
    for payload in (
        {},
        {"data": {}},
        {"data": {"from": ""}},
        {"nonsense": [1, 2, 3]},
        {"data": {"from": "x@y.z", "headers": [{"name": "Message-ID", "value": "<a@b>"}]}},
    ):
        assert client.post("/api/webhooks/resend-inbound", json=payload).status_code == 200
    # Not even valid JSON.
    assert client.post(
        "/api/webhooks/resend-inbound",
        content=b"this is not json",
        headers={"Content-Type": "application/json"},
    ).status_code == 200


def test_list_style_headers_are_understood(client, db, monkeypatch):
    """Some providers send headers as [{name, value}] rather than an object."""
    fake_llm(monkeypatch, None)
    ref = client.post(
        "/api/support/contact",
        json={"email": "listhdr@example.com", "subject": "Question", "message": "hi"},
    ).json()["ref"]
    db.expire_all()
    parent = ticket_by_ref(db, ref).email_message_id

    client.post(
        "/api/webhooks/resend-inbound",
        json={
            "data": {
                "from": "listhdr@example.com",
                "subject": "Re: Question",
                "text": "Following up.",
                "headers": [
                    {"name": "Message-ID", "value": "<list-1@mail.example>"},
                    {"name": "In-Reply-To", "value": parent},
                ],
            }
        },
    )
    db.expire_all()
    found = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "listhdr@example.com")
    ).scalars().all()
    assert len(found) == 1, "In-Reply-To from a list-style header must still thread"


# ---------------------------------------------------------------------------
# Cross-brand isolation
# ---------------------------------------------------------------------------
#
# Resend webhooks subscribe to EVENT TYPES, not domains — there is no
# per-domain filter anywhere in the dashboard or the API. Every
# `email.received` in the account is fanned out to every endpoint listening
# for it, and this account also serves promechdirectory.com, which runs its
# own support desk on its own inbound webhook. Without a recipient check,
# each business ingests the other's customers and answers them under the
# wrong brand. These tests are the guard on that.


def test_mail_for_another_brand_is_ignored(client, db, monkeypatch, captured_mail):
    """A ProMechDirectory customer must never open a ProReadyEngineer ticket."""
    fake_llm(monkeypatch, None)
    before = len(db.execute(select(SupportTicket)).scalars().all())

    r = client.post(
        "/api/webhooks/resend-inbound",
        json={
            "type": "email.received",
            "data": {
                "email_id": "promech-1",
                "from": "buyer@othercompany.example",
                "to": ["info@mail.promechdirectory.com"],
                "received_for": "info@mail.promechdirectory.com",
                "subject": "RFQ question",
                "text": "How do I submit an RFQ?",
            },
        },
    )
    assert r.status_code == 200
    db.expire_all()
    assert len(db.execute(select(SupportTicket)).scalars().all()) == before
    assert captured_mail == [], "must not auto-reply to another brand's customer"


def test_mail_for_us_is_accepted(client, db, monkeypatch):
    """The guard must not reject our own mail."""
    fake_llm(monkeypatch, None)
    client.post(
        "/api/webhooks/resend-inbound",
        json={
            "data": {
                "email_id": "ours-1",
                "from": "student@example.com",
                "to": ["info@mail.proreadyengineer.com"],
                "received_for": "info@mail.proreadyengineer.com",
                "subject": "Course dates",
                "text": "When does the next cohort run?",
            }
        },
    )
    db.expire_all()
    found = db.execute(
        select(SupportTicket).where(SupportTicket.submitter_email == "student@example.com")
    ).scalars().all()
    assert len(found) == 1


@pytest.mark.parametrize(
    "recipients,expected",
    [
        (["info@mail.proreadyengineer.com"], True),
        (["ProReadyEngineer <info@mail.proreadyengineer.com>"], True),
        (["INFO@MAIL.PROREADYENGINEER.COM"], True),
        (["anything@mail.proreadyengineer.com"], True),
        # Someone else on the same Resend account.
        (["info@mail.promechdirectory.com"], False),
        (["support@promechdirectory.com"], False),
        # Multi-recipient: ours anywhere in the list counts.
        (["info@mail.promechdirectory.com", "info@mail.proreadyengineer.com"], True),
        ("a@promechdirectory.com, info@mail.proreadyengineer.com", True),
        # Unknown/absent recipient: treated as ours so a human still sees it.
        ([], True),
        (None, True),
        (["not-an-address"], True),
        # A lookalike domain must NOT pass.
        (["info@mail.proreadyengineer.com.evil.example"], False),
        (["info@notmail.proreadyengineer.com"], False),
    ],
)
def test_recipient_matching(recipients, expected):
    assert svc.is_for_us(recipients) is expected


def test_promech_inbound_does_not_reach_our_triage(client, db, monkeypatch):
    """End to end: the fan-out lands, and nothing at all happens."""
    calls = []
    monkeypatch.setattr(
        svc, "process_ticket", lambda db_, tid: calls.append(tid)
    )
    for addr in (
        "info@mail.promechdirectory.com",
        "sales@promechdirectory.com",
    ):
        client.post(
            "/api/webhooks/resend-inbound",
            json={
                "data": {
                    "from": "someone@example.com",
                    "received_for": addr,
                    "subject": "Not ours",
                    "text": "hello",
                }
            },
        )
    assert calls == [], "triage must never run for another brand's mail"


# ---------------------------------------------------------------------------
# Attendance confirmation
# ---------------------------------------------------------------------------
#
# The workflow this supports: broadcast "reply to confirm your seat", then
# chase whoever didn't. That only works if replies come back to the desk
# AND get recorded against the registration — an inbox full of "yes I'll be
# there" that nobody has counted is not a confirmation list.


@pytest.fixture()
def attend_course(db):
    """The test cohort. Created once, reused — the DB is session-scoped."""
    from datetime import date

    from app.models import Course

    course = db.execute(
        select(Course).where(Course.code == "attend-test")
    ).scalar_one_or_none()
    if course is None:
        course = Course(
            code="attend-test", title="Attendance Test Course",
            start_date=date(2026, 12, 1), total_seats=10,
        )
        db.add(course)
        db.commit()
    return course


@pytest.fixture()
def registrant(db, attend_course):
    """Exactly one active registration for yusuf@example.com.

    Rebuilt per test rather than appended: the test DB persists across the
    module, and a fixture that stacked duplicate rows would make
    confirm_attendance look like it was confirming three seats.
    """
    from app.models import Registration

    for old in db.execute(
        select(Registration).where(Registration.email == "yusuf@example.com")
    ).scalars().all():
        db.delete(old)
    db.commit()

    reg = Registration(
        course_code="attend-test", full_name="Yusuf Kaya",
        email="yusuf@example.com", job_title="Engineer", company="Acme",
        years_experience="5", location="TR", status="pending",
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    yield reg


def test_broadcast_replies_come_back_to_the_desk(client, db, monkeypatch, attend_course):
    """A broadcast asking a question must route answers to the support desk.

    Without this the replies land in a personal inbox and the whole
    confirm-your-seat workflow is manual again.
    """
    captured = {}

    def fake_broadcast(db_, recipients, subject, html_builder, scope, reply_to=None):
        captured["reply_to"] = reply_to
        captured["recipients"] = list(recipients)
        return len(list(recipients)), []

    from app.routes import courses as courses_routes

    monkeypatch.setattr(courses_routes, "send_broadcast", fake_broadcast)
    r = client.post(
        "/api/admin/courses/attend-test/notify",
        json={
            "subject": "Please confirm your seat",
            "body_html": "<p>Reply to confirm.</p>",
            "audience": "all",
        },
        headers=AUTH,
    )
    assert r.status_code == 200
    assert captured["reply_to"] == svc.SUPPORT_ADDRESS, (
        "broadcast replies must return to the support desk"
    )


def test_confirmation_reply_marks_the_registration(client, db, monkeypatch, registrant):
    fake_llm(
        monkeypatch,
        {
            "category": "attendance",
            "priority": 8,
            "is_spam": False,
            "confidence": 0.95,
            "summary": "Confirming attendance.",
            "reply_html": "",
            "can_auto_resolve": True,
            "escalation_reason": "",
        },
    )
    assert registrant.attendance_confirmed_at is None

    r = client.post(
        "/api/support/contact",
        json={
            "name": "Yusuf Kaya",
            "email": "yusuf@example.com",
            "subject": "Re: Please confirm your seat",
            "message": "Yes, confirming I will attend. Looking forward to it.",
        },
    )
    ref = r.json()["ref"]

    db.expire_all()
    db.refresh(registrant)
    assert registrant.attendance_confirmed_at is not None, "the reply must be recorded"
    t = ticket_by_ref(db, ref)
    assert t.status == "auto_resolved"
    assert t.category == "attendance"
    assert "attendance_confirmed" in events(db, t.id)


def test_confirmation_is_recorded_even_when_a_human_is_wanted(
    client, db, monkeypatch, registrant
):
    """The bug this exists to prevent, exactly as it happened in production.

    A registrant replied "Confirmed and thank you". The classifier tagged it
    attendance with 0.98 confidence — and then said a human should handle the
    thread. The attendance branch sat below the can_auto_resolve gate, so the
    function returned before recording anything: the seat stayed unconfirmed,
    the answer sat unread in a ticket, and the honest report to Bassam was
    "nobody has confirmed".

    Whether a person needs to read the thread has nothing to do with whether
    this registrant said they are coming. Record the fact; escalate anyway.
    """
    fake_llm(
        monkeypatch,
        {
            "category": "attendance",
            "priority": 8,
            "is_spam": False,
            "confidence": 0.98,
            "summary": "Customer is confirming their attendance.",
            "reply_html": "<p>Thank you for confirming.</p>",
            "can_auto_resolve": False,
            "escalation_reason": "Attendance status update requires human handling.",
        },
    )
    assert registrant.attendance_confirmed_at is None

    r = client.post(
        "/api/support/contact",
        json={
            "email": "yusuf@example.com",
            "subject": "Re: Confirm Your Seat",
            "message": "Confirmed and thank you",
        },
    )
    ref = r.json()["ref"]

    db.expire_all()
    db.refresh(registrant)
    assert registrant.attendance_confirmed_at is not None, (
        "a confirmation must be recorded even when the ticket escalates"
    )

    t = ticket_by_ref(db, ref)
    assert t.status == "escalated", "the human review the classifier asked for still happens"
    assert "attendance_confirmed" in events(db, t.id)


def test_escalated_confirmation_says_it_was_already_recorded(
    client, db, monkeypatch, registrant
):
    """The inbox has to show the seat is marked, or Bassam chases someone who
    already answered."""
    fake_llm(
        monkeypatch,
        {
            "category": "attendance", "priority": 8, "is_spam": False,
            "confidence": 0.98, "summary": "Confirming.",
            "reply_html": "<p>Thanks.</p>", "can_auto_resolve": False,
            "escalation_reason": "Needs a human.",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={"email": "yusuf@example.com", "subject": "Re: confirm", "message": "Confirmed"},
    )
    t = ticket_by_ref(db, r.json()["ref"])
    payloads = [
        e.payload for e in db.execute(
            select(SupportTicketEvent).where(SupportTicketEvent.ticket_id == t.id)
        ).scalars().all()
        if e.event_type == "escalated"
    ]
    joined = " ".join(str(p) for p in payloads)
    assert "already recorded" in joined


def test_unconfirmed_list_flags_people_who_did_reply(client, db, monkeypatch, registrant):
    """If someone emailed a confirmation and it never reached their row, that
    gap must be visible — otherwise the assistant reports 'nobody confirmed'
    while the answer sits in the support desk."""
    from app.ai_tools import list_unconfirmed

    fake_llm(
        monkeypatch,
        {
            "category": "attendance", "priority": 8, "is_spam": False,
            "confidence": 0.98, "summary": "Confirming attendance.",
            "reply_html": "<p>Thanks.</p>", "can_auto_resolve": False,
            "escalation_reason": "Needs a human.",
        },
    )
    client.post(
        "/api/support/contact",
        json={"email": "yusuf@example.com", "subject": "Re: confirm", "message": "Confirmed"},
    )

    # Simulate the old broken state: ticket exists, registration not marked.
    db.expire_all()
    db.refresh(registrant)
    registrant.attendance_confirmed_at = None
    db.commit()

    out = list_unconfirmed(db, course_code="attend-test")
    assert out["replied_but_unmarked"], "the mismatch must be surfaced, not hidden"
    assert out["replied_but_unmarked"][0]["email"] == "yusuf@example.com"
    assert "warning" in out


def test_confirmation_survives_the_attempt_cap(client, db, monkeypatch, registrant):
    """Someone who confirms on the third message still confirmed.

    The attempt cap exists to stop the AI talking in circles, not to decide
    whether a registrant is coming. Recording sits above that gate too.
    """
    fake_llm(
        monkeypatch,
        {
            "category": "attendance", "priority": 8, "is_spam": False,
            "confidence": 0.97, "summary": "Confirming, finally.",
            "reply_html": "", "can_auto_resolve": True, "escalation_reason": "",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={"email": "yusuf@example.com", "subject": "Re: confirm", "message": "Yes."},
    )
    t = ticket_by_ref(db, r.json()["ref"])

    # Burn through the cap, clear the confirmation, and triage once more.
    t.ai_attempt_count = svc.MAX_AI_ATTEMPTS + 5
    registrant.attendance_confirmed_at = None
    db.commit()
    svc.process_ticket(db, t.id)

    db.expire_all()
    db.refresh(registrant)
    assert registrant.attendance_confirmed_at is not None, (
        "an exhausted thread must still record the confirmation"
    )


def test_a_miscategorised_confirmation_is_still_flagged(client, db, monkeypatch, registrant):
    """The categoriser is a language model. "Confirmed, and one question about
    the software" can land in course_info — and then nothing records the
    confirmation. The cross-check must not itself depend on the category being
    right, or it only catches the cases that were never going to be lost."""
    from app.ai_tools import list_unconfirmed

    fake_llm(
        monkeypatch,
        {
            "category": "course_info", "priority": 6, "is_spam": False,
            "confidence": 0.9, "summary": "Confirming, plus a question.",
            "reply_html": "<p>Thanks.</p>", "can_auto_resolve": False,
            "escalation_reason": "Needs a human.",
        },
    )
    client.post(
        "/api/support/contact",
        json={
            "email": "yusuf@example.com",
            "subject": "Re: confirm",
            "message": "Confirmed. Also, which software will we use?",
        },
    )

    out = list_unconfirmed(db, course_code="attend-test")
    flagged = out["replied_but_unmarked"]
    assert flagged, "a confirmation hiding in another category must still surface"
    assert all(f["email"] == "yusuf@example.com" for f in flagged)
    # Other tests in this module leave tickets behind, so find ours by category
    # rather than assuming it sorts first.
    mine = [f for f in flagged if f["category"] == "course_info"]
    assert mine, "the course_info ticket must be in the list"
    assert mine[0]["looks_like_a_confirmation"] is False


def test_confirmation_names_the_course_back(client, db, monkeypatch, registrant, captured_mail):
    """Say what was confirmed, not a vague 'you're all set'."""
    fake_llm(
        monkeypatch,
        {
            "category": "attendance", "priority": 8, "is_spam": False,
            "confidence": 0.95, "summary": "Confirming.", "reply_html": "",
            "can_auto_resolve": True, "escalation_reason": "",
        },
    )
    client.post(
        "/api/support/contact",
        json={"email": "yusuf@example.com", "subject": "Re: confirm", "message": "Yes."},
    )
    assert any("Attendance Test Course" in m["html"] for m in captured_mail)


def test_confirmation_from_an_unknown_address_is_not_faked(client, db, monkeypatch, captured_mail):
    """Never tell someone they're confirmed when we can't find them."""
    fake_llm(
        monkeypatch,
        {
            "category": "attendance", "priority": 8, "is_spam": False,
            "confidence": 0.95, "summary": "Confirming.", "reply_html": "",
            "can_auto_resolve": True, "escalation_reason": "",
        },
    )
    r = client.post(
        "/api/support/contact",
        json={"email": "nobody@example.com", "subject": "Re: confirm", "message": "Yes I'll be there."},
    )
    t = ticket_by_ref(db, r.json()["ref"])
    assert t.status == "escalated", "an unmatched confirmation needs a human"
    joined = " ".join(m["html"] for m in captured_mail)
    assert "could not match" in joined.lower()
    assert "is confirmed" not in joined.lower()


def test_cancelled_registrations_are_not_resurrected(client, db, monkeypatch):
    """Someone who withdrew and later replies to an old broadcast stays out."""
    from app.models import Registration

    reg = Registration(
        course_code="attend-test", full_name="Gone Away",
        email="gone@example.com", job_title="x", company="y",
        years_experience="1", location="z", status="cancelled",
    )
    db.add(reg)
    db.commit()

    confirmed = svc.confirm_attendance(db, "gone@example.com")
    assert confirmed == []
    db.refresh(reg)
    assert reg.attendance_confirmed_at is None


def test_confirming_twice_keeps_the_first_timestamp(db, registrant):
    first = svc.confirm_attendance(db, "yusuf@example.com")
    db.commit()
    assert len(first) == 1
    again = svc.confirm_attendance(db, "yusuf@example.com")
    db.commit()
    assert again[0]["confirmed_at"] == first[0]["confirmed_at"]


def test_assistant_can_list_who_has_not_confirmed(db, registrant):
    from app.ai_tools import list_unconfirmed, mark_attendance_confirmed

    before = list_unconfirmed(db, course_code="attend-test")
    assert before["ok"] is True
    assert "yusuf@example.com" in [r["email"] for r in before["unconfirmed"]]

    out = mark_attendance_confirmed(db, email="yusuf@example.com")
    assert out["ok"] is True

    after = list_unconfirmed(db, course_code="attend-test")
    assert "yusuf@example.com" not in [r["email"] for r in after["unconfirmed"]]
    assert "yusuf@example.com" in [r["email"] for r in after["confirmed"]]
    assert after["confirmed_count"] >= 1


def test_admin_can_confirm_attendance_by_hand(client, db, registrant):
    """Not every confirmation arrives by email.

    Someone says yes on a call, or replies from an address they didn't
    register with. Without a way to record that, the admin's confirmed list
    is wrong and the only correction available is the database.
    """
    r = client.post(
        "/api/admin/attendance",
        json={"registration_id": registrant.id, "confirmed": True},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["registration"]["attendance_confirmed_at"] is not None

    db.refresh(registrant)
    assert registrant.attendance_confirmed_at is not None


def test_confirming_by_hand_twice_keeps_the_first_timestamp(client, db, registrant):
    first = client.post(
        "/api/admin/attendance",
        json={"registration_id": registrant.id, "confirmed": True},
        headers=AUTH,
    ).json()["registration"]["attendance_confirmed_at"]
    second = client.post(
        "/api/admin/attendance",
        json={"registration_id": registrant.id, "confirmed": True},
        headers=AUTH,
    ).json()["registration"]["attendance_confirmed_at"]
    assert first == second, "re-confirming must not rewrite when they answered"


def test_admin_can_undo_a_confirmation(client, db, registrant):
    """A confirmation recorded against the wrong person has to be reversible."""
    client.post(
        "/api/admin/attendance",
        json={"registration_id": registrant.id, "confirmed": True},
        headers=AUTH,
    )
    r = client.post(
        "/api/admin/attendance",
        json={"registration_id": registrant.id, "confirmed": False},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["registration"]["attendance_confirmed_at"] is None
    db.refresh(registrant)
    assert registrant.attendance_confirmed_at is None


def test_attendance_endpoint_is_admin_only_and_404s_cleanly(client, registrant):
    assert client.post(
        "/api/admin/attendance", json={"registration_id": registrant.id}
    ).status_code in (401, 403)
    assert client.post(
        "/api/admin/attendance", json={"registration_id": 9_999_999}, headers=AUTH
    ).status_code == 404


def test_admin_registration_list_exposes_the_confirmation(client, db, registrant):
    """The admin table renders this field — if the API stops sending it the
    Attendance column silently shows everyone as awaiting a reply."""
    rows = client.get(
        "/api/admin/registrations?course=attend-test", headers=AUTH
    ).json()
    row = next(r for r in rows if r["email"] == "yusuf@example.com")
    assert "attendance_confirmed_at" in row
    assert row["attendance_confirmed_at"] is None

    svc.confirm_attendance(db, "yusuf@example.com")
    db.commit()
    rows = client.get(
        "/api/admin/registrations?course=attend-test", headers=AUTH
    ).json()
    row = next(r for r in rows if r["email"] == "yusuf@example.com")
    assert row["attendance_confirmed_at"] is not None


def test_assistant_reports_unknown_course_and_email_cleanly(db):
    from app.ai_tools import list_unconfirmed, mark_attendance_confirmed

    assert list_unconfirmed(db, course_code="no-such-course")["ok"] is False
    assert mark_attendance_confirmed(db, email="nobody@nowhere.example")["ok"] is False


# ---------------------------------------------------------------------------
# The assistant knowing the website, and knowing where you are
# ---------------------------------------------------------------------------
#
# The complaint that produced these: standing inside a course workspace,
# with the course code on screen, the assistant asked "what is the course
# code?" — a question three separate tools could have answered.


def test_site_tools_read_real_pages(monkeypatch):
    from app import site_content
    from app.ai_tools import list_site_pages, read_site_page, search_site

    monkeypatch.setattr(
        site_content,
        "_refresh",
        lambda force=False: {
            "fetched_at": 9e9,
            "order": ["/training", "/services/gas-turbine-combustion"],
            "pages": {
                "/training": {"title": "Training", "text": "Gas Turbine Emissions Mapping runs live online."},
                "/services/gas-turbine-combustion": {
                    "title": "Combustion Consulting",
                    "text": "DLN and DLE combustion tuning, hydrogen conversion, dynamics diagnosis.",
                },
            },
        },
    )

    listed = list_site_pages(None)
    assert listed["ok"] is True and listed["count"] == 2

    page = read_site_page(None, path="/training")
    assert page["ok"] is True and "Emissions Mapping" in page["text"]

    # Path forgiveness — a trailing slash is not a different page.
    assert read_site_page(None, path="training")["ok"] is True

    found = search_site(None, query="hydrogen")
    assert found["count"] == 1
    assert found["results"][0]["path"] == "/services/gas-turbine-combustion"


def test_site_search_does_not_invent_matches(monkeypatch):
    """A miss must read as a miss, or the agent will pad it into a claim."""
    from app import site_content
    from app.ai_tools import search_site

    monkeypatch.setattr(
        site_content, "_refresh",
        lambda force=False: {"fetched_at": 9e9, "order": ["/x"],
                             "pages": {"/x": {"title": "X", "text": "nothing relevant"}}},
    )
    out = search_site(None, query="nuclear submarines")
    assert out["count"] == 0
    assert "do not claim" in out["note"].lower()


def test_unknown_page_lists_what_does_exist(monkeypatch):
    from app import site_content
    from app.ai_tools import read_site_page

    monkeypatch.setattr(
        site_content, "_refresh",
        lambda force=False: {"fetched_at": 9e9, "order": ["/training"],
                             "pages": {"/training": {"title": "T", "text": "t"}}},
    )
    out = read_site_page(None, path="/nope")
    assert out["ok"] is False
    assert "/training" in out["available_paths"]


def test_site_unreachable_degrades_to_an_error_not_a_crash(monkeypatch):
    from app import site_content
    from app.ai_tools import list_site_pages

    monkeypatch.setattr(
        site_content, "_refresh",
        lambda force=False: {"fetched_at": 0, "order": [], "pages": {}},
    )
    out = list_site_pages(None)
    assert out["ok"] is False
    assert "database" in out["error"].lower()


def test_page_context_reaches_the_system_prompt():
    """The fix for 'which course?' asked while standing in one."""
    from app.routes.ai import _build_initial_messages
    from app.schemas import AIChatMessage

    msgs = _build_initial_messages(
        [AIChatMessage(role="user", content="email these people")],
        'Admin → Courses → the cohort "gas-turbine-emissions-mapping-2026-05", '
        'on its registrations tab.',
    )
    system = msgs[0]["content"]
    assert msgs[0]["role"] == "system"
    assert "gas-turbine-emissions-mapping-2026-05" in system
    assert "WHERE HE IS RIGHT NOW" in system
    assert "do not ask" in system.lower()


def test_no_page_context_leaves_the_prompt_alone():
    from app.routes.ai import SYSTEM_PROMPT, _build_initial_messages
    from app.schemas import AIChatMessage

    msgs = _build_initial_messages([AIChatMessage(role="user", content="hi")], None)
    assert msgs[0]["content"] == SYSTEM_PROMPT


def test_prompt_forbids_asking_what_a_tool_answers():
    from app.routes.ai import SYSTEM_PROMPT

    assert "NEVER ask Bassam for something a tool can tell you" in SYSTEM_PROMPT
    # The exact questions it actually asked, now explicitly routed to tools.
    for q in ("what is the course code?", "what are the dates?"):
        assert q in SYSTEM_PROMPT
    assert "search_site" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Never invent a session time
# ---------------------------------------------------------------------------
#
# Asked to email registrants with the dates and local times, the assistant
# produced "9:00 AM UTC" — a time that appears nowhere in the data. That
# email goes to real people who would show up at the wrong hour. Courses
# now carry a real session time, and an unset one has to be admitted.


def test_course_summary_flags_a_missing_session_time(db):
    from datetime import date

    from app.ai_tools import _course_summary
    from app.models import Course

    c = db.execute(select(Course).where(Course.code == "notime")).scalar_one_or_none()
    if c is None:
        c = Course(code="notime", title="No Time Set",
                   start_date=date(2026, 9, 1), total_seats=5)
        db.add(c)
        db.commit()

    out = _course_summary(c, db)
    assert out["session_time_utc"] == ""
    assert "NO SESSION TIME IS SET" in out["session_time_note"]
    assert "guess" in out["session_time_note"].lower()


def test_course_summary_is_quiet_once_the_time_is_set(db):
    from datetime import date

    from app.ai_tools import _course_summary, update_course
    from app.models import Course

    c = db.execute(select(Course).where(Course.code == "hastime")).scalar_one_or_none()
    if c is None:
        db.add(Course(code="hastime", title="Timed", start_date=date(2026, 9, 1),
                      total_seats=5))
        db.commit()

    ok = update_course(db, code="hastime", session_time_utc="13:30",
                       session_duration_minutes=180)
    assert ok["ok"] is True

    c = db.execute(select(Course).where(Course.code == "hastime")).scalar_one()
    out = _course_summary(c, db)
    assert out["session_time_utc"] == "13:30"
    assert out["session_duration_minutes"] == 180
    assert out["session_time_note"] == ""


@pytest.mark.parametrize("bad", ["9am", "25:00", "13:60", "1:30", "noon"])
def test_bad_session_times_are_rejected(db, bad):
    from datetime import date

    from app.ai_tools import update_course
    from app.models import Course

    if db.execute(select(Course).where(Course.code == "tval")).scalar_one_or_none() is None:
        db.add(Course(code="tval", title="V", start_date=date(2026, 9, 1), total_seats=5))
        db.commit()
    out = update_course(db, code="tval", session_time_utc=bad)
    assert out["ok"] is False
    assert "HH:MM" in out["error"]


def test_session_time_can_be_cleared(db):
    from datetime import date

    from app.ai_tools import update_course
    from app.models import Course

    if db.execute(select(Course).where(Course.code == "tclear")).scalar_one_or_none() is None:
        db.add(Course(code="tclear", title="C", start_date=date(2026, 9, 1), total_seats=5))
        db.commit()
    assert update_course(db, code="tclear", session_time_utc="08:00")["ok"] is True
    assert update_course(db, code="tclear", session_time_utc="")["ok"] is True
    c = db.execute(select(Course).where(Course.code == "tclear")).scalar_one()
    assert c.session_time_utc == ""


def test_prompt_forbids_inventing_a_time():
    from app.routes.ai import SYSTEM_PROMPT

    assert "NEVER state a time of day" in SYSTEM_PROMPT
    assert "session_time_utc" in SYSTEM_PROMPT
    # Converting a real time to attendees' own zones is still encouraged —
    # it just has to go through the tool that does it correctly.
    assert "session_local_times" in SYSTEM_PROMPT


def test_patch_course_persists_the_session_time(client, db):
    """The PATCH handler silently dropped these fields when they shipped."""
    from datetime import date

    from app.models import Course

    if db.execute(select(Course).where(Course.code == "patchtime")).scalar_one_or_none() is None:
        db.add(Course(code="patchtime", title="P", start_date=date(2026, 9, 1), total_seats=5))
        db.commit()

    r = client.patch(
        "/api/admin/courses/patchtime",
        json={"session_time_utc": "14:00", "session_duration_minutes": 340},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["session_time_utc"] == "14:00"
    assert r.json()["session_duration_minutes"] == 340

    db.expire_all()
    c = db.execute(select(Course).where(Course.code == "patchtime")).scalar_one()
    assert c.session_time_utc == "14:00"


def test_prompt_sends_the_agent_to_the_website_for_times():
    from app.routes.ai import SYSTEM_PROMPT

    assert "PUBLISHED ON THE WEBSITE" in SYSTEM_PROMPT
    assert "/training/gas-turbine-emissions-mapping" in SYSTEM_PROMPT
    assert "disagree" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Local session times
# ---------------------------------------------------------------------------
#
# Registrants are in Ohio, British Columbia, Québec, Algeria and Saudi
# Arabia. "UTC+3" makes them do the conversion; "17:00 for you in Saudi
# Arabia" does not. The arithmetic lives in Python because offsets move
# with the season and an hour wrong is an attendee who misses a session.


@pytest.mark.parametrize(
    "location,expected",
    [
        ("West Chester Township", "America/New_York"),
        ("Kitimat, BC, CAN", "America/Vancouver"),   # BC beats CAN
        ("Kitimat, Canada", "America/Vancouver"),    # city beats country
        ("Montréal Canada", "America/Toronto"),
        ("Laghouat", "Africa/Algiers"),
        ("algeria", "Africa/Algiers"),
        ("Yanbu", "Asia/Riyadh"),
        ("  YANBU  ", "Asia/Riyadh"),
    ],
)
def test_real_registrant_locations_resolve(location, expected):
    from app.local_times import resolve_zone

    assert resolve_zone(location) == expected


@pytest.mark.parametrize("ambiguous", ["Kingston", "Springfield", "", "   ", "asdfgh"])
def test_ambiguous_places_resolve_to_nothing(ambiguous):
    """Kingston is Jamaica, Ontario, London and New York. Guessing is worse
    than admitting, because nobody double-checks a time that looks right."""
    from app.local_times import resolve_zone

    assert resolve_zone(ambiguous) is None


def test_country_substring_does_not_beat_the_city():
    """'south africa' must not be matched by 'africa', and 'new york' the
    city must not be swallowed by the 'york' in another word."""
    from app.local_times import resolve_zone

    assert resolve_zone("South Africa") == "Africa/Johannesburg"
    assert resolve_zone("New York") == "America/New_York"


def test_local_times_match_the_published_website_schedule():
    """14:00 UTC must reproduce exactly what /training already tells people:
    Pacific 07:00, Eastern 10:00, UTC+1 15:00, UTC+3 17:00."""
    from app.local_times import local_schedule

    out = local_schedule(
        session_time_utc="14:00",
        duration_minutes=340,
        day_dates=["2026-08-29", "2026-08-30", "2026-09-05", "2026-09-06"],
        locations=["Kitimat, BC, CAN", "Montréal Canada", "Laghouat", "Yanbu"],
    )
    assert out["ok"] is True
    first = {z["timezone"]: z["sessions"][0] for z in out["zones"]}
    assert first["America/Vancouver"]["start"] == "07:00"
    assert first["America/Toronto"]["start"] == "10:00"
    assert first["Africa/Algiers"]["start"] == "15:00"
    assert first["Asia/Riyadh"]["start"] == "17:00"
    # End of a 5h40m day, as published (Eastern 10:00 -> 15:40).
    assert first["America/Toronto"]["end"] == "15:40"
    assert first["Asia/Riyadh"]["end"] == "22:40"


def test_daylight_saving_is_handled_per_date():
    """The same UTC time is a different local hour in December. A fixed
    offset table would get this wrong and nobody would notice until people
    joined an hour late."""
    from app.local_times import local_schedule

    out = local_schedule(
        session_time_utc="14:00", duration_minutes=60,
        day_dates=["2026-08-29", "2026-12-15"], locations=["Montréal Canada"],
    )
    sessions = out["zones"][0]["sessions"]
    assert sessions[0]["start"] == "10:00" and sessions[0]["abbrev"] == "EDT"
    assert sessions[1]["start"] == "09:00" and sessions[1]["abbrev"] == "EST"


def test_unresolved_locations_are_reported_not_buried():
    from app.local_times import local_schedule

    out = local_schedule(
        session_time_utc="14:00", duration_minutes=60,
        day_dates=["2026-08-29"], locations=["Yanbu", "Kingston"],
    )
    assert "Kingston" in out["unresolved_locations"]
    assert [z["timezone"] for z in out["zones"]] == ["Asia/Riyadh"]


def test_no_session_time_refuses_rather_than_assuming_utc():
    from app.local_times import local_schedule

    out = local_schedule(
        session_time_utc="", duration_minutes=60,
        day_dates=["2026-08-29"], locations=["Yanbu"],
    )
    assert out["ok"] is False
    assert "website" in out["error"].lower()


def test_utc_anchor_is_always_returned():
    """Anyone whose zone is missing must still be able to convert."""
    from app.local_times import local_schedule

    out = local_schedule(
        session_time_utc="14:00", duration_minutes=60,
        day_dates=["2026-08-29"], locations=["Yanbu"],
    )
    assert out["utc_sessions"][0]["start"] == "14:00"
    assert "14:00 UTC" in out["note"]


def test_tool_groups_registrants_and_flags_the_unknown_ones(db):
    from datetime import date

    from app.ai_tools import session_local_times
    from app.models import Course, Registration

    if db.execute(select(Course).where(Course.code == "tz-course")).scalar_one_or_none() is None:
        db.add(Course(code="tz-course", title="TZ", start_date=date(2026, 8, 29),
                      total_seats=20, day_dates=["2026-08-29"],
                      session_time_utc="14:00", session_duration_minutes=340))
        db.commit()
    for old in db.execute(
        select(Registration).where(Registration.course_code == "tz-course")
    ).scalars().all():
        db.delete(old)
    db.commit()

    people = [
        ("Yusuf", "Yanbu", "YASREF"),
        ("Aissa", "Laghouat", "Sonatrach"),
        # Bare "Kingston" is ambiguous, but the company names the city.
        ("Tawfik", "Kingston", "Kingston University London"),
        ("Nobody", "Atlantis", "Unknown Co"),
    ]
    for name, loc, company in people:
        db.add(Registration(course_code="tz-course", full_name=name,
                            email=f"{name.lower()}@example.com", job_title="Eng",
                            company=company, years_experience="5", location=loc,
                            status="pending"))
    db.commit()

    out = session_local_times(db, course_code="tz-course")
    assert out["ok"] is True
    zones = {z["timezone"]: z for z in out["zones"]}
    assert zones["Asia/Riyadh"]["sessions"][0]["start"] == "17:00"
    assert zones["Africa/Algiers"]["sessions"][0]["start"] == "15:00"
    # Company rescued the ambiguous location.
    assert "Europe/London" in zones
    assert zones["Europe/London"]["sessions"][0]["start"] == "15:00"
    # The genuinely unknown one is named, not guessed.
    unknown = [u["name"] for u in out["registrants_without_a_known_timezone"]]
    assert unknown == ["Nobody"]
    assert "Do NOT guess" in out["unknown_warning"]
    # No empty zones padding the list.
    assert all(z["registrants"] for z in out["zones"])


def test_prompt_routes_timing_through_the_tool():
    from app.routes.ai import SYSTEM_PROMPT

    assert "session_local_times" in SYSTEM_PROMPT
    assert "never do this arithmetic yourself" in SYSTEM_PROMPT.lower()
