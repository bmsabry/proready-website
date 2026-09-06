"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text

from .academy_seed import seed_academy
from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import Course, SoftwareProduct
from .routes import academy as academy_routes
from .routes import academy_admin as academy_admin_routes
from .routes import certification as certification_routes
from .routes import certification_admin as certification_admin_routes
from .routes import admin as admin_routes
from .routes import ai as ai_routes
from .routes import auth as auth_routes
from .routes import checkout as checkout_routes
from .routes import comms as comms_routes
from .routes import compat as compat_routes
from .routes import courses as courses_routes
from .routes import downloads as downloads_routes
from .routes import interest as interest_routes
from .routes import payments as payments_routes
from .routes import register as register_routes
from .routes import reminders as reminders_routes
from .routes import seats as seats_routes
from .routes import sim as sim_routes
from .routes import software as software_routes
from .routes import stats as stats_routes
from .routes import support as support_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


def _register_gate_handler(application: FastAPI) -> None:
    """Serialize a sequential-gate refusal so old and new clients both cope.

    Body: {"detail": "<readable sentence>", "gate": {…structured…}}. A client
    that only knows `detail` shows a proper message; the current UI reads
    `gate` and links straight to the evaluation that unlocks the section.
    """
    from fastapi.responses import JSONResponse

    from .routes.academy import GateLocked

    @application.exception_handler(GateLocked)
    async def _gate_locked_handler(request, exc: GateLocked):  # noqa: ANN001
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "gate": exc.blocker},
        )

settings = get_settings()

# Create tables on startup. Safe for a single-table schema; swap to
# Alembic if the model grows.
Base.metadata.create_all(bind=engine)


def _ensure_column(table: str, column: str, ddl: str) -> None:
    """Add `column` to an existing `table` if it isn't there yet.

    create_all() does NOT alter existing tables, so when we ship a new
    column to a DB that already has the table (Render Postgres), we have
    to migrate manually. This helper is idempotent — it inspects the
    current schema and only ALTERs when the column is missing. Brand-new
    tables need nothing: create_all makes them with every column.
    """
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return  # create_all just made it with the column already
    cols = {c["name"] for c in inspector.get_columns(table)}
    if column in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    log.info("Migrated: added %s.%s column", table, column)


def _run_column_migrations() -> None:
    # courses.day_dates — the JSON default needs a ::json cast on Postgres
    # but not on SQLite's TEXT-backed JSON.
    if engine.dialect.name == "postgresql":
        _ensure_column("courses", "day_dates", "JSON NOT NULL DEFAULT '[]'::json")
    else:
        _ensure_column("courses", "day_dates", "JSON NOT NULL DEFAULT '[]'")
    # courses.recorded_product_code — nullable link to the academy Product
    # that carries this course's recorded counterpart.
    _ensure_column("courses", "recorded_product_code", "VARCHAR(64)")
    # academy_products.sequential_gate — False = cohort mode (admin grants
    # decide access; daily evaluations don't lock the next module).
    _ensure_column(
        "academy_products", "sequential_gate", "BOOLEAN NOT NULL DEFAULT TRUE"
    )
    # academy_slides.video_asset — AssetBlob key of a movie embedded on the
    # slide; the viewer swaps the still image for a gated player.
    _ensure_column(
        "academy_slides", "video_asset", "VARCHAR(128) NOT NULL DEFAULT ''"
    )
    # academy_modules.gate_exempt — support modules (simulator, resources)
    # sit outside the sequential chain.
    _ensure_column(
        "academy_modules", "gate_exempt", "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    # courses price — online seat price for live cohorts (0 = invoice-only).
    _ensure_column("courses", "price_cents", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column("courses", "currency", "VARCHAR(8) NOT NULL DEFAULT 'usd'")
    # registrations payment audit trail (PayPal/Stripe live-cohort payments).
    _ensure_column(
        "registrations", "payment_provider", "VARCHAR(16) NOT NULL DEFAULT ''"
    )
    _ensure_column("registrations", "payment_ref", "VARCHAR(128) NOT NULL DEFAULT ''")
    _ensure_column("registrations", "amount_cents", "INTEGER")
    # academy_enrollments settlement tracking (ACH delayed-notification).
    _ensure_column(
        "academy_enrollments",
        "settlement_status",
        "VARCHAR(16) NOT NULL DEFAULT 'settled'",
    )
    _ensure_column(
        "academy_enrollments", "settlement_deadline", "TIMESTAMP WITH TIME ZONE"
    )
    # Asset provenance. These tables ship new, but a column added to them in a
    # LATER release still needs migrating — create_all made the table on the
    # first deploy and will never touch it again. Shipping origin_host without
    # this line 500'd the simulator in production for ten minutes.
    _ensure_column(
        "academy_asset_deliveries", "origin_host", "VARCHAR(200) NOT NULL DEFAULT ''"
    )
    _ensure_column(
        "academy_asset_pings", "reviewed_at", "TIMESTAMP WITH TIME ZONE"
    )
    _ensure_column(
        "academy_asset_pings", "reviewed_note", "VARCHAR(300) NOT NULL DEFAULT ''"
    )
    # Run-lock (2026-09): per-copy key, revocation and key-fetch counters.
    _ensure_column(
        "academy_asset_deliveries", "key_b64", "VARCHAR(64) NOT NULL DEFAULT ''"
    )
    _ensure_column(
        "academy_asset_deliveries", "revoked_at", "TIMESTAMP WITH TIME ZONE"
    )
    _ensure_column(
        "academy_asset_deliveries", "revoke_reason", "VARCHAR(200) NOT NULL DEFAULT ''"
    )
    _ensure_column(
        "academy_asset_deliveries", "key_fetches", "INTEGER NOT NULL DEFAULT 0"
    )
    _ensure_column(
        "academy_asset_deliveries", "key_denied", "INTEGER NOT NULL DEFAULT 0"
    )
    _ensure_column(
        "academy_asset_deliveries", "last_key_at", "TIMESTAMP WITH TIME ZONE"
    )
    # Support desk. support_tickets/_messages/_events are brand-new tables,
    # so create_all builds them complete — but ai_settings already exists in
    # production and needs the two new columns added by hand.
    #   scope   — 'assistant' (the admin chat) vs 'support' (the desk). The
    #             existing row predates the column and must become
    #             'assistant', which the DEFAULT gives us.
    #   kb_text — admin-authored facts the auto-replier may state.
    _ensure_column(
        "ai_settings", "scope", "VARCHAR(16) NOT NULL DEFAULT 'assistant'"
    )
    _ensure_column("ai_settings", "kb_text", "TEXT NOT NULL DEFAULT ''")
    # registrations.attendance_confirmed_at — set when a registrant replies
    # to confirm their seat; null means they have not answered yet.
    _ensure_column(
        "registrations", "attendance_confirmed_at", "TIMESTAMP WITH TIME ZONE"
    )
    # courses session time — empty string means "not set"; the assistant is
    # told to ask rather than invent a time of day.
    _ensure_column("courses", "session_time_utc", "VARCHAR(5) NOT NULL DEFAULT ''")
    _ensure_column(
        "courses", "session_duration_minutes", "INTEGER NOT NULL DEFAULT 0"
    )
    # Joining instructions for the live sessions (2026-09). Empty = no
    # meeting set, so the reminder job leaves the course alone.
    _ensure_column("courses", "meeting_info", "TEXT NOT NULL DEFAULT ''")
    # Certification tiers (2026-09). academy_advanced_certifications is a new
    # table (create_all builds it complete); the columns below land on tables
    # that already exist in production.
    json_empty_list = "'[]'::json" if engine.dialect.name == "postgresql" else "'[]'"
    _ensure_column("academy_products", "certificate_descriptor", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        "academy_products", "certificate_competencies",
        f"JSON NOT NULL DEFAULT {json_empty_list}",
    )
    _ensure_column(
        "academy_products", "advanced_cert_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    _ensure_column(
        "academy_products", "advanced_cert_price_cents", "INTEGER NOT NULL DEFAULT 30000"
    )
    _ensure_column("academy_orders", "kind", "VARCHAR(16) NOT NULL DEFAULT 'course'")
    _ensure_column("academy_quiz_items", "product_code", "VARCHAR(64) NOT NULL DEFAULT ''")
    _ensure_column("academy_quiz_attempts", "product_code", "VARCHAR(64) NOT NULL DEFAULT ''")
    for column, ddl in [
        ("tier", "VARCHAR(16) NOT NULL DEFAULT 'completion'"),
        ("status", "VARCHAR(16) NOT NULL DEFAULT 'issued'"),
        ("revoke_reason", "VARCHAR(300) NOT NULL DEFAULT ''"),
        ("course_title", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("signature_b64", "TEXT NOT NULL DEFAULT ''"),
        ("signature_fingerprint", "VARCHAR(24) NOT NULL DEFAULT ''"),
        ("pdf_sha256", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("pdf_key", "VARCHAR(128) NOT NULL DEFAULT ''"),
        ("preview_key", "VARCHAR(128) NOT NULL DEFAULT ''"),
        ("exam_date", "DATE"),
        ("exam_minutes", "INTEGER NOT NULL DEFAULT 0"),
        ("competencies", f"JSON NOT NULL DEFAULT {json_empty_list}"),
        ("email_sent_at", "TIMESTAMP WITH TIME ZONE"),
    ]:
        _ensure_column("academy_certificates", column, ddl)


_run_column_migrations()


# Default day-by-day schedule for the legacy Gas Turbine course. Admins
# can override these any time via PATCH /api/admin/courses/{code}.
_DEFAULT_GAS_TURBINE_DAY_DATES = [
    "2026-05-16",
    "2026-05-17",
    "2026-05-23",
    "2026-05-24",
    "2026-05-30",
]


def _seed_default_course() -> None:
    """Ensure the legacy Gas Turbine Emissions Mapping course row exists.

    The Course table is new; existing Registration rows already reference
    settings.COURSE_CODE. Without this seed, the public /api/courses/{code}
    endpoint would 404 on first boot after the Course table lands.

    Also backfills day_dates for the seeded course if the row already exists
    but predates the day_dates column (i.e. came in as []). We never overwrite
    a non-empty admin-set list.
    """
    db = SessionLocal()
    try:
        existing = db.execute(
            select(Course).where(Course.code == settings.COURSE_CODE)
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                Course(
                    code=settings.COURSE_CODE,
                    title="Gas Turbine Emissions Mapping",
                    start_date=date(2026, 5, 15),
                    total_seats=settings.COURSE_CAPACITY,
                    status="open",
                    day_dates=list(_DEFAULT_GAS_TURBINE_DAY_DATES),
                )
            )
            db.commit()
            log.info("Seeded default course %s", settings.COURSE_CODE)
        elif not existing.day_dates:
            existing.day_dates = list(_DEFAULT_GAS_TURBINE_DAY_DATES)
            db.commit()
            log.info(
                "Backfilled day_dates on existing course %s",
                settings.COURSE_CODE,
            )
    finally:
        db.close()


_seed_default_course()


def _seed_software_products() -> None:
    """Ensure the software registry knows about Pro3DWorks.

    The registry replaces the old hardcoded KNOWN_PRODUCTS whitelist in
    routes/downloads.py; without this seed, telemetry from Pro3DWorks
    builds already in the wild would start 400ing after deploy. Idempotent
    — never overwrites admin edits to an existing row.
    """
    db = SessionLocal()
    try:
        existing = db.execute(
            select(SoftwareProduct).where(SoftwareProduct.slug == "pro3dworks")
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                SoftwareProduct(
                    slug="pro3dworks",
                    name="Pro3DWorks",
                    asset_path="/downloads/Pro3DWorks.html",
                    latest_version="2.53.2",
                )
            )
            db.commit()
            log.info("Seeded software product pro3dworks")
    finally:
        db.close()


_seed_software_products()

# Academy content (products/modules/lessons/quiz items) is seeded from the
# JSON manifests bundled in app/data/. Idempotent — safe on every boot.
seed_academy()

app = FastAPI(
    title="ProReadyEngineer Training API",
    version="1.0.0",
    description="Registration + seat management for ProReadyEngineer training cohorts.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # required so /api/admin/* cookies survive
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

_register_gate_handler(app)

app.include_router(seats_routes.router)
app.include_router(sim_routes.router)
app.include_router(sim_routes.admin_router)
app.include_router(register_routes.router)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(courses_routes.public_router)
app.include_router(courses_routes.admin_router)
app.include_router(reminders_routes.router)
app.include_router(interest_routes.public_router)
app.include_router(interest_routes.admin_router)
app.include_router(ai_routes.router)
app.include_router(downloads_routes.router)
app.include_router(software_routes.public_router)
app.include_router(software_routes.admin_router)
app.include_router(stats_routes.router)
app.include_router(academy_routes.router)
app.include_router(certification_routes.router)
app.include_router(certification_admin_routes.router)
app.include_router(checkout_routes.router)
app.include_router(payments_routes.router)
app.include_router(academy_admin_routes.router)
app.include_router(comms_routes.router)
app.include_router(support_routes.public_router)
app.include_router(support_routes.admin_router)
# Legacy contract for the standalone quiz apps. Mounted at /auth and
# /learning (no /api prefix) because that is what those apps already call.
app.include_router(compat_routes.auth_router)
app.include_router(compat_routes.learning_router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "proreadyengineer-training-api",
        "cohort": settings.COHORT_LABEL,
        "capacity": settings.COURSE_CAPACITY,
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    return {"ok": True}
