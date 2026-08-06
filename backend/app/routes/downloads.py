"""Product download tracking + statistics.

POST /api/track/download        — called by the Cloudflare Pages Function that
                                  serves each product file; one row per download.
GET  /api/downloads/stats       — public aggregates (counts only, no UA/referrer
                                  detail) so the Products page can show a live
                                  download counter.
GET  /api/admin/downloads       — full detail for the admin dashboard: daily
                                  series, countries, referrers, recent rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as tz

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import ProductDownload

router = APIRouter(prefix="/api", tags=["downloads"])

# Whitelist keeps junk products out of the table; extend as products ship.
KNOWN_PRODUCTS = {"pro3dworks"}


class DownloadEvent(BaseModel):
    product: str = Field(min_length=1, max_length=64)
    country: str = Field(default="", max_length=8)
    region: str = Field(default="", max_length=128)
    city: str = Field(default="", max_length=128)
    timezone: str = Field(default="", max_length=64)
    colo: str = Field(default="", max_length=8)
    referrer: str = Field(default="", max_length=1024)
    user_agent: str = Field(default="", max_length=1024)


@router.post("/track/download")
def track_download(event: DownloadEvent, db: Session = Depends(get_db)) -> dict:
    product = event.product.strip().lower()
    if product not in KNOWN_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown product."
        )
    row = ProductDownload(
        product=product,
        country=event.country.strip().upper()[:8],
        region=event.region.strip()[:128],
        city=event.city.strip()[:128],
        timezone=event.timezone.strip()[:64],
        colo=event.colo.strip().upper()[:8],
        referrer=event.referrer.strip()[:1024],
        user_agent=event.user_agent.strip()[:1024],
    )
    db.add(row)
    db.commit()
    return {"ok": True}


def _since(days: int) -> datetime:
    return datetime.now(tz.utc) - timedelta(days=days)


@router.get("/downloads/stats")
def public_stats(product: str = "pro3dworks", db: Session = Depends(get_db)) -> dict:
    """Aggregate counts only — safe for the public Products page."""
    product = product.strip().lower()
    if product not in KNOWN_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown product."
        )
    base = select(func.count(ProductDownload.id)).where(
        ProductDownload.product == product
    )
    total = db.execute(base).scalar() or 0
    last7 = db.execute(base.where(ProductDownload.ts >= _since(7))).scalar() or 0
    last30 = db.execute(base.where(ProductDownload.ts >= _since(30))).scalar() or 0
    countries = db.execute(
        select(ProductDownload.country, func.count(ProductDownload.id))
        .where(ProductDownload.product == product, ProductDownload.country != "")
        .group_by(ProductDownload.country)
        .order_by(func.count(ProductDownload.id).desc())
        .limit(10)
    ).all()
    return {
        "product": product,
        "total": int(total),
        "last7": int(last7),
        "last30": int(last30),
        "top_countries": [{"country": c, "count": int(n)} for c, n in countries],
    }


@router.get("/admin/downloads")
def admin_stats(
    product: str = "pro3dworks",
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    product = product.strip().lower()
    if product not in KNOWN_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown product."
        )
    base = select(func.count(ProductDownload.id)).where(
        ProductDownload.product == product
    )
    total = db.execute(base).scalar() or 0
    last7 = db.execute(base.where(ProductDownload.ts >= _since(7))).scalar() or 0
    last30 = db.execute(base.where(ProductDownload.ts >= _since(30))).scalar() or 0

    day = func.date(ProductDownload.ts)
    by_day = db.execute(
        select(day, func.count(ProductDownload.id))
        .where(ProductDownload.product == product, ProductDownload.ts >= _since(30))
        .group_by(day)
        .order_by(day)
    ).all()
    by_country = db.execute(
        select(ProductDownload.country, func.count(ProductDownload.id))
        .where(ProductDownload.product == product)
        .group_by(ProductDownload.country)
        .order_by(func.count(ProductDownload.id).desc())
        .limit(25)
    ).all()
    by_referrer = db.execute(
        select(ProductDownload.referrer, func.count(ProductDownload.id))
        .where(ProductDownload.product == product, ProductDownload.referrer != "")
        .group_by(ProductDownload.referrer)
        .order_by(func.count(ProductDownload.id).desc())
        .limit(25)
    ).all()
    recent = db.execute(
        select(ProductDownload)
        .where(ProductDownload.product == product)
        .order_by(ProductDownload.ts.desc())
        .limit(100)
    ).scalars().all()

    return {
        "product": product,
        "total": int(total),
        "last7": int(last7),
        "last30": int(last30),
        "by_day": [{"date": str(d), "count": int(n)} for d, n in by_day],
        "by_country": [
            {"country": c or "(unknown)", "count": int(n)} for c, n in by_country
        ],
        "by_referrer": [{"referrer": r, "count": int(n)} for r, n in by_referrer],
        "recent": [
            {
                "ts": r.ts.isoformat() if r.ts else "",
                "country": r.country,
                "region": r.region,
                "city": r.city,
                "timezone": r.timezone,
                "referrer": r.referrer,
                "user_agent": r.user_agent[:160],
            }
            for r in recent
        ],
    }


# ---------------------------------------------------------------------------
# App launches — the in-app update check doubles as an anonymous launch
# signal (app version + city-level geo only; same policy as downloads).
# ---------------------------------------------------------------------------

class LaunchEvent(BaseModel):
    product: str = Field(min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=24)
    country: str | None = Field(default=None, max_length=8)
    region: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)


@router.post("/track/launch")
def track_launch(event: LaunchEvent, db: Session = Depends(get_db)) -> dict:
    from ..models import AppLaunch

    product = event.product.strip().lower()
    if product not in KNOWN_PRODUCTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unknown product")
    db.add(AppLaunch(
        product=product,
        version=(event.version or "").strip()[:24],
        country=(event.country or "").strip()[:8],
        region=(event.region or "").strip()[:128],
        city=(event.city or "").strip()[:128],
    ))
    db.commit()
    return {"ok": True}


@router.get("/launches/stats")
def launch_stats(product: str = "pro3dworks", db: Session = Depends(get_db)) -> dict:
    """Public aggregate launch statistics — no personal data, mirrors /downloads/stats."""
    from ..models import AppLaunch

    product = product.strip().lower()
    total = db.scalar(select(func.count()).select_from(AppLaunch).where(AppLaunch.product == product)) or 0
    week_ago = datetime.now(tz.utc) - timedelta(days=7)
    last7 = db.scalar(
        select(func.count()).select_from(AppLaunch)
        .where(AppLaunch.product == product, AppLaunch.ts >= week_ago)) or 0
    by_version = [
        {"version": v or "unknown", "count": c}
        for v, c in db.execute(
            select(AppLaunch.version, func.count()).where(AppLaunch.product == product)
            .group_by(AppLaunch.version).order_by(func.count().desc()).limit(8)).all()
    ]
    top_countries = [
        {"country": co or "unknown", "count": c}
        for co, c in db.execute(
            select(AppLaunch.country, func.count()).where(AppLaunch.product == product)
            .group_by(AppLaunch.country).order_by(func.count().desc()).limit(8)).all()
    ]
    return {"product": product, "total": total, "last7": last7,
            "by_version": by_version, "top_countries": top_countries}
