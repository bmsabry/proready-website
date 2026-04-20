"""Database models.

Single table for v1 — one row per registration attempt. Status transitions:
  pending -> paid      (admin marks paid after invoice clears)
  pending -> cancelled (admin releases a stale lead)

Only `paid` rows count toward the 15-seat cap.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Cohort identifier — lets a second cohort reuse the same table later.
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


# Composite index: common "count paid rows for this cohort" query.
Index(
    "ix_registrations_course_status",
    Registration.course_code,
    Registration.status,
)
