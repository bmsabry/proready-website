"""Watching what happens to customer emails after they leave.

Why (2026-11-09): a registrant's confirmation was refused by Hotmail
("Message lacks SPF/DKIM/DMARC Auth Records") and nobody knew. The site
only asked Resend about an email when it was opened in Admin -> Comms, so a
trainee whose email bounced simply waited, and the instructor heard of it
from the trainee.

The cron job calls `sweep` every 10 minutes:

  * every customer email sent in the last WATCH_HOURS whose outcome is not
    settled yet is looked up in Resend (email_copies.refresh), so Comms
    shows Delivered / Bounced without anyone opening the email;
  * an email that bounced, was suppressed, failed or was marked as spam,
    or that Resend never accepted, gets ONE alert to ADMIN_NOTIFY_EMAIL
    saying who the person is and what to do.

Emails to the instructor himself are not watched: an email telling him an
email to him bounced would reach nobody.

The once-only marker is the alert's own OK EmailLog row (template
`delivery_problem`, scope_code `email:<id>`), the pattern the session
reminders use: a failed alert leaves no OK row, so the next run tries again.

Resend's API does not give the bounce reason; its webhook does. When the
webhook is configured (RESEND_WEBHOOK_SECRET), `apply_event` records the
receiving server's own words on the row and alerts within seconds; the sweep
stays as the safety net for anything the webhook misses.

Two more guards run from the same cron call (`checks`):

  * the DNS records email depends on (DMARC, DKIM, SPF, the MX records for
    sending feedback, the support desk and Google Workspace) are looked up
    every run; a missing or changed record alerts at most once a day;
  * once a day a short "canary" email goes to the instructor's own
    mailboxes at other providers (CANARY_EMAILS). The sweep watches it like
    any customer email, so a provider that starts refusing our mail shows up
    on a test mailbox before it reaches a trainee.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import email_copies as copies
from .config import get_settings
from .emailer import (
    delivery_canary_html,
    delivery_problem_html,
    email_setup_problem_html,
    send_email,
)
from .models import Course, EmailLog, Learner, Registration

log = logging.getLogger(__name__)

ALERT_TEMPLATE = "delivery_problem"
# How long after sending an email is still watched. Delivery is normally
# settled within a minute; Resend retries a delayed one for hours.
WATCH_HOURS = 72
# Resend allows 2 requests a second; the pause keeps under it, and the cap
# bounds one run (the cron calls again in 10 minutes).
PAUSE_SECONDS = 0.6
MAX_LOOKUPS = 40
# Outcomes that will not change any more, good or bad.
SETTLED = {"delivered", "opened", "clicked", "bounced", "complained", "failed", "suppressed", "canceled"}
RESEND_EMAIL_PAGE = "https://resend.com/emails/{id}"
CANARY_TEMPLATE = "delivery_canary"
SETUP_TEMPLATE = "email_setup_problem"

# Resend webhook event -> delivery state. A later state never moves back to
# an earlier one (events can arrive out of order): RANK decides.
EVENT_STATE = {
    "email.sent": "sent",
    "email.delivery_delayed": "delivery_delayed",
    "email.delivered": "delivered",
    "email.opened": "opened",
    "email.clicked": "clicked",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.failed": "failed",
    "email.suppressed": "suppressed",
}
RANK = {"": 0, "queued": 0, "scheduled": 0, "sent": 1, "delivery_delayed": 2,
        "delivered": 3, "opened": 4, "clicked": 4,
        "bounced": 5, "complained": 5, "failed": 5, "suppressed": 5}

# What email depends on in DNS: (name, type, text that must appear, why).
DNS_EXPECTED = (
    ("_dmarc.proreadyengineer.com", "TXT", "v=DMARC1",
     "DMARC policy (Microsoft refuses mail without one)"),
    ("resend._domainkey.mail.proreadyengineer.com", "TXT", "p=",
     "DKIM key that signs the website's emails"),
    ("send.mail.proreadyengineer.com", "TXT", "include:amazonses.com",
     "SPF for the website's emails"),
    ("send.mail.proreadyengineer.com", "MX", "feedback-smtp.us-east-1.amazonses.com",
     "bounce feedback for the website's emails"),
    ("mail.proreadyengineer.com", "MX", "inbound-smtp.us-east-1.amazonaws.com",
     "receiving for the support desk (info@mail.proreadyengineer.com)"),
    ("proreadyengineer.com", "MX", "google.com",
     "receiving for your Google Workspace mailboxes"),
    ("proreadyengineer.com", "TXT", "include:_spf.google.com",
     "SPF for mail you send from Google Workspace"),
)
DOH_URL = "https://dns.google/resolve"


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_problem(row: EmailLog) -> bool:
    return (not row.ok) or row.delivery in copies.PROBLEM_DELIVERY


def _person(db: Session, email: str, sent: Optional[datetime] = None) -> list[tuple[str, str]]:
    """What the site knows about the recipient, as label/value pairs.

    The registration shown is the latest one made before the email was sent
    (the one it was about), else the latest one.
    """
    addr = (email or "").strip().lower()
    regs = db.execute(
        select(Registration)
        .where(func.lower(Registration.email) == addr)
        .order_by(Registration.id.desc())
    ).scalars().all()
    reg = regs[0] if regs else None
    if sent is not None:
        reg = next(
            (r for r in regs if (_aware(r.created_at) or sent) <= sent + timedelta(minutes=2)),
            reg,
        )
    learner = db.execute(
        select(Learner).where(func.lower(Learner.email) == addr)
    ).scalars().first()
    out: list[tuple[str, str]] = []
    name = (reg.full_name if reg else "") or (learner.full_name if learner else "")
    out.append(("Name", name or ""))
    if reg is not None:
        course = db.execute(select(Course.title).where(Course.code == reg.course_code)).scalar()
        when = _aware(reg.created_at)
        out.append((
            "Registration",
            f"{course or reg.course_code} — {reg.status}"
            + (f", registered {when.strftime('%b %d, %Y %H:%M')} UTC" if when else ""),
        ))
        out.append(("WhatsApp / phone", getattr(reg, "phone", "") or ""))
        out.append(("Company", reg.company or ""))
        out.append(("Location", reg.location or ""))
    if learner is not None:
        out.append(("Learner account", "yes"))
    return out


def _alert(db: Session, row: EmailLog) -> bool:
    settings = get_settings()
    to = (settings.ADMIN_NOTIFY_EMAIL or "").strip()
    if not to:
        return False
    info = copies.delivery_info(row)
    what = copies.kind_label(row.template)
    ts = _aware(row.ts)
    site = settings.SITE_URL.rstrip("/")
    canary = row.template == CANARY_TEMPLATE
    domain = (row.recipient or "").rsplit("@", 1)[-1]
    html = delivery_problem_html(
        recipient=row.recipient,
        what=what,
        subject=row.subject or what,
        sent=ts.strftime("%b %d, %Y %H:%M UTC") if ts else "",
        outcome=info["label"],
        explanation=info["explanation"],
        person=[] if canary else _person(db, row.recipient, ts),
        resend_url=RESEND_EMAIL_PAGE.format(id=row.provider_id) if row.provider_id else "",
        comms_url=f"{site}/admin#comms",
        canary_domain=domain if canary else "",
    )
    subject = (
        f"[Email problem] {domain} refused our daily test email"
        if canary else f"[Email problem] {info['label']}: {what} to {row.recipient}"
    )
    return send_email(
        to=to,
        subject=subject,
        html=html,
        db=db,
        scope_kind="system",
        scope_code=f"email:{row.id}",
        audience="admin",
        template=ALERT_TEMPLATE,
    )


def _already_alerted(db: Session, row: EmailLog) -> bool:
    return db.execute(
        select(EmailLog.id).where(
            EmailLog.template == ALERT_TEMPLATE,
            EmailLog.scope_code == f"email:{row.id}",
            EmailLog.ok.is_(True),
        )
    ).first() is not None


def alert_once(db: Session, row: EmailLog) -> bool:
    """Alert about a problem email unless it is to the instructor, fine, or done."""
    if row.template == ALERT_TEMPLATE or copies.to_admin(row) or not _is_problem(row):
        return False
    if _already_alerted(db, row):
        return False
    return _alert(db, row)


def _event_detail(data: dict) -> str:
    """The receiving server's own words from a webhook event, if any."""
    parts: list[str] = []
    for key in ("bounce", "failed", "suppressed", "complaint", "delivery_delayed"):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        codes = block.get("diagnosticCode") or block.get("diagnostic_code") or []
        if isinstance(codes, str):
            codes = [codes]
        for text in [*codes, block.get("message"), block.get("reason")]:
            text = str(text or "").strip()
            if text and text not in parts:
                parts.append(text)
        kind = " / ".join(str(block.get(k)) for k in ("type", "subType") if block.get(k))
        if kind:
            parts.append(f"({kind})")
    return " ".join(parts)[:1000]


def apply_event(db: Session, event: dict) -> str:
    """Record one Resend webhook event on its EmailLog row; alert if needed.

    Returns what happened, in a word, for the webhook's log line. Events for
    emails this site did not send (the Resend account is shared with another
    business) match no row and are ignored.
    """
    state = EVENT_STATE.get(str(event.get("type") or ""))
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    email_id = str(data.get("email_id") or "")
    if not state or not email_id:
        return "ignored"
    row = db.execute(
        select(EmailLog).where(EmailLog.provider_id == email_id)
    ).scalars().first()
    if row is None:
        return "not ours"
    if RANK.get(state, 0) >= RANK.get(row.delivery or "", 0):
        row.delivery = state
        row.delivery_checked_at = datetime.now(timezone.utc)
        detail = _event_detail(data)
        if detail:
            row.delivery_detail = detail
        db.commit()
    if alert_once(db, row):
        return f"{state}, alerted"
    return state


def _doh(name: str, rtype: str) -> Optional[list[str]]:
    """DNS-over-HTTPS lookup — the seam tests replace. None = could not check."""
    try:
        with httpx.Client(timeout=6.0) as client:
            r = client.get(DOH_URL, params={"name": name, "type": rtype})
        if r.status_code != 200:
            return None
        body = r.json() or {}
    except (httpx.HTTPError, ValueError):
        return None
    if body.get("Status") not in (0, 3):  # 0 = found, 3 = no such name
        return None
    return [str(a.get("data") or "") for a in body.get("Answer") or []]


def dns_check(db: Session, now: datetime) -> dict:
    """Look up every record email depends on; alert at most once a day."""
    failures: list[tuple[str, str, str]] = []
    unchecked = 0
    for name, rtype, needle, why in DNS_EXPECTED:
        answers = _doh(name, rtype)
        if answers is None:
            unchecked += 1
            continue
        if not any(needle.lower() in a.lower() for a in answers):
            failures.append((f"{rtype} {name}", why, "; ".join(answers) or "no record"))
    out = {"failures": [f[0] for f in failures], "unchecked": unchecked, "alerted": False}
    if not failures:
        return out
    since = now - timedelta(hours=24)
    recent = db.execute(
        select(EmailLog).where(EmailLog.template == SETUP_TEMPLATE, EmailLog.ok.is_(True))
        .order_by(EmailLog.id.desc()).limit(1)
    ).scalars().first()
    if recent is not None and (_aware(recent.ts) or now) >= since:
        return out
    settings = get_settings()
    to = (settings.ADMIN_NOTIFY_EMAIL or "").strip()
    if to:
        out["alerted"] = send_email(
            to=to,
            subject="[Email setup] A DNS record that email depends on is missing or changed",
            html=email_setup_problem_html(failures),
            db=db, scope_kind="system", scope_code="dns",
            audience="admin", template=SETUP_TEMPLATE,
        )
    return out


def send_canaries(db: Session, now: datetime) -> dict:
    """Once a day, email the instructor's own mailboxes at other providers."""
    settings = get_settings()
    addresses = [a.strip() for a in (settings.CANARY_EMAILS or "").split(",") if a.strip()]
    if not addresses:
        return {"sent": 0, "reason": "no CANARY_EMAILS"}
    if now.hour < settings.CANARY_HOUR_UTC:
        return {"sent": 0, "reason": "not yet today"}
    last = db.execute(
        select(EmailLog).where(EmailLog.template == CANARY_TEMPLATE, EmailLog.ok.is_(True))
        .order_by(EmailLog.id.desc()).limit(1)
    ).scalars().first()
    if last is not None and (_aware(last.ts) or now) >= now - timedelta(hours=20):
        return {"sent": 0, "reason": "already sent today"}
    sent = 0
    day = now.strftime("%b %d, %Y")
    for addr in addresses:
        if send_email(
            to=addr,
            subject=f"[Canary] ProReadyEngineer email check — {day}",
            html=delivery_canary_html(day),
            db=db, scope_kind="system", scope_code="canary",
            audience="canary", template=CANARY_TEMPLATE,
        ):
            sent += 1
    return {"sent": sent, "reason": ""}


def checks(db: Session, *, now: Optional[datetime] = None) -> dict:
    """The DNS guard and the daily canary, for the cron call."""
    now = now or datetime.now(timezone.utc)
    return {"dns": dns_check(db, now), "canary": send_canaries(db, now)}


def sweep(
    db: Session,
    *,
    now: Optional[datetime] = None,
    pause: float = PAUSE_SECONDS,
    max_lookups: int = MAX_LOOKUPS,
) -> dict:
    """Look up unsettled customer emails in Resend; alert once per problem."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=WATCH_HOURS)
    admins = copies.admin_addresses()

    recent = [
        r for r in db.execute(
            select(EmailLog).order_by(EmailLog.id.desc()).limit(2000)
        ).scalars().all()
        if (_aware(r.ts) or now) >= since
    ]
    alerted = {
        r.scope_code for r in recent
        if r.template == ALERT_TEMPLATE and r.ok
    }

    out = {"looked_up": 0, "lookup_errors": 0, "still_pending": 0,
           "alerts_sent": 0, "alerts_failed": 0, "problems": []}
    for row in reversed(recent):  # oldest first
        if row.template == ALERT_TEMPLATE or copies.to_admin(row, admins):
            continue
        if f"email:{row.id}" in alerted:
            continue
        if row.ok and row.provider_id and row.delivery not in SETTLED:
            if out["looked_up"] >= max_lookups:
                out["still_pending"] += 1
                continue
            why = copies.refresh(db, row)
            out["looked_up"] += 1
            if pause:
                time.sleep(pause)
            if why:
                out["lookup_errors"] += 1
                log.warning("[delivery] could not check email %s: %s", row.id, why)
                continue
        if _is_problem(row):
            note = f"#{row.id} {row.template} -> {row.recipient}: {copies.delivery_info(row)['state']}"
            out["problems"].append(note)
            if _alert(db, row):
                out["alerts_sent"] += 1
                alerted.add(f"email:{row.id}")
            else:
                out["alerts_failed"] += 1
        elif row.ok and row.delivery not in SETTLED:
            out["still_pending"] += 1
    log.info("[delivery] sweep: %s", out)
    return out
