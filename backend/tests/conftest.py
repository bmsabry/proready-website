"""Shared test bootstrap.

`get_settings()` is `lru_cache`d and the app builds its engine at import time,
so every environment variable has to be in place before *any* test module
imports `app.main`. pytest imports conftest first, which makes this the only
correct place to set them — doing it per-file means whichever module imports
first silently wins and the others run against its config.
"""
from __future__ import annotations

import os
import tempfile

_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)

ADMIN_TOKEN = "test-admin-token"
ADMIN_EMAIL = "admin@example.com"

os.environ.update(
    DATABASE_URL=f"sqlite:///{_DB_PATH}",
    SESSION_SECRET="test-admin-secret",
    LEARNER_SESSION_SECRET="test-learner-secret",
    COMPAT_JWT_SECRET="test-compat-secret",
    ADMIN_TOKEN=ADMIN_TOKEN,
    ADMIN_EMAIL=ADMIN_EMAIL,
    SITE_URL="https://proreadyengineer.com",
    RESEND_API_KEY="",  # emailer logs instead of sending
    IP_LOOKUP_ENABLED="false",  # no calls to ipapi.is from tests
)


# The course manifest no longer ships an examined-tier bank: the real one is
# loaded through the admin API and must never be committed to this public
# repository. The examined-tier tests run against this synthetic stand-in:
# 23 questions tagged to the seven MGT certificate competencies, key always B.
TEST_ADVANCED_PRODUCT = "micro-gas-turbine-design"
TEST_ADVANCED_BANK = {"C1": 4, "C2": 3, "C3": 3, "C4": 3, "C5": 3, "C6": 4, "C7": 3}


def _load_test_advanced_bank() -> None:
    from app.main import app  # noqa: F401  (import builds the schema and seeds the course)
    from app.db import SessionLocal
    from app.models import QuizItem

    db = SessionLocal()
    try:
        existing = db.query(QuizItem).filter(
            QuizItem.product_code == TEST_ADVANCED_PRODUCT, QuizItem.item_set == "advanced"
        ).count()
        if existing:
            return
        position = 0
        for competency, count in TEST_ADVANCED_BANK.items():
            for n in range(1, count + 1):
                position += 1
                db.add(QuizItem(
                    module_id=0, product_code=TEST_ADVANCED_PRODUCT, item_set="advanced",
                    code=f"{competency}-{n:02d}", position=position, kind="mcq",
                    outcome_id=competency, cognitive_level="Analyze",
                    stem=f"Synthetic {competency} question {n}",
                    options=[{"key": k, "text": f"Option {k}"} for k in "ABCD"],
                    answer={"key": "B"}, explanation="Synthetic test item.", rubric="",
                ))
        db.commit()
    finally:
        db.close()


_load_test_advanced_bank()


# The GT-05 module quiz is no longer shipped in this public repository either:
# production keeps it in the database. The tests run against a synthetic bank
# with the same shape — 41 formative MCQs in eight sections, and a summative
# set of 17 MCQs plus 9 rubric-graded short answers — key always B.
TEST_GT05_FORMATIVE = {1: 5, 2: 6, 3: 5, 4: 5, 5: 5, 6: 5, 7: 5, 8: 5}
TEST_GT05_SUMMATIVE_MCQ = {1: 2, 2: 3, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2, 9: 0}


def _load_test_gt05_bank() -> None:
    from app.db import SessionLocal
    from app.models import Module, QuizItem

    db = SessionLocal()
    try:
        module = db.query(Module).filter(
            Module.product_code == TEST_ADVANCED_PRODUCT, Module.code == "GT-05"
        ).one_or_none()
        if module is None or db.query(QuizItem).filter(QuizItem.module_id == module.id).count():
            return

        def add(code, item_set, kind, section, n):
            mcq = kind == "mcq"
            db.add(QuizItem(
                module_id=module.id, code=code, item_set=item_set, kind=kind,
                position=section * 100 + n, outcome_id=f"M{section}.O1", cognitive_level="Apply",
                stem=f"Synthetic GT-05 {item_set} item {code}: which statement holds?",
                options=[{"key": k, "text": f"Option {k} of {code}"} for k in "ABCD"] if mcq else [],
                answer={"key": "B"} if mcq else {},
                rubric="" if mcq else f"Rubric for {code}: 1 pt for the correct reasoning.",
                explanation=f"Synthetic explanation for {code}.",
            ))

        for section, count in TEST_GT05_FORMATIVE.items():
            for n in range(1, count + 1):
                add(f"F{section}.{n}", "formative", "mcq", section, n)
        for section, count in TEST_GT05_SUMMATIVE_MCQ.items():
            for n in range(1, count + 1):
                add(f"S{section}.{n}", "summative", "mcq", section, n)
            add(f"S{section}.{count + 1}", "summative", "short", section, count + 1)
        db.commit()
    finally:
        db.close()


_load_test_gt05_bank()
