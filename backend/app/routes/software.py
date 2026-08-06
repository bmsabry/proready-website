"""Software registry — public product list + admin CRUD.

The registry (software_products table) is the source of truth for which
download/telemetry slugs are valid (see valid_product in routes/downloads.py)
and drives:

Public:
  GET   /api/products/software        — live products for the Products page

Admin (protected):
  GET   /api/admin/software           — all products incl. hidden, with counts
  POST  /api/admin/software           — create
  PATCH /api/admin/software/{slug}    — update any field

There is deliberately no DELETE: telemetry rows reference products by slug,
so removing one would orphan its history. Hide it instead (status='hidden').
"""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import AppLaunch, AppUsage, ProductDownload, SoftwareProduct

public_router = APIRouter(prefix="/api/products", tags=["public"])

admin_router = APIRouter(
    prefix="/api/admin/software",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class SoftwareCreateIn(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    blurb: str = Field(default="", max_length=10_000)
    asset_path: str = Field(default="", max_length=300)
    latest_version: str = Field(default="", max_length=24)
    status: Literal["live", "hidden"] = "live"


class SoftwarePatchIn(BaseModel):
    """All fields optional — only supplied ones are updated."""

    slug: Optional[str] = Field(
        default=None, min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    blurb: Optional[str] = Field(default=None, max_length=10_000)
    asset_path: Optional[str] = Field(default=None, max_length=300)
    latest_version: Optional[str] = Field(default=None, max_length=24)
    status: Optional[Literal["live", "hidden"]] = None


def _count_by_product(db: Session, model) -> dict[str, int]:
    """{slug: row count} for one telemetry table, in a single query."""
    return {
        slug: int(n)
        for slug, n in db.execute(
            select(model.product, func.count(model.id)).group_by(model.product)
        ).all()
    }


def _get_or_404(db: Session, slug: str) -> SoftwareProduct:
    product = db.execute(
        select(SoftwareProduct).where(SoftwareProduct.slug == slug)
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Software product not found."
        )
    return product


def _admin_row(product: SoftwareProduct, downloads: int, launches: int, usage: int) -> dict:
    return {
        "slug": product.slug,
        "name": product.name,
        "blurb": product.blurb,
        "asset_path": product.asset_path,
        "latest_version": product.latest_version,
        "status": product.status,
        "created_at": product.created_at.isoformat() if product.created_at else "",
        "downloads": downloads,
        "launches": launches,
        "usage_pings": usage,
    }


# ----- Public ----------------------------------------------------------------

@public_router.get("/software")
def list_software_public(db: Session = Depends(get_db)) -> List[dict]:
    """Live products only, with the public download counter per product."""
    products = db.execute(
        select(SoftwareProduct)
        .where(SoftwareProduct.status == "live")
        .order_by(SoftwareProduct.created_at.asc(), SoftwareProduct.id.asc())
    ).scalars().all()
    downloads = _count_by_product(db, ProductDownload)
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "blurb": p.blurb,
            "latest_version": p.latest_version,
            "download_count": downloads.get(p.slug, 0),
            # The Pages download function (/download/{slug}) resolves slugs to
            # assets from this list. Asset paths are public by design — the
            # function's fail-open path redirects straight to them.
            "asset_path": p.asset_path,
        }
        for p in products
    ]


# ----- Admin CRUD ------------------------------------------------------------

@admin_router.get("")
def list_software_admin(db: Session = Depends(get_db)) -> List[dict]:
    """Every product (hidden included) with per-table telemetry counts."""
    products = db.execute(
        select(SoftwareProduct).order_by(
            SoftwareProduct.created_at.asc(), SoftwareProduct.id.asc()
        )
    ).scalars().all()
    downloads = _count_by_product(db, ProductDownload)
    launches = _count_by_product(db, AppLaunch)
    usage = _count_by_product(db, AppUsage)
    return [
        _admin_row(
            p,
            downloads.get(p.slug, 0),
            launches.get(p.slug, 0),
            usage.get(p.slug, 0),
        )
        for p in products
    ]


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def create_software(body: SoftwareCreateIn, db: Session = Depends(get_db)) -> dict:
    existing = db.execute(
        select(SoftwareProduct).where(SoftwareProduct.slug == body.slug)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Software slug '{body.slug}' already exists.",
        )
    product = SoftwareProduct(
        slug=body.slug,
        name=body.name,
        blurb=body.blurb,
        asset_path=body.asset_path,
        latest_version=body.latest_version,
        status=body.status,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _admin_row(product, 0, 0, 0)


@admin_router.patch("/{slug}")
def patch_software(
    slug: str, body: SoftwarePatchIn, db: Session = Depends(get_db)
) -> dict:
    product = _get_or_404(db, slug)

    if body.slug is not None and body.slug != product.slug:
        # Renaming a slug orphans existing telemetry rows (they keep the old
        # slug) — allowed, but guarded against collisions.
        clash = db.execute(
            select(SoftwareProduct).where(SoftwareProduct.slug == body.slug)
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Software slug '{body.slug}' already exists.",
            )

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)

    downloads = _count_by_product(db, ProductDownload)
    launches = _count_by_product(db, AppLaunch)
    usage = _count_by_product(db, AppUsage)
    return _admin_row(
        product,
        downloads.get(product.slug, 0),
        launches.get(product.slug, 0),
        usage.get(product.slug, 0),
    )
