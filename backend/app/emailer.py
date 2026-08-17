"""Resend transactional email wrapper + outbound email log.

Kept intentionally thin — POSTs to Resend's /emails and /emails/batch
endpoints through one seam (_resend_post) so tests can fake the wire.
If the API key is unset (e.g. local dev), the would-have-been email is
logged and the send reports failure: a message that never left must not
read as delivered in broadcast counts or the admin comms log.

Every send can optionally record an EmailLog row (pass db=...); that log
is what GET /api/admin/comms/log serves.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Optional, Sequence

import httpx
from sqlalchemy.orm import Session

from .config import get_settings
from .models import EmailLog

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
RESEND_BATCH_URL = "https://api.resend.com/emails/batch"

# Resend's documented cap on items per /emails/batch call.
BATCH_CHUNK_SIZE = 100


def _resend_post(
    url: str, payload: dict | list, api_key: str
) -> Optional[httpx.Response]:
    """Single HTTP seam for every Resend call — tests monkeypatch this.

    Returns the response, or None on a network-level failure (callers
    treat None like a non-2xx status).
    """
    try:
        with httpx.Client(timeout=15.0) as client:
            return client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        log.error("Resend network error: %s", exc)
        return None


def _log_email(
    db: Optional[Session],
    *,
    scope_kind: str,
    scope_code: str,
    audience: str,
    template: str,
    subject: str,
    recipient: str,
    ok: bool,
    provider_id: str = "",
) -> None:
    """Best-effort EmailLog write. Never raises — logging must not be the
    reason a send (or the request around it) fails."""
    if db is None:
        return
    try:
        db.add(
            EmailLog(
                scope_kind=scope_kind,
                scope_code=scope_code,
                audience=audience,
                template=template,
                subject=subject[:500],
                recipient=recipient,
                ok=ok,
                provider_id=provider_id[:64],
            )
        )
        db.commit()
    except Exception:
        log.exception("EmailLog write failed for recipient=%s", recipient)
        db.rollback()


def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    reply_to: Optional[str] = None,
    bcc: Optional[str] = None,
    db: Optional[Session] = None,
    scope_kind: str = "system",
    scope_code: str = "",
    audience: str = "",
    template: str = "",
    headers: Optional[dict] = None,
    from_override: Optional[str] = None,
    text: Optional[str] = None,
) -> bool:
    """Send one email via Resend. Returns True on 2xx, False otherwise.

    Failures are logged but NOT raised — registration success shouldn't
    depend on the email making it out. Admin notifications include the
    applicant's full payload so Bassam can follow up manually if the
    applicant's email bounces.

    When `db` is supplied, the outcome (including stubbed/failed sends)
    is recorded as an EmailLog row tagged with scope_kind/scope_code/
    audience/template — the raw material for the admin comms log.

    `headers` passes RFC-2822 headers straight through to Resend. The
    support desk uses it for Message-ID/In-Reply-To/References so a
    customer's reply threads back onto its ticket instead of opening a
    new one; nothing else needs it. `from_override` lets the support desk
    send as its own address while the rest of the platform keeps
    EMAIL_FROM, and `text` supplies a plain-text alternative part.
    """
    settings = get_settings()

    ok = False
    provider_id = ""

    if not settings.RESEND_API_KEY:
        # Deliberately False (changed 2026-08; used to fake success): a
        # send that never happened must not inflate broadcast counts or
        # show as delivered in the comms log.
        log.warning(
            "[email stub] RESEND_API_KEY unset; would have sent to=%s subject=%r",
            to,
            subject,
        )
    else:
        payload: dict = {
            "from": from_override or settings.EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if reply_to or settings.EMAIL_REPLY_TO:
            payload["reply_to"] = reply_to or settings.EMAIL_REPLY_TO
        if bcc:
            payload["bcc"] = [bcc]
        if headers:
            # Drop empties: Resend rejects a header whose value is null, and
            # an absent In-Reply-To is normal on the first mail of a thread.
            clean = {k: v for k, v in headers.items() if v}
            if clean:
                payload["headers"] = clean

        r = _resend_post(RESEND_URL, payload, settings.RESEND_API_KEY)
        if r is None:
            pass  # network failure already logged by the seam
        elif r.status_code >= 300:
            log.error(
                "Resend send failed: status=%s body=%s", r.status_code, r.text[:500]
            )
        else:
            ok = True
            try:
                provider_id = str((r.json() or {}).get("id") or "")
            except Exception:
                provider_id = ""

    _log_email(
        db,
        scope_kind=scope_kind,
        scope_code=scope_code,
        audience=audience,
        template=template,
        subject=subject,
        recipient=to,
        ok=ok,
        provider_id=provider_id,
    )
    return ok


def send_broadcast(
    db: Session,
    recipients: Sequence[str],
    subject: str,
    html_builder: Callable[[str], str],
    scope: dict,
) -> tuple[int, list[str]]:
    """Send one subject to many recipients via Resend's batch endpoint.

    Why batch: the old notify path POSTed once per registrant, which is
    slow and rate-limit-prone at cohort size. Batch sends up to 100
    messages per call; each recipient still gets an individual message
    (their address alone in `to`) and an individual EmailLog row.

    If a batch POST fails outright, that chunk falls back to per-recipient
    send_email — a transient batch error degrades to the old behavior
    instead of dropping the broadcast. `html_builder(email)` produces the
    body per recipient so future templates can personalize; today's
    builders ignore the argument.

    scope keys: scope_kind, scope_code, audience, template.
    Returns (sent_count, failed_addresses).
    """
    settings = get_settings()
    recipients = list(recipients)
    scope_kwargs = dict(
        scope_kind=scope.get("scope_kind", "system"),
        scope_code=scope.get("scope_code", ""),
        audience=scope.get("audience", ""),
        template=scope.get("template", ""),
    )

    sent = 0
    failed: list[str] = []

    def _fallback(chunk: list[str]) -> None:
        nonlocal sent
        for addr in chunk:
            if send_email(
                to=addr, subject=subject, html=html_builder(addr), db=db, **scope_kwargs
            ):
                sent += 1
            else:
                failed.append(addr)

    if not settings.RESEND_API_KEY:
        _fallback(recipients)  # stub mode: logs every recipient as not sent
        return sent, failed

    for i in range(0, len(recipients), BATCH_CHUNK_SIZE):
        chunk = recipients[i : i + BATCH_CHUNK_SIZE]
        payload = []
        for addr in chunk:
            item: dict = {
                "from": settings.EMAIL_FROM,
                "to": [addr],
                "subject": subject,
                "html": html_builder(addr),
            }
            if settings.EMAIL_REPLY_TO:
                item["reply_to"] = settings.EMAIL_REPLY_TO
            payload.append(item)

        r = _resend_post(RESEND_BATCH_URL, payload, settings.RESEND_API_KEY)
        if r is None or r.status_code >= 300:
            log.error(
                "Resend batch failed (status=%s); falling back to single sends "
                "for %d recipients",
                "network" if r is None else r.status_code,
                len(chunk),
            )
            _fallback(chunk)
            continue

        ids: list = []
        try:
            ids = (r.json() or {}).get("data") or []
        except Exception:
            ids = []
        for idx, addr in enumerate(chunk):
            provider_id = ""
            if idx < len(ids) and isinstance(ids[idx], dict):
                provider_id = str(ids[idx].get("id") or "")
            _log_email(
                db,
                subject=subject,
                recipient=addr,
                ok=True,
                provider_id=provider_id,
                **scope_kwargs,
            )
            sent += 1

    return sent, failed


# -----------------------------------------------------------------------------
# Message templates
# -----------------------------------------------------------------------------

def applicant_confirmation_html(
    full_name: str,
    course_title: str,
    cohort: str,
    price_display: str,
    payment_instructions: str,
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
        <strong>{course_title}</strong> cohort starting
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


# -----------------------------------------------------------------------------
# Academy templates
# -----------------------------------------------------------------------------
# Same dark-navy + cyan shell as the cohort emails above, so a buyer who has
# also registered for a live course sees one consistent sender identity.

def _academy_shell(eyebrow: str, heading: str, body_html: str) -> str:
    return f"""\
<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;padding:32px;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#0f172a;border:1px solid #1e293b;border-radius:16px;overflow:hidden;">
    <tr><td style="padding:32px;">
      <div style="font-size:12px;letter-spacing:0.2em;text-transform:uppercase;color:#22d3ee;margin-bottom:8px;">
        {eyebrow}
      </div>
      <h1 style="margin:0 0 16px;font-size:22px;color:#f1f5f9;">{heading}</h1>
      {body_html}
      <p style="margin:24px 0 0;font-size:13px;color:#64748b;">
        Questions? Reply to this email or write to
        <a href="mailto:info@proreadyengineer.com" style="color:#22d3ee;">info@proreadyengineer.com</a>.
      </p>
    </td></tr>
    <tr><td style="padding:16px 32px;background:#0b1220;border-top:1px solid #1e293b;font-size:12px;color:#475569;">
      ProReadyEngineer &middot; Thermal Fluid Sciences &amp; AI
    </td></tr>
  </table>
</body></html>"""


def _cta_button(label: str, url: str) -> str:
    return f"""\
      <p style="margin:0 0 24px;">
        <a href="{url}" style="display:inline-block;background:linear-gradient(90deg,#22d3ee,#3b82f6);color:#04121f;
           font-weight:700;font-size:15px;text-decoration:none;padding:13px 26px;border-radius:10px;">{label}</a>
      </p>"""


def login_link_html(full_name: str, link: str, minutes: int) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{greeting}</p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.55;">
        Here's your sign-in link. It works once and expires in
        <strong>{minutes} minutes</strong>.
      </p>
{_cta_button("Sign in to your courses", link)}
      <p style="margin:0 0 16px;font-size:13px;line-height:1.55;color:#94a3b8;">
        If the button doesn't work, paste this into your browser:<br>
        <span style="color:#22d3ee;word-break:break-all;">{link}</span>
      </p>
      <p style="margin:0;font-size:13px;line-height:1.55;color:#94a3b8;">
        Didn't ask for this? You can ignore this email — nobody can sign in
        without the link above.
      </p>"""
    return _academy_shell("Sign in", "Your sign-in link", body)


def purchase_welcome_html(
    full_name: str, course_title: str, link: str, minutes: int,
    bank_pending: bool = False,
) -> str:
    greeting = f"Welcome aboard, {full_name}." if full_name else "Welcome aboard."
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{greeting}</p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.55;">
        Your payment for <strong>{course_title}</strong> went through and your
        access is live. It's yours for good — there's no subscription and no
        expiry date.
      </p>
{_cta_button("Start the course", link)}
      <p style="margin:0 0 16px;font-size:13px;line-height:1.55;color:#94a3b8;">
        That link signs you in and expires in {minutes} minutes. After that,
        request a fresh one any time from the sign-in page — same email address,
        no password to remember.
      </p>
      <p style="margin:0 0 8px;font-size:15px;line-height:1.55;">What's inside:</p>
      <p style="margin:0 0 16px;font-size:14px;line-height:1.7;color:#cbd5e1;">
        Recorded sessions you can work through at your own pace, the slide decks
        and design spreadsheets, the interactive labs, and the module quizzes.
        Each module unlocks the next once you clear its check, and your progress
        is saved as you go.
      </p>"""
    if bank_pending:
        # ACH: the debit is initiated but unconfirmed for a few business days.
        # Access is provisional; academy.settlement_ok pulls it if the payment
        # never clears, and _payment_failed emails them if the bank says no.
        body += """
      <p style="margin:0 0 16px;padding:12px 14px;border:1px solid rgba(245,158,11,0.4);border-radius:10px;background:rgba(245,158,11,0.08);font-size:13px;line-height:1.6;color:#fcd34d;">
        One note: you paid by bank transfer, which takes a few business days to
        clear. Your access is active now and will be fully confirmed once the
        payment clears — nothing more for you to do. If it doesn't go through,
        we'll email you right away.
      </p>"""
    return _academy_shell(
        "Bank payment processing" if bank_pending else "Payment confirmed",
        "You're in",
        body,
    )


def enrollment_granted_html(full_name: str, course_title: str, link: str) -> str:
    """Manual/comp grant — an admin added this learner by hand."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{greeting}</p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.55;">
        You've been given access to <strong>{course_title}</strong> on the
        ProReadyEngineer training platform.
      </p>
{_cta_button("Open the course", link)}
      <p style="margin:0;font-size:13px;line-height:1.55;color:#94a3b8;">
        This link signs you in once. After that, request a new one any time from
        the sign-in page using this same email address.
      </p>"""
    return _academy_shell("Access granted", "Your course is ready", body)


def payment_receipt_html(
    full_name: str, course_title: str, amount_display: str, reference: str
) -> str:
    """Receipt for a live-cohort seat paid online (PayPal or Stripe)."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    amount_row = (
        f"""<tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Amount</td>
          <td style="padding:4px 0;color:#f1f5f9;"><strong>{amount_display}</strong></td>
        </tr>"""
        if amount_display
        else ""
    )
    reference_row = (
        f"""<tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Reference</td>
          <td style="padding:4px 0;color:#f1f5f9;">{reference}</td>
        </tr>"""
        if reference
        else ""
    )
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{greeting}</p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        Your payment for <strong>{course_title}</strong> went through and your
        seat is now <strong>confirmed</strong>.
      </p>
      <table style="margin:0 0 16px;font-size:15px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Course</td>
          <td style="padding:4px 0;color:#f1f5f9;">{course_title}</td>
        </tr>
{amount_row}
{reference_row}
      </table>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        Keep this email as your receipt. We'll follow up with the joining
        details and schedule before the course begins.
      </p>"""
    return _academy_shell("Payment received", "Your seat is confirmed", body)


def settlement_failed_html(
    full_name: str, course_title: str, course_url: str
) -> str:
    """Recorded product: the bank debit never cleared — access is paused."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{greeting}</p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        Your bank payment for <strong>{course_title}</strong> didn't clear, so
        your course access is paused for now. Your progress is saved — nothing
        is lost.
      </p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.55;">
        To get back in, pay by card from the course page (it takes a minute and
        access is restored instantly), or simply reply to this email and we'll
        sort it out and reinstate you.
      </p>
{_cta_button("Pay by card", course_url)}
      <p style="margin:0;font-size:13px;line-height:1.55;color:#94a3b8;">
        Course page:
        <a href="{course_url}" style="color:#22d3ee;word-break:break-all;">{course_url}</a>
      </p>"""
    return _academy_shell("Payment issue", "Your bank payment didn't clear", body)


def live_bank_failed_html(
    full_name: str, course_title: str, course_url: str
) -> str:
    """Live cohort seat: the bank debit never cleared — the seat is still held."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{greeting}</p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        Your bank payment for <strong>{course_title}</strong> didn't clear.
        Don't worry — <strong>your seat is still held</strong> for you.
      </p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.55;">
        To confirm it, pay by card from the course page, or reply to this email
        and we'll arrange another way to settle it.
      </p>
{_cta_button("Pay by card", course_url)}
      <p style="margin:0;font-size:13px;line-height:1.55;color:#94a3b8;">
        Course page:
        <a href="{course_url}" style="color:#22d3ee;word-break:break-all;">{course_url}</a>
      </p>"""
    return _academy_shell("Payment issue", "Your bank payment didn't clear", body)


def settlement_failed_admin_html(
    buyer_email: str, course_title: str, detail: str
) -> str:
    """Owner heads-up when a bank payment fails or times out unconfirmed."""
    body = f"""\
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;">
        A bank (ACH) payment did not clear.
      </p>
      <table style="margin:0 0 16px;font-size:14px;">
        <tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Buyer</td>
          <td style="padding:4px 0;color:#f1f5f9;">{buyer_email}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Course</td>
          <td style="padding:4px 0;color:#f1f5f9;">{course_title}</td>
        </tr>
        <tr>
          <td style="padding:4px 16px 4px 0;color:#94a3b8;">Outcome</td>
          <td style="padding:4px 0;color:#f1f5f9;">{detail}</td>
        </tr>
      </table>
      <p style="margin:0;font-size:13px;line-height:1.55;color:#94a3b8;">
        The buyer has been emailed with card-payment and contact options.
      </p>"""
    return _academy_shell("Payments", "Bank payment failed", body)
