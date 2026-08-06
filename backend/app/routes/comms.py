"""Admin comms — the outbound email log + academy-product broadcasts.

Endpoints (all admin-only):
  GET  /api/admin/comms/log              — newest-first EmailLog rows,
                                            optionally filtered by scope_code
  POST /api/admin/products/{code}/notify — broadcast to a product's active
                                            enrollees (audience 'buyers')

Course broadcasts live in routes/courses.py; this module covers everything
comms-related that isn't tied to a cohort.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..emailer import broadcast_html, send_broadcast
from ..models import EmailLog, Product
from ..schemas import NotifyOut
from ..stats_queries import active_enrollee_emails

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class ProductNotifyIn(BaseModel):
    """Same shape as a course notify, minus the audience — a product
    broadcast always targets its active buyers."""

    subject: str = Field(min_length=1, max_length=200)
    body_html: str = Field(min_length=1, max_length=100_000)


@router.get("/comms/log")
def comms_log(
    scope_code: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
) -> dict:
    """Newest-first outbound email log, optionally scoped to one code."""
    limit = max(1, min(limit, 1000))
    stmt = select(EmailLog)
    if scope_code:
        stmt = stmt.where(EmailLog.scope_code == scope_code)
    # id desc as tiebreak: batch sends share one timestamp second.
    stmt = stmt.order_by(EmailLog.ts.desc(), EmailLog.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return {
        "rows": [
            {
                "id": r.id,
                "ts": r.ts.isoformat() if r.ts else "",
                "scope_kind": r.scope_kind,
                "scope_code": r.scope_code,
                "audience": r.audience,
                "template": r.template,
                "subject": r.subject,
                "recipient": r.recipient,
                "ok": r.ok,
                "provider_id": r.provider_id,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/products/{code}/notify", response_model=NotifyOut)
def notify_product(
    code: str, body: ProductNotifyIn, db: Session = Depends(get_db)
) -> NotifyOut:
    """Broadcast to everyone holding live access to an academy product."""
    product = db.get(Product, code)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found."
        )
    recipients = active_enrollee_emails(db, code)
    html = broadcast_html(course_title=product.title, body_html=body.body_html)

    sent, failed = send_broadcast(
        db,
        recipients,
        subject=body.subject,
        html_builder=lambda _to: html,
        scope={
            "scope_kind": "product",
            "scope_code": code,
            "audience": "buyers",
            "template": "broadcast",
        },
    )

    return NotifyOut(
        ok=True,
        recipients=sent,
        failures=len(failed),
        failed_addresses=failed,
    )
