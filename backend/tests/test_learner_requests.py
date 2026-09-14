"""The three course-dashboard buttons: start over, request completion
marks, request the answer key — and the admin's approve/decline.

Owner's rules (2026-09-14): a reset keeps an earned certificate; the answer
key may be requested any time by a live-cohort registrant, and only after
completion by a self-study learner; nothing is applied until an admin
approves in the panel; a decline sends the learner the instructor's note.
"""
from __future__ import annotations

import base64
from datetime import date

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import emailer as E  # noqa: E402
from app import learner_requests as lr  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AssetBlob,
    Certificate,
    Course,
    Learner,
    LearnerRequest,
    Lesson,
    LessonProgress,
    Module,
    QuizAttempt,
    QuizItem,
    Registration,
)

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
SELF = "self.study@example.com"
COHORT = "cohort.attendee@example.com"
COURSE_CODE = "test-live-cohort-for-requests"


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-req-1"}


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1])
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    return sent


@pytest.fixture(scope="module", autouse=True)
def fixtures_and_cleanup():
    db = SessionLocal()
    for lesson in db.query(Lesson).all():
        lesson.duration_s = 0
    db.add(Course(code=COURSE_CODE, title="Test Live Cohort", start_date=date.today(),
                  day_dates=[], recorded_product_code=PRODUCT))
    db.add(Registration(course_code=COURSE_CODE, full_name="Cohort Attendee", email=COHORT,
                        job_title="Engineer", company="ACME", years_experience="5",
                        location="Cairo", status="paid"))
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    from app.progress_guard import allow_progress_loss

    ids = [l.id for l in db.query(Learner).filter(Learner.email.in_((SELF, COHORT))).all()]
    with allow_progress_loss("test fixture: remove the request-test learners' history"):
        for cert in db.query(Certificate).filter(Certificate.learner_id.in_(ids)).all():
            for key in (cert.pdf_key, cert.preview_key):
                if key:
                    db.query(AssetBlob).filter(AssetBlob.key == key).delete()
            db.delete(cert)
        db.query(LearnerRequest).filter(LearnerRequest.learner_id.in_(ids)).delete()
        db.query(LessonProgress).filter(LessonProgress.learner_id.in_(ids)).delete()
        db.query(QuizAttempt).filter(QuizAttempt.learner_id.in_(ids)).delete()
        db.query(Registration).filter(Registration.course_code == COURSE_CODE).delete()
        db.query(Course).filter(Course.code == COURSE_CODE).delete()
        db.commit()
    db.close()


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _sign_in(client: TestClient, email: str, full_name: str) -> None:
    r = client.post("/api/admin/academy/grant",
                    json={"email": email, "product_code": PRODUCT, "full_name": full_name,
                          "send_email_invite": False}, headers=ADMIN)
    assert r.status_code == 200, r.text
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == email).one()
    from app.learner_auth import issue_login_token

    raw = issue_login_token(db, learner)
    db.close()
    assert client.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
    me = client.get("/api/academy/me").json()
    client.post("/api/academy/accept-terms", json={"version": me["terms_version"]})


def _learner_id(email: str) -> int:
    db = SessionLocal()
    lid = db.query(Learner).filter(Learner.email == email).one().id
    db.close()
    return lid


# -----------------------------------------------------------------------------

def test_dashboard_knows_what_each_learner_may_ask(outbox):
    with _client() as c:
        _sign_in(c, SELF, "Ada Reset")
        s = c.get(f"/api/academy/course/{PRODUCT}").json()["support"]
        assert s["reset_available"] is True
        assert s["completion_request_available"] is True
        assert s["answers_request_available"] is False
        assert "Certificate of Completion" in s["answers_blocked_reason"]
        assert s["pending"] == {}
    with _client() as c:
        _sign_in(c, COHORT, "Cohort Attendee")
        s = c.get(f"/api/academy/course/{PRODUCT}").json()["support"]
        assert s["answers_request_available"] is True, "a paid live-cohort registrant may ask any time"


def test_self_study_cannot_request_answers_before_completion(outbox):
    with _client() as c:
        _sign_in(c, SELF, "Ada Reset")
        r = c.post(f"/api/academy/course/{PRODUCT}/requests", json={"kind": "answers"})
        assert r.status_code == 409 and "Certificate of Completion" in r.json()["detail"]
        # (signing the same learner in from several test clients trips the
        # device-overlap integrity alert — unrelated to this feature)
        assert not [m for m in outbox if "Learner request" in m["subject"]]


def test_completion_request_emails_the_owner_and_waits(outbox):
    with _client() as c:
        _sign_in(c, SELF, "Ada Reset")
        r = c.post(f"/api/academy/course/{PRODUCT}/requests",
                   json={"kind": "completion", "note": "The quiz page froze and my answers were lost."})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"
        assert "completion" in r.json()["support"]["pending"]
        # Twice is refused.
        assert c.post(f"/api/academy/course/{PRODUCT}/requests", json={"kind": "completion"}).status_code == 409
        # Nothing was applied by asking.
        course = c.get(f"/api/academy/course/{PRODUCT}").json()
        assert course["complete"] is False and course["certificate_code"] is None

    mail = [m for m in outbox if "[Learner request]" in m["subject"]]
    assert len(mail) == 1
    assert mail[0]["to"] == [get_settings().ADMIN_NOTIFY_EMAIL]
    assert "asks for completion marks" in mail[0]["subject"]
    html = mail[0]["html"]
    assert "lose their answers" in html
    assert "The quiz page froze" in html
    assert "Self-study access" in html
    assert 'href="https://proreadyengineer.com/admin#academy"' in html


def test_admin_approves_completion_and_the_certificate_issues(outbox):
    with _client() as c:
        r = c.get("/api/admin/academy/requests?status_filter=pending", headers=ADMIN)
        assert r.status_code == 200
        pending = [x for x in r.json()["requests"] if x["learner_email"] == SELF]
        assert len(pending) == 1
        req = pending[0]
        assert req["kind"] == "completion" and req["cohort"] is None
        assert req["progress"]["complete"] is False

        r = c.post(f"/api/admin/academy/requests/{req['id']}/approve", json={"note": "Granted."}, headers=ADMIN)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved" and body["result"].startswith("PRE-C-")
        assert body["decided_by"] == conftest.ADMIN_EMAIL
        # Second approval is refused.
        assert c.post(f"/api/admin/academy/requests/{req['id']}/approve", json={}, headers=ADMIN).status_code == 409

    # The learner's dashboard agrees everywhere: lessons, sets, certificate.
    with _client() as c:
        _sign_in(c, SELF, "Ada Reset")
        course = c.get(f"/api/academy/course/{PRODUCT}").json()
        assert course["complete"] is True
        assert course["percent"] == 100.0
        assert course["certificate_code"].startswith("PRE-C-")
        cert = c.get(f"/api/academy/certification/{PRODUCT}").json()
        assert cert["completion"]["sets_passed"] == cert["completion"]["sets_total"] == 2
        assert cert["completion"]["certificate"]["code"] == course["certificate_code"]
        s = course["support"]
        assert s["completion_request_available"] is False  # holds it now
        assert s["answers_request_available"] is True       # completion unlocks the key

    # Granted attempts are marked as the instructor's act, never a sat quiz.
    db = SessionLocal()
    lid = _learner_id(SELF)
    granted = db.query(QuizAttempt).filter(QuizAttempt.learner_id == lid).all()
    assert granted and all(a.responses.get("_granted", {}).get("request_id") for a in granted)
    assert all(a.auto_total == 0 and a.passed for a in granted)
    db.close()

    # The congratulations email went out under his name with him on cc.
    congrats = [m for m in outbox if m["subject"].startswith("Congratulations, Ada")]
    assert len(congrats) == 1
    assert congrats[0]["cc"] == [get_settings().ADMIN_NOTIFY_EMAIL]
    assert congrats[0]["attachments"][0]["filename"].endswith(".pdf")


def test_start_over_clears_progress_but_keeps_the_certificate(outbox):
    with _client() as c:
        _sign_in(c, SELF, "Ada Reset")
        before = c.get(f"/api/academy/course/{PRODUCT}").json()
        assert before["complete"] is True
        # A stray click does nothing.
        r = c.post(f"/api/academy/course/{PRODUCT}/reset", json={"confirm": ""})
        assert r.status_code == 428
        r = c.post(f"/api/academy/course/{PRODUCT}/reset", json={"confirm": "reset"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["lessons_cleared"] > 0 and out["attempts_cleared"] == 2

        after = c.get(f"/api/academy/course/{PRODUCT}").json()
        assert after["percent"] == 0.0 and after["lessons_completed"] == 0
        assert after["complete"] is False
        assert after["certificate_code"] == before["certificate_code"], "earned; kept"
        cert = c.get(f"/api/academy/certification/{PRODUCT}").json()
        assert cert["completion"]["certificate"]["code"] == before["certificate_code"]
        assert cert["completion"]["lessons_done"] == 0
        # Redoing the course is possible: the first lesson takes a heartbeat again.
        first = after["modules"][0]["lessons"][0]["id"]
        assert c.post(f"/api/academy/lesson/{first}/progress",
                      json={"position_s": 1, "watched_delta_s": 5}).status_code == 200
    db = SessionLocal()
    lid = _learner_id(SELF)
    assert db.query(QuizAttempt).filter(QuizAttempt.learner_id == lid).count() == 0
    assert db.query(Certificate).filter(Certificate.learner_id == lid, Certificate.tier == "completion").count() == 1
    db.close()


def test_cohort_attendee_gets_the_answer_key_pdf(outbox):
    with _client() as c:
        _sign_in(c, COHORT, "Cohort Attendee")
        r = c.post(f"/api/academy/course/{PRODUCT}/requests", json={"kind": "answers", "note": ""})
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]
    admin_mail = [m for m in outbox if "asks for the answer key" in m["subject"]]
    assert len(admin_mail) == 1 and "Live-cohort registrant" in admin_mail[0]["html"]

    with _client() as c:
        r = c.post(f"/api/admin/academy/requests/{req_id}/approve", json={}, headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["result"] == "answer_key_sent"

    key_mail = [m for m in outbox if m["subject"].startswith("Answer key —")]
    assert len(key_mail) == 1 and key_mail[0]["to"] == [COHORT]
    pdf = base64.b64decode(key_mail[0]["attachments"][0]["content"])
    assert pdf[:5] == b"%PDF-"
    import fitz

    text = "".join(page.get_text() for page in fitz.open(stream=pdf, filetype="pdf"))
    db = SessionLocal()
    gt05 = db.query(Module).filter(Module.code == "GT-05").one()
    items = db.query(QuizItem).filter(QuizItem.module_id == gt05.id,
                                      QuizItem.item_set.in_(("formative", "summative"))).all()
    advanced = db.query(QuizItem).filter(QuizItem.item_set == "advanced").all()
    db.close()
    assert items
    # Every item's stem and its answer are in the PDF; the paid exam is not.
    for item in items:
        assert item.stem[:40] in text.replace("\n", " ") or item.stem[:40] in text
    assert "Answer: " in text and "Mastery check" in text and "Module evaluation" in text
    assert "Cohort Attendee" in text and "not for distribution" in text
    for item in advanced[:5]:
        assert item.stem[:60] not in text.replace("\n", " ")


def test_decline_sends_the_learner_the_note(outbox):
    with _client() as c:
        _sign_in(c, COHORT, "Cohort Attendee")
        r = c.post(f"/api/academy/course/{PRODUCT}/requests", json={"kind": "completion"})
        assert r.status_code == 200
        req_id = r.json()["id"]
    with _client() as c:
        r = c.post(f"/api/admin/academy/requests/{req_id}/decline",
                   json={"note": "Please finish Day 2 first, then ask again."}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["status"] == "declined"
    mail = [m for m in outbox if m["subject"].startswith("About your request")]
    assert len(mail) == 1 and mail[0]["to"] == [COHORT]
    assert "was not approved" in mail[0]["html"] and "finish Day 2" in mail[0]["html"]
    # The learner may ask again.
    with _client() as c:
        _sign_in(c, COHORT, "Cohort Attendee")
        assert c.post(f"/api/academy/course/{PRODUCT}/requests", json={"kind": "completion"}).status_code == 200
