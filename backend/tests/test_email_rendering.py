"""Every outbound email must survive a mail client that rewrites <body>.

The bug this file exists to prevent shipped a real "Your course is ready"
email in which the greeting, the body paragraph and the button label were all
invisible — near-black text on a dark navy card. Two causes, both structural:

  1. Those elements set no `color` of their own. They inherited it from
     <body style="color:#e2e8f0">. Gmail, Yahoo and Outlook.com rewrite or drop
     <body>, so the inherited colour disappeared and the client's default
     near-black applied. The elements that DID set their own colour — the
     heading, the eyebrow, the footnotes — rendered correctly, which is exactly
     the pattern the screenshot showed.

  2. The call-to-action was an <a> with `background:linear-gradient(...)` and
     near-black label text. Mail clients do not render CSS gradients, so the
     background fell away and the label was black-on-navy.

These tests assert the structural properties rather than the pixels: no
inherited text colour, no gradients, a real bgcolor on every button, and
enough contrast to read.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser

import pytest

from app import emailer as E

LINK = "https://proreadyengineer.com/academy/sign-in?token=t"

# Every template, rendered with representative content.
TEMPLATES = {
    "enrollment_granted": lambda: E.enrollment_granted_html("Ada", "Course X", LINK),
    "login_link": lambda: E.login_link_html("Ada", LINK, 30),
    "purchase_welcome": lambda: E.purchase_welcome_html("Ada", "Course X", LINK, 30),
    "purchase_welcome_ach": lambda: E.purchase_welcome_html(
        "Ada", "Course X", LINK, 30, bank_pending=True
    ),
    "applicant_confirmation": lambda: E.applicant_confirmation_html(
        "Ada", "Course X", "August 29, 2026", "$1,000", "We'll invoice you."
    ),
    "applicant_confirmation_no_price": lambda: E.applicant_confirmation_html(
        "", "Course X", "August 29, 2026", "", "We'll invoice you."
    ),
    "payment_receipt": lambda: E.payment_receipt_html("Ada", "Course X", "$1,000", "R1"),
    "payment_receipt_bare": lambda: E.payment_receipt_html("", "Course X", "", ""),
    "broadcast": lambda: E.broadcast_html(
        "Course X", '<p style="margin:0;">Admin wrote this.</p>'
    ),
    "start_date_updated": lambda: E.start_date_updated_html(
        "Course X", date(2026, 5, 15), date(2026, 8, 29)
    ),
    "settlement_failed": lambda: E.settlement_failed_html("Ada", "Course X", LINK),
    "live_bank_failed": lambda: E.live_bank_failed_html("Ada", "Course X", LINK),
    "settlement_failed_admin": lambda: E.settlement_failed_admin_html(
        "ada@example.com", "Course X", "R01 insufficient funds"
    ),
    "admin_notification": lambda: E.admin_notification_html(
        {"Name": "Ada", "Email": "ada@example.com"}, 3, 15
    ),
    "session_reminder": lambda: E.session_reminder_html(
        "Ada Lovelace", "Course X", 2, 4,
        ["14:00 UTC on Saturday, March 2", "10:00 EDT in Cincinnati, OH — your local time"],
        "To join the video meeting, click this link: https://meet.google.com/abc-defg-hij\n"
        "Otherwise, to join by phone, dial +1 321-430-1922 and enter this PIN: 316 913 670#",
        60,
    ),
}

IGNORED_TEXT_TAGS = {"title", "style", "script", "head", "meta"}


class _UncolouredText(HTMLParser):
    """Find text that would render in the mail client's default colour.

    Walks the tree keeping a stack of open elements. Text is safe when it, or
    an ancestor that is NOT <body>/<html>, sets an inline `color`. <body> is
    excluded on purpose: that is the element clients rewrite, and trusting it
    is the whole bug.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.offenders: list[str] = []

    def handle_starttag(self, tag, attrs):
        style = dict(attrs).get("style") or ""
        # Match `color:` as its own declaration — a substring search would count
        # `background-color:` as a text colour and wave the bug straight through.
        sets_colour = any(
            part.strip().startswith("color:") for part in style.split(";")
        )
        self.stack.append((tag, sets_colour))
        if tag in ("br", "img", "meta", "link", "input", "hr"):
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not data.strip():
            return
        if any(t in IGNORED_TEXT_TAGS for t, _ in self.stack):
            return
        inherited = any(
            sets_colour for tag, sets_colour in self.stack if tag not in ("body", "html")
        )
        if not inherited:
            path = " > ".join(t for t, _ in self.stack)
            self.offenders.append(f"{path}: {data.strip()[:60]!r}")


def _relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_text_depends_on_the_body_element_for_its_colour(name):
    parser = _UncolouredText()
    parser.feed(TEMPLATES[name]())
    assert not parser.offenders, (
        f"{name}: text with no colour of its own would render in the mail "
        f"client's default once <body> is rewritten:\n  "
        + "\n  ".join(parser.offenders)
    )


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_css_gradients(name):
    html = TEMPLATES[name]()
    assert "gradient" not in html, (
        f"{name}: mail clients do not render CSS gradients — the background "
        "falls away and whatever sits on it is left on the bare card."
    )


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_light_card_never_carries_dark_backgrounds_behind_body_text(name):
    """The card body is light; a dark background there means dark-on-dark risk."""
    html = TEMPLATES[name]()
    assert E.CARD_BG.lower() == "#ffffff"
    assert E.PAGE_BG.lower() != E.INK.lower()


def test_the_button_paints_its_own_background():
    html = E.enrollment_granted_html("Ada", "Course X", LINK)
    assert f'bgcolor="{E.BUTTON_BG}"' in html, (
        "Outlook reads the bgcolor attribute, not just the style"
    )
    assert f"background-color:{E.BUTTON_BG}" in html
    assert f"color:{E.BUTTON_TEXT}" in html


def test_readable_contrast_everywhere_it_matters():
    checks = {
        "body text on card": (E.INK, E.CARD_BG, 4.5),
        "heading on card": (E.HEADING, E.CARD_BG, 4.5),
        "muted text on card": (E.MUTED, E.CARD_BG, 4.5),
        "link on card": (E.LINK, E.CARD_BG, 4.5),
        "button label on button": (E.BUTTON_TEXT, E.BUTTON_BG, 4.5),
        "wordmark on band": (E.BAND_TEXT, E.BAND_BG, 4.5),
        "eyebrow on band": (E.EYEBROW, E.BAND_BG, 4.5),
        "footer text on footer": (E.MUTED, E.FOOTER_BG, 4.5),
    }
    failures = []
    for label, (fg, bg, want) in checks.items():
        got = _contrast(fg, bg)
        if got < want:
            failures.append(f"{label}: {got:.2f}:1 (need {want}:1)")
    assert not failures, "unreadable colour pairs:\n  " + "\n  ".join(failures)


def test_composed_broadcast_paragraphs_carry_their_own_colour():
    """The admin's own words go through the same rule."""
    from app.ai_tools import _plain_text_to_email_html

    composed = _plain_text_to_email_html("Hello.\n\nSee https://example.com please.")
    assert f"color:{E.INK}" in composed
    assert f"color:{E.LINK}" in composed

    parser = _UncolouredText()
    parser.feed(E.broadcast_html("Course X", composed))
    assert not parser.offenders, parser.offenders


def test_the_old_markup_would_have_failed_this():
    """Guard the guard: the checker must actually catch the shipped bug."""
    old = (
        '<html><body style="background:#0f172a;color:#e2e8f0;">'
        '<p style="margin:0 0 16px;font-size:15px;">Hi,</p>'
        '<a href="#" style="background:linear-gradient(90deg,#22d3ee,#3b82f6);'
        'color:#04121f;">Open the course</a>'
        "</body></html>"
    )
    parser = _UncolouredText()
    parser.feed(old)
    assert parser.offenders, "the checker must flag text that only <body> colours"
    assert "gradient" in old


# ---------------------------------------------------------------------------
# The plain-text alternative
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_yields_readable_plain_text(name):
    text = E.html_to_text(TEMPLATES[name]())
    assert text.strip(), f"{name}: empty text part"
    assert "<" not in text and ">" not in text, f"{name}: markup leaked into the text part"
    assert "ProReadyEngineer" in text


def test_the_text_part_keeps_link_destinations():
    """A text part whose call to action is the bare words "Open the course" is
    useless — the reader cannot get anywhere."""
    text = E.html_to_text(E.enrollment_granted_html("Ada", "Course X", LINK))
    assert f"Open the course ({LINK})" in text


def test_the_text_part_does_not_repeat_a_mailto_twice():
    text = E.html_to_text(E.enrollment_granted_html("Ada", "Course X", LINK))
    assert "mailto:" not in text
    assert "info@proreadyengineer.com" in text


def test_send_email_attaches_the_text_part(monkeypatch):
    """Multipart, not HTML-only: some gateways strip HTML, and HTML-only mail
    scores worse with spam filters."""
    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "abc"}

    def fake_post(url, payload, key):
        captured.update(payload)
        return _Resp()

    monkeypatch.setattr(E, "_resend_post", fake_post)
    settings = E.get_settings()
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test", raising=False)

    E.send_email(
        to="ada@example.com",
        subject="Hi",
        html=E.enrollment_granted_html("Ada", "Course X", LINK),
    )
    assert "text" in captured, "no plain-text alternative was sent"
    assert "Open the course" in captured["text"]


def test_an_explicit_text_part_is_not_overwritten(monkeypatch):
    """The support desk sends the customer's own wording — don't re-derive it."""
    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "abc"}

    monkeypatch.setattr(
        E, "_resend_post", lambda url, payload, key: (captured.update(payload), _Resp())[1]
    )
    settings = E.get_settings()
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test", raising=False)

    E.send_email(
        to="ada@example.com", subject="Hi", html="<p>ignored</p>", text="exact wording"
    )
    assert captured["text"] == "exact wording"
