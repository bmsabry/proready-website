"""Resend transactional email wrapper.

Kept intentionally thin — one POST to Resend's /emails endpoint. If the
API key is unset (e.g. local dev), logs the would-have-been email and
returns success. This lets the registration flow work without Resend
credentials while developing.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    reply_to: Optional[str] = None,
    bcc: Optional[str] = None,
) -> bool:
    """Send one email via Resend. Returns True on 2xx, False otherwise.

    Failures are logged but NOT raised — registration success shouldn't
    depend on the email making it out. Admin notifications include the
    applicant's full payload so Bassam can follow up manually if the
    applicant's email bounces.
    """
    settings = get_settings()

    if not settings.RESEND_API_KEY:
        log.warning(
            "[email stub] RESEND_API_KEY unset; would have sent to=%s subject=%r",
            to,
            subject,
        )
        return True

    payload: dict = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if reply_to or settings.EMAIL_REPLY_TO:
        payload["reply_to"] = reply_to or settings.EMAIL_REPLY_TO
    if bcc:
        payload["bcc"] = [bcc]

    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if r.status_code >= 300:
            log.error(
                "Resend send failed: status=%s body=%s", r.status_code, r.text[:500]
            )
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Resend network error: %s", exc)
        return False


# -----------------------------------------------------------------------------
# Message templates
# -----------------------------------------------------------------------------

def applicant_confirmation_html(
    full_name: str, cohort: str, price_display: str, payment_instructions: str
) -> str:
    price_block = (
        f"<p style='margin:0 0 16px;font-size:15px;'>"
        f"<strong>Course fee:</strong> {price_display}</p>"
        if price_display
        else ""
    )
    return f"""\
<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;padding:32px;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#0f172a;border:1px solid #1e293b;border-radius:16px;overflow:hidden;">
    <tr><td style="padding:32px;">
      <div style="font-size:12px;letter-spacing:0.2em;text-transform:uppercase;color:#22d3ee;margin-bottom:8px;">
        Registration received
      </div>
      <h1 style="margin:0 0 16px;font-size:22px;color:#f1f5f9;">
        Thanks, {full_name} — your seat is pending
      </h1>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        We've received your registration for the
        <strong>Gas Turbine Emissions Mapping</strong> cohort starting
        <strong>{cohort}</strong>.
      </p>
      {price_block}
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        <strong>Next step:</strong> {payment_instructions}
      </p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        Your seat is <strong>pending</strong> and counts toward the cohort
        only once payment clears. If the cohort fills before your payment
        arrives, we'll move you to the waitlist and refund any overlap.
      </p>
      <p style="margin:24px 0 0;font-size:13px;color:#64748b;">
        Questions? Reply to this email or write to
        <a href="mailto:info@proreadyengineer.com" style="color:#22d3ee;">info@proreadyengineer.com</a>.
      </p>
    </td></tr>
  </table>
</body></html>
"""


def _fmt_date(d: date) -> str:
    """Format a date like 'May 15, 2026' — matches the COHORT_LABEL style."""
    return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else str(d)


def start_date_updated_html(
    course_title: str, old_start_date: date, new_start_date: date
) -> str:
    """Stock template auto-sent when an admin changes a course's start date."""
    return f"""\
<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;padding:32px;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#0f172a;border:1px solid #1e293b;border-radius:16px;overflow:hidden;">
    <tr><td style="padding:32px;">
      <div style="font-size:12px;letter-spacing:0.2em;text-transform:uppercase;color:#22d3ee;margin-bottom:8px;">
        Start date updated
      </div>
      <h1 style="margin:0 0 16px;font-size:22px;color:#f1f5f9;">
        {course_title} — new start date
      </h1>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        The start date for your cohort has been updated.
      </p>
      <table style="margin:0 0 16px;font-size:15px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Previous start</td>
          <td style="padding:4px 0;color:#f1f5f9;">{_fmt_date(old_start_date)}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">New start</td>
          <td style="padding:4px 0;color:#22d3ee;"><strong>{_fmt_date(new_start_date)}</strong></td>
        </tr>
      </table>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        No action is required from your side — your registration remains active. If
        the new schedule doesn't work for you, reply to this email and we'll sort it out.
      </p>
      <p style="margin:24px 0 0;font-size:13px;color:#64748b;">
        Questions? Reply here or write to
        <a href="mailto:info@proreadyengineer.com" style="color:#22d3ee;">info@proreadyengineer.com</a>.
      </p>
    </td></tr>
  </table>
</body></html>
"""


def broadcast_html(course_title: str, body_html: str) -> str:
    """Wrap admin-composed HTML in a branded shell for course broadcasts."""
    return f"""\
<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;padding:32px;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;background:#0f172a;border:1px solid #1e293b;border-radius:16px;overflow:hidden;">
    <tr><td style="padding:32px;">
      <div style="font-size:12px;letter-spacing:0.2em;text-transform:uppercase;color:#22d3ee;margin-bottom:8px;">
        Course update
      </div>
      <h1 style="margin:0 0 20px;font-size:20px;color:#f1f5f9;">
        {course_title}
      </h1>
      <div style="font-size:15px;line-height:1.6;color:#e2e8f0;">
        {body_html}
      </div>
      <p style="margin:24px 0 0;font-size:13px;color:#64748b;">
        Questions? Reply here or write to
        <a href="mailto:info@proreadyengineer.com" style="color:#22d3ee;">info@proreadyengineer.com</a>.
      </p>
    </td></tr>
  </table>
</body></html>
"""


def admin_notification_html(reg: dict, taken_after: int, capacity: int) -> str:
    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#94a3b8;'>{k}</td>"
        f"<td style='padding:4px 0;color:#f1f5f9;'>{v}</td></tr>"
        for k, v in reg.items()
    )
    return f"""\
<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;padding:32px;color:#e2e8f0;">
  <table style="max-width:560px;margin:0 auto;background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:24px;">
    <tr><td>
      <h2 style="margin:0 0 16px;font-size:18px;color:#f1f5f9;">New registration (pending)</h2>
      <p style="margin:0 0 12px;color:#94a3b8;font-size:13px;">
        Pending count unchanged ({taken_after}/{capacity} paid). Mark paid via admin endpoint once the invoice clears.
      </p>
      <table style="font-size:13px;border-collapse:collapse;">{rows}</table>
    </td></tr>
  </table>
</body></html>
"""
