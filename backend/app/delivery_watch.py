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

Resend's API does not give the bounce reason (only its dashboard and its
webhooks do), so the alert links to the email in Resend's dashboard.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import email_copies as copies
from .config import get_settings
from .emailer import delivery_problem_html, send_email
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


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_problem(row: EmailLog) -> bool:
    return (not row.ok) or row.delivery in copies.PROBLEM_DELIVERY


def _person(db: Session, email: str) -> list[tuple[str, str]]:
    """What the site knows about the recipient, as label/value pairs."""
    addr = (email or "").strip().lower()
    reg = db.execute(
        select(Registration)
        .where(func.lower(Registration.email) == addr)
        .order_by(Registration.id.desc())
    ).scalars().first()
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
    html = delivery_problem_html(
        recipient=row.recipient,
        what=what,
        subject=row.subject or what,
        sent=ts.strftime("%b %d, %Y %H:%M UTC") if ts else "",
        outcome=info["label"],
        explanation=info["explanation"],
        person=_person(db, row.recipient),
        resend_url=RESEND_EMAIL_PAGE.format(id=row.provider_id) if row.provider_id else "",
        comms_url=f"{site}/admin#comms",
    )
    return send_email(
        to=to,
        subject=f"[Email problem] {info['label']}: {what} to {row.recipient}",
        html=html,
        db=db,
        scope_kind="system",
        scope_code=f"email:{row.id}",
        audience="admin",
        template=ALERT_TEMPLATE,
    )


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
