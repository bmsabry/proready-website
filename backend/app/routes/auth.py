"""Admin login/logout/me endpoints.

Email+password authentication for the single admin (Bassam). The
email must match settings.ADMIN_EMAIL (case-insensitive). The password
is verified against a bcrypt hash stored in settings.ADMIN_PASSWORD_HASH.

On success we set an httpOnly, Secure, SameSite=None cookie so the
separate-origin frontend (proreadyengineer.com) can include it in
credentialed fetch() calls to the API on onrender.com.

To rotate the admin password: generate a new bcrypt hash and update the
ADMIN_PASSWORD_HASH env var on Render. No in-app rotation UI — intentional.
"""
from __future__ import annotations

import logging
import secrets as _secrets

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import get_settings
from ..deps import SESSION_COOKIE_NAME, make_session_token, require_admin
from ..schemas import LoginIn, MeOut, OkOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])


def _verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _set_session_cookie(response: Response, email: str) -> None:
    settings = get_settings()
    token = make_session_token(email)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,          # required with SameSite=None
        samesite="none",      # cross-site cookie: frontend=.com, api=onrender.com
        path="/",
    )


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, response: Response) -> MeOut:
    settings = get_settings()

    if not settings.ADMIN_PASSWORD_HASH or not settings.SESSION_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin login is not configured on this server.",
        )

    email_norm = body.email.lower().strip()
    admin_email_norm = settings.ADMIN_EMAIL.lower().strip()

    # Always hash even if email is wrong, to keep timing roughly flat.
    password_ok = _verify_password(body.password, settings.ADMIN_PASSWORD_HASH)
    email_ok = _secrets.compare_digest(email_norm, admin_email_norm)

    if not (email_ok and password_ok):
        log.warning("Admin login failed for email=%r", email_norm)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    _set_session_cookie(response, email_norm)
    log.info("Admin login OK for %s", email_norm)
    return MeOut(email=email_norm)


@router.post("/logout", response_model=OkOut)
def logout(response: Response) -> OkOut:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    return OkOut()


@router.get("/me", response_model=MeOut)
def me(email: str = Depends(require_admin)) -> MeOut:
    return MeOut(email=email)
