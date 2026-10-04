"""Telling finishers that the examined tier is open.

A course can open its Certificate of Verified Competency after learners have
already earned the Certificate of Completion: their completion email could
only offer to request the examination. The owner asked (2026-10-04) that they
be told it is open now. POST .../certification/{code}/invite-examined sends
the instructor's note to the finishers named — a dry run unless told
otherwise, and only to learners who can register today.

Captured at the Resend seam (emailer._resend_post) on the shared SQLite DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import emailer as E  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Certificate, EmailLog, Learner, Product  # noqa: E402

PRODUCT = conftest.TEST_ADVANCED_PRODUCT
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
URL = f"/api/admin/academy/certification/{PRODUCT}/invite-examined"
BOOKING_URL = f"https://proreadyengineer.com/learn/{PRODUCT}?advanced=start"

FINISHER = "invited.finisher@example.com"
STILL_STUDYING = "still.studying@example.com"
ALREADY_VERIFIED = "already.verified@example.com"
NAMES = {FINISHER: "Ada Finisher", STILL_STUDYING: "Sam Studying", ALREADY_VERIFIED: "Val Verified"}
CERTS = (
    (FINISHER, "PRE-C-INVT-0001", "completion"),
    (ALREADY_VERIFIED, "PRE-C-INVT-0002", "completion"),
    (ALREADY_VERIFIED, "PRE-V-INVT-0002", "verified"),
)


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-invite-1"}


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1]
    )
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


@pytest.fixture(scope="module", autouse=True)
def three_learners():
    """A finisher, a learner still studying, and one who already holds the
    verified certificate — all with access. Their certificates are removed
    and the tier settings restored afterwards: the suite shares one DB."""
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
    ids = {l.email: l.id for l in db.query(Learner).filter(Learner.email.in_(NAMES)).all()}
    for email, code, tier in CERTS:
        db.add(Certificate(
            learner_id=ids[email], product_code=PRODUCT, code=code, learner_name=NAMES[email],
            tier=tier, status="issued", course_title=product.title,
            issued_at=datetime.now(timezone.utc),
        ))
    db.commit()
    db.close()
    yield
    from app.progress_guard import allow_progress_loss

    db = SessionLocal()
    with allow_progress_loss("test fixture: remove synthetic certificates"):
        db.query(Certificate).filter(
            Certificate.code.in_([code for _, code, _ in CERTS])
        ).delete(synchronize_session=False)
        db.commit()
    product = db.get(Product, PRODUCT)
    product.advanced_cert_enabled, product.advanced_cert_price_cents = was
    db.commit()
    db.close()


def _tier(enabled: bool) -> None:
    db = SessionLocal()
    product = db.get(Product, PRODUCT)
    product.advanced_cert_enabled = enabled
    product.advanced_cert_price_cents = 30000
    db.commit()
    db.close()


def _post(emails: list[str], **extra):
    with TestClient(app, base_url="https://testserver") as c:
        return c.post(URL, json={"emails": emails, **extra}, headers=ADMIN)


# -----------------------------------------------------------------------------

def test_admin_only():
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post(URL, json={"emails": [FINISHER], "dry_run": False})
    assert r.status_code in (401, 403)


def test_nothing_is_sent_while_the_tier_is_closed(outbox):
    _tier(False)
    r = _post([FINISHER], dry_run=False)
    assert r.status_code == 409
    assert outbox == []


def test_the_default_is_a_dry_run_naming_who_would_receive_it(outbox):
    _tier(True)
    r = _post([FINISHER, "Invited.Finisher@Example.com", STILL_STUDYING,
               ALREADY_VERIFIED, "nobody@example.com"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    rows = body["results"]
    # One row per address, case-insensitively, in the order given.
    assert [row["email"] for row in rows] == [
        FINISHER, STILL_STUDYING, ALREADY_VERIFIED, "nobody@example.com"
    ]
    by = {row["email"]: row for row in rows}
    assert by[FINISHER] == {"email": FINISHER, "sent": False, "reason": "dry run: would send"}
    assert "Certificate of Completion first" in by[STILL_STUDYING]["reason"]
    assert "already hold" in by[ALREADY_VERIFIED]["reason"]
    assert by["nobody@example.com"]["reason"] == "no learner with this email"
    assert not any(row["sent"] for row in rows)
    assert outbox == []


def test_the_invitation_reaches_finishers_only_from_him_with_him_on_cc(outbox):
    _tier(True)
    r = _post([FINISHER, STILL_STUDYING, ALREADY_VERIFIED], dry_run=False)
    assert r.status_code == 200, r.text
    by = {row["email"]: row for row in r.json()["results"]}
    assert by[FINISHER] == {"email": FINISHER, "sent": True, "reason": ""}
    assert by[STILL_STUDYING]["sent"] is False
    assert by[ALREADY_VERIFIED]["sent"] is False

    assert len(outbox) == 1
    mail = outbox[0]
    settings = get_settings()
    assert mail["to"] == [FINISHER]
    assert mail["cc"] == [settings.ADMIN_NOTIFY_EMAIL]
    assert "bcc" not in mail
    assert mail["from"] == f'"{settings.INSTRUCTOR_NAME}" <bassam@proreadyengineer.com>'
    assert mail["subject"] == (
        "Your Certificate of Verified Competency examination is open — "
        "Micro Gas Turbine Design"
    )
    html = mail["html"]
    assert "Dear Ada," in html
    assert "Its examination is now open" in html
    # The facts the completion email and the course page publish.
    assert "$300 USD" in html and "23 analysis-level questions" in html
    assert "Pass mark 80%" in html and "2 attempts" in html
    assert "60 minutes, live and one-on-one" in html
    assert "one complimentary re-examination" in html
    # The button opens the examination card on the course page.
    assert f'href="{BOOKING_URL}"' in html and "Book my examination" in html
    assert BOOKING_URL in mail["text"]
    assert "Request my examination" not in html
    assert settings.INSTRUCTOR_NAME in html and settings.INSTRUCTOR_TITLE in html

    # Recorded in the comms log against the course.
    db = SessionLocal()
    row = db.query(EmailLog).filter(
        EmailLog.recipient == FINISHER, EmailLog.template == "examined_invitation"
    ).one()
    assert row.ok and row.scope_kind == "product" and row.scope_code == PRODUCT
    db.close()
