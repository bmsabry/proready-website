"""Cross-cutting admin stats: per-course (live vs recorded) and per-software.

GET /api/admin/stats/courses  — every course with its live-registration
                                 numbers and, when a recorded counterpart is
                                 linked, that product's revenue/enrollment
                                 headline (same queries as the academy
                                 dashboard, via stats_queries).
GET /api/admin/stats/software — download/launch/usage rollup per registered
                                 software product.

'Registration types' vocabulary: 'live' = rows in registrations (cohort
seats), 'recorded' = active enrollments on the linked academy product.

The per-row builders live in stats_queries (course_funnel_stats,
software_telemetry_stats) so the AI assistant's stat tools report the
same numbers as these endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Course, SoftwareProduct
from ..stats_queries import course_funnel_stats, software_telemetry_stats

router = APIRouter(
    prefix="/api/admin/stats",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/courses")
def stats_courses(db: Session = Depends(get_db)) -> dict:
    """Per-course funnel, split by registration type (live vs recorded)."""
    courses = db.execute(
        select(Course).order_by(Course.start_date.asc())
    ).scalars().all()
    return {"courses": [course_funnel_stats(db, course) for course in courses]}


@router.get("/software")
def stats_software(db: Session = Depends(get_db)) -> dict:
    """Downloads / launches / usage rollup for every registered product."""
    products = db.execute(
        select(SoftwareProduct).order_by(
            SoftwareProduct.created_at.asc(), SoftwareProduct.id.asc()
        )
    ).scalars().all()
    return {
        "software": [software_telemetry_stats(db, product) for product in products]
    }
