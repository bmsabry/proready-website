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
    # Single shared bearer token (server-to-server / curl escape hatch).
    # Rotate by changing the env var on Render.
    ADMIN_TOKEN: str = ""

    # Email + password login for the admin UI. Only one admin is recognised;
    # only requests where the login email matches ADMIN_EMAIL (case-insensitive)
    # are even considered. ADMIN_PASSWORD_HASH is a bcrypt hash of the current
    # password. SESSION_SECRET signs the httpOnly session cookie.
    ADMIN_EMAIL: str = "bmsabry@gmail.com"
    ADMIN_PASSWORD_HASH: str = ""
    SESSION_SECRET: str = ""
    SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 7  # 7 days

    # --- Academy (self-serve on-demand courses) ---------------------------
    # Public site root — used to build magic-link URLs and Stripe redirect
    # targets. No trailing slash.
    SITE_URL: str = "https://proreadyengineer.com"

    # Learner sessions are separate from the admin session in every way:
    # different cookie, different signing salt, different lifetime. A leaked
    # learner cookie must never grant admin access.
    LEARNER_SESSION_SECRET: str = ""
    LEARNER_SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 30  # 30 days
    # How long a sign-in link stays valid before it must be re-requested.
    LOGIN_LINK_TTL_SECONDS: int = 60 * 30  # 30 minutes
    # Sign-in links are rate limited per email to blunt inbox flooding.
    LOGIN_LINK_MAX_PER_HOUR: int = 5

    # Owner override. Any learner whose (verified) email is listed here is
    # treated as enrolled in everything and flagged is_staff. Safe because an
    # email only becomes a session after a magic link is received, or after a
    # password is set on that address — a stranger typing it gets nothing.
    OWNER_EMAILS: str = "bmsabry@gmail.com"

    @property
    def owner_emails_list(self) -> List[str]:
        return [e.strip().lower() for e in self.OWNER_EMAILS.split(",") if e.strip()]

    # Mastery gate: percentage required on a module's formative set before
    # the next module unlocks. Per the GT-05 curriculum sign-off.
    MASTERY_THRESHOLD_PCT: float = 80.0

    # Click-wrap terms document version. Bump this string when the training
    # terms/liability notice changes materially — every learner is then asked
    # to accept the new version before opening protected material again.
    TERMS_VERSION: str = "2026-08-v2"

    # --- Legacy quiz-app compatibility ------------------------------------
    # The five standalone smallgasturbine.gt-XX apps speak an email+password
    # JWT contract that used to be served by the combustion-toolkit API. We
    # reimplement that contract here so those apps point at this service and
    # the toolkit can stay switched off for good.
    COMPAT_JWT_SECRET: str = ""
    COMPAT_ACCESS_TOKEN_MINUTES: int = 60 * 24
    COMPAT_REFRESH_TOKEN_DAYS: int = 30
    # Which academy product an enrolment in it unlocks the legacy modules for.
    # One purchase of the course opens all five quiz apps.
    COMPAT_PRODUCT_CODE: str = "micro-gas-turbine-design"

    # --- Payments (Stripe Checkout) ---------------------------------------
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # --- Payments (PayPal Orders v2) --------------------------------------
    # Credentials land later; until both are set every PayPal endpoint
    # degrades to 503 and /api/payments/config reports paypal_enabled=False.
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_MODE: str = "live"  # 'live' | 'sandbox'
    PAYPAL_CURRENCY: str = "USD"

    @property
    def paypal_enabled(self) -> bool:
        return bool(self.PAYPAL_CLIENT_ID and self.PAYPAL_CLIENT_SECRET)

    @property
    def paypal_base_url(self) -> str:
        return (
            "https://api-m.sandbox.paypal.com"
            if self.PAYPAL_MODE == "sandbox"
            else "https://api-m.paypal.com"
        )

    # --- Video (Cloudflare Stream) ----------------------------------------
    # Customer subdomain code, e.g. "abcd1234" in
    # https://customer-abcd1234.cloudflarestream.com
    CF_STREAM_CUSTOMER_CODE: str = ""
    CF_ACCOUNT_ID: str = ""
    CF_API_TOKEN: str = ""
    # Signing key pair from POST /stream/keys — the JWK is base64-encoded.
    CF_STREAM_SIGNING_KEY_ID: str = ""
    CF_STREAM_SIGNING_KEY_JWK: str = ""
    # Playback tokens are deliberately short-lived; the player refreshes.
    STREAM_TOKEN_TTL_SECONDS: int = 60 * 60 * 2  # 2 hours

    # --- Asset provenance -------------------------------------------------
    # Hostnames the protected material is legitimately served from. A
    # call-home ping carrying any other host — or a file:// path — is
    # reported as `offsite`, which is the clearest leak signal there is.
    ASSET_ALLOWED_HOSTS: str = (
        "proreadyengineer.com,www.proreadyengineer.com,"
        "api.proreadyengineer.com,proready-api.onrender.com,"
        "proready-website.pages.dev,localhost,127.0.0.1"
    )
    # Absolute URL the beacon posts to. Left empty, it is derived per-request
    # from the URL the asset itself was served on, which is correct in every
    # environment including local dev.
    ASSET_BEACON_URL: str = ""

    @property
    def asset_allowed_hosts_set(self) -> set:
        return {
            h.strip().lower()
            for h in self.ASSET_ALLOWED_HOSTS.split(",")
            if h.strip()
        }

    # --- CORS -------------------------------------------------------------
    # Comma-separated origins. In prod: https://proreadyengineer.com
    # The five smallgasturbine.* quiz-app origins must be listed here too;
    # they call /auth and /learning cross-origin with a Bearer token.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
