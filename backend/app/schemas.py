"""Pydantic request/response models."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    """Payload matches the frontend form's FormData keys exactly."""

    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    job_title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    years_experience: str = Field(min_length=1, max_length=16)
    location: str = Field(min_length=1, max_length=200)
    consent: bool | str = True  # HTML checkbox sends "on" as string

    # Optional course code. If omitted, falls back to settings.COURSE_CODE
    # so older clients keep working during rollout.
    course_code: Optional[str] = Field(default=None, max_length=128)

    # Honeypot — real users leave this blank. If filled, backend returns
    # a fake success response and drops the submission.
    website: str = Field(default="", max_length=500)


class RegisterOut(BaseModel):
    ok: bool = True
    taken: int
    capacity: int
    status: Literal["pending", "duplicate"]
    registration_id: Optional[int] = None


class SeatsOut(BaseModel):
    taken: int
    capacity: int
    cohort: str


class AdminRegistrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_code: str
    full_name: str
    email: EmailStr
    job_title: str
    company: str
    years_experience: str
    location: str
    status: str
    admin_notes: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None


class MarkPaidIn(BaseModel):
    registration_id: int
    notes: Optional[str] = None


class MarkPaidOut(BaseModel):
    ok: bool
    taken: int
    registration: AdminRegistrationOut


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MeOut(BaseModel):
    email: EmailStr


class OkOut(BaseModel):
    ok: bool = True


# ----- Courses ---------------------------------------------------------------

class CourseOut(BaseModel):
    """Public + admin shape. `seats_taken` is always computed from registrations."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    start_date: date
    total_seats: int
    status: Literal["open", "closed"]
    # Per-day schedule, ordered Day 1 -> Day N. Empty list means
    # "duration not yet scheduled". Returned as ISO strings so the
    # browser doesn't have to deal with date-object reconstruction.
    day_dates: List[date] = Field(default_factory=list)
    # `seats_taken` = active seats (paid + pending). This is the public
    # counter — a registration takes a seat the moment it's submitted.
    # `seats_paid` is exposed separately so the admin UI can show the
    # paid / pending split.
    seats_taken: int = 0
    seats_paid: int = 0
    seats_remaining: int = 0


class CourseCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=2, max_length=200)
    start_date: date
    total_seats: int = Field(ge=1, le=1000)
    status: Literal["open", "closed"] = "open"
    # Optional on create — admin can fill in the schedule later.
    day_dates: List[date] = Field(default_factory=list, max_length=60)


class CoursePatchIn(BaseModel):
    """All fields optional — only supplied ones are updated."""

    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    start_date: Optional[date] = None
    total_seats: Optional[int] = Field(default=None, ge=1, le=1000)
    status: Optional[Literal["open", "closed"]] = None
    # Pass the full ordered list; we replace the column in one shot.
    # Send [] to clear; omit the field to leave unchanged.
    day_dates: Optional[List[date]] = Field(default=None, max_length=60)


class NotifyIn(BaseModel):
    """Admin broadcast payload."""

    subject: str = Field(min_length=1, max_length=200)
    body_html: str = Field(min_length=1, max_length=100_000)
    # Which registrants to target. 'all' includes paid + pending (not cancelled).
    audience: Literal["all", "paid", "pending"] = "all"


class NotifyOut(BaseModel):
    ok: bool = True
    recipients: int
    failures: int
    failed_addresses: List[str] = Field(default_factory=list)
