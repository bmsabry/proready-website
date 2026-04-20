"""Shared FastAPI dependencies."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_admin(authorization: str = Header(default="")) -> None:
    """Guard admin endpoints with a simple bearer token.

    Expected header: `Authorization: Bearer <ADMIN_TOKEN>`
    Uses constant-time comparison. If ADMIN_TOKEN is unset, denies everything.
    """
    settings = get_settings()
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints disabled (ADMIN_TOKEN not configured).",
        )

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
        )
    token = authorization[len(prefix) :].strip()
    if not secrets.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )
