"""End-to-end test of the academy purchase → learn → assess → certify flow.

Runs against a throwaway SQLite file with a real FastAPI TestClient, so it
exercises the actual routers, dependencies, cookie handling and grading —
not mocks. Run with:  python -m pytest backend/tests -q
"""
from __future__ import annotations

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Learner, LoginToken, Module, QuizItem  # noqa: E402

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
LEARNER_EMAIL = "engineer@example.com"


@pytest.fixture(scope="module")
def client():
    # https base_url so the Secure cookie is actually stored by the client.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(scope="module")
def anon():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


# -----------------------------------------------------------------------------
# Seeding
# -----------------------------------------------------------------------------

def test_seed_created_full_curriculum(client):
    r = client.get("/api/admin/academy/products/%s/content" % PRODUCT, headers=ADMIN)
    assert r.status_code == 200
    modules = r.json()["modules"]
    assert [m["code"] for m in modules] == [
        "GT-03", "GT-05", "GT-06", "GT-07", "GT-12", "GT-13", "GT-15"
    ]
    videos = {m["code"]: sum(1 for l in m["lessons"] if l["kind"] == "video")
              for m in modules}
    assert videos == {"GT-03": 0, "GT-05": 11, "GT-06": 14,
                      "GT-07": 23, "GT-12": 0, "GT-13": 17, "GT-15": 18}
    # The GT-05 bank landed on GT-05 and nowhere else.
    counts = {m["code"]: m["quiz_item_count"] for m in modules}
    assert counts["GT-05"] == 67
    assert sum(v for k, v in counts.items() if k != "GT-05") == 0


def test_seed_is_idempotent():
    """Re-running the seeder must not duplicate rows."""
    from app.academy_seed import seed_academy

    db = SessionLocal()
    before_modules = db.query(Module).count()
    before_items = db.query(QuizItem).count()
    db.close()

    seed_academy()

    db = SessionLocal()
    assert db.query(Module).count() == before_modules
    assert db.query(QuizItem).count() == before_items
    db.close()


# -----------------------------------------------------------------------------
# Publishing guard rails
# -----------------------------------------------------------------------------

def test_product_starts_as_draft_and_is_not_in_catalog(anon):
    assert anon.get("/api/academy/catalog").json()["products"] == []


def test_cannot_publish_without_a_price(client):
    r = client.patch(
        f"/api/admin/academy/products/{PRODUCT}", json={"status": "live"}, headers=ADMIN
    )
    assert r.status_code == 409


def test_publish_with_price(client, anon):
    r = client.patch(
        f"/api/admin/academy/products/{PRODUCT}",
        json={"status": "live", "price_cents": 129900},
        headers=ADMIN,
    )
    assert r.status_code == 200 and r.json()["status"] == "live"
    catalog = anon.get("/api/academy/catalog").json()["products"]
    assert len(catalog) == 1
    assert catalog[0]["price_cents"] == 129900
    assert len(catalog[0]["curriculum"]) == 7


def test_admin_endpoints_reject_anonymous(anon):
    assert anon.get("/api/admin/academy/products").status_code == 401
    assert anon.post(
        "/api/admin/academy/grant",
        json={"email": "x@y.com", "product_code": PRODUCT},
    ).status_code == 401


# -----------------------------------------------------------------------------
# Access control before purchase
# -----------------------------------------------------------------------------

def test_course_requires_sign_in(anon):
    assert anon.get(f"/api/academy/course/{PRODUCT}").status_code == 401


def test_preview_lesson_is_open_to_anonymous_visitors(anon, client):
    content = client.get(
        f"/api/admin/academy/products/{PRODUCT}/content", headers=ADMIN
    ).json()
    preview = [
        l for m in content["modules"] for l in m["lessons"] if l["is_preview"]
    ]
    assert len(preview) == 1, "exactly one free sample lesson should exist"
    r = anon.get(f"/api/academy/lesson/{preview[0]['id']}")
    assert r.status_code == 200
    assert r.json()["is_preview"] is True


def test_non_preview_lesson_is_denied_to_anonymous_visitors(anon, client):
    content = client.get(
        f"/api/admin/academy/products/{PRODUCT}/content", headers=ADMIN
    ).json()
    locked = [
        l for m in content["modules"] for l in m["lessons"] if not l["is_preview"]
    ][0]
    r = anon.get(f"/api/academy/lesson/{locked['id']}")
    assert r.status_code == 403


# -----------------------------------------------------------------------------
# Sign-in
# -----------------------------------------------------------------------------

def test_grant_access_and_sign_in(client):
    r = client.post(
        "/api/admin/academy/grant",
        json={
            "email": LEARNER_EMAIL,
            "product_code": PRODUCT,
            "full_name": "Test Engineer",
            "send_email_invite": True,
        },
        headers=ADMIN,
    )
    assert r.status_code == 200

    # The grant emails a link; pull the raw token the same way the learner
    # would receive it. Only the hash is stored, so we mint a fresh one.
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == LEARNER_EMAIL).one()
    from app.learner_auth import issue_login_token

    raw = issue_login_token(db, learner)
    db.close()

    r = client.post("/api/academy/auth/verify", json={"token": raw})
    assert r.status_code == 200 and r.json()["email"] == LEARNER_EMAIL

    me = client.get("/api/academy/me").json()
    assert me["signed_in"] is True
    assert me["enrollments"][0]["product_code"] == PRODUCT


def test_login_token_is_single_use(client):
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == LEARNER_EMAIL).one()
    from app.learner_auth import issue_login_token

    raw = issue_login_token(db, learner)
    db.close()

    assert client.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200
    assert client.post("/api/academy/auth/verify", json={"token": raw}).status_code == 400


def test_request_link_does_not_reveal_unknown_addresses(anon):
    known = anon.post(
        "/api/academy/auth/request-link", json={"email": LEARNER_EMAIL}
    )
    unknown = anon.post(
        "/api/academy/auth/request-link", json={"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"ok": True}


def test_request_link_rate_limit(anon):
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == LEARNER_EMAIL).one()
    before = db.query(LoginToken).filter(LoginToken.learner_id == learner.id).count()
    db.close()

    for _ in range(10):
        anon.post("/api/academy/auth/request-link", json={"email": LEARNER_EMAIL})

    db = SessionLocal()
    after = db.query(LoginToken).filter(LoginToken.learner_id == learner.id).count()
    db.close()
    # Capped at LOGIN_LINK_MAX_PER_HOUR (5) issued within the window.
    assert after - before <= 5


def test_learner_cookie_does_not_grant_admin(client):
    """The two auth systems must not be interchangeable."""
    assert client.get("/api/admin/academy/products").status_code == 401


# -----------------------------------------------------------------------------
# Mastery gating
# -----------------------------------------------------------------------------

def test_only_first_module_starts_unlocked(client):
    modules = client.get(f"/api/academy/course/{PRODUCT}").json()["modules"]
    assert modules[0]["unlocked"] is True
    assert all(m["unlocked"] is False for m in modules[1:])


def test_locked_module_lesson_is_denied(client):
    modules = client.get(f"/api/academy/course/{PRODUCT}").json()["modules"]
    gt05 = modules[1]
    locked = [l for l in gt05["lessons"] if not l["is_preview"]][0]
    r = client.get(f"/api/academy/lesson/{locked['id']}")
    assert r.status_code == 403
    assert "previous module" in r.json()["detail"].lower()


def test_locked_module_quiz_is_denied(client):
    modules = client.get(f"/api/academy/course/{PRODUCT}").json()["modules"]
    r = client.get(f"/api/academy/quiz/{modules[1]['id']}/formative")
    assert r.status_code == 403


def test_completing_module_one_unlocks_module_two(client):
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    gt03 = course["modules"][0]
    for lesson in gt03["lessons"]:
        r = client.post(
            f"/api/academy/lesson/{lesson['id']}/progress",
            json={"position_s": 10, "watched_delta_s": 30},
        )
        assert r.status_code == 200

    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    assert course["modules"][0]["lessons_completed"] == gt03["lesson_count"]
    assert course["modules"][1]["unlocked"] is True, "GT-05 should now be open"
    assert course["modules"][2]["unlocked"] is False, "GT-06 still gated on GT-05"


def test_progress_heartbeat_is_clamped(client):
    """A client must not be able to fake completion with one huge delta."""
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    lesson = next(
        l for l in course["modules"][1]["lessons"] if l["kind"] == "video"
    )
    client.patch(
        f"/api/admin/academy/lessons/{lesson['id']}",
        json={"duration_s": 3600},
        headers=ADMIN,
    )
    r = client.post(
        f"/api/academy/lesson/{lesson['id']}/progress",
        json={"position_s": 3599, "watched_delta_s": 60},
    )
    assert r.status_code == 200
    assert r.json()["watched_s"] <= 60
    assert r.json()["completed"] is False

    # Values beyond the schema bounds are rejected outright.
    assert client.post(
        f"/api/academy/lesson/{lesson['id']}/progress",
        json={"position_s": 0, "watched_delta_s": 99999},
    ).status_code == 422


# -----------------------------------------------------------------------------
# Quiz engine
# -----------------------------------------------------------------------------

def test_quiz_never_exposes_the_answer_key(client):
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    module_id = course["modules"][1]["id"]
    body = client.get(f"/api/academy/quiz/{module_id}/formative").json()
    assert len(body["items"]) == 41

    # The serializer exposes exactly this whitelist and nothing else, so a
    # field added to QuizItem later cannot silently start leaking.
    allowed = {
        "code", "kind", "stem", "options", "cognitive_level",
        "position", "section", "rubric",
    }
    for item in body["items"]:
        assert set(item) == allowed, f"unexpected fields: {set(item) - allowed}"
        for option in item["options"]:
            assert "✓" not in option["text"]

    # And the actual keys really are absent from the payload.
    db = SessionLocal()
    keyed = {
        i.code: i.answer.get("key")
        for i in db.query(QuizItem)
        .filter(QuizItem.module_id == module_id, QuizItem.item_set == "formative")
        .all()
        if i.kind == "mcq"
    }
    db.close()
    by_code = {i["code"]: i for i in body["items"]}
    for code, key in keyed.items():
        assert key not in by_code[code].values()
    # Sections let the UI chunk the bank rather than show 41 items at once.
    assert len({i["section"] for i in body["items"]}) > 1


def test_failing_the_formative_keeps_the_next_module_locked(client):
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    module_id = course["modules"][1]["id"]
    items = client.get(f"/api/academy/quiz/{module_id}/formative").json()["items"]

    responses = {i["code"]: "A" for i in items}  # blanket guess
    r = client.post(
        f"/api/academy/quiz/{module_id}/formative", json={"responses": responses}
    )
    assert r.status_code == 200
    result = r.json()
    assert result["score_pct"] < 80.0
    assert result["passed"] is False
    # Feedback is released after submission — that's the teaching moment.
    assert any(f["explanation"] for f in result["feedback"])

    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    assert course["modules"][2]["unlocked"] is False


def test_passing_the_formative_unlocks_the_next_module(client):
    db = SessionLocal()
    module = db.query(Module).filter(Module.code == "GT-05").one()
    items = (
        db.query(QuizItem)
        .filter(QuizItem.module_id == module.id, QuizItem.item_set == "formative")
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
    module_id = module.id
    db.close()

    r = client.post(
        f"/api/academy/quiz/{module_id}/formative", json={"responses": responses}
    )
    assert r.status_code == 200
    result = r.json()
    assert result["score_pct"] == 100.0
    assert result["passed"] is True
    # The formative bank is all MCQ, so every item is auto-graded.
    assert result["auto_total"] == len(responses) == 41

    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    assert course["modules"][2]["unlocked"] is True
    assert course["modules"][3]["unlocked"] is False


def test_unknown_item_set_is_rejected(client):
    course = client.get(f"/api/academy/course/{PRODUCT}").json()
    module_id = course["modules"][1]["id"]
    assert client.get(f"/api/academy/quiz/{module_id}/bogus").status_code == 400


# -----------------------------------------------------------------------------
# Certificates
# -----------------------------------------------------------------------------

def test_certificate_is_refused_until_the_course_is_finished(client):
    r = client.post(f"/api/academy/certificate/{PRODUCT}")
    assert r.status_code == 409


def test_certificate_verification_of_unknown_code_is_false(anon):
    assert anon.get("/api/academy/verify/PRE-NOPE").json()["valid"] is False


# -----------------------------------------------------------------------------
# Revocation
# -----------------------------------------------------------------------------

def test_revoking_access_locks_the_course_immediately(client):
    r = client.post(
        "/api/admin/academy/revoke",
        json={"email": LEARNER_EMAIL, "product_code": PRODUCT},
        headers=ADMIN,
    )
    assert r.status_code == 200
    assert client.get(f"/api/academy/course/{PRODUCT}").status_code == 403
    assert client.get("/api/academy/me").json()["enrollments"] == []


def test_regranting_reactivates_the_same_enrollment_row(client):
    from app.models import Enrollment

    client.post(
        "/api/admin/academy/grant",
        json={
            "email": LEARNER_EMAIL,
            "product_code": PRODUCT,
            "send_email_invite": False,
        },
        headers=ADMIN,
    )
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == LEARNER_EMAIL).one()
    rows = (
        db.query(Enrollment)
        .filter(
            Enrollment.learner_id == learner.id, Enrollment.product_code == PRODUCT
        )
        .all()
    )
    db.close()
    assert len(rows) == 1 and rows[0].status == "active"
    assert client.get(f"/api/academy/course/{PRODUCT}").status_code == 200


# -----------------------------------------------------------------------------
# Admin analytics
# -----------------------------------------------------------------------------

def test_stats_reports_the_module_funnel(client):
    body = client.get(
        f"/api/admin/academy/stats?product_code={PRODUCT}", headers=ADMIN
    ).json()
    assert body["active_enrollments"] == 1
    assert len(body["modules"]) == 7
    gt05 = next(m for m in body["modules"] if m["code"] == "GT-05")
    assert gt05["quiz_attempts"] >= 2
    assert gt05["learners_passed"] == 1
    assert gt05["avg_score"] is not None


def test_checkout_is_disabled_without_stripe_keys(anon):
    r = anon.post(
        "/api/academy/checkout", json={"product_code": PRODUCT}
    )
    assert r.status_code == 503


def test_short_answers_are_held_for_review_not_marked_wrong(client):
    """The summative set mixes MCQ with rubric-graded short answers.

    A short answer must never count against the score — otherwise a learner
    who writes a perfect essay is punished for the grader being asynchronous.
    """
    db = SessionLocal()
    module = db.query(Module).filter(Module.code == "GT-05").one()
    items = (
        db.query(QuizItem)
        .filter(QuizItem.module_id == module.id, QuizItem.item_set == "summative")
        .all()
    )
    responses = {}
    shorts = 0
    for item in items:
        if item.kind == "mcq":
            responses[item.code] = item.answer.get("key")
        else:
            shorts += 1
            responses[item.code] = "A written answer awaiting rubric review."
    module_id = module.id
    db.close()

    assert shorts == 9, "the summative bank should carry the rubric items"

    r = client.post(
        f"/api/academy/quiz/{module_id}/summative", json={"responses": responses}
    )
    assert r.status_code == 200
    result = r.json()
    assert result["auto_total"] == len(responses) - shorts == 17
    assert result["score_pct"] == 100.0 and result["passed"] is True
    flagged = [f for f in result["feedback"] if f["needs_review"]]
    assert len(flagged) == shorts
    assert all(f["rubric"] for f in flagged), "rubric must reach the reviewer"
