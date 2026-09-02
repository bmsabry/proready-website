"""Certificate renderer — vector PDF, US Letter landscape.

Two tiers share one composition so the family is recognisable:

  completion — "Certificate of Completion". Issued automatically by the
               platform once every lesson is complete and every module
               evaluation and mastery check is passed.
  verified   — "Certificate of Verified Competency — Instructor Examined".
               Issued only by an explicit admin action after the advanced
               written examination and the live oral examination.

Pure reportlab + Pillow + qrcode: no system dependencies, runs on Render as
is. Fonts (OFL) and the seal PNG ship in `assets/`.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from datetime import date

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_DIR = os.path.join(ASSETS, "fonts")
SEAL_PATH = os.path.join(ASSETS, "logo_seal.jpg")

PAGE_W, PAGE_H = landscape(letter)  # 792 x 612 pt

# Brand palette — the site's locked theme, expressed for print.
NAVY = HexColor("#0b1220")
NAVY_DEEP = HexColor("#020617")
INK = HexColor("#0f172a")        # slate-900, body headings
BODY = HexColor("#334155")       # slate-700
MUTED = HexColor("#64748b")      # slate-500
FAINT = HexColor("#cbd5e1")      # slate-300
HAIR = HexColor("#e2e8f0")       # slate-200
CYAN = HexColor("#22d3ee")
BLUE = HexColor("#3b82f6")
WHITE = HexColor("#ffffff")
PAPER = HexColor("#ffffff")

_FONTS_REGISTERED = False


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    for name, file in [
        ("Cinzel", "Cinzel-400.ttf"),
        ("Cinzel-Bold", "Cinzel-700.ttf"),
        ("Cormorant", "CormorantGaramond-400.ttf"),
        ("Cormorant-Italic", "CormorantGaramond-400-italic.ttf"),
        ("Cormorant-Semi", "CormorantGaramond-600.ttf"),
        ("Inter", "Inter-400.ttf"),
        ("Inter-Semi", "Inter-600.ttf"),
        ("Inter-Bold", "Inter-700.ttf"),
        ("Mono", "JetBrainsMono-400.ttf"),
        ("Mono-Medium", "JetBrainsMono-500.ttf"),
    ]:
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, file)))
    _FONTS_REGISTERED = True


@dataclass
class Instructor:
    name: str = "Dr. Bassam Abdelnabi"
    credentials: str = "Ph.D., Aerospace Engineering"
    title: str = "Principal Consultant & Instructor, ProReadyEngineer LLC"


@dataclass
class Issuer:
    legal_name: str = "ProReadyEngineer LLC"
    address: str = "5325 Deerfield Blvd #148, Mason, OH 45040, USA"
    phone: str = "+1 (513) 849-1016"
    email: str = "info@proreadyengineer.com"
    website: str = "www.proreadyengineer.com"
    place: str = "Mason, Ohio, USA"


@dataclass
class CertificateSpec:
    tier: str                      # 'completion' | 'verified'
    learner_name: str
    course_title: str
    course_descriptor: str         # one sentence describing the programme
    credential_id: str
    verify_url: str
    issued_on: date
    signature_fingerprint: str     # short grouped hex of the Ed25519 signature
    # verified tier only
    exam_date: date | None = None
    exam_minutes: int = 60
    competencies: list[str] = field(default_factory=list)
    signature_png: bytes | None = None
    instructor: Instructor = field(default_factory=Instructor)
    issuer: Issuer = field(default_factory=Issuer)
    mastery_threshold_pct: int = 80
    course_hours: float | None = None
    module_count: int | None = None
    # Marketing preview: a faint diagonal SAMPLE watermark so a specimen can
    # never pass as an issued credential.
    sample: bool = False


# -----------------------------------------------------------------------------
# Drawing helpers
# -----------------------------------------------------------------------------

def _fmt_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _gradient_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float,
                   colors: list, horizontal: bool = True) -> None:
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    if horizontal:
        c.linearGradient(x, y, x + w, y, colors, extend=True)
    else:
        c.linearGradient(x, y, x, y + h, colors, extend=True)
    c.restoreState()


def _tracked_text(c: canvas.Canvas, x: float, y: float, text: str, font: str,
                  size: float, tracking: float, color, align: str = "center") -> None:
    """Letter-spaced text (reportlab's charSpace) with alignment handled here."""
    c.saveState()
    c.setFont(font, size)
    c.setFillColor(color)
    width = pdfmetrics.stringWidth(text, font, size) + tracking * (len(text) - 1)
    if align == "center":
        x0 = x - width / 2
    elif align == "right":
        x0 = x - width
    else:
        x0 = x
    t = c.beginText(x0, y)
    t.setCharSpace(tracking)
    t.textOut(text)
    c.drawText(t)
    c.restoreState()


def _wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(trial, font, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _paragraph(c: canvas.Canvas, x: float, y_top: float, text: str, font: str,
               size: float, leading: float, max_w: float, color,
               align: str = "center") -> float:
    """Draw wrapped text; returns the y of the last baseline."""
    c.setFont(font, size)
    c.setFillColor(color)
    y = y_top
    lines = _wrap(text, font, size, max_w)
    for i, line in enumerate(lines):
        if align == "center":
            c.drawCentredString(x + max_w / 2, y, line)
        elif align == "justify" and i < len(lines) - 1:
            words = line.split()
            if len(words) > 1:
                gap = (max_w - pdfmetrics.stringWidth(line.replace(" ", ""), font, size)) / (len(words) - 1)
                xx = x
                for w in words:
                    c.drawString(xx, y, w)
                    xx += pdfmetrics.stringWidth(w, font, size) + gap
            else:
                c.drawString(x, y, line)
        else:
            c.drawString(x, y, line)
        y -= leading
    return y + leading


def _qr_image(url: str, box: int = 8) -> ImageReader:
    q = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box, border=0)
    q.add_data(url)
    q.make(fit=True)
    img = q.make_image(fill_color="#0b1220", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _seal(c: canvas.Canvas, cx: float, cy: float, r: float) -> None:
    """The ProReadyEngineer seal on a white disc with a thin brand ring."""
    c.saveState()
    # soft shadow
    c.setFillColor(Color(0, 0, 0, alpha=0.18))
    c.circle(cx, cy - 1.5, r + 5, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.circle(cx, cy, r + 5, stroke=0, fill=1)
    # The seal artwork is a flattened JPEG (small file) drawn inside a
    # circular clip so its square corners never show over the band.
    c.saveState()
    p = c.beginPath()
    p.circle(cx, cy, r)
    c.clipPath(p, stroke=0, fill=0)
    c.drawImage(SEAL_PATH, cx - r, cy - r, 2 * r, 2 * r)
    c.restoreState()
    c.restoreState()
    # ring drawn as stroked circle with gradient via clip
    c.saveState()
    p = c.beginPath()
    p.rect(cx - r - 8, cy - r - 8, 2 * r + 16, 2 * r + 16)
    c.clipPath(p, stroke=0, fill=0)
    c.setLineWidth(1.6)
    c.setStrokeColor(BLUE)
    c.circle(cx, cy, r + 4.2, stroke=1, fill=0)
    c.setStrokeColor(CYAN)
    c.setLineWidth(0.6)
    c.circle(cx, cy, r + 6.2, stroke=1, fill=0)
    c.restoreState()


def _band(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    """Deep-navy header band with the site's radial glow and faint grid."""
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    c.setFillColor(NAVY_DEEP)
    c.rect(x, y, w, h, stroke=0, fill=1)
    # hero-radial: cyan glow from the top centre, fading into navy
    c.radialGradient(x + w / 2, y + h + 20, w * 0.62,
                     [HexColor("#0e3f52"), HexColor("#0b1f33"), NAVY_DEEP],
                     positions=[0.0, 0.55, 1.0], extend=True)
    # faint grid
    c.setStrokeColor(Color(0.58, 0.64, 0.72, alpha=0.07))
    c.setLineWidth(0.5)
    step = 22
    gx = x
    while gx < x + w:
        c.line(gx, y, gx, y + h)
        gx += step
    gy = y
    while gy < y + h:
        c.line(x, gy, x + w, gy)
        gy += step
    c.restoreState()
    # gradient hairline along the band's bottom edge
    _gradient_rect(c, x, y - 1.2, w, 1.8, [CYAN, BLUE, CYAN])


def _frame(c: canvas.Canvas, inset: float) -> tuple[float, float, float, float]:
    """Outer double rule. Returns the inner box (x, y, w, h)."""
    c.saveState()
    c.setStrokeColor(NAVY)
    c.setLineWidth(1.4)
    c.rect(inset, inset, PAGE_W - 2 * inset, PAGE_H - 2 * inset, stroke=1, fill=0)
    c.setStrokeColor(FAINT)
    c.setLineWidth(0.5)
    i2 = inset + 4
    c.rect(i2, i2, PAGE_W - 2 * i2, PAGE_H - 2 * i2, stroke=1, fill=0)
    c.restoreState()
    return (inset, inset, PAGE_W - 2 * inset, PAGE_H - 2 * inset)


def _verify_block(c: canvas.Canvas, right_x: float, base_y: float,
                  spec: CertificateSpec, *, size: float = 66) -> None:
    """QR + verification text, anchored to a right edge and a bottom baseline."""
    qr = _qr_image(spec.verify_url)
    qx = right_x - size
    qy = base_y
    c.saveState()
    c.setFillColor(WHITE)
    c.setStrokeColor(HAIR)
    c.setLineWidth(0.6)
    c.roundRect(qx - 5, qy - 5, size + 10, size + 10, 4, stroke=1, fill=1)
    c.restoreState()
    c.drawImage(qr, qx, qy, size, size)

    tx = qx - 12
    y = qy + size - 2
    c.setFont("Inter-Semi", 7.2)
    c.setFillColor(INK)
    c.drawRightString(tx, y, "VERIFY THIS CREDENTIAL")
    y -= 11
    c.setFont("Inter", 7.2)
    c.setFillColor(BODY)
    c.drawRightString(tx, y, "Scan the code or visit")
    y -= 10
    c.setFont("Mono-Medium", 7.0)
    c.setFillColor(BLUE)
    c.drawRightString(tx, y, spec.verify_url.replace("https://", ""))
    y -= 13
    c.setFont("Inter", 6.6)
    c.setFillColor(MUTED)
    c.drawRightString(tx, y, "Credential ID")
    c.setFont("Mono-Medium", 7.2)
    c.setFillColor(INK)
    c.drawRightString(tx, y - 9.5, spec.credential_id)
    y -= 22
    c.setFont("Inter", 6.6)
    c.setFillColor(MUTED)
    c.drawRightString(tx, y, "Digital signature (Ed25519)")
    c.setFont("Mono", 6.8)
    c.setFillColor(INK)
    c.drawRightString(tx, y - 9.5, spec.signature_fingerprint)


def _footer(c: canvas.Canvas, box: tuple, spec: CertificateSpec, extra_line: str | None = None,
            fy: float | None = None) -> None:
    x, y, w, h = box
    fy = y + 22 if fy is None else fy
    rule_y = fy + 12 + (11 if extra_line else 0)
    _gradient_rect(c, x + 60, rule_y, w - 120, 0.8, [WHITE, CYAN, BLUE, WHITE])
    iss = spec.issuer
    line = f"{iss.legal_name}   ·   {iss.address}   ·   {iss.phone}   ·   {iss.email}   ·   {iss.website}"
    c.setFont("Inter", 7.4)
    c.setFillColor(MUTED)
    c.drawCentredString(x + w / 2, fy, line)
    if extra_line:
        c.setFont("Inter", 6.4)
        c.setFillColor(MUTED)
        c.drawCentredString(x + w / 2, fy + 11.5, extra_line)


# -----------------------------------------------------------------------------
# Tier 1 — Certificate of Completion
# -----------------------------------------------------------------------------

def _draw_completion(c: canvas.Canvas, spec: CertificateSpec) -> None:
    box = _frame(c, 22)
    x, y, w, h = box
    band_h = 128
    band_y = y + h - band_h
    _band(c, x + 1, band_y, w - 2, band_h - 1)

    cx = PAGE_W / 2
    _tracked_text(c, cx, band_y + band_h - 34, "PROREADYENGINEER LLC   ·   TECHNICAL TRAINING",
                  "Mono-Medium", 7.6, 2.2, CYAN)
    _tracked_text(c, cx, band_y + band_h - 74, "CERTIFICATE OF COMPLETION",
                  "Cinzel", 27, 5.5, WHITE)
    _gradient_rect(c, cx - 120, band_y + band_h - 86, 240, 1.2, [NAVY_DEEP, CYAN, BLUE, NAVY_DEEP])

    # Seal straddling the band's bottom edge
    seal_r = 40
    _seal(c, cx, band_y, seal_r)

    # Body
    top = band_y - seal_r - 22
    _tracked_text(c, cx, top, "THIS IS TO CERTIFY THAT", "Inter-Semi", 8.4, 2.6, MUTED)

    name_y = top - 46
    c.setFont("Cormorant-Semi", 40)
    c.setFillColor(NAVY)
    c.drawCentredString(cx, name_y, spec.learner_name)
    name_w = pdfmetrics.stringWidth(spec.learner_name, "Cormorant-Semi", 40)
    rule_w = max(220, min(name_w + 60, 420))
    _gradient_rect(c, cx - rule_w / 2, name_y - 12, rule_w, 1.1, [WHITE, CYAN, BLUE, WHITE])

    c.setFont("Inter", 11.5)
    c.setFillColor(BODY)
    c.drawCentredString(cx, name_y - 36, "has successfully completed the programme")

    c.setFont("Cinzel-Bold", 17.5)
    c.setFillColor(NAVY)
    c.drawCentredString(cx, name_y - 66, spec.course_title.upper())

    para_w = 560
    last = _paragraph(c, cx - para_w / 2, name_y - 88, spec.course_descriptor,
                      "Inter", 9.6, 13.2, para_w, BODY, align="center")

    facts = []
    if spec.course_hours:
        facts.append(f"{spec.course_hours:g} hours of instruction")
    if spec.module_count:
        facts.append(f"{spec.module_count} modules")
    facts.append(f"mastery threshold {spec.mastery_threshold_pct:g}%")
    _tracked_text(c, cx, last - 20, "   ·   ".join(facts).upper(), "Mono", 6.8, 1.4, MUTED)

    attest = (
        "Completion was verified by the ProReadyEngineer learning platform: the holder completed "
        "every lesson of the programme and passed every module evaluation and mastery check at or "
        f"above the {spec.mastery_threshold_pct:g}% mastery threshold."
    )
    _paragraph(c, cx - 250, last - 44, attest, "Cormorant-Italic", 11.6, 14, 500, INK, align="center")

    # Bottom row: issuer (left) · issue date (centre) · verify (right)
    row_y = y + 62
    # left — issuer block
    lx = x + 58
    c.setStrokeColor(FAINT)
    c.setLineWidth(0.7)
    c.line(lx, row_y + 34, lx + 210, row_y + 34)
    c.setFont("Cinzel", 10.5)
    c.setFillColor(NAVY)
    c.drawString(lx, row_y + 20, "PROREADYENGINEER LLC")
    c.setFont("Inter", 7.6)
    c.setFillColor(BODY)
    c.drawString(lx, row_y + 8, "Issuing organisation")
    c.setFont("Inter-Semi", 7.6)
    c.setFillColor(INK)
    c.drawString(lx, row_y - 4, f"Course instructor: {spec.instructor.name}, {spec.instructor.credentials}")
    c.setFont("Inter", 7.2)
    c.setFillColor(MUTED)
    c.drawString(lx, row_y - 15, "Issued by the ProReadyEngineer learning platform upon verified completion.")

    # centre — date
    c.setFont("Inter", 7.2)
    c.setFillColor(MUTED)
    c.drawCentredString(cx, row_y + 22, "ISSUED ON")
    c.setFont("Cormorant-Semi", 14)
    c.setFillColor(NAVY)
    c.drawCentredString(cx, row_y + 6, _fmt_date(spec.issued_on))
    c.setFont("Inter", 7.2)
    c.setFillColor(MUTED)
    c.drawCentredString(cx, row_y - 6, spec.issuer.place)

    _verify_block(c, x + w - 52, row_y - 20, spec)
    _footer(c, box, spec)


# -----------------------------------------------------------------------------
# Tier 2 — Certificate of Verified Competency (Instructor Examined)
# -----------------------------------------------------------------------------

def _draw_verified(c: canvas.Canvas, spec: CertificateSpec) -> None:
    box = _frame(c, 22)
    x, y, w, h = box
    band_h = 106
    band_y = y + h - band_h
    _band(c, x + 1, band_y, w - 2, band_h - 1)

    cx = PAGE_W / 2
    _tracked_text(c, cx, band_y + band_h - 27, "PROREADYENGINEER LLC   ·   INSTRUCTOR-EXAMINED CREDENTIAL",
                  "Mono-Medium", 7.4, 2.2, CYAN)
    _tracked_text(c, cx, band_y + band_h - 62, "CERTIFICATE OF VERIFIED COMPETENCY",
                  "Cinzel", 24, 4.6, WHITE)
    # two short accent rules either side of the seal
    _gradient_rect(c, cx - 210, band_y + band_h - 74, 150, 1.1, [NAVY_DEEP, CYAN, BLUE])
    _gradient_rect(c, cx + 60, band_y + band_h - 74, 150, 1.1, [BLUE, CYAN, NAVY_DEEP])

    seal_r = 33
    _seal(c, cx, band_y, seal_r)

    top = band_y - seal_r - 16
    _tracked_text(c, cx, top, "THIS IS TO ATTEST THAT", "Inter-Semi", 8.0, 2.6, MUTED)

    name_y = top - 35
    c.setFont("Cormorant-Semi", 32)
    c.setFillColor(NAVY)
    c.drawCentredString(cx, name_y, spec.learner_name)
    name_w = pdfmetrics.stringWidth(spec.learner_name, "Cormorant-Semi", 32)
    rule_w = max(220, min(name_w + 60, 420))
    _gradient_rect(c, cx - rule_w / 2, name_y - 10, rule_w, 1.1, [WHITE, CYAN, BLUE, WHITE])

    c.setFont("Inter", 10.2)
    c.setFillColor(BODY)
    c.drawCentredString(cx, name_y - 28,
                        "has been examined by the undersigned and has demonstrated a verified command of")

    c.setFont("Cinzel-Bold", 15)
    c.setFillColor(NAVY)
    c.drawCentredString(cx, name_y - 51, spec.course_title.upper())

    # Attestation — first person, signed below.
    exam_when = _fmt_date(spec.exam_date) if spec.exam_date else "[examination date]"
    signer = spec.instructor.name.replace("Dr. ", "")
    attest = (
        f"I, {signer}, personally examined the holder in a live, one-on-one oral examination of "
        f"{spec.exam_minutes} minutes, conducted by video conference on {exam_when}, after the holder had "
        f"completed the full programme, all of its module evaluations and mastery checks, and an advanced "
        f"written examination. The holder was questioned without notice on the principles listed below, was "
        f"required to reason through design cases not covered in the course material, and answered to my "
        f"satisfaction. I attest that the holder understands the key principles of this subject and can apply "
        f"them with sound engineering judgement."
    )
    para_w = 620
    last = _paragraph(c, cx - para_w / 2, name_y - 73, attest, "Cormorant", 11.0, 12.9,
                      para_w, INK, align="justify")

    # Principles examined — two columns
    py = last - 17
    _tracked_text(c, cx, py, "PRINCIPLES EXAMINED", "Inter-Semi", 7.2, 2.4, MUTED)
    _gradient_rect(c, cx - 60, py - 5, 120, 0.7, [WHITE, CYAN, BLUE, WHITE])
    items = spec.competencies or []
    col_w = 300
    gap = 20
    left_x = cx - col_w - gap / 2
    right_x = cx + gap / 2
    half = (len(items) + 1) // 2
    cols = [items[:half], items[half:]]
    yy_start = py - 16
    yy_end = yy_start
    for ci, col in enumerate(cols):
        yy = yy_start
        colx = left_x if ci == 0 else right_x
        for k, item in enumerate(col):
            n = k + 1 + (0 if ci == 0 else half)
            c.setFont("Mono-Medium", 6.8)
            c.setFillColor(BLUE)
            c.drawString(colx, yy, f"{n:02d}")
            lines = _wrap(item, "Inter", 7.9, col_w - 16)
            c.setFont("Inter", 7.9)
            c.setFillColor(BODY)
            for li, line in enumerate(lines):
                c.drawString(colx + 15, yy - li * 9.6, line)
            yy -= 9.6 * len(lines) + 3.2
        yy_end = min(yy_end, yy)

    # Bottom row: signature (left) · dates (centre) · verify (right)
    row_y = y + 74
    lx = x + 56
    sig_w, sig_h = 140, 40
    if spec.signature_png:
        c.drawImage(ImageReader(io.BytesIO(spec.signature_png)), lx + 6, row_y + 30, sig_w, sig_h,
                    preserveAspectRatio=True, anchor="sw", mask="auto")
    c.setStrokeColor(FAINT)
    c.setLineWidth(0.7)
    c.line(lx, row_y + 28, lx + 236, row_y + 28)
    c.setFont("Cinzel", 10)
    c.setFillColor(NAVY)
    c.drawString(lx, row_y + 15, spec.instructor.name.upper())
    c.setFont("Inter", 7.4)
    c.setFillColor(BODY)
    c.drawString(lx, row_y + 4, spec.instructor.credentials)
    c.drawString(lx, row_y - 6, spec.instructor.title)
    c.setFont("Inter", 6.8)
    c.setFillColor(MUTED)
    c.drawString(lx, row_y - 17, "Examiner and signatory · signature bound to this credential")

    dx = cx + 34
    c.setFont("Inter", 7.0)
    c.setFillColor(MUTED)
    c.drawCentredString(dx, row_y + 18, "EXAMINED ON")
    c.setFont("Cormorant-Semi", 13)
    c.setFillColor(NAVY)
    c.drawCentredString(dx, row_y + 5, exam_when)
    c.setFont("Inter", 7.0)
    c.setFillColor(MUTED)
    c.drawCentredString(dx, row_y - 7, f"Issued {_fmt_date(spec.issued_on)}")
    c.drawCentredString(dx, row_y - 17, spec.issuer.place)

    _verify_block(c, x + w - 50, row_y - 14, spec, size=60)
    scope = ("This certificate attests to the holder's demonstrated understanding in the examination "
             "described above. It is not a professional engineering licence and confers no authority to "
             "practise engineering or to certify equipment.")
    _footer(c, box, spec, extra_line=scope, fy=y + 18)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def _sample_watermark(c: canvas.Canvas) -> None:
    c.saveState()
    c.setFillColor(Color(0.55, 0.62, 0.72, alpha=0.16))
    c.setFont("Cinzel-Bold", 118)
    c.translate(PAGE_W / 2, PAGE_H / 2 - 20)
    c.rotate(24)
    c.drawCentredString(0, 0, "SAMPLE")
    c.restoreState()


def render_certificate(spec: CertificateSpec) -> bytes:
    _register_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    title = ("Certificate of Completion" if spec.tier == "completion"
             else "Certificate of Verified Competency")
    c.setTitle(f"{title}: {spec.learner_name}, {spec.course_title}")
    c.setAuthor(spec.issuer.legal_name)
    c.setSubject(f"{spec.course_title} · Credential {spec.credential_id}")
    c.setCreator("ProReadyEngineer learning platform")
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    if spec.tier == "completion":
        _draw_completion(c, spec)
    elif spec.tier == "verified":
        _draw_verified(c, spec)
    else:
        raise ValueError(f"unknown tier {spec.tier!r}")
    if spec.sample:
        _sample_watermark(c)
    c.showPage()
    c.save()
    return buf.getvalue()
