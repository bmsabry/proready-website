"""Idempotent seeding of academy content from bundled JSON.

Two data files ship with the app:

  data/course_manifest.json  — the product, its 7 modules, and the video
                               part list for each (derived from Bassam's
                               KSA jet-engine training library)
  data/gt05_quiz_items.json  — the signed-off GT-05 assessment bank

Seeding runs on every boot and is safe to repeat: rows are matched on their
natural keys (product code, module code, lesson code, item code) and updated
in place. Nothing a human edits later — a price change in the admin UI, a
`video_uid` written by the upload pipeline — is ever clobbered, because the
seeder only fills fields it owns and leaves operator-owned fields alone.

Deliberate non-goals: this is not a migration framework. If the manifest
shape changes materially, bump `_MANIFEST_VERSION` and handle it explicitly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Lesson, Module, Product, QuizItem

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
MANIFEST_PATH = DATA_DIR / "course_manifest.json"
QUIZ_PATH = DATA_DIR / "gt05_quiz_items.json"

# Which module the GT-05 assessment bank belongs to. The bank's own
# `module_position` values are positions *within GT-05's curriculum spine*,
# not positions in the product — mapping them here keeps that straight.
QUIZ_BANK_MODULE_CODE = "GT-05"

# The product ships as a draft. Flipping it live is an explicit admin action
# so a half-uploaded course can never become purchasable by accident.
DEFAULT_STATUS = "draft"


def _load(path: Path):
    if not path.exists():
        log.warning("Academy seed file missing: %s", path)
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _seed_product(db: Session, spec: dict) -> Product:
    product = db.get(Product, spec["code"])
    if product is None:
        product = Product(
            code=spec["code"],
            title=spec["title"],
            subtitle=spec.get("subtitle", ""),
            summary=spec.get("summary", ""),
            total_hours=float(spec.get("total_hours") or 0.0),
            status=DEFAULT_STATUS,
        )
        db.add(product)
        log.info("Seeded academy product %s", spec["code"])
    else:
        # Copy only descriptive fields. price_cents, stripe_price_id and
        # status belong to the admin from the moment the row exists.
        product.title = spec["title"]
        product.subtitle = spec.get("subtitle", "")
        product.summary = spec.get("summary", "")
        product.total_hours = float(spec.get("total_hours") or 0.0)
    db.commit()
    return product


def _seed_module(db: Session, product_code: str, spec: dict) -> Module:
    module = db.execute(
        select(Module).where(
            Module.product_code == product_code, Module.code == spec["code"]
        )
    ).scalar_one_or_none()
    if module is None:
        module = Module(product_code=product_code, code=spec["code"])
        db.add(module)
    module.title = spec["title"]
    module.summary = spec.get("summary", "")
    module.position = int(spec["position"])
    module.hours = float(spec.get("hours") or 0.0)
    module.objectives = list(spec.get("objectives") or [])
    module.topics = list(spec.get("topics") or [])
    module.quiz_app_url = spec.get("quiz_app_url", "")
    db.commit()
    db.refresh(module)
    return module


def _seed_lessons(db: Session, module: Module, spec: dict) -> None:
    """Create one lesson per video part, plus one per extra asset.

    `duration_s` is left at 0 and `video_uid` empty — both are filled by the
    upload pipeline once the files are in Cloudflare Stream. Seeding them as
    placeholders means the curriculum renders (and sells) before a single
    byte of video has been uploaded.
    """
    existing = {
        l.code: l
        for l in db.execute(
            select(Lesson).where(Lesson.module_id == module.id)
        ).scalars().all()
    }
    position = 0

    # A module's "parts" are upload-size splits of one continuous lecture, and
    # the upload pipeline collapses them into a single master once the video is
    # on Stream. From that point the manifest's part list is history: seeding it
    # again creates empty rows a learner can click and puts "Part 1" ahead of the
    # real lecture. That is not hypothetical — it happened to this course twice,
    # the second time silently, on the next deploy after the rows were cleared.
    # So if a master exists, leave the parts alone and give it position 1, which
    # also makes the extras number 2, 3, 4 instead of 12, 13, 14.
    master = next(
        (
            lesson
            for lesson in existing.values()
            if lesson.code.endswith("-LECTURE")
            or (lesson.kind == "video" and lesson.video_uid)
        ),
        None,
    )
    if master is not None:
        master.position = 1
        position = 1
    else:
        for index, filename in enumerate(spec.get("video_parts") or []):
            position += 1
            code = f"{module.code}-V{index:02d}"
            lesson = existing.get(code)
            if lesson is None:
                lesson = Lesson(module_id=module.id, code=code)
                db.add(lesson)
            lesson.title = f"{module.code} — Part {index + 1}"
            lesson.kind = "video"
            lesson.position = position
            lesson.source_file = filename
            # No lesson is ever published by seeding. This used to flag
            # "part 1 of module 2" as a free sample, which was safe only while
            # a lecture was 11 upload-sized parts and part 1 ran ~15 minutes.
            # Once the parts were collapsed into one master per module the same
            # flag sat on a full 175-minute lecture, and because
            # `lesson_accessible` short-circuits on `is_preview`, the API handed
            # a signed video token to anyone who asked for that lesson by id.
            # The course now has no free sample at all, by the owner's decision.

    _KIND_LABEL = {
        "deck": "Slide deck",
        "calculator": "Design calculator",
        "lab": "Interactive lab",
        "simulator": "Interactive simulator",
    }
    for index, extra in enumerate(spec.get("extras") or []):
        position += 1
        code = f"{module.code}-X{index:02d}"
        lesson = existing.get(code)
        if lesson is None:
            lesson = Lesson(module_id=module.id, code=code)
            db.add(lesson)
        kind = extra.get("kind", "deck")
        lesson.title = extra.get("label") or _KIND_LABEL.get(kind, "Resource")
        lesson.kind = "slides" if kind == "deck" else (
            "lab" if kind in ("lab", "simulator") else "calculator"
        )
        lesson.position = position
        lesson.source_file = extra.get("filename", "")

    if spec.get("quiz_app_url"):
        position += 1
        code = f"{module.code}-QUIZ"
        lesson = existing.get(code)
        if lesson is None:
            lesson = Lesson(module_id=module.id, code=code)
            db.add(lesson)
        lesson.title = f"{module.code} — Interactive quiz"
        lesson.kind = "quiz"
        lesson.position = position
        lesson.asset_path = spec["quiz_app_url"]

    db.commit()


def _seed_quiz_items(db: Session, product_code: str) -> int:
    items = _load(QUIZ_PATH)
    if not items:
        return 0
    module = db.execute(
        select(Module).where(
            Module.product_code == product_code,
            Module.code == QUIZ_BANK_MODULE_CODE,
        )
    ).scalar_one_or_none()
    if module is None:
        log.warning("Quiz bank target module %s missing", QUIZ_BANK_MODULE_CODE)
        return 0

    existing = {
        i.code: i
        for i in db.execute(
            select(QuizItem).where(QuizItem.module_id == module.id)
        ).scalars().all()
    }
    count = 0
    for spec in items:
        code = spec["code"]
        item = existing.get(code)
        if item is None:
            item = QuizItem(module_id=module.id, code=code)
            db.add(item)
        item.item_set = spec.get("item_set", "formative")
        item.kind = spec.get("kind", "mcq")
        item.stem = spec.get("stem", "")
        item.options = list(spec.get("options") or [])
        item.answer = dict(spec.get("answer") or {})
        item.rubric = spec.get("rubric", "")
        item.explanation = spec.get("explanation", "")
        item.cognitive_level = spec.get("cognitive_level", "")
        item.outcome_id = spec.get("outcome_id", "")
        # Order items across the whole bank: module spine position first,
        # then position within its set, so a single module's quiz reads in
        # the curriculum's intended sequence.
        item.position = int(spec.get("module_position", 0)) * 100 + int(
            spec.get("position", 0)
        )
        count += 1
    db.commit()
    return count


def _seed_certification(db: Session, product: Product, spec: dict) -> int:
    """Certificate copy (only when the operator has not set it) and the
    product-level advanced examination bank (idempotent by item code)."""
    cert_spec = spec.get("certification") or {}
    if cert_spec.get("descriptor") and not (product.certificate_descriptor or "").strip():
        product.certificate_descriptor = cert_spec["descriptor"]
    if cert_spec.get("competencies") and not (product.certificate_competencies or []):
        product.certificate_competencies = list(cert_spec["competencies"])
    db.commit()

    exam_file = cert_spec.get("advanced_exam_file")
    if not exam_file:
        return 0
    items = _load(DATA_DIR / exam_file)
    if not items:
        return 0
    existing = {
        i.code: i
        for i in db.execute(
            select(QuizItem).where(
                QuizItem.product_code == product.code, QuizItem.item_set == "advanced"
            )
        ).scalars().all()
    }
    count = 0
    for item_spec in items:
        code = item_spec["code"]
        item = existing.get(code)
        if item is None:
            item = QuizItem(module_id=0, product_code=product.code, code=code, item_set="advanced")
            db.add(item)
        item.kind = item_spec.get("kind", "mcq")
        item.stem = item_spec.get("stem", "")
        item.options = list(item_spec.get("options") or [])
        item.answer = dict(item_spec.get("answer") or {})
        item.rubric = item_spec.get("rubric", "")
        item.explanation = item_spec.get("explanation", "")
        item.cognitive_level = item_spec.get("cognitive_level", "")
        item.outcome_id = item_spec.get("outcome_id", "")
        item.position = int(item_spec.get("module_position", 0)) * 100 + int(
            item_spec.get("position", 0)
        )
        count += 1
    db.commit()
    return count


def seed_academy() -> None:
    """Entry point called once at app startup."""
    manifest = _load(MANIFEST_PATH)
    if not manifest:
        log.info("No academy manifest — skipping academy seed")
        return

    db: Session = SessionLocal()
    try:
        product = _seed_product(db, manifest["product"])
        for module_spec in manifest.get("modules", []):
            module = _seed_module(db, product.code, module_spec)
            _seed_lessons(db, module, module_spec)
        items = _seed_quiz_items(db, product.code)
        _seed_certification(db, product, manifest["product"])
        log.info(
            "Academy seed complete: product=%s modules=%d quiz_items=%d status=%s",
            product.code,
            len(manifest.get("modules", [])),
            items,
            product.status,
        )
    except Exception as exc:  # never let seeding take down the API
        log.error("Academy seed failed: %s", exc, exc_info=True)
        db.rollback()
    finally:
        db.close()
