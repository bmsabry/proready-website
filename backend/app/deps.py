"""Shared FastAPI dependencies."""
from __future__ import annotations

import secrets

from fastapi import Cookie, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import get_settings

SESSION_COOKIE_NAME = "admin_session"


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    if not settings.SESSION_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin sessions disabled (SESSION_SECRET not configured).",
        )
    return URLSafeTimedSerializer(settings.SESSION_SECRET, salt="admin-session")


def make_session_token(email: str) -> str:
    """Sign a short JSON payload for the admin session cookie."""
    return _serializer().dumps({"email": email.lower().strip()})


def verify_session_token(token: str) -> str | None:
    """Return the email from a valid session cookie, or None."""
    settings = get_settings()
    try:
        data = _serializer().loads(token, max_age=settings.SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    email = data.get("email")
    if not isinstance(email, str):
        return None
    if email.lower() != settings.ADMIN_EMAIL.lower():
        return None
    return email


def require_admin(
    authorization: str = Header(default=""),
    admin_session: str = Cookie(default=""),
) -> str:
    """Guard admin endpoints. Accepts either:
      * a signed session cookie set by /api/admin/login (browser UI), OR
      * a bearer token matching ADMIN_TOKEN (curl / scripts).

    Returns the authenticated email so callers can audit-log if they want.
    """
    settings = get_settings()

    # Path 1: session cookie
    if admin_session:
        email = verify_session_token(admin_session)
        if email:
            return email

    # Path 2: bearer token escape hatch
    if settings.ADMIN_TOKEN:
        prefix = "Bearer "
        if authorization.startswith(prefix):
            token = authorization[len(prefix) :].strip()
            if secrets.compare_digest(token, settings.ADMIN_TOKEN):
                return settings.ADMIN_EMAIL

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Sign in at /admin or supply a bearer token.",
    )
