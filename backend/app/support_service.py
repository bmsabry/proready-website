"""Support desk: AI triage, auto-reply, escalation, and email threading.

The shape is ported from the ProMechDirectory support panel and adapted
to this platform. What happens to an incoming message:

    arrives (form / portal / email reply)
      -> classify with the LLM into a category + priority
      -> spam?                 -> park it, tell nobody
      -> sensitive category?   -> acknowledge, escalate to Bassam
      -> answerable?           -> answer it, resolve or await reply
      -> too many AI turns?    -> escalate; a customer stuck in a loop
                                  with a bot is worse than a slow human

Two rules run through the whole module:

  Never go silent. Every path that can be reached by a customer sends
  *something* — an answer, or an acknowledgement with a ticket ref. The
  failure mode that loses customers is a message that vanishes, so the
  LLM being down degrades to "we got it, a human will reply", never to
  nothing.

  Never invent. The classifier answers from admin-authored notes and from
  live database state (their actual registrations, enrolments, orders). If
  the answer is in neither, it is required to escalate rather than guess.
  A confident wrong answer about someone's money is worse than a slow one.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .crypto import CryptoNotConfigured, decrypt
from .emailer import send_email
from .models import (
    AISettings,
    Course,
    Enrollment,
    Learner,
    Order,
    Product,
    Registration,
    SupportTicket,
    SupportTicketEvent,
    SupportTicketMessage,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
#
# Category drives priority 1:1 and decides whether the AI may answer alone.
# Ordering is deliberate: anything touching someone's money or their access
# to material they already paid for goes to a human, always.

CATEGORIES: dict[str, str] = {
    "payment": "Billing, invoices, refunds, double charges, PayPal/Stripe problems, price questions about an order already placed.",
    "access": "Paid but can't get in: sign-in link not arriving, course/module locked, quiz app rejecting them, download or video failing for an enrolled learner.",
    "bug": "Something on the site or in the software is broken: an error page, a simulator or viewer misbehaving, a broken link.",
    "business": "Corporate or in-house training enquiries, partnerships, reselling, speaking, consulting, bulk seats.",
    "enrollment": "Wants to join a cohort: seat availability, dates, how to register, prerequisites, what payment options exist.",
    "course_info": "Questions about course content, syllabus, level, duration, certificates, recordings — from someone not yet enrolled.",
    "software": "Questions about the downloadable tools (Pro3DWorks and friends): what they do, system requirements, where to get them.",
    "attendance": "A registrant answering a message we sent asking them to confirm their seat on a cohort — 'yes I'll be there', 'confirming my attendance', 'I still plan to attend'. Only use this when they are CONFIRMING. Someone cancelling, asking to move dates, or asking a question is NOT this category.",
    "general": "Anything that does not clearly fit the categories above.",
}

CATEGORY_PRIORITY: dict[str, int] = {
    "payment": 1,
    "access": 2,
    "bug": 3,
    "business": 4,
    "enrollment": 5,
    "course_info": 6,
    "software": 7,
    "attendance": 8,
    "general": 9,
}

CATEGORY_LABEL: dict[str, str] = {
    "payment": "Payment",
    "access": "Access",
    "bug": "Bug",
    "business": "Business",
    "enrollment": "Enrollment",
    "course_info": "Course info",
    "software": "Software",
    "attendance": "Attendance",
    "general": "General",
}

# A human answers these. Money, blocked access, faults, and revenue leads:
# in every one of them a wrong automated answer costs more than a slow
# correct one. The customer still gets an instant acknowledgement.
ESCALATE_ALWAYS: set[str] = {"payment", "access", "bug", "business"}

# Two AI turns per ticket. Past that the customer is clearly not getting
# what they need and it goes to Bassam.
MAX_AI_ATTEMPTS = 2

# How long after a ticket closes a reply counts as a brand-new conversation
# rather than "your answer didn't help". Only past this does the AI get a
# fresh attempt budget — see ingest_inbound.
REOPEN_FRESH_AFTER = timedelta(days=3)

STATUSES = (
    "new",
    "ai_handling",
    "awaiting_customer",
    "escalated",
    "auto_resolved",
    "resolved",
    "archived",
    "spam",
)

# Statuses that mean "nobody is waiting on us".
CLOSED_STATUSES = {"auto_resolved", "resolved", "archived", "spam"}


# ---------------------------------------------------------------------------
# Identity of the desk
# ---------------------------------------------------------------------------


def support_from() -> str:
    """The From header for support mail.

    Deliberately the mail. subdomain: it is the Resend-verified sending
    domain (see the DKIM/SPF work that fixed spam-folder delivery) and it
    is the domain that carries inbound MX, so a customer hitting Reply
    lands back on the webhook rather than in a black hole.
    """
    return "ProReadyEngineer Support <info@mail.proreadyengineer.com>"


SUPPORT_ADDRESS = "info@mail.proreadyengineer.com"
SUPPORT_DOMAIN = "mail.proreadyengineer.com"

# Inbound mail is only ours if it was addressed to this domain.
#
# This guard is not paranoia — it is required. Resend webhooks subscribe to
# EVENT TYPES, not domains: there is no per-domain filter in the dashboard or
# the API. Every `email.received` in the account is delivered to every
# endpoint listening for it. This Resend account also serves
# promechdirectory.com, which has its own receiving domain and its own
# inbound webhook, so without this check each business would ingest the
# other's customers and auto-reply to them under the wrong brand.
RECEIVING_DOMAINS = {SUPPORT_DOMAIN}

# Mail from any of these is us. Auto-replying to our own address is how a
# support desk mails itself into a loop until the sending quota is gone.
OUR_ADDRESSES = {
    "info@mail.proreadyengineer.com",
    "noreply@mail.proreadyengineer.com",
    "support@mail.proreadyengineer.com",
    "info@proreadyengineer.com",
    "noreply@proreadyengineer.com",
}


def new_ref() -> str:
    """Customer-facing ticket reference — 8 uppercase hex chars."""
    return secrets.token_hex(4).upper()


def _aware(dt: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    SQLite hands back naive datetimes even for DateTime(timezone=True)
    columns, so comparing one against an aware `now()` raises. Postgres
    returns aware values and this is a no-op there.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Quoted-reply stripping
# ---------------------------------------------------------------------------
#
# An email reply carries the whole prior thread underneath it. We already
# store every message separately, so keeping the quote would show the
# conversation N times over and would feed the classifier its own previous
# output as if the customer had written it.

_QUOTE_MARKERS = [
    # Gmail / Apple Mail: "On <date>, <name> <addr> wrote:", possibly wrapped.
    re.compile(r"(?is)\n\s*On .{0,400}?\bwrote:\s*\n"),
    # Outlook and generic separators.
    re.compile(r"(?im)^\s*-{2,}\s*Original Message\s*-{2,}\s*$"),
    re.compile(r"(?im)^\s*_{5,}\s*$"),
    re.compile(r"(?im)^\s*From:\s.+$\n^\s*Sent:\s.+$"),
    re.compile(r"(?im)^\s*.{0,200}?<[^>]+@[^>]+>\s*wrote:\s*$"),
    # Our own outbound footer — belt and braces if a client quotes oddly.
    re.compile(r"(?im)^\s*--\s*\nProReadyEngineer Support\s*$"),
]


def strip_quoted_reply(body: str) -> str:
    """Return just the new text the sender typed.

    Conservative by design: if cutting at the earliest quote marker would
    leave nothing, the original is returned untouched. Showing a customer's
    message with some quoted noise attached is a cosmetic problem; dropping
    the message is a real one.
    """
    if not body or not body.strip():
        return body or ""
    text = body.replace("\r\n", "\n").replace("\r", "\n")

    cut = len(text)
    for pat in _QUOTE_MARKERS:
        m = pat.search(text)
        if m and m.start() < cut:
            cut = m.start()
    candidate = text[:cut]

    lines = candidate.split("\n")
    while lines and lines[-1].lstrip().startswith(">"):
        lines.pop()
    candidate = "\n".join(lines).strip()

    return candidate or body.strip()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def emit_event(
    db: Session,
    ticket: SupportTicket,
    event_type: str,
    *,
    actor: str = "",
    payload: Optional[dict] = None,
) -> SupportTicketEvent:
    """Append to the ticket's audit trail. Never updated, never deleted."""
    ev = SupportTicketEvent(
        ticket_id=ticket.id,
        event_type=event_type,
        actor=actor or "",
        payload=payload or {},
    )
    db.add(ev)
    return ev


def add_message(
    db: Session,
    ticket: SupportTicket,
    *,
    sender_kind: str,
    sender_name: str = "",
    body_text: str = "",
    body_html: str = "",
    direction: str = "form",
    email_message_id: str = "",
    email_delivered: Optional[bool] = None,
) -> SupportTicketMessage:
    msg = SupportTicketMessage(
        ticket_id=ticket.id,
        sender_kind=sender_kind,
        sender_name=sender_name or "",
        body_text=body_text or "",
        body_html=body_html or "",
        direction=direction,
        email_message_id=email_message_id or "",
        email_delivered=email_delivered,
    )
    db.add(msg)
    ticket.last_message_at = datetime.now(timezone.utc)
    if sender_kind == "customer":
        ticket.last_customer_message_at = ticket.last_message_at
    return msg


# ---------------------------------------------------------------------------
# Outbound mail
# ---------------------------------------------------------------------------


def _thread_message_id(ticket: SupportTicket, seq: int) -> str:
    """A Message-ID we choose, so replies are matchable even without headers.

    The ticket ref is embedded in the local part. If a mail client mangles
    In-Reply-To but keeps References — or keeps neither and only quotes the
    subject — the ref is still recoverable from one of the three.
    """
    return f"<pre-{ticket.ref.lower()}-{seq}@{SUPPORT_DOMAIN}>"


def subject_with_ref(ticket: SupportTicket, subject: Optional[str] = None) -> str:
    """Tag the subject with the ticket ref, exactly once.

    The `[#REF]` tag is the most durable threading signal there is: it
    survives forwards, clients that strip References, and a customer
    starting a fresh mail with the old subject pasted in.
    """
    base = (subject or ticket.subject or "Support request").strip()
    tag = f"[#{ticket.ref}]"
    if tag in base:
        return base
    return f"{base} {tag}"


def send_ticket_email(
    db: Session,
    ticket: SupportTicket,
    *,
    subject: Optional[str] = None,
    body_html: str,
    body_text: str = "",
    seq: Optional[int] = None,
) -> tuple[bool, str]:
    """Send one message on a ticket thread. Returns (delivered, message_id).

    Threading is set up three ways at once — our own Message-ID, the
    In-Reply-To/References chain, and the `[#REF]` subject tag — because
    real mail clients drop any one of them and the cost of a missed match
    is a duplicate ticket and a confused customer.
    """
    if seq is None:
        seq = (
            db.execute(
                select(func.count(SupportTicketMessage.id)).where(
                    SupportTicketMessage.ticket_id == ticket.id
                )
            ).scalar()
            or 0
        ) + 1

    message_id = _thread_message_id(ticket, seq)
    parent = ticket.email_message_id or ""

    html = _wrap_email_html(ticket, body_html)
    ok = send_email(
        to=ticket.submitter_email,
        subject=subject_with_ref(ticket, subject and f"Re: {subject}" or f"Re: {ticket.subject}"),
        html=html,
        text=body_text or None,
        db=db,
        scope_kind="support",
        scope_code=ticket.ref,
        audience="ticket",
        template="support_reply",
        from_override=support_from(),
        reply_to=SUPPORT_ADDRESS,
        headers={
            "Message-ID": message_id,
            "In-Reply-To": parent,
            "References": parent,
        },
    )

    # The first outbound message becomes the thread root that later replies
    # are matched against.
    if not ticket.email_message_id:
        ticket.email_message_id = message_id
    return ok, message_id


def _wrap_email_html(ticket: SupportTicket, inner: str) -> str:
    """House-style wrapper: the reply, then the ref, then a plain sign-off."""
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;line-height:1.6;color:#0f172a">'
        f"{inner}"
        '<p style="margin-top:28px;padding-top:14px;border-top:1px solid #e2e8f0;'
        'font-size:12px;color:#64748b">'
        f"Ticket reference <strong>#{ticket.ref}</strong> — reply to this email and it "
        "will be added to the same conversation."
        "</p>"
        "</div>"
    )


def notify_admin(db: Session, ticket: SupportTicket, reason: str) -> None:
    """Tell Bassam a ticket needs him. Never raises — this is a courtesy."""
    settings = get_settings()
    to = (settings.ADMIN_NOTIFY_EMAIL or "").strip()
    if not to:
        return
    try:
        preview = (ticket.body or "")[:600]
        html = (
            f"<p><strong>{reason}</strong></p>"
            f"<table style='font-family:sans-serif;font-size:14px;border-collapse:collapse'>"
            f"<tr><td style='padding:3px 12px 3px 0'><strong>Ref</strong></td><td>#{ticket.ref}</td></tr>"
            f"<tr><td style='padding:3px 12px 3px 0'><strong>From</strong></td>"
            f"<td>{ticket.submitter_name or '—'} &lt;{ticket.submitter_email}&gt;</td></tr>"
            f"<tr><td style='padding:3px 12px 3px 0'><strong>Subject</strong></td><td>{ticket.subject}</td></tr>"
            f"<tr><td style='padding:3px 12px 3px 0'><strong>Category</strong></td>"
            f"<td>{CATEGORY_LABEL.get(ticket.category, ticket.category)} (P{ticket.priority})</td></tr>"
            f"</table>"
            f"<pre style='white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;"
            f"padding:10px;border-radius:6px;font-size:13px'>{preview}</pre>"
            f"<p><a href='{settings.SITE_URL}/admin#support/{ticket.ref}'>Open in the admin panel</a></p>"
        )
        send_email(
            to=to,
            subject=f"[Support #{ticket.ref}] {ticket.subject}",
            html=html,
            db=db,
            scope_kind="support",
            scope_code=ticket.ref,
            audience="admin",
            template="support_admin_alert",
            from_override=support_from(),
        )
    except Exception:
        log.exception("[support] admin notification failed for ticket %s", ticket.ref)


# ---------------------------------------------------------------------------
# Customer context
# ---------------------------------------------------------------------------


def customer_context(db: Session, email: str) -> dict[str, Any]:
    """Everything we know about the person who wrote in, by email.

    This is what separates a useful auto-reply from a form letter: the
    model can say "your seat on the May cohort is marked paid" instead of
    "please check your records". It is also rendered in the admin thread
    view so Bassam has the account in front of him without going to look.
    """
    addr = (email or "").lower().strip()
    if not addr:
        return {"known": False}

    out: dict[str, Any] = {"email": addr, "known": False}

    regs = (
        db.execute(
            select(Registration)
            .where(func.lower(Registration.email) == addr)
            .order_by(desc(Registration.created_at))
            .limit(20)
        )
        .scalars()
        .all()
    )
    if regs:
        titles = {
            c.code: c.title
            for c in db.execute(select(Course)).scalars().all()
        }
        out["registrations"] = [
            {
                "id": r.id,
                "course_code": r.course_code,
                "course_title": titles.get(r.course_code, r.course_code),
                "status": r.status,
                "company": r.company,
                "full_name": r.full_name,
                "payment_provider": r.payment_provider or "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "paid_at": r.paid_at.isoformat() if r.paid_at else None,
                "attendance_confirmed_at": _aware(r.attendance_confirmed_at).isoformat()
                if r.attendance_confirmed_at
                else None,
            }
            for r in regs
        ]

    learner = db.execute(
        select(Learner).where(func.lower(Learner.email) == addr)
    ).scalar_one_or_none()
    if learner is not None:
        out["learner"] = {
            "id": learner.id,
            "full_name": learner.full_name or "",
            "created_at": learner.created_at.isoformat() if learner.created_at else None,
        }
        enrolls = (
            db.execute(
                select(Enrollment).where(Enrollment.learner_id == learner.id)
            )
            .scalars()
            .all()
        )
        if enrolls:
            pnames = {
                p.code: p.title
                for p in db.execute(select(Product)).scalars().all()
            }
            out["enrollments"] = [
                {
                    "product_code": e.product_code,
                    "product_title": pnames.get(e.product_code, e.product_code),
                    "status": e.status or "",
                    "settlement_status": e.settlement_status or "",
                    "granted_at": e.granted_at.isoformat() if e.granted_at else None,
                }
                for e in enrolls
            ]
        orders = (
            db.execute(
                select(Order)
                .where(Order.learner_id == learner.id)
                .order_by(desc(Order.created_at))
                .limit(10)
            )
            .scalars()
            .all()
        )
        if orders:
            out["orders"] = [
                {
                    "id": o.id,
                    "product_code": o.product_code or "",
                    "status": o.status or "",
                    "provider": o.provider or "",
                    "amount_cents": o.amount_cents,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in orders
            ]

    prior = (
        db.execute(
            select(SupportTicket)
            .where(func.lower(SupportTicket.submitter_email) == addr)
            .order_by(desc(SupportTicket.created_at))
            .limit(10)
        )
        .scalars()
        .all()
    )
    if prior:
        out["prior_tickets"] = [
            {
                "ref": t.ref,
                "subject": t.subject,
                "status": t.status,
                "category": t.category,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in prior
        ]

    out["known"] = bool(
        out.get("registrations") or out.get("learner") or out.get("enrollments")
    )
    return out


def platform_context(db: Session) -> dict[str, Any]:
    """Live facts about what's on sale, so the model quotes real dates.

    Rebuilt per classification rather than cached: a stale seat count in
    an auto-reply is exactly the kind of small wrong answer that costs a
    sale.
    """
    from .seats import count_active  # local import: avoids a cycle at module load

    courses = []
    for c in db.execute(select(Course)).scalars().all():
        try:
            # 'active' = paid + pending: a pending seat is held, so quoting
            # paid-only here would advertise seats that are already taken.
            taken = count_active(db, c.code)
        except Exception:
            taken = None
        courses.append(
            {
                "code": c.code,
                "title": c.title,
                "status": c.status,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "day_dates": list(c.day_dates or []),
                "total_seats": c.total_seats,
                "seats_taken": taken,
                "price_cents": c.price_cents,
                "currency": c.currency,
            }
        )

    products = [
        {
            "code": p.code,
            "title": p.title,
            "status": p.status or "",
        }
        for p in db.execute(select(Product)).scalars().all()
    ]
    return {"live_courses": courses, "recorded_products": products}


# ---------------------------------------------------------------------------
# LLM plumbing
# ---------------------------------------------------------------------------


def get_support_settings(db: Session) -> Optional[AISettings]:
    """The support LLM config, falling back to the admin assistant's.

    Support works the moment the assistant is configured; pointing support
    at a cheaper model is an optional refinement, not a prerequisite.
    """
    row = db.execute(
        select(AISettings).where(AISettings.scope == "support").limit(1)
    ).scalar_one_or_none()
    if row is not None and row.api_url and row.api_key_encrypted and row.model_name:
        return row
    fallback = db.execute(
        select(AISettings).where(AISettings.scope == "assistant").limit(1)
    ).scalar_one_or_none()
    if fallback is not None and (
        fallback.api_url and fallback.api_key_encrypted and fallback.model_name
    ):
        # Carry the support row's knowledge base across even when the
        # credentials come from the assistant.
        if row is not None and row.kb_text and not fallback.kb_text:
            fallback.kb_text = row.kb_text
        return fallback
    return None


def support_kb_text(db: Session) -> str:
    row = db.execute(
        select(AISettings).where(AISettings.scope == "support").limit(1)
    ).scalar_one_or_none()
    return (row.kb_text if row is not None else "") or ""


def _chat_url(api_url: str) -> str:
    url = (api_url or "").strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _call_support_llm(
    db: Session,
    messages: list[dict],
    *,
    json_mode: bool = True,
    max_tokens: int = 1100,
) -> Optional[dict]:
    """One LLM round trip. Returns parsed JSON, or None on any failure.

    Every failure mode returns None rather than raising: a support desk
    whose classifier is down must still take the message and acknowledge
    it. The caller's fallback path handles None.
    """
    row = get_support_settings(db)
    if row is None:
        log.warning("[support] no LLM configured — falling back to escalation")
        return None
    try:
        api_key = decrypt(row.api_key_encrypted)
    except CryptoNotConfigured:
        log.warning("[support] stored LLM key cannot be decrypted")
        return None
    if not api_key:
        return None

    payload: dict[str, Any] = {
        "model": row.model_name,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            resp = client.post(
                _chat_url(row.api_url),
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as e:
        log.error("[support] LLM transport error: %s", e)
        return None

    if resp.status_code >= 400:
        # Some OpenAI-compatible providers reject response_format. Retry
        # once without it rather than dropping to the fallback reply.
        if json_mode and resp.status_code in (400, 422):
            log.info("[support] provider rejected json mode; retrying plain")
            return _call_support_llm(
                db, messages, json_mode=False, max_tokens=max_tokens
            )
        log.error("[support] LLM HTTP %s: %s", resp.status_code, resp.text[:400])
        return None

    try:
        content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as e:
        log.error("[support] unexpected LLM response shape: %s", e)
        return None

    return _parse_json_object(content)


def _parse_json_object(content: str) -> Optional[dict]:
    """Pull a JSON object out of a model response.

    Models wrap JSON in ```json fences, prefix it with prose, or both.
    Strip the fence, then fall back to the outermost {...} span.
    """
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
            text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_system_prompt(db: Session) -> str:
    cat_lines = "\n".join(f'- "{k}": {v}' for k, v in CATEGORIES.items())
    prio_lines = "\n".join(
        f"  {CATEGORY_PRIORITY[k]} = {k}" for k in CATEGORY_PRIORITY
    )
    kb = support_kb_text(db).strip()
    kb_block = (
        f"\nADMIN-AUTHORED FACTS — these are authoritative, prefer them over your own\n"
        f"assumptions, and never contradict them:\n{kb}\n"
        if kb
        else "\nNo admin-authored notes are configured yet, so you have no approved\n"
        "policy statements. Do not invent policy — escalate anything that turns on\n"
        "refunds, deadlines, discounts, or commitments.\n"
    )

    return f"""\
You triage customer support for ProReadyEngineer — an engineering training
business run by Bassam Sabry. It sells live instructor-led cohorts, recorded
on-demand courses, and downloadable engineering software.

CLASSIFY FROM THE MESSAGE BODY, NOT THE SUBJECT. Subjects are routinely
vague ("question", "help", "hi") and are frequently wrong about the topic.
Read what the person actually wrote.

Categories:
{cat_lines}

Priority is determined by category, exactly:
{prio_lines}
{kb_block}
WRITING THE REPLY
- Address them by first name if you know it. Plain, direct, warm; no
  corporate padding, no "we value your inquiry".
- Use the supplied ACCOUNT CONTEXT to be specific. If it shows they are
  registered and paid on a cohort, say so. If it shows nothing, do not
  claim to have checked anything.
- Use the supplied PLATFORM CONTEXT for dates, seats and prices. Never
  state a date, price, or seat count that is not in it.
- HTML only: <p>, <ul>, <li>, <strong>, <a>. No headings, no inline styles.
  Under 180 words. Do not add a sign-off or a ticket reference — the system
  appends those.

WHEN NOT TO ANSWER
Set can_auto_resolve false, and write the reply as a short acknowledgement
only, whenever any of these is true:
- The category is payment, access, bug, or business.
- Answering would require a fact you were not given.
- They are asking for a refund, discount, extension, exception, or any
  commitment on Bassam's behalf.
- They are upset, or this is their second time asking the same thing.
- You are less than confident the answer is right.
Escalating costs a few hours. A confident wrong answer about someone's
money or access costs the customer.

Respond with ONLY a JSON object:
{{
  "category": one of {list(CATEGORIES.keys())},
  "priority": integer matching the category above,
  "is_spam": boolean — true only for bulk marketing, SEO/link-building
     pitches, crypto, or obvious automated junk. A clumsy or off-topic
     message from a real person is NOT spam.
  "confidence": float 0..1,
  "summary": one sentence, what they actually want,
  "reply_html": the HTML reply body per the rules above,
  "can_auto_resolve": boolean per the rules above,
  "escalation_reason": short string, or "" when auto-resolving
}}"""


def _thread_for_prompt(messages: list[SupportTicketMessage], limit: int = 12) -> str:
    out = []
    for m in messages[-limit:]:
        if m.sender_kind == "note":
            continue  # internal notes are for Bassam, not for the model's mouth
        who = {"customer": "CUSTOMER", "ai": "SUPPORT (auto)", "admin": "SUPPORT (human)"}.get(
            m.sender_kind, m.sender_kind.upper()
        )
        body = (m.body_text or _html_to_text(m.body_html)).strip()
        if body:
            out.append(f"--- {who} ---\n{body}")
    return "\n\n".join(out)


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def classify_ticket(
    db: Session,
    ticket: SupportTicket,
    messages: list[SupportTicketMessage],
) -> dict[str, Any]:
    """Classify and draft. Always returns a usable dict.

    On any LLM failure this returns the escalation fallback, so the caller
    never has to special-case "the model was down".
    """
    ctx = customer_context(db, ticket.submitter_email)
    plat = platform_context(db)

    user_prompt = (
        f"SUBJECT (may be misleading): {ticket.subject}\n\n"
        f"MESSAGE BODY (classify from this):\n{ticket.body or '(empty)'}\n\n"
        f"ACCOUNT CONTEXT for {ticket.submitter_email}:\n"
        f"{json.dumps(ctx, indent=2, default=str)}\n\n"
        f"PLATFORM CONTEXT (authoritative for dates, seats, prices):\n"
        f"{json.dumps(plat, indent=2, default=str)}\n"
    )
    thread = _thread_for_prompt(messages)
    if thread:
        user_prompt += f"\nCONVERSATION SO FAR:\n{thread}\n"
    if ticket.ai_attempt_count >= 1:
        user_prompt += (
            "\nNOTE: an automated reply has already been sent on this ticket and "
            "the customer has come back. Treat that as a signal the automated "
            "answer did not land — lean strongly toward can_auto_resolve=false.\n"
        )

    raw = _call_support_llm(
        db,
        [
            {"role": "system", "content": _classify_system_prompt(db)},
            {"role": "user", "content": user_prompt},
        ],
    )
    if raw is None:
        return _fallback_classification(ticket)

    return _sanitize_classification(raw, ticket)


def _sanitize_classification(raw: dict, ticket: SupportTicket) -> dict[str, Any]:
    """Coerce model output into something we can act on without trusting it.

    Everything here is defensive on purpose. The model decides *what kind*
    of message this is; it does not get to decide the routing rules. In
    particular an escalate-always category is forced to escalate no matter
    what the model set can_auto_resolve to.
    """
    cat = str(raw.get("category", "general"))
    cat = cat.strip().strip(":").lower().replace(" ", "_").replace("-", "_")
    if cat not in CATEGORIES:
        cat = "general"

    try:
        conf = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = min(max(conf, 0.0), 1.0)

    auto = bool(raw.get("can_auto_resolve", False))
    if cat in ESCALATE_ALWAYS:
        auto = False
    if conf < 0.55:
        # A model that isn't sure what it's reading has no business
        # answering unsupervised.
        auto = False

    reply = str(raw.get("reply_html", "") or "").strip()
    if reply and "<" not in reply:
        reply = "".join(
            f"<p>{p.strip()}</p>" for p in reply.split("\n\n") if p.strip()
        )

    return {
        "category": cat,
        "priority": CATEGORY_PRIORITY.get(cat, 8),
        "is_spam": bool(raw.get("is_spam", False)),
        "confidence": conf,
        "summary": str(raw.get("summary", "") or "")[:500],
        "reply_html": reply,
        "can_auto_resolve": auto,
        "escalation_reason": str(raw.get("escalation_reason", "") or "")[:300],
        "source": "llm",
    }


def _fallback_classification(ticket: SupportTicket) -> dict[str, Any]:
    """What we do when the model is unavailable: acknowledge and escalate."""
    name = (ticket.submitter_name or "").strip().split(" ")[0]
    greeting = f"<p>Hi {name},</p>" if name else "<p>Hello,</p>"
    return {
        "category": ticket.category or "general",
        "priority": CATEGORY_PRIORITY.get(ticket.category or "general", 8),
        "is_spam": False,
        "confidence": 0.0,
        "summary": "Automatic triage unavailable — needs manual review.",
        "reply_html": (
            f"{greeting}"
            "<p>Thanks for getting in touch with ProReadyEngineer. Your message has "
            "reached us and someone will reply personally within one business day.</p>"
        ),
        "can_auto_resolve": False,
        "escalation_reason": "Automatic triage unavailable",
        "source": "fallback",
    }


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def escalate(
    db: Session,
    ticket: SupportTicket,
    reason: str,
    *,
    actor: str = "",
    notify: bool = True,
) -> None:
    was = ticket.status
    ticket.status = "escalated"
    emit_event(
        db, ticket, "escalated", actor=actor, payload={"reason": reason, "from": was}
    )
    log.info("[support] ticket %s escalated: %s", ticket.ref, reason)
    if notify:
        notify_admin(db, ticket, reason)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def process_ticket(db: Session, ticket_id: int) -> None:
    """Triage a ticket that just received a customer message.

    Runs in a background task with its own session. Wrapped so a failure
    here can never take down the request that queued it — but a ticket
    that fails triage is still escalated rather than left silent.
    """
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        log.error("[support] ticket id=%s vanished before triage", ticket_id)
        return

    try:
        _process_ticket_inner(db, ticket)
    except Exception:
        log.exception("[support] triage failed for ticket %s", ticket.ref)
        db.rollback()
        # Re-fetch: the rollback detached whatever state we had.
        ticket = db.get(SupportTicket, ticket_id)
        if ticket is None:
            return
        try:
            _send_acknowledgement(db, ticket)
            escalate(db, ticket, "Triage failed — see server logs")
            db.commit()
        except Exception:
            log.exception("[support] escalation-after-failure also failed")
            db.rollback()


def _process_ticket_inner(db: Session, ticket: SupportTicket) -> None:
    messages = (
        db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == ticket.id)
            .order_by(SupportTicketMessage.created_at, SupportTicketMessage.id)
        )
        .scalars()
        .all()
    )

    ticket.status = "ai_handling"
    ticket.ai_attempt_count = (ticket.ai_attempt_count or 0) + 1
    attempt = ticket.ai_attempt_count

    result = classify_ticket(db, ticket, messages)

    ticket.category = result["category"]
    ticket.priority = result["priority"]
    ticket.is_spam = result["is_spam"]
    ticket.ai_result = result
    emit_event(
        db,
        ticket,
        "ai_classified",
        payload={
            "category": result["category"],
            "priority": result["priority"],
            "confidence": result["confidence"],
            "can_auto_resolve": result["can_auto_resolve"],
            "is_spam": result["is_spam"],
            "summary": result["summary"],
            "attempt": attempt,
            "source": result["source"],
        },
    )

    # --- Spam ------------------------------------------------------------
    # Parked silently. Replying to spam confirms the address is live, and
    # the sender is not waiting for an answer. It stays visible in the
    # Spam filter so a false positive can be recovered.
    if result["is_spam"]:
        ticket.status = "spam"
        emit_event(db, ticket, "spam_flagged", payload={"summary": result["summary"]})
        db.commit()
        log.info("[support] ticket %s parked as spam", ticket.ref)
        return

    # --- Too many automated turns ----------------------------------------
    if attempt > MAX_AI_ATTEMPTS:
        _send_acknowledgement(db, ticket, human_soon=True)
        escalate(db, ticket, f"Automated replies exhausted after {MAX_AI_ATTEMPTS} attempts")
        db.commit()
        return

    reply_html = result["reply_html"]

    # --- Human required ---------------------------------------------------
    if not result["can_auto_resolve"]:
        # Send the model's acknowledgement if it wrote a usable one, else
        # the stock one. Either way the customer hears back immediately.
        if reply_html:
            delivered, mid = send_ticket_email(db, ticket, body_html=reply_html)
            add_message(
                db,
                ticket,
                sender_kind="ai",
                sender_name="ProReadyEngineer Support",
                body_html=reply_html,
                body_text=_html_to_text(reply_html),
                direction="outbound",
                email_message_id=mid,
                email_delivered=delivered,
            )
            emit_event(db, ticket, "ai_replied", payload={"delivered": delivered, "kind": "acknowledgement"})
            if not ticket.first_responded_at:
                ticket.first_responded_at = datetime.now(timezone.utc)
        else:
            _send_acknowledgement(db, ticket)

        escalate(
            db,
            ticket,
            result["escalation_reason"]
            or f"Category '{result['category']}' is handled by a human",
        )
        db.commit()
        return

    # --- Attendance confirmation ------------------------------------------
    # A registrant answering "yes, I'll be there". Record it against their
    # registration so the unconfirmed list is a fact rather than an inbox
    # someone has to read, then thank them and close.
    if result["category"] == "attendance":
        confirmed = confirm_attendance(db, ticket.submitter_email)
        emit_event(
            db, ticket, "attendance_confirmed", payload={"courses": confirmed}
        )
        if confirmed:
            names = ", ".join(c["course_title"] for c in confirmed)
            ack = (
                f"<p>Thanks — your place on <strong>{names}</strong> is confirmed. "
                f"We'll send joining details before the first session.</p>"
            )
        else:
            # They confirmed, but we cannot find a registration under this
            # address. Do not tell them they are confirmed when they are not.
            ack = (
                "<p>Thanks for coming back to us. I could not match this email "
                "address to a registration, so I have passed it to Bassam to "
                "check personally.</p>"
            )
        delivered, mid = send_ticket_email(db, ticket, body_html=ack)
        add_message(
            db, ticket, sender_kind="ai", sender_name="ProReadyEngineer Support",
            body_html=ack, body_text=_html_to_text(ack), direction="outbound",
            email_message_id=mid, email_delivered=delivered,
        )
        if not ticket.first_responded_at:
            ticket.first_responded_at = datetime.now(timezone.utc)
        if confirmed and delivered:
            ticket.status = "auto_resolved"
            ticket.resolved_at = datetime.now(timezone.utc)
            emit_event(db, ticket, "auto_resolved", payload={"kind": "attendance"})
        else:
            escalate(
                db, ticket,
                "Attendance confirmation could not be matched to a registration"
                if not confirmed else "Confirmation reply could not be delivered",
            )
        db.commit()
        log.info(
            "[support] ticket %s attendance confirmed for %d registration(s)",
            ticket.ref, len(confirmed),
        )
        return

    # --- Answered automatically -------------------------------------------
    if not reply_html:
        # The model said it could answer but produced nothing. Don't guess.
        _send_acknowledgement(db, ticket)
        escalate(db, ticket, "Auto-reply was empty")
        db.commit()
        return

    delivered, mid = send_ticket_email(db, ticket, body_html=reply_html)
    add_message(
        db,
        ticket,
        sender_kind="ai",
        sender_name="ProReadyEngineer Support",
        body_html=reply_html,
        body_text=_html_to_text(reply_html),
        direction="outbound",
        email_message_id=mid,
        email_delivered=delivered,
    )
    if not ticket.first_responded_at:
        ticket.first_responded_at = datetime.now(timezone.utc)
    emit_event(db, ticket, "ai_replied", payload={"delivered": delivered, "kind": "answer"})

    if not delivered:
        # We had an answer and couldn't deliver it. That is exactly the
        # silent failure this module exists to avoid.
        escalate(db, ticket, "Auto-reply could not be delivered — Resend rejected the send")
        db.commit()
        return

    ticket.status = "auto_resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    emit_event(db, ticket, "auto_resolved", payload={"summary": result["summary"]})
    db.commit()
    log.info("[support] ticket %s auto-resolved (%s)", ticket.ref, result["category"])


def _send_acknowledgement(
    db: Session, ticket: SupportTicket, *, human_soon: bool = False
) -> None:
    """Stock 'we got it' reply. The one message that must never fail to go."""
    name = (ticket.submitter_name or "").strip().split(" ")[0]
    greeting = f"<p>Hi {name},</p>" if name else "<p>Hello,</p>"
    tail = (
        "<p>I'm passing this to Bassam directly so you get a proper answer rather "
        "than another automated one.</p>"
        if human_soon
        else "<p>Someone will reply to you personally within one business day.</p>"
    )
    html = (
        f"{greeting}"
        f"<p>Thanks for contacting ProReadyEngineer — your message about "
        f"<strong>{ticket.subject}</strong> has reached us.</p>{tail}"
    )
    delivered, mid = send_ticket_email(db, ticket, body_html=html)
    add_message(
        db,
        ticket,
        sender_kind="ai",
        sender_name="ProReadyEngineer Support",
        body_html=html,
        body_text=_html_to_text(html),
        direction="outbound",
        email_message_id=mid,
        email_delivered=delivered,
    )
    if not ticket.first_responded_at:
        ticket.first_responded_at = datetime.now(timezone.utc)
    emit_event(db, ticket, "ai_replied", payload={"delivered": delivered, "kind": "stock_ack"})


# ---------------------------------------------------------------------------
# Attendance confirmation
# ---------------------------------------------------------------------------


def confirm_attendance(db: Session, email: str) -> list[dict[str, Any]]:
    """Mark every open registration for this address as confirmed.

    Returns what was confirmed, so the caller can name the course back to
    the registrant instead of sending a vague "you're all set".

    Cancelled rows are skipped: someone who already withdrew and later
    replies to an old broadcast has not un-cancelled themselves.
    """
    addr = (email or "").lower().strip()
    if not addr:
        return []
    rows = (
        db.execute(
            select(Registration).where(
                func.lower(Registration.email) == addr,
                Registration.status != "cancelled",
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    titles = {c.code: c.title for c in db.execute(select(Course)).scalars().all()}
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for r in rows:
        # Idempotent: a second confirmation keeps the original timestamp, so
        # "when did they answer" stays true if they reply twice.
        if r.attendance_confirmed_at is None:
            r.attendance_confirmed_at = now
        out.append(
            {
                "registration_id": r.id,
                "course_code": r.course_code,
                "course_title": titles.get(r.course_code, r.course_code),
                "confirmed_at": _aware(r.attendance_confirmed_at).isoformat(),
            }
        )
    db.flush()
    return out


# ---------------------------------------------------------------------------
# Admin-side drafting
# ---------------------------------------------------------------------------


def draft_reply(
    db: Session, ticket: SupportTicket, instruction: str = ""
) -> dict[str, Any]:
    """Write a reply for Bassam to review, edit, and send.

    Distinct from the auto-reply path in one important way: this one is
    allowed to be more forthcoming, because a human reads it before it
    leaves. It still refuses to invent policy — it flags what it doesn't
    know instead, so the gap is visible in the editor rather than shipped
    to the customer.
    """
    messages = (
        db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == ticket.id)
            .order_by(SupportTicketMessage.created_at, SupportTicketMessage.id)
        )
        .scalars()
        .all()
    )
    ctx = customer_context(db, ticket.submitter_email)
    plat = platform_context(db)
    kb = support_kb_text(db).strip()

    system = f"""\
You draft support replies for Bassam Sabry, who runs ProReadyEngineer
(engineering training: live cohorts, recorded courses, downloadable software).

He reads and edits every word before it sends, so be useful and specific
rather than defensive. Write as him — first person, plain, direct, warm,
no corporate register, no "we apologise for any inconvenience".

Ground every factual claim in the ACCOUNT CONTEXT and PLATFORM CONTEXT
supplied below. If answering properly needs something you were not given
(a refund decision, an unlisted date, a discount), do NOT invent it: write
the reply around the gap and name the gap in "needs_from_admin" so he can
fill it in one edit.

{f"Approved facts and policy:{chr(10)}{kb}" if kb else "No policy notes are configured, so state no policy."}

Return ONLY a JSON object:
{{
  "reply_html": "<p>…</p>",   // HTML body: <p>, <ul>, <li>, <strong>, <a> only.
                              // No sign-off, no ticket reference — appended by the system.
  "needs_from_admin": ["short note about anything you could not answer"],
  "suggested_status": "resolved" | "awaiting_customer" | "escalated"
}}"""

    user = (
        f"TICKET #{ticket.ref} — {ticket.subject}\n"
        f"Category: {ticket.category} (P{ticket.priority}); status: {ticket.status}\n"
        f"From: {ticket.submitter_name or '—'} <{ticket.submitter_email}>\n\n"
        f"ACCOUNT CONTEXT:\n{json.dumps(ctx, indent=2, default=str)}\n\n"
        f"PLATFORM CONTEXT:\n{json.dumps(plat, indent=2, default=str)}\n\n"
        f"CONVERSATION:\n{_thread_for_prompt(messages, limit=20)}\n"
    )
    if instruction.strip():
        user += (
            f"\nBASSAM'S INSTRUCTION FOR THIS DRAFT — follow it over your own "
            f"judgement:\n{instruction.strip()}\n"
        )

    raw = _call_support_llm(
        db,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=1400,
    )
    if raw is None:
        return {
            "ok": False,
            "error": "The support AI is not configured or is unreachable. "
            "Check /admin → AI Assistant → Support settings.",
        }

    reply = str(raw.get("reply_html", "") or "").strip()
    if reply and "<" not in reply:
        reply = "".join(f"<p>{p.strip()}</p>" for p in reply.split("\n\n") if p.strip())
    gaps = raw.get("needs_from_admin") or []
    if isinstance(gaps, str):
        gaps = [gaps]

    emit_event(
        db,
        ticket,
        "ai_draft",
        payload={"instruction": instruction[:300], "gaps": gaps[:10]},
    )
    return {
        "ok": True,
        "reply_html": reply,
        "needs_from_admin": [str(g)[:300] for g in gaps][:10],
        "suggested_status": str(raw.get("suggested_status", "") or ""),
    }


# ---------------------------------------------------------------------------
# Inbound email
# ---------------------------------------------------------------------------

_REF_IN_SUBJECT = re.compile(r"\[#([0-9A-Fa-f]{8})\]")
_REF_IN_MSGID = re.compile(r"pre-([0-9a-f]{8})-\d+@")


def _match_ticket(
    db: Session,
    *,
    subject: str,
    in_reply_to: str,
    references: str,
    from_email: str,
) -> Optional[SupportTicket]:
    """Find the ticket an inbound email belongs to.

    Four strategies, cheapest and most reliable first. Mail clients are
    inconsistent enough that all four earn their place — a customer who
    replies from a phone, forwards to a colleague, or starts a new mail
    with the old subject should all land on the same thread.
    """
    # 1. Our ref embedded in the Message-ID we generated.
    for blob in (in_reply_to or "", references or ""):
        for m in _REF_IN_MSGID.finditer(blob):
            t = db.execute(
                select(SupportTicket).where(SupportTicket.ref == m.group(1).upper())
            ).scalar_one_or_none()
            if t is not None:
                return t

    # 2. The [#REF] subject tag.
    m = _REF_IN_SUBJECT.search(subject or "")
    if m:
        t = db.execute(
            select(SupportTicket).where(SupportTicket.ref == m.group(1).upper())
        ).scalar_one_or_none()
        if t is not None:
            return t

    # 3. A Message-ID we stored verbatim on a message or a ticket.
    ref_ids: list[str] = []
    if in_reply_to:
        ref_ids.append(in_reply_to.strip())
    if references:
        ref_ids.extend(r.strip() for r in references.split() if r.strip())
    for rid in ref_ids:
        if not rid:
            continue
        t = db.execute(
            select(SupportTicket).where(SupportTicket.email_message_id == rid)
        ).scalar_one_or_none()
        if t is not None:
            return t
        msg = db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.email_message_id == rid)
            .limit(1)
        ).scalar_one_or_none()
        if msg is not None:
            t = db.get(SupportTicket, msg.ticket_id)
            if t is not None:
                return t

    # 4. Same sender, same normalised subject, still open. Last resort —
    #    scoped to open tickets so an old closed thread isn't resurrected
    #    by an unrelated message that happens to share a subject.
    norm = _normalize_subject(subject)
    if norm:
        return db.execute(
            select(SupportTicket)
            .where(
                func.lower(SupportTicket.submitter_email) == from_email.lower().strip(),
                func.lower(SupportTicket.subject) == norm,
                SupportTicket.status.notin_(["archived", "spam"]),
            )
            .order_by(desc(SupportTicket.created_at))
            .limit(1)
        ).scalar_one_or_none()
    return None


def _normalize_subject(subject: str) -> str:
    s = (subject or "").strip()
    s = _REF_IN_SUBJECT.sub("", s).strip()
    for _ in range(5):  # "Re: Fwd: Re: ..." nests
        low = s.lower()
        for pfx in ("re:", "fwd:", "fw:", "aw:", "antwort:"):
            if low.startswith(pfx):
                s = s[len(pfx) :].strip()
                break
        else:
            break
    return s.lower()


def is_for_us(recipients: list[str] | str | None) -> bool:
    """True when an inbound email was addressed to one of our domains.

    Resend fans `email.received` out to every endpoint subscribed to that
    event across the whole account, with no per-domain filter, so an
    endpoint has to decide for itself whether a message is its business.

    Unknown/empty recipients return True: a message we cannot attribute is
    better handled as ours (it reaches a human) than dropped silently. The
    cross-brand leak this guards against always carries an explicit
    recipient, so the permissive fallback does not reopen it.
    """
    if not recipients:
        return True
    if isinstance(recipients, str):
        recipients = [recipients]
    seen_any = False
    for entry in recipients:
        if not isinstance(entry, str):
            continue
        for part in entry.split(","):
            part = part.strip().lower()
            if "<" in part and ">" in part:
                part = part.split("<", 1)[1].split(">", 1)[0].strip()
            if "@" not in part:
                continue
            seen_any = True
            if part.rsplit("@", 1)[-1] in RECEIVING_DOMAINS:
                return True
    return not seen_any


def ingest_inbound(
    db: Session,
    *,
    from_email: str,
    from_name: str,
    subject: str,
    body_text: str,
    body_html: str,
    in_reply_to: str = "",
    references: str = "",
    message_id: str = "",
    to: list[str] | str | None = None,
) -> tuple[Optional[SupportTicket], bool]:
    """Land an inbound email on a ticket. Returns (ticket, needs_triage).

    needs_triage is False when nothing should run — a duplicate webhook
    delivery, a message we sent ourselves, or mail for a different brand
    on the same Resend account.
    """
    addr = (from_email or "").lower().strip()
    if not addr:
        log.warning("[support] inbound with no sender — dropped")
        return None, False

    if addr in OUR_ADDRESSES:
        log.info("[support] inbound from our own address (%s) — ignored", addr)
        return None, False

    if not is_for_us(to):
        log.info(
            "[support] inbound addressed to %s — not one of our domains, ignored",
            to,
        )
        return None, False

    # Resend redelivers on any non-2xx, so the same Message-ID can arrive
    # repeatedly. Without this check a retry storm becomes a ticket storm.
    if message_id:
        dupe = db.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.email_message_id == message_id)
            .limit(1)
        ).scalar_one_or_none()
        if dupe is not None:
            log.info("[support] duplicate inbound message_id=%s — ignored", message_id[:60])
            return db.get(SupportTicket, dupe.ticket_id), False

    clean_text = strip_quoted_reply(body_text or "") or strip_quoted_reply(
        _html_to_text(body_html or "")
    )

    ticket = _match_ticket(
        db,
        subject=subject or "",
        in_reply_to=in_reply_to or "",
        references=references or "",
        from_email=addr,
    )
    is_new = ticket is None

    if is_new:
        ticket = SupportTicket(
            ref=new_ref(),
            submitter_email=addr,
            submitter_name=(from_name or "").strip()[:200],
            subject=(_readable_subject(subject) or "(no subject)")[:500],
            body=clean_text[:20000],
            status="new",
            source="inbound_email",
            last_customer_message_at=datetime.now(timezone.utc),
        )
        db.add(ticket)
        db.flush()
        emit_event(db, ticket, "created", payload={"source": "inbound_email"})
    else:
        assert ticket is not None
        if ticket.status in CLOSED_STATUSES and ticket.status != "spam":
            was = ticket.status
            ticket.status = "new"
            # Whether to hand the AI a fresh budget turns on *when* they
            # came back. Bouncing straight off an auto-resolution means the
            # answer did not work — resetting there would let the bot
            # re-answer forever and the attempt cap would never trip. A
            # reply weeks later is a new conversation that happens to reuse
            # an old thread, and does deserve a fresh budget.
            resolved = ticket.resolved_at
            stale = resolved is not None and (
                datetime.now(timezone.utc) - _aware(resolved) > REOPEN_FRESH_AFTER
            )
            if stale:
                ticket.ai_attempt_count = 0
            emit_event(
                db,
                ticket,
                "reopened",
                payload={"from": was, "ai_budget_reset": bool(stale)},
            )

    add_message(
        db,
        ticket,
        sender_kind="customer",
        sender_name=(from_name or addr)[:200],
        body_text=clean_text,
        body_html=body_html or "",
        direction="inbound",
        email_message_id=message_id or "",
    )
    emit_event(db, ticket, "customer_reply" if not is_new else "created", payload={})
    db.flush()

    # A reply on a ticket a human already took over goes straight to that
    # human. Re-triaging it would have the bot talk over Bassam mid-thread.
    needs_triage = ticket.status not in ("escalated", "spam")
    if not needs_triage and ticket.status == "escalated":
        notify_admin(db, ticket, "Customer replied on an escalated ticket")

    return ticket, needs_triage


def _readable_subject(subject: str) -> str:
    """Strip Re:/Fwd: and our own [#REF] tag for the stored subject."""
    s = _REF_IN_SUBJECT.sub("", subject or "").strip()
    for _ in range(5):
        low = s.lower()
        for pfx in ("re:", "fwd:", "fw:"):
            if low.startswith(pfx):
                s = s[len(pfx) :].strip()
                break
        else:
            break
    return s
