"""Runtime configuration loaded from environment variables.

All settings are optional at import time so tests and local dev don't
require a fully populated .env. Validation happens at first use.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---------------------------------------------------------
    # Default: on-disk SQLite file for local dev. In Render, set to the
    # Postgres URL from the managed-db Internal Connection String.
    DATABASE_URL: str = "sqlite:///./proready.db"

    # --- Cohort -----------------------------------------------------------
    COURSE_CAPACITY: int = 15
    COURSE_CODE: str = "gas-turbine-emissions-mapping-2026-05"
    COHORT_LABEL: str = "May 15, 2026"

    # --- Email (Resend) ---------------------------------------------------
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "ProReadyEngineer <info@proreadyengineer.com>"
    EMAIL_REPLY_TO: str = "info@proreadyengineer.com"
    ADMIN_NOTIFY_EMAIL: str = "bmsabry@gmail.com"

    # Payment instructions embedded in the confirmation email.
    # Bassam can override per-cohort via env without code changes.
    PAYMENT_INSTRUCTIONS: str = (
        "We'll send a Stripe Payment Link and a PayPal invoice "
        "to this email address within 24 hours. Your seat is held "
        "as pending until payment clears."
    )
    COURSE_PRICE_DISPLAY: str = ""  # e.g. "$1,950 USD". Empty = omit from email.

    # --- Admin auth -------------------------------------------------------
    # Single shared bearer token. Rotate by changing the env var on Render.
    ADMIN_TOKEN: str = ""

    # --- CORS -------------------------------------------------------------
    # Comma-separated origins. In prod: https://proreadyengineer.com
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
