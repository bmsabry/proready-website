"""Compatibility API for the five standalone quiz apps.

The `smallgasturbine.gt-05 / 06 / 07 / 13 / 15` Cloudflare Workers were built
against the combustion-toolkit API and speak an email+password JWT contract:

    POST /auth/signup            -> {access_token, refresh_token, token_type, expires_in}
    POST /auth/login             -> same
    POST /auth/refresh           -> same
    GET  /auth/me                -> {id, email, full_name, is_verified, is_admin, created_at}
    GET  /learning/{mid}/access  -> {enrolled, has_pending_invitation, has_pending_request, is_admin}
    GET  /learning/{mid}/progress-> {payload, updated_at}
    PUT  /learning/{mid}/progress-> same
    GET  /learning/my-modules    -> [{module_id, title, subtitle, url_base, enrolled, ...}]
    POST /learning/{mid}/request-access

This module reimplements that contract byte-for-byte against academy tables so
those apps can be repointed here and the combustion-toolkit service can stay
switched off permanently. Nothing here imports from, or depends on, that
service.

The important behavioural change: **entitlement now comes from the academy
enrolment**, so a single purchase of the course opens all five apps at once.
The old per-module grant + auto-grant cascade is gone; there is one product.

Progress payloads stay opaque. The apps own that shape, we store and return it
verbatim, and the platform's own server-graded assessments live separately in
`academy_quiz_attempts`. Grading inside these apps remains client-side — that
is a property of the apps, not something this layer can fix; the platform's
own quiz engine is the trustworthy one.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as svc
from ..config import get_settings
from ..db import get_db
from ..models import Learner, ModuleState

log = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["compat-auth"])
learning_router = APIRouter(prefix="/learning", tags=["compat-learning"])

# Legacy module ids, in the shape the apps send them, with the metadata the
# directory view renders. Kept here rather than read from academy_modules
# because these are the *apps*, not the platform's own module rows — the two
# can diverge (GT-03 and GT-12 have no app) without breaking either.
MODULES: dict[str, dict] = {
    "gt-05": {
        "title": "GT-05 — Centrifugal Compressor",
        "subtitle": "Aerodynamics, Design & Performance Map",
        "url_base": "https://smallgasturbine.gt-05.proreadyengineer.com",
    },
    "gt-06": {
        "title": "GT-06 — Evaporative Tube Combustor",
        "subtitle": "Design Principles & Fuel Delivery",
        "url_base": "https://smallgasturbine.gt-06.proreadyengineer.com",
    },
    "gt-07": {
        "title": "GT-07 — Axial Turbine",
        "subtitle": "Aerodynamics, Blade Loading & Structural Integrity",
        "url_base": "https://smallgasturbine.gt-07.proreadyengineer.com",
    },
    "gt-13": {
        "title": "GT-13 — CFD Fundamentals",
        "subtitle": "Application to Turbomachinery Components",
        "url_base": "https://smallgasturbine.gt-13.proreadyengineer.com",
    },
    "gt-15": {
        "title": "GT-15 — Combustor Performance Analysis",
        "subtitle": "HRR, Pattern Factor & Start Fuel Scheduling",
        "url_base": "https://smallgasturbine.gt-15.proreadyengineer.com",
    },
}


# -----------------------------------------------------------------------------
# Schemas — field names and defaults must match the old API exactly
# -----------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str | None
    is_verified: bool
    is_admin: bool = False
    created_at: datetime


class AccessOut(BaseModel):
    enrolled: bool
    has_pending_invitation: bool = False
    has_pending_request: bool = False
    is_admin: bool = False


class ProgressIn(BaseModel):
    payload: dict


class ProgressOut(BaseModel):
    payload: dict
    updated_at: datetime | None = None


class ModuleAccessOut(BaseModel):
    module_id: str
    title: str
    subtitle: str
    url_base: str
    enrolled: bool
    granted_at: datetime | None = None
    last_active_at: datetime | None = None
    progress_summary: dict = {}
    via_admin: bool = False


# -----------------------------------------------------------------------------
# Passwords + JWT
# -----------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify against a bcrypt hash — including hashes migrated over verbatim."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret() -> str:
    settings = get_settings()
    # Fall back to the learner-session secret so a deploy that forgets
    # COMPAT_JWT_SECRET still works rather than handing out unsigned tokens.
    secret = settings.COMPAT_JWT_SECRET or settings.LEARNER_SESSION_SECRET
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is not configured on this server.",
        )
    return secret


def _encode(payload: dict) -> str:
    """Minimal HS256 JWT. Hand-rolled to avoid pulling in a JOSE dependency."""
    header = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"},
                              separators=(",", ":")).encode())
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}"
    sig = hmac.new(_secret().encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64u(sig)}"


def decode_token(token: str) -> dict | None:
    """Verify signature and expiry. Returns the claims, or None."""
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        return None
    expected = hmac.new(
        _secret().encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
    ).digest()
    try:
        if not hmac.compare_digest(expected, _b64u_decode(sig_b64)):
            return None
        claims = json.loads(_b64u_decode(body_b64))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(timezone.utc).timestamp()):
        return None
    return claims


def _token_response(learner: Learner) -> TokenResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    sub = str(learner.id)
    access = _encode({
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.COMPAT_ACCESS_TOKEN_MINUTES)).timestamp()),
        "type": "access",
    })
    refresh = _encode({
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.COMPAT_REFRESH_TOKEN_DAYS)).timestamp()),
        "type": "refresh",
    })
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.COMPAT_ACCESS_TOKEN_MINUTES * 60,
    )


def current_learner(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Learner:
    """Resolve the Bearer access token the quiz apps send on every call."""
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    claims = decode_token(authorization[len(prefix):].strip())
    if not claims or claims.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    try:
        learner = db.get(Learner, int(claims["sub"]))
    except (KeyError, TypeError, ValueError):
        learner = None
    if learner is None or learner.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return learner


def _user_out(learner: Learner) -> UserOut:
    return UserOut(
        id=str(learner.id),
        email=learner.email,
        full_name=learner.full_name or None,
        # Owning an account here means the email was reachable, either via a
        # magic link or an invitation, so there is no separate verify step.
        is_verified=True,
        is_admin=bool(learner.is_staff),
        created_at=learner.created_at,
    )


# -----------------------------------------------------------------------------
# Auth endpoints
# -----------------------------------------------------------------------------

@auth_router.post("/signup", response_model=TokenResponse,
                  status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Create an account, or claim one that exists without a password.

    A buyer provisioned by Stripe already has a Learner row with no password.
    Letting them "sign up" sets a password on that same row instead of
    colliding — otherwise the person who just paid cannot get into the quiz
    apps without a support email.
    """
    email = body.email.lower().strip()
    learner = db.execute(
        select(Learner).where(Learner.email == email)
    ).scalar_one_or_none()

    if learner is not None and learner.password_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    if learner is None:
        learner = Learner(email=email, full_name=(body.full_name or "").strip())
        db.add(learner)
    elif body.full_name and not learner.full_name:
        learner.full_name = body.full_name.strip()

    learner.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(learner)
    svc.promote_if_owner(db, learner)
    return _token_response(learner)


@auth_router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    learner = db.execute(
        select(Learner).where(Learner.email == body.email.lower().strip())
    ).scalar_one_or_none()
    if learner is None or not verify_password(body.password, learner.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    if learner.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    learner.last_login_at = datetime.now(timezone.utc)
    db.commit()
    svc.promote_if_owner(db, learner)
    return _token_response(learner)


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    claims = decode_token(body.refresh_token)
    if not claims or claims.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    try:
        learner = db.get(Learner, int(claims["sub"]))
    except (KeyError, TypeError, ValueError):
        learner = None
    if learner is None or learner.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return _token_response(learner)


@auth_router.get("/me", response_model=UserOut)
def me(learner: Learner = Depends(current_learner)) -> UserOut:
    return _user_out(learner)


# -----------------------------------------------------------------------------
# Learning endpoints
# -----------------------------------------------------------------------------

def _known_module(module_id: str) -> dict:
    info = MODULES.get(module_id.lower())
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown module")
    return info


def _entitled(db: Session, learner: Learner) -> bool:
    """One academy enrolment covers every legacy module."""
    if learner.is_staff:
        return True
    return svc.has_access(db, learner, get_settings().COMPAT_PRODUCT_CODE)


def _progress_summary(payload: dict) -> dict:
    """Roster-level summary derived from the app's own blob.

    Mirrors the old implementation so any instructor view built against it
    keeps working. Deliberately shallow — no probe-level detail.
    """
    if not isinstance(payload, dict):
        return {"sections_completed": 0, "probe_accuracy": None, "summative_score": None}
    section_state = payload.get("sectionState") or {}
    completed = sum(
        1 for s in section_state.values()
        if isinstance(s, dict) and s.get("completedAt")
    )
    total_probes = 0
    correct_probes = 0
    for s in section_state.values():
        if not isinstance(s, dict):
            continue
        for attempts in (s.get("probeAttempts") or {}).values():
            if not isinstance(attempts, list) or not attempts:
                continue
            total_probes += 1
            if True in attempts:
                correct_probes += 1
    accuracy = round(100 * correct_probes / total_probes) if total_probes else None
    summative = payload.get("summative")
    summative_score = None
    if isinstance(summative, dict):
        score, total = summative.get("score"), summative.get("total")
        if score is not None and total:
            summative_score = f"{score}/{total}"
    return {
        "sections_completed": completed,
        "probes_attempted": total_probes,
        "probe_accuracy": accuracy,
        "summative_score": summative_score,
        "needs_completed": bool(payload.get("needs")),
    }


def _state_row(db: Session, learner_id: int, module_id: str) -> ModuleState | None:
    return db.execute(
        select(ModuleState).where(
            ModuleState.learner_id == learner_id,
            ModuleState.module_id == module_id,
        )
    ).scalar_one_or_none()


@learning_router.get("/my-modules", response_model=list[ModuleAccessOut])
def my_modules(
    db: Session = Depends(get_db), learner: Learner = Depends(current_learner)
) -> list[ModuleAccessOut]:
    """Every module this learner can open. Empty list when unentitled."""
    entitled = _entitled(db, learner)
    enrollment = svc.active_enrollment(
        db, learner, get_settings().COMPAT_PRODUCT_CODE
    )
    rows = db.execute(
        select(ModuleState).where(ModuleState.learner_id == learner.id)
    ).scalars().all()
    state_by_module = {r.module_id: r for r in rows}

    out: list[ModuleAccessOut] = []
    for module_id in sorted(MODULES):
        if not entitled:
            continue
        info = MODULES[module_id]
        state = state_by_module.get(module_id)
        out.append(
            ModuleAccessOut(
                module_id=module_id,
                title=info["title"],
                subtitle=info["subtitle"],
                url_base=info["url_base"],
                enrolled=True,
                granted_at=enrollment.granted_at if enrollment else None,
                last_active_at=state.last_active_at if state else None,
                progress_summary=_progress_summary(state.payload if state else {}),
                via_admin=enrollment is None and learner.is_staff,
            )
        )
    return out


@learning_router.get("/{module_id}/access", response_model=AccessOut)
def get_access(
    module_id: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(current_learner),
) -> AccessOut:
    _known_module(module_id)
    return AccessOut(
        enrolled=_entitled(db, learner),
        # Invitations and access requests were the old way in. Access now
        # follows the purchase, so these are always false — the fields stay
        # so the apps' response parsing does not break.
        has_pending_invitation=False,
        has_pending_request=False,
        is_admin=bool(learner.is_staff),
    )


@learning_router.post("/{module_id}/request-access", status_code=201)
def request_access(
    module_id: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(current_learner),
) -> dict:
    """Kept so the apps' 'request access' button still resolves.

    There is nothing to approve any more — the course is bought, not granted —
    so this points the person at the sales page instead of opening a ticket
    that nobody works.
    """
    _known_module(module_id)
    settings = get_settings()
    if _entitled(db, learner):
        return {"ok": True, "already_enrolled": True}
    return {
        "ok": True,
        "already_enrolled": False,
        "purchase_url": (
            f"{settings.SITE_URL}/training/{settings.COMPAT_PRODUCT_CODE}"
        ),
        "detail": "This module is part of the Micro Gas Turbine Design course.",
    }


class AcceptInvitationRequest(BaseModel):
    token: str


@learning_router.post("/invitations/accept")
def accept_invitation(
    body: AcceptInvitationRequest,
    db: Session = Depends(get_db),
    learner: Learner = Depends(current_learner),
) -> dict:
    """Retained because the deployed bundles still call it.

    Invitations no longer gate anything — access follows the purchase — so a
    learner who already owns the course gets a success, and anyone else is
    pointed at the sales page rather than a dead 404 the app cannot explain.
    """
    settings = get_settings()
    if _entitled(db, learner):
        return {"ok": True, "already_accepted": True}
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Invitations have been replaced by course enrolment. "
            f"Get access at {settings.SITE_URL}/training/{settings.COMPAT_PRODUCT_CODE}"
        ),
    )


@learning_router.get("/{module_id}/progress", response_model=ProgressOut)
def get_progress(
    module_id: str,
    db: Session = Depends(get_db),
    learner: Learner = Depends(current_learner),
) -> ProgressOut:
    _known_module(module_id)
    if not _entitled(db, learner):
        raise HTTPException(status_code=403, detail="Not enrolled in this module")
    row = _state_row(db, learner.id, module_id.lower())
    return ProgressOut(
        payload=row.payload if row else {},
        updated_at=row.updated_at if row else None,
    )


@learning_router.put("/{module_id}/progress", response_model=ProgressOut)
def put_progress(
    module_id: str,
    body: ProgressIn,
    db: Session = Depends(get_db),
    learner: Learner = Depends(current_learner),
) -> ProgressOut:
    _known_module(module_id)
    if not _entitled(db, learner):
        raise HTTPException(status_code=403, detail="Not enrolled in this module")

    now = datetime.now(timezone.utc)
    row = _state_row(db, learner.id, module_id.lower())
    if row is None:
        row = ModuleState(
            learner_id=learner.id, module_id=module_id.lower(), payload={}
        )
        db.add(row)
    # Wholesale replace: the app owns this document and sends it complete.
    row.payload = body.payload
    row.last_active_at = now
    db.commit()
    db.refresh(row)
    return ProgressOut(payload=row.payload, updated_at=row.updated_at)
