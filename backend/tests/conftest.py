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
