"""AI tool registry — JSON-Schema definitions + Python handlers.

Each tool maps a model-emitted function call to existing admin logic.
Handlers always return JSON-serialisable dicts. They never raise the
Python errors back to the agent — instead they catch and return
{"ok": false, "error": "..."} so the agent can reason about failures
and the audit log records the error string.

Wherever an admin HTTP endpoint already implements the behaviour, the
handler calls that route function (or its shared helper) directly —
mark_paid goes through routes/admin.mark_registration_paid, broadcasts
through routes/courses + routes/comms, grants through routes/academy_admin
— so the assistant and the dashboard can never disagree on side effects.

High-stakes operations (broadcasts, enrollment grant/revoke, lesson
edits, software hide/show, bulk mark_paid/cancel ≥ 3 rows) are
intercepted in routes/ai.py BEFORE handlers run, so the admin can
approve in chat first.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from html import escape as _html_escape
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    Course,
    Enrollment,
    Learner,
    Lesson,
    Order,
    Product,
    Registration,
    SoftwareProduct,
    SupportTicket,
    SupportTicketMessage,
)
from .routes import academy_admin as academy_admin_routes
from .routes import admin as admin_routes
from .routes import comms as comms_routes
from .routes import courses as courses_routes
from .routes import software as software_routes
from .schemas import NotifyIn
from .seats import count_active, count_paid
from .stats_queries import course_funnel_stats, software_telemetry_stats

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plain-text → email-safe HTML (mirrors the frontend helper so the agent
# can pass natural prose into the notify tools and have it format right).
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


def _iso(dt: Any) -> Optional[str]:
    return dt.isoformat() if dt else None


def _http_err(e: HTTPException) -> Dict[str, Any]:
    return {"ok": False, "error": str(e.detail)}


def _validation_err(e: ValidationError) -> Dict[str, Any]:
    first = e.errors()[0]
    field = ".".join(str(p) for p in first.get("loc", ()))
    return {"ok": False, "error": f"invalid {field or 'input'}: {first.get('msg', 'validation error')}"}


def _course_summary(c: Course, db: Session) -> Dict[str, Any]:
    return {
        "code": c.code,
        "title": c.title,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "total_seats": c.total_seats,
        "status": c.status,
        "session_time_utc": c.session_time_utc or "",
        "session_duration_minutes": c.session_duration_minutes or 0,
        "session_time_note": ("" if c.session_time_utc else "NO SESSION TIME IS SET for this course. You do not know what time of day it runs. Do not state or guess one — ask Bassam, or set it with update_course."),
        "day_dates": list(c.day_dates or []),
        "price_cents": c.price_cents,
        "currency": c.currency,
        "recorded_product_code": c.recorded_product_code,
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
        "created_at": _iso(r.created_at),
        "attendance_confirmed_at": _iso(r.attendance_confirmed_at),
        "attendance_confirmed": r.attendance_confirmed_at is not None,
    }


def _course_or_error(db: Session, code: str) -> tuple[Optional[Course], Optional[Dict[str, Any]]]:
    course = db.execute(select(Course).where(Course.code == code)).scalar_one_or_none()
    if course is None:
        return None, {"ok": False, "error": f"course '{code}' not found"}
    return course, None


# ---------------------------------------------------------------------------
# Tool handlers — courses & registrations
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
    session_time_utc: Optional[str] = None,
    session_duration_minutes: Optional[int] = None,
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
    if session_time_utc is not None:
        t = session_time_utc.strip()
        if t and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            return {
                "ok": False,
                "error": f"session_time_utc must be 24-hour 'HH:MM' UTC, got '{t}'",
            }
        course.session_time_utc = t
        changed.append("session_time_utc")
    if session_duration_minutes is not None:
        if not 0 <= int(session_duration_minutes) <= 1440:
            return {"ok": False, "error": "session_duration_minutes must be 0-1440"}
        course.session_duration_minutes = int(session_duration_minutes)
        changed.append("session_duration_minutes")

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
    code = (course_code or "").strip()
    if not code:
        return {
            "ok": False,
            "error": (
                "course_code is required — pass a real course code "
                "(use list_courses to find it) or 'all' for every course"
            ),
        }
    stmt = select(Registration)
    if code != "all":
        _, err = _course_or_error(db, code)
        if err:
            return err
        stmt = stmt.where(Registration.course_code == code)
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


def mark_paid(db: Session, registration_id: int, notes: Optional[str] = None) -> Dict[str, Any]:
    reg = db.get(Registration, registration_id)
    if reg is None:
        return {"ok": False, "error": f"registration {registration_id} not found"}
    try:
        # Shared with the admin endpoint and the online payment paths
        # (PayPal capture, Stripe webhook) — identical side effects.
        transitioned = admin_routes.mark_registration_paid(db, reg, notes=notes)
    except HTTPException as e:
        return {"ok": False, "error": str(e.detail), "course_code": reg.course_code}
    return {
        "ok": True,
        "course_code": reg.course_code,
        "already_paid": not transitioned,
        "registration": _registration_summary(reg),
    }


def cancel(db: Session, registration_id: int, notes: Optional[str] = None) -> Dict[str, Any]:
    reg = db.get(Registration, registration_id)
    if reg is None:
        return {"ok": False, "error": f"registration {registration_id} not found"}
    # Mirrors POST /api/admin/cancel: frees the seat, clears paid_at.
    reg.status = "cancelled"
    reg.paid_at = None
    if notes is not None:
        reg.admin_notes = notes
    db.commit()
    db.refresh(reg)
    return {
        "ok": True,
        "course_code": reg.course_code,
        "registration": _registration_summary(reg),
    }


def _bulk(db: Session, registration_ids: List[int], notes: Optional[str], one) -> Dict[str, Any]:
    results = [one(db, int(rid), notes) for rid in registration_ids]
    ok = sum(1 for r in results if r.get("ok"))
    course_codes = sorted({r["course_code"] for r in results if r.get("course_code")})
    return {
        "ok": True,
        "succeeded": ok,
        "failed": len(results) - ok,
        "course_codes": course_codes,
        "results": results,
    }


def bulk_mark_paid(db: Session, registration_ids: List[int], notes: Optional[str] = None) -> Dict[str, Any]:
    return _bulk(db, registration_ids, notes, mark_paid)


def bulk_cancel(db: Session, registration_ids: List[int], notes: Optional[str] = None) -> Dict[str, Any]:
    return _bulk(db, registration_ids, notes, cancel)


def notify_course(
    db: Session,
    code: str,
    subject: str,
    body: str,
    audience: str = "all",
) -> Dict[str, Any]:
    """Broadcast to a cohort via the same path as the admin notify endpoint
    (audience resolution, batch send and EmailLog rows all included).
    Body is plain text — converted to HTML here."""
    try:
        payload = NotifyIn(
            subject=subject,
            body_html=_plain_text_to_email_html(body),
            audience=audience,
        )
    except ValidationError as e:
        return _validation_err(e)
    try:
        out = courses_routes.notify_course(code, payload, db)
    except HTTPException as e:
        return _http_err(e)
    return {
        "ok": True,
        "sent": out.recipients,
        "failed_count": out.failures,
        "failed_addresses": out.failed_addresses,
        "audience": audience,
        "recipients_total": out.recipients + out.failures,
    }


# ---------------------------------------------------------------------------
# Tool handlers — platform-wide reads
# ---------------------------------------------------------------------------


def get_course_stats(db: Session, course_code: Optional[str] = None) -> Dict[str, Any]:
    stmt = select(Course).order_by(Course.start_date.asc())
    if course_code:
        stmt = stmt.where(Course.code == course_code)
    courses = list(db.execute(stmt).scalars())
    if course_code and not courses:
        return {"ok": False, "error": f"course '{course_code}' not found"}
    return {"ok": True, "courses": [course_funnel_stats(db, c) for c in courses]}


def get_software_stats(db: Session, slug: Optional[str] = None) -> Dict[str, Any]:
    stmt = select(SoftwareProduct).order_by(
        SoftwareProduct.created_at.asc(), SoftwareProduct.id.asc()
    )
    if slug:
        stmt = stmt.where(SoftwareProduct.slug == slug)
    products = list(db.execute(stmt).scalars())
    if slug and not products:
        return {"ok": False, "error": f"software '{slug}' not found"}
    return {"ok": True, "software": [software_telemetry_stats(db, p) for p in products]}


def list_software(db: Session, **_: Any) -> Dict[str, Any]:
    # Same rows as GET /api/admin/software — hidden products included.
    return {"ok": True, "software": software_routes.list_software_admin(db)}


def list_learners(
    db: Session,
    query: Optional[str] = None,
    product_code: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    if product_code and db.get(Product, product_code) is None:
        return {"ok": False, "error": f"product '{product_code}' not found"}
    data = academy_admin_routes.list_learners(product_code=product_code or "", db=db)
    q = (query or "").strip().lower()
    cap = max(1, min(int(limit), 200))
    rows: List[Dict[str, Any]] = []
    for row in data["learners"]:
        if q and q not in row["email"].lower() and q not in (row["full_name"] or "").lower():
            continue
        rows.append(
            {
                "id": row["id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "status": row["status"],
                "is_owner": row["is_owner"],
                "created_at": _iso(row["created_at"]),
                "last_login_at": _iso(row["last_login_at"]),
                "lessons_completed": row["lessons_completed"],
                "quiz_attempts": row["quiz_attempts"],
                "enrollments": [
                    {
                        "product_code": e["product_code"],
                        "status": e["status"],
                        "source": e["source"],
                        "granted_at": _iso(e["granted_at"]),
                    }
                    for e in row["enrollments"]
                ],
            }
        )
        if len(rows) >= cap:
            break
    return {"ok": True, "count": len(rows), "learners": rows}


def get_email_log(db: Session, scope_code: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    data = comms_routes.comms_log(
        scope_code=(scope_code or "").strip(),
        limit=max(1, min(int(limit), 200)),
        db=db,
    )
    return {"ok": True, "count": data["count"], "emails": data["rows"]}


def list_course_content(db: Session, product_code: str) -> Dict[str, Any]:
    try:
        data = academy_admin_routes.product_content(product_code, db)
    except HTTPException as e:
        return _http_err(e)
    modules = []
    for m in data["modules"]:
        modules.append(
            {
                "id": m["id"],
                "code": m["code"],
                "title": m["title"],
                "position": m["position"],
                "quiz_item_count": m["quiz_item_count"],
                "lessons": [
                    {
                        "id": l["id"],
                        "title": l["title"],
                        "kind": l["kind"],
                        "position": l["position"],
                        "duration_s": l["duration_s"],
                        "video_ready": bool(l["video_uid"]) if l["kind"] == "video" else None,
                        "is_preview": l["is_preview"],
                    }
                    for l in m["lessons"]
                ],
            }
        )
    return {"ok": True, "product": data["product"], "modules": modules}


def find_person(db: Session, email: str) -> Dict[str, Any]:
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return {"ok": False, "error": "email is required"}

    regs = list(
        db.execute(
            select(Registration)
            .where(func.lower(Registration.email) == email_norm)
            .order_by(Registration.created_at.desc())
        ).scalars()
    )
    learner = db.execute(
        select(Learner).where(Learner.email == email_norm)
    ).scalar_one_or_none()
    enrollments: List[Enrollment] = []
    if learner is not None:
        enrollments = list(
            db.execute(
                select(Enrollment).where(Enrollment.learner_id == learner.id)
            ).scalars()
        )
    order_filter = func.lower(Order.email) == email_norm
    if learner is not None:
        order_filter = or_(order_filter, Order.learner_id == learner.id)
    orders = list(
        db.execute(
            select(Order).where(order_filter).order_by(Order.created_at.desc())
        ).scalars()
    )

    return {
        "ok": True,
        "email": email_norm,
        "found": bool(regs or learner or orders),
        "registrations": [_registration_summary(r) for r in regs],
        "learner": (
            {
                "id": learner.id,
                "email": learner.email,
                "full_name": learner.full_name,
                "status": learner.status,
                "created_at": _iso(learner.created_at),
                "last_login_at": _iso(learner.last_login_at),
            }
            if learner is not None
            else None
        ),
        "enrollments": [
            {
                "product_code": e.product_code,
                "status": e.status,
                "source": e.source,
                "granted_at": _iso(e.granted_at),
                "expires_at": _iso(e.expires_at),
                "note": e.note,
            }
            for e in enrollments
        ],
        "orders": [
            {
                "id": o.id,
                "product_code": o.product_code,
                "provider": o.provider,
                "status": o.status,
                "amount_cents": o.amount_cents,
                "currency": o.currency,
                "created_at": _iso(o.created_at),
                "paid_at": _iso(o.paid_at),
            }
            for o in orders
        ],
    }


# ---------------------------------------------------------------------------
# Tool handlers — platform-wide writes
# ---------------------------------------------------------------------------


def notify_product_buyers(db: Session, product_code: str, subject: str, body: str) -> Dict[str, Any]:
    """Broadcast to a product's active enrollees via the same path as
    POST /api/admin/products/{code}/notify (batch send + EmailLog rows)."""
    try:
        payload = comms_routes.ProductNotifyIn(
            subject=subject, body_html=_plain_text_to_email_html(body)
        )
    except ValidationError as e:
        return _validation_err(e)
    try:
        out = comms_routes.notify_product(product_code, payload, db)
    except HTTPException as e:
        return _http_err(e)
    return {
        "ok": True,
        "product_code": product_code,
        "sent": out.recipients,
        "failed_count": out.failures,
        "failed_addresses": out.failed_addresses,
    }


def grant_enrollment(
    db: Session, email: str, product_code: str, full_name: Optional[str] = None
) -> Dict[str, Any]:
    try:
        payload = academy_admin_routes.GrantIn(
            email=email,
            product_code=product_code,
            full_name=full_name or "",
            note="granted via AI assistant",
        )
    except ValidationError as e:
        return _validation_err(e)
    try:
        # Same path as POST /api/admin/academy/grant — upserts the learner,
        # activates the enrollment and emails a sign-in link.
        out = academy_admin_routes.grant(payload, db, admin="ai-assistant")
    except HTTPException as e:
        return _http_err(e)
    return {**out, "product_code": product_code}


def revoke_enrollment(db: Session, email: str, product_code: str) -> Dict[str, Any]:
    try:
        payload = academy_admin_routes.RevokeIn(email=email, product_code=product_code)
    except ValidationError as e:
        return _validation_err(e)
    try:
        academy_admin_routes.revoke(payload, db, admin="ai-assistant")
    except HTTPException as e:
        return _http_err(e)
    return {"ok": True, "email": str(payload.email), "product_code": product_code}


_LESSON_FIELDS = ("title", "body", "is_preview", "position")


def update_lesson(db: Session, lesson_id: int, fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fields = dict(fields or {})
    unknown = sorted(set(fields) - set(_LESSON_FIELDS))
    if unknown:
        return {"ok": False, "error": f"unsupported fields {unknown}; allowed: {list(_LESSON_FIELDS)}"}
    if not fields:
        return {"ok": False, "error": "no fields supplied to update"}
    try:
        payload = academy_admin_routes.LessonPatch(**fields)
    except ValidationError as e:
        return _validation_err(e)
    try:
        academy_admin_routes.patch_lesson(int(lesson_id), payload, db)
    except HTTPException as e:
        return _http_err(e)
    lesson = db.get(Lesson, int(lesson_id))
    return {
        "ok": True,
        "changed_fields": sorted(fields),
        "lesson": {
            "id": lesson.id,
            "title": lesson.title,
            "kind": lesson.kind,
            "position": lesson.position,
            "is_preview": lesson.is_preview,
        },
    }


_SOFTWARE_FIELDS = ("name", "blurb", "latest_version", "status")


def update_software(db: Session, slug: str, fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fields = dict(fields or {})
    unknown = sorted(set(fields) - set(_SOFTWARE_FIELDS))
    if unknown:
        return {"ok": False, "error": f"unsupported fields {unknown}; allowed: {list(_SOFTWARE_FIELDS)}"}
    if not fields:
        return {"ok": False, "error": "no fields supplied to update"}
    try:
        payload = software_routes.SoftwarePatchIn(**fields)
    except ValidationError as e:
        return _validation_err(e)
    try:
        row = software_routes.patch_software(slug, payload, db)
    except HTTPException as e:
        return _http_err(e)
    return {"ok": True, "changed_fields": sorted(fields), "software": row}




# ---------------------------------------------------------------------------
# Support desk
# ---------------------------------------------------------------------------
#
# These let the assistant work the inbox conversationally — "what's waiting
# on me?", "read me ticket 7A3C91B2", "reply to it explaining the refund
# window". Sending is deliberately high-stakes: everything else here only
# moves rows around inside the admin panel, but reply_to_ticket puts words
# in Bassam's name in front of a customer, and that is not something an
# agent should be able to do on its own reading of the situation.


def _ticket_brief(db: Session, t: SupportTicket) -> Dict[str, Any]:
    last = db.execute(
        select(SupportTicketMessage)
        .where(SupportTicketMessage.ticket_id == t.id)
        .order_by(SupportTicketMessage.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "ref": t.ref,
        "subject": t.subject,
        "from": t.submitter_email,
        "name": t.submitter_name or "",
        "category": t.category,
        "priority": t.priority,
        "status": t.status,
        "source": t.source,
        "summary": (t.ai_result or {}).get("summary", "") if t.ai_result else "",
        "created_at": _iso(t.created_at),
        "last_message_at": _iso(t.last_message_at or t.created_at),
        "waiting_on_us": bool(last is not None and last.sender_kind == "customer"),
    }


def _ticket_or_error(
    db: Session, ref: str
) -> tuple[Optional[SupportTicket], Optional[Dict[str, Any]]]:
    t = db.execute(
        select(SupportTicket).where(SupportTicket.ref == (ref or "").strip().upper())
    ).scalar_one_or_none()
    if t is None:
        return None, {"ok": False, "error": f"No support ticket with ref '{ref}'."}
    return t, None


def list_tickets(
    db: Session,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 25,
    **_: Any,
) -> Dict[str, Any]:
    from . import support_service as svc

    stmt = select(SupportTicket)
    if status == "open" or status is None:
        stmt = stmt.where(
            SupportTicket.status.in_(
                ["new", "ai_handling", "escalated", "awaiting_customer"]
            )
        )
    elif status != "all":
        stmt = stmt.where(SupportTicket.status == status)
    if category:
        if category not in svc.CATEGORIES:
            return {
                "ok": False,
                "error": f"Unknown category '{category}'. Valid: {sorted(svc.CATEGORIES)}",
            }
        stmt = stmt.where(SupportTicket.category == category)

    rows = (
        db.execute(
            stmt.order_by(
                SupportTicket.priority.asc(),
                func.coalesce(
                    SupportTicket.last_message_at, SupportTicket.created_at
                ).desc(),
            ).limit(max(1, min(int(limit or 25), 100)))
        )
        .scalars()
        .all()
    )
    return {"ok": True, "count": len(rows), "tickets": [_ticket_brief(db, t) for t in rows]}


def get_ticket(db: Session, ref: str) -> Dict[str, Any]:
    from . import support_service as svc

    t, err = _ticket_or_error(db, ref)
    if err:
        return err
    assert t is not None
    msgs = (
        db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == t.id)
            .order_by(SupportTicketMessage.id)
        )
        .scalars()
        .all()
    )
    return {
        "ok": True,
        "ticket": _ticket_brief(db, t),
        "customer": svc.customer_context(db, t.submitter_email),
        "thread": [
            {
                "from": m.sender_kind,
                "name": m.sender_name or "",
                "at": _iso(m.created_at),
                "text": (m.body_text or svc._html_to_text(m.body_html))[:4000],
                "delivered": m.email_delivered,
            }
            for m in msgs
        ],
    }


def reply_to_ticket(db: Session, ref: str, body: str, resolve: bool = False) -> Dict[str, Any]:
    """Email a reply to the customer. High-stakes — needs approval."""
    from . import support_service as svc

    t, err = _ticket_or_error(db, ref)
    if err:
        return err
    assert t is not None
    if not (body or "").strip():
        return {"ok": False, "error": "Reply body is empty."}

    html = _plain_text_to_email_html(body) if "<" not in body else body
    delivered, mid = svc.send_ticket_email(db, t, body_html=html)
    svc.add_message(
        db,
        t,
        sender_kind="admin",
        sender_name="Bassam Sabry",
        body_html=html,
        body_text=svc._html_to_text(html),
        direction="outbound",
        email_message_id=mid,
        email_delivered=delivered,
    )
    if not t.first_responded_at:
        t.first_responded_at = datetime.now(timezone.utc)
    # A send Resend refused reached nobody — never close on a failed send.
    t.status = ("resolved" if resolve else "awaiting_customer") if delivered else "escalated"
    if t.status == "resolved" and not t.resolved_at:
        t.resolved_at = datetime.now(timezone.utc)
    svc.emit_event(
        db, t, "admin_reply", actor="ai-assistant", payload={"delivered": delivered}
    )
    db.commit()
    return {
        "ok": True,
        "delivered": delivered,
        "status": t.status,
        "note": "" if delivered else "Email send FAILED — ticket left escalated.",
    }


def update_ticket(
    db: Session,
    ref: str,
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Move a ticket's status or fix its category. Never emails anyone."""
    from . import support_service as svc

    t, err = _ticket_or_error(db, ref)
    if err:
        return err
    assert t is not None
    changed: Dict[str, Any] = {}
    if category is not None:
        if category not in svc.CATEGORIES:
            return {
                "ok": False,
                "error": f"Unknown category '{category}'. Valid: {sorted(svc.CATEGORIES)}",
            }
        changed["category"] = {"from": t.category, "to": category}
        t.category = category
        t.priority = svc.CATEGORY_PRIORITY[category]
    if status is not None:
        if status not in svc.STATUSES:
            return {
                "ok": False,
                "error": f"Unknown status '{status}'. Valid: {list(svc.STATUSES)}",
            }
        changed["status"] = {"from": t.status, "to": status}
        t.status = status
        if status == "resolved" and not t.resolved_at:
            t.resolved_at = datetime.now(timezone.utc)
        if status == "spam":
            t.is_spam = True
    if changed:
        svc.emit_event(db, t, "status_change", actor="ai-assistant", payload=changed)
        db.commit()
    return {"ok": True, "ticket": _ticket_brief(db, t), "changed": changed}


def add_ticket_note(db: Session, ref: str, note: str) -> Dict[str, Any]:
    """Leave an internal note. Never emailed to the customer."""
    from . import support_service as svc

    t, err = _ticket_or_error(db, ref)
    if err:
        return err
    assert t is not None
    if not (note or "").strip():
        return {"ok": False, "error": "Note is empty."}
    svc.add_message(
        db,
        t,
        sender_kind="note",
        sender_name="ai-assistant",
        body_text=note.strip(),
        direction="internal",
    )
    svc.emit_event(db, t, "note", actor="ai-assistant", payload={})
    db.commit()
    return {"ok": True, "ref": t.ref}


def get_support_stats(db: Session, **_: Any) -> Dict[str, Any]:
    rows = db.execute(
        select(SupportTicket.status, func.count(SupportTicket.id)).group_by(
            SupportTicket.status
        )
    ).all()
    by_status = {str(s): int(n) for s, n in rows}
    return {
        "ok": True,
        "by_status": by_status,
        "needs_human": by_status.get("escalated", 0),
        "open": sum(
            by_status.get(s, 0)
            for s in ("new", "ai_handling", "escalated", "awaiting_customer")
        ),
        "total": sum(by_status.values()),
    }




def list_unconfirmed(db: Session, course_code: str, **_: Any) -> Dict[str, Any]:
    """Who has NOT replied to confirm their seat.

    The list Bassam actually chases. Cancelled rows are excluded — they
    already withdrew, so they are not outstanding.
    """
    course, err = _course_or_error(db, course_code)
    if err:
        return err
    rows = (
        db.execute(
            select(Registration).where(
                Registration.course_code == course_code,
                Registration.status != "cancelled",
            ).order_by(Registration.created_at)
        )
        .scalars()
        .all()
    )
    unconfirmed = [r for r in rows if r.attendance_confirmed_at is None]
    confirmed = [r for r in rows if r.attendance_confirmed_at is not None]

    # Cross-check against the support desk. If someone emailed a confirmation
    # and it is not reflected here, that gap is the single most useful thing
    # this tool can tell you — it is the difference between "they never
    # answered" and "they answered and we dropped it". Bassam once saw a reply
    # in Resend that the desk had recorded as a ticket but never applied to the
    # registration; nothing in this tool's output hinted at it, so the honest
    # answer looked like "nobody has confirmed".
    unconfirmed_addresses = {r.email.lower().strip() for r in unconfirmed}
    replied_but_unmarked: List[Dict[str, Any]] = []
    if unconfirmed_addresses:
        tickets = (
            db.execute(
                select(SupportTicket)
                .where(SupportTicket.category == "attendance")
                .order_by(SupportTicket.created_at.desc())
                .limit(200)
            )
            .scalars()
            .all()
        )
        for t in tickets:
            addr = (t.submitter_email or "").lower().strip()
            if addr in unconfirmed_addresses:
                replied_but_unmarked.append(
                    {
                        "email": t.submitter_email,
                        "ticket_ref": t.ref,
                        "ticket_status": t.status,
                        "summary": (t.ai_result or {}).get("summary", ""),
                        "subject": t.subject,
                        "received_at": _iso(t.created_at),
                    }
                )

    out = {
        "ok": True,
        "course_code": course_code,
        "total_active": len(rows),
        "confirmed_count": len(confirmed),
        "unconfirmed_count": len(unconfirmed),
        "unconfirmed": [_registration_summary(r) for r in unconfirmed],
        "confirmed": [_registration_summary(r) for r in confirmed],
        "replied_but_unmarked": replied_but_unmarked,
    }
    if replied_but_unmarked:
        out["warning"] = (
            f"{len(replied_but_unmarked)} of the unconfirmed registrants have an "
            "attendance ticket in the support desk — they appear to have replied "
            "without being marked confirmed. Read the ticket with get_ticket and, "
            "if they did confirm, record it with mark_attendance_confirmed."
        )
    return out


def mark_attendance_confirmed(db: Session, email: str) -> Dict[str, Any]:
    """Record that someone confirmed their seat — e.g. they told you by phone."""
    from . import support_service as svc

    confirmed = svc.confirm_attendance(db, email)
    if not confirmed:
        return {
            "ok": False,
            "error": f"No active registration found for '{email}'.",
        }
    db.commit()
    return {"ok": True, "confirmed": confirmed}




# ---------------------------------------------------------------------------
# The public website
# ---------------------------------------------------------------------------
#
# The assistant used to know every row in the database and nothing about
# the site those rows belong to. These read the live prerendered pages, so
# what it quotes is what a visitor actually sees today.


def list_site_pages(db: Session, **_: Any) -> Dict[str, Any]:
    from . import site_content

    pages = site_content.list_pages()
    if not pages:
        return {
            "ok": False,
            "error": "Could not read the website right now. Answer from the database instead, and say you could not check the site.",
        }
    return {"ok": True, "count": len(pages), "pages": pages}


def read_site_page(db: Session, path: str) -> Dict[str, Any]:
    from . import site_content

    page = site_content.read_page(path)
    if page is None:
        available = [p["path"] for p in site_content.list_pages()]
        return {
            "ok": False,
            "error": f"No public page at '{path}'.",
            "available_paths": available,
        }
    return {"ok": True, **page}


def search_site(db: Session, query: str, limit: int = 6) -> Dict[str, Any]:
    from . import site_content

    hits = site_content.search(query, limit=max(1, min(int(limit or 6), 15)))
    if not hits:
        return {
            "ok": True,
            "count": 0,
            "results": [],
            "note": f"Nothing on the website mentions '{query}'. Do not claim the site says something it does not.",
        }
    return {"ok": True, "count": len(hits), "results": hits}




def session_local_times(db: Session, course_code: str, **_: Any) -> Dict[str, Any]:
    """Session times in each registrant's own local zone.

    "17:00 for you in Saudi Arabia" beats "UTC+3". The arithmetic is done
    with the IANA database rather than by the model, because offsets move
    with the season and an hour wrong in a joining email is an attendee who
    misses the session.
    """
    from .local_times import local_schedule, resolve_zone

    course, err = _course_or_error(db, course_code)
    if err:
        return err

    regs = (
        db.execute(
            select(Registration).where(
                Registration.course_code == course_code,
                Registration.status != "cancelled",
            )
        )
        .scalars()
        .all()
    )

    def _zone_for(r: Registration) -> Optional[str]:
        # Company can disambiguate a city that cannot stand alone:
        # "Kingston" is four different places; "Kingston University London"
        # is not.
        return resolve_zone(r.location or "") or resolve_zone(r.company or "")

    zones_from_company = [z for z in (_zone_for(r) for r in regs) if z]
    out = local_schedule(
        session_time_utc=course.session_time_utc or "",
        duration_minutes=course.session_duration_minutes or 0,
        day_dates=[str(d) for d in (course.day_dates or [])],
        locations=[r.location or "" for r in regs],
        extra_zones=zones_from_company,
    )
    if not out.get("ok"):
        return out

    by_zone: Dict[str, List[str]] = {}
    unknown: List[Dict[str, str]] = []
    for r in regs:
        z = _zone_for(r)
        if z:
            by_zone.setdefault(z, []).append(f"{r.full_name} ({r.location})")
        else:
            unknown.append({"name": r.full_name, "location": r.location or "(blank)"})

    for zone in out["zones"]:
        zone["registrants"] = by_zone.get(zone["timezone"], [])
    # Drop zones nobody is actually in — a list of empty time zones in an
    # email is noise that makes the real ones harder to find.
    out["zones"] = [z for z in out["zones"] if z["registrants"]]
    out["course_code"] = course_code
    out["registrants_without_a_known_timezone"] = unknown
    if unknown:
        out["unknown_warning"] = (
            "These registrants' locations could not be matched to a timezone. "
            "Do NOT guess their local time — leave them to the UTC line, or "
            "ask Bassam where they are."
        )
    return out


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# Maps tool name -> handler. Handlers receive db as first positional arg,
# then kwargs from the model. Every name here must have a TOOL_SPECS entry
# and vice versa (enforced by tests).
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
    "get_course_stats": get_course_stats,
    "get_software_stats": get_software_stats,
    "list_software": list_software,
    "list_learners": list_learners,
    "get_email_log": get_email_log,
    "list_course_content": list_course_content,
    "find_person": find_person,
    "notify_product_buyers": notify_product_buyers,
    "grant_enrollment": grant_enrollment,
    "revoke_enrollment": revoke_enrollment,
    "update_lesson": update_lesson,
    "update_software": update_software,
    "list_tickets": list_tickets,
    "get_ticket": get_ticket,
    "reply_to_ticket": reply_to_ticket,
    "update_ticket": update_ticket,
    "add_ticket_note": add_ticket_note,
    "get_support_stats": get_support_stats,
    "list_unconfirmed": list_unconfirmed,
    "mark_attendance_confirmed": mark_attendance_confirmed,
    "list_site_pages": list_site_pages,
    "read_site_page": read_site_page,
    "search_site": search_site,
    "session_local_times": session_local_times,
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
        "List every live-cohort course with seats, pricing, schedule and its linked recorded_product_code. Read-only; use freely.",
        {"type": "object", "properties": {}, "required": []},
    ),
    _fn(
        "get_course",
        "Fetch full detail for a single course by its code.",
        {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Course code from list_courses."}},
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
                "session_time_utc": {"type": "string", "description": "Session start time in 24-hour UTC 'HH:MM'. Send '' to clear."},
                "session_duration_minutes": {"type": "integer", "description": "How long one session runs, in minutes."},
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
        "List live-cohort registrations. course_code is REQUIRED: a real course code, or 'all' for every course. Each row carries its own course_code. Filterable by status.",
        {
            "type": "object",
            "properties": {
                "course_code": {
                    "type": "string",
                    "description": "A course code from list_courses, or 'all' for every course.",
                },
                "status": {"type": "string", "enum": ["paid", "pending", "cancelled"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
            "required": ["course_code"],
        },
    ),
    _fn(
        "mark_paid",
        "Mark a single registration as paid (same side effects as the admin dashboard button). Use bulk_mark_paid for >1 row.",
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
        "Send an email broadcast to a course's audience. Body is PLAIN TEXT — newlines become paragraphs/<br>, links auto-link. Every send is written to the email log. Always requires admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain text. Backend converts to email HTML."},
                "audience": {
                    "type": "string",
                    "enum": ["all", "paid", "pending", "recorded", "everyone"],
                    "default": "all",
                    "description": "all = live paid+pending; recorded = active buyers of the linked recorded product; everyone = all + recorded.",
                },
            },
            "required": ["code", "subject", "body"],
        },
    ),
    _fn(
        "get_course_stats",
        "Per-course stats: live funnel (pending/paid/cancelled, seats, registrations by day, top companies) plus the linked recorded product's revenue/enrollments (null when no recorded twin). Omit course_code for all courses.",
        {
            "type": "object",
            "properties": {"course_code": {"type": "string"}},
            "required": [],
        },
    ),
    _fn(
        "get_software_stats",
        "Download / launch / usage telemetry per software product (totals, last-7/30-day windows, versions, top features). Omit slug for all products.",
        {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": [],
        },
    ),
    _fn(
        "list_software",
        "List every software product in the registry — hidden ones included — with telemetry counts and status.",
        {"type": "object", "properties": {}, "required": []},
    ),
    _fn(
        "list_learners",
        "List academy learners with enrollment summaries and progress counts. query = substring match on email or name; product_code = only that product's active enrollees.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring match on email or full name."},
                "product_code": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": [],
        },
    ),
    _fn(
        "get_email_log",
        "Recent outbound emails (broadcasts and transactional), newest first, with per-recipient success flags. scope_code filters to one course or product code.",
        {
            "type": "object",
            "properties": {
                "scope_code": {"type": "string", "description": "Course code or product code."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": [],
        },
    ),
    _fn(
        "list_course_content",
        "Module → lesson tree for a recorded academy product: ids, titles, kind, duration, video readiness, preview flags.",
        {
            "type": "object",
            "properties": {"product_code": {"type": "string", "description": "Academy product code, e.g. from a course's recorded_product_code."}},
            "required": ["product_code"],
        },
    ),
    _fn(
        "find_person",
        "Everything about one person by email, across the whole platform: cohort registrations (any course), learner record, enrollments and orders. Prefer this for 'who is X?' questions.",
        {
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
    ),
    _fn(
        "notify_product_buyers",
        "Email everyone holding active access to a recorded product. Body is PLAIN TEXT. Every send is written to the email log. Always requires admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain text. Backend converts to email HTML."},
            },
            "required": ["product_code", "subject", "body"],
        },
    ),
    _fn(
        "grant_enrollment",
        "Give a person access to a recorded product — creates the learner if needed and emails them a sign-in link. Always requires admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "product_code": {"type": "string"},
                "full_name": {"type": "string"},
            },
            "required": ["email", "product_code"],
        },
    ),
    _fn(
        "revoke_enrollment",
        "Revoke a person's access to a recorded product. Always requires admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "product_code": {"type": "string"},
            },
            "required": ["email", "product_code"],
        },
    ),
    _fn(
        "update_lesson",
        "Edit one lesson. fields may contain: title, body, is_preview, position. Always requires admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "lesson_id": {"type": "integer", "description": "Lesson id from list_course_content."},
                "fields": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "is_preview": {"type": "boolean"},
                        "position": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["lesson_id", "fields"],
        },
    ),
    _fn(
        "update_software",
        "Edit a software product. fields may contain: name, blurb, latest_version, status ('live'|'hidden'). Status changes (hide/show) require admin confirmation in chat.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "fields": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "blurb": {"type": "string"},
                        "latest_version": {"type": "string"},
                        "status": {"type": "string", "enum": ["live", "hidden"]},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["slug", "fields"],
        },
    ),
    _fn(
        "get_support_stats",
        "Support desk overview: how many tickets are open and how many are escalated (waiting on Bassam). Read-only; the fastest answer to 'what needs me today?'.",
        {"type": "object", "properties": {}, "required": []},
    ),
    _fn(
        "list_tickets",
        "List support tickets, most urgent first. Defaults to open tickets only. Read-only.",
        {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "'open' (default), 'all', or an exact status: new, ai_handling, awaiting_customer, escalated, auto_resolved, resolved, archived, spam.",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category: payment, access, bug, business, enrollment, course_info, software, general.",
                },
                "limit": {"type": "integer", "description": "Max rows, 1-100. Default 25."},
            },
            "required": [],
        },
    ),
    _fn(
        "get_ticket",
        "Read one support ticket in full: the whole message thread plus who the customer is (their registrations, enrolments and orders). Read this before drafting any reply — the customer context is what makes the reply accurate.",
        {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "8-character ticket ref, e.g. 7A3C91B2."}},
            "required": ["ref"],
        },
    ),
    _fn(
        "reply_to_ticket",
        "Email a reply to the customer on a ticket, as Bassam. Requires his approval before it sends. Call get_ticket first so the reply is grounded in their actual account state. Write plain prose — it is converted to email HTML. Do not add a sign-off or ticket reference; the system appends those.",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "8-character ticket ref."},
                "body": {"type": "string", "description": "The reply, in plain prose."},
                "resolve": {
                    "type": "boolean",
                    "description": "True to close the ticket after sending. Leave false when you expect them to answer.",
                },
            },
            "required": ["ref", "body"],
        },
    ),
    _fn(
        "update_ticket",
        "Change a ticket's status or fix its category. Never emails the customer — use reply_to_ticket for that.",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "status": {
                    "type": "string",
                    "description": "new, ai_handling, awaiting_customer, escalated, auto_resolved, resolved, archived, spam.",
                },
                "category": {
                    "type": "string",
                    "description": "payment, access, bug, business, enrollment, course_info, software, general. Priority follows automatically.",
                },
            },
            "required": ["ref"],
        },
    ),
    _fn(
        "add_ticket_note",
        "Leave an internal note on a ticket. Never emailed to the customer and never shown to the auto-replier — use it to record what was done off-platform (a call, a manual refund).",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["ref", "note"],
        },
    ),
    _fn(
        "list_unconfirmed",
        "For one cohort: who has confirmed their seat and who has not replied yet. Use this after sending a 'reply to confirm your attendance' broadcast, and before cancelling anyone. Read-only.",
        {
            "type": "object",
            "properties": {"course_code": {"type": "string", "description": "Course code from list_courses."}},
            "required": ["course_code"],
        },
    ),
    _fn(
        "mark_attendance_confirmed",
        "Record that a registrant confirmed their seat, when they told you outside email (a call, a message). Replies to a confirmation broadcast are recorded automatically by the support desk, so you rarely need this.",
        {
            "type": "object",
            "properties": {"email": {"type": "string", "description": "The registrant's email address."}},
            "required": ["email"],
        },
    ),
    _fn(
        "search_site",
        "Search the live public website (proreadyengineer.com) for a word or topic and get matching pages with excerpts. Use this whenever a question is about what the WEBSITE says — services, case studies, research insights, course descriptions, positioning, wording. Read-only.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for, e.g. 'hydrogen', 'test cell', 'emissions mapping'."},
                "limit": {"type": "integer", "description": "Max pages to return, 1-15. Default 6."},
            },
            "required": ["query"],
        },
    ),
    _fn(
        "read_site_page",
        "Read the full text of one public page exactly as a visitor sees it. Use after search_site, or when you know the path. Read-only.",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path such as /services/gas-turbine-combustion or /training."}},
            "required": ["path"],
        },
    ),
    _fn(
        "list_site_pages",
        "List every public page on the website with its title. Use to see what exists before searching or reading. Read-only.",
        {"type": "object", "properties": {}, "required": []},
    ),
    _fn(
        "session_local_times",
        "Session start and end times converted into the local timezone of every registrant on a cohort, from the locations they gave. Use this whenever an email has to tell people WHEN to attend. Daylight saving on each session date is handled for you — never do this arithmetic yourself. Registrants whose location cannot be matched to a timezone come back in their own list and must not be guessed at.",
        {
            "type": "object",
            "properties": {"course_code": {"type": "string", "description": "Course code from list_courses."}},
            "required": ["course_code"],
        },
    ),
]

# Tools that always require admin confirmation in chat.
HIGH_STAKES_ALWAYS = {
    "notify_course",
    "notify_product_buyers",
    "grant_enrollment",
    "revoke_enrollment",
    "update_lesson",
    # Puts words in Bassam's name in front of a customer. Reading and
    # triaging tickets is free; speaking for him is not.
    "reply_to_ticket",
}

# Tools that are high-stakes only at large size.
HIGH_STAKES_BULK_THRESHOLD = 3
HIGH_STAKES_BULK_TOOLS = {"bulk_mark_paid", "bulk_cancel"}


def is_high_stakes(tool_name: str, args: Dict[str, Any]) -> bool:
    if tool_name in HIGH_STAKES_ALWAYS:
        return True
    if tool_name in HIGH_STAKES_BULK_TOOLS:
        ids = args.get("registration_ids") or []
        return len(ids) >= HIGH_STAKES_BULK_THRESHOLD
    if tool_name == "update_software":
        # Hiding/showing a product changes the public site; metadata edits don't.
        return "status" in (args.get("fields") or {})
    return False


def summarize_call(tool_name: str, args: Dict[str, Any]) -> str:
    """Short human-readable summary used in the confirmation prompt."""
    if tool_name == "notify_course":
        aud = args.get("audience", "all")
        return (
            f"Send broadcast email to '{args.get('code', '?')}' "
            f"(audience: {aud}) — subject: \"{args.get('subject', '')[:80]}\""
        )
    if tool_name == "notify_product_buyers":
        return (
            f"Email all active buyers of product '{args.get('product_code', '?')}' "
            f"— subject: \"{args.get('subject', '')[:80]}\""
        )
    if tool_name == "grant_enrollment":
        return (
            f"Grant {args.get('email', '?')} access to "
            f"'{args.get('product_code', '?')}' (sends a sign-in link email)"
        )
    if tool_name == "revoke_enrollment":
        return (
            f"Revoke {args.get('email', '?')}'s access to "
            f"'{args.get('product_code', '?')}'"
        )
    if tool_name == "update_lesson":
        fields = sorted((args.get("fields") or {}).keys())
        return f"Update lesson {args.get('lesson_id', '?')} — fields: {fields}"
    if tool_name == "update_software":
        fields = sorted((args.get("fields") or {}).keys())
        return f"Update software '{args.get('slug', '?')}' — fields: {fields}"
    if tool_name == "reply_to_ticket":
        body = str(args.get("body", ""))
        preview = body[:160] + ("…" if len(body) > 160 else "")
        closing = " and mark it resolved" if args.get("resolve") else ""
        return (
            f"Email a reply to the customer on ticket #{args.get('ref', '?')}"
            f"{closing}:\n\n{preview}"
        )
    if tool_name in {"bulk_mark_paid", "bulk_cancel"}:
        ids = args.get("registration_ids") or []
        action = "Mark paid" if tool_name == "bulk_mark_paid" else "Cancel"
        return f"{action} {len(ids)} registration(s): {ids}"
    return f"{tool_name} with {args}"
