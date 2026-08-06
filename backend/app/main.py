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
from .routes import admin as admin_routes
from .routes import ai as ai_routes
from .routes import auth as auth_routes
from .routes import checkout as checkout_routes
from .routes import comms as comms_routes
from .routes import compat as compat_routes
from .routes import courses as courses_routes
from .routes import downloads as downloads_routes
from .routes import register as register_routes
from .routes import seats as seats_routes
from .routes import software as software_routes
from .routes import stats as stats_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

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

app.include_router(seats_routes.router)
app.include_router(register_routes.router)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(courses_routes.public_router)
app.include_router(courses_routes.admin_router)
app.include_router(ai_routes.router)
app.include_router(downloads_routes.router)
app.include_router(software_routes.public_router)
app.include_router(software_routes.admin_router)
app.include_router(stats_routes.router)
app.include_router(academy_routes.router)
app.include_router(checkout_routes.router)
app.include_router(academy_admin_routes.router)
app.include_router(comms_routes.router)
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
