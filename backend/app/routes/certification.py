"""Learner + public routes for the two certification tiers.

  GET  /api/academy/certification/{code}            — my status for a course
  POST /api/academy/certificate/{code}              — claim (auto-issue check)
  POST /api/academy/profile/name                    — set the name printed
  GET  /api/academy/verify/{cert_code}              — PUBLIC verification
  GET  /api/academy/verify/{cert_code}/certificate.pdf
  GET  /api/academy/verify/{cert_code}/certificate.png
  POST /api/academy/advanced/{code}/checkout        — buy the examined tier
  GET  /api/academy/advanced/{code}/exam            — written exam items
  POST /api/academy/advanced/{code}/exam            — submit written exam
  POST /api/academy/advanced/{code}/slots           — propose interview windows

The certificate PDF/PNG are public on purpose: the certificate carries only
what the verify page already shows, and LinkedIn's crawler needs the image.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as svc
from .. import advanced_cert as adv
from .. import certificates as certs
from ..config import get_settings
from ..db import get_db
from ..learner_auth import require_learner
from ..models import Learner, Order, Product

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/academy", tags=["academy-certification"])

_PUBLIC_FILE_HEADERS = {
    # The file is public and immutable per code; let browsers and LinkedIn
    # cache it, but re-check daily in case of a re-issue.
    "Cache-Control": "public, max-age=86400",
    "X-Robots-Tag": "noindex",
}


def _product_or_404(db: Session, code: str) -> Product:
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    return product


def _public_item(item) -> dict:
    return {
        "code": item.code,
        "kind": item.kind,
        "stem": item.stem,
        "options": item.options or [],
        "cognitive_level": item.cognitive_level,
        "position": item.position,
        "section": item.position // 100,
        "rubric": item.rubric if item.kind == "short" else "",
    }


# -----------------------------------------------------------------------------
# Status + claim + name
# -----------------------------------------------------------------------------

def certification_payload(db: Session, learner: Learner, product: Product) -> dict:
    completion = certs.completion_status(db, learner, product.code)
    cert_c = certs.get_certificate(db, learner, product.code, "completion")
    cert_v = certs.get_certificate(db, learner, product.code, "verified")
    name = (learner.full_name or "").strip()
    return {
        "full_name": name,
        # Once anything has been issued the printed name is fixed; changes go
        # through support (admin re-issue).
        "name_locked": bool(cert_c or cert_v),
        "completion": {
            **completion,
            "certificate": certs.certificate_out(db, cert_c, product) if cert_c else None,
            "awaiting_name": completion["complete"] and cert_c is None and not name,
        },
        "advanced": {
            **adv.learner_out(db, learner, product, adv.current(db, learner, product.code)),
            "certificate": certs.certificate_out(db, cert_v, product) if cert_v else None,
        },
    }


@router.get("/certification/{code}")
def certification_status(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    product = _product_or_404(db, code)
    if not svc.has_any_access(db, learner, code):
        raise HTTPException(status_code=403, detail="You don't have access to this course.")
    # Auto-issue is also attempted here so a learner who finished before this
    # feature shipped receives their certificate the next time they look.
    certs.maybe_issue_completion(db, learner, code)
    return certification_payload(db, learner, product)


@router.post("/certificate/{code}")
def claim_certificate(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    product = _product_or_404(db, code)
    if not svc.has_access(db, learner, code):
        raise HTTPException(status_code=403, detail="You don't have access to this course.")
    cert = certs.maybe_issue_completion(db, learner, code)
    if cert is None:
        if not certs.completion_status(db, learner, code)["complete"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Finish every lesson and pass every module evaluation and mastery check to earn the certificate.",
            )
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Add the full name to print on the certificate first.",
        )
    return certs.certificate_out(db, cert, product)


class NameIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)


@router.post("/profile/name")
def set_name(
    body: NameIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    name = " ".join(body.full_name.split())
    if len(name) < 2 or not any(ch.isalpha() for ch in name):
        raise HTTPException(status_code=422, detail="Enter your full name as it should appear.")
    issued = db.execute(
        select(certs.Certificate).where(certs.Certificate.learner_id == learner.id)
    ).first()
    if issued is not None:
        raise HTTPException(
            status_code=409,
            detail="A certificate has already been issued in your name. Contact "
            "info@proreadyengineer.com to correct it.",
        )
    learner.full_name = name
    db.commit()
    # A learner who finished before naming themselves gets the certificate now.
    issued_codes = []
    for (product_code,) in db.execute(select(Product.code)).all():
        if svc.has_access(db, learner, product_code):
            cert = certs.maybe_issue_completion(db, learner, product_code)
            if cert is not None:
                issued_codes.append(cert.code)
    return {"ok": True, "full_name": name, "issued": issued_codes}


# -----------------------------------------------------------------------------
# Public verification
# -----------------------------------------------------------------------------

@router.get("/verify/{cert_code}")
def verify_certificate(cert_code: str, db: Session = Depends(get_db)) -> dict:
    """Public. Returns holder, course, tier, dates and integrity checks."""
    cert = certs.by_code(db, cert_code)
    if cert is None:
        return {"valid": False, "code": cert_code.upper().strip()}
    return certs.verify_out(db, cert)


@router.get("/verify/{cert_code}/certificate.pdf")
def certificate_pdf(cert_code: str, db: Session = Depends(get_db)) -> Response:
    cert = certs.by_code(db, cert_code)
    if cert is None:
        raise HTTPException(status_code=404, detail="No such certificate.")
    if cert.status != "issued":
        raise HTTPException(status_code=410, detail="This certificate has been revoked.")
    data = certs.blob_bytes(db, cert.pdf_key)
    if data is None:
        raise HTTPException(status_code=404, detail="Certificate file not available.")
    title = certs.TIER_TITLES.get(cert.tier, "Certificate").replace(" ", "_")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            **_PUBLIC_FILE_HEADERS,
            "Content-Disposition": f'inline; filename="ProReadyEngineer_{title}_{cert.code}.pdf"',
        },
    )


@router.get("/verify/{cert_code}/certificate.png")
def certificate_png(cert_code: str, db: Session = Depends(get_db)) -> Response:
    cert = certs.by_code(db, cert_code)
    if cert is None or cert.status != "issued":
        raise HTTPException(status_code=404, detail="No such certificate.")
    data = certs.blob_bytes(db, cert.preview_key)
    if data is None:
        raise HTTPException(status_code=404, detail="Preview not available.")
    return Response(content=data, media_type="image/png", headers=_PUBLIC_FILE_HEADERS)


# -----------------------------------------------------------------------------
# Examined tier — purchase
# -----------------------------------------------------------------------------

@router.post("/advanced/{code}/checkout")
def advanced_checkout(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    from .checkout import _stripe  # noqa: PLC0415 — lazy SDK import lives there

    settings = get_settings()
    product = _product_or_404(db, code)
    ok, reason = adv.eligibility(db, learner, product)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    if product.advanced_cert_price_cents <= 0:
        raise HTTPException(status_code=409, detail="No price is set for the examined tier.")
    stripe = _stripe()
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": product.currency,
                        "unit_amount": product.advanced_cert_price_cents,
                        "product_data": {
                            "name": f"Instructor-examined certification — {product.title}",
                            "description": (
                                "Advanced written examination + 60-minute live oral "
                                "examination with the instructor; signed Certificate "
                                "of Verified Competency on a pass."
                            )[:300],
                        },
                    },
                }
            ],
            customer_email=learner.email,
            success_url=f"{settings.SITE_URL}/learn/{product.code}?advanced=paid",
            cancel_url=f"{settings.SITE_URL}/learn/{product.code}",
            client_reference_id=product.code,
            metadata={
                "kind": "advanced_cert",
                "product_code": product.code,
                "learner_id": str(learner.id),
            },
            billing_address_collection="auto",
            allow_promotion_codes=True,
        )
    except Exception as exc:
        log.error("Stripe Checkout (advanced cert) failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout. Please try again.",
        ) from exc

    db.add(
        Order(
            learner_id=learner.id,
            product_code=product.code,
            email=learner.email,
            provider="stripe",
            kind="advanced_cert",
            provider_ref=session.id,
            amount_cents=product.advanced_cert_price_cents,
            currency=product.currency,
            status="pending",
        )
    )
    db.commit()
    return {"url": session.url, "session_id": session.id}


# -----------------------------------------------------------------------------
# Examined tier — written examination
# -----------------------------------------------------------------------------

def _advanced_row(db: Session, learner: Learner, code: str):
    row = adv.current(db, learner, code)
    if row is None:
        raise HTTPException(status_code=404, detail="No examination in progress.")
    return row


@router.get("/advanced/{code}/exam")
def advanced_exam(
    code: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    product = _product_or_404(db, code)
    row = _advanced_row(db, learner, code)
    if not adv.exam_open(row):
        raise HTTPException(
            status_code=409,
            detail="The written examination is not open at this step."
            if row.status != "exam_failed"
            else "The written examination attempts are used up. Contact info@proreadyengineer.com.",
        )
    settings = get_settings()
    items = adv.exam_items(db, code)
    return {
        "product": {"code": product.code, "title": product.title},
        "item_set": "advanced",
        "threshold": settings.ADVANCED_EXAM_THRESHOLD_PCT,
        "attempts_used": row.exam_attempts,
        "attempts_max": settings.ADVANCED_EXAM_MAX_ATTEMPTS,
        "items": [_public_item(i) for i in items],
    }


class SubmitIn(BaseModel):
    responses: dict


@router.post("/advanced/{code}/exam")
def submit_advanced_exam(
    code: str,
    body: SubmitIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    product = _product_or_404(db, code)
    row = _advanced_row(db, learner, code)
    if not adv.exam_open(row):
        raise HTTPException(status_code=409, detail="The written examination is not open at this step.")
    attempt = adv.grade_exam(db, learner, product, row, body.responses or {})
    items = {i.code: i for i in adv.exam_items(db, code)}
    settings = get_settings()
    return {
        "score_pct": attempt.score_pct,
        "passed": attempt.passed,
        "auto_correct": attempt.auto_correct,
        "auto_total": attempt.auto_total,
        "threshold": settings.ADVANCED_EXAM_THRESHOLD_PCT,
        "attempts_used": row.exam_attempts,
        "attempts_max": settings.ADVANCED_EXAM_MAX_ATTEMPTS,
        "status": row.status,
        # Explanations are withheld on the examined tier: the bank must stay
        # examinable for the second attempt and the oral examination.
        "feedback": [
            {"code": c, "correct": d.get("correct"), "needs_review": d.get("correct") is None}
            for c, d in attempt.responses.items()
            if c in items
        ],
    }


# -----------------------------------------------------------------------------
# Examined tier — interview windows
# -----------------------------------------------------------------------------

class SlotsIn(BaseModel):
    slots: list[datetime] = Field(min_length=1, max_length=5)
    timezone: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=1000)


@router.post("/advanced/{code}/slots")
def propose_slots(
    code: str,
    body: SlotsIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(require_learner),
) -> dict:
    product = _product_or_404(db, code)
    row = _advanced_row(db, learner, code)
    ok, why = adv.can_propose(row)
    if not ok:
        raise HTTPException(status_code=409, detail=why)
    try:
        adv.propose_slots(db, learner, product, row, body.slots, body.timezone, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return certification_payload(db, learner, product)["advanced"]
