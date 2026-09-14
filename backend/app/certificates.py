"""Certificate service: completion rules, issuance, rendering, verification.

Two tiers, one table (models.Certificate):

  completion — free. `maybe_issue_completion` is called after every quiz
               submission and every lesson-completing heartbeat; the moment
               `completion_status(...)["complete"]` is true and the learner
               has a name, the certificate is issued, rendered, stored and
               emailed. No button.
  verified   — the paid, instructor-examined tier. `issue_verified` is only
               ever reached from the admin outcome endpoint; nothing in the
               learner-facing code path can call it.

Rendering is deterministic from the row, but the PDF is rendered ONCE and
stored (AssetBlob) so the file the holder downloads is byte-identical to the
SHA-256 shown on the verify page. Re-issuing (name correction) re-renders and
re-signs under the same code.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
from datetime import date, datetime, timezone
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import academy as svc
from . import certificate_signing as signing
from .certificate_render import CertificateSpec, Instructor, render_certificate
from .config import get_settings
from .emailer import certificate_issued_html, first_name, send_email, sender_as
from .models import AssetBlob, Certificate, Learner, Lesson, Module, Product

log = logging.getLogger(__name__)

TIER_TITLES = {
    "completion": "Certificate of Completion",
    "verified": "Certificate of Verified Competency",
    "attendance": "Certificate of Attendance",
}


# -----------------------------------------------------------------------------
# Completion rule
# -----------------------------------------------------------------------------

def completion_status(db: Session, learner: Learner | None, product_code: str) -> dict:
    """Everything the free tier requires, itemised.

    The rule the owner set: EVERY lesson of EVERY module complete (video
    watched through, deck reached its last slide, tools opened) AND every
    formative and summative set that exists passed at the mastery threshold.
    A module with no items contributes only its lessons.
    """
    modules = db.execute(
        select(Module).where(Module.product_code == product_code).order_by(Module.position)
    ).scalars().all()
    if not modules or learner is None:
        return {
            "complete": False,
            "lessons_total": 0,
            "lessons_done": 0,
            "sets_total": 0,
            "sets_passed": 0,
            "modules": [],
        }
    lessons = db.execute(
        select(Lesson).where(Lesson.module_id.in_([m.id for m in modules]))
    ).scalars().all()
    by_module: dict[int, list[Lesson]] = {}
    for l in lessons:
        by_module.setdefault(l.module_id, []).append(l)
    prog = svc.progress_map(db, learner, [l.id for l in lessons])
    totals = svc.slide_totals(db, [m.id for m in modules])

    out_modules = []
    lessons_total = lessons_done = sets_total = sets_passed = 0
    for module in modules:
        mod_lessons = by_module.get(module.id, [])
        done = sum(
            1 for l in mod_lessons
            if svc.lesson_is_complete(l, prog.get(l.id), totals.get(module.id))
        )
        entry = {
            "id": module.id,
            "code": module.code,
            "title": module.title,
            "lessons_total": len(mod_lessons),
            "lessons_done": done,
            "formative": None,
            "summative": None,
        }
        for item_set in ("formative", "summative"):
            if svc.module_has_items(db, module.id, item_set):
                best = svc.best_attempt(db, learner, module.id, item_set)
                passed = bool(best and best.passed)
                entry[item_set] = {
                    "passed": passed,
                    "best_score": best.score_pct if best else None,
                }
                sets_total += 1
                sets_passed += 1 if passed else 0
        lessons_total += len(mod_lessons)
        lessons_done += done
        out_modules.append(entry)

    complete = (
        lessons_total > 0
        and lessons_done == lessons_total
        and sets_passed == sets_total
    )
    return {
        "complete": complete,
        "lessons_total": lessons_total,
        "lessons_done": lessons_done,
        "sets_total": sets_total,
        "sets_passed": sets_passed,
        "modules": out_modules,
    }


# -----------------------------------------------------------------------------
# Lookups
# -----------------------------------------------------------------------------

def get_certificate(
    db: Session, learner: Learner, product_code: str, tier: str
) -> Certificate | None:
    return db.execute(
        select(Certificate).where(
            Certificate.learner_id == learner.id,
            Certificate.product_code == product_code,
            Certificate.tier == tier,
        )
    ).scalar_one_or_none()


def by_code(db: Session, code: str) -> Certificate | None:
    return db.execute(
        select(Certificate).where(Certificate.code == code.upper().strip())
    ).scalar_one_or_none()


def _new_code(db: Session, tier: str) -> str:
    """PRE-C-… (completion) / PRE-V-… (verified) / PRE-A-… (attendance)."""
    letter = {"verified": "V", "attendance": "A"}.get(tier, "C")
    while True:
        h = secrets.token_hex(4).upper()
        code = f"PRE-{letter}-{h[:4]}-{h[4:]}"
        if by_code(db, code) is None:
            return code


# -----------------------------------------------------------------------------
# Product-level certificate copy (descriptor + competencies)
# -----------------------------------------------------------------------------

def taught_modules(db: Session, product: Product) -> list[Module]:
    """The modules a certificate counts: the taught ones, in order. Support
    modules (`gate_exempt` — the simulator lab, a Q&A handout) are part of
    the course but not a module OF it, and the specimen the owner approved
    counts them out; an issued certificate must say the same number."""
    modules = db.execute(
        select(Module).where(Module.product_code == product.code).order_by(Module.position)
    ).scalars().all()
    return [m for m in modules if not m.gate_exempt]


def course_descriptor(db: Session, product: Product) -> str:
    if product.certificate_descriptor.strip():
        return product.certificate_descriptor.strip()
    n = len(taught_modules(db, product))
    hours = f"{product.total_hours:g}-hour, " if product.total_hours else ""
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
             8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
    count = f"{words.get(n, str(n))}-module " if n else ""
    return f"A {hours}{count}programme. {product.subtitle}".strip()


def course_competencies(db: Session, product: Product) -> list[str]:
    items = [str(x).strip() for x in (product.certificate_competencies or []) if str(x).strip()]
    if items:
        return items
    return [m.title for m in taught_modules(db, product)]


_DAY_PREFIX = re.compile(r"^\s*Day\s+\d+\s*[—\-:.]\s*", re.IGNORECASE)
_CH_SUFFIX = re.compile(r"\s*\((?:Ch\.?|Chapters?|Modules?)[^)]*\)\s*$", re.IGNORECASE)


def cohort_span_for_product(db: Session, product: Product):
    """(first, last) date of a live cohort linked to this product, for the
    attendance specimen. (None, None) when no cohort is linked. The issued
    certificate uses the specific registrant's cohort, not this."""
    from .models import Course  # local import: avoids a cycle at module load

    course = db.execute(
        select(Course).where(Course.recorded_product_code == product.code)
        .order_by(Course.id.desc())
    ).scalars().first()
    dates = []
    for raw in (course.day_dates or []) if course is not None else []:
        try:
            dates.append(date.fromisoformat(str(raw)[:10]))
        except (ValueError, TypeError):
            continue
    return (min(dates), max(dates)) if dates else (None, None)


def attendance_topics(db: Session, product: Product) -> list[str]:
    """The day-by-day outline an attendance certificate lists as 'topics
    covered': the taught modules' titles, cleaned of the 'Day N —' prefix and
    the '(Ch. …)' suffix so each reads as a plain topic. This is the course
    outline, not a claim about the holder — attendance records presence."""
    out: list[str] = []
    for m in taught_modules(db, product):
        title = _CH_SUFFIX.sub("", _DAY_PREFIX.sub("", m.title or "")).strip()
        # A 'Topic: elaboration' title reduces to its topic head, so the
        # outline reads as short labels rather than full sentences.
        head = title.split(":", 1)[0].strip() if ":" in title else title
        if head:
            out.append(head)
    return out


# -----------------------------------------------------------------------------
# Rendering + storage
# -----------------------------------------------------------------------------

def _instructor() -> Instructor:
    s = get_settings()
    return Instructor(
        name=s.INSTRUCTOR_NAME, credentials=s.INSTRUCTOR_CREDENTIALS, title=s.INSTRUCTOR_TITLE
    )


def instructor_signature_png(db: Session) -> bytes | None:
    key = get_settings().INSTRUCTOR_SIGNATURE_ASSET_KEY
    blob = db.execute(select(AssetBlob).where(AssetBlob.key == key)).scalar_one_or_none()
    return bytes(blob.data) if blob is not None and blob.data else None


def verify_url(code: str) -> str:
    return f"{get_settings().SITE_URL}/verify/{code}"


def _png_preview(pdf: bytes, width_px: int = 1200) -> bytes:
    import fitz  # PyMuPDF — pure wheel, no system deps

    doc = fitz.open(stream=pdf, filetype="pdf")
    page = doc[0]
    scale = width_px / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return pix.tobytes("png")


def _put_blob(db: Session, key: str, data: bytes, content_type: str, filename: str) -> None:
    blob = db.execute(select(AssetBlob).where(AssetBlob.key == key)).scalar_one_or_none()
    if blob is None:
        blob = AssetBlob(key=key, filename=filename, content_type=content_type, data=data)
        db.add(blob)
    else:
        blob.data = data
        blob.filename = filename
        blob.content_type = content_type


def blob_bytes(db: Session, key: str) -> bytes | None:
    if not key:
        return None
    blob = db.execute(select(AssetBlob).where(AssetBlob.key == key)).scalar_one_or_none()
    return bytes(blob.data) if blob is not None else None


def build_spec(db: Session, cert: Certificate, product: Product, *, sample: bool = False) -> CertificateSpec:
    settings = get_settings()
    issued_on = svc._aware(cert.issued_at) or datetime.now(timezone.utc)
    module_count = len(taught_modules(db, product))
    return CertificateSpec(
        tier=cert.tier,
        learner_name=cert.learner_name,
        course_title=cert.course_title or product.title,
        course_descriptor=course_descriptor(db, product),
        credential_id=cert.code,
        verify_url=verify_url(cert.code),
        issued_on=issued_on.date(),
        signature_fingerprint=cert.signature_fingerprint or "—",
        exam_date=cert.exam_date,
        exam_minutes=cert.exam_minutes or settings.ADVANCED_INTERVIEW_MINUTES,
        competencies=list(cert.competencies or []),
        signature_png=instructor_signature_png(db) if cert.tier == "verified" else None,
        instructor=_instructor(),
        mastery_threshold_pct=int(settings.MASTERY_THRESHOLD_PCT),
        course_hours=product.total_hours or None,
        module_count=module_count or None,
        cohort_start=cert.cohort_start,
        cohort_end=cert.cohort_end,
        sample=sample,
    )


def sign_and_render(db: Session, cert: Certificate, product: Product) -> None:
    """Sign the canonical facts, render the PDF + PNG, store both, hash."""
    issued_on = (svc._aware(cert.issued_at) or datetime.now(timezone.utc)).date()
    payload = signing.canonical_payload(
        code=cert.code,
        tier=cert.tier,
        learner_name=cert.learner_name,
        product_code=cert.product_code,
        course_title=cert.course_title,
        issued_on=issued_on,
        exam_date=cert.exam_date,
    )
    cert.signature_b64 = signing.sign(payload)
    cert.signature_fingerprint = signing.fingerprint(cert.signature_b64)

    spec = build_spec(db, cert, product)
    if cert.tier == "verified" and spec.signature_png is None:
        raise RuntimeError(
            "The instructor's signature image is not uploaded — refusing to issue "
            "an unsigned Certificate of Verified Competency."
        )
    pdf = render_certificate(spec)
    cert.pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    cert.pdf_key = f"cert:{cert.code}.pdf"
    cert.preview_key = f"cert:{cert.code}.png"
    _put_blob(db, cert.pdf_key, pdf, "application/pdf", f"{cert.code}.pdf")
    try:
        _put_blob(db, cert.preview_key, _png_preview(pdf), "image/png", f"{cert.code}.png")
    except Exception as exc:  # pragma: no cover — preview is a nicety
        log.error("Certificate preview render failed for %s: %s", cert.code, exc)
        cert.preview_key = ""
    db.commit()


def signature_valid(cert: Certificate) -> bool:
    issued_on = (svc._aware(cert.issued_at) or datetime.now(timezone.utc)).date()
    payload = signing.canonical_payload(
        code=cert.code,
        tier=cert.tier,
        learner_name=cert.learner_name,
        product_code=cert.product_code,
        course_title=cert.course_title,
        issued_on=issued_on,
        exam_date=cert.exam_date,
    )
    return signing.verify(payload, cert.signature_b64)


# -----------------------------------------------------------------------------
# Issuance
# -----------------------------------------------------------------------------

def _issue(
    db: Session,
    learner: Learner,
    product: Product,
    tier: str,
    *,
    exam_date: date | None = None,
    exam_minutes: int = 0,
    competencies: list[str] | None = None,
    cohort_start: date | None = None,
    cohort_end: date | None = None,
) -> Certificate:
    if tier == "verified" and instructor_signature_png(db) is None:
        raise RuntimeError(
            "The instructor's signature image is not uploaded — refusing to issue "
            "an unsigned Certificate of Verified Competency."
        )
    cert = Certificate(
        learner_id=learner.id,
        product_code=product.code,
        code=_new_code(db, tier),
        learner_name=learner.full_name.strip(),
        tier=tier,
        status="issued",
        course_title=product.title,
        issued_at=datetime.now(timezone.utc),
        exam_date=exam_date,
        exam_minutes=exam_minutes,
        competencies=list(competencies or []),
        cohort_start=cohort_start,
        cohort_end=cohort_end,
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)
    try:
        sign_and_render(db, cert, product)
    except Exception:
        # No half-issued rows: an unsigned/unrendered certificate must not
        # exist, or the dashboard and verify page would show a phantom.
        db.rollback()
        db.delete(cert)
        db.commit()
        raise
    return cert


def booking_url(product_code: str) -> str:
    """Opens the learner's course page at the examination card, where the
    'Register for the examination' button starts the paid tier (Dashboard
    reads ?advanced=start; a signed-out click survives sign-in)."""
    return f"{get_settings().SITE_URL}/learn/{product_code}?advanced=start"


def _price_display(cents: int, currency: str) -> str:
    amount = f"{cents / 100:,.0f}" if cents % 100 == 0 else f"{cents / 100:,.2f}"
    return f"${amount} {currency.upper()}"


def examined_tier_offer(db: Session, learner: Learner, product: Product) -> dict | None:
    """The facts the course page publishes about the paid tier, for the
    completion email. Every finisher hears about it; None only when this
    learner already holds it. `bookable` says whether the course page can
    take the registration today (tier switched on, exam bank loaded, price
    set); otherwise the email carries a request link instead of a dead one."""
    from . import advanced_cert as adv  # noqa: PLC0415 — advanced_cert imports this module

    if get_certificate(db, learner, product.code, "verified") is not None:
        return None
    settings = get_settings()
    price = product.advanced_cert_price_cents
    bookable = adv.offered(db, product) and price > 0
    subject = quote(f"Verified Competency examination — {product.title}", safe="")
    return {
        "bookable": bookable,
        "price_display": _price_display(price, product.currency) if price > 0 else "",
        "exam_item_count": len(adv.exam_items(db, product.code)),
        "exam_threshold_pct": settings.ADVANCED_EXAM_THRESHOLD_PCT,
        "exam_max_attempts": settings.ADVANCED_EXAM_MAX_ATTEMPTS,
        "interview_minutes": settings.ADVANCED_INTERVIEW_MINUTES,
        "booking_url": booking_url(product.code),
        "request_mailto": f"mailto:{settings.EMAIL_REPLY_TO}?subject={subject}",
    }


def email_certificate(db: Session, cert: Certificate, learner: Learner, product: Product) -> None:
    """The instructor's congratulations, sent under his name with him on cc,
    the certificate PDF attached — and, on a completion certificate, the
    invitation to book the instructor-examined tier."""
    settings = get_settings()
    pdf = blob_bytes(db, cert.pdf_key)
    attachments = None
    if pdf:
        attachments = [
            {
                "filename": f"ProReadyEngineer_{TIER_TITLES[cert.tier].replace(' ', '_')}_{cert.code}.pdf",
                "content": base64.b64encode(pdf).decode(),
            }
        ]
    offer = (
        examined_tier_offer(db, learner, product)
        if cert.tier in ("completion", "attendance")
        else None
    )
    who = first_name(learner.full_name or "")
    ok = send_email(
        to=learner.email,
        subject=(
            f"Congratulations{', ' + who if who else ''} — your {TIER_TITLES[cert.tier]} "
            f"for {product.title}"
        ),
        html=certificate_issued_html(
            learner.full_name or "",
            product.title,
            cert.tier,
            cert.code,
            verify_url(cert.code),
            f"{settings.SITE_URL}/learn/{product.code}",
            instructor_name=settings.INSTRUCTOR_NAME,
            instructor_credentials=settings.INSTRUCTOR_CREDENTIALS,
            instructor_title=settings.INSTRUCTOR_TITLE,
            mastery_threshold_pct=settings.MASTERY_THRESHOLD_PCT,
            offer=offer,
        ),
        from_override=sender_as(settings.INSTRUCTOR_NAME, mailbox=settings.INSTRUCTOR_MAILBOX),
        cc=settings.ADMIN_NOTIFY_EMAIL or None,
        db=db,
        scope_kind="product",
        scope_code=product.code,
        template=f"certificate_{cert.tier}",
        attachments=attachments,
    )
    if ok:
        cert.email_sent_at = datetime.now(timezone.utc)
        db.commit()


def maybe_issue_completion(db: Session, learner: Learner, product_code: str) -> Certificate | None:
    """The auto-issue hook. Cheap when nothing is due; idempotent.

    Returns the certificate when one exists (new or old), None otherwise.
    A learner with no name on file is held back — the certificate needs a
    real name and the dashboard asks for one.
    """
    existing = get_certificate(db, learner, product_code, "completion")
    if existing is not None:
        return existing
    if not learner.full_name.strip():
        return None
    if not completion_status(db, learner, product_code)["complete"]:
        return None
    product = db.get(Product, product_code)
    if product is None:
        return None
    cert = _issue(db, learner, product, "completion")
    log.info("Issued completion certificate %s to %s for %s", cert.code, learner.email, product_code)
    try:
        email_certificate(db, cert, learner, product)
    except Exception as exc:  # pragma: no cover — issuance must not depend on email
        log.error("Certificate email failed for %s: %s", cert.code, exc)
    return cert


def issue_verified(
    db: Session,
    learner: Learner,
    product: Product,
    *,
    exam_date: date,
    exam_minutes: int,
) -> Certificate:
    """Admin-only. The caller is the outcome endpoint; nothing else."""
    existing = get_certificate(db, learner, product.code, "verified")
    if existing is not None:
        return existing
    if not learner.full_name.strip():
        raise ValueError("The learner has no name on file.")
    cert = _issue(
        db, learner, product, "verified",
        exam_date=exam_date,
        exam_minutes=exam_minutes,
        competencies=course_competencies(db, product),
    )
    log.info("Issued VERIFIED certificate %s to %s for %s", cert.code, learner.email, product.code)
    try:
        email_certificate(db, cert, learner, product)
    except Exception as exc:  # pragma: no cover
        log.error("Certificate email failed for %s: %s", cert.code, exc)
    return cert


def issue_attendance(
    db: Session,
    learner: Learner,
    product: Product,
    *,
    cohort_start: date | None = None,
    cohort_end: date | None = None,
    send_email: bool = True,
) -> Certificate:
    """The moderator-issued tier: recorded presence at the live course.

    Idempotent — a learner holds at most one attendance certificate per
    product; re-marking returns the existing one and does not re-email.
    """
    existing = get_certificate(db, learner, product.code, "attendance")
    if existing is not None:
        return existing
    if not learner.full_name.strip():
        raise ValueError("The learner has no name on file.")
    cert = _issue(
        db, learner, product, "attendance",
        competencies=attendance_topics(db, product),
        cohort_start=cohort_start,
        cohort_end=cohort_end,
    )
    log.info("Issued ATTENDANCE certificate %s to %s for %s", cert.code, learner.email, product.code)
    if send_email:
        try:
            email_certificate(db, cert, learner, product)
        except Exception as exc:  # pragma: no cover
            log.error("Certificate email failed for %s: %s", cert.code, exc)
    return cert


def reissue(db: Session, cert: Certificate, *, learner_name: str | None = None) -> Certificate:
    """Name correction: same code, new signature, new file."""
    product = db.get(Product, cert.product_code)
    if product is None:
        raise ValueError("Product missing.")
    if learner_name is not None and learner_name.strip():
        cert.learner_name = learner_name.strip()
    cert.course_title = product.title
    cert.status = "issued"
    cert.revoke_reason = ""
    db.commit()
    sign_and_render(db, cert, product)
    return cert


def revoke(db: Session, cert: Certificate, reason: str) -> None:
    cert.status = "revoked"
    cert.revoke_reason = reason.strip()[:300]
    db.commit()


# -----------------------------------------------------------------------------
# Serialisers
# -----------------------------------------------------------------------------

def linkedin_links(cert: Certificate, product: Product) -> dict:
    """The two things LinkedIn lets an issuer do without an approved app.

    add_to_profile — opens Licenses & certifications pre-filled.
    share          — opens the post composer with the verify page attached;
                     the page's OG tags carry the certificate image.
    """
    settings = get_settings()
    issued = svc._aware(cert.issued_at) or datetime.now(timezone.utc)
    url = verify_url(cert.code)
    name = f"{TIER_TITLES[cert.tier]} — {product.title}"
    params = {
        "startTask": "CERTIFICATION_NAME",
        "name": name,
        "organizationName": "ProReadyEngineer LLC",
        "issueYear": str(issued.year),
        "issueMonth": str(issued.month),
        "certUrl": url,
        "certId": cert.code,
    }
    if settings.LINKEDIN_ORGANIZATION_ID:
        params["organizationId"] = settings.LINKEDIN_ORGANIZATION_ID
    q = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return {
        "add_to_profile": f"https://www.linkedin.com/profile/add?{q}",
        "share": f"https://www.linkedin.com/sharing/share-offsite/?url={quote(url, safe='')}",
    }


def certificate_out(db: Session, cert: Certificate, product: Product) -> dict:
    """Learner-facing shape."""
    settings = get_settings()
    api = ""  # relative; the SPA prefixes API_BASE
    return {
        "code": cert.code,
        "tier": cert.tier,
        "title": TIER_TITLES.get(cert.tier, cert.tier),
        "status": cert.status,
        "learner_name": cert.learner_name,
        "course_title": cert.course_title or product.title,
        "issued_at": cert.issued_at,
        "exam_date": cert.exam_date,
        "signature_fingerprint": cert.signature_fingerprint,
        "pdf_sha256": cert.pdf_sha256,
        "verify_url": verify_url(cert.code),
        "pdf_url": f"{api}/api/academy/verify/{cert.code}/certificate.pdf",
        "preview_url": f"{api}/api/academy/verify/{cert.code}/certificate.png" if cert.preview_key else "",
        "linkedin": linkedin_links(cert, product),
        "site_url": settings.SITE_URL,
    }


def verify_out(db: Session, cert: Certificate) -> dict:
    """Public shape: holder, course, tier, dates, integrity — nothing else."""
    product = db.get(Product, cert.product_code)
    valid_sig = signature_valid(cert)
    return {
        "valid": cert.status == "issued" and valid_sig,
        "status": cert.status,
        "revoke_reason": cert.revoke_reason if cert.status == "revoked" else "",
        "code": cert.code,
        "tier": cert.tier,
        "title": TIER_TITLES.get(cert.tier, cert.tier),
        "learner_name": cert.learner_name,
        "course": cert.course_title or (product.title if product else cert.product_code),
        "product_code": cert.product_code,
        "issued_at": cert.issued_at,
        "exam_date": cert.exam_date,
        "exam_minutes": cert.exam_minutes,
        "competencies": list(cert.competencies or []),
        "signature_valid": valid_sig,
        "signature_fingerprint": cert.signature_fingerprint,
        "signing_key_id": signing.key_id(),
        "public_key_b64": signing.public_key_b64(),
        "pdf_sha256": cert.pdf_sha256,
        "has_pdf": bool(cert.pdf_key),
        "has_preview": bool(cert.preview_key),
        "instructor": get_settings().INSTRUCTOR_NAME if cert.tier == "verified" else "",
        "issuer": "ProReadyEngineer LLC",
    }
