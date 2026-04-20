"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routes import admin as admin_routes
from .routes import register as register_routes
from .routes import seats as seats_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

settings = get_settings()

# Create tables on startup. Safe for a single-table schema; swap to
# Alembic if the model grows.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ProReadyEngineer Training API",
    version="1.0.0",
    description="Registration + seat management for ProReadyEngineer training cohorts.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(seats_routes.router)
app.include_router(register_routes.router)
app.include_router(admin_routes.router)


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
