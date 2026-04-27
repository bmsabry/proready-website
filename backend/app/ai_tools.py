"""AI tool registry — JSON-Schema definitions + Python handlers.

Each tool maps a model-emitted function call to existing admin logic.
Handlers always return JSON-serialisable dicts. They never raise the
Python errors back to the agent — instead they catch and return
{"ok": false, "error": "..."} so the agent can reason about failures
and the audit log records the error string.

High-stakes operations (any notify_course, or bulk mark_paid/cancel
≥ 3 rows) are intercepted in routes/ai.py BEFORE handlers run, so the
admin can approve in chat first.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from html import escape as _html_escape
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import broadcast_html, send_email
from .models import Course, Registration
from .seats import count_active, count_paid

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plain-text → email-safe HTML (mirrors the frontend helper so the agent
# can pass natural prose into notify_course and have it format right).
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"(https?://[^\s<]+|mailto:[^\s<]+)")


def _plain_text_to_email_html(text: str) -> str:
    paragraphs = text.replace("\r\n", "\n").split("\n\n")
    out = []
    for raw in paragraphs:
        p = raw.strip()
        if not p:
            continue
        escaped = _html_escape(p).replace("\n", "<br>")
        linked = _LINK_RE.sub(
            lambda m: f'<a href="{m.group(0)}" style="color:#22d3ee;">{m.group(0)}</a>',
            escaped,
        )
        out.append(f'<p style="margin:0 0 16px;">{linked}</p>')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _course_summary(c: Course, db: Session) -> Dict[str, Any]:
    return {
        "code": c.code,
        "title": c.title,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "total_seats": c.total_seats,
        "status": c.status,
        "day_dates": list(c.day_dates or []),
        "seats_paid": count_paid(db, c.code),
        "seats_active": count_active(db, c.code),
        "seats_remaining": max(c.total_seats - count_active(db, c.code), 0),
    }


def _registration_summary(r: Registration) -> Dict[str, Any]:
    return {
        "id": r.id,
        "course_code": r.course_code,
        "full_name": r.full_name,
        "email": r.email,
        "company": r.company,
        "job_title": r.job_title,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _course_or_error(db: Session, code: str) -> tuple[Optional[Course], Optional[Dict[str, Any]]]:
    course = db.execute(select(Course).where(Course.code == code)).scalar_one_or_none()
    if course is None:
        return None, {"ok": False, "error": f"course '{code}' not found"}
    return course, None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def list_courses(db: Session, **_: Any) -> Dict[str, Any]:
    rows = list(db.execute(select(Course).order_by(Course.start_date.asc())).scalars())
    return {"ok": True, "courses": [_course_summary(c, db) for c in rows]}


def get_course(db: Session, code: str) -> Dict[str, Any]:
    course, err = _course_or_error(db, code)
    if err:
        return err
    return {"ok": True, "course": _course_summary(course, db)}


def update_course(
    db: Session,
    code: str,
    title: Optional[str] = None,
    start_date: Optional[str] = None,
    total_seats: Optional[int] = None,
    status: Optional[str] = None,
    day_dates: Optional[List[str]] = None,
) -> Dict[str, Any]:
    course, err = _course_or_error(db, code)
    if err:
        return err
    changed: List[str] = []

    if title is not None:
        course.title = title.strip()
        changed.append("title")
    if total_seats is not None:
        if total_seats < 1:
            return {"ok": False, "error": "total_seats must be >= 1"}
        course.total_seats = int(total_seats)
        changed.append("total_seats")
    if status is not None:
        if status not in ("open", "closed"):
            return {"ok": False, "error": "status must be 'open' or 'closed'"}
        course.status = status
        changed.append("status")
    if start_date is not None:
        try:
            course.start_date = date.fromisoformat(start_date)
            changed.append("start_date")
        except ValueError:
            return {"ok": False, "error": f"start_date must be YYYY-MM-DD, got '{start_date}'"}
    if day_dates is not None:
        try:
            parsed = [date.fromisoformat(d).isoformat() for d in day_dates]
        except ValueError as e:
            return {"ok": False, "error": f"day_dates contains invalid date: {e}"}
        course.day_dates = parsed
        changed.append("day_dates")

    if not changed:
        return {"ok": False, "error": "no fields supplied to update"}

    db.commit()
    db.refresh(course)
    return {"ok": True, "changed_fields": changed, "course": _course_summary(course, db)}


def list_registrations(
    db: Session,
    course_code: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    settings = get_settings()
    code = (course_code or settings.COURSE_CODE).strip()
    stmt = select(Registration).where(Registration.course_code == code)
    if status:
        if status not in ("paid", "pending", "cancelled"):
            return {"ok": False, "error": "status must be paid|pending|cancelled"}
        stmt = stmt.where(Registration.status == status)
    stmt = stmt.order_by(Registration.created_at.desc()).limit(min(int(limit), 500))
    rows = list(db.execute(stmt).scalars())
    return {
        "ok": True,
        "course_code": code,
        "count": len(rows),
        "registrations": [_registration_summary(r) for r in rows],
    }


def _set_status(db: Session, registration_id: int, new_status: str, notes: Optional[str]) -> Dict[str, Any]:
    reg = db.get(Registration, registration_id)
    if reg is None:
        return {"ok": False, "error": f"registration {registration_id} not found"}
    if new_status == "paid":
        # Capacity guard, mirrors the admin endpoint.
        course = db.execute(
            select(Course).where(Course.code == reg.course_code)
        ).scalar_one_or_none()
        capacity = course.total_seats if course else get_settings().COURSE_CAPACITY
        if reg.status != "paid" and count_paid(db, reg.course_code) >= capacity:
            return {"ok": False, "error": "cohort already at paid capacity"}
        if reg.status != "paid":
            reg.paid_at = datetime.now(timezone.utc)
    else:
        reg.paid_at = None
    reg.status = new_status
    if notes is not None:
        reg.admin_notes = notes
    db.commit()
    db.refresh(reg)
    return {"ok": True, "registration": _registration_summary(reg)}


def mark_paid(db: Session, registration_id: int, notes: Optional[str] = None) -> Dict[str, Any]:
    return _set_status(db, registration_id, "paid", notes)


def cancel(db: Session, registration_id: int, notes: Optional[str] = None) -> Dict[str, Any]:
    return _set_status(db, registration_id, "cancelled", notes)


def bulk_mark_paid(db: Session, registration_ids: List[int], notes: Optional[str] = None) -> Dict[str, Any]:
    results = [_set_status(db, int(rid), "paid", notes) for rid in registration_ids]
    ok = sum(1 for r in results if r.get("ok"))
    return {"ok": True, "succeeded": ok, "failed": len(results) - ok, "results": results}


def bulk_cancel(db: Session, registration_ids: List[int], notes: Optional[str] = None) -> Dict[str, Any]:
    results = [_set_status(db, int(rid), "cancelled", notes) for rid in registration_ids]
    ok = sum(1 for r in results if r.get("ok"))
    return {"ok": True, "succeeded": ok, "failed": len(results) - ok, "results": results}


def notify_course(
    db: Session,
    code: str,
    subject: str,
    body: str,
    audience: str = "all",
) -> Dict[str, Any]:
    """Send a broadcast email. Body is plain text — converted to HTML here."""
    if audience not in ("all", "paid", "pending"):
        return {"ok": False, "error": "audience must be all|paid|pending"}
    course, err = _course_or_error(db, code)
    if err:
        return err

    stmt = select(Registration).where(Registration.course_code == code)
    if audience == "paid":
        stmt = stmt.where(Registration.status == "paid")
    elif audience == "pending":
        stmt = stmt.where(Registration.status == "pending")
    else:  # 'all' excludes cancelled
        stmt = stmt.where(Registration.status.in_(("paid", "pending")))
    recipients = list(db.execute(stmt).scalars())

    body_html = _plain_text_to_email_html(body)
    html = broadcast_html(course_title=course.title, body_html=body_html)

    sent = 0
    failed: List[str] = []
    for r in recipients:
        if send_email(to=r.email, subject=subject, html=html):
            sent += 1
        else:
            failed.append(r.email)

    return {
        "ok": True,
        "sent": sent,
        "failed_count": len(failed),
        "failed_addresses": failed,
        "audience": audience,
        "recipients_total": len(recipients),
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# Maps tool name -> (handler, JSON-Schema spec for OpenAI tools field).
# Handlers receive db as first positional arg, then kwargs from the model.
TOOL_HANDLERS = {
    "list_courses": list_courses,
    "get_course": get_course,
    "update_course": update_course,
    "list_registrations": list_registrations,
    "mark_paid": mark_paid,
    "cancel": cancel,
    "bulk_mark_paid": bulk_mark_paid,
    "bulk_cancel": bulk_cancel,
    "notify_course": notify_course,
}


def _fn(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


# OpenAI-format tool defs the agent sees.
TOOL_SPECS = [
    _fn(
        "list_courses",
        "List every course with its seats and schedule. Read-only; use freely.",
        {"type": "object", "properties": {}, "required": []},
    ),
    _fn(
        "get_course",
        "Fetch full detail for a single course by its code.",
        {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Course code, e.g. gas-turbine-emissions-mapping-2026-05"}},
            "required": ["code"],
        },
    ),
    _fn(
        "update_course",
        "Edit a course. Only fields you supply are changed. Use ISO YYYY-MM-DD for dates. day_dates is the full ordered list of per-day dates (length sets the cohort length).",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "title": {"type": "string"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "total_seats": {"type": "integer", "minimum": 1},
                "status": {"type": "string", "enum": ["open", "closed"]},
                "day_dates": {
                    "type": "array",
                    "items": {"type": "string", "description": "YYYY-MM-DD"},
                    "description": "Full ordered list. Length = cohort days. Pass [] to clear.",
                },
            },
            "required": ["code"],
        },
    ),
    _fn(
        "list_registrations",
        "List registrations for a course. Filterable by status. Returns up to `limit` rows (default 100).",
        {
            "type": "object",
            "properties": {
                "course_code": {"type": "string"},
                "status": {"type": "string", "enum": ["paid", "pending", "cancelled"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
            "required": [],
        },
    ),
    _fn(
        "mark_paid",
        "Mark a single registration as paid. Use bulk_mark_paid for >1 row.",
        {
            "type": "object",
            "properties": {
                "registration_id": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["registration_id"],
        },
    ),
    _fn(
        "cancel",
        "Cancel a single registration (frees the seat). Use bulk_cancel for >1 row.",
        {
            "type": "object",
            "properties": {
                "registration_id": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["registration_id"],
        },
    ),
    _fn(
        "bulk_mark_paid",
        "Mark several registrations paid in one call. Requires admin confirmation in chat when ≥3 ids.",
        {
            "type": "object",
            "properties": {
                "registration_ids": {"type": "array", "items": {"type": "integer"}},
                "notes": {"type": "string"},
            },
            "required": ["registration_ids"],
        },
    ),
    _fn(
        "bulk_cancel",
        "Cancel several registrations in one call. Requires admin confirmation in chat when ≥3 ids.",
        {
            "type": "object",
            "properties": {
                "registration_ids": {"type": "array", "items": {"type": "integer"}},
                "notes": {"type": "string"},
            },
            "required": ["registration_ids"],
        },
    ),
    _fn(
        "notify_course",
        "Send an email broadcast to a course's registrants. Body is PLAIN TEXT — newlines become paragraphs/<br>, links auto-link. Always requires admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain text. Backend converts to email HTML."},
                "audience": {
                    "type": "string",
                    "enum": ["all", "paid", "pending"],
                    "default": "all",
                    "description": "all = paid+pending; paid only; pending only.",
                },
            },
            "required": ["code", "subject", "body"],
        },
    ),
]


# Tools that always require admin confirmation in chat.
HIGH_STAKES_ALWAYS = {"notify_course"}

# Tools that are high-stakes only at large size.
HIGH_STAKES_BULK_THRESHOLD = 3
HIGH_STAKES_BULK_TOOLS = {"bulk_mark_paid", "bulk_cancel"}


def is_high_stakes(tool_name: str, args: Dict[str, Any]) -> bool:
    if tool_name in HIGH_STAKES_ALWAYS:
        return True
    if tool_name in HIGH_STAKES_BULK_TOOLS:
        ids = args.get("registration_ids") or []
        return len(ids) >= HIGH_STAKES_BULK_THRESHOLD
    return False


def summarize_call(tool_name: str, args: Dict[str, Any]) -> str:
    """Short human-readable summary used in the confirmation prompt."""
    if tool_name == "notify_course":
        aud = args.get("audience", "all")
        return (
            f"Send broadcast email to '{args.get('code', '?')}' "
            f"(audience: {aud}) — subject: \"{args.get('subject', '')[:80]}\""
        )
    if tool_name in {"bulk_mark_paid", "bulk_cancel"}:
        ids = args.get("registration_ids") or []
        action = "Mark paid" if tool_name == "bulk_mark_paid" else "Cancel"
        return f"{action} {len(ids)} registration(s): {ids}"
    return f"{tool_name} with {args}"
