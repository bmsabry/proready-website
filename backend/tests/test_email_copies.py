"""Opening any sent email from Admin → Comms.

What the owner asked for (2026-09-28): click an email in the log and see the
email itself, with nothing cut off. What is asserted:

  * Every send keeps a copy — headers, the HTML and text bodies, attachment
    names, and why it failed when it did — minus sign-in tokens.
  * Emails sent before copies were kept are fetched back from Resend (which
    keeps them 30 days) and then kept here, so they stay readable.
  * Opening an email asks Resend what became of it (delivered, bounced…).
  * The list can be searched and narrowed to customers, to "me", or to
    problems, and says in words what each email was and what it was about.

Resend is faked at its two seams: emailer._resend_post (sending) and
email_copies._resend_get (reading back).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import conftest  # noqa: F401
from app import email_copies as copies
from app import emailer as E
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import EmailLog, Learner

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"id": "re-msg-1"}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def resend(monkeypatch):
    """Sending succeeds with a fresh id; reading back is scripted per test."""
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    counter = {"n": 0}

    def post(url, payload, key):
        counter["n"] += 1
        if isinstance(payload, list):
            return _Resp(body={"data": [{"id": f"re-batch-{counter['n']}-{i}"} for i in range(len(payload))]})
        return _Resp(body={"id": f"re-msg-{counter['n']}"})

    monkeypatch.setattr(E, "_resend_post", post)
    stored: dict[str, _Resp] = {}
    asked: list[str] = []

    def get(url, key):
        asked.append(url)
        return stored.get(url.rsplit("/", 1)[-1], _Resp(404, {"message": "not found"}))

    monkeypatch.setattr(copies, "_resend_get", get)
    return stored, asked


def _latest(db, recipient: str) -> EmailLog:
    db.expire_all()
    return (
        db.query(EmailLog).filter(EmailLog.recipient == recipient).order_by(EmailLog.id.desc()).first()
    )


# ---------------------------------------------------------------------------
# A copy is kept at send time
# ---------------------------------------------------------------------------


def test_every_send_keeps_a_readable_copy(db, resend):
    ok = E.send_email(
        to="copy@example.com",
        subject="Your certificate",
        html="<p>Congratulations, Dana.</p>",
        cc="bmsabry@gmail.com",
        reply_to="info@mail.proreadyengineer.com",
        attachments=[{"filename": "certificate.pdf", "content": "JVBERi0="}],
        db=db,
        scope_kind="product",
        scope_code="dle-combustion-mapping",
        template="certificate_completion",
    )
    assert ok
    row = _latest(db, "copy@example.com")
    assert row.body_html == "<p>Congratulations, Dana.</p>"
    assert "Congratulations, Dana." in row.body_text
    assert row.cc == "bmsabry@gmail.com"
    assert row.reply_to == "info@mail.proreadyengineer.com"
    assert row.from_addr  # the From actually used
    assert row.attachments == "certificate.pdf", "the name is kept, never the file"
    assert row.copy_source == "sent" and row.error == ""


def test_a_sign_in_link_is_never_stored_with_its_token(db, resend):
    link = "https://proreadyengineer.com/learn/signin?token=SECRET-abc123&next=%2Flearn"
    E.send_email(
        to="signin@example.com",
        subject="Your sign-in link",
        html=f'<p><a href="{link.replace("&", "&amp;")}">Sign in</a></p>',
        db=db,
    )
    row = _latest(db, "signin@example.com")
    assert "SECRET-abc123" not in row.body_html and "SECRET-abc123" not in row.body_text
    assert "token=(hidden)" in row.body_html
    assert "next=%2Flearn" in row.body_html, "only the secret is blanked"


def test_a_failed_send_says_why(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    monkeypatch.setattr(
        E, "_resend_post",
        lambda url, payload, key: _Resp(422, {"name": "validation_error", "message": "Invalid `to` field."}),
    )
    assert E.send_email(to="bad@example", subject="Hi", html="<p>x</p>", db=db) is False
    row = _latest(db, "bad@example")
    assert row.ok is False
    assert row.error == "Resend refused it (HTTP 422): Invalid `to` field."
    assert row.body_html == "<p>x</p>", "a failed email can still be read"

    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "", raising=False)
    E.send_email(to="nokey@example.com", subject="Hi", html="<p>x</p>", db=db)
    assert "RESEND_API_KEY" in _latest(db, "nokey@example.com").error


def test_each_broadcast_recipient_gets_their_own_copy(db, resend):
    sent, failed = E.send_broadcast(
        db,
        ["b1@example.com", "b2@example.com"],
        "Start date moved",
        lambda to: f"<p>Hi {to.split('@')[0]}, the date moved.</p>",
        {"scope_kind": "course", "scope_code": "gt-2026", "audience": "all", "template": "start_date_updated"},
    )
    assert sent == 2 and not failed
    assert "Hi b1" in _latest(db, "b1@example.com").body_html
    assert "Hi b2" in _latest(db, "b2@example.com").body_html
    assert _latest(db, "b2@example.com").provider_id.startswith("re-batch-")


# ---------------------------------------------------------------------------
# Opening an email
# ---------------------------------------------------------------------------


def test_opening_an_email_shows_it_and_its_delivery(client, db, resend):
    stored, asked = resend
    E.send_email(
        to="open@example.com", subject="Joining details for Saturday",
        html="<p>The link is below.</p>", db=db, scope_kind="course",
        scope_code="gas-turbine-emissions-mapping-2026-05", audience="2026-09-13",
        template="session_reminder",
    )
    row = _latest(db, "open@example.com")
    stored[row.provider_id] = _Resp(body={"id": row.provider_id, "last_event": "delivered"})

    assert client.get(f"/api/admin/comms/log/{row.id}").status_code == 401
    d = client.get(f"/api/admin/comms/log/{row.id}", headers=ADMIN).json()
    assert d["html"] == "<p>The link is below.</p>" and d["copy"]["available"] is True
    assert d["subject"] == "Joining details for Saturday"
    assert d["kind_label"] == "Session reminder"
    assert d["about"]["href"] == "#courses/gas-turbine-emissions-mapping-2026-05"
    assert "session of Sep 13" in d["about"]["label"]
    assert d["delivery"]["label"] == "Delivered" and d["delivery"]["tone"] == "good"
    assert asked, "Resend was asked what became of it"


def test_a_bounce_shows_as_a_problem(client, db, resend):
    stored, _ = resend
    E.send_email(to="bounce@nowhere.example", subject="Receipt", html="<p>Thanks</p>", db=db)
    row = _latest(db, "bounce@nowhere.example")
    stored[row.provider_id] = _Resp(body={"id": row.provider_id, "last_event": "bounced"})
    d = client.get(f"/api/admin/comms/log/{row.id}", headers=ADMIN).json()
    assert d["delivery"]["label"] == "Bounced" and d["delivery"]["tone"] == "bad"
    problems = client.get("/api/admin/comms/log?problems=true", headers=ADMIN).json()["rows"]
    assert row.id in [r["id"] for r in problems]


def test_an_older_email_is_fetched_from_resend_and_then_kept(client, db, resend):
    stored, asked = resend
    old = EmailLog(
        scope_kind="support", scope_code="59772CB6", audience="ticket", template="support_reply",
        subject="Re: Consulting Services enquiry [#59772CB6]", recipient="zaur@example.com",
        ok=True, provider_id="re-old-1",
    )
    db.add(old)
    db.commit()
    stored["re-old-1"] = _Resp(body={
        "id": "re-old-1", "from": "ProReadyEngineer Support <info@mail.proreadyengineer.com>",
        "to": ["zaur@example.com"], "cc": [], "bcc": ["bmsabry@gmail.com"], "reply_to": ["info@mail.proreadyengineer.com"],
        "html": '<p>Hi Zaur, <a href="https://proreadyengineer.com/learn/signin?token=LIVE">sign in</a></p>',
        "text": "Hi Zaur", "last_event": "opened",
    })
    d = client.get(f"/api/admin/comms/log/{old.id}", headers=ADMIN).json()
    assert d["copy"]["available"] and d["copy"]["source"] == "resend"
    assert "Hi Zaur" in d["html"] and "LIVE" not in d["html"]
    assert d["bcc"] == "bmsabry@gmail.com" and d["from_addr"].startswith("ProReadyEngineer Support")
    assert d["delivery"]["label"] == "Opened"
    assert d["about"] == {"label": "Support ticket #59772CB6", "href": "#support/59772CB6"}

    # Kept: readable even once Resend has deleted it.
    del stored["re-old-1"]
    again = client.get(f"/api/admin/comms/log/{old.id}", headers=ADMIN).json()
    assert "Hi Zaur" in again["html"]


def test_an_email_resend_no_longer_has_says_so_plainly(client, db, resend):
    gone = EmailLog(
        scope_kind="support", scope_code="AB12CD34", audience="ticket", template="support_reply",
        subject="Re: old", recipient="old@example.com", ok=True, provider_id="re-gone-1",
    )
    db.add(gone)
    db.commit()
    d = client.get(f"/api/admin/comms/log/{gone.id}", headers=ADMIN).json()
    assert d["copy"]["available"] is False
    assert "30 days" in d["copy"]["note"] and "support ticket" in d["copy"]["note"]
    assert d["subject"] == "Re: old", "the headers are still shown"


def test_the_recipient_links_to_their_student_page(client, db, resend):
    learner = db.query(Learner).filter(Learner.email == "learner.copy@example.com").first()
    if learner is None:
        learner = Learner(email="learner.copy@example.com", full_name="Lina Learner")
        db.add(learner)
        db.commit()
    E.send_email(to="learner.copy@example.com", subject="Materials", html="<p>x</p>", db=db)
    row = _latest(db, "learner.copy@example.com")
    d = client.get(f"/api/admin/comms/log/{row.id}", headers=ADMIN).json()
    assert d["learner"] == {"id": learner.id, "name": "Lina Learner"}


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------


def test_the_list_is_searchable_and_splits_customers_from_me(client, db, resend):
    E.send_email(to="findme.customer@example.com", subject="Invoice 4471", html="<p>x</p>", db=db)
    E.send_email(to="bmsabry@gmail.com", subject="[Support #X] alert", html="<p>x</p>", db=db,
                 audience="admin", template="support_admin_alert")

    found = client.get("/api/admin/comms/log?q=invoice 4471", headers=ADMIN).json()["rows"]
    assert [r["recipient"] for r in found] == ["findme.customer@example.com"]
    assert client.get("/api/admin/comms/log?q=FINDME.customer", headers=ADMIN).json()["count"] == 1

    mine = client.get("/api/admin/comms/log?who=me", headers=ADMIN).json()["rows"]
    assert mine and all(r["to_me"] for r in mine)
    customers = client.get("/api/admin/comms/log?who=customers", headers=ADMIN).json()["rows"]
    assert customers and not any(r["to_me"] for r in customers)
    alert = next(r for r in mine if r["subject"] == "[Support #X] alert")
    assert alert["kind_label"] == "Support alert"


def test_show_older_pages_through_the_log(client, db, resend):
    for i in range(3):
        E.send_email(to=f"page{i}@example.com", subject=f"Page {i}", html="<p>x</p>", db=db)
    first = client.get("/api/admin/comms/log?limit=2", headers=ADMIN).json()
    assert first["has_more"] is True and len(first["rows"]) == 2
    older = client.get(f"/api/admin/comms/log?limit=2&before_id={first['rows'][-1]['id']}", headers=ADMIN).json()
    assert all(r["id"] < first["rows"][-1]["id"] for r in older["rows"])


# ---------------------------------------------------------------------------
# Saving copies of recent emails before Resend deletes them
# ---------------------------------------------------------------------------


def test_keeping_copies_saves_recent_ones_and_skips_what_resend_cannot_have(db, resend):
    stored, asked = resend
    now = datetime.now(timezone.utc)
    recent = EmailLog(recipient="r@example.com", subject="recent", ok=True, provider_id="re-bf-recent",
                      ts=now - timedelta(days=10))
    gone = EmailLog(recipient="g@example.com", subject="gone", ok=True, provider_id="re-bf-gone",
                    ts=now - timedelta(days=20))
    ancient = EmailLog(recipient="a@example.com", subject="ancient", ok=True, provider_id="re-bf-ancient",
                       ts=now - timedelta(days=60))
    db.add_all([recent, gone, ancient])
    db.commit()
    stored["re-bf-recent"] = _Resp(body={"html": "<p>kept</p>", "text": "kept", "last_event": "delivered"})

    out = copies.backfill(db, pause=0)
    db.expire_all()
    assert db.get(EmailLog, recent.id).body_html == "<p>kept</p>"
    assert db.get(EmailLog, recent.id).delivery == "delivered"
    assert db.get(EmailLog, gone.id).copy_source == "gone"
    assert not any("re-bf-ancient" in u for u in asked), "past Resend's 30 days: not asked"
    assert out["kept"] >= 1 and out["gone"] >= 1 and out["too_old"] >= 1

    # Running it again asks for nothing it already has or knows is gone.
    asked.clear()
    copies.backfill(db, pause=0)
    assert not any(u.endswith(("re-bf-recent", "re-bf-gone")) for u in asked)


def test_keep_copies_endpoint_is_admin_only_and_reports_the_queue(client, db, resend, monkeypatch):
    monkeypatch.setattr(copies, "backfill", lambda db, **kw: {"kept": 0})
    assert client.post("/api/admin/comms/keep-copies").status_code == 401
    r = client.post("/api/admin/comms/keep-copies", headers=ADMIN)
    assert r.status_code == 200 and r.json()["ok"] is True and "queued" in r.json()
