"""Admin → Website Traffic.

  GET /api/admin/traffic?days=30&include_admin=false

Visits and page views on proreadyengineer.com from Cloudflare Web Analytics;
see app/traffic.py. Read-only and admin-only. Uses no database, so it never
holds a pooled connection while Cloudflare answers.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import traffic
from ..deps import require_admin

router = APIRouter(prefix="/api/admin/traffic", tags=["admin-traffic"])


@router.get("")
def traffic_report(
    days: int = 30,
    include_admin: bool = False,
    refresh: bool = False,
    _: str = Depends(require_admin),
) -> dict:
    if refresh:
        traffic.clear_cache()
    return traffic.report(days, include_admin)
