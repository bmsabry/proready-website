"""Shared read-only stat/segment queries used by more than one admin surface.

Extracted from routes/academy_admin.py so the per-course stats endpoint
(routes/stats.py) and the comms audiences (routes/courses.py, routes/comms.py)
reuse the exact same numbers — keeping two dashboards from ever disagreeing
about what "revenue" or "an active buyer" means.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import academy as svc
from .models import Enrollment, Learner, Order


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
