"""The DEPLOYER identity: a GitHub Actions run that may update the simulator.

When a commit lands on the simulator's private repository, a workflow there
builds the thin client and the engine bundle and uploads them here. It does
not carry an admin token. It carries the OIDC token GitHub mints for every
workflow run, which says — signed by GitHub — which repository, branch and
workflow it came from. We verify that signature against GitHub's published
keys and accept the run only if it is *our* repository on *our* branch and
the token was minted for *our* audience.

What the deployer may do is deliberately small (see the endpoints that take
`require_admin_or_deployer`): write two named blobs, read the engine status,
reload the engine. It cannot read learners, grants, emails or anything else.

A static SIM_DEPLOY_TOKEN is accepted as a fallback for a machine that
cannot mint OIDC tokens; it grants exactly the same small set of actions.
"""
from __future__ import annotations

import logging
import secrets
import time

import jwt
from fastapi import Cookie, Header, HTTPException, status

from .config import get_settings
from .deps import require_admin

log = logging.getLogger(__name__)

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_JWKS_URL = GITHUB_OIDC_ISSUER + "/.well-known/jwks"
DEPLOYER = "deployer:github-actions"

_jwk_client: jwt.PyJWKClient | None = None


def _signing_key(token: str):
    """The public key that signed `token`, from GitHub's JWKS (cached)."""
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(GITHUB_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwk_client.get_signing_key_from_jwt(token).key


def verify_github_oidc(token: str) -> dict:
    """Return the claims of a GitHub Actions OIDC token that is ours, or
    raise ValueError saying why it is not."""
    settings = get_settings()
    repo = settings.SIM_DEPLOY_GITHUB_REPO.strip()
    if not repo:
        raise ValueError("deployer identity is switched off (SIM_DEPLOY_GITHUB_REPO empty)")
    try:
        key = _signing_key(token)
    except Exception as exc:  # network, unknown kid, malformed header
        raise ValueError("could not fetch the signing key: %s" % exc) from exc
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.SIM_DEPLOY_AUDIENCE,
            issuer=GITHUB_OIDC_ISSUER,
            options={"require": ["exp", "iat", "aud", "iss", "sub", "repository", "ref"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise ValueError("token rejected: %s" % exc) from exc
    if claims.get("repository", "").lower() != repo.lower():
        raise ValueError("token is for repository %r, not %r" % (claims.get("repository"), repo))
    want_ref = settings.SIM_DEPLOY_GITHUB_REF.strip()
    if want_ref and claims.get("ref") != want_ref:
        raise ValueError("token is for ref %r, not %r" % (claims.get("ref"), want_ref))
    # a token is minted for one run; never accept one that is already old
    if time.time() - float(claims.get("iat", 0)) > 15 * 60:
        raise ValueError("token is older than 15 minutes")
    return claims


def require_admin_or_deployer(
    authorization: str = Header(default=""),
    admin_session: str = Cookie(default=""),
) -> str:
    """Admin (cookie or ADMIN_TOKEN) as usual — or the deployer.

    Returns the admin email, or DEPLOYER for a verified GitHub Actions run
    (callers that must restrict what the deployer can touch check for it)."""
    try:
        return require_admin(authorization=authorization, admin_session=admin_session)
    except HTTPException:
        pass
    settings = get_settings()
    prefix = "Bearer "
    if authorization.startswith(prefix):
        token = authorization[len(prefix):].strip()
        if settings.SIM_DEPLOY_TOKEN and secrets.compare_digest(token, settings.SIM_DEPLOY_TOKEN):
            return DEPLOYER
        # an OIDC token is a JWT: three dot-separated segments
        if token.count(".") == 2 and settings.SIM_DEPLOY_GITHUB_REPO:
            try:
                claims = verify_github_oidc(token)
            except ValueError as exc:
                log.warning("Deployer token refused: %s", exc)
            else:
                log.info("Deployer accepted: %s@%s run %s", claims.get("repository"),
                         claims.get("ref"), claims.get("run_id"))
                return DEPLOYER
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Sign in at /admin, supply a bearer token, or present a GitHub Actions OIDC token for the simulator repository.",
    )


def deployer_may_write(key: str) -> bool:
    keys = {k.strip() for k in get_settings().SIM_DEPLOY_ASSET_KEYS.split(",") if k.strip()}
    return key in keys
