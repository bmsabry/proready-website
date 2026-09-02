"""Certification tiers — completion rule, auto-issue, signing, verification,
and the instructor-examined state machine end to end.

Runs against the real routers on a throwaway SQLite file (see conftest).
"""
from __future__ import annotations

import base64
import io
from datetime import date, datetime, timedelta, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AdvancedCertification,
    AssetBlob,
    Certificate,
    Enrollment,
    Learner,
    Lesson,
    Module,
    Order,
    QuizItem,
)

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
EMAIL = "cert.candidate@example.com"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(scope="module")
def anon():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _sign_in(client, email: str, full_name: str = "") -> None:
    r = client.post(
        "/api/admin/academy/grant",
        json={"email": email, "product_code": PRODUCT, "full_name": full_name,
              "send_email_invite": False},
        headers=ADMIN,
    )
    assert r.status_code == 200
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == email).one()
    from app.learner_auth import issue_login_token

    raw = issue_login_token(db, learner)
    db.close()
    assert client.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
    # Accept the click-wrap so protected reads work.
    me = client.get("/api/academy/me").json()
    client.post("/api/academy/accept-terms", json={"version": me["terms_version"]})


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


def _make_all_lessons_instant() -> None:
    """Zero durations so every lesson completes on first open — the test is
    about the completion RULE, not about watching 28 hours of video."""
    db = SessionLocal()
    for lesson in db.query(Lesson).all():
        lesson.duration_s = 0
    db.commit()
    db.close()


def _signature_png() -> bytes:
    from PIL import Image

    im = Image.new("RGBA", (300, 90), (0, 0, 0, 0))
    for x in range(20, 280):
        for y in range(40, 46):
            im.putpixel((x, y), (12, 23, 42, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Completion tier
# -----------------------------------------------------------------------------

def test_setup_learner(client):
    _make_all_lessons_instant()
    _sign_in(client, EMAIL)  # deliberately no name yet


def test_status_itemises_every_requirement(client):
    r = client.get(f"/api/academy/certification/{PRODUCT}")
    assert r.status_code == 200
    body = r.json()
    comp = body["completion"]
    assert comp["complete"] is False
    assert comp["lessons_total"] > 0 and comp["lessons_done"] == 0
    # GT-05 carries formative + summative; nothing else has items yet.
    assert comp["sets_total"] == 2
    assert [m["code"] for m in comp["modules"]][:2] == ["GT-03", "GT-05"]
    assert comp["certificate"] is None
    assert body["advanced"]["offered"] is False  # not switched on yet
    assert body["advanced"]["state"] is None


def test_passing_every_quiz_is_not_enough_without_the_lessons(client):
    """The owner's rule: all material AND all quizzes."""
    # Open GT-03 lessons (needed to unlock GT-05's quiz at all).
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    for lesson in course["modules"][0]["lessons"]:
        client.post(f"/api/academy/lesson/{lesson['id']}/progress",
                    json={"position_s": 1, "watched_delta_s": 5})
    for item_set in ("formative", "summative"):
        mid, responses = _correct_responses("GT-05", item_set)
        r = client.post(f"/api/academy/quiz/{mid}/{item_set}", json={"responses": responses})
        assert r.status_code == 200 and r.json()["passed"] is True
    comp = client.get(f"/api/academy/certification/{PRODUCT}").json()["completion"]
    assert comp["sets_passed"] == 2
    assert comp["complete"] is False, "lessons still outstanding"
    assert client.post(f"/api/academy/certificate/{PRODUCT}").status_code == 409


def test_finishing_the_material_without_a_name_holds_the_certificate(client):
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    for module in course["modules"]:
        for lesson in module["lessons"]:
            r = client.post(f"/api/academy/lesson/{lesson['id']}/progress",
                            json={"position_s": 1, "watched_delta_s": 5})
            assert r.status_code == 200, r.text
    body = client.get(f"/api/academy/certification/{PRODUCT}").json()
    assert body["completion"]["complete"] is True
    assert body["completion"]["awaiting_name"] is True
    assert body["completion"]["certificate"] is None
    assert client.post(f"/api/academy/certificate/{PRODUCT}").status_code == 428


def test_setting_the_name_issues_renders_signs_and_stores(client, anon):
    r = client.post("/api/academy/profile/name", json={"full_name": "  Ada   Lovelace "})
    assert r.status_code == 200
    assert r.json()["full_name"] == "Ada Lovelace"
    assert len(r.json()["issued"]) == 1

    body = client.get(f"/api/academy/certification/{PRODUCT}").json()
    cert = body["completion"]["certificate"]
    assert cert is not None
    assert cert["tier"] == "completion"
    assert cert["code"].startswith("PRE-C-")
    assert cert["learner_name"] == "Ada Lovelace"
    assert cert["signature_fingerprint"].count("-") == 3
    assert body["name_locked"] is True
    assert "certId=" in cert["linkedin"]["add_to_profile"]
    assert cert["code"] in cert["linkedin"]["add_to_profile"]
    assert "share-offsite" in cert["linkedin"]["share"]

    # Public verification: valid, signed, files served.
    v = anon.get(f"/api/academy/verify/{cert['code']}").json()
    assert v["valid"] is True and v["signature_valid"] is True
    assert v["learner_name"] == "Ada Lovelace" and v["tier"] == "completion"
    assert v["pdf_sha256"] and v["public_key_b64"]
    pdf = anon.get(f"/api/academy/verify/{cert['code']}/certificate.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"
    import hashlib

    assert hashlib.sha256(pdf.content).hexdigest() == v["pdf_sha256"]
    png = anon.get(f"/api/academy/verify/{cert['code']}/certificate.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    # Lower-case codes verify too.
    assert anon.get(f"/api/academy/verify/{cert['code'].lower()}").json()["valid"] is True

    # The name is now fixed.
    assert client.post("/api/academy/profile/name", json={"full_name": "Someone Else"}).status_code == 409


def test_issue_is_idempotent(client):
    a = client.get(f"/api/academy/certification/{PRODUCT}").json()["completion"]["certificate"]
    b = client.post(f"/api/academy/certificate/{PRODUCT}").json()
    assert a["code"] == b["code"]
    db = SessionLocal()
    n = db.query(Certificate).filter(Certificate.product_code == PRODUCT, Certificate.tier == "completion").count()
    db.close()
    assert n == 1


def test_tampering_with_the_stored_facts_breaks_the_signature(client, anon):
    code = client.get(f"/api/academy/certification/{PRODUCT}").json()["completion"]["certificate"]["code"]
    db = SessionLocal()
    cert = db.query(Certificate).filter(Certificate.code == code).one()
    original = cert.learner_name
    cert.learner_name = "Somebody Else"
    db.commit()
    v = anon.get(f"/api/academy/verify/{code}").json()
    assert v["signature_valid"] is False and v["valid"] is False
    cert.learner_name = original
    db.commit()
    db.close()
    assert anon.get(f"/api/academy/verify/{code}").json()["valid"] is True


def test_revoke_and_reissue(client, anon):
    code = client.get(f"/api/academy/certification/{PRODUCT}").json()["completion"]["certificate"]["code"]
    r = client.post(f"/api/admin/academy/certification/certificates/{code}/revoke",
                    json={"reason": "issued in error"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert anon.get(f"/api/academy/verify/{code}").json()["valid"] is False
    assert anon.get(f"/api/academy/verify/{code}/certificate.pdf").status_code == 410

    r = client.post(f"/api/admin/academy/certification/certificates/{code}/reissue",
                    json={"learner_name": "Ada King-Lovelace", "resend_email": False}, headers=ADMIN)
    assert r.status_code == 200
    v = anon.get(f"/api/academy/verify/{code}").json()
    assert v["valid"] is True and v["learner_name"] == "Ada King-Lovelace"
    assert v["signature_valid"] is True


def test_unknown_code_is_invalid(anon):
    assert anon.get("/api/academy/verify/PRE-C-NOPE-NOPE").json()["valid"] is False
    assert anon.get("/api/academy/verify/PRE-C-NOPE-NOPE/certificate.pdf").status_code == 404


# -----------------------------------------------------------------------------
# Examined tier
# -----------------------------------------------------------------------------

def test_advanced_bank_seeded_and_answer_key_hidden(client):
    db = SessionLocal()
    n = db.query(QuizItem).filter(QuizItem.product_code == PRODUCT, QuizItem.item_set == "advanced").count()
    db.close()
    assert n == 23


def test_advanced_is_off_until_switched_on(client):
    assert client.post(f"/api/academy/advanced/{PRODUCT}/checkout").status_code == 409
    r = client.patch(f"/api/admin/academy/products/{PRODUCT}",
                     json={"advanced_cert_enabled": True, "advanced_cert_price_cents": 30000},
                     headers=ADMIN)
    assert r.status_code == 200
    body = client.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]
    assert body["offered"] is True and body["price_cents"] == 30000
    assert body["can_purchase"] is True
    assert len(body["competencies"]) == 7


def test_comp_candidate_and_written_exam(client):
    r = client.post("/api/admin/academy/certification/comp",
                    json={"email": EMAIL, "product_code": PRODUCT, "send_email": False}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "purchased"
    # A second open journey is refused.
    assert client.post("/api/admin/academy/certification/comp",
                       json={"email": EMAIL, "product_code": PRODUCT}, headers=ADMIN).status_code == 409

    exam = client.get(f"/api/academy/advanced/{PRODUCT}/exam")
    assert exam.status_code == 200
    items = exam.json()["items"]
    assert len(items) == 23
    for item in items:
        assert "answer" not in item and "explanation" not in item

    # Attempt 1: blanket guess → fail.
    r = client.post(f"/api/academy/advanced/{PRODUCT}/exam",
                    json={"responses": {i["code"]: "A" for i in items}})
    assert r.status_code == 200
    assert r.json()["passed"] is False and r.json()["attempts_used"] == 1
    assert all("explanation" not in f for f in r.json()["feedback"])
    # Attempt 2: another guess → attempts exhausted.
    r = client.post(f"/api/academy/advanced/{PRODUCT}/exam",
                    json={"responses": {i["code"]: "D" for i in items}})
    assert r.json()["status"] == "exam_failed"
    assert client.get(f"/api/academy/advanced/{PRODUCT}/exam").status_code == 409

    # Admin gives the exam back.
    row_id = client.get(f"/api/admin/academy/certification/{PRODUCT}", headers=ADMIN).json()["candidates"][0]["id"]
    assert client.post(f"/api/admin/academy/certification/advanced/{row_id}/reset-exam", headers=ADMIN).status_code == 200

    # Attempt with the real key → pass.
    db = SessionLocal()
    key = {}
    for item in db.query(QuizItem).filter(QuizItem.product_code == PRODUCT, QuizItem.item_set == "advanced").all():
        key[item.code] = item.answer.get("key") if item.kind == "mcq" else item.answer.get("value")
    db.close()
    r = client.post(f"/api/academy/advanced/{PRODUCT}/exam", json={"responses": key})
    assert r.status_code == 200 and r.json()["passed"] is True and r.json()["score_pct"] == 100.0
    state = client.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["status"] == "exam_passed" and state["can_propose"] is True


def test_propose_schedule_retake_and_pass(client, anon):
    # Slots must be in the future.
    r = client.post(f"/api/academy/advanced/{PRODUCT}/slots",
                    json={"slots": [(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()],
                          "timezone": "Europe/Berlin"})
    assert r.status_code == 422
    future = [(datetime.now(timezone.utc) + timedelta(days=d, hours=3)).isoformat() for d in (2, 3, 4)]
    r = client.post(f"/api/academy/advanced/{PRODUCT}/slots",
                    json={"slots": future, "timezone": "Europe/Berlin", "note": "mornings are best"})
    assert r.status_code == 200 and r.json()["state"]["status"] == "slots_proposed"

    overview = client.get(f"/api/admin/academy/certification/{PRODUCT}", headers=ADMIN).json()
    cand = overview["candidates"][0]
    assert cand["status"] == "slots_proposed" and len(cand["proposed_slots"]) == 3
    assert any("Europe/Berlin" in line for line in cand["proposed_slots"][0]["lines"])
    assert overview["counts"]["awaiting_action"] == 1

    # Outcome before scheduling is refused.
    assert client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/outcome",
                       json={"result": "pass"}, headers=ADMIN).status_code == 409

    r = client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/schedule",
                    json={"at": future[0], "meeting_url": "https://zoom.us/j/123"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    state = client.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["meeting_url"] == "https://zoom.us/j/123" and state["scheduled_lines"]

    # 'Not yet' → complimentary re-examination after a study period.
    r = client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/outcome",
                    json={"result": "retake", "note": "weak on surge margin"}, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["status"] == "retake_pending" and r.json()["interview_no"] == 2
    state = client.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["can_propose"] is False and "on or after" in state["propose_blocked_reason"]

    # Study period over (admin re-records with today's date) → propose again.
    db = SessionLocal()
    row = db.get(AdvancedCertification, cand["id"])
    row.retake_after = date.today()
    db.commit()
    db.close()
    r = client.post(f"/api/academy/advanced/{PRODUCT}/slots", json={"slots": future[1:], "timezone": "UTC"})
    assert r.status_code == 200
    r = client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/schedule",
                    json={"at": future[1], "meeting_url": "https://zoom.us/j/456"}, headers=ADMIN)
    assert r.status_code == 200

    # A second 'retake' is not available.
    assert client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/outcome",
                       json={"result": "retake"}, headers=ADMIN).status_code == 409

    # No signature uploaded → a verified certificate is refused, state unchanged.
    db = SessionLocal()
    db.query(AssetBlob).filter(AssetBlob.key == "instructor-signature.png").delete()
    db.commit()
    db.close()
    r = client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/outcome",
                    json={"result": "pass"}, headers=ADMIN)
    assert r.status_code == 409 and "signature" in r.json()["detail"].lower()
    db = SessionLocal()
    assert db.get(AdvancedCertification, cand["id"]).status == "scheduled"
    assert db.query(Certificate).filter(Certificate.tier == "verified").count() == 0
    db.close()

    r = client.post("/api/admin/academy/certification/signature",
                    json={"png_b64": base64.b64encode(_signature_png()).decode()}, headers=ADMIN)
    assert r.status_code == 200
    assert client.get(f"/api/admin/academy/certification/{PRODUCT}", headers=ADMIN).json()["signature_uploaded"] is True

    r = client.post(f"/api/admin/academy/certification/advanced/{cand['id']}/outcome",
                    json={"result": "pass", "note": "excellent on maps and CFD"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "passed"
    vcode = r.json()["certificate"]["code"]
    assert vcode.startswith("PRE-V-")

    body = client.get(f"/api/academy/certification/{PRODUCT}").json()
    assert body["advanced"]["certificate"]["code"] == vcode
    assert body["advanced"]["can_purchase"] is False
    v = anon.get(f"/api/academy/verify/{vcode}").json()
    assert v["valid"] is True and v["tier"] == "verified"
    assert v["exam_date"] == future[1][:10] and v["exam_minutes"] == 60
    assert len(v["competencies"]) == 7 and v["instructor"]
    pdf = anon.get(f"/api/academy/verify/{vcode}/certificate.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    # The private examiner note never reaches the learner-facing shape.
    assert "outcome_note" not in body["advanced"]["state"]


def test_sample_pdf_is_watermarked_specimen(client):
    for tier in ("completion", "verified"):
        r = client.get(f"/api/admin/academy/certification/{PRODUCT}/sample.pdf?tier={tier}", headers=ADMIN)
        assert r.status_code == 200 and r.content[:5] == b"%PDF-"


# -----------------------------------------------------------------------------
# Payment plumbing
# -----------------------------------------------------------------------------

def test_webhook_fulfilment_is_idempotent_and_refund_keeps_the_course(client):
    from app.routes.checkout import _revoke_for_payment, fulfil_advanced_cert

    email2 = "second.candidate@example.com"
    # Enrol + complete for a second learner so they are eligible.
    with TestClient(app, base_url="https://testserver") as c2:
        _make_all_lessons_instant()
        _sign_in(c2, email2, full_name="Grace Hopper")
        course = c2.get(f"/api/academy/course/{PRODUCT}").json()
        for module in course["modules"]:
            for lesson in module["lessons"]:
                c2.post(f"/api/academy/lesson/{lesson['id']}/progress",
                        json={"position_s": 1, "watched_delta_s": 5})
            if module["code"] == "GT-05":
                for item_set in ("formative", "summative"):
                    mid, responses = _correct_responses("GT-05", item_set)
                    c2.post(f"/api/academy/quiz/{mid}/{item_set}", json={"responses": responses})
        body = c2.get(f"/api/academy/certification/{PRODUCT}").json()
        assert body["completion"]["certificate"] is not None, "auto-issued on the last heartbeat/quiz"

    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == email2).one()
    session_obj = {
        "id": "cs_test_adv_1",
        "payment_status": "paid",
        "amount_total": 30000,
        "currency": "usd",
        "payment_intent": "pi_adv_1",
        "customer_details": {"email": email2, "name": "Grace Hopper"},
        "metadata": {"kind": "advanced_cert", "product_code": PRODUCT, "learner_id": str(learner.id)},
    }
    fulfil_advanced_cert(db, session_obj)
    fulfil_advanced_cert(db, session_obj)  # Stripe retries
    rows = db.query(AdvancedCertification).filter(AdvancedCertification.learner_id == learner.id).all()
    assert len(rows) == 1 and rows[0].status == "purchased" and rows[0].amount_cents == 30000
    order = db.query(Order).filter(Order.provider_ref == "cs_test_adv_1").one()
    assert order.kind == "advanced_cert" and order.status == "paid"

    # A refund of the examined tier closes the examination but must NOT
    # touch the course enrollment or the completion certificate.
    _revoke_for_payment(db, "pi_adv_1", "refunded")
    db.expire_all()
    assert db.get(AdvancedCertification, rows[0].id).status == "cancelled"
    enrollment = db.query(Enrollment).filter(
        Enrollment.learner_id == learner.id, Enrollment.product_code == PRODUCT
    ).one()
    assert enrollment.status == "active"
    assert db.query(Certificate).filter(
        Certificate.learner_id == learner.id, Certificate.tier == "completion"
    ).one().status == "issued"
    db.close()
