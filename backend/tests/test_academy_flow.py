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
from app.config import get_settings  # noqa: E402
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
    # The refusal now names the blocking module and what to do there, so the
    # UI can send the learner straight to that evaluation.
    body = r.json()
    # A readable sentence for any client, plus the structured payload.
    assert isinstance(body["detail"], str)
    assert modules[0]["title"] in body["detail"]
    gate = body["gate"]
    assert gate["code"] == "gate_locked"
    assert gate["blocking_module_id"] == modules[0]["id"]
    assert gate["needs"] in ("quiz", "lessons")


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


# -----------------------------------------------------------------------------
# Owner override
# -----------------------------------------------------------------------------

def test_owner_email_bypasses_purchase_and_every_gate(client):
    """The site owner can inspect the whole product without buying it.

    Safe because the email is only ever proven — magic link received, or a
    password set on that address. A stranger typing it gets nothing, which the
    next test asserts.
    """
    from app.academy import is_owner
    from app.config import get_settings

    owner_email = get_settings().owner_emails_list[0]

    db = SessionLocal()
    owner = Learner(email=owner_email, full_name="Owner")
    db.add(owner)
    db.commit()
    from app.learner_auth import issue_login_token

    raw = issue_login_token(db, owner)
    db.close()

    owner_client = TestClient(app, base_url="https://testserver")
    assert owner_client.post("/api/academy/auth/verify", json={"token": raw}).status_code == 200

    # No enrollment row exists for this learner at all.
    me = owner_client.get("/api/academy/me").json()
    assert me["signed_in"] is True and me["enrollments"] == []

    course = owner_client.get(f"/api/academy/course/{PRODUCT}")
    assert course.status_code == 200, "owner should reach the course without buying"
    modules = course.json()["modules"]
    assert all(m["unlocked"] for m in modules), "every module open, no sequential gate"

    # And a locked-for-everyone-else lesson opens.
    deep = modules[-1]["lessons"][0]
    assert owner_client.get(f"/api/academy/lesson/{deep['id']}").status_code == 200

    db = SessionLocal()
    promoted = db.query(Learner).filter(Learner.email == owner_email).one()
    db.close()
    assert promoted.is_staff is True, "owner should be flagged staff on first sight"
    assert is_owner(promoted) is True


def test_claiming_the_owner_email_without_proving_it_grants_nothing(anon):
    """Typing the owner's address must not be a way in."""
    # No session at all — the course stays closed.
    assert anon.get(f"/api/academy/course/{PRODUCT}").status_code == 401
    # And asking for a link to that address reveals nothing and grants nothing.
    from app.config import get_settings

    r = anon.post(
        "/api/academy/auth/request-link",
        json={"email": get_settings().owner_emails_list[0]},
    )
    assert r.json() == {"ok": True}
    assert anon.get("/api/academy/me").json()["signed_in"] is False


# -----------------------------------------------------------------------------
# Admin tooling for access
# -----------------------------------------------------------------------------

def test_admin_sees_who_holds_owner_bypass(client):
    r = client.get("/api/admin/academy/owners", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert get_settings().owner_emails_list[0] in body["owner_emails"]
    assert body["env_var"] == "OWNER_EMAILS"
    # Unauthenticated callers learn nothing about who can bypass.
    assert client.get("/api/admin/academy/owners").status_code == 401


def test_admin_can_mint_a_sign_in_link_and_it_works_once(client):
    email = "link-me@example.com"
    client.post(
        "/api/admin/academy/grant",
        headers=ADMIN,
        json={"email": email, "product_code": PRODUCT, "send_email_invite": False},
    )

    r = client.post(
        "/api/admin/academy/login-link", headers=ADMIN, json={"email": email}
    )
    assert r.status_code == 200
    link = r.json()["link"]
    assert r.json()["emailed"] is False, "must not email unless asked"

    token = link.split("token=")[1]
    fresh = TestClient(app, base_url="https://testserver")
    assert fresh.post("/api/academy/auth/verify", json={"token": token}).status_code == 200
    assert fresh.get("/api/academy/me").json()["email"] == email

    # Single use: the same token is dead the second time.
    again = TestClient(app, base_url="https://testserver")
    assert again.post("/api/academy/auth/verify", json={"token": token}).status_code == 400

    assert client.post(
        "/api/admin/academy/login-link", headers=ADMIN, json={"email": "nobody@example.com"}
    ).status_code == 404
    assert client.post(
        "/api/admin/academy/login-link", json={"email": email}
    ).status_code == 401


def test_admin_learner_rows_flag_owners_and_missing_passwords(client):
    rows = client.get("/api/admin/academy/learners", headers=ADMIN).json()["learners"]
    assert rows, "expected at least one learner by now"
    for row in rows:
        assert "is_owner" in row and "has_password" in row


def test_a_learner_can_set_a_quiz_app_password_from_a_proven_session(client):
    """Closes the loop opened by refusing password signup on accounts that
    already carry access: the session proves the mailbox, so setting a
    password from inside it is safe."""
    from app.routes.compat import verify_password

    email = "sets-a-password@example.com"
    client.post(
        "/api/admin/academy/grant",
        headers=ADMIN,
        json={"email": email, "product_code": PRODUCT, "send_email_invite": False},
    )
    link = client.post(
        "/api/admin/academy/login-link", headers=ADMIN, json={"email": email}
    ).json()["link"]

    session = TestClient(app, base_url="https://testserver")
    session.post("/api/academy/auth/verify", json={"token": link.split("token=")[1]})
    assert session.get("/api/academy/me").json()["has_password"] is False

    assert session.post(
        "/api/academy/auth/set-password", json={"password": "a-good-long-password"}
    ).status_code == 200
    assert session.get("/api/academy/me").json()["has_password"] is True

    db = SessionLocal()
    row = db.query(Learner).filter(Learner.email == email).one()
    assert verify_password("a-good-long-password", row.password_hash)
    db.close()

    # And it is genuinely session-gated, not just email-gated.
    assert TestClient(app, base_url="https://testserver").post(
        "/api/academy/auth/set-password", json={"password": "another-password"}
    ).status_code == 401


def test_a_newly_added_owner_can_get_in_from_a_standing_start(client):
    """The gap this pins: password signup on an owner address is refused, so if
    request-link also no-opped for an address with no row yet, adding an email
    to OWNER_EMAILS would lock that person out completely rather than let them
    in. Owner rows are therefore created on first request."""
    from app.config import get_settings

    settings = get_settings()
    original = settings.OWNER_EMAILS
    fresh = "brand-new-owner@example.com"
    settings.OWNER_EMAILS = f"{original},{fresh}"
    try:
        db = SessionLocal()
        assert db.query(Learner).filter(Learner.email == fresh).count() == 0
        db.close()

        assert client.post(
            "/api/academy/auth/request-link",
            json={"email": fresh, "next_path": "/learn", "website": ""},
        ).status_code == 200

        db = SessionLocal()
        row = db.query(Learner).filter(Learner.email == fresh).one()
        assert row.is_staff is True, "and is promoted at the same moment"
        db.close()

        # A stranger with no row still gets nothing created for them.
        client.post(
            "/api/academy/auth/request-link",
            json={"email": "not-an-owner@example.com", "next_path": "/learn", "website": ""},
        )
        db = SessionLocal()
        assert db.query(Learner).filter(Learner.email == "not-an-owner@example.com").count() == 0
        db.close()

        # Admin can mint a link for an owner who has never signed in; not for
        # an arbitrary unknown address.
        assert client.post(
            "/api/admin/academy/login-link", headers=ADMIN, json={"email": fresh}
        ).status_code == 200
        assert client.post(
            "/api/admin/academy/login-link", headers=ADMIN, json={"email": "ghost@example.com"}
        ).status_code == 404
    finally:
        settings.OWNER_EMAILS = original


def test_owner_access_can_be_taken_back(client):
    """The failure this pins: is_staff used to be an independent grant, so once
    a row had been flagged, removing the address from OWNER_EMAILS left the
    bypass in place permanently — a temporary co-instructor would have kept
    god-mode forever. The config list is now the only source of truth."""
    settings = get_settings()
    original = settings.OWNER_EMAILS
    temp = "temporary-owner@example.com"

    settings.OWNER_EMAILS = f"{original},{temp}"
    try:
        link = client.post(
            "/api/admin/academy/login-link", headers=ADMIN, json={"email": temp}
        ).json()["link"]
        session = TestClient(app, base_url="https://testserver")
        session.post("/api/academy/auth/verify", json={"token": link.split("token=")[1]})

        assert session.get("/api/academy/me").json()["is_owner"] is True
        assert session.get(f"/api/academy/course/{PRODUCT}").status_code == 200

        db = SessionLocal()
        assert db.query(Learner).filter(Learner.email == temp).one().is_staff is True
        db.close()
    finally:
        settings.OWNER_EMAILS = original

    # Same live session, same cookie — the bypass is simply gone.
    assert session.get("/api/academy/me").json()["is_owner"] is False
    assert session.get(f"/api/academy/course/{PRODUCT}").status_code == 403

    # And the stored flag reconciles rather than lingering as a false badge.
    client.get("/api/admin/academy/learners", headers=ADMIN)
    db = SessionLocal()
    assert db.query(Learner).filter(Learner.email == temp).one().is_staff is False
    db.close()
