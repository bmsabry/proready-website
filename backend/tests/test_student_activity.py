"""Student Activity: visits, the activity log, and the admin report.

Covers what the admin page promises: every sign-in and visit with what was
done during it, lessons completed (matching the certificate rule), the
certificates held, integrity signals and the other suspicious-activity flags
— and that tracking never gets in the way of the learner.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

import conftest  # noqa: F401
from fastapi.testclient import TestClient

from app import activity
from app import activity_report as report
from app import certificates as certs
from app.db import SessionLocal
from app.learner_auth import make_learner_token
from app.main import app
from app.models import (
    Learner,
    LearnerActivity,
    LearnerDevice,
    LearnerVisit,
    LessonProgress,
    LoginToken,
)
from app.routes import sim as sim_routes
from app.routes.compat import hash_password
from app.sim_runtime import SimSession

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "activity-test-course"
EMAIL = "trainee.activity@example.com"


@pytest.fixture(scope="module")
def admin():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _sign_in(email: str, headers: dict | None = None) -> TestClient:
    c = TestClient(app, base_url="https://testserver", headers=headers or {})
    r = c.post("/api/admin/academy/login-link", json={"email": email}, headers=ADMIN)
    assert r.status_code == 200, r.text
    token = r.json()["link"].split("token=")[1]
    assert c.post("/api/academy/auth/verify", json={"token": token}).status_code == 200
    return c


def _learner_id(email: str) -> int:
    db = SessionLocal()
    try:
        return db.query(Learner).filter(Learner.email == email).one().id
    finally:
        db.close()


def _row(admin: TestClient, email: str, **params) -> dict:
    r = admin.get("/api/admin/academy/activity", params={"q": email, **params}, headers=ADMIN)
    assert r.status_code == 200, r.text
    rows = [x for x in r.json()["learners"] if x["email"] == email]
    assert len(rows) == 1
    return rows[0]


def _detail(admin: TestClient, email: str) -> dict:
    r = admin.get(f"/api/admin/academy/activity/{_learner_id(email)}", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def course(admin):
    r = admin.post("/api/admin/academy/products", json={
        "code": PRODUCT, "title": "Activity Test Course", "sequential_gate": False,
        "status": "draft"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    r = admin.post(f"/api/admin/academy/products/{PRODUCT}/modules",
                   json={"code": "M1", "title": "Module One", "position": 1}, headers=ADMIN)
    module_id = r.json()["module_id"]
    lessons = []
    for i in (1, 2):
        r = admin.post(f"/api/admin/academy/modules/{module_id}/lessons", json={
            "code": f"M1-L{i}", "title": f"Lesson {i}", "kind": "lab"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        lessons.append(r.json()["lesson_id"])
    items = [{
        "code": f"Q{i}", "stem": f"Pick A ({i})",
        "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
        "answer": {"key": "A"}, "position": i,
    } for i in range(1, 7)]
    r = admin.post(f"/api/admin/academy/modules/{module_id}/quiz-items",
                   json={"items": items}, headers=ADMIN)
    assert r.status_code == 200, r.text
    r = admin.post("/api/admin/academy/grant", json={
        "email": EMAIL, "product_code": PRODUCT, "full_name": "Test Trainee",
        "send_email_invite": False}, headers=ADMIN)
    assert r.status_code == 200, r.text
    return module_id, lessons


def test_report_needs_admin(course):
    with TestClient(app, base_url="https://testserver") as anon:
        assert anon.get("/api/admin/academy/activity").status_code == 401
        assert anon.get("/api/admin/academy/activity/1").status_code == 401


def test_sign_in_opens_a_visit_and_actions_land_in_it(admin, course):
    module_id, lessons = course
    c = _sign_in(EMAIL)
    assert c.get(f"/api/academy/course/{PRODUCT}").status_code == 200
    assert c.get(f"/api/academy/lesson/{lessons[0]}").status_code == 200
    # A reload inside 30 minutes is not a second "opened".
    assert c.get(f"/api/academy/lesson/{lessons[0]}").status_code == 200
    for _ in range(2):
        r = c.post(f"/api/academy/lesson/{lessons[0]}/progress",
                   json={"position_s": 0, "watched_delta_s": 30})
        assert r.status_code == 200, r.text

    lid = _learner_id(EMAIL)
    db = SessionLocal()
    try:
        visits = db.query(LearnerVisit).filter(LearnerVisit.learner_id == lid).all()
        assert len(visits) == 1 and visits[0].sign_in == "link"
        acts = db.query(LearnerActivity).filter(LearnerActivity.learner_id == lid).all()
        kinds = sorted(a.kind for a in acts)
        assert kinds == ["course_open", "lesson_open", "lesson_time", "sign_in"]
        assert all(a.visit_id == visits[0].id for a in acts)
        spent = next(a for a in acts if a.kind == "lesson_time")
        assert spent.amount == 60  # two 30 s beats on one row
    finally:
        db.close()

    row = _row(admin, EMAIL)
    assert row["visits"] == 1 and row["visits_tracked"] == 1 and row["sign_ins"] == 1
    d = _detail(admin, EMAIL)
    v = d["visits"][0]
    assert v["how"] == "Email-link sign-in" and v["source"] == "tracked"
    labels = [e["label"] for e in v["events"]]
    assert "Signed in with an email link" in labels
    assert "Opened “Lesson 1”" in labels
    assert "Completed “Lesson 1”" in labels  # lab lesson completes on first beat
    assert any(l.startswith("Spent 1 min on “Lesson 1”") for l in labels)


def test_coming_back_after_30_minutes_is_a_new_visit(admin, course):
    module_id, lessons = course
    lid = _learner_id(EMAIL)
    db = SessionLocal()
    try:
        old = datetime.now(timezone.utc) - timedelta(minutes=45)
        for v in db.query(LearnerVisit).filter(LearnerVisit.learner_id == lid):
            v.started_at = old - timedelta(minutes=10)
            v.last_seen_at = old
        for dvc in db.query(LearnerDevice).filter(LearnerDevice.learner_id == lid):
            dvc.last_seen_at = old
        for a in db.query(LearnerActivity).filter(LearnerActivity.learner_id == lid):
            a.at = old - timedelta(minutes=5)
            a.last_at = None
        for p in db.query(LessonProgress).filter(LessonProgress.learner_id == lid):
            p.completed_at = old - timedelta(minutes=5)
            p.updated_at = old - timedelta(minutes=5)
        for t in db.query(LoginToken).filter(LoginToken.learner_id == lid):
            t.created_at = old - timedelta(minutes=5)
            t.used_at = old - timedelta(minutes=5)
        db.commit()
        cookie = db.query(LearnerDevice).filter(LearnerDevice.learner_id == lid).one().device_id
    finally:
        db.close()

    c = TestClient(app, base_url="https://testserver")
    c.cookies.set("learner_session", make_learner_token(lid, EMAIL))
    c.cookies.set("learner_device", cookie)
    assert c.get(f"/api/academy/lesson/{lessons[1]}").status_code == 200

    db = SessionLocal()
    try:
        visits = db.query(LearnerVisit).filter(LearnerVisit.learner_id == lid) \
            .order_by(LearnerVisit.started_at).all()
        assert len(visits) == 2
        assert visits[1].sign_in == ""  # still signed in: a return visit, not a sign-in
    finally:
        db.close()
    row = _row(admin, EMAIL)
    assert row["visits"] == 2 and row["sign_ins"] == 1
    d = _detail(admin, EMAIL)
    assert d["visits"][0]["how"] == "Already signed in"
    assert "Opened “Lesson 2”" in [e["label"] for e in d["visits"][0]["events"]]


def test_progress_matches_the_certificate_rule(admin, course):
    row = _row(admin, EMAIL)
    course_row = next(c for c in row["courses"] if c["code"] == PRODUCT)
    db = SessionLocal()
    try:
        learner = db.get(Learner, _learner_id(EMAIL))
        truth = certs.completion_status(db, learner, PRODUCT)
    finally:
        db.close()
    for k in ("lessons_done", "lessons_total", "sets_passed", "sets_total", "complete"):
        assert course_row[k] == truth[k], k
    d = _detail(admin, EMAIL)
    mod = next(c for c in d["courses"] if c["code"] == PRODUCT)["modules"][0]
    assert [l["done"] for l in mod["lessons"]] == [True, False]
    assert mod["lessons"][0]["completed_at"] is not None


def test_passing_a_set_in_seconds_is_flagged(admin, course):
    module_id, _ = course
    c = _sign_in(EMAIL)
    assert c.get(f"/api/academy/quiz/{module_id}/formative").status_code == 200
    r = c.post(f"/api/academy/quiz/{module_id}/formative",
               json={"responses": {f"Q{i}": "A" for i in range(1, 7)}})
    assert r.status_code == 200 and r.json()["passed"] is True
    row = _row(admin, EMAIL)
    titles = [f["title"] for f in row["flags"]]
    assert any(t.startswith("Passed in ") and "Evaluation — Module One" in t for t in titles), titles
    assert row["worst"] == "warn"


def test_wrong_passwords_are_counted_and_flagged(admin, course):
    email = "pw.guess@example.com"
    admin.post("/api/admin/academy/grant", json={
        "email": email, "product_code": PRODUCT, "send_email_invite": False}, headers=ADMIN)
    db = SessionLocal()
    try:
        db.query(Learner).filter(Learner.email == email).one().password_hash = hash_password("right-one")
        db.commit()
    finally:
        db.close()
    with TestClient(app, base_url="https://testserver") as c:
        for _ in range(5):
            assert c.post("/auth/login", json={"email": email, "password": "nope"}).status_code == 401
        r = c.post("/auth/login", json={"email": email, "password": "right-one"})
        assert r.status_code == 200, r.text
    row = _row(admin, email)
    assert any("5 wrong passwords within one hour" in f["title"] for f in row["flags"])
    d = _detail(admin, email)
    tracked = [v for v in d["visits"] if v["source"] == "tracked"]
    assert tracked and tracked[0]["how"] == "Password (quiz apps)"
    assert tracked[0]["device"] == "Quiz app"


def test_two_browsers_at_once_on_different_networks(admin, course):
    email = "shared.login@example.com"
    admin.post("/api/admin/academy/grant", json={
        "email": email, "product_code": PRODUCT, "send_email_invite": False}, headers=ADMIN)
    a = _sign_in(email, headers={"x-forwarded-for": "203.0.113.10"})
    b = _sign_in(email, headers={"x-forwarded-for": "198.51.100.20"})
    assert a.get(f"/api/academy/course/{PRODUCT}").status_code == 200
    assert b.get(f"/api/academy/course/{PRODUCT}").status_code == 200
    row = _row(admin, email)
    assert row["integrity"]["overlaps_different_networks_30d"] >= 1
    assert any("different networks" in f["title"] for f in row["flags"])
    d = _detail(admin, email)
    assert len(d["devices"]) == 2


def test_simulator_sessions_and_refusals_are_recorded(admin, course):
    module_id, lessons = course
    lid = _learner_id(EMAIL)
    cookie = make_learner_token(lid, EMAIL)

    assert sim_routes.refusal_kind(4403, "The simulator runs only from proreadyengineer.com. Launch it") == "offsite"
    assert sim_routes.refusal_kind(4410, "This copy has expired. Launch a fresh one") == "expired"
    assert sim_routes.refusal_kind(4410, "This copy is not licensed to your account.") == "other_copy"

    meta = {"device": "", "cookie": cookie, "ip": "192.0.2.5", "origin": "https://evil.example"}
    sim_routes._record_refusal(
        meta, 4403, "The simulator runs only from proreadyengineer.com. Launch it from your course page.",
        lessons[0], "abcdef12")
    # Nobody signed in: nothing to attach it to, and no crash.
    sim_routes._record_refusal({**meta, "cookie": ""}, 4403, "x", lessons[0], "")

    class _Lesson:
        id = lessons[0]
        module_id = course[0]

    s = SimSession(id="s1", learner_id=lid, learner_email=EMAIL, lesson_id=lessons[0],
                   copy_token="tok123456", ctx=None)
    s.created = time.time() - 600
    s.ops = 450
    s.op_counts = {"step": 400, "set": 40, "ping": 10}
    s.sim_seconds = 400
    sim_routes._record_session(meta, lid, _Lesson(), s)

    row = _row(admin, EMAIL)
    titles = [f["title"] for f in row["flags"]]
    assert any("possibly a script" in t for t in titles), titles
    assert any("outside proreadyengineer.com" in t for t in titles), titles
    assert row["worst"] == "alert"
    d = _detail(admin, EMAIL)
    labels = [e["label"] for v in d["visits"] for e in v["events"]]
    assert any(l.startswith("Ran the simulator for 10 min — 440 commands") for l in labels), labels


def test_history_from_before_tracking_is_reconstructed(admin, course):
    email = "old.timer@example.com"
    admin.post("/api/admin/academy/grant", json={
        "email": email, "product_code": PRODUCT, "send_email_invite": False}, headers=ADMIN)
    _, lessons = course
    lid = _learner_id(email)
    db = SessionLocal()
    try:
        first = min((v.started_at for v in db.query(LearnerVisit).all()),
                    default=datetime.now(timezone.utc))
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        at = first - timedelta(days=5)
        db.add(LoginToken(learner_id=lid, token_hash="h" * 64, created_at=at,
                          expires_at=at + timedelta(minutes=30), used_at=at + timedelta(minutes=2)))
        db.add(LessonProgress(learner_id=lid, lesson_id=lessons[0], position_s=0,
                              watched_s=10, completed_at=at + timedelta(minutes=10),
                              updated_at=at + timedelta(minutes=10)))
        # The only browser this learner used then: the rebuilt visit names it.
        db.add(LearnerDevice(learner_id=lid, device_id="d" * 32, ip="198.51.100.7",
                             user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
                             first_seen_at=at - timedelta(days=1), last_seen_at=at + timedelta(minutes=12),
                             seen_count=3))
        db.commit()
    finally:
        db.close()
    d = _detail(admin, email)
    rebuilt = [v for v in d["visits"] if v["source"] == "records"]
    visit = next(v for v in rebuilt if any(e["kind"] == "lesson_complete" for e in v["events"]))
    kinds = [e["kind"] for e in visit["events"]]
    assert "sign_in" in kinds and "link_requested" in kinds
    assert visit["how"] == "Email-link sign-in"
    assert visit["counts_as_visit"] is True
    assert visit["device"] == "Safari on Mac" and visit["ip"] == "198.51.100.7"
    row = _row(admin, email)
    assert row["sign_ins"] >= 1


def test_certificates_are_listed(admin, course):
    module_id, lessons = course
    c = _sign_in(EMAIL)
    # Finish the course: lesson 2 and the (already passed) evaluation.
    c.post(f"/api/academy/lesson/{lessons[1]}/progress", json={"position_s": 0, "watched_delta_s": 5})
    c.post("/api/academy/profile/name", json={"full_name": "Test Trainee"})
    c.get(f"/api/academy/certification/{PRODUCT}")
    d = _detail(admin, EMAIL)
    tiers = [x["tier"] for x in d["learner"]["certificates"]]
    assert "completion" in tiers
    assert any(e["kind"] == "certificate" for v in d["visits"] for e in v["events"])


def test_tracking_failure_never_breaks_the_request(admin, course, monkeypatch):
    _, lessons = course

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(activity, "_open_visit", boom)
    c = _sign_in(EMAIL)
    assert c.get(f"/api/academy/lesson/{lessons[0]}").status_code == 200


def test_owner_is_not_counted_as_a_flagged_student(admin):
    r = admin.get("/api/admin/academy/activity", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    owners = [x for x in body["learners"] if x["is_owner"]]
    students = [x for x in body["learners"] if not x["is_owner"]]
    assert body["totals"]["students"] == len(students)
    assert body["totals"]["flagged"] == sum(1 for x in students if x["worst"] in ("warn", "alert"))
    del owners


def test_ua_summary():
    assert report.ua_summary(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1") == "Safari on iPhone"
    assert report.ua_summary(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0 Safari/537.36 Edg/128.0") == "Edge on Windows"
    assert report.ua_summary("") == "Unknown browser"


def test_sign_in_sets_the_device_cookie_before_the_first_page_loads(admin, course):
    """The page fires several requests at once right after signing in; if
    none of them carried a device cookie, each minted its own id and one
    person showed up as two browsers used at the same time."""
    email = "fresh.browser@example.com"
    admin.post("/api/admin/academy/grant", json={
        "email": email, "product_code": PRODUCT, "send_email_invite": False}, headers=ADMIN)
    c = TestClient(app, base_url="https://testserver")
    link = c.post("/api/admin/academy/login-link", json={"email": email}, headers=ADMIN).json()["link"]
    r = c.post("/api/academy/auth/verify", json={"token": link.split("token=")[1]})
    assert r.status_code == 200
    assert "learner_device=" in r.headers.get("set-cookie", "")
