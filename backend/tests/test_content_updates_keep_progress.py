"""Updating course material never erases what a trainee has done.

Bassam, 2026-09-06: "when I update the course materials (presentations, add
videos or whatsoever) it does not erase the trainee progress or quiz
takings — it simply overwrites the materials — across the whole website."

Every content path the platform has is exercised here against a learner
with real history, and the history is compared before and after:

  * module / lesson re-upload (same codes, new titles)  — ids kept
  * deck re-upload, shorter and longer                    — completion kept
  * recording replaced (new Stream uid, new chapters)     — watch state kept
  * question bank reloaded with `replace`                 — attempts, pass, gate kept
  * a bonus video lesson survives a re-ingest             — untouched
  * legacy part-lessons collapse into the master          — progress folded, not dropped
  * the guard itself: nothing can delete history, or a lesson/module that has it
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import progress_guard
from app.db import SessionLocal
from app.main import app
from app.models import (
    Chapter, Learner, Lesson, LessonProgress, Module, ModuleState, Product, QuizAttempt,
    QuizItem, Slide, SlideImage,
)

from conftest import ADMIN_TOKEN

ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
PRODUCT = "keep-progress-product"
STUDENT = "keeper@example.com"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _sign_in(email: str) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/admin/academy/login-link", json={"email": email, "send_email": False}, headers=ADMIN)
    token = r.json()["link"].split("token=")[1]
    assert c.post("/api/academy/auth/verify", json={"token": token}).status_code == 200
    me = c.get("/api/academy/me").json()
    c.post("/api/academy/accept-terms", json={"version": me["terms_version"]})
    return c


def _bank(n: int = 5) -> list[dict]:
    return [
        {
            "code": f"Q{i}", "item_set": "formative", "kind": "mcq", "stem": f"Question {i}?",
            "options": [{"key": "A", "text": "yes"}, {"key": "B", "text": "no"}],
            "answer": {"key": "A"}, "position": i,
        }
        for i in range(1, n + 1)
    ]


@pytest.fixture()
def world(client, db):
    """A product with one module (video + deck + bank), and a learner with history on all of it."""
    with progress_guard.allow_progress_loss("test fixture reset"):
        for mid in db.execute(select(Module.id).where(Module.product_code == PRODUCT)).scalars().all():
            lids = db.execute(select(Lesson.id).where(Lesson.module_id == mid)).scalars().all()
            db.execute(delete(LessonProgress).where(LessonProgress.lesson_id.in_(lids)))
            db.execute(delete(Chapter).where(Chapter.lesson_id.in_(lids)))
            db.execute(delete(QuizAttempt).where(QuizAttempt.module_id == mid))
            db.execute(delete(QuizItem).where(QuizItem.module_id == mid))
            db.execute(delete(Slide).where(Slide.module_id == mid))
            db.execute(delete(SlideImage).where(SlideImage.module_id == mid))
            db.execute(delete(Lesson).where(Lesson.module_id == mid))
            db.execute(delete(Module).where(Module.id == mid))
        db.execute(delete(ModuleState).where(ModuleState.module_id == "kp-01"))
        db.commit()

    r = client.post("/api/admin/academy/products", headers=ADMIN, json={
        "code": PRODUCT, "title": "Keep Progress", "status": "draft", "sequential_gate": True,
    })
    assert r.status_code == 200, r.text
    mod = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", headers=ADMIN, json={
        "code": "KP-01", "title": "Module one", "position": 1,
    }).json()
    mod2 = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", headers=ADMIN, json={
        "code": "KP-02", "title": "Module two", "position": 2,
    }).json()
    video = client.post(f"/api/admin/academy/modules/{mod['module_id']}/lessons", headers=ADMIN, json={
        "code": "KP-01-LECTURE", "title": "Lecture", "kind": "video", "position": 1, "duration_s": 600,
    }).json()
    deck = client.post(f"/api/admin/academy/modules/{mod['module_id']}/lessons", headers=ADMIN, json={
        "code": "KP-01-X00", "title": "Slide deck", "kind": "slides", "position": 2,
    }).json()
    client.post(f"/api/admin/academy/modules/{mod2['module_id']}/lessons", headers=ADMIN, json={
        "code": "KP-02-X00", "title": "Deck two", "kind": "slides", "position": 1,
    })
    r = client.post(f"/api/admin/academy/modules/{mod['module_id']}/slides", headers=ADMIN, json={
        "slides": [{"number": i, "title": f"Slide {i}", "image_lg_b64": PNG, "image_sm_b64": PNG} for i in range(1, 11)],
    })
    assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/academy/modules/{mod['module_id']}/quiz-items", headers=ADMIN, json={"items": _bank()})
    assert r.status_code == 200, r.text
    client.post("/api/admin/academy/grant", headers=ADMIN, json={
        "email": STUDENT, "product_code": PRODUCT, "send_email_invite": False,
    })

    s = _sign_in(STUDENT)
    # watched 4 of 10 minutes of the lecture
    for _ in range(4):
        r = s.post(f"/api/academy/lesson/{video['lesson_id']}/progress", json={"position_s": 240, "watched_delta_s": 60})
        assert r.status_code == 200, r.text
    # read the whole deck
    r = s.post(f"/api/academy/lesson/{deck['lesson_id']}/progress", json={"position_s": 10, "watched_delta_s": 5})
    assert r.status_code == 200 and r.json()["completed"] is True, r.text
    # passed the formative
    items = s.get(f"/api/academy/quiz/{mod['module_id']}/formative").json()["items"]
    r = s.post(f"/api/academy/quiz/{mod['module_id']}/formative", json={"responses": {i["code"]: "A" for i in items}})
    assert r.status_code == 200 and r.json()["passed"] is True, r.text
    # quiz-app state blob
    learner = db.execute(select(Learner).where(Learner.email == STUDENT)).scalar_one()
    db.add(ModuleState(learner_id=learner.id, module_id="kp-01", payload={"score": 91, "done": ["a", "b"]}))
    db.commit()

    return {"module_id": mod["module_id"], "module2_id": mod2["module_id"], "video_id": video["lesson_id"],
            "deck_id": deck["lesson_id"], "learner_id": learner.id, "student": s}


def _snapshot(db, w) -> dict:
    db.expire_all()
    prog = {
        p.lesson_id: (p.position_s, p.watched_s, p.completed_at is not None)
        for p in db.execute(select(LessonProgress).where(
            LessonProgress.learner_id == w["learner_id"])).scalars().all()
    }
    attempts = [
        (a.module_id, a.item_set, a.score_pct, a.passed, dict(a.responses))
        for a in db.execute(select(QuizAttempt).where(QuizAttempt.learner_id == w["learner_id"])
                            .order_by(QuizAttempt.id)).scalars().all()
    ]
    state = db.execute(select(ModuleState).where(
        ModuleState.learner_id == w["learner_id"], ModuleState.module_id == "kp-01")).scalar_one()
    return {"progress": prog, "attempts": attempts, "state": dict(state.payload)}


def _course(s) -> dict:
    return s.get(f"/api/academy/course/{PRODUCT}").json()


# ----- re-uploading the same structure -------------------------------------

def test_reuploading_modules_and_lessons_keeps_ids_and_history(client, db, world):
    before = _snapshot(db, world)
    m = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", headers=ADMIN, json={
        "code": "KP-01", "title": "Module one, revised", "position": 1, "summary": "new summary",
    }).json()
    assert m["created"] is False and m["module_id"] == world["module_id"]
    v = client.post(f"/api/admin/academy/modules/{world['module_id']}/lessons", headers=ADMIN, json={
        "code": "KP-01-LECTURE", "title": "Lecture (v2)", "kind": "video", "position": 1, "duration_s": 600,
    }).json()
    assert v["created"] is False and v["lesson_id"] == world["video_id"]
    assert _snapshot(db, world) == before
    course = _course(world["student"])
    assert course["modules"][0]["title"] == "Module one, revised"
    assert course["modules"][1]["unlocked"] is True  # the pass still opens module two


# ----- decks ------------------------------------------------------------------

def test_a_shorter_deck_replaces_the_old_one_and_keeps_completion(client, db, world):
    before = _snapshot(db, world)
    r = client.post(f"/api/admin/academy/modules/{world['module_id']}/slides", headers=ADMIN, json={
        "slides": [{"number": i, "title": f"New slide {i}", "image_lg_b64": PNG, "image_sm_b64": PNG} for i in range(1, 7)],
        "total": 6,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "module_id": world["module_id"], "slides_total": 6, "slides_pruned": 4}
    assert db.execute(select(SlideImage).where(SlideImage.module_id == world["module_id"], SlideImage.number > 6)).first() is None
    assert _snapshot(db, world) == before
    detail = world["student"].get(f"/api/academy/lesson/{world['deck_id']}").json()
    assert len(detail["slides"]) == 6 and detail["slides"][0]["title"] == "New slide 1"
    assert detail["progress"]["completed"] is True


def test_a_longer_deck_keeps_the_learner_complete(client, db, world):
    before = _snapshot(db, world)
    r = client.post(f"/api/admin/academy/modules/{world['module_id']}/slides", headers=ADMIN, json={
        "slides": [{"number": i, "title": f"Slide {i}", "image_lg_b64": PNG, "image_sm_b64": PNG} for i in range(1, 16)],
        "total": 15,
    })
    assert r.status_code == 200 and r.json()["slides_total"] == 15
    assert _snapshot(db, world) == before
    detail = world["student"].get(f"/api/academy/lesson/{world['deck_id']}").json()
    assert detail["progress"]["completed"] is True  # completion is earned once, never revoked by an edit


# ----- recordings --------------------------------------------------------------

def test_replacing_the_recording_keeps_watch_state_and_leaves_other_videos_alone(client, db, world):
    bonus = client.post(f"/api/admin/academy/modules/{world['module_id']}/lessons", headers=ADMIN, json={
        "code": "KP-01-BONUS", "title": "Bonus demo", "kind": "video", "position": 3, "duration_s": 120,
    }).json()
    s = world["student"]
    assert s.post(f"/api/academy/lesson/{bonus['lesson_id']}/progress", json={"position_s": 30, "watched_delta_s": 30}).status_code == 200
    before = _snapshot(db, world)

    r = client.post("/api/admin/academy/modules/KP-01/ingest", headers=ADMIN, json={
        "video_uid": "new-stream-uid", "duration_s": 900, "replace": True,
        "chapters": [{"title": "Intro", "start_s": 0, "end_s": 300, "slides": [1]},
                     {"title": "Main", "start_s": 300, "end_s": 900, "slides": [2, 3]}],
        "slides": [],
    })
    assert r.status_code == 200, r.text
    assert r.json()["lesson_id"] == world["video_id"]
    assert r.json()["part_lessons_removed"] == 0 and r.json()["progress_rows_migrated"] == 0
    assert _snapshot(db, world) == before
    assert db.get(Lesson, bonus["lesson_id"]) is not None
    detail = s.get(f"/api/academy/lesson/{world['video_id']}").json()
    assert detail["progress"]["position_s"] == 240 and detail["progress"]["watched_s"] == 240
    assert [c["title"] for c in detail["chapters"]] == ["Intro", "Main"]


def test_a_shorter_replacement_recording_restarts_instead_of_seeking_past_the_end(client, db, world):
    before = _snapshot(db, world)
    r = client.patch(f"/api/admin/academy/lessons/{world['video_id']}", headers=ADMIN, json={"duration_s": 200})
    assert r.status_code == 200, r.text
    assert _snapshot(db, world) == before  # the stored position is untouched
    detail = world["student"].get(f"/api/academy/lesson/{world['video_id']}").json()
    assert detail["progress"]["position_s"] == 0 and detail["progress"]["watched_s"] == 240


def test_legacy_part_lessons_fold_their_progress_into_the_master(client, db, world):
    # A course seeded as upload-size parts, watched by a learner, then ingested.
    mid = world["module2_id"]
    parts = [
        client.post(f"/api/admin/academy/modules/{mid}/lessons", headers=ADMIN, json={
            "code": f"KP-02-V0{i}", "title": f"Part {i + 1}", "kind": "video", "position": i + 1, "duration_s": 300,
        }).json()["lesson_id"]
        for i in range(2)
    ]
    s = world["student"]
    for lid in parts:
        for _ in range(5):  # the whole 300 s of each part
            assert s.post(f"/api/academy/lesson/{lid}/progress", json={"position_s": 300, "watched_delta_s": 60}).status_code == 200
    db.expire_all()
    assert all(db.execute(select(LessonProgress).where(LessonProgress.lesson_id == lid)).scalar_one().completed_at for lid in parts)

    r = client.post("/api/admin/academy/modules/KP-02/ingest", headers=ADMIN, json={
        "video_uid": "master-uid", "duration_s": 600, "replace": True, "chapters": [], "slides": [],
    })
    assert r.status_code == 200, r.text
    assert r.json()["part_lessons_removed"] == 1 and r.json()["progress_rows_migrated"] == 1
    master = db.get(Lesson, r.json()["lesson_id"])
    assert master.code == "KP-02-LECTURE"
    db.expire_all()
    prog = db.execute(select(LessonProgress).where(
        LessonProgress.learner_id == world["learner_id"], LessonProgress.lesson_id == master.id)).scalar_one()
    assert prog.watched_s == 600 and prog.completed_at is not None
    # nothing else the learner did was touched
    assert db.execute(select(LessonProgress).where(
        LessonProgress.learner_id == world["learner_id"], LessonProgress.lesson_id == world["video_id"])).scalar_one().watched_s == 240


# ----- question banks ------------------------------------------------------------

def test_reloading_the_question_bank_keeps_attempts_and_the_pass(client, db, world):
    before = _snapshot(db, world)
    r = client.post(f"/api/admin/academy/modules/{world['module_id']}/quiz-items", headers=ADMIN, json={
        "items": _bank(8), "replace": True,
    })
    assert r.status_code == 200 and r.json()["items_total"] == 8
    assert _snapshot(db, world) == before
    course = _course(world["student"])
    assert course["modules"][1]["unlocked"] is True
    items = world["student"].get(f"/api/academy/quiz/{world['module_id']}/formative").json()["items"]
    assert len(items) == 8


# ----- the guard ---------------------------------------------------------------

def test_nothing_can_delete_history_or_the_rows_it_hangs_from(db, world):
    with pytest.raises(progress_guard.ProgressLossBlocked):
        db.execute(delete(LessonProgress).where(LessonProgress.learner_id == world["learner_id"]))
    db.rollback()
    with pytest.raises(progress_guard.ProgressLossBlocked):
        db.execute(delete(QuizAttempt))
    db.rollback()
    with pytest.raises(progress_guard.ProgressLossBlocked):
        db.execute(delete(Lesson).where(Lesson.id == world["video_id"]))
    db.rollback()
    with pytest.raises(progress_guard.ProgressLossBlocked):
        db.delete(db.get(Lesson, world["video_id"]))
        db.flush()
    db.rollback()
    with pytest.raises(progress_guard.ProgressLossBlocked):
        db.delete(db.get(Module, world["module_id"]))
        db.flush()
    db.rollback()
    with pytest.raises(progress_guard.ProgressLossBlocked):
        db.delete(db.get(Product, PRODUCT))
        db.flush()
    db.rollback()
    with pytest.raises(progress_guard.ProgressLossBlocked):
        row = db.execute(select(QuizAttempt).where(QuizAttempt.learner_id == world["learner_id"])).scalars().first()
        db.delete(row)
        db.flush()
    db.rollback()
    # everything is still there
    db.expire_all()
    assert db.execute(select(LessonProgress).where(LessonProgress.learner_id == world["learner_id"])).scalars().all()
    assert db.execute(select(QuizAttempt).where(QuizAttempt.learner_id == world["learner_id"])).scalars().all()


def test_a_lesson_nobody_has_touched_can_still_be_removed(client, db, world):
    spare = client.post(f"/api/admin/academy/modules/{world['module_id']}/lessons", headers=ADMIN, json={
        "code": "KP-01-SPARE", "title": "Never opened", "kind": "reading", "position": 9,
    }).json()
    db.delete(db.get(Lesson, spare["lesson_id"]))
    db.commit()
    assert db.get(Lesson, spare["lesson_id"]) is None


def test_the_escape_hatch_is_explicit(db, world):
    with pytest.raises(ValueError):
        with progress_guard.allow_progress_loss("  "):
            pass
    with progress_guard.allow_progress_loss("test: proving the hatch works"):
        db.execute(delete(ModuleState).where(ModuleState.module_id == "kp-01"))
        db.commit()
    assert db.execute(select(ModuleState).where(ModuleState.module_id == "kp-01")).first() is None
