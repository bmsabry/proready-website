"""Admin API for certification — the only place the examined tier is decided.

  GET  /api/admin/academy/certification/{product_code}          overview
  POST /api/admin/academy/certification/{product_code}/exam-items load the
                                                                  written bank
  GET  /api/admin/academy/certification/{product_code}/sample.pdf preview
  POST /api/admin/academy/certification/signature               upload PNG
  POST /api/admin/academy/certification/comp                    comp a candidate
  POST /api/admin/academy/certification/advanced/{id}/schedule
  POST /api/admin/academy/certification/advanced/{id}/outcome   pass|retake|fail
  POST /api/admin/academy/certification/advanced/{id}/reopen
  POST /api/admin/academy/certification/advanced/{id}/reset-exam
  POST /api/admin/academy/certification/advanced/{id}/cancel
  POST /api/admin/academy/certification/certificates/{code}/revoke
  POST /api/admin/academy/certification/certificates/{code}/reissue
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import academy as svc
from .. import advanced_cert as adv
from .. import certificates as certs
from ..certificate_render import CertificateSpec, render_certificate
from ..config import get_settings
from ..db import get_db
from ..deps import require_admin
from ..models import AdvancedCertification, AssetBlob, Certificate, Learner, Product, QuizItem

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/academy/certification", tags=["academy-admin-certification"])


def _product(db: Session, code: str) -> Product:
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


def _cert_admin_out(db: Session, cert: Certificate) -> dict:
    learner = db.get(Learner, cert.learner_id)
    return {
        "code": cert.code,
        "tier": cert.tier,
        "status": cert.status,
        "revoke_reason": cert.revoke_reason,
        "learner_id": cert.learner_id,
        "email": learner.email if learner else "",
        "learner_name": cert.learner_name,
        "product_code": cert.product_code,
        "issued_at": cert.issued_at,
        "exam_date": cert.exam_date,
        "signature_fingerprint": cert.signature_fingerprint,
        "signature_valid": certs.signature_valid(cert),
        "email_sent_at": cert.email_sent_at,
        "verify_url": certs.verify_url(cert.code),
        "pdf_url": f"/api/academy/verify/{cert.code}/certificate.pdf",
    }


@router.get("/{product_code}")
def overview(
    product_code: str, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    product = _product(db, product_code)
    rows = db.execute(
        select(AdvancedCertification)
        .where(AdvancedCertification.product_code == product_code)
        .order_by(AdvancedCertification.created_at.desc())
    ).scalars().all()
    issued = db.execute(
        select(Certificate)
        .where(Certificate.product_code == product_code)
        .order_by(Certificate.issued_at.desc())
    ).scalars().all()
    settings = get_settings()
    return {
        "product": {
            "code": product.code,
            "title": product.title,
            "advanced_cert_enabled": product.advanced_cert_enabled,
            "advanced_cert_price_cents": product.advanced_cert_price_cents,
            "currency": product.currency,
            "certificate_descriptor": product.certificate_descriptor,
            "certificate_descriptor_effective": certs.course_descriptor(db, product),
            "certificate_competencies": list(product.certificate_competencies or []),
            "certificate_competencies_effective": certs.course_competencies(db, product),
        },
        "exam_item_count": len(adv.exam_items(db, product_code)),
        "signature_uploaded": certs.instructor_signature_png(db) is not None,
        "signing_key_id": certs.signing.key_id(),
        "signing_key_from_env": bool(settings.CERT_SIGNING_KEY),
        "interview_minutes": settings.ADVANCED_INTERVIEW_MINUTES,
        "candidates": [adv.admin_out(db, r) for r in rows],
        "certificates": [_cert_admin_out(db, c) for c in issued],
        "counts": {
            "completion": sum(1 for c in issued if c.tier == "completion" and c.status == "issued"),
            "verified": sum(1 for c in issued if c.tier == "verified" and c.status == "issued"),
            "awaiting_action": sum(1 for r in rows if r.status in ("slots_proposed", "scheduled")),
        },
    }


# -----------------------------------------------------------------------------
# Written examination bank
# -----------------------------------------------------------------------------

class ExamItemIn(BaseModel):
    code: str
    kind: str = "mcq"
    stem: str
    options: list = []
    answer: dict = {}
    rubric: str = ""
    explanation: str = ""
    cognitive_level: str = ""
    outcome_id: str = ""
    position: int = 0


class ExamBankIn(BaseModel):
    items: list[ExamItemIn]
    replace: bool = True


@router.post("/{product_code}/exam-items")
def load_exam_items(
    product_code: str,
    body: ExamBankIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    _product(db, product_code)
    if not body.items:
        raise HTTPException(status_code=400, detail="No items supplied.")
    for item in body.items:
        if item.kind == "mcq":
            keys = {o.get("key") for o in item.options if isinstance(o, dict)}
            if item.answer.get("key") not in keys:
                raise HTTPException(
                    status_code=400, detail=f"Item {item.code}: answer key not among options."
                )
    if body.replace:
        db.execute(
            delete(QuizItem).where(
                QuizItem.product_code == product_code, QuizItem.item_set == "advanced"
            )
        )
    for item in body.items:
        db.add(
            QuizItem(
                module_id=0, product_code=product_code, item_set="advanced",
                **item.model_dump(),
            )
        )
    db.commit()
    n = len(adv.exam_items(db, product_code))
    log.info("Advanced exam bank loaded for %s: %d items", product_code, n)
    return {"ok": True, "product_code": product_code, "items_total": n}


# -----------------------------------------------------------------------------
# Preview + signature
# -----------------------------------------------------------------------------

@router.get("/{product_code}/sample.pdf")
def sample_pdf(
    product_code: str,
    tier: str = "completion",
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> Response:
    """Render a SAMPLE-watermarked specimen with the product's current copy."""
    product = _product(db, product_code)
    if tier not in ("completion", "verified"):
        raise HTTPException(status_code=400, detail="tier must be completion or verified.")
    settings = get_settings()
    spec = CertificateSpec(
        tier=tier,
        learner_name="Your Name Here",
        course_title=product.title,
        course_descriptor=certs.course_descriptor(db, product),
        credential_id="PRE-C-0000-0000" if tier == "completion" else "PRE-V-0000-0000",
        verify_url=f"{settings.SITE_URL}/verify/SAMPLE",
        issued_on=date.today(),
        signature_fingerprint="0000-0000-0000-0000",
        exam_date=date.today(),
        exam_minutes=settings.ADVANCED_INTERVIEW_MINUTES,
        competencies=certs.course_competencies(db, product),
        signature_png=certs.instructor_signature_png(db) if tier == "verified" else None,
        instructor=certs._instructor(),
        mastery_threshold_pct=int(settings.MASTERY_THRESHOLD_PCT),
        course_hours=product.total_hours or None,
        module_count=len(certs.course_competencies(db, product)) or None,
        sample=True,
    )
    return Response(
        content=render_certificate(spec),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="sample-{tier}.pdf"'},
    )


class SignatureIn(BaseModel):
    png_b64: str


@router.post("/signature")
def upload_signature(
    body: SignatureIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    """Store the instructor's handwritten signature (PNG with alpha)."""
    try:
        data = base64.b64decode(body.png_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload.")
    if not data.startswith(b"\x89PNG"):
        raise HTTPException(status_code=400, detail="The signature must be a PNG.")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Signature exceeds the 2MB cap.")
    key = get_settings().INSTRUCTOR_SIGNATURE_ASSET_KEY
    row = db.execute(select(AssetBlob).where(AssetBlob.key == key)).scalar_one_or_none()
    if row is None:
        row = AssetBlob(key=key)
        db.add(row)
    row.filename = "signature.png"
    row.content_type = "image/png"
    row.data = data
    db.commit()
    return {"ok": True, "bytes": len(data)}


# -----------------------------------------------------------------------------
# Candidates
# -----------------------------------------------------------------------------

def _row(db: Session, row_id: int) -> tuple[AdvancedCertification, Learner, Product]:
    row = db.get(AdvancedCertification, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    learner = db.get(Learner, row.learner_id)
    product = db.get(Product, row.product_code)
    if learner is None or product is None:
        raise HTTPException(status_code=404, detail="Candidate's learner or product is missing.")
    return row, learner, product


class CompIn(BaseModel):
    email: EmailStr
    product_code: str
    note: str = ""
    send_email: bool = True


@router.post("/comp")
def comp_candidate(
    body: CompIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    """Open the examined tier for someone without a payment."""
    product = _product(db, body.product_code)
    learner = db.execute(
        select(Learner).where(Learner.email == str(body.email).lower().strip())
    ).scalar_one_or_none()
    if learner is None:
        raise HTTPException(status_code=404, detail="No learner with that email.")
    ok, reason = adv.eligibility(db, learner, product)
    if not ok and "not offered" in reason:
        raise HTTPException(status_code=409, detail=reason)
    if not ok and "already" in reason:
        raise HTTPException(status_code=409, detail=reason)
    row = adv.create(
        db, learner, product, source="manual", order_id=None,
        amount_cents=0, currency=product.currency, send_welcome=body.send_email,
    )
    if body.note:
        row.outcome_note = body.note
        db.commit()
    return adv.admin_out(db, row)


class ScheduleIn(BaseModel):
    at: datetime
    meeting_url: str = Field(default="", max_length=500)


@router.post("/advanced/{row_id}/schedule")
def schedule(
    row_id: int, body: ScheduleIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    row, learner, product = _row(db, row_id)
    try:
        adv.schedule(db, learner, product, row, body.at, body.meeting_url)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return adv.admin_out(db, row)


class OutcomeIn(BaseModel):
    result: str  # 'pass' | 'retake' | 'fail'
    note: str = Field(default="", max_length=4000)
    retake_after: date | None = None


@router.post("/advanced/{row_id}/outcome")
def outcome(
    row_id: int, body: OutcomeIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    row, learner, product = _row(db, row_id)
    try:
        cert = adv.record_outcome(
            db, learner, product, row, body.result, body.note, body.retake_after
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = adv.admin_out(db, row)
    if cert is not None:
        out["certificate"] = _cert_admin_out(db, cert)
    return out


@router.post("/advanced/{row_id}/reopen")
def reopen(row_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    row, _learner, _product = _row(db, row_id)
    try:
        adv.reopen_scheduling(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return adv.admin_out(db, row)


@router.post("/advanced/{row_id}/reset-exam")
def reset_exam(row_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    row, _learner, _product = _row(db, row_id)
    try:
        adv.reset_exam(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return adv.admin_out(db, row)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/advanced/{row_id}/cancel")
def cancel(
    row_id: int, body: NoteIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    row, _learner, _product = _row(db, row_id)
    try:
        adv.cancel(db, row, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return adv.admin_out(db, row)


# -----------------------------------------------------------------------------
# Issued certificates
# -----------------------------------------------------------------------------

class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/certificates/{code}/revoke")
def revoke_certificate(
    code: str, body: RevokeIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    cert = certs.by_code(db, code)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    certs.revoke(db, cert, body.reason)
    return _cert_admin_out(db, cert)


class ReissueIn(BaseModel):
    learner_name: str | None = Field(default=None, max_length=120)
    resend_email: bool = True


@router.post("/certificates/{code}/reissue")
def reissue_certificate(
    code: str, body: ReissueIn, db: Session = Depends(get_db), _: str = Depends(require_admin)
) -> dict:
    """Name correction / un-revoke: same code, fresh signature and file."""
    cert = certs.by_code(db, code)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    learner = db.get(Learner, cert.learner_id)
    product = db.get(Product, cert.product_code)
    if learner is None or product is None:
        raise HTTPException(status_code=404, detail="Learner or product missing.")
    name = " ".join((body.learner_name or "").split()) or None
    try:
        certs.reissue(db, cert, learner_name=name)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if name:
        learner.full_name = name
        db.commit()
    if body.resend_email:
        certs.email_certificate(db, cert, learner, product)
    return _cert_admin_out(db, cert)
