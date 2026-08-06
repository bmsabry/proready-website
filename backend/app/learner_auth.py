"""Passwordless (magic-link) authentication for academy learners.

Deliberately separate from the admin auth in `deps.py`:

  * different cookie name  — `learner_session` vs `admin_session`
  * different signing salt — a token minted for one is invalid for the other
  * different secret       — LEARNER_SESSION_SECRET vs SESSION_SECRET

so a stolen or forged learner cookie can never be replayed against an admin
endpoint, and rotating one secret does not sign the other's users out.

Flow:
  1. POST /api/academy/auth/request-link  → mint raw token, store only its
     SHA-256 hash, email the link.
  2. GET/POST /api/academy/auth/verify    → hash the presented token, look it
     up, check unused + unexpired, mark used, set the session cookie.

Tokens are single-use. The cookie is the long-lived credential; the link is
a one-shot bearer of it.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Learner, LoginToken

LEARNER_COOKIE_NAME = "learner_session"
_SALT = "learner-session-v1"


# -----------------------------------------------------------------------------
# Session cookie
# -----------------------------------------------------------------------------

def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    secret = settings.LEARNER_SESSION_SECRET
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learner sign-in is not configured on this server.",
        )
    return URLSafeTimedSerializer(secret, salt=_SALT)


def make_learner_token(learner_id: int, email: str) -> str:
    return _serializer().dumps({"id": learner_id, "email": email.lower().strip()})


def verify_learner_token(token: str) -> int | None:
    """Return the learner id from a valid cookie, else None."""
    settings = get_settings()
    try:
        data = _serializer().loads(
            token, max_age=settings.LEARNER_SESSION_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    learner_id = data.get("id")
    return learner_id if isinstance(learner_id, int) else None


def set_learner_cookie(response: Response, learner: Learner) -> None:
    """Attach the session cookie.

    SameSite=None + Secure because the SPA is on proreadyengineer.com while
    the API is on onrender.com — a cross-site pair. Same constraint the admin
    cookie already lives under.
    """
    settings = get_settings()
    response.set_cookie(
        key=LEARNER_COOKIE_NAME,
        value=make_learner_token(learner.id, learner.email),
        max_age=settings.LEARNER_SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


def clear_learner_cookie(response: Response) -> None:
    response.set_cookie(
        key=LEARNER_COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


# -----------------------------------------------------------------------------
# Magic-link tokens
# -----------------------------------------------------------------------------

def hash_login_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_login_token(
    db: Session, learner: Learner, *, next_path: str = "/learn"
) -> str:
    """Mint a single-use sign-in token and persist only its hash.

    Returns the raw token — the ONLY moment it exists in plaintext. Callers
    must put it straight into an email and then drop it.
    """
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    row = LoginToken(
        learner_id=learner.id,
        token_hash=hash_login_token(raw),
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.LOGIN_LINK_TTL_SECONDS),
        next_path=next_path or "/learn",
    )
    db.add(row)
    db.commit()
    return raw


def consume_login_token(db: Session, raw: str) -> tuple[Learner, str] | None:
    """Exchange a raw token for its learner. Returns (learner, next_path).

    Returns None for anything that isn't a live, unused, unexpired token, or
    whose learner is blocked. Callers must not distinguish these cases to the
    client — one generic failure keeps the endpoint from confirming which
    emails exist.
    """
    row = db.execute(
        select(LoginToken).where(LoginToken.token_hash == hash_login_token(raw))
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        return None

    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None

    learner = db.get(Learner, row.learner_id)
    if learner is None or learner.status != "active":
        return None

    row.used_at = datetime.now(timezone.utc)
    learner.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return learner, row.next_path


def recent_link_count(db: Session, learner_id: int, *, within_seconds: int = 3600) -> int:
    """How many links this learner has been sent recently — the rate limit."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
    rows = db.execute(
        select(LoginToken.id).where(
            LoginToken.learner_id == learner_id, LoginToken.created_at >= cutoff
        )
    ).all()
    return len(rows)


# -----------------------------------------------------------------------------
# FastAPI dependencies
# -----------------------------------------------------------------------------

def optional_learner(
    learner_session: str = Cookie(default=""),
    db: Session = Depends(get_db),
) -> Learner | None:
    """Resolve the signed-in learner, or None. Never raises.

    Used by endpoints that serve both anonymous visitors (preview lessons,
    catalog) and signed-in learners.
    """
    if not learner_session:
        return None
    settings = get_settings()
    if not settings.LEARNER_SESSION_SECRET:
        return None
    learner_id = verify_learner_token(learner_session)
    if learner_id is None:
        return None
    learner = db.get(Learner, learner_id)
    if learner is None or learner.status != "active":
        return None
    return learner


def require_learner(
    learner: Learner | None = Depends(optional_learner),
) -> Learner:
    """Guard learner-only endpoints."""
    if learner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
        )
    return learner
