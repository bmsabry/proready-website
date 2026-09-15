"""Who counts as a registrant of a live cohort — the one rule, in one place.

A `registrations` row moves through pending → paid, or to cancelled. A
fourth state was added in Sep 2026 without a rule behind it: `attended_at`,
the moderator's record that the person sat the full live course. Until
2026-09-15 every audience, counter and list still treated an attended row
as an active seat — so when the owner re-dated the course for its NEXT
cohort, the five people who had just finished the previous one were told
their start date had "moved". That must never happen again.

  active  — status in (pending, paid) AND not attended: someone awaiting
            (or in) the next delivery. Takes a seat; receives the
            automatic notices (date changes, session reminders, "confirm
            your seat" chases); is what the Registrations tab lists.
  past    — attended, whatever the status: a past-cohort record. Holds no
            seat; is never in an automatic audience; is written to only on
            purpose (the 'alumni' audience); lives under Past cohorts.

Cancelled rows are neither — they are kept for history only.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Course, Registration

ACTIVE_STATUSES = ("paid", "pending")


def active_clauses(course_code: str | None = None) -> list:
    """SQLAlchemy conditions selecting active registrants."""
    where = [
        Registration.status.in_(ACTIVE_STATUSES),
        Registration.attended_at.is_(None),
    ]
    if course_code is not None:
        where.insert(0, Registration.course_code == course_code)
    return where


def past_clauses(course_code: str | None = None) -> list:
    """SQLAlchemy conditions selecting past-cohort (attended) registrants."""
    where = [
        Registration.attended_at.is_not(None),
        Registration.status != "cancelled",
    ]
    if course_code is not None:
        where.insert(0, Registration.course_code == course_code)
    return where


def is_active(reg: Registration) -> bool:
    return reg.status in ACTIVE_STATUSES and reg.attended_at is None


def is_past(reg: Registration) -> bool:
    return reg.attended_at is not None and reg.status != "cancelled"


def active_registrations(db: Session, course_code: str) -> list[Registration]:
    return list(db.execute(
        select(Registration).where(*active_clauses(course_code)).order_by(Registration.created_at)
    ).scalars().all())


def past_registrations(db: Session, course_code: str) -> list[Registration]:
    return list(db.execute(
        select(Registration).where(*past_clauses(course_code)).order_by(Registration.attended_at.desc())
    ).scalars().all())


def active_emails(db: Session, course_code: str, statuses: tuple[str, ...] = ACTIVE_STATUSES) -> list[str]:
    """Emails of active registrants, optionally narrowed to a status subset
    (the Comms tab's 'paid' / 'pending' audiences), first-seen order."""
    stmt = (
        select(Registration.email)
        .where(*active_clauses(course_code), Registration.status.in_(statuses))
        .order_by(Registration.created_at)
    )
    return [email for (email,) in db.execute(stmt).all()]


def past_emails(db: Session, course_code: str) -> list[str]:
    stmt = (
        select(Registration.email)
        .where(*past_clauses(course_code))
        .order_by(Registration.attended_at)
    )
    return [email for (email,) in db.execute(stmt).all()]


def course_for(db: Session, reg: Registration) -> Course | None:
    return db.execute(select(Course).where(Course.code == reg.course_code)).scalar_one_or_none()
