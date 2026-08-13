"""Per-module grants, cohort mode, protected material serving, click-wrap.

Covers the DLE-mapping feature set end to end against real routers:

  * a product created through the new admin content API, in cohort mode
    (sequential_gate=False)
  * per-day ModuleGrants — grant Day 1 only, see exactly Day 1 open
  * grant-all via product enrollment; revoke works in both directions
  * cohort mark-paid → automatic learner + full enrollment + revoke on cancel
  * slide-image and asset endpoints enforce the module-scoped entitlement
  * click-wrap terms acceptance is recorded and reported
"""
from __future__ import annotations

import base64
import io
import struct
import zlib

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Learner, LoginToken  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "dle-mapping-test"
STUDENT = "day1.student@example.com"
COHORT_STUDENT = "cohort.buyer@example.com"


def _tiny_png() -> bytes:
    """A valid 4x4 red PNG built by hand — no Pillow dependency in tests."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _sign_in(client: TestClient, email: str) -> TestClient:
    """Grant-independent sign-in: mint a login link via the admin API."""
    c = TestClient(app, base_url="https://testserver")
    r = c.post(
        "/api/admin/academy/login-link",
        json={"email": email, "send_email": False},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    token = r.json()["link"].split("token=")[1]
    assert c.post("/api/academy/auth/verify", json={"token": token}).status_code == 200
    return c


@pytest.fixture(scope="module")
def setup(client):
    """Build the cohort-mode product with 2 day-modules + a sim module."""
    r = client.post(
        "/api/admin/academy/products",
        json={
            "code": PRODUCT,
            "title": "DLE Mapping (test)",
            "sequential_gate": False,
            "status": "draft",
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text

    module_ids = {}
    for pos, code in ((1, "DAY-1"), (2, "DAY-2"), (3, "SIM")):
        r = client.post(
            f"/api/admin/academy/products/{PRODUCT}/modules",
            json={"code": code, "title": code, "position": pos},
            headers=ADMIN,
        )
        assert r.status_code == 200, r.text
        module_ids[code] = r.json()["module_id"]

    # One slides lesson per day, one lab lesson for the sim.
    lessons = {}
    for code in ("DAY-1", "DAY-2"):
        r = client.post(
            f"/api/admin/academy/modules/{module_ids[code]}/lessons",
            json={"code": f"{code}-slides", "title": "Slides", "kind": "slides"},
            headers=ADMIN,
        )
        assert r.status_code == 200, r.text
        lessons[code] = r.json()["lesson_id"]
    r = client.post(
        "/api/admin/academy/assets",
        json={
            "key": "sim-test.html",
            "content_type": "text/html",
            "data_b64": base64.b64encode(
                b"<html><body><h1>SIM</h1></body></html>"
            ).decode(),
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/admin/academy/modules/{module_ids['SIM']}/lessons",
        json={
            "code": "sim-lab",
            "title": "Simulator",
            "kind": "lab",
            "asset_path": "blob:sim-test.html",
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    lessons["SIM"] = r.json()["lesson_id"]

    # One slide image on each day module.
    png_b64 = base64.b64encode(_tiny_png()).decode()
    for code in ("DAY-1", "DAY-2"):
        r = client.post(
            f"/api/admin/academy/modules/{module_ids[code]}/slides",
            json={
                "slides": [
                    {
                        "number": 1,
                        "title": "Cover",
                        "image_lg_b64": png_b64,
                        "image_sm_b64": png_b64,
                    }
                ]
            },
            headers=ADMIN,
        )
        assert r.status_code == 200, r.text

    # A 2-item formative bank on DAY-1 so gates exist to ignore in cohort mode.
    r = client.post(
        f"/api/admin/academy/modules/{module_ids['DAY-1']}/quiz-items",
        json={
            "items": [
                {
                    "code": "T1",
                    "stem": "Pick A",
                    "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
                    "answer": {"key": "A"},
                    "position": 1,
                },
                {
                    "code": "T2",
                    "stem": "Pick B",
                    "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
                    "answer": {"key": "B"},
                    "position": 2,
                },
            ]
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    return module_ids, lessons


# -----------------------------------------------------------------------------
# Per-module grants
# -----------------------------------------------------------------------------

def test_day1_grant_opens_day1_only(client, setup):
    module_ids, lessons = setup
    r = client.post(
        "/api/admin/academy/grant-module",
        json={"email": STUDENT, "module_id": module_ids["DAY-1"]},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text

    s = _sign_in(client, STUDENT)
    course = s.get(f"/api/academy/course/{PRODUCT}")
    assert course.status_code == 200, course.text
    by_code = {m["code"]: m for m in course.json()["modules"]}
    assert by_code["DAY-1"]["unlocked"] is True
    assert by_code["DAY-1"]["entitled"] is True
    assert by_code["DAY-2"]["unlocked"] is False
    assert by_code["DAY-2"]["entitled"] is False

    # Lesson access follows the same rule.
    assert s.get(f"/api/academy/lesson/{lessons['DAY-1']}").status_code == 200
    assert s.get(f"/api/academy/lesson/{lessons['DAY-2']}").status_code == 403

    # Slide pixels: day 1 serves, day 2 refuses — URL iteration buys nothing.
    ok = s.get(f"/api/academy/slide-image/{module_ids['DAY-1']}/1/lg")
    assert ok.status_code == 200
    # Browser-private caching only — never a shared cache.
    assert ok.headers["cache-control"].startswith("private")
    assert "no-store" not in ok.headers["cache-control"]
    assert s.get(f"/api/academy/slide-image/{module_ids['DAY-2']}/1/lg").status_code == 403

    # The simulator module was never granted.
    assert s.get(f"/api/academy/asset/{lessons['SIM']}").status_code == 403


def test_module_grants_appear_on_me(client, setup):
    s = _sign_in(client, STUDENT)
    me = s.get("/api/academy/me").json()
    assert any(g["product_code"] == PRODUCT for g in me["module_grants"])


def test_quiz_reachable_on_granted_module_without_product_enrollment(client, setup):
    module_ids, _ = setup
    s = _sign_in(client, STUDENT)
    r = s.get(f"/api/academy/quiz/{module_ids['DAY-1']}/formative")
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2
    # And the answer key never crosses the wire.
    assert "answer" not in r.json()["items"][0]

    graded = s.post(
        f"/api/academy/quiz/{module_ids['DAY-1']}/formative",
        json={"responses": {"T1": "A", "T2": "B"}},
    )
    assert graded.status_code == 200
    assert graded.json()["score_pct"] == 100.0


def test_revoke_module_closes_the_door(client, setup):
    module_ids, lessons = setup
    r = client.post(
        "/api/admin/academy/revoke-module",
        json={"email": STUDENT, "module_id": module_ids["DAY-1"]},
        headers=ADMIN,
    )
    assert r.status_code == 200 and r.json()["changed"] is True

    s = _sign_in(client, STUDENT)
    assert s.get(f"/api/academy/course/{PRODUCT}").status_code == 403
    assert s.get(f"/api/academy/lesson/{lessons['DAY-1']}").status_code == 403
    assert s.get(f"/api/academy/slide-image/{module_ids['DAY-1']}/1/lg").status_code == 403

    # Re-grant reactivates the same row (idempotent path).
    client.post(
        "/api/admin/academy/grant-module",
        json={"email": STUDENT, "module_id": module_ids["DAY-1"]},
        headers=ADMIN,
    )
    assert s.get(f"/api/academy/lesson/{lessons['DAY-1']}").status_code == 200


def test_grant_all_via_product_enrollment(client, setup):
    module_ids, lessons = setup
    r = client.post(
        "/api/admin/academy/grant",
        json={
            "email": STUDENT,
            "product_code": PRODUCT,
            "send_email_invite": False,
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text

    s = _sign_in(client, STUDENT)
    by_code = {m["code"]: m for m in s.get(f"/api/academy/course/{PRODUCT}").json()["modules"]}
    # Cohort mode: everything entitled is open at once — no mastery chain.
    assert all(m["unlocked"] for m in by_code.values())

    sim = s.get(f"/api/academy/asset/{lessons['SIM']}")
    assert sim.status_code == 200
    assert "Licensed to" in sim.text and STUDENT in sim.text
    assert sim.headers["cache-control"].startswith("private, no-store")

    # Product-level revoke pulls everything except the standalone day grant.
    client.post(
        "/api/admin/academy/revoke",
        json={"email": STUDENT, "product_code": PRODUCT},
        headers=ADMIN,
    )
    by_code = {m["code"]: m for m in s.get(f"/api/academy/course/{PRODUCT}").json()["modules"]}
    assert by_code["DAY-1"]["unlocked"] is True  # module grant survives
    assert by_code["DAY-2"]["unlocked"] is False


def test_access_matrix_reports_the_truth(client, setup):
    module_ids, _ = setup
    r = client.get(f"/api/admin/academy/products/{PRODUCT}/access", headers=ADMIN)
    assert r.status_code == 200
    data = r.json()
    assert data["product"]["sequential_gate"] is False
    row = next(l for l in data["learners"] if l["email"] == STUDENT)
    assert row["enrolled_all"] is False
    assert module_ids["DAY-1"] in row["module_ids"]


# -----------------------------------------------------------------------------
# Cohort mark-paid → auto-grant → cancel → auto-revoke
# -----------------------------------------------------------------------------

def test_cohort_mark_paid_grants_everything(client, setup):
    # A live cohort linked to the materials product.
    from app.models import Course

    db = SessionLocal()
    db.add(
        Course(
            code="dle-cohort-test",
            title="DLE cohort (test)",
            start_date=__import__("datetime").date(2026, 8, 29),
            total_seats=15,
            recorded_product_code=PRODUCT,
        )
    )
    db.commit()
    db.close()

    r = client.post(
        "/api/register",
        json={
            "course_code": "dle-cohort-test",
            "full_name": "Cohort Buyer",
            "email": COHORT_STUDENT,
            "job_title": "Engineer",
            "company": "ACME",
            "years_experience": "5-10",
            "location": "Houston",
        },
    )
    assert r.status_code == 200, r.text
    reg_id = r.json().get("id")
    if reg_id is None:  # registration endpoint may not echo the id
        from app.models import Registration

        db = SessionLocal()
        reg_id = (
            db.query(Registration)
            .filter(Registration.email == COHORT_STUDENT)
            .one()
            .id
        )
        db.close()

    r = client.post(
        "/api/admin/mark-paid", json={"registration_id": reg_id}, headers=ADMIN
    )
    assert r.status_code == 200, r.text

    # Paid = all access: learner exists, enrollment active, everything opens.
    s = _sign_in(client, COHORT_STUDENT)
    me = s.get("/api/academy/me").json()
    assert any(e["product_code"] == PRODUCT for e in me["enrollments"])
    course = s.get(f"/api/academy/course/{PRODUCT}")
    assert course.status_code == 200
    assert all(m["unlocked"] for m in course.json()["modules"])

    # Cancel pulls the cohort-sourced enrollment back.
    r = client.post(
        "/api/admin/cancel", json={"registration_id": reg_id}, headers=ADMIN
    )
    assert r.status_code == 200
    me = s.get("/api/academy/me").json()
    assert not any(e["product_code"] == PRODUCT for e in me["enrollments"])


# -----------------------------------------------------------------------------
# Click-wrap terms
# -----------------------------------------------------------------------------

def test_terms_acceptance_round_trip(client, setup):
    s = _sign_in(client, STUDENT)
    me = s.get("/api/academy/me").json()
    version = me["terms_version"]
    assert me["terms_accepted"] is False

    r = s.post("/api/academy/accept-terms", json={"version": "stale-version"})
    assert r.status_code == 409

    r = s.post("/api/academy/accept-terms", json={"version": version})
    assert r.status_code == 200
    assert s.get("/api/academy/me").json()["terms_accepted"] is True


# -----------------------------------------------------------------------------
# Watermarking
# -----------------------------------------------------------------------------

def test_slide_image_is_watermarked_per_learner(client, setup):
    module_ids, _ = setup
    s = _sign_in(client, STUDENT)
    lg = s.get(f"/api/academy/slide-image/{module_ids['DAY-1']}/1/lg")
    sm = s.get(f"/api/academy/slide-image/{module_ids['DAY-1']}/1/sm")
    assert lg.status_code == 200 and sm.status_code == 200
    # The lg variant is re-encoded with the burn; sm is the original bytes.
    assert sm.content == _tiny_png()
    assert lg.content != _tiny_png()
    assert lg.content[:8] == b"\x89PNG\r\n\x1a\n"


# -----------------------------------------------------------------------------
# /my-courses — the /learn chooser feed
# -----------------------------------------------------------------------------

def test_my_courses_lists_partial_and_full_access(client, setup):
    module_ids, _ = setup
    # STUDENT currently holds a DAY-1 grant (re-granted) and no enrollment.
    s = _sign_in(client, STUDENT)
    r = s.get("/api/academy/my-courses")
    assert r.status_code == 200, r.text
    courses = {c["code"]: c for c in r.json()["courses"]}
    assert PRODUCT in courses
    assert courses[PRODUCT]["access"] == "partial"

    # A full enrollment upgrades the same row to 'full'.
    client.post(
        "/api/admin/academy/grant",
        json={"email": STUDENT, "product_code": PRODUCT, "send_email_invite": False},
        headers=ADMIN,
    )
    courses = {c["code"]: c for c in s.get("/api/academy/my-courses").json()["courses"]}
    assert courses[PRODUCT]["access"] == "full"
    # Cleanup so later runs start from the partial state again.
    client.post(
        "/api/admin/academy/revoke",
        json={"email": STUDENT, "product_code": PRODUCT},
        headers=ADMIN,
    )


def test_my_courses_owner_sees_everything(client, setup):
    # Owner addresses are created on demand by the login-link endpoint.
    from app.config import get_settings

    owner_email = get_settings().owner_emails_list[0]
    o = _sign_in(client, owner_email)
    r = o.get("/api/academy/my-courses")
    assert r.status_code == 200
    codes = {c["code"] for c in r.json()["courses"]}
    assert PRODUCT in codes  # drafts included for owners
    assert all(c["access"] == "owner" for c in r.json()["courses"])


# -----------------------------------------------------------------------------
# Deck completion — reached the last slide, not merely opened the page
# -----------------------------------------------------------------------------

def test_slides_lesson_completes_on_last_slide_not_first_open(client, setup):
    module_ids, lessons = setup
    # Give the student DAY-1 (idempotent if already granted).
    client.post(
        "/api/admin/academy/grant-module",
        json={"email": STUDENT, "module_id": module_ids["DAY-1"]},
        headers=ADMIN,
    )
    s = _sign_in(client, STUDENT)
    lesson_id = lessons["DAY-1"]

    # DAY-1 has exactly 1 slide in the fixture; add a second so "first
    # slide" and "last slide" are distinct states.
    import base64 as _b64

    client.post(
        f"/api/admin/academy/modules/{module_ids['DAY-1']}/slides",
        json={"slides": [{"number": 2, "title": "Second",
                          "image_lg_b64": _b64.b64encode(_tiny_png()).decode(),
                          "image_sm_b64": _b64.b64encode(_tiny_png()).decode()}]},
        headers=ADMIN,
    )

    # Heartbeat from slide 1: watched time accrues but the deck is NOT done.
    r = s.post(
        f"/api/academy/lesson/{lesson_id}/progress",
        json={"position_s": 1, "watched_delta_s": 30},
    )
    assert r.status_code == 200, r.text
    assert r.json()["completed"] is False

    detail = s.get(f"/api/academy/lesson/{lesson_id}").json()
    assert detail["progress"]["completed"] is False

    # Reaching the last slide completes the deck.
    r = s.post(
        f"/api/academy/lesson/{lesson_id}/progress",
        json={"position_s": 2, "watched_delta_s": 5},
    )
    assert r.json()["completed"] is True

    # And the high-water mark never rolls back.
    r = s.post(
        f"/api/academy/lesson/{lesson_id}/progress",
        json={"position_s": 1, "watched_delta_s": 5},
    )
    assert r.json()["completed"] is True
