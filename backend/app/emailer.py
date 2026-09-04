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
import re
from datetime import date
from html import unescape
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


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"</(p|div|tr|h1|h2|h3|table)>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_HEAD_RE = re.compile(r"<(head|style|script|title)[^>]*>.*?</\1>", re.I | re.S)


def html_to_text(html: str) -> str:
    """A readable plain-text alternative derived from the HTML body.

    Not cosmetic. A multipart message scores better with spam filters than an
    HTML-only one, some corporate gateways strip HTML outright, and a screen
    reader or a text-mode client gets something usable. Link URLs are kept
    inline, because a text part whose call to action is the bare word "Open
    the course" is useless.
    """
    body = _HEAD_RE.sub(" ", html)
    # Keep the destination of every link — the label alone is not actionable.
    def _flatten_link(m: "re.Match[str]") -> str:
        href = m.group(1)
        label = _TAG_RE.sub("", m.group(2)).strip()
        bare = href[len("mailto:") :] if href.lower().startswith("mailto:") else href
        # "info@x.com (mailto:info@x.com)" is noise — only append the URL when
        # it actually tells the reader something the label doesn't.
        if not label or label == bare:
            return bare
        return f"{label} ({bare})"

    body = re.sub(
        r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        _flatten_link,
        body,
        flags=re.I | re.S,
    )
    body = _BR_RE.sub("\n", body)
    body = _BLOCK_END_RE.sub("\n\n", body)
    body = _TAG_RE.sub("", body)
    body = unescape(body)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


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
    attachments: Optional[list] = None,
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
    `attachments` is a list of {"filename", "content" (base64)} dicts in
    Resend's own shape — certificates ride along as PDFs.
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
        # Always send multipart. An explicit `text` wins (the support desk
        # passes the customer's own wording); otherwise derive one.
        body_text = text or html_to_text(html)
        if body_text:
            payload["text"] = body_text
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
        if attachments:
            payload["attachments"] = list(attachments)

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
    reply_to: Optional[str] = None,
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

    `reply_to` overrides EMAIL_REPLY_TO for this broadcast. Broadcasts that
    ask a question ("confirm your attendance") pass the support desk address
    so the answers arrive as tickets instead of scattering into a personal
    inbox where nobody can count them.

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
                to=addr,
                subject=subject,
                html=html_builder(addr),
                db=db,
                reply_to=reply_to,
                **scope_kwargs,
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
            if reply_to or settings.EMAIL_REPLY_TO:
                item["reply_to"] = reply_to or settings.EMAIL_REPLY_TO
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
# Email is not a browser. Two rules here are not style preferences, they are the
# reason a real "your course is ready" email arrived unreadable:
#
#   1. EVERY piece of text carries its own explicit `color`. Gmail, Yahoo and
#      Outlook.com rewrite or drop the <body> element, so any colour inherited
#      from <body> is gone by the time the message renders — leaving the
#      client's default near-black text. On the old dark-navy card that was
#      black on navy: the greeting, the paragraph and the button label were
#      invisible, while the few elements that did set their own colour showed
#      up fine. Use the _p()/_kv_table() helpers below and it cannot recur.
#
#   2. The call-to-action is a table cell with a `bgcolor`, not an <a> with a
#      CSS gradient. Gradients are unsupported in most mail clients; the old
#      button fell back to a transparent background behind near-black label
#      text, on a dark card.
#
# The palette is light-on-white for the same reason: clients that auto-invert
# handle light designs far better than dark ones, and a light card cannot fail
# into dark-on-dark. Brand identity lives in the navy header band and the cyan
# eyebrow, both of which are solid colours every client can render.

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
    "'Helvetica Neue',sans-serif"
)
PAGE_BG = "#eef2f7"
CARD_BG = "#ffffff"
CARD_BORDER = "#e2e8f0"
BAND_BG = "#0f172a"
BAND_TEXT = "#ffffff"
EYEBROW = "#67e8f9"
HEADING = "#0f172a"
INK = "#334155"
MUTED = "#64748b"
LINK = "#0369a1"
BUTTON_BG = "#0e7490"
BUTTON_TEXT = "#ffffff"
FOOTER_BG = "#f8fafc"
SUPPORT_EMAIL = "info@proreadyengineer.com"


def _p(
    html: str,
    *,
    size: int = 15,
    color: str = INK,
    margin: str = "0 0 16px",
    weight: int = 400,
) -> str:
    """A paragraph that always states its own colour. See rule 1 above."""
    return (
        f'<p style="margin:{margin};font-family:{FONT};font-size:{size}px;'
        f'line-height:1.6;font-weight:{weight};color:{color};">{html}</p>'
    )


def _kv_table(rows: "list[tuple[str, str]]", *, size: int = 15) -> str:
    """Label/value rows — every cell states its own colour."""
    body = "".join(
        f'<tr>'
        f'<td style="padding:5px 18px 5px 0;font-family:{FONT};font-size:{size}px;'
        f'line-height:1.5;color:{MUTED};vertical-align:top;">{k}</td>'
        f'<td style="padding:5px 0;font-family:{FONT};font-size:{size}px;'
        f'line-height:1.5;color:{HEADING};vertical-align:top;">{v}</td>'
        f'</tr>'
        for k, v in rows
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 18px;border-collapse:collapse;">{body}</table>'
    )


def _link(url: str, label: str = "") -> str:
    return (
        f'<a href="{url}" style="color:{LINK};text-decoration:underline;'
        f'word-break:break-word;">{label or url}</a>'
    )


def _cta_button(label: str, url: str) -> str:
    """Bulletproof button: colour lives on the <td>, not in a CSS gradient.

    `bgcolor` as an attribute AND as a style is deliberate — Outlook reads the
    attribute, everything else reads the style, and if both are somehow lost
    the label is still dark-on-white rather than invisible, because the
    fallback colour below is never the card background.
    """
    return f"""\
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 24px;">
        <tr>
          <td align="center" bgcolor="{BUTTON_BG}" style="background-color:{BUTTON_BG};border-radius:8px;">
            <a href="{url}" style="display:inline-block;padding:14px 30px;font-family:{FONT};font-size:16px;font-weight:700;line-height:1;color:{BUTTON_TEXT};text-decoration:none;border-radius:8px;">{label}</a>
          </td>
        </tr>
      </table>"""


def _shell(eyebrow: str, heading: str, body_html: str, *, width: int = 560) -> str:
    """The one wrapper every outbound email uses.

    One shell rather than a copy per template: the dark-on-dark bug shipped
    because four near-identical wrappers had drifted, and a fix to one of them
    would not have reached the others.
    """
    return f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{heading}</title>
</head>
<body style="margin:0;padding:0;background-color:{PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE_BG}" style="background-color:{PAGE_BG};margin:0;padding:0;width:100%;">
  <tr>
    <td align="center" style="padding:24px 12px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{width}" style="width:100%;max-width:{width}px;background-color:{CARD_BG};border:1px solid {CARD_BORDER};border-radius:12px;">
        <tr>
          <td bgcolor="{BAND_BG}" style="background-color:{BAND_BG};padding:18px 28px;border-radius:12px 12px 0 0;">
            <div style="font-family:{FONT};font-size:15px;font-weight:700;line-height:1.2;color:{BAND_TEXT};">ProReadyEngineer</div>
            <div style="font-family:{FONT};font-size:11px;font-weight:600;line-height:1.4;letter-spacing:0.16em;text-transform:uppercase;color:{EYEBROW};padding-top:5px;">{eyebrow}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:28px;">
            <h1 style="margin:0 0 18px;font-family:{FONT};font-size:22px;font-weight:700;line-height:1.3;color:{HEADING};">{heading}</h1>
{body_html}
            {_p(f'Questions? Reply to this email or write to {_link("mailto:" + SUPPORT_EMAIL, SUPPORT_EMAIL)}.', size=13, color=MUTED, margin="24px 0 0")}
          </td>
        </tr>
        <tr>
          <td bgcolor="{FOOTER_BG}" style="background-color:{FOOTER_BG};border-top:1px solid {CARD_BORDER};padding:14px 28px;border-radius:0 0 12px 12px;font-family:{FONT};font-size:12px;line-height:1.5;color:{MUTED};">
            ProReadyEngineer &middot; Thermal Fluid Sciences &amp; AI
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def applicant_confirmation_html(
    full_name: str,
    course_title: str,
    cohort: str,
    price_display: str,
    payment_instructions: str,
) -> str:
    body = _p(
        f"We've received your registration for the <strong>{course_title}</strong> "
        f"cohort starting <strong>{cohort}</strong>."
    )
    if price_display:
        body += _kv_table([("Course fee", f"<strong>{price_display}</strong>")])
    body += _p(f"<strong>Next step:</strong> {payment_instructions}")
    body += _p(
        "Your seat is <strong>pending</strong> and counts toward the cohort only "
        "once payment clears. If the cohort fills before your payment arrives, "
        "we'll move you to the waitlist and refund any overlap."
    )
    heading = (
        f"Thanks, {full_name}. Your seat is pending"
        if full_name
        else "Your seat is pending"
    )
    return _shell("Registration received", heading, body)


def _fmt_date(d: date) -> str:
    """Format a date like 'May 15, 2026' — matches the COHORT_LABEL style."""
    return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else str(d)


def start_date_updated_html(
    course_title: str, old_start_date: date, new_start_date: date
) -> str:
    """Stock template auto-sent when an admin changes a course's start date."""
    body = _p("The start date for your cohort has been updated.")
    body += _kv_table(
        [
            ("Previous start", _fmt_date(old_start_date)),
            ("New start", f"<strong>{_fmt_date(new_start_date)}</strong>"),
        ]
    )
    body += _p(
        "No action is required from your side; your registration remains active. "
        "If the new schedule doesn't work for you, reply to this email and we'll "
        "sort it out."
    )
    return _shell("Start date updated", f"{course_title}: new start date", body)


def broadcast_html(course_title: str, body_html: str) -> str:
    """Wrap admin-composed HTML in a branded shell for course broadcasts.

    The colour is set on the wrapping div AND by the composer that produced
    body_html, because either one alone would leave some clients rendering the
    admin's own words in their default colour.
    """
    wrapped = (
        f'<div style="font-family:{FONT};font-size:15px;line-height:1.6;'
        f'color:{INK};">{body_html}</div>'
    )
    return _shell("Course update", course_title, wrapped, width=600)


def admin_notification_html(reg: dict, taken_after: int, capacity: int) -> str:
    body = _p(
        f"Pending count unchanged ({taken_after}/{capacity} paid). Mark the row "
        "paid from the Registrations tab once the invoice clears.",
        size=13,
        color=MUTED,
    )
    body += _kv_table([(str(k), str(v)) for k, v in reg.items()], size=14)
    return _shell("New registration", "New registration (pending)", body)


# -----------------------------------------------------------------------------
# Academy templates
# -----------------------------------------------------------------------------
# Same shell as the cohort emails above, so a buyer who has also registered for
# a live course sees one consistent sender identity.


def login_link_html(full_name: str, link: str, minutes: int) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        "Here's your sign-in link. It works once and expires in "
        f"<strong>{minutes} minutes</strong>.",
        margin="0 0 22px",
    )
    body += _cta_button("Sign in to your courses", link)
    body += _p(
        "If the button doesn't work, paste this into your browser:<br>"
        f"{_link(link)}",
        size=13,
        color=MUTED,
    )
    body += _p(
        "Didn't ask for this? You can ignore this email; nobody can sign in "
        "without the link above.",
        size=13,
        color=MUTED,
        margin="0",
    )
    return _shell("Sign in", "Your sign-in link", body)


def purchase_welcome_html(
    full_name: str, course_title: str, link: str, minutes: int,
    bank_pending: bool = False,
) -> str:
    greeting = f"Welcome aboard, {full_name}." if full_name else "Welcome aboard."
    body = _p(greeting)
    body += _p(
        f"Your payment for <strong>{course_title}</strong> went through and your "
        "access is live. It's yours for good; there's no subscription and no "
        "expiry date.",
        margin="0 0 22px",
    )
    body += _cta_button("Start the course", link)
    body += _p(
        f"That link signs you in and expires in {minutes} minutes. After that, "
        "request a fresh one any time from the sign-in page, same email "
        "address, no password to remember.",
        size=13,
        color=MUTED,
    )
    body += _p("What's inside:", weight=700, margin="0 0 8px")
    body += _p(
        "Recorded sessions you can work through at your own pace, the slide decks "
        "and design spreadsheets, the interactive labs, and the module quizzes. "
        "Each module unlocks the next once you clear its check, and your progress "
        "is saved as you go.",
        size=14,
    )
    if bank_pending:
        # ACH: the debit is initiated but unconfirmed for a few business days.
        # Access is provisional; academy.settlement_ok pulls it if the payment
        # never clears, and _payment_failed emails them if the bank says no.
        body += f"""\
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0 0 16px;">
        <tr>
          <td bgcolor="#fffbeb" style="background-color:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:12px 14px;font-family:{FONT};font-size:13px;line-height:1.6;color:#92400e;">
            One note: you paid by bank transfer, which takes a few business days
            to clear. Your access is active now and will be fully confirmed once
            the payment clears, and there is nothing more for you to do. If it doesn't go
            through, we'll email you right away.
          </td>
        </tr>
      </table>"""
    return _shell(
        "Bank payment processing" if bank_pending else "Payment confirmed",
        "You're in",
        body,
    )


def enrollment_granted_html(full_name: str, course_title: str, link: str) -> str:
    """Manual/comp grant — an admin added this learner by hand."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"You've been given access to <strong>{course_title}</strong> on the "
        "ProReadyEngineer training platform.",
        margin="0 0 22px",
    )
    body += _cta_button("Open the course", link)
    body += _p(
        "This link signs you in once. After that, request a new one any time "
        "from the sign-in page using this same email address.",
        size=13,
        color=MUTED,
        margin="0",
    )
    return _shell("Access granted", "Your course is ready", body)


def payment_receipt_html(
    full_name: str, course_title: str, amount_display: str, reference: str
) -> str:
    """Receipt for a live-cohort seat paid online (PayPal or Stripe)."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    rows = [("Course", course_title)]
    if amount_display:
        rows.append(("Amount", f"<strong>{amount_display}</strong>"))
    if reference:
        rows.append(("Reference", reference))

    body = _p(greeting)
    body += _p(
        f"Your payment for <strong>{course_title}</strong> went through and your "
        "seat is now <strong>confirmed</strong>."
    )
    body += _kv_table(rows)
    body += _p(
        "Keep this email as your receipt. We'll follow up with the joining "
        "details and schedule before the course begins.",
        margin="0",
    )
    return _shell("Payment received", "Your seat is confirmed", body)


def settlement_failed_html(
    full_name: str, course_title: str, course_url: str
) -> str:
    """Recorded product: the bank debit never cleared — access is paused."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"Your bank payment for <strong>{course_title}</strong> didn't clear, so "
        "your course access is paused for now. Your progress is saved; nothing "
        "is lost."
    )
    body += _p(
        "To get back in, pay by card from the course page (it takes a minute and "
        "access is restored instantly), or simply reply to this email and we'll "
        "sort it out and reinstate you.",
        margin="0 0 22px",
    )
    body += _cta_button("Pay by card", course_url)
    body += _p(
        f"Course page: {_link(course_url)}", size=13, color=MUTED, margin="0"
    )
    return _shell("Payment issue", "Your bank payment didn't clear", body)


def live_bank_failed_html(
    full_name: str, course_title: str, course_url: str
) -> str:
    """Live cohort seat: the bank debit never cleared — the seat is still held."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"Your bank payment for <strong>{course_title}</strong> didn't clear. "
        "Don't worry: <strong>your seat is still held</strong> for you."
    )
    body += _p(
        "To confirm it, pay by card from the course page, or reply to this email "
        "and we'll arrange another way to settle it.",
        margin="0 0 22px",
    )
    body += _cta_button("Pay by card", course_url)
    body += _p(
        f"Course page: {_link(course_url)}", size=13, color=MUTED, margin="0"
    )
    return _shell("Payment issue", "Your bank payment didn't clear", body)


def settlement_failed_admin_html(
    buyer_email: str, course_title: str, detail: str
) -> str:
    """Owner heads-up when a bank payment fails or times out unconfirmed."""
    body = _p("A bank (ACH) payment did not clear.")
    body += _kv_table(
        [("Buyer", buyer_email), ("Course", course_title), ("Outcome", detail)],
        size=14,
    )
    body += _p(
        "The buyer has been emailed with card-payment and contact options.",
        size=13,
        color=MUTED,
        margin="0",
    )
    return _shell("Payments", "Bank payment failed", body)


# -----------------------------------------------------------------------------
# Certification
# -----------------------------------------------------------------------------

_TIER_TITLES = {
    "completion": "Certificate of Completion",
    "verified": "Certificate of Verified Competency",
}


def certificate_issued_html(
    full_name: str,
    course_title: str,
    tier: str,
    code: str,
    verify_url: str,
    dashboard_url: str,
) -> str:
    """The certificate itself is attached as a PDF; this carries the links."""
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    title = _TIER_TITLES.get(tier, "Certificate")
    body = _p(greeting)
    if tier == "verified":
        body += _p(
            f"Congratulations. Your <strong>{title}</strong> for "
            f"<strong>{course_title}</strong> is attached. It is signed by your "
            "examiner and records that you were examined live, one-on-one, and "
            "demonstrated a verified command of the subject."
        )
    else:
        body += _p(
            f"Congratulations. You have completed <strong>{course_title}</strong>. "
            f"Your <strong>{title}</strong> is attached as a PDF."
        )
    body += _kv_table(
        [
            ("Credential ID", f"<strong>{code}</strong>"),
            ("Verify at", _link(verify_url)),
        ]
    )
    body += _p(
        "Anyone can confirm this credential at the link above. It checks the "
        "digital signature and shows exactly what was attested. From your course "
        "page you can download the PDF again, add the credential to your LinkedIn "
        "profile, or share it.",
    )
    body += _cta_button("Open your course page", dashboard_url)
    return _shell("Credential issued", f"Your {title}", body)


def advanced_purchased_html(
    full_name: str, course_title: str, exam_url: str, price_display: str
) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"Thank you. Your payment for the <strong>instructor-examined "
        f"certification</strong> in <strong>{course_title}</strong> went through."
    )
    body += _p("<strong>What happens next</strong>", margin="0 0 8px")
    body += _p(
        "1. Pass the advanced written examination from your course page.<br>"
        "2. Propose three 60-minute windows for your live oral examination.<br>"
        "3. Your examiner confirms one and sends the meeting link.<br>"
        "4. After the examination, a pass issues your signed "
        "Certificate of Verified Competency.",
        margin="0 0 22px",
    )
    if price_display:
        body += _kv_table([("Amount", price_display)])
    body += _cta_button("Start the written examination", exam_url)
    body += _p(
        "The fee pays for the examination, not the outcome. If you do not "
        "demonstrate mastery at the first session, one complimentary "
        "re-examination is offered after a study period.",
        size=13,
        color=MUTED,
        margin="0",
    )
    return _shell("Instructor-examined certification", "You're registered for the examination", body)


def advanced_exam_passed_html(full_name: str, course_title: str, score: float, slots_url: str) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"You passed the advanced written examination for <strong>{course_title}</strong> "
        f"with <strong>{score:g}%</strong>. The next step is your live oral examination."
    )
    body += _p(
        "From your course page, propose three 60-minute windows that suit you. "
        "Your examiner will confirm one and you will receive the meeting link by email.",
        margin="0 0 22px",
    )
    body += _cta_button("Propose your interview times", slots_url)
    return _shell("Written examination passed", "Now book your oral examination", body)


def advanced_slots_admin_html(
    learner_name: str, learner_email: str, course_title: str,
    slots_lines: "list[str]", note: str, admin_url: str,
) -> str:
    body = _p(
        f"<strong>{learner_name or learner_email}</strong> ({learner_email}) passed the "
        f"written examination for <strong>{course_title}</strong> and proposed these "
        "windows for the live oral examination:"
    )
    body += _p("<br>".join(slots_lines), margin="0 0 18px")
    if note:
        body += _p(f"Note from the candidate: <em>{note}</em>")
    body += _cta_button("Confirm a slot in the admin panel", admin_url)
    return _shell("Oral examination requested", "A candidate is waiting for a time", body)


def advanced_scheduled_html(
    full_name: str, course_title: str, when_lines: "list[str]", meeting_url: str,
    minutes: int, interview_no: int, dashboard_url: str,
) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    what = "re-examination" if interview_no > 1 else "oral examination"
    body += _p(
        f"Your live {what} for <strong>{course_title}</strong> is confirmed."
    )
    body += _kv_table(
        [("When", "<br>".join(when_lines)), ("Duration", f"{minutes} minutes"),
         ("Meeting link", _link(meeting_url) if meeting_url else "Sent separately")]
    )
    body += _p(
        "Please join from a quiet place with your camera on. You will be asked to "
        "show a photo ID at the start. Questions are asked without notice and you "
        "may be given design cases not covered in the course. Think aloud; the "
        "reasoning is what is being examined.",
    )
    if meeting_url:
        body += _cta_button("Join the examination", meeting_url)
    body += _p(f"Your course page: {_link(dashboard_url)}", size=13, color=MUTED, margin="0")
    return _shell("Oral examination confirmed", "Your examination is booked", body)


def advanced_outcome_retake_html(
    full_name: str, course_title: str, retake_after: str, dashboard_url: str
) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"Thank you for your oral examination in <strong>{course_title}</strong>. "
        "Your examiner concluded that mastery was not yet demonstrated across all "
        "of the principles examined."
    )
    body += _p(
        f"One complimentary re-examination is included. Take some time with the "
        f"material and, on or after <strong>{retake_after}</strong>, propose new "
        "windows from your course page.",
        margin="0 0 22px",
    )
    body += _cta_button("Open your course page", dashboard_url)
    return _shell("Oral examination", "Not yet: a re-examination is available", body)


def advanced_outcome_failed_html(full_name: str, course_title: str) -> str:
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    body = _p(greeting)
    body += _p(
        f"Thank you for your re-examination in <strong>{course_title}</strong>. "
        "Your examiner concluded that mastery was not demonstrated, so no "
        "Certificate of Verified Competency is issued at this time."
    )
    body += _p(
        "Your Certificate of Completion stands, and you keep full access to the "
        "course. If you would like to be examined again in the future, reply to "
        "this email.",
        margin="0",
    )
    return _shell("Oral examination", "Outcome of your re-examination", body)


# -----------------------------------------------------------------------------
# Integrity alerts (to the instructor)
# -----------------------------------------------------------------------------

def integrity_alert_html(
    headline: str,
    meaning: str,
    facts: "list[tuple[str, str]]",
    *,
    next_steps: str,
    integrity_url: str,
) -> str:
    """One shape for every alert about protected material.

    The headline says what happened in plain words; the facts table is the
    evidence as recorded; `next_steps` tells the instructor what the
    platform already did and what is his to decide. Kept factual: an alert
    is not a verdict, and the person named may turn out to be innocent.
    """
    body = _p(meaning)
    body += _kv_table(facts, size=14)
    body += _p(next_steps, size=14)
    body += _cta_button("Open the Integrity tab", integrity_url)
    body += _p(
        "You receive one alert per copy per day; every further signal is "
        "listed in the Integrity tab.",
        size=13, color=MUTED, margin="0",
    )
    return _shell("Integrity alert", headline, body)
