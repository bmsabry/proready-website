"""Database models.

Tables:
  courses        — one row per cohort/course offering
  registrations  — one row per registration attempt, linked to a course by `course_code`

Registration status transitions:
  pending -> paid      (admin marks paid after invoice clears)
  pending -> cancelled (admin releases a stale lead)

Only `paid` rows count toward a course's seat cap.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # URL-friendly identifier used in registrations.course_code and public API.
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    total_seats: Mapped[int] = mapped_column(Integer, default=15)

    # ISO date strings, ordered Day 1 -> Day N. Number of days = len(day_dates).
    # Stored as JSON for portability (Postgres uses native json, SQLite text).
    day_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 'open' | 'closed' — 'closed' rejects new registrations.
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Foreign-key-by-string to Course.code. String chosen over a real FK so
    # admins can rename/replace courses without cascading migrations.
    course_code: Mapped[str] = mapped_column(String(128), index=True)

    # Applicant fields mirror the frontend form.
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), index=True)
    job_title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200))
    years_experience: Mapped[str] = mapped_column(String(16))
    location: Mapped[str] = mapped_column(String(200))

    # 'pending' | 'paid' | 'cancelled'
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)

    # Free-text admin notes (optional, nullable).
    admin_notes: Mapped[str | None] = mapped_column(String(2000), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


# Composite index: common "count paid rows for this course" query.
Index(
    "ix_registrations_course_status",
    Registration.course_code,
    Registration.status,
)


class AISettings(Base):
    """LLM credentials + model preference for the admin AI assistant.

    Single-row table — there's only ever one config (the admin's). The API
    key is stored Fernet-encrypted using the AI_SETTINGS_KEY env var; the
    plaintext never touches the DB or the wire after entry.
    """

    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    api_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
