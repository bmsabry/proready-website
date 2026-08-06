"""AI assistant platform-tools coverage.

Exercises the tool registry and the handlers directly (no LLM involved):
registry/spec parity, explicit course scoping on list_registrations, the
cross-domain find_person aggregation, high-stakes gating for the new write
tools, and the stat/read tool shapes. Handlers are called with a raw
SessionLocal session, exactly how routes/ai.py invokes them.

Shares the session-wide throwaway SQLite DB with the other test modules,
so every code/slug/email here is unique to this file.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

import conftest  # noqa: F401  — env vars must be set before app imports
from fastapi.testclient import TestClient

from app import ai_tools
from app.db import SessionLocal
from app.main import app
from app.models import (
    AppLaunch,
    AppUsage,
    Course,
    EmailLog,
    Enrollment,
    Learner,
    Lesson,
    Module,
    Order,
    Product,
    ProductDownload,
    Registration,
    SoftwareProduct,
)

COURSE_X = "ai-tools-course-x-2027"
COURSE_Y = "ai-tools-course-y-2027"
PRODUCT = "ai-tools-recorded-prod"
SOFT_SLUG = "ai-tools-soft"
PERSON = "ai.person@example.com"
GRANTEE = "ai.granted@example.com"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(scope="module")
def seeded(client):
    """One fixed cross-domain scenario: two cohorts, a recorded product with
    content, one person who exists in every domain, and a hidden software
    product with telemetry."""
    db = SessionLocal()
    try:
        db.add(
            Course(
                code=COURSE_X,
                title="AI Tools Cohort X",
                start_date=date(2027, 5, 3),
                total_seats=10,
                recorded_product_code=PRODUCT,
            )
        )
        db.add(
            Course(
                code=COURSE_Y,
                title="AI Tools Cohort Y",
                start_date=date(2027, 6, 7),
                total_seats=10,
            )
        )
        db.add(Product(code=PRODUCT, title="AI Tools Recorded", price_cents=49_900, status="live"))
        db.commit()

        module = Module(product_code=PRODUCT, code="AIT-01", title="Module One", position=1)
        db.add(module)
        db.commit()
        db.refresh(module)
        db.add(
            Lesson(
                module_id=module.id,
                code="AIT-01-L1",
                title="Intro",
                position=0,
                kind="video",
                video_uid="uid-ai-1",
                duration_s=600,
                is_preview=True,
            )
        )
        db.add(
            Lesson(
                module_id=module.id,
                code="AIT-01-L2",
                title="Deep dive",
                position=1,
                kind="video",
                video_uid="",
                duration_s=0,
            )
        )

        common = dict(
            full_name="Person One",
            job_title="Engineer",
            company="Aero Co",
            years_experience="5-10",
            location="Riyadh",
        )
        db.add(Registration(course_code=COURSE_X, email=PERSON, status="paid", **common))
        # Mixed-case email on the second cohort — find_person must still match.
        db.add(Registration(course_code=COURSE_Y, email="AI.Person@Example.com", status="pending", **common))

        learner = Learner(email=PERSON, full_name="Person One")
        db.add(learner)
        db.commit()
        db.refresh(learner)
        db.add(Enrollment(learner_id=learner.id, product_code=PRODUCT, status="active", source="manual"))
        db.add(
            Order(
                learner_id=learner.id,
                product_code=PRODUCT,
                email=PERSON,
                provider="stripe",
                provider_ref="ai-tools-order-1",
                amount_cents=49_900,
                currency="usd",
                status="paid",
                paid_at=datetime.now(timezone.utc),
            )
        )

        db.add(SoftwareProduct(slug=SOFT_SLUG, name="AI Tools Soft", status="hidden"))
        db.add(ProductDownload(product=SOFT_SLUG))
        db.add(AppLaunch(product=SOFT_SLUG, version="1.0.0"))
        db.add(AppUsage(product=SOFT_SLUG, version="1.0.0", minutes=5, features='{"mesh": 2}'))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db(client, seeded):
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _spec(name: str) -> dict:
    return next(s["function"] for s in ai_tools.TOOL_SPECS if s["function"]["name"] == name)


# -----------------------------------------------------------------------------
# Registry completeness
# -----------------------------------------------------------------------------

def test_every_spec_has_a_handler_and_vice_versa():
    spec_names = [s["function"]["name"] for s in ai_tools.TOOL_SPECS]
    assert len(spec_names) == len(set(spec_names)), "duplicate tool spec names"
    assert set(spec_names) == set(ai_tools.TOOL_HANDLERS)
    for name, handler in ai_tools.TOOL_HANDLERS.items():
        assert callable(handler), name


def test_high_stakes_tools_are_registered():
    known = set(ai_tools.TOOL_HANDLERS)
    assert ai_tools.HIGH_STAKES_ALWAYS <= known
    assert ai_tools.HIGH_STAKES_BULK_TOOLS <= known


# -----------------------------------------------------------------------------
# list_registrations — explicit course scoping
# -----------------------------------------------------------------------------

def test_list_registrations_schema_requires_course_code():
    assert "course_code" in _spec("list_registrations")["parameters"]["required"]


def test_list_registrations_handler_errors_without_course_code(db):
    out = ai_tools.list_registrations(db)
    assert out["ok"] is False
    assert "course_code" in out["error"]


def test_list_registrations_rejects_unknown_course(db):
    out = ai_tools.list_registrations(db, course_code="no-such-course-2099")
    assert out["ok"] is False
    assert "not found" in out["error"]


def test_list_registrations_all_spans_courses_with_row_codes(db):
    out = ai_tools.list_registrations(db, course_code="all", limit=500)
    assert out["ok"] is True and out["course_code"] == "all"
    codes = {r["course_code"] for r in out["registrations"]}
    assert {COURSE_X, COURSE_Y} <= codes
    json.dumps(out)


def test_list_registrations_single_course_still_filters(db):
    out = ai_tools.list_registrations(db, course_code=COURSE_Y)
    assert out["ok"] is True
    assert {r["course_code"] for r in out["registrations"]} == {COURSE_Y}


def test_mark_paid_and_cancel_report_course_code(db):
    reg = Registration(
        course_code=COURSE_Y,
        full_name="Flip Me",
        email="ai.flip@example.com",
        job_title="Engineer",
        company="Flip Co",
        years_experience="0-2",
        location="Dammam",
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)

    out = ai_tools.mark_paid(db, reg.id, notes="wire received")
    assert out["ok"] is True and out["course_code"] == COURSE_Y
    assert out["already_paid"] is False
    assert out["registration"]["status"] == "paid"

    # Idempotent replay via the shared mark_registration_paid helper.
    again = ai_tools.mark_paid(db, reg.id)
    assert again["ok"] is True and again["already_paid"] is True

    out = ai_tools.cancel(db, reg.id)
    assert out["ok"] is True and out["course_code"] == COURSE_Y
    assert out["registration"]["status"] == "cancelled"


# -----------------------------------------------------------------------------
# find_person — cross-domain aggregation
# -----------------------------------------------------------------------------

def test_find_person_aggregates_across_domains(db):
    out = ai_tools.find_person(db, email="AI.Person@Example.com")
    assert out["ok"] is True and out["found"] is True

    assert {r["course_code"] for r in out["registrations"]} == {COURSE_X, COURSE_Y}
    assert out["learner"]["email"] == PERSON
    assert any(
        e["product_code"] == PRODUCT and e["status"] == "active"
        for e in out["enrollments"]
    )
    assert any(
        o["product_code"] == PRODUCT and o["status"] == "paid" and o["amount_cents"] == 49_900
        for o in out["orders"]
    )
    json.dumps(out)  # must be JSON-safe for the tool-result message


def test_find_person_unknown_email(db):
    out = ai_tools.find_person(db, email="nobody.ai@example.com")
    assert out["ok"] is True and out["found"] is False
    assert out["registrations"] == [] and out["learner"] is None
    assert out["enrollments"] == [] and out["orders"] == []


# -----------------------------------------------------------------------------
# High-stakes gating
# -----------------------------------------------------------------------------

def test_new_write_tools_are_always_high_stakes():
    hs = ai_tools.is_high_stakes
    assert hs("notify_product_buyers", {"product_code": PRODUCT, "subject": "s", "body": "b"})
    assert hs("grant_enrollment", {"email": GRANTEE, "product_code": PRODUCT})
    assert hs("revoke_enrollment", {"email": GRANTEE, "product_code": PRODUCT})
    assert hs("update_lesson", {"lesson_id": 1, "fields": {"title": "t"}})
    assert hs("notify_course", {"code": COURSE_X, "subject": "s", "body": "b"})


def test_bulk_threshold_unchanged():
    hs = ai_tools.is_high_stakes
    assert hs("bulk_mark_paid", {"registration_ids": [1, 2, 3]})
    assert not hs("bulk_mark_paid", {"registration_ids": [1, 2]})


def test_read_tools_are_not_high_stakes():
    hs = ai_tools.is_high_stakes
    for name in (
        "list_registrations",
        "get_course_stats",
        "get_software_stats",
        "list_software",
        "list_learners",
        "get_email_log",
        "list_course_content",
        "find_person",
    ):
        assert not hs(name, {}), name


def test_update_software_status_high_stakes_blurb_not():
    hs = ai_tools.is_high_stakes
    assert hs("update_software", {"slug": SOFT_SLUG, "fields": {"status": "hidden"}})
    assert hs("update_software", {"slug": SOFT_SLUG, "fields": {"blurb": "x", "status": "live"}})
    assert not hs("update_software", {"slug": SOFT_SLUG, "fields": {"blurb": "New blurb"}})
    assert not hs("update_software", {"slug": SOFT_SLUG, "fields": {"name": "N", "latest_version": "2.0"}})


def test_summaries_for_new_high_stakes_tools_are_readable():
    s = ai_tools.summarize_call("grant_enrollment", {"email": GRANTEE, "product_code": PRODUCT})
    assert GRANTEE in s and PRODUCT in s
    s = ai_tools.summarize_call("notify_product_buyers", {"product_code": PRODUCT, "subject": "Hi"})
    assert PRODUCT in s and "Hi" in s
    s = ai_tools.summarize_call("update_software", {"slug": SOFT_SLUG, "fields": {"status": "hidden"}})
    assert SOFT_SLUG in s and "status" in s


# -----------------------------------------------------------------------------
# Stats + read tools
# -----------------------------------------------------------------------------

def test_get_course_stats_shape(db):
    out = ai_tools.get_course_stats(db, course_code=COURSE_X)
    assert out["ok"] is True and len(out["courses"]) == 1
    row = out["courses"][0]
    assert set(row) == {"code", "title", "start_date", "status", "live", "recorded"}
    live = row["live"]
    assert set(live) == {
        "pending", "paid", "cancelled", "seats_total", "seats_taken", "by_day", "by_company",
    }
    assert live["paid"] >= 1 and live["seats_total"] == 10
    # Linked recorded product reports the academy revenue headline.
    rec = row["recorded"]
    assert rec["orders_paid"] >= 1 and rec["active_enrollments"] >= 1
    assert rec["revenue_cents_total"] >= 49_900
    json.dumps(out)


def test_get_course_stats_all_and_unlinked_course(db):
    out = ai_tools.get_course_stats(db)
    by_code = {c["code"]: c for c in out["courses"]}
    assert COURSE_X in by_code and COURSE_Y in by_code
    assert by_code[COURSE_Y]["recorded"] is None  # no recorded twin -> null

    missing = ai_tools.get_course_stats(db, course_code="no-such-course-2099")
    assert missing["ok"] is False


def test_get_software_stats_shape(db):
    out = ai_tools.get_software_stats(db, slug=SOFT_SLUG)
    assert out["ok"] is True and len(out["software"]) == 1
    row = out["software"][0]
    assert set(row) == {"slug", "name", "downloads", "launches", "usage"}
    assert row["downloads"]["total"] == 1
    assert row["launches"]["total"] == 1
    assert row["launches"]["by_version"] == [{"version": "1.0.0", "count": 1}]
    assert row["usage"]["pings"] == 1 and row["usage"]["total_minutes"] == 5
    assert row["usage"]["top_features"] == [{"feature": "mesh", "count": 2}]
    json.dumps(out)

    assert ai_tools.get_software_stats(db, slug="no-such-soft")["ok"] is False


def test_list_software_includes_hidden(db):
    out = ai_tools.list_software(db)
    row = next(s for s in out["software"] if s["slug"] == SOFT_SLUG)
    assert row["status"] == "hidden"
    assert row["downloads"] == 1 and row["launches"] == 1 and row["usage_pings"] == 1
    json.dumps(out)


def test_list_learners_query_filter(db):
    out = ai_tools.list_learners(db, query="ai.person")
    assert out["ok"] is True and out["count"] >= 1
    assert all("ai.person" in l["email"] for l in out["learners"])
    me = next(l for l in out["learners"] if l["email"] == PERSON)
    assert any(
        e["product_code"] == PRODUCT and e["status"] == "active" for e in me["enrollments"]
    )
    json.dumps(out)

    assert ai_tools.list_learners(db, product_code="no-such-prod")["ok"] is False


def test_list_course_content_tree(db):
    out = ai_tools.list_course_content(db, product_code=PRODUCT)
    assert out["ok"] is True and out["product"]["code"] == PRODUCT
    mod = next(m for m in out["modules"] if m["code"] == "AIT-01")
    lessons = {l["title"]: l for l in mod["lessons"]}
    assert lessons["Intro"]["video_ready"] is True and lessons["Intro"]["is_preview"] is True
    assert lessons["Deep dive"]["video_ready"] is False
    assert set(lessons["Intro"]) == {
        "id", "title", "kind", "position", "duration_s", "video_ready", "is_preview",
    }
    json.dumps(out)

    assert ai_tools.list_course_content(db, product_code="no-such-prod")["ok"] is False


# -----------------------------------------------------------------------------
# Write tools — executed directly (approval gating is routes/ai.py's job)
# -----------------------------------------------------------------------------

def test_grant_then_revoke_enrollment(db):
    out = ai_tools.grant_enrollment(db, email=GRANTEE, product_code=PRODUCT, full_name="Granted Person")
    assert out["ok"] is True and out["product_code"] == PRODUCT

    learner = db.query(Learner).filter_by(email=GRANTEE).one()
    enr = db.query(Enrollment).filter_by(learner_id=learner.id, product_code=PRODUCT).one()
    assert enr.status == "active" and enr.source == "manual"

    missing = ai_tools.grant_enrollment(db, email=GRANTEE, product_code="no-such-prod")
    assert missing["ok"] is False

    out = ai_tools.revoke_enrollment(db, email=GRANTEE, product_code=PRODUCT)
    assert out["ok"] is True
    db.refresh(enr)
    assert enr.status == "revoked"


def test_update_lesson_fields_and_rejects_unknown(db):
    lesson = db.query(Lesson).filter_by(code="AIT-01-L2").one()
    out = ai_tools.update_lesson(db, lesson.id, {"title": "Deep dive II", "position": 5, "is_preview": True})
    assert out["ok"] is True and sorted(out["changed_fields"]) == ["is_preview", "position", "title"]
    db.refresh(lesson)
    assert lesson.title == "Deep dive II" and lesson.position == 5 and lesson.is_preview is True

    assert ai_tools.update_lesson(db, lesson.id, {"video_uid": "nope"})["ok"] is False
    assert ai_tools.update_lesson(db, lesson.id, {})["ok"] is False
    assert ai_tools.update_lesson(db, 999_999, {"title": "x"})["ok"] is False


def test_update_software_blurb(db):
    out = ai_tools.update_software(db, SOFT_SLUG, {"blurb": "Updated by assistant", "latest_version": "1.1.0"})
    assert out["ok"] is True
    assert out["software"]["blurb"] == "Updated by assistant"
    assert out["software"]["latest_version"] == "1.1.0"
    assert out["software"]["status"] == "hidden"  # untouched

    assert ai_tools.update_software(db, SOFT_SLUG, {"asset_path": "/x"})["ok"] is False
    assert ai_tools.update_software(db, "no-such-soft", {"blurb": "x"})["ok"] is False


def test_notify_product_buyers_writes_email_log(db):
    """Stub mode (no RESEND_API_KEY): sends report failure but every attempt
    still lands in the email log via the shared broadcast path."""
    before = db.query(EmailLog).filter_by(scope_code=PRODUCT).count()
    out = ai_tools.notify_product_buyers(db, PRODUCT, "Course update", "New module is up.\n\nEnjoy!")
    assert out["ok"] is True
    # Only ai.person holds active access (grantee was revoked above).
    assert out["failed_addresses"] == [PERSON]

    log = ai_tools.get_email_log(db, scope_code=PRODUCT)
    assert log["ok"] is True and log["count"] == before + 1
    row = log["emails"][0]
    assert row["scope_kind"] == "product" and row["audience"] == "buyers"
    assert row["recipient"] == PERSON
    json.dumps(log)

    assert ai_tools.notify_product_buyers(db, "no-such-prod", "s", "b")["ok"] is False
