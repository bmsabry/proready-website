"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import Course
from .routes import admin as admin_routes
from .routes import auth as auth_routes
from .routes import courses as courses_routes
from .routes import register as register_routes
from .routes import seats as seats_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

settings = get_settings()

# Create tables on startup. Safe for a single-table schema; swap to
# Alembic if the model grows.
Base.metadata.create_all(bind=engine)


def _seed_default_course() -> None:
    """Ensure the legacy Gas Turbine Emissions Mapping course row exists.

    The Course table is new; existing Registration rows already reference
    settings.COURSE_CODE. Without this seed, the public /api/courses/{code}
    endpoint would 404 on first boot after the Course table lands.
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
                )
            )
            db.commit()
            log.info("Seeded default course %s", settings.COURSE_CODE)
    finally:
        db.close()


_seed_default_course()

app = FastAPI(
    title="ProReadyEngineer Training API",
    version="1.0.0",
    description="Registration + seat management for ProReadyEngineer training cohorts.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # required so /api/admin/* cookies survive
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(seats_routes.router)
app.include_router(register_routes.router)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(courses_routes.public_router)
app.include_router(courses_routes.admin_router)


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
