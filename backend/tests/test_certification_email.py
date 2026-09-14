"""The certificate email — the instructor's congratulations.

What the owner asked for (2026-09-14): when a learner finishes the course
requirements, the auto-issued certificate goes out as a congratulations from
him, with him on cc (visible, not bcc), and the same email tells the learner
about the paid Certificate of Verified Competency — with the facts the course
page publishes and a link that opens the booking card on their course page.

Captured at the Resend seam (emailer._resend_post) on the shared SQLite DB.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import certificates as certs  # noqa: E402
from app import emailer as E  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AssetBlob, Certificate, Learner, Lesson, Module, Product, QuizItem  # noqa: E402

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
BOOKING_URL = f"https://proreadyengineer.com/learn/{PRODUCT}?advanced=start"


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-cert-1"}


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1]
    )
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


FINISHERS = ("first.finisher@example.com", "second.finisher@example.com")


@pytest.fixture(scope="module", autouse=True)
def leave_the_shared_db_as_found():
    """The suite shares one SQLite file. test_certification.py counts the
    completion certificates on this product and expects the examined tier
    switched off at its start, so this module removes the certificates it
    issued and restores the flag when it is done."""
    db = SessionLocal()
    product = db.get(Product, PRODUCT)
    was_enabled = product.advanced_cert_enabled
    db.close()
    yield
    db = SessionLocal()
    learner_ids = [
        l.id for l in db.query(Learner).filter(Learner.email.in_(FINISHERS)).all()
    ]
    for cert in db.query(Certificate).filter(Certificate.learner_id.in_(learner_ids)).all():
        for key in (cert.pdf_key, cert.preview_key):
            if key:
                db.query(AssetBlob).filter(AssetBlob.key == key).delete()
        db.delete(cert)
    product = db.get(Product, PRODUCT)
    product.advanced_cert_enabled = was_enabled
    db.commit()
    db.close()


def _set_examined_tier(enabled: bool) -> None:
    db = SessionLocal()
    product = db.get(Product, PRODUCT)
    product.advanced_cert_enabled = enabled
    product.advanced_cert_price_cents = 30000
    db.commit()
    db.close()


def _instant_lessons() -> None:
    db = SessionLocal()
    for lesson in db.query(Lesson).all():
        lesson.duration_s = 0
    db.commit()
    db.close()


def _correct_responses(module_code: str, item_set: str) -> tuple[int, dict]:
    db = SessionLocal()
    module = db.query(Module).filter(Module.code == module_code).one()
    items = (
        db.query(QuizItem)
        .filter(QuizItem.module_id == module.id, QuizItem.item_set == item_set)
        .all()
    )
    responses = {}
    for item in items:
        if item.kind == "mcq":
            responses[item.code] = item.answer.get("key")
        elif item.kind == "numeric":
            responses[item.code] = item.answer.get("value")
        else:
            responses[item.code] = "A written answer for rubric review."
    mid = module.id
    db.close()
    return mid, responses


def _complete_course(client: TestClient, email: str, full_name: str) -> str:
    """Enrol, sign in with a name, finish every lesson and pass every set.
    Returns the completion certificate code (issued on the last requirement)."""
    r = client.post(
        "/api/admin/academy/grant",
        json={"email": email, "product_code": PRODUCT, "full_name": full_name,
              "send_email_invite": False},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == email).one()
    from app.learner_auth import issue_login_token

    raw = issue_login_token(db, learner)
    db.close()
    assert client.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
    me = client.get("/api/academy/me").json()
    client.post("/api/academy/accept-terms", json={"version": me["terms_version"]})

    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    for module in course["modules"]:
        for lesson in module["lessons"]:
            r = client.post(f"/api/academy/lesson/{lesson['id']}/progress",
                            json={"position_s": 1, "watched_delta_s": 5})
            assert r.status_code == 200, r.text
        if module["code"] == "GT-05":
            for item_set in ("formative", "summative"):
                mid, responses = _correct_responses("GT-05", item_set)
                r = client.post(f"/api/academy/quiz/{mid}/{item_set}", json={"responses": responses})
                assert r.status_code == 200 and r.json()["passed"] is True
    body = client.get(f"/api/academy/certification/{PRODUCT}").json()
    cert = body["completion"]["certificate"]
    assert cert is not None, "auto-issued on the last heartbeat/quiz"
    return cert["code"]


def _certificate_mail(sent: list[dict]) -> dict:
    mails = [m for m in sent if "Certificate of Completion" in m["subject"]]
    assert len(mails) == 1, [m["subject"] for m in sent]
    return mails[0]


# -----------------------------------------------------------------------------

def test_completion_email_is_from_bassam_with_him_on_cc(outbox):
    _instant_lessons()
    _set_examined_tier(False)
    with TestClient(app, base_url="https://testserver") as c:
        code = _complete_course(c, "first.finisher@example.com", "Ada Byron")

    mail = _certificate_mail(outbox)
    settings = get_settings()
    assert mail["to"] == ["first.finisher@example.com"]
    # Visible copy to the owner — cc, not bcc.
    assert mail["cc"] == [settings.ADMIN_NOTIFY_EMAIL]
    assert "bcc" not in mail
    # Sent under his name from his own mailbox on the verified domain — not
    # info@, which mail clients relabel with the saved "Support" contact.
    assert mail["from"] == f'"{settings.INSTRUCTOR_NAME}" <bassam@proreadyengineer.com>'
    assert mail["subject"] == (
        "Congratulations, Ada — your Certificate of Completion for Micro Gas Turbine Design"
    )
    html = mail["html"]
    assert "Dear Ada," in html
    assert "Congratulations, Ada" in html
    assert code in html and f"https://proreadyengineer.com/verify/{code}" in html
    assert settings.INSTRUCTOR_NAME in html and settings.INSTRUCTOR_TITLE in html
    # The PDF rides along.
    assert mail["attachments"][0]["filename"].endswith(f"{code}.pdf")
    assert base64.b64decode(mail["attachments"][0]["content"])[:5] == b"%PDF-"
    # Examined tier not open on this course yet: the learner still hears
    # about it, with a request link — never a booking link to a dead end.
    assert "Certificate of Verified Competency" in html
    assert "$300 USD" in html and "60 minutes, live and one-on-one" in html
    assert "Book my examination" not in html
    assert "advanced=start" not in html
    assert "Request my examination" in html
    assert 'href="mailto:info@proreadyengineer.com?subject=Verified%20Competency%20examination' in html
    assert "reply to this email" in html


def test_completion_email_invites_the_examined_tier_when_offered(outbox):
    _instant_lessons()
    _set_examined_tier(True)
    with TestClient(app, base_url="https://testserver") as c:
        code = _complete_course(c, "second.finisher@example.com", "Grace Hopper")

    mail = _certificate_mail(outbox)
    html = mail["html"]
    assert code in html
    # The second option, with the facts the course page publishes.
    assert "Certificate of Verified Competency" in html
    assert "$300 USD" in html
    assert "23 analysis-level questions" in html
    assert "Pass mark 80%" in html and "2 attempts" in html
    assert "60 minutes, live and one-on-one" in html
    assert "one complimentary re-examination" in html
    assert "pays for the examination, not the outcome" in html
    # …and the button that opens the booking card on the course page.
    assert f'href="{BOOKING_URL}"' in html
    assert "Book my examination" in html
    # The plain-text part keeps the link actionable.
    assert BOOKING_URL in mail["text"]
    # No half-measures: the course-page link and the sign-off are there too.
    assert f"https://proreadyengineer.com/learn/{PRODUCT}\"" in html
    assert get_settings().INSTRUCTOR_NAME in html


def test_certificate_counts_taught_modules_only():
    """MGT has seven taught modules plus a gate-exempt Q&A handout. The
    specimen the owner approved says 7 MODULES; an issued certificate said 8."""
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "second.finisher@example.com").one()
    product = db.get(Product, PRODUCT)
    cert = certs.get_certificate(db, learner, PRODUCT, "completion")
    total = db.query(Module).filter(Module.product_code == PRODUCT).count()
    exempt = db.query(Module).filter(Module.product_code == PRODUCT, Module.gate_exempt.is_(True)).count()
    assert exempt >= 1, "the fixture course needs a support module for this test to mean anything"
    spec = certs.build_spec(db, cert, product)
    assert spec.module_count == total - exempt
    assert len(certs.taught_modules(db, product)) == total - exempt
    db.close()


def test_no_invitation_once_the_verified_certificate_is_held():
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "second.finisher@example.com").one()
    product = db.get(Product, PRODUCT)
    assert certs.examined_tier_offer(db, learner, product) is not None
    db.add(Certificate(
        learner_id=learner.id, product_code=PRODUCT, code="PRE-V-TEST-HELD",
        learner_name=learner.full_name, tier="verified", status="issued",
        course_title=product.title, issued_at=datetime.now(timezone.utc),
    ))
    db.commit()
    try:
        assert certs.examined_tier_offer(db, learner, product) is None
    finally:
        from app.progress_guard import allow_progress_loss

        with allow_progress_loss("test fixture: remove synthetic verified certificate"):
            db.query(Certificate).filter(Certificate.code == "PRE-V-TEST-HELD").delete()
            db.commit()
        db.close()


def test_verified_tier_email_has_no_upsell_and_is_signed_by_him():
    html = E.certificate_issued_html(
        "Grace Hopper", "Micro Gas Turbine Design", "verified", "PRE-V-AAAA-BBBB",
        "https://proreadyengineer.com/verify/PRE-V-AAAA-BBBB",
        f"https://proreadyengineer.com/learn/{PRODUCT}",
        instructor_name="Dr. Bassam Abdelnabi",
        instructor_credentials="Ph.D., Aerospace Engineering",
        instructor_title="Principal Consultant & Instructor, ProReadyEngineer LLC",
        mastery_threshold_pct=80.0,
        offer=None,
    )
    assert "Dear Grace," in html
    assert "examined live, one-on-one" in html and "signed by me" in html
    assert "Book my examination" not in html
    assert "Dr. Bassam Abdelnabi" in html


def test_principles_the_certificate_cannot_carry_are_refused():
    """Two columns above a fixed signature row: ten two-line items at the
    smallest type is the limit. Over that, the save is refused with the
    reason, not silently trimmed or printed overlapping."""
    with TestClient(app, base_url="https://testserver") as c:
        url = f"/api/admin/academy/products/{PRODUCT}"
        before = c.get(f"/api/admin/academy/certification/{PRODUCT}", headers=ADMIN).json()["product"]["certificate_competencies"]
        r = c.patch(url, json={"certificate_competencies": [f"Principle {i}" for i in range(11)]}, headers=ADMIN)
        assert r.status_code == 422 and "at most 10" in r.json()["detail"]
        r = c.patch(url, json={"certificate_competencies": ["ok", "x" * 151]}, headers=ADMIN)
        assert r.status_code == 422 and "item 2 is 151 characters" in r.json()["detail"]
        r = c.patch(url, json={"certificate_competencies": [f"  Principle   {i} " for i in range(10)]}, headers=ADMIN)
        assert r.status_code == 200
        after = c.get(f"/api/admin/academy/certification/{PRODUCT}", headers=ADMIN).json()["product"]["certificate_competencies"]
        assert after == [f"Principle {i}" for i in range(10)]
        assert c.patch(url, json={"certificate_competencies": before}, headers=ADMIN).status_code == 200


def test_long_principles_step_the_type_down_but_never_reach_the_signature_row():
    """Ten items at the 150-character cap must render clear of the bottom row."""
    import fitz

    from app.certificate_render import CertificateSpec, render_certificate

    items = [("Principle %d: " % i + "word " * 40)[:150].rstrip() for i in range(10)]
    pdf = render_certificate(CertificateSpec(
        tier="verified", learner_name="Fit Test", course_title="Fit Course", course_descriptor="x",
        credential_id="PRE-V-0000-0001", verify_url="https://proreadyengineer.com/verify/PRE-V-0000-0001",
        issued_on=date.today(), signature_fingerprint="0000", competencies=items,
        exam_date=date.today(), sample=True,
    ))
    page = fitz.open(stream=pdf, filetype="pdf")[0]
    words = page.get_text("words")
    verify_top = min(w[1] for w in words if w[4] == "VERIFY")
    lowest_principle = max(w[3] for w in words if w[4] == "word")
    assert lowest_principle < verify_top


def test_first_name_and_sender_helpers():
    assert E.first_name("Ada Lovelace") == "Ada"
    assert E.first_name("Eng. Ahmed Ali") == "Ahmed"
    assert E.first_name("  ") == ""
    assert E.sender_as("Dr. Bassam Abdelnabi") == '"Dr. Bassam Abdelnabi" <info@proreadyengineer.com>'
    assert E.sender_as("Dr. Bassam Abdelnabi", mailbox="bassam") == '"Dr. Bassam Abdelnabi" <bassam@proreadyengineer.com>'
    assert E.sender_as("") == get_settings().EMAIL_FROM
