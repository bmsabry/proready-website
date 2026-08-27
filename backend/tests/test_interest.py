"""Interest-waitlist coverage — public signup, dedupe, honeypot, validation,
admin summary/list/delete/notify, and the AI assistant's read tool.

Shares the session-wide throwaway SQLite DB with the other test modules,
so every slug/email here is unique to this file (wl- prefix).
"""
from __future__ import annotations

import pytest

import conftest  # noqa: F401  — env vars must be set before app imports
from fastapi.testclient import TestClient

from app import ai_tools
from app import emailer as E
from app.db import SessionLocal
from app.main import app
from app.models import CourseInterest, EmailLog

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}

SLUG_A = "wl-hydrogen-retrofit"          # ends up with 2 signups
SLUG_B = "wl-blade-cooling"              # ends up with 1 signup
SLUG_SOLO = "wl-solo-signup"             # signup + dedupe tests
SLUG_HONEY = "wl-honeypot-target"        # must stay empty
SLUG_DEL = "wl-delete-me"                # delete test


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _rows_for(slug: str) -> list[CourseInterest]:
    db = SessionLocal()
    try:
        return list(
            db.query(CourseInterest).filter(CourseInterest.course_slug == slug).all()
        )
    finally:
        db.close()


# ----- Public signup ---------------------------------------------------------

def test_signup_creates_a_row(client):
    r = client.post(
        "/api/interest",
        json={
            "course_slug": SLUG_SOLO,
            "email": "Solo.Person@Example.com",
            "full_name": "  Solo Person  ",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "already": False}

    rows = _rows_for(SLUG_SOLO)
    assert len(rows) == 1
    assert rows[0].email == "solo.person@example.com"  # normalized
    assert rows[0].full_name == "Solo Person"
    assert rows[0].created_at is not None


def test_duplicate_signup_reports_already_and_adds_nothing(client):
    r = client.post(
        "/api/interest",
        json={"course_slug": SLUG_SOLO, "email": "SOLO.PERSON@example.com"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "already": True}
    assert len(_rows_for(SLUG_SOLO)) == 1


def test_honeypot_submission_is_silently_accepted_and_dropped(client):
    r = client.post(
        "/api/interest",
        json={
            "course_slug": SLUG_HONEY,
            "email": "bot@example.com",
            "website": "https://spam.example",
        },
    )
    # A bot must see the same success a human sees.
    assert r.status_code == 200
    assert r.json() == {"ok": True, "already": False}
    assert _rows_for(SLUG_HONEY) == []


@pytest.mark.parametrize("slug", ["ab", "Bad_Slug", "UPPER-CASE", "has space", "x" * 65])
def test_bad_slug_is_rejected(client, slug):
    r = client.post("/api/interest", json={"course_slug": slug, "email": "ok@example.com"})
    assert r.status_code == 422
    assert _rows_for(slug) == []


def test_bad_email_is_rejected(client):
    r = client.post("/api/interest", json={"course_slug": SLUG_SOLO, "email": "not-an-email"})
    assert r.status_code == 422


# ----- Admin: summary / list / delete ---------------------------------------

@pytest.fixture(scope="module")
def seeded(client):
    """Two waitlists built through the public endpoint: A has 2 people, B has 1."""
    for slug, email, name in [
        (SLUG_A, "ada@example.com", "Ada"),
        (SLUG_A, "grace@example.com", "Grace"),
        (SLUG_B, "linus@example.com", "Linus"),
    ]:
        r = client.post(
            "/api/interest",
            json={"course_slug": slug, "email": email, "full_name": name},
        )
        assert r.status_code == 200
    return True


def test_admin_endpoints_require_auth(client):
    assert client.get("/api/admin/interest/summary").status_code == 401
    assert client.get("/api/admin/interest").status_code == 401
    assert client.delete("/api/admin/interest/1").status_code == 401
    assert (
        client.post(
            f"/api/admin/interest/{SLUG_A}/notify",
            json={"subject": "s", "body_html": "<p>b</p>"},
        ).status_code
        == 401
    )


def test_summary_counts_and_orders_by_count_desc(client, seeded):
    r = client.get("/api/admin/interest/summary", headers=ADMIN)
    assert r.status_code == 200
    rows = r.json()

    by_slug = {row["course_slug"]: row for row in rows}
    assert by_slug[SLUG_A]["count"] == 2
    assert by_slug[SLUG_B]["count"] == 1
    assert by_slug[SLUG_A]["latest_at"] is not None

    counts = [row["count"] for row in rows]
    assert counts == sorted(counts, reverse=True)
    assert rows.index(by_slug[SLUG_A]) < rows.index(by_slug[SLUG_B])


def test_admin_list_filters_by_slug_newest_first(client, seeded):
    r = client.get(f"/api/admin/interest?course_slug={SLUG_A}", headers=ADMIN)
    assert r.status_code == 200
    rows = r.json()
    assert [row["course_slug"] for row in rows] == [SLUG_A, SLUG_A]
    assert {row["email"] for row in rows} == {"ada@example.com", "grace@example.com"}
    # Newest first — Grace signed up after Ada.
    assert rows[0]["email"] == "grace@example.com"
    for row in rows:
        assert set(row) == {"id", "course_slug", "email", "full_name", "created_at"}


def test_admin_list_without_filter_returns_all_slugs(client, seeded):
    r = client.get("/api/admin/interest", headers=ADMIN)
    assert r.status_code == 200
    slugs = {row["course_slug"] for row in r.json()}
    assert {SLUG_A, SLUG_B} <= slugs


def test_delete_removes_one_row(client):
    client.post("/api/interest", json={"course_slug": SLUG_DEL, "email": "gone@example.com"})
    (row,) = _rows_for(SLUG_DEL)

    r = client.delete(f"/api/admin/interest/{row.id}", headers=ADMIN)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert _rows_for(SLUG_DEL) == []

    assert client.delete(f"/api/admin/interest/{row.id}", headers=ADMIN).status_code == 404


# ----- Admin: notify ---------------------------------------------------------

def test_notify_broadcasts_to_that_waitlist_only(client, seeded, monkeypatch):
    captured: list = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "msg-1"}, {"id": "msg-2"}]}

    def fake_post(url, payload, key):
        captured.append((url, payload))
        return _Resp()

    monkeypatch.setattr(E, "_resend_post", fake_post)
    settings = E.get_settings()
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test", raising=False)

    r = client.post(
        f"/api/admin/interest/{SLUG_A}/notify",
        headers=ADMIN,
        json={"subject": "It is ready", "body_html": "<p>The course shipped.</p>"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["recipients"] == 2
    assert data["failures"] == 0

    # One batch POST, addressed to exactly the waitlist of SLUG_A.
    assert len(captured) == 1
    _, payload = captured[0]
    tos = [item["to"] for item in payload]
    assert tos == [["ada@example.com"], ["grace@example.com"]]
    assert all(item["subject"] == "It is ready" for item in payload)
    assert "The course shipped." in payload[0]["html"]

    # EmailLog rows carry the interest scope.
    db = SessionLocal()
    try:
        logs = list(db.query(EmailLog).filter(EmailLog.scope_code == SLUG_A).all())
    finally:
        db.close()
    assert {l.recipient for l in logs} == {"ada@example.com", "grace@example.com"}
    for l in logs:
        assert l.scope_kind == "interest"
        assert l.audience == "waitlist"
        assert l.template == "broadcast"
        assert l.ok is True


def test_notify_empty_waitlist_sends_nothing(client):
    r = client.post(
        "/api/admin/interest/wl-nobody-home/notify",
        headers=ADMIN,
        json={"subject": "s", "body_html": "<p>b</p>"},
    )
    assert r.status_code == 200
    assert r.json()["recipients"] == 0


# ----- AI assistant tool -----------------------------------------------------

def test_ai_tool_registry_includes_get_interest_summary(seeded):
    assert "get_interest_summary" in ai_tools.TOOL_HANDLERS
    spec = next(
        s["function"]
        for s in ai_tools.TOOL_SPECS
        if s["function"]["name"] == "get_interest_summary"
    )
    assert spec["parameters"]["required"] == []
    assert not ai_tools.is_high_stakes("get_interest_summary", {})

    db = SessionLocal()
    try:
        out = ai_tools.TOOL_HANDLERS["get_interest_summary"](db)
    finally:
        db.close()
    assert out["ok"] is True
    by_slug = {w["course_slug"]: w for w in out["waitlists"]}
    assert by_slug[SLUG_A]["count"] == 2
    assert by_slug[SLUG_B]["count"] == 1
    assert by_slug[SLUG_A]["latest_signup_at"] is not None
