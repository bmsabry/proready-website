"""The written examination can no longer vanish without a trace (2026-11-27).

A candidate answered the paper for hours, the answers lived only in his
browser tab, and no hand-in ever reached the site: nothing was graded,
nothing was recorded, and nobody could say what had happened. Now:

  * answers are autosaved on the server and come back on reload;
  * every hand-in that is refused, or fails on the server, is recorded;
  * the instructor sees the open paper and can hand in the saved answers;
  * every result (pass or not) is emailed to both sides;
  * a paper open for a day without a hand-in alerts the instructor and
    reminds the candidate, once.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import advanced_cert as adv  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AdvancedCertification, EmailLog, Learner  # noqa: E402

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
EMAIL = "paper.safety@example.com"
EXAM = f"/api/academy/advanced/{PRODUCT}/exam"
STATE: dict = {}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        r = c.patch(f"/api/admin/academy/products/{PRODUCT}",
                    json={"advanced_cert_enabled": True, "advanced_cert_price_cents": 30000},
                    headers=ADMIN)
        assert r.status_code == 200
        r = c.post("/api/admin/academy/grant",
                   json={"email": EMAIL, "product_code": PRODUCT, "full_name": "Paper Safety",
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


def _events(client) -> list[str]:
    return [e["event"] for e in _candidate(client)["exam_log"]]


def _mail(template: str, to: str) -> int:
    db = SessionLocal()
    try:
        return db.query(EmailLog).filter(EmailLog.template == template, EmailLog.recipient == to).count()
    finally:
        db.close()


def test_answers_are_saved_on_the_server_and_come_back(client):
    exam = client.get(EXAM).json()
    codes = [i["code"] for i in exam["items"]]
    STATE["codes"] = codes
    assert exam["draft"] == {} and exam["opened_at"]
    some = {codes[0]: "A", codes[1]: "B", codes[2]: ""}
    r = client.post(f"{EXAM}/draft", json={"responses": some})
    assert r.status_code == 200 and r.json()["answered"] == 2, "blanks are not answers"

    again = client.get(EXAM).json()
    assert [i["code"] for i in again["items"]] == codes, "a reload serves the same paper"
    assert again["draft"] == {codes[0]: "A", codes[1]: "B"}
    assert again["draft_saved_at"]

    state = client.get(f"/api/academy/certification/{PRODUCT}").json()["advanced"]["state"]
    assert state["paper"]["answered"] == 2 and state["paper"]["questions"] == len(codes)

    c = _candidate(client)
    assert c["exam_paper"]["answered"] == 2 and c["exam_attempts"] == 0
    assert "paper_drawn" in _events(client)


def test_answers_to_another_paper_are_not_saved(client):
    assert client.post(f"{EXAM}/draft", json={"responses": {"NOT-ON-THIS-PAPER": "A"}}).status_code == 409


def test_a_refused_hand_in_leaves_a_record(client):
    r = client.post(EXAM, json={"responses": {"NOT-ON-THIS-PAPER": "A"}})
    assert r.status_code == 409 and "No attempt has been used" in r.json()["detail"]
    last = _candidate(client)["exam_log"][0]
    assert last["event"] == "hand_in_refused" and last["reason"] == "answers are to a different paper"
    assert _candidate(client)["exam_attempts"] == 0


def test_a_hand_in_that_fails_on_the_server_keeps_the_answers(client, monkeypatch):
    codes = STATE["codes"]
    def boom(*a, **k):
        raise RuntimeError("grading broke")
    monkeypatch.setattr(adv, "grade_exam", boom)
    sent = {codes[0]: "C", codes[1]: "B", codes[3]: "D"}
    r = client.post(EXAM, json={"responses": sent})
    assert r.status_code == 500 and "Your answers are saved" in r.json()["detail"]
    c = _candidate(client)
    assert c["exam_attempts"] == 0
    assert c["exam_paper"]["answered"] == 3, "the hand-in's answers were stored before grading"
    assert c["exam_log"][0]["event"] == "hand_in_failed"
    assert client.get(EXAM).json()["draft"] == sent


def test_the_instructor_hands_in_the_saved_answers(client):
    r = client.post(f"/api/admin/academy/certification/advanced/{STATE['row_id']}/hand-in-saved",
                    headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exam_attempts"] == 1 and body["exam_paper"] is None
    assert body["graded"]["passed"] is False
    handed = body["exam_log"][0]
    assert handed["event"] == "handed_in" and handed["by"].startswith("admin:")
    assert handed["answered"] == 3
    # Both sides hear about a result that is not a pass.
    assert _mail("advanced_exam_not_passed", EMAIL) == 1
    assert _mail("advanced_exam_not_passed_admin", get_settings().ADMIN_NOTIFY_EMAIL) >= 1
    # The paper is closed: nothing left to hand in, and the candidate's old tab is refused.
    again = client.post(f"/api/admin/academy/certification/advanced/{STATE['row_id']}/hand-in-saved",
                        headers=ADMIN)
    assert again.status_code == 409
    assert client.post(EXAM, json={"responses": {STATE["codes"][0]: "A"}}).status_code == 409
    assert _candidate(client)["exam_log"][0]["reason"] == "no open paper (already handed in)"


def test_the_candidates_own_hand_in_is_recorded_and_emailed(client):
    exam = client.get(EXAM).json()  # attempt 2 draws a new paper
    assert exam["draft"] == {}
    r = client.post(EXAM, json={"responses": {i["code"]: "A" for i in exam["items"]}})
    assert r.status_code == 200 and r.json()["attempts_used"] == 2
    handed = _candidate(client)["exam_log"][0]
    assert handed["event"] == "handed_in" and handed["by"] == "candidate"
    assert handed["answered"] == len(exam["items"])
    assert _mail("advanced_exam_not_passed", EMAIL) == 2


def test_a_paper_open_for_a_day_alerts_once(client):
    assert client.post(f"/api/admin/academy/certification/advanced/{STATE['row_id']}/reset-exam",
                       headers=ADMIN).status_code == 200
    assert client.get(EXAM).status_code == 200
    db = SessionLocal()
    row = db.get(AdvancedCertification, STATE["row_id"])
    row.exam_opened_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    db.close()
    assert client.post("/api/admin/academy/certification/exam-watch").status_code == 401
    r = client.post("/api/admin/academy/certification/exam-watch", headers=ADMIN)
    assert r.status_code == 200 and STATE["row_id"] in r.json()["rows"]
    assert _mail("exam_paper_open_reminder", EMAIL) == 1
    assert _mail("exam_paper_open_admin", get_settings().ADMIN_NOTIFY_EMAIL) >= 1
    assert "stale_alert" in _events(client)
    again = client.post("/api/admin/academy/certification/exam-watch", headers=ADMIN).json()
    assert STATE["row_id"] not in again["rows"], "one alert per paper"


def test_a_fresh_paper_is_not_announced(client):
    db = SessionLocal()
    row = db.get(AdvancedCertification, STATE["row_id"])
    row.exam_stale_alerted_at = None
    row.exam_opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    db.close()
    r = client.post("/api/admin/academy/certification/exam-watch", headers=ADMIN).json()
    assert STATE["row_id"] not in r["rows"]


def test_a_paper_from_before_opening_times_keeps_its_date(client):
    """A paper drawn before opening times were recorded is dated by the row's
    last change. The alert writes to the row, so that date is kept first."""
    drawn = datetime(2026, 10, 18, 23, 8, 1, tzinfo=timezone.utc)
    db = SessionLocal()
    row = db.get(AdvancedCertification, STATE["row_id"])
    row.exam_opened_at = None
    row.exam_stale_alerted_at = None
    row.updated_at = drawn
    db.commit()
    db.close()
    r = client.post("/api/admin/academy/certification/exam-watch", headers=ADMIN).json()
    assert STATE["row_id"] in r["rows"]
    c = _candidate(client)
    assert c["exam_paper"]["opened_at"].startswith("2026-10-18T23:08:01")
    assert c["exam_log"][0]["event"] == "stale_alert"
    assert c["exam_log"][0]["candidate_reminded"] is False
    assert _mail("exam_paper_open_reminder", EMAIL) == 1, "no reminder when the opening time is unknown"
