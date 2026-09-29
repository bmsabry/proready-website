"""Shared read-only stat/segment queries used by more than one admin surface.

Extracted from routes/academy_admin.py so the per-course stats endpoint
(routes/stats.py) and the comms audiences (routes/courses.py, routes/comms.py)
reuse the exact same numbers — keeping two dashboards from ever disagreeing
about what "revenue" or "an active buyer" means. The per-course funnel and
per-software telemetry rollups live here too (moved from routes/stats.py),
so the admin stats endpoints and the AI assistant's stat tools report
number-for-number identical results.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import academy as svc
from . import registrants
from .models import (
    AppLaunch,
    AppUsage,
    Course,
    Enrollment,
    Learner,
    Order,
    ProductDownload,
    Registration,
    SoftwareProduct,
)


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def active_enrollee_emails(db: Session, product_code: str | None) -> list[str]:
    """Distinct emails of learners holding a live enrollment on a product.

    'Live' matches the access rule in academy.active_enrollment —
    status='active' AND not expired — so we only email people who can
    actually open the course. Blocked learners are excluded too: they
    fail auth, so mailing them invites replies we can't act on. The
    expiry check runs in Python because SQLite hands back naive
    datetimes (see academy._aware).
    """
    if not product_code:
        return []
    rows = db.execute(
        select(Learner.email, Enrollment.expires_at)
        .join(Enrollment, Enrollment.learner_id == Learner.id)
        .where(
            Enrollment.product_code == product_code,
            Enrollment.status == "active",
            Learner.status == "active",
        )
        .order_by(Learner.id.asc())
    ).all()
    now = datetime.now(timezone.utc)
    out: list[str] = []
    for email, expires_at in rows:
        expires = svc._aware(expires_at)
        if expires is None or expires > now:
            out.append(email)
    return list(dict.fromkeys(out))


def product_headline_stats(db: Session, product_code: str = "") -> dict:
    """Revenue + enrollment headline numbers for one product ('' = all).

    Body lifted verbatim from the old inline block in academy_admin's
    GET /stats so both callers keep identical semantics — notably
    active_enrollments counts status='active' rows regardless of expiry
    (an expired trial is still a relationship worth seeing on a revenue
    dashboard), unlike the comms audience above.
    """
    orders_q = select(Order).where(Order.status == "paid")
    if product_code:
        orders_q = orders_q.where(Order.product_code == product_code)
    paid_orders = db.execute(orders_q).scalars().all()

    revenue_cents = sum(o.amount_cents for o in paid_orders)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent_revenue = sum(
        o.amount_cents
        for o in paid_orders
        if o.paid_at and svc._aware(o.paid_at) >= cutoff
    )

    enroll_q = select(Enrollment).where(Enrollment.status == "active")
    if product_code:
        enroll_q = enroll_q.where(Enrollment.product_code == product_code)
    active = db.execute(enroll_q).scalars().all()

    completed = 0
    for learner_id in {e.learner_id for e in active}:
        learner = db.get(Learner, learner_id)
        if learner and product_code and svc.course_complete(db, learner, product_code):
            completed += 1

    return {
        "orders_paid": len(paid_orders),
        "revenue_cents_total": revenue_cents,
        "revenue_cents_30d": recent_revenue,
        "active_enrollments": len(active),
        "learners_completed": completed,
    }


def _past_cohorts(db: Session, course: Course, past: list[Registration]) -> list[dict]:
    """The cohorts this course has already delivered, newest first.

    A cohort's dates come from the Certificate of Attendance its people
    received (it records the span it was issued for). Without one, the day
    attendance was marked stands in for both ends.
    """
    from . import certificates as certs

    spans: dict[tuple, int] = {}
    for reg in past:
        start = end = None
        if course.recorded_product_code:
            learner = db.execute(
                select(Learner).where(Learner.email == (reg.email or "").lower().strip())
            ).scalar_one_or_none()
            cert = (
                certs.get_certificate(db, learner, course.recorded_product_code, "attendance")
                if learner is not None
                else None
            )
            if cert is not None and cert.cohort_start:
                start, end = cert.cohort_start, cert.cohort_end or cert.cohort_start
        if start is None and reg.attended_at is not None:
            start = end = reg.attended_at.date()
        key = (start.isoformat() if start else "", end.isoformat() if end else "")
        spans[key] = spans.get(key, 0) + 1
    return [
        {"start": s or None, "end": e or None, "trained": n}
        for (s, e), n in sorted(spans.items(), reverse=True)
    ]


def course_funnel_stats(db: Session, course: Course) -> dict:
    """One course: its current offering, and everything it has done so far.

    live     — the CURRENT cohort (the next or running delivery): who holds
               a seat now, by the one registrant rule (app/registrants.py).
               Someone who already attended a previous cohort is history,
               not a paid seat in this one.
    cohort   — the current cohort's dates.
    history  — all-time: the cohorts delivered, people trained, paid seats
               and any fees recorded with them.
    recorded — the linked recorded product's sales and learners (all time),
               null when the course has no recorded twin.

    The admin Overview, the Courses page and the AI assistant's
    get_course_stats all read this, so they cannot disagree.
    """
    rows = db.execute(
        select(Registration).where(Registration.course_code == course.code)
    ).scalars().all()
    active = [r for r in rows if registrants.is_active(r)]
    past = [r for r in rows if registrants.is_past(r)]
    pending = sum(1 for r in active if r.status == "pending")
    paid = sum(1 for r in active if r.status == "paid")

    # Cancellations since the last cohort was signed off belong to the
    # current one; earlier ones are history.
    marked = [a for a in (svc._aware(r.attended_at) for r in past) if a is not None]
    last_signed_off = max(marked) if marked else None
    cancelled_rows = [r for r in rows if r.status == "cancelled"]
    cancelled_now = sum(
        1
        for r in cancelled_rows
        if last_signed_off is None or (svc._aware(r.created_at) or last_signed_off) > last_signed_off
    )

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
    # null (not zeros) so callers can tell "no recorded offering"
    # apart from "recorded offering with no sales yet".
    recorded = (
        product_headline_stats(db, course.recorded_product_code)
        if course.recorded_product_code
        else None
    )

    days = sorted(course.day_dates or [])
    paid_ever = [r for r in rows if r.status == "paid"]
    cohorts = _past_cohorts(db, course, past)

    return {
        "code": course.code,
        "title": course.title,
        "start_date": course.start_date.isoformat(),
        "status": course.status,
        "live": {
            "pending": pending,
            "paid": paid,
            "cancelled": cancelled_now,
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
        "cohort": {
            "start": days[0] if days else course.start_date.isoformat(),
            "end": days[-1] if days else course.start_date.isoformat(),
            "days": len(days),
            "price_cents": course.price_cents,
            "currency": course.currency,
        },
        "history": {
            "cohorts_run": len(cohorts),
            "cohorts": cohorts,
            "trained": len(past),
            "paid_seats": len(paid_ever),
            # Fees are only known where a payment recorded its amount
            # (online payments); seats marked paid by hand carry none.
            "fees_cents": sum(r.amount_cents or 0 for r in paid_ever),
            "paid_without_amount": sum(1 for r in paid_ever if r.amount_cents is None),
            "registrations": len(rows),
            "cancelled": len(cancelled_rows),
        },
        "recorded": recorded,
    }


def software_telemetry_stats(db: Session, product: SoftwareProduct) -> dict:
    """Downloads / launches / usage rollup for one registered product.

    Body moved verbatim from routes/stats.py GET /software so the stats
    dashboard and the AI assistant's get_software_stats agree exactly.
    """
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

    return {
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
