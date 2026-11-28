"""The instructor can award the written examination (2026-11-27).

When a candidate's paper is lost to a fault on the site's side, the
instructor records the written examination as passed from the admin panel,
with a reason. The rest of the journey runs as after a graded pass: the
candidate is emailed and can book the oral examination. No score is
invented and no attempt is used.
"""
from __future__ import annotations

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AdvancedCertification, EmailLog, Learner  # noqa: E402

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
EMAIL = "pass.awarded@example.com"
EXAM = f"/api/academy/advanced/{PRODUCT}/exam"
STATE: dict = {}


def _award(client, reason: str = "Paper lost in the browser; nothing reached the site", headers=ADMIN):
    return client.post(
        f"/api/admin/academy/certification/advanced/{STATE['row_id']}/award-pass",
        json={"reason": reason}, headers=headers,
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        r = c.patch(f"/api/admin/academy/products/{PRODUCT}",
                    json={"advanced_cert_enabled": True, "advanced_cert_price_cents": 30000},
                    headers=ADMIN)
        assert r.status_code == 200
        r = c.post("/api/admin/academy/grant",
                   json={"email": EMAIL, "product_code": PRODUCT, "full_name": "Pass Awarded",
                         "send_email_invite": False}, headers=ADMIN)
        assert r.status_code == 200
        db = SessionLocal()
        learner = db.query(Learner).filter(Learner.email == EMAIL).one()
        from app.learner_auth import issue_login_token

        raw = issue_login_token(db, learner)
        db.close()
        assert c.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
        me = c.get("/api/academy/me").json()
        c.post("/api/academy/accept-terms", json={"version": me["terms_version"]})
        r = c.post("/api/admin/academy/certification/comp",
                   json={"email": EMAIL, "product_code": PRODUCT, "send_email": False}, headers=ADMIN)
        assert r.status_code == 200, r.text
        STATE["row_id"] = r.json()["id"]
        yield c


def _candidate(client) -> dict:
    rows = client.get(f"/api/admin/academy/certification/{PRODUCT}", headers=ADMIN).json()["candidates"]
    return next(r for r in rows if r["id"] == STATE["row_id"])


def _mail(template: str) -> int:
    db = SessionLocal()
    try:
        return db.query(EmailLog).filter(EmailLog.template == template, EmailLog.recipient == EMAIL).count()
    finally:
        db.close()


def test_only_the_admin_can_award_and_a_reason_is_required(client):
    exam = client.get(EXAM).json()
    codes = [i["code"] for i in exam["items"]]
    STATE["codes"] = codes
    assert client.post(f"{EXAM}/draft", json={"responses": {codes[0]: "A"}}).status_code == 200
    assert _award(client, headers={}).status_code == 401
    r = _award(client, reason="  ")
    assert r.status_code == 409 and "why" in r.json()["detail"]
    assert _candidate(client)["status"] == "purchased", "a refused award changes nothing"


def test_the_award_passes_the_written_exam_without_inventing_a_score(client):
    r = _award(client)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "exam_passed" and c["exam_passed_at"]
    assert c["exam_attempts"] == 0 and c["exam_best_pct"] == 0, "no attempt used, no score made up"
    assert c["exam_paper"] is None, "the open paper is closed"
    entry = c["exam_log"][0]
    assert entry["event"] == "pass_awarded" and entry["by"].startswith("admin:")
    assert entry["reason"].startswith("Paper lost in the browser")
    assert entry["paper_closed"] is True and entry["answers_set_aside"] == 1
    assert c["exam_pass_awarded"]["reason"] == entry["reason"]


def test_the_candidate_is_emailed_and_can_book_the_oral_exam(client):
    assert _mail("advanced_exam_pass_awarded") == 1
    db = SessionLocal()
    try:
        sent = db.query(EmailLog).filter(
            EmailLog.template == "advanced_exam_pass_awarded", EmailLog.recipient == EMAIL).one()
        assert sent.subject.startswith("Written examination passed")
    finally:
        db.close()
    state = client.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["status"] == "exam_passed"
    assert state["can_propose"] is True and state["booking"] in ("calendar", "propose")
    assert state["paper"] is None


def test_a_hand_in_from_the_old_paper_is_refused_and_recorded(client):
    r = client.post(EXAM, json={"responses": {STATE["codes"][0]: "A"}})
    assert r.status_code == 409
    c = _candidate(client)
    assert c["exam_attempts"] == 0 and c["status"] == "exam_passed"
    assert c["exam_log"][0]["event"] == "hand_in_refused"
    assert client.get(EXAM).status_code == 409, "no new paper is drawn after the award"


def test_an_award_is_not_repeated(client):
    r = _award(client)
    assert r.status_code == 409
    assert _mail("advanced_exam_pass_awarded") == 1


def test_a_candidate_whose_attempts_are_used_can_be_awarded(client):
    db = SessionLocal()
    row = db.get(AdvancedCertification, STATE["row_id"])
    row.status = "exam_failed"
    row.exam_attempts = 2
    row.exam_best_pct = 76.0
    db.commit()
    db.close()
    r = _award(client, reason="Second paper lost to a site fault")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "exam_passed"
    assert c["exam_attempts"] == 2 and c["exam_best_pct"] == 76.0, "the real record is kept"
    assert "paper_closed" not in c["exam_log"][0], "there was no open paper to close"
