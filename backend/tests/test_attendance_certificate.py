"""The Certificate of Attendance — the moderator-issued tier.

Issued from the Registrations tab for a paid live-cohort seat; it records
presence, lists the topics, and carries contact hours / PDH — but attests no
competency (that is the completion and examined tiers).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import conftest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Certificate, Course, Learner, Product, Registration

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "micro-gas-turbine-design"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _cohort_and_registration(email: str, *, status: str = "paid", linked: bool = True) -> int:
    """A live cohort linked to the product (or not) and one registration on it."""
    db = SessionLocal()
    try:
        code = f"att-cohort-{email.split('@')[0]}"
        course = Course(
            code=code,
            title="Live MGT Cohort",
            start_date=date(2026, 11, 2),
            day_dates=["2026-11-02", "2026-11-03", "2026-11-06"],
            recorded_product_code=PRODUCT if linked else None,
        )
        db.add(course)
        reg = Registration(
            course_code=code, full_name="Ada Attendee", email=email, job_title="Engineer",
            company="ACME", years_experience="10", location="Cairo", status=status,
            paid_at=datetime.now(timezone.utc) if status == "paid" else None,
        )
        db.add(reg)
        db.commit()
        return reg.id
    finally:
        db.close()


def test_marking_a_paid_seat_attended_issues_the_certificate():
    c = _client()
    rid = _cohort_and_registration("attend.paid@example.com")
    r = c.post("/api/admin/mark-attended", headers=ADMIN,
               json={"registration_id": rid, "send_email": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transitioned"] is True
    assert body["certificate_code"].startswith("PRE-A-")
    assert body["registration"]["attended_at"] is not None

    # The certificate is a real, signed attendance row with the cohort span.
    db = SessionLocal()
    try:
        cert = db.query(Certificate).filter(Certificate.code == body["certificate_code"]).one()
        assert cert.tier == "attendance"
        assert cert.status == "issued"
        assert str(cert.cohort_start) == "2026-11-02" and str(cert.cohort_end) == "2026-11-06"
        assert cert.competencies  # the topic outline, not empty
    finally:
        db.close()

    # Public verification reports it as a Certificate of Attendance.
    v = c.get(f"/api/academy/verify/{body['certificate_code']}").json()
    assert v["valid"] is True and v["tier"] == "attendance"
    assert v["title"] == "Certificate of Attendance"
    # Attendance is not instructor-attested, so no instructor is named.
    assert v["instructor"] == ""


def test_marking_attended_is_idempotent():
    c = _client()
    rid = _cohort_and_registration("attend.twice@example.com")
    first = c.post("/api/admin/mark-attended", headers=ADMIN,
                   json={"registration_id": rid, "send_email": False}).json()
    again = c.post("/api/admin/mark-attended", headers=ADMIN,
                   json={"registration_id": rid, "send_email": False}).json()
    assert again["transitioned"] is False
    assert again["certificate_code"] == first["certificate_code"]


def test_an_unpaid_seat_cannot_be_marked_attended():
    c = _client()
    rid = _cohort_and_registration("attend.pending@example.com", status="pending")
    r = c.post("/api/admin/mark-attended", headers=ADMIN,
               json={"registration_id": rid, "send_email": False})
    assert r.status_code == 409
    assert "paid" in r.json()["detail"].lower()


def test_a_cohort_with_no_linked_product_cannot_certify_attendance():
    c = _client()
    rid = _cohort_and_registration("attend.noproduct@example.com", linked=False)
    r = c.post("/api/admin/mark-attended", headers=ADMIN,
               json={"registration_id": rid, "send_email": False})
    assert r.status_code == 409
    assert "product" in r.json()["detail"].lower()


def test_withdrawing_attendance_revokes_the_certificate():
    c = _client()
    rid = _cohort_and_registration("attend.withdraw@example.com")
    issued = c.post("/api/admin/mark-attended", headers=ADMIN,
                    json={"registration_id": rid, "send_email": False}).json()
    code = issued["certificate_code"]
    r = c.post("/api/admin/mark-attended", headers=ADMIN,
               json={"registration_id": rid, "attended": False})
    assert r.status_code == 200, r.text
    assert r.json()["registration"]["attended_at"] is None
    v = c.get(f"/api/academy/verify/{code}").json()
    assert v["valid"] is False and v["status"] == "revoked"


def test_admin_can_preview_an_attendance_specimen():
    c = _client()
    r = c.get(f"/api/admin/academy/certification/{PRODUCT}/sample.pdf?tier=attendance", headers=ADMIN)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"


def test_the_learner_sees_a_held_attendance_certificate():
    email = "attend.learner@example.com"
    rid = _cohort_and_registration(email)
    admin = _client()
    admin.post("/api/admin/mark-attended", headers=ADMIN,
               json={"registration_id": rid, "send_email": False})
    # A grant so the learner can open the course, then sign in.
    admin.post("/api/admin/academy/grant", headers=ADMIN,
               json={"email": email, "product_code": PRODUCT, "send_email_invite": False})
    s = _client()
    link = admin.post("/api/admin/academy/login-link", headers=ADMIN,
                      json={"email": email, "send_email": False}).json()["link"]
    s.post("/api/academy/auth/verify", json={"token": link.split("token=")[1]})
    me = s.get("/api/academy/me").json()
    s.post("/api/academy/accept-terms", json={"version": me["terms_version"]})
    payload = s.get(f"/api/academy/certification/{PRODUCT}").json()
    assert payload["attendance"]["certificate"] is not None
    assert payload["attendance"]["certificate"]["tier"] == "attendance"
    assert payload["name_locked"] is True
