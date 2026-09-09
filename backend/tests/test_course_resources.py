"""Downloadable course resources: workbooks and handouts.

  * a stored non-HTML asset downloads under its real filename
  * a manifest 'handout' extra seeds as a 'reading' lesson
  * a manifest module can be gate-exempt (the Q&A section opens to everyone
    who is enrolled, wherever they are in the course)
"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import academy_seed
from app.db import SessionLocal
from app.main import app
from app.models import Lesson, Module, Product

from conftest import ADMIN_TOKEN

ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
PRODUCT = "resources-test-product"
STUDENT = "resources@example.com"


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _sign_in(email: str) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/admin/academy/login-link", json={"email": email, "send_email": False}, headers=ADMIN)
    token = r.json()["link"].split("token=")[1]
    assert c.post("/api/academy/auth/verify", json={"token": token}).status_code == 200
    me = c.get("/api/academy/me").json()
    c.post("/api/academy/accept-terms", json={"version": me["terms_version"]})
    return c


def test_a_workbook_downloads_under_its_own_filename(client):
    r = client.post("/api/admin/academy/products", headers=ADMIN, json={
        "code": PRODUCT, "title": "Resources", "status": "draft", "sequential_gate": False})
    assert r.status_code == 200, r.text
    mod = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", headers=ADMIN,
                      json={"code": "RS-01", "title": "Section", "position": 1}).json()
    r = client.post("/api/admin/academy/assets", headers=ADMIN, json={
        "key": "rs-calculator.xlsx", "filename": "design_calculator_v2.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "data_b64": base64.b64encode(b"PK\x03\x04 fake workbook").decode(),
    })
    assert r.status_code == 200, r.text
    lesson = client.post(f"/api/admin/academy/modules/{mod['module_id']}/lessons", headers=ADMIN, json={
        "code": "RS-01-X01", "title": "Design calculator (Excel)", "kind": "calculator", "position": 1,
        "asset_path": "blob:rs-calculator.xlsx",
    }).json()
    client.post("/api/admin/academy/grant", headers=ADMIN, json={
        "email": STUDENT, "product_code": PRODUCT, "send_email_invite": False})

    s = _sign_in(STUDENT)
    r = s.get(f"/api/academy/asset/{lesson['lesson_id']}")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="design_calculator_v2.xlsx"'
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert r.content == b"PK\x03\x04 fake workbook"
    assert "no-store" in r.headers["cache-control"]


def test_a_handout_extra_seeds_as_a_reading_lesson_in_a_gate_exempt_section():
    db = SessionLocal()
    try:
        product = db.get(Product, PRODUCT) or Product(code=PRODUCT, title="Resources")
        if product.code not in {p.code for p in db.query(Product).all()}:
            db.add(product)
            db.commit()
        module = academy_seed._seed_module(db, PRODUCT, {
            "code": "QA", "title": "Questions and Answers", "position": 9, "gate_exempt": True,
        })
        assert module.gate_exempt is True
        academy_seed._seed_lessons(db, module, {
            "extras": [{"kind": "handout", "label": "Questions and Answers handout", "filename": "qa.docx"}],
        })
        lesson = db.execute(select(Lesson).where(Lesson.module_id == module.id)).scalar_one()
        assert (lesson.code, lesson.kind, lesson.title, lesson.source_file) == (
            "QA-X00", "reading", "Questions and Answers handout", "qa.docx")
        # re-seeding without the flag keeps it honest: False, not "unchanged"
        module = academy_seed._seed_module(db, PRODUCT, {"code": "QA", "title": "Questions and Answers", "position": 9})
        assert module.gate_exempt is False
    finally:
        db.close()


def test_asset_content_type_column_fits_the_office_mime_types():
    # Postgres enforces the declared VARCHAR length; the .docx type is the
    # longest of the Office MIME types and used to overflow VARCHAR(64).
    from app.models import AssetBlob
    longest = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert AssetBlob.__table__.c.content_type.type.length >= len(longest)
