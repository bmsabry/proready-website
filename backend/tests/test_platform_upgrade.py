"""Platform-upgrade coverage: software registry, email log + segmented comms,
course↔product link, unpinned admin registrations, per-course/software stats.

Runs last (alphabetical), against the same throwaway SQLite DB the academy
tests already populated — so every fixture here uses its own course codes,
slugs and email addresses. Resend is never contacted: tests either run in
stub mode (RESEND_API_KEY unset, sends report failure) or monkeypatch the
single HTTP seam (emailer._resend_post).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import emailer  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import EmailLog, Enrollment, Learner, Order, Product  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}

COURSE_A = "platform-test-2027"          # main test cohort
COURSE_A_TITLE = "Compressor Surge Masterclass"
COURSE_B = "platform-other-2027"         # second cohort for cross-course checks
RECORDED = "test-recorded-prod"          # academy product linked to COURSE_A


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


class FakeResp:
    def __init__(self, status_code: int = 200, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


@pytest.fixture
def resend(monkeypatch):
    """Pretend Resend is configured; capture every HTTP call at the seam."""
    calls: list[dict] = []
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test_key")

    def fake_post(url, payload, api_key):
        calls.append({"url": url, "payload": payload})
        if url == emailer.RESEND_BATCH_URL:
            return FakeResp(200, {"data": [{"id": f"batch-{i}"} for i in range(len(payload))]})
        return FakeResp(200, {"id": "single-abc123"})

    monkeypatch.setattr(emailer, "_resend_post", fake_post)
    return calls


def _register(client, email: str, course_code: str, company: str = "Alpha Co") -> dict:
    r = client.post(
        "/api/register",
        json={
            "full_name": "Test Person",
            "email": email,
            "job_title": "Engineer",
            "company": company,
            "years_experience": "5-10",
            "location": "Riyadh",
            "course_code": course_code,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _log_rows(**filters) -> list[EmailLog]:
    db = SessionLocal()
    try:
        q = db.query(EmailLog)
        for key, value in filters.items():
            q = q.filter(getattr(EmailLog, key) == value)
        return q.order_by(EmailLog.id.asc()).all()
    finally:
        db.close()


# -----------------------------------------------------------------------------
# A. Software registry
# -----------------------------------------------------------------------------

def test_public_software_list_has_seeded_pro3dworks(client):
    r = client.get("/api/products/software")
    assert r.status_code == 200
    products = r.json()
    row = next(p for p in products if p["slug"] == "pro3dworks")
    assert set(row) == {"slug", "name", "blurb", "latest_version", "download_count", "asset_path"}
    assert row["name"] == "Pro3DWorks"
    assert row["latest_version"] == "2.53.2"
    assert row["download_count"] == 0


def test_admin_create_product_enables_tracking(client):
    """Creating a registry row is all it takes for telemetry to accept a slug
    — the old hardcoded KNOWN_PRODUCTS set would have 400'd everything here."""
    r = client.post(
        "/api/admin/software",
        headers=ADMIN,
        json={
            "slug": "heatflow",
            "name": "HeatFlow",
            "blurb": "1D thermal network solver",
            "asset_path": "/downloads/HeatFlow.html",
            "latest_version": "1.0.0",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "live"

    assert client.post(
        "/api/track/download", json={"product": "heatflow", "country": "SA"}
    ).status_code == 200
    assert client.post(
        "/api/track/launch", json={"product": "heatflow", "version": "1.0.0"}
    ).status_code == 200
    assert client.post(
        "/api/track/usage",
        json={"product": "heatflow", "version": "1.0.0", "minutes": 5,
              "features": {"mesh": 2}},
    ).status_code == 200


def test_unknown_slug_still_400s(client):
    assert client.post("/api/track/download", json={"product": "nope"}).status_code == 400
    assert client.post("/api/track/launch", json={"product": "nope"}).status_code == 400
    assert client.post("/api/track/usage", json={"product": "nope"}).status_code == 400
    assert client.get("/api/downloads/stats?product=nope").status_code == 400
    assert client.get("/api/launches/stats?product=nope").status_code == 400
    assert client.get("/api/usage/stats?product=nope").status_code == 400
    assert client.get("/api/admin/downloads?product=nope", headers=ADMIN).status_code == 400


def test_admin_list_patch_and_hidden_visibility(client):
    rows = client.get("/api/admin/software", headers=ADMIN).json()
    heatflow = next(p for p in rows if p["slug"] == "heatflow")
    assert heatflow["downloads"] == 1
    assert heatflow["launches"] == 1
    assert heatflow["usage_pings"] == 1

    r = client.patch(
        "/api/admin/software/heatflow",
        headers=ADMIN,
        json={"status": "hidden", "blurb": "unlisted beta"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "hidden" and r.json()["blurb"] == "unlisted beta"

    # Hidden: off the public list, but telemetry keeps flowing (any status).
    public = client.get("/api/products/software").json()
    assert all(p["slug"] != "heatflow" for p in public)
    assert client.post(
        "/api/track/download", json={"product": "heatflow"}
    ).status_code == 200
    admin_rows = client.get("/api/admin/software", headers=ADMIN).json()
    assert next(p for p in admin_rows if p["slug"] == "heatflow")["downloads"] == 2


def test_software_admin_guards(client):
    assert client.get("/api/admin/software").status_code == 401  # no auth
    assert client.post(
        "/api/admin/software",
        headers=ADMIN,
        json={"slug": "heatflow", "name": "Duplicate"},
    ).status_code == 409
    assert client.patch(
        "/api/admin/software/ghost", headers=ADMIN, json={"name": "x"}
    ).status_code == 404


# -----------------------------------------------------------------------------
# B/C. Email log, segmented comms, course↔product link
# -----------------------------------------------------------------------------

def test_create_test_courses(client):
    for code, title, seats in (
        (COURSE_A, COURSE_A_TITLE, 10),
        (COURSE_B, "Other Cohort", 5),
    ):
        r = client.post(
            "/api/admin/courses",
            headers=ADMIN,
            json={"code": code, "title": title, "start_date": "2027-03-01",
                  "total_seats": seats},
        )
        assert r.status_code == 201, r.text
        assert r.json()["recorded_product_code"] is None


def test_applicant_confirmation_uses_course_title(client, resend):
    _register(client, "live-a@example.com", COURSE_A, company="Alpha Co")

    confirmation = next(
        c for c in resend
        if c["url"] == emailer.RESEND_URL and c["payload"]["to"] == ["live-a@example.com"]
    )
    assert COURSE_A_TITLE in confirmation["payload"]["html"]
    assert "Gas Turbine Emissions Mapping" not in confirmation["payload"]["html"]

    rows = _log_rows(recipient="live-a@example.com", template="applicant_confirmation")
    assert len(rows) == 1
    assert rows[0].ok is True
    assert rows[0].scope_kind == "course" and rows[0].scope_code == COURSE_A


def test_course_notify_batches_and_writes_email_log(client, resend):
    _register(client, "live-b-overlap@example.com", COURSE_A, company="Alpha Co")
    _register(client, "live-c@example.com", COURSE_A, company="Beta Co")

    r = client.post(
        f"/api/admin/courses/{COURSE_A}/notify",
        headers=ADMIN,
        json={"subject": "Venue update", "body_html": "<p>New venue.</p>",
              "audience": "all"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] == 3
    assert r.json()["failures"] == 0

    batches = [c for c in resend if c["url"] == emailer.RESEND_BATCH_URL]
    assert len(batches) == 1, "3 recipients must go out as one batch call"
    assert sorted(item["to"][0] for item in batches[0]["payload"]) == [
        "live-a@example.com", "live-b-overlap@example.com", "live-c@example.com",
    ]

    rows = _log_rows(scope_code=COURSE_A, template="broadcast", audience="all")
    assert len(rows) == 3
    assert all(row.ok and row.scope_kind == "course" for row in rows)
    assert {row.provider_id for row in rows} == {"batch-0", "batch-1", "batch-2"}


def test_batch_failure_falls_back_to_single_sends(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test_key")

    def flaky_post(url, payload, api_key):
        calls.append(url)
        if url == emailer.RESEND_BATCH_URL:
            return FakeResp(500, {"message": "batch exploded"})
        return FakeResp(200, {"id": "single-fallback"})

    monkeypatch.setattr(emailer, "_resend_post", flaky_post)

    r = client.post(
        f"/api/admin/courses/{COURSE_A}/notify",
        headers=ADMIN,
        json={"subject": "Fallback check", "body_html": "<p>hi</p>",
              "audience": "pending"},
    )
    assert r.status_code == 200
    assert r.json()["recipients"] == 3 and r.json()["failures"] == 0
    assert calls.count(emailer.RESEND_BATCH_URL) == 1
    assert calls.count(emailer.RESEND_URL) == 3

    rows = _log_rows(scope_code=COURSE_A, audience="pending")
    assert len(rows) == 3
    assert all(row.ok and row.provider_id == "single-fallback" for row in rows)


def test_stub_mode_returns_false_and_logs_failure():
    """RESEND_API_KEY unset: sends report failure (old code faked success)
    and the comms log records exactly what did not go out."""
    assert get_settings().RESEND_API_KEY == ""
    db = SessionLocal()
    try:
        ok = emailer.send_email(
            to="stub@example.com", subject="Stub", html="<p>x</p>",
            db=db, scope_kind="system", template="stub_check",
        )
        assert ok is False

        sent, failed = emailer.send_broadcast(
            db, ["stub2@example.com"], "Stub2", lambda _to: "<p>x</p>",
            scope={"scope_kind": "system", "template": "stub_check"},
        )
        assert sent == 0 and failed == ["stub2@example.com"]
    finally:
        db.close()

    rows = _log_rows(template="stub_check")
    assert [r.recipient for r in rows] == ["stub@example.com", "stub2@example.com"]
    assert all(r.ok is False and r.provider_id == "" for r in rows)


def test_comms_log_endpoint(client):
    assert client.get("/api/admin/comms/log").status_code == 401  # no auth

    body = client.get(
        f"/api/admin/comms/log?scope_code={COURSE_A}", headers=ADMIN
    ).json()
    assert body["count"] >= 6  # confirmations + broadcast + fallback rows
    assert all(row["scope_code"] == COURSE_A for row in body["rows"])
    ids = [row["id"] for row in body["rows"]]
    assert ids == sorted(ids, reverse=True), "newest first"
    expected_keys = {
        "id", "ts", "scope_kind", "scope_code", "audience", "template",
        "subject", "recipient", "ok", "provider_id",
    }
    assert set(body["rows"][0]) == expected_keys

    limited = client.get(
        f"/api/admin/comms/log?scope_code={COURSE_A}&limit=2", headers=ADMIN
    ).json()
    assert limited["count"] == 2 and len(limited["rows"]) == 2


def _seed_recorded_product() -> None:
    """An academy product with a spread of enrollment states:

    live-b-overlap@ (also a live registrant — proves dedup), rec-c@, rec-d@
    are live buyers; rec-e@ is revoked; rec-f@ is status='active' but expired
    (counts for revenue dashboards, never for comms).
    """
    db = SessionLocal()
    try:
        if db.get(Product, RECORDED) is None:
            db.add(Product(code=RECORDED, title="Recorded Counterpart"))
            db.flush()
        specs = [
            ("live-b-overlap@example.com", "active", None),
            ("rec-c@example.com", "active", None),
            ("rec-d@example.com", "active", None),
            ("rec-e@example.com", "revoked", None),
            ("rec-f@example.com", "active", datetime.utcnow() - timedelta(days=1)),
        ]
        for email, enr_status, expires in specs:
            learner = db.query(Learner).filter(Learner.email == email).one_or_none()
            if learner is None:
                learner = Learner(email=email, full_name="Rec Learner")
                db.add(learner)
                db.flush()
            db.add(
                Enrollment(
                    learner_id=learner.id,
                    product_code=RECORDED,
                    source="manual",
                    status=enr_status,
                    expires_at=expires,
                )
            )
        db.commit()
    finally:
        db.close()


def test_recorded_and_everyone_audiences(client, resend):
    _seed_recorded_product()

    r = client.patch(
        f"/api/admin/courses/{COURSE_A}",
        headers=ADMIN,
        json={"recorded_product_code": RECORDED},
    )
    assert r.status_code == 200
    assert r.json()["recorded_product_code"] == RECORDED

    # 'recorded' = live enrollees only: overlap + rec-c + rec-d.
    r = client.post(
        f"/api/admin/courses/{COURSE_A}/notify",
        headers=ADMIN,
        json={"subject": "Recorded news", "body_html": "<p>x</p>",
              "audience": "recorded"},
    )
    assert r.status_code == 200
    assert r.json()["recipients"] == 3
    recorded_rows = _log_rows(scope_code=COURSE_A, audience="recorded")
    assert sorted(row.recipient for row in recorded_rows) == [
        "live-b-overlap@example.com", "rec-c@example.com", "rec-d@example.com",
    ]

    # 'everyone' = live all (a, b-overlap, c) ∪ recorded (b-overlap, c, d),
    # deduped on the overlap.
    r = client.post(
        f"/api/admin/courses/{COURSE_A}/notify",
        headers=ADMIN,
        json={"subject": "Everyone news", "body_html": "<p>x</p>",
              "audience": "everyone"},
    )
    assert r.status_code == 200
    assert r.json()["recipients"] == 5
    everyone_rows = _log_rows(scope_code=COURSE_A, audience="everyone")
    assert len(everyone_rows) == 5
    assert len({row.recipient for row in everyone_rows}) == 5

    assert client.post(
        f"/api/admin/courses/{COURSE_A}/notify",
        headers=ADMIN,
        json={"subject": "x", "body_html": "<p>x</p>", "audience": "bogus"},
    ).status_code == 422


def test_product_notify_targets_buyers(client, resend):
    r = client.post(
        f"/api/admin/products/{RECORDED}/notify",
        headers=ADMIN,
        json={"subject": "New module posted", "body_html": "<p>x</p>"},
    )
    assert r.status_code == 200
    assert r.json()["recipients"] == 3

    rows = _log_rows(scope_code=RECORDED, audience="buyers")
    assert len(rows) == 3
    assert all(row.scope_kind == "product" and row.ok for row in rows)

    assert client.post(
        "/api/admin/products/ghost-product/notify",
        headers=ADMIN,
        json={"subject": "x", "body_html": "<p>x</p>"},
    ).status_code == 404


def test_recorded_product_code_validation_and_clearing(client):
    assert client.patch(
        f"/api/admin/courses/{COURSE_A}",
        headers=ADMIN,
        json={"recorded_product_code": "does-not-exist"},
    ).status_code == 400

    # Explicit null clears; omitting the field leaves the link untouched.
    r = client.patch(
        f"/api/admin/courses/{COURSE_A}",
        headers=ADMIN,
        json={"recorded_product_code": None},
    )
    assert r.status_code == 200 and r.json()["recorded_product_code"] is None
    r = client.patch(
        f"/api/admin/courses/{COURSE_A}", headers=ADMIN, json={"total_seats": 10}
    )
    assert r.json()["recorded_product_code"] is None

    r = client.patch(
        f"/api/admin/courses/{COURSE_A}",
        headers=ADMIN,
        json={"recorded_product_code": RECORDED},
    )
    assert r.json()["recorded_product_code"] == RECORDED
    assert client.get(f"/api/courses/{COURSE_A}").json()["recorded_product_code"] == RECORDED


# -----------------------------------------------------------------------------
# E. Unpinned admin registration routes
# -----------------------------------------------------------------------------

def test_admin_registrations_all_and_filtered(client):
    _register(client, "other-a@example.com", COURSE_B, company="Gamma LLC")

    rows = client.get("/api/admin/registrations", headers=ADMIN).json()
    codes = {row["course_code"] for row in rows}
    assert {COURSE_A, COURSE_B} <= codes, "unfiltered list spans courses"

    only_b = client.get(
        f"/api/admin/registrations?course={COURSE_B}", headers=ADMIN
    ).json()
    assert len(only_b) == 1
    assert only_b[0]["email"] == "other-a@example.com"
    assert only_b[0]["course_code"] == COURSE_B


def test_cross_course_mark_paid_and_cancel(client):
    reg_b = client.get(
        f"/api/admin/registrations?course={COURSE_B}", headers=ADMIN
    ).json()[0]

    # Pre-upgrade this 400'd ("belongs to a different cohort") because the
    # row's course != settings.COURSE_CODE.
    r = client.post(
        "/api/admin/mark-paid", headers=ADMIN,
        json={"registration_id": reg_b["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["registration"]["status"] == "paid"
    assert r.json()["registration"]["course_code"] == COURSE_B
    assert r.json()["taken"] == 1  # COURSE_B's own active count, not COURSE_A's

    # Idempotent re-mark.
    r = client.post(
        "/api/admin/mark-paid", headers=ADMIN,
        json={"registration_id": reg_b["id"]},
    )
    assert r.status_code == 200 and r.json()["taken"] == 1

    assert client.post(
        "/api/admin/mark-paid", headers=ADMIN, json={"registration_id": 9_999_999}
    ).status_code == 404

    reg_c = next(
        row for row in client.get(
            f"/api/admin/registrations?course={COURSE_A}", headers=ADMIN
        ).json()
        if row["email"] == "live-c@example.com"
    )
    r = client.post(
        "/api/admin/cancel", headers=ADMIN, json={"registration_id": reg_c["id"]}
    )
    assert r.status_code == 200
    assert r.json()["registration"]["status"] == "cancelled"
    assert r.json()["taken"] == 2  # live-a + live-b-overlap still hold seats


# -----------------------------------------------------------------------------
# D. Per-course + per-software stats
# -----------------------------------------------------------------------------

def _seed_orders_for_recorded() -> None:
    db = SessionLocal()
    try:
        db.add_all([
            Order(product_code=RECORDED, email="rec-c@example.com",
                  provider="manual", provider_ref="plat-ord-1", amount_cents=10_000,
                  status="paid", paid_at=datetime.utcnow()),
            Order(product_code=RECORDED, email="rec-d@example.com",
                  provider="manual", provider_ref="plat-ord-2", amount_cents=5_000,
                  status="paid", paid_at=datetime.utcnow() - timedelta(days=60)),
            Order(product_code=RECORDED, email="rec-e@example.com",
                  provider="manual", provider_ref="plat-ord-3", amount_cents=7_000,
                  status="pending"),
        ])
        db.commit()
    finally:
        db.close()


def test_stats_courses_shape_and_numbers(client):
    _seed_orders_for_recorded()

    body = client.get("/api/admin/stats/courses", headers=ADMIN).json()
    by_code = {row["code"]: row for row in body["courses"]}
    assert get_settings().COURSE_CODE in by_code  # legacy course listed too

    a = by_code[COURSE_A]
    assert set(a) == {"code", "title", "start_date", "status", "live", "recorded"}
    assert a["title"] == COURSE_A_TITLE and a["start_date"] == "2027-03-01"
    live = a["live"]
    assert live["pending"] == 2 and live["paid"] == 0 and live["cancelled"] == 1
    assert live["seats_total"] == 10 and live["seats_taken"] == 2
    assert sum(d["count"] for d in live["by_day"]) == 3  # all created today
    assert live["by_company"][0] == {"company": "Alpha Co", "count": 2}
    assert {"company": "Beta Co", "count": 1} in live["by_company"]

    # Recorded side reuses the academy dashboard's queries: status='active'
    # counts even when expired (rec-f), revoked (rec-e) never does.
    rec = a["recorded"]
    assert rec == {
        "orders_paid": 2,
        "revenue_cents_total": 15_000,
        "revenue_cents_30d": 10_000,
        "active_enrollments": 4,
        "learners_completed": 0,
    }

    b = by_code[COURSE_B]
    assert b["live"]["paid"] == 1 and b["live"]["pending"] == 0
    assert b["recorded"] is None  # no link -> null, not zeros


def test_stats_software_shape_and_numbers(client):
    body = client.get("/api/admin/stats/software", headers=ADMIN).json()
    by_slug = {row["slug"]: row for row in body["software"]}
    assert "pro3dworks" in by_slug  # hidden products still reported

    hf = by_slug["heatflow"]
    assert set(hf) == {"slug", "name", "downloads", "launches", "usage"}
    assert hf["downloads"] == {"total": 2, "last7": 2, "last30": 2}
    assert hf["launches"]["total"] == 1 and hf["launches"]["last7"] == 1
    assert hf["launches"]["by_version"] == [{"version": "1.0.0", "count": 1}]
    assert hf["usage"]["pings"] == 1
    assert hf["usage"]["total_minutes"] == 5
    assert hf["usage"]["top_features"] == [{"feature": "mesh", "count": 2}]

    # The pre-existing public launch/usage stats carry the same per-version
    # breakdown for any registry slug.
    launches = client.get("/api/launches/stats?product=heatflow").json()
    assert launches["by_version"] == [{"version": "1.0.0", "count": 1}]

    assert client.get("/api/admin/stats/software").status_code == 401
    assert client.get("/api/admin/stats/courses").status_code == 401
