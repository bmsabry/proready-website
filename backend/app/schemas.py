"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

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
