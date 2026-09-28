"""Copies of sent emails, and what happened to them after they left.

The admin comms log lists every outbound email; this module is what lets
each one be opened and read as the recipient saw it:

  * From now on send_email keeps a copy of every email in email_log.
  * Older emails are fetched back from Resend, which keeps copies for
    30 days (every plan) — and kept locally once fetched, so they stay
    readable after Resend deletes them. `backfill` does that for every
    recent email at once.
  * Resend also reports what happened after the send (delivered, bounced,
    opened, marked as spam); `refresh` records it on the row.

One thing is never kept: the token in a sign-in link. A stored copy that
could sign someone in is a credential sitting in a table; it is blanked
before anything is written (redact_secrets).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import EmailLog

log = logging.getLogger(__name__)

RESEND_EMAIL_URL = "https://api.resend.com/emails/{id}"
# Resend's data retention on every plan (resend.com/pricing, Sep 2026).
RESEND_KEEPS = timedelta(days=30)
HIDDEN = "(hidden)"

# ?token=… in a sign-in link — in HTML the & arrives as &amp;.
_SECRET_PARAM = re.compile(r"(\?|&amp;|&)(token|signature|sig)=([^&\"'\s<>]+)", re.I)


def redact_secrets(body: str) -> str:
    """Blank the values of token-like URL parameters (sign-in links)."""
    if not body:
        return ""
    return _SECRET_PARAM.sub(lambda m: f"{m.group(1)}{m.group(2)}={HIDDEN}", body)


# ---------------------------------------------------------------------------
# Labels — the log is read by a person, not by the code that wrote it
# ---------------------------------------------------------------------------

KIND_LABELS: dict[str, str] = {
    "broadcast": "Broadcast",
    "start_date_updated": "Start date changed",
    "session_reminder": "Session reminder",
    "session_reminder_test": "Session reminder (test)",
    "materials_ready": "Course materials ready",
    "applicant_confirmation": "Registration received",
    "admin_new_registration": "New registration",
    "support_reply": "Support reply",
    "support_admin_alert": "Support alert",
    "integrity_sharing": "Integrity alert: shared login",
    "integrity_leak": "Integrity alert: file leak",
    "integrity_launch_cap": "Integrity alert: launch limit",
    "certificate_completion": "Certificate of Completion",
    "certificate_attendance": "Certificate of Attendance",
    "certificate_verified": "Certificate of Verified Competency",
    "access_granted": "Course access granted",
    "payment_receipt": "Payment receipt",
    "settlement_failed": "Payment failed",
    "settlement_failed_admin": "Payment failed",
    "live_bank_failed": "Bank payment failed",
    "live_bank_failed_admin": "Bank payment failed",
    "learner_request_answers": "Learner request: answer key",
    "learner_request_completion": "Learner request: completion marks",
    "learner_request_answers_approved": "Request approved: answer key",
    "learner_request_completion_approved": "Request approved: completion marks",
    "advanced_purchased": "Verified Competency: purchased",
    "advanced_exam_passed": "Verified Competency: exam passed",
    "advanced_slots_admin": "Verified Competency: interview times",
    "advanced_scheduled": "Verified Competency: interview booked",
    "advanced_retake": "Verified Competency: retake",
    "advanced_failed": "Verified Competency: not passed",
}

# (label, tone, what it means) — tone drives the colour: good/neutral/warn/bad.
DELIVERY: dict[str, tuple[str, str, str]] = {
    "delivered": ("Delivered", "good", "The recipient's mail server accepted it."),
    "opened": ("Opened", "good", "Delivered, and the recipient opened it."),
    "clicked": ("Link clicked", "good", "Delivered, and the recipient clicked a link in it."),
    "sent": ("Sent", "neutral", "Handed to the recipient's mail server; delivery not confirmed yet."),
    "queued": ("Queued", "neutral", "Waiting to be sent."),
    "scheduled": ("Scheduled", "neutral", "Scheduled to be sent later."),
    "canceled": ("Canceled", "neutral", "The scheduled send was canceled."),
    "delivery_delayed": (
        "Delayed", "warn",
        "The recipient's mail server had a temporary problem; Resend keeps retrying.",
    ),
    "bounced": (
        "Bounced", "bad",
        "The recipient's mail server rejected it: the address may be wrong, or the mailbox full or closed.",
    ),
    "complained": ("Marked as spam", "bad", "Delivered, but the recipient marked it as spam."),
    "failed": ("Failed", "bad", "Resend could not send it."),
    "suppressed": (
        "Not sent (suppressed)", "bad",
        "Resend skipped it because this address bounced or complained before.",
    ),
}
PROBLEM_DELIVERY = {k for k, v in DELIVERY.items() if v[1] == "bad"}


def kind_label(template: str) -> str:
    if template in KIND_LABELS:
        return KIND_LABELS[template]
    words = (template or "email").replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def admin_addresses() -> set[str]:
    s = get_settings()
    return {
        a.strip().lower()
        for a in (s.ADMIN_NOTIFY_EMAIL, s.ADMIN_EMAIL, getattr(s, "INTEGRITY_ALERT_EMAIL", ""))
        if a and a.strip()
    }


def to_admin(row: EmailLog, admins: Optional[set[str]] = None) -> bool:
    """An alert to Bassam himself, not an email to a customer."""
    return row.audience == "admin" or (row.recipient or "").lower() in (admins or admin_addresses())


def delivery_info(row: EmailLog) -> dict[str, Any]:
    """The best-known outcome of one email, in words."""
    if not row.ok:
        return {
            "state": "not_sent",
            "label": "Not sent",
            "tone": "bad",
            "explanation": row.error or "The send failed before it reached Resend.",
            "checked_at": None,
        }
    if row.delivery in DELIVERY:
        label, tone, explanation = DELIVERY[row.delivery]
    else:
        label, tone, explanation = (
            "Sent", "neutral",
            "Accepted for sending. No delivery report from Resend yet.",
        )
    return {
        "state": row.delivery or "accepted",
        "label": label,
        "tone": tone,
        "explanation": explanation,
        "checked_at": row.delivery_checked_at.isoformat() if row.delivery_checked_at else None,
    }


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------


def _resend_get(url: str, api_key: str) -> Optional[httpx.Response]:
    """Single HTTP seam for reading from Resend — tests replace it."""
    try:
        with httpx.Client(timeout=10.0) as client:
            return client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        log.warning("Resend lookup failed: %s", exc)
        return None


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _addresses(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value or "")


def refresh(db: Session, row: EmailLog) -> str:
    """Ask Resend about one email: fill in a missing copy, update delivery.

    Returns "" on success, or why it could not (for the viewer to say).
    Never raises.
    """
    if not row.provider_id:
        return "no Resend id recorded for this email"
    key = (get_settings().RESEND_API_KEY or "").strip()
    if not key:
        return "the email service key is not set"
    resp = _resend_get(RESEND_EMAIL_URL.format(id=row.provider_id), key)
    if resp is None:
        return "Resend could not be reached"
    if resp.status_code == 404:
        if not row.body_html and not row.body_text:
            row.copy_source = "gone"
            db.commit()
        return "Resend no longer has this email"
    if resp.status_code >= 300:
        return f"Resend answered HTTP {resp.status_code}"
    try:
        data = resp.json() or {}
    except ValueError:
        return "Resend's answer could not be read"

    row.delivery = str(data.get("last_event") or "")[:32]
    row.delivery_checked_at = datetime.now(timezone.utc)
    if not row.body_html and not row.body_text:
        row.body_html = redact_secrets(str(data.get("html") or ""))
        row.body_text = redact_secrets(str(data.get("text") or ""))
        row.copy_source = "resend" if (row.body_html or row.body_text) else "gone"
    row.from_addr = row.from_addr or str(data.get("from") or "")[:320]
    row.reply_to = row.reply_to or _addresses(data.get("reply_to"))[:320]
    row.cc = row.cc or _addresses(data.get("cc"))[:640]
    row.bcc = row.bcc or _addresses(data.get("bcc"))[:640]
    db.commit()
    return ""


def backfill(db: Session, *, pause: float = 0.6, now: Optional[datetime] = None) -> dict[str, int]:
    """Fetch and keep a copy of every recent email that has none yet.

    Only emails Resend can still have (sent within its 30 days) are asked
    for; the pause keeps under Resend's rate limit (2 requests a second).
    """
    now = now or datetime.now(timezone.utc)
    rows = db.execute(
        select(EmailLog)
        .where(
            EmailLog.provider_id != "",
            EmailLog.body_html == "",
            EmailLog.body_text == "",
            EmailLog.copy_source != "gone",
        )
        .order_by(EmailLog.id.desc())
    ).scalars().all()
    out = {"kept": 0, "gone": 0, "failed": 0, "too_old": 0}
    for row in rows:
        ts = _aware(row.ts)
        if ts is not None and now - ts > RESEND_KEEPS + timedelta(days=1):
            out["too_old"] += 1
            continue
        why = refresh(db, row)
        if not why and row.copy_source == "resend":
            out["kept"] += 1
        elif row.copy_source == "gone":
            out["gone"] += 1
        else:
            out["failed"] += 1
        if pause:
            time.sleep(pause)
    log.info("[email copies] backfill: %s", out)
    return out
