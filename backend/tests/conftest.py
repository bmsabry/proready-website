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
)
