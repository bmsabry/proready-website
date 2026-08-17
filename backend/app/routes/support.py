"""Support desk routes — public intake, inbound email, and the admin panel.

Public (no auth):
  POST /api/support/contact                    — the website contact form
  POST /api/webhooks/resend-inbound            — Resend inbound email

Learner (learner session):
  POST /api/support/contact-portal             — signed-in "contact support"

Admin:
  GET   /api/admin/support/tickets             — inbox, filtered
  GET   /api/admin/support/stats               — counts for the badges
  GET   /api/admin/support/tickets/{ref}       — one thread, full
  POST  /api/admin/support/tickets/{ref}/reply — send a reply
  POST  /api/admin/support/tickets/{ref}/note  — internal note (never emailed)
  POST  /api/admin/support/tickets/{ref}/draft — ask the AI for a draft
  PATCH /api/admin/support/tickets/{ref}       — status / category / priority
  POST  /api/admin/support/tickets/{ref}/retriage — re-run the classifier
  GET   /api/admin/support/settings            — support AI config + KB
  PUT   /api/admin/support/settings

Triage runs in a FastAPI background task with its own session: an LLM call
plus an email send is several seconds, and a customer submitting a form
should not sit and watch that happen.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import support_service as svc
from ..config import get_settings
from ..crypto import CryptoNotConfigured, decrypt, encrypt
from ..db import SessionLocal, get_db
from ..deps import require_admin
from ..learner_auth import require_learner
from ..models import (
    AISettings,
    Learner,
    SupportTicket,
    SupportTicketEvent,
    SupportTicketMessage,
)

log = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api", tags=["support"])
admin_router = APIRouter(
    prefix="/api/admin/support",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------------
# Background triage
# ---------------------------------------------------------------------------


def _triage_later(ticket_id: int) -> None:
    """Run triage on its own session, swallowing everything.

    A background task that raises is invisible — FastAPI logs it and moves
    on, and the ticket sits untouched forever. process_ticket already
    escalates on internal failure; this layer only guards against the
    session itself failing to open.
    """
    db = SessionLocal()
    try:
        svc.process_ticket(db, ticket_id)
    except Exception:
        log.exception("[support] background triage crashed for ticket id=%s", ticket_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _ticket_row(t: SupportTicket, *, unread_from_customer: bool = False) -> dict:
    return {
        "ref": t.ref,
        "subject": t.subject,
        "submitter_email": t.submitter_email,
        "submitter_name": t.submitter_name or "",
        "category": t.category,
        "category_label": svc.CATEGORY_LABEL.get(t.category, t.category),
        "priority": t.priority,
        "status": t.status,
        "source": t.source,
        "is_spam": t.is_spam,
        "ai_attempt_count": t.ai_attempt_count,
        "summary": (t.ai_result or {}).get("summary", "") if t.ai_result else "",
        "created_at": _iso(t.created_at),
        "last_message_at": _iso(t.last_message_at or t.created_at),
        "last_customer_message_at": _iso(t.last_customer_message_at),
        "first_responded_at": _iso(t.first_responded_at),
        "resolved_at": _iso(t.resolved_at),
        "needs_reply": unread_from_customer,
    }


def _message_row(m: SupportTicketMessage) -> dict:
    return {
        "id": m.id,
        "sender_kind": m.sender_kind,
        "sender_name": m.sender_name or "",
        "body_text": m.body_text or "",
        "body_html": m.body_html or "",
        "direction": m.direction,
        "email_delivered": m.email_delivered,
        "created_at": _iso(m.created_at),
    }


def _event_row(e: SupportTicketEvent) -> dict:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "actor": e.actor or "",
        "payload": e.payload or {},
        "created_at": _iso(e.created_at),
    }


def _get_ticket(db: Session, ref: str) -> SupportTicket:
    t = db.execute(
        select(SupportTicket).where(SupportTicket.ref == ref.strip().upper())
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return t


def _messages(db: Session, ticket_id: int) -> list[SupportTicketMessage]:
    return list(
        db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == ticket_id)
            .order_by(SupportTicketMessage.created_at, SupportTicketMessage.id)
        )
        .scalars()
        .all()
    )


def _awaiting_us(db: Session, ticket: SupportTicket) -> bool:
    """True when the newest message on the thread came from the customer."""
    last = db.execute(
        select(SupportTicketMessage)
        .where(SupportTicketMessage.ticket_id == ticket.id)
        .order_by(desc(SupportTicketMessage.created_at), desc(SupportTicketMessage.id))
        .limit(1)
    ).scalar_one_or_none()
    return bool(last is not None and last.sender_kind == "customer")


# ---------------------------------------------------------------------------
# Public intake
# ---------------------------------------------------------------------------


class ContactIn(BaseModel):
    name: str = Field(default="", max_length=200)
    email: EmailStr
    subject: str = Field(default="", max_length=300)
    message: str = Field(min_length=1, max_length=20_000)
    # Honeypot. A real browser leaves it blank; bots fill every field they
    # find. Filled means "accept and discard" — telling a bot it failed
    # just teaches it to try again.
    website: str = ""


class ContactOut(BaseModel):
    ok: bool = True
    ref: str
    message: str


def _create_ticket(
    db: Session,
    *,
    email: str,
    name: str,
    subject: str,
    message: str,
    source: str,
    meta: dict,
) -> SupportTicket:
    ticket = SupportTicket(
        ref=svc.new_ref(),
        submitter_email=email.lower().strip(),
        submitter_name=(name or "").strip()[:200],
        subject=(subject or "").strip()[:500] or "Support request",
        body=message.strip(),
        status="new",
        source=source,
        last_customer_message_at=datetime.now(timezone.utc),
        meta=meta,
    )
    db.add(ticket)
    db.flush()
    svc.add_message(
        db,
        ticket,
        sender_kind="customer",
        sender_name=(name or email)[:200],
        body_text=message.strip(),
        direction="form",
    )
    svc.emit_event(db, ticket, "created", payload={"source": source})
    db.commit()
    return ticket


def _request_meta(request: Request) -> dict:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (
        request.client.host if request.client else ""
    )
    return {
        "ip": ip,
        "ua": request.headers.get("user-agent", "")[:400],
        "referer": request.headers.get("referer", "")[:400],
    }


@public_router.post("/support/contact", response_model=ContactOut, status_code=201)
def contact(
    payload: ContactIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ContactOut:
    """The public website contact form. Creates a ticket and triages it."""
    if payload.website.strip():
        # Honeypot tripped. Look exactly like success.
        return ContactOut(ref="00000000", message="Thanks — your message has been sent.")

    ticket = _create_ticket(
        db,
        email=str(payload.email),
        name=payload.name,
        subject=payload.subject,
        message=payload.message,
        source="contact_form",
        meta=_request_meta(request),
    )
    background.add_task(_triage_later, ticket.id)
    log.info("[support] ticket %s created from contact form (%s)", ticket.ref, ticket.submitter_email)
    return ContactOut(
        ref=ticket.ref,
        message="Thanks — your message has reached us. We'll reply by email shortly.",
    )


class PortalContactIn(BaseModel):
    subject: str = Field(default="", max_length=300)
    message: str = Field(min_length=1, max_length=20_000)
    context: str = Field(default="", max_length=200)
    website: str = ""


@public_router.post("/support/contact-portal", response_model=ContactOut, status_code=201)
def contact_portal(
    payload: PortalContactIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> ContactOut:
    """Signed-in learner support form.

    Identity comes from the session, never the request body — a learner
    must not be able to open a ticket as somebody else and read the reply.
    """
    if payload.website.strip():
        return ContactOut(ref="00000000", message="Thanks — your message has been sent.")

    meta = _request_meta(request)
    meta["portal_context"] = payload.context.strip()
    meta["learner_id"] = learner.id

    ticket = _create_ticket(
        db,
        email=learner.email,
        name=learner.full_name or learner.email,
        subject=payload.subject,
        message=payload.message,
        source="portal",
        meta=meta,
    )
    background.add_task(_triage_later, ticket.id)
    return ContactOut(
        ref=ticket.ref,
        message="Thanks — your message has reached us. We'll reply by email shortly.",
    )


# ---------------------------------------------------------------------------
# Inbound email webhook
# ---------------------------------------------------------------------------


def _pick(data: dict, body: dict, *names: str) -> str:
    """First non-empty value across both payload shapes and several spellings.

    Resend has shipped this webhook flat ({"from": …}) and wrapped
    ({"data": {"from": …}}), and field names vary between the inbound and
    the standard email object. Reading defensively is cheaper than
    breaking every time the payload shape moves.
    """
    for src in (data, body):
        if not isinstance(src, dict):
            continue
        for n in names:
            v = src.get(n)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _fetch_received_email(email_id: str) -> Optional[dict]:
    """Pull the full inbound message from Resend's receiving API.

    Returns None on any failure — the caller stores what it has and the
    ticket still reaches the inbox. A dropped body is recoverable (the
    ref, sender and subject are all there); a dropped ticket is not.
    """
    key = (get_settings().RESEND_API_KEY or "").strip()
    if not key:
        log.warning("[support] cannot fetch inbound body: RESEND_API_KEY is unset")
        return None
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"https://api.resend.com/emails/receiving/{email_id}",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as e:
        log.error("[support] inbound body fetch failed for %s: %s", email_id, e)
        return None
    if resp.status_code >= 300:
        log.error(
            "[support] inbound body fetch for %s returned %s: %s",
            email_id,
            resp.status_code,
            resp.text[:300],
        )
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _parse_from(raw: str, headers: dict) -> tuple[str, str]:
    """Split a From header into (email, display name)."""
    src = raw or ""
    if "<" in src and ">" in src:
        name = src.split("<", 1)[0].strip().strip('"')
        addr = src.split("<", 1)[1].split(">", 1)[0].strip()
        return addr.lower(), name
    addr = src.strip().lower()
    hdr = headers.get("from") or headers.get("From") or ""
    if hdr and "<" in hdr:
        return addr, hdr.split("<", 1)[0].strip().strip('"')
    return addr, ""


@public_router.post("/webhooks/resend-inbound", status_code=200)
async def resend_inbound(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """Receive an inbound email from Resend and thread it onto a ticket.

    Always returns 200, whatever happens. A non-2xx makes Resend retry the
    same message on a schedule, and a payload we can't parse will fail
    identically on every retry — so a bad message would be redelivered
    forever. Failures are logged and swallowed instead.

    Async only to read the request body; the handler is synchronous ORM
    work, so it runs in the threadpool rather than blocking the loop.
    """
    try:
        body = await request.json()
    except Exception:
        log.warning("[support] inbound webhook: body was not JSON")
        return {"ok": True}
    if not isinstance(body, dict):
        log.warning("[support] inbound webhook: body was %s, not an object", type(body).__name__)
        return {"ok": True}
    return await run_in_threadpool(_handle_inbound, body, background, db)


def _handle_inbound(body: dict, background: BackgroundTasks, db: Session) -> dict:
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    headers = data.get("headers") or body.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    # Some providers send headers as a list of {name, value} pairs.
    if isinstance(data.get("headers"), list):
        headers = {
            str(h.get("name", "")).lower(): str(h.get("value", ""))
            for h in data["headers"]
            if isinstance(h, dict)
        }

    from_email, from_name = _parse_from(_pick(data, body, "from"), headers)
    if not from_email:
        log.warning("[support] inbound webhook: no sender; keys=%s", list(body)[:12])
        return {"ok": True}

    subject = _pick(data, body, "subject") or "(no subject)"
    body_text = _pick(data, body, "text", "plain", "textBody", "text_body")
    body_html = _pick(data, body, "html", "htmlBody", "html_body")

    def _hdr(*names: str) -> str:
        for n in names:
            v = headers.get(n) or headers.get(n.lower()) or headers.get(n.title())
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    in_reply_to = _hdr("in-reply-to", "In-Reply-To") or _pick(
        data, body, "inReplyTo", "in_reply_to"
    )
    references = _hdr("references", "References") or _pick(data, body, "references")
    message_id = _hdr("message-id", "Message-ID") or _pick(
        data, body, "messageId", "message_id"
    )

    # Resend's email.received webhook carries metadata ONLY — no body, no
    # headers. The full message has to be fetched by id, or every inbound
    # reply lands as an empty message. (Older/other payload shapes do
    # include the body inline, hence the check rather than an
    # unconditional fetch.)
    email_id = _pick(data, body, "email_id", "id")
    if (not body_text and not body_html) and email_id:
        fetched = _fetch_received_email(email_id)
        if fetched:
            subject = fetched.get("subject") or subject
            body_text = fetched.get("text") or body_text
            body_html = fetched.get("html") or body_html
            fh = fetched.get("headers")
            if isinstance(fh, dict):
                lowered = {str(k).lower(): str(v) for k, v in fh.items()}
                in_reply_to = in_reply_to or lowered.get("in-reply-to", "")
                references = references or lowered.get("references", "")
                message_id = message_id or lowered.get("message-id", "")

    if not body_text and not body_html:
        log.warning(
            "[support] inbound from %s had no body (subject=%r, email_id=%r) — "
            "stored empty; check RESEND_API_KEY and the receiving API",
            from_email,
            subject[:80],
            email_id,
        )

    try:
        ticket, needs_triage = svc.ingest_inbound(
            db,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            in_reply_to=in_reply_to,
            references=references,
            message_id=message_id,
        )
        db.commit()
    except Exception:
        log.exception("[support] inbound ingest failed for %s", from_email)
        db.rollback()
        return {"ok": True}

    if ticket is not None and needs_triage:
        background.add_task(_triage_later, ticket.id)
    if ticket is not None:
        log.info(
            "[support] inbound from %s -> ticket %s (triage=%s)",
            from_email,
            ticket.ref,
            needs_triage,
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin — inbox
# ---------------------------------------------------------------------------


@admin_router.get("/stats")
def support_stats(db: Session = Depends(get_db)) -> dict:
    """Counts for the sidebar badge and the inbox filter chips."""
    rows = db.execute(
        select(SupportTicket.status, func.count(SupportTicket.id)).group_by(
            SupportTicket.status
        )
    ).all()
    by_status = {str(s): int(n) for s, n in rows}

    cat_rows = db.execute(
        select(SupportTicket.category, func.count(SupportTicket.id))
        .where(SupportTicket.status.notin_(["archived", "spam"]))
        .group_by(SupportTicket.category)
    ).all()

    open_statuses = ["new", "ai_handling", "escalated", "awaiting_customer"]
    return {
        "by_status": by_status,
        "by_category": {str(c): int(n) for c, n in cat_rows},
        "open": sum(by_status.get(s, 0) for s in open_statuses),
        # The number that actually matters: tickets a human has to answer.
        "needs_human": by_status.get("escalated", 0),
        "total": sum(by_status.values()),
    }


@admin_router.get("/tickets")
def list_tickets(
    status_filter: str = "",
    category: str = "",
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    """Inbox listing.

    Default view (no status filter) hides archived and spam — an inbox
    that shows everything ever received is not an inbox. Sorted by
    priority then recency so P1 payment problems sit at the top.
    """
    limit = max(1, min(limit, 500))
    stmt = select(SupportTicket)

    if status_filter == "open":
        stmt = stmt.where(
            SupportTicket.status.in_(["new", "ai_handling", "escalated", "awaiting_customer"])
        )
    elif status_filter:
        stmt = stmt.where(SupportTicket.status == status_filter)
    else:
        stmt = stmt.where(SupportTicket.status.notin_(["archived", "spam"]))

    if category:
        stmt = stmt.where(SupportTicket.category == category)

    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(SupportTicket.subject).like(like)
            | func.lower(SupportTicket.submitter_email).like(like)
            | func.lower(SupportTicket.submitter_name).like(like)
            | (SupportTicket.ref == q.strip().upper())
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0

    rows = (
        db.execute(
            stmt.order_by(
                SupportTicket.priority.asc(),
                desc(func.coalesce(SupportTicket.last_message_at, SupportTicket.created_at)),
            )
            .offset(max(0, offset))
            .limit(limit)
        )
        .scalars()
        .all()
    )

    # One query for "who spoke last" across the whole page, rather than one
    # per ticket — the inbox is the most-hit admin view there is.
    ids = [t.id for t in rows]
    awaiting: set[int] = set()
    if ids:
        newest = (
            select(
                SupportTicketMessage.ticket_id.label("tid"),
                func.max(SupportTicketMessage.id).label("mid"),
            )
            .where(SupportTicketMessage.ticket_id.in_(ids))
            .group_by(SupportTicketMessage.ticket_id)
            .subquery()
        )
        for tid, kind in db.execute(
            select(SupportTicketMessage.ticket_id, SupportTicketMessage.sender_kind).join(
                newest, SupportTicketMessage.id == newest.c.mid
            )
        ).all():
            if kind == "customer":
                awaiting.add(int(tid))

    return {
        "total": total,
        "items": [_ticket_row(t, unread_from_customer=t.id in awaiting) for t in rows],
    }


@admin_router.get("/tickets/{ref}")
def get_ticket(ref: str, db: Session = Depends(get_db)) -> dict:
    """One ticket: the thread, the audit trail, and who the customer is."""
    t = _get_ticket(db, ref)
    return {
        "ticket": _ticket_row(t, unread_from_customer=_awaiting_us(db, t)),
        "ai_result": t.ai_result or {},
        "meta": t.meta or {},
        "messages": [_message_row(m) for m in _messages(db, t.id)],
        "events": [
            _event_row(e)
            for e in db.execute(
                select(SupportTicketEvent)
                .where(SupportTicketEvent.ticket_id == t.id)
                .order_by(SupportTicketEvent.created_at, SupportTicketEvent.id)
            )
            .scalars()
            .all()
        ],
        "customer": svc.customer_context(db, t.submitter_email),
    }


# ---------------------------------------------------------------------------
# Admin — actions
# ---------------------------------------------------------------------------


class ReplyIn(BaseModel):
    body_html: str = Field(min_length=1, max_length=100_000)
    # What the ticket becomes after sending. 'resolved' closes it;
    # 'awaiting_customer' keeps it open pending their answer.
    set_status: str = Field(default="awaiting_customer")


@admin_router.post("/tickets/{ref}/reply")
def reply(
    ref: str,
    payload: ReplyIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Send an admin reply on the thread."""
    t = _get_ticket(db, ref)
    delivered, mid = svc.send_ticket_email(db, t, body_html=payload.body_html)

    svc.add_message(
        db,
        t,
        sender_kind="admin",
        sender_name="Bassam Sabry",
        body_html=payload.body_html,
        body_text=svc._html_to_text(payload.body_html),
        direction="outbound",
        email_message_id=mid,
        email_delivered=delivered,
    )
    if not t.first_responded_at:
        t.first_responded_at = datetime.now(timezone.utc)

    new_status = payload.set_status if payload.set_status in svc.STATUSES else "awaiting_customer"
    # A reply that Resend refused has not reached anyone. Marking the
    # ticket resolved on the strength of a send that failed is how a
    # customer ends up ignored with the ticket closed.
    if not delivered:
        new_status = "escalated"
    was, t.status = t.status, new_status
    if new_status == "resolved":
        t.resolved_at = datetime.now(timezone.utc)

    svc.emit_event(
        db,
        t,
        "admin_reply",
        actor=admin,
        payload={"delivered": delivered, "from": was, "to": new_status},
    )
    db.commit()
    return {
        "ok": True,
        "delivered": delivered,
        "status": t.status,
        "warning": "" if delivered else
        "The email could not be sent (Resend rejected it or the API key is unset). "
        "The message is saved on the thread and the ticket was left open.",
    }


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)


@admin_router.post("/tickets/{ref}/note")
def add_note(
    ref: str,
    payload: NoteIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Attach an internal note. Never emailed, never shown to the AI."""
    t = _get_ticket(db, ref)
    svc.add_message(
        db,
        t,
        sender_kind="note",
        sender_name=admin,
        body_text=payload.body,
        direction="internal",
    )
    svc.emit_event(db, t, "note", actor=admin, payload={})
    db.commit()
    return {"ok": True}


class DraftIn(BaseModel):
    instruction: str = Field(default="", max_length=4000)


@admin_router.post("/tickets/{ref}/draft")
def draft(
    ref: str,
    payload: DraftIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Ask the AI for a reply draft. Never sends — the editor gets it."""
    t = _get_ticket(db, ref)
    result = svc.draft_reply(db, t, payload.instruction)
    db.commit()
    if not result.get("ok"):
        raise HTTPException(status_code=412, detail=result.get("error", "Draft failed."))
    return result


class PatchIn(BaseModel):
    status: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None


@admin_router.patch("/tickets/{ref}")
def patch_ticket(
    ref: str,
    payload: PatchIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Override what the classifier decided, or move the ticket's status."""
    t = _get_ticket(db, ref)
    changes: dict[str, Any] = {}

    if payload.category is not None:
        if payload.category not in svc.CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Unknown category '{payload.category}'.")
        changes["category"] = {"from": t.category, "to": payload.category}
        t.category = payload.category
        # Priority follows category unless the same request overrides it.
        if payload.priority is None:
            t.priority = svc.CATEGORY_PRIORITY[payload.category]

    if payload.priority is not None:
        if not 1 <= payload.priority <= 9:
            raise HTTPException(status_code=400, detail="Priority must be 1–9.")
        changes["priority"] = {"from": t.priority, "to": payload.priority}
        t.priority = payload.priority

    if payload.status is not None:
        if payload.status not in svc.STATUSES:
            raise HTTPException(status_code=400, detail=f"Unknown status '{payload.status}'.")
        changes["status"] = {"from": t.status, "to": payload.status}
        t.status = payload.status
        if payload.status == "resolved" and not t.resolved_at:
            t.resolved_at = datetime.now(timezone.utc)
        if payload.status == "spam":
            t.is_spam = True
        elif t.is_spam and payload.status != "archived":
            # Pulling a ticket out of spam clears the flag; otherwise it
            # would keep reading as spam everywhere else in the UI.
            t.is_spam = False

    if changes:
        svc.emit_event(db, t, "status_change", actor=admin, payload=changes)
    db.commit()
    return {"ok": True, "ticket": _ticket_row(t)}


@admin_router.post("/tickets/{ref}/retriage")
def retriage(
    ref: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Re-run the classifier — after editing the knowledge base, say.

    Resets the attempt counter so the AI is allowed to answer again; the
    admin asking for this is an explicit override of the exhaustion rule.
    """
    t = _get_ticket(db, ref)
    t.ai_attempt_count = 0
    svc.emit_event(db, t, "status_change", actor=admin, payload={"retriage": True})
    db.commit()
    background.add_task(_triage_later, t.id)
    return {"ok": True}


class BulkIn(BaseModel):
    refs: list[str] = Field(min_length=1, max_length=500)
    action: str  # 'archive' | 'resolve' | 'spam'


@admin_router.post("/tickets/bulk")
def bulk(
    payload: BulkIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> dict:
    """Archive / resolve / spam several tickets at once.

    Explicitly enumerated refs only — no "apply to everything matching the
    current filter", which is the shape that turns a mis-click into a
    wiped inbox.
    """
    if payload.action not in ("archive", "resolve", "spam"):
        raise HTTPException(status_code=400, detail="action must be archive, resolve or spam.")
    target = {"archive": "archived", "resolve": "resolved", "spam": "spam"}[payload.action]

    refs = [r.strip().upper() for r in payload.refs if r.strip()]
    rows = (
        db.execute(select(SupportTicket).where(SupportTicket.ref.in_(refs)))
        .scalars()
        .all()
    )
    for t in rows:
        was = t.status
        t.status = target
        if target == "resolved" and not t.resolved_at:
            t.resolved_at = datetime.now(timezone.utc)
        if target == "spam":
            t.is_spam = True
        svc.emit_event(
            db, t, "status_change", actor=admin, payload={"from": was, "to": target, "bulk": True}
        )
    db.commit()
    return {"ok": True, "updated": len(rows)}


# ---------------------------------------------------------------------------
# Admin — support AI settings
# ---------------------------------------------------------------------------


class SupportSettingsIn(BaseModel):
    """Save payload. An empty api_key means "keep the stored one"."""

    model_config = ConfigDict(protected_namespaces=())

    api_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=500)
    model_name: str = Field(default="", max_length=200)
    kb_text: str = Field(default="", max_length=60_000)


def _support_settings_row(db: Session) -> AISettings:
    row = db.execute(
        select(AISettings).where(AISettings.scope == "support").limit(1)
    ).scalar_one_or_none()
    if row is None:
        row = AISettings(scope="support")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _settings_out(db: Session, row: AISettings) -> dict:
    masked = ""
    if row.api_key_encrypted:
        try:
            plain = decrypt(row.api_key_encrypted)
            masked = f"…{plain[-4:]}" if len(plain) >= 4 else "…"
        except CryptoNotConfigured:
            masked = "(unreadable — AI_SETTINGS_KEY changed)"
    active = svc.get_support_settings(db)
    return {
        "api_url": row.api_url or "",
        "model_name": row.model_name or "",
        "api_key_masked": masked,
        "kb_text": row.kb_text or "",
        "is_configured": bool(row.api_url and row.api_key_encrypted and row.model_name),
        # False here means support is borrowing the assistant's credentials.
        "using_own_credentials": bool(
            active is not None and active.scope == "support"
        ),
        "llm_available": active is not None,
        "categories": [
            {
                "key": k,
                "label": svc.CATEGORY_LABEL[k],
                "priority": svc.CATEGORY_PRIORITY[k],
                "auto": k not in svc.ESCALATE_ALWAYS,
                "description": v,
            }
            for k, v in svc.CATEGORIES.items()
        ],
    }


@admin_router.get("/settings")
def get_support_settings(db: Session = Depends(get_db)) -> dict:
    return _settings_out(db, _support_settings_row(db))


@admin_router.put("/settings")
def put_support_settings(
    payload: SupportSettingsIn, db: Session = Depends(get_db)
) -> dict:
    row = _support_settings_row(db)
    row.api_url = payload.api_url.strip()
    row.model_name = payload.model_name.strip()
    row.kb_text = payload.kb_text
    # An empty key means "leave the stored one alone" — the UI only ever
    # shows the mask, so re-saving the KB must not wipe the credential.
    if payload.api_key.strip():
        try:
            row.api_key_encrypted = encrypt(payload.api_key.strip())
        except CryptoNotConfigured as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
    db.commit()
    db.refresh(row)
    return _settings_out(db, row)
