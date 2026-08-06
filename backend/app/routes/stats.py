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
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as tz

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import (
    AppLaunch,
    AppUsage,
    Course,
    ProductDownload,
    Registration,
    SoftwareProduct,
)
from ..stats_queries import product_headline_stats

router = APIRouter(
    prefix="/api/admin/stats",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _since(days: int) -> datetime:
    return datetime.now(tz.utc) - timedelta(days=days)


@router.get("/courses")
def stats_courses(db: Session = Depends(get_db)) -> dict:
    """Per-course funnel, split by registration type (live vs recorded)."""
    courses = db.execute(
        select(Course).order_by(Course.start_date.asc())
    ).scalars().all()

    out = []
    for course in courses:
        counts = dict(
            db.execute(
                select(Registration.status, func.count(Registration.id))
                .where(Registration.course_code == course.code)
                .group_by(Registration.status)
            ).all()
        )
        pending = int(counts.get("pending", 0))
        paid = int(counts.get("paid", 0))
        cancelled = int(counts.get("cancelled", 0))

        day = func.date(Registration.created_at)
        by_day = db.execute(
            select(day, func.count(Registration.id))
            .where(
                Registration.course_code == course.code,
                Registration.created_at >= _since(60),
            )
            .group_by(day)
            .order_by(day)
        ).all()

        by_company = db.execute(
            select(Registration.company, func.count(Registration.id))
            .where(Registration.course_code == course.code)
            .group_by(Registration.company)
            .order_by(func.count(Registration.id).desc())
            .limit(10)
        ).all()

        # Recorded side only exists once a counterpart product is linked;
        # null (not zeros) so the dashboard can tell "no recorded offering"
        # apart from "recorded offering with no sales yet".
        recorded = (
            product_headline_stats(db, course.recorded_product_code)
            if course.recorded_product_code
            else None
        )

        out.append(
            {
                "code": course.code,
                "title": course.title,
                "start_date": course.start_date.isoformat(),
                "status": course.status,
                "live": {
                    "pending": pending,
                    "paid": paid,
                    "cancelled": cancelled,
                    "seats_total": course.total_seats,
                    # Active seats (paid + pending) — same definition as the
                    # public counter in routes/courses.py.
                    "seats_taken": paid + pending,
                    "by_day": [
                        {"date": str(d), "count": int(n)} for d, n in by_day
                    ],
                    "by_company": [
                        {"company": c, "count": int(n)} for c, n in by_company
                    ],
                },
                "recorded": recorded,
            }
        )
    return {"courses": out}


@router.get("/software")
def stats_software(db: Session = Depends(get_db)) -> dict:
    """Downloads / launches / usage rollup for every registered product."""
    products = db.execute(
        select(SoftwareProduct).order_by(
            SoftwareProduct.created_at.asc(), SoftwareProduct.id.asc()
        )
    ).scalars().all()

    out = []
    for product in products:
        slug = product.slug

        dl_base = select(func.count(ProductDownload.id)).where(
            ProductDownload.product == slug
        )
        downloads = {
            "total": int(db.execute(dl_base).scalar() or 0),
            "last7": int(
                db.execute(dl_base.where(ProductDownload.ts >= _since(7))).scalar()
                or 0
            ),
            "last30": int(
                db.execute(dl_base.where(ProductDownload.ts >= _since(30))).scalar()
                or 0
            ),
        }

        la_base = select(func.count(AppLaunch.id)).where(AppLaunch.product == slug)
        launches = {
            "total": int(db.execute(la_base).scalar() or 0),
            "last7": int(
                db.execute(la_base.where(AppLaunch.ts >= _since(7))).scalar() or 0
            ),
            "by_version": [
                {"version": v or "(unknown)", "count": int(n)}
                for v, n in db.execute(
                    select(AppLaunch.version, func.count(AppLaunch.id))
                    .where(AppLaunch.product == slug)
                    .group_by(AppLaunch.version)
                    .order_by(func.count(AppLaunch.id).desc())
                    .limit(8)
                )
            ],
        }

        pings = int(
            db.execute(
                select(func.count(AppUsage.id)).where(AppUsage.product == slug)
            ).scalar()
            or 0
        )
        total_minutes = int(
            db.execute(
                select(func.coalesce(func.sum(AppUsage.minutes), 0)).where(
                    AppUsage.product == slug
                )
            ).scalar()
            or 0
        )
        # Feature counts live as JSON strings; aggregate the most recent 5000
        # pings in Python (same bound as the existing /api/usage/stats).
        feature_totals: dict[str, int] = {}
        for (feats_json,) in db.execute(
            select(AppUsage.features)
            .where(AppUsage.product == slug, AppUsage.features.isnot(None))
            .order_by(AppUsage.ts.desc())
            .limit(5000)
        ):
            try:
                for k, v in json.loads(feats_json).items():
                    if isinstance(v, int):
                        feature_totals[k] = feature_totals.get(k, 0) + v
            except Exception:
                continue
        top_features = [
            {"feature": k, "count": v}
            for k, v in sorted(feature_totals.items(), key=lambda kv: -kv[1])[:10]
        ]

        out.append(
            {
                "slug": slug,
                "name": product.name,
                "downloads": downloads,
                "launches": launches,
                "usage": {
                    "pings": pings,
                    "total_minutes": total_minutes,
                    "top_features": top_features,
                },
            }
        )
    return {"software": out}
