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

    # --- Live-session reminders ------------------------------------------
    # The joining-instructions email goes to every confirmed registrant this
    # many minutes before each session day starts (course.day_dates at
    # course.session_time_utc). A Render cron job calls
    # POST /api/admin/session-reminders/run every 10 minutes with
    # X-Cron-Secret: CRON_SECRET; the admin token works there too.
    SESSION_REMINDER_LEAD_MINUTES: int = 60
    CRON_SECRET: str = ""

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
    # Links inside provisioning emails ("your course materials are ready",
    # purchase welcome, admin grant) live longer: people read those when
    # they get to them, not within half an hour. Still single-use.
    WELCOME_LINK_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 days
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

    # --- Certification ----------------------------------------------------
    # Base64 of the 32-byte Ed25519 seed every certificate is signed with.
    # NEVER rotate casually: all issued certificates verify against it.
    CERT_SIGNING_KEY: str = ""
    # Printed in the signature block of the instructor-examined tier and as
    # the course instructor on the completion tier.
    INSTRUCTOR_NAME: str = "Dr. Bassam Abdelnabi"
    INSTRUCTOR_CREDENTIALS: str = "Ph.D., Aerospace Engineering"
    INSTRUCTOR_TITLE: str = "Principal Consultant & Instructor, ProReadyEngineer LLC"
    # AssetBlob key holding the instructor's handwritten signature (PNG with
    # alpha). Uploaded through the admin assets endpoint, never committed —
    # the repository is public. The verified tier refuses to issue without it.
    INSTRUCTOR_SIGNATURE_ASSET_KEY: str = "instructor-signature.png"
    # Written examination of the paid tier: pass mark and attempt cap.
    ADVANCED_EXAM_THRESHOLD_PCT: float = 80.0
    ADVANCED_EXAM_MAX_ATTEMPTS: int = 2
    ADVANCED_INTERVIEW_MINUTES: int = 60
    # LinkedIn "Add to profile" pre-fill. The numeric Company Page id makes
    # the issuer show with the ProReadyEngineer logo; empty falls back to the
    # organisation name as text.
    LINKEDIN_ORGANIZATION_ID: str = ""

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
    # The host that served a copy is always treated as allowed for that copy
    # (AssetDelivery.origin_host), so this list only needs the *other* places
    # material may legitimately be opened from.
    ASSET_ALLOWED_HOSTS: str = (
        "proreadyengineer.com,www.proreadyengineer.com,"
        "proreadyengineer-training-api-jd9a.onrender.com,"
        "proready-website.pages.dev,localhost,127.0.0.1"
    )
    # Absolute URL the beacon posts to. Left empty, it is derived per-request
    # from the URL the asset itself was served on, which is correct in every
    # environment including local dev.
    ASSET_BEACON_URL: str = ""

    # --- Asset run-lock ---------------------------------------------------
    # When on, the scripts inside an HTML asset are encrypted per copy at
    # serve time and the copy has to fetch its key from this API before it
    # can run (app/asset_lock.py). A saved file is inert; a copy that is
    # revoked, expired, or opened by another account gets no key.
    ASSET_LOCK_ENABLED: bool = True
    # How long a served copy may keep unlocking itself before the learner
    # has to launch a fresh one from the course page.
    ASSET_COPY_TTL_HOURS: int = 24
    # Reloads a single copy may perform inside its TTL. Generous for real
    # use (a reload per minute for an hour); tight against a script that
    # hammers the key endpoint.
    ASSET_KEY_MAX_FETCHES: int = 60
    # Launches per learner per 24 h beyond which an alert is sent. A person
    # launches a simulator a handful of times a day; a harvester does not.
    ASSET_LAUNCH_ALERT_PER_DAY: int = 8
    # Where integrity alerts go. Empty = ADMIN_NOTIFY_EMAIL.
    INTEGRITY_ALERT_EMAIL: str = ""

    # --- Server-side simulator engine (app/sim_runtime.py) ----------------
    # The engine bundle lives in academy_asset_blobs under this key; it is
    # never in the repository. The thin client connects over a WebSocket on
    # the API origin and only ever receives frames.
    SIM_ENGINE_ASSET_KEY: str = "sim-engine.js"
    SIM_MAX_SESSIONS: int = 60
    SIM_MAX_PER_LEARNER: int = 3
    SIM_IDLE_SECONDS: int = 20 * 60
    SIM_TICK_SECONDS: float = 0.25
    SIM_MAX_SPEED: int = 30
    # Control messages per second one session may send before it is slowed.
    SIM_OPS_PER_SECOND: int = 40

    # --- Automatic simulator deployment (app/deploy_auth.py) ---------------
    # A GitHub Actions run in the simulator's PRIVATE repository may upload
    # the two simulator blobs and reload the engine. It proves who it is with
    # GitHub's OIDC token (no shared secret anywhere): the token must be
    # issued for this repository and branch and for our audience. Empty repo
    # = the deployer identity is switched off. SIM_DEPLOY_TOKEN is an optional
    # static fallback for a machine that cannot mint OIDC tokens.
    SIM_DEPLOY_GITHUB_REPO: str = ""
    SIM_DEPLOY_GITHUB_REF: str = "refs/heads/main"
    SIM_DEPLOY_AUDIENCE: str = "proreadyengineer-sim-deploy"
    SIM_DEPLOY_TOKEN: str = ""
    # The only blob keys the deployer may write.
    SIM_DEPLOY_ASSET_KEYS: str = "prodlemappingsim-thin.html,sim-engine.js"

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
