"""Cloudflare Stream signed playback tokens.

A video uploaded with `requireSignedURLs: true` has no public URL at all —
knowing its UID gets you nothing. Playback requires a short-lived JWT signed
with an account signing key, so the only way to watch is to ask this API,
which checks the learner's entitlement first.

Token lifetime is deliberately short (2h default). The player re-requests on
expiry, which means a token copied out of devtools and pasted elsewhere stops
working the same afternoon.

Until the Cloudflare credentials are configured this module reports
`is_configured() == False` and the API degrades gracefully rather than
crashing — lessons still list, they just aren't playable yet.
"""
from __future__ import annotations

import base64
import json
import logging
import time

from .config import get_settings

log = logging.getLogger(__name__)


def is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.CF_STREAM_SIGNING_KEY_ID
        and settings.CF_STREAM_SIGNING_KEY_JWK
        and settings.CF_STREAM_CUSTOMER_CODE
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _load_private_key():
    """Rebuild the RSA private key from Cloudflare's base64-encoded JWK."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.asymmetric.rsa import (
        RSAPrivateNumbers,
        RSAPublicNumbers,
    )

    settings = get_settings()
    raw = settings.CF_STREAM_SIGNING_KEY_JWK
    padding = "=" * (-len(raw) % 4)
    jwk = json.loads(base64.b64decode(raw + padding))

    def num(field: str) -> int:
        value = jwk[field]
        pad = "=" * (-len(value) % 4)
        return int.from_bytes(base64.urlsafe_b64decode(value + pad), "big")

    public = RSAPublicNumbers(e=num("e"), n=num("n"))
    private = RSAPrivateNumbers(
        p=num("p"),
        q=num("q"),
        d=num("d"),
        dmp1=num("dp"),
        dmq1=num("dq"),
        iqmp=num("qi"),
        public_numbers=public,
    )
    _ = rsa  # imported for the type only
    return private.private_key()


def sign_playback_token(
    video_uid: str,
    *,
    ttl_seconds: int | None = None,
    downloadable: bool = False,
) -> str | None:
    """Mint an RS256 JWT authorising playback of one video.

    `downloadable` stays False everywhere in this codebase — that flag is the
    switch that would expose an MP4 URL, which is exactly what the product
    promises not to do. It exists only so a future admin-side export can opt
    in explicitly.
    """
    if not is_configured():
        return None

    settings = get_settings()
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

    ttl = ttl_seconds or settings.STREAM_TOKEN_TTL_SECONDS
    now = int(time.time())
    header = {"alg": "RS256", "kid": settings.CF_STREAM_SIGNING_KEY_ID}
    payload = {
        "sub": video_uid,
        "kid": settings.CF_STREAM_SIGNING_KEY_ID,
        "exp": now + ttl,
        "nbf": now - 30,  # small skew allowance
        "downloadable": downloadable,
    }

    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    try:
        key = _load_private_key()
        signature = key.sign(
            signing_input.encode("ascii"),
            asym_padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as exc:  # malformed key material — fail closed, not loud
        log.error("Stream token signing failed: %s", exc)
        return None
    return signing_input + "." + _b64url(signature)


def playback_urls(video_uid: str) -> dict | None:
    """HLS/DASH manifest URLs plus a thumbnail, all token-scoped.

    Returns None when Stream isn't configured yet so callers can render an
    honest "video coming soon" state instead of a broken player.
    """
    if not video_uid:
        return None
    token = sign_playback_token(video_uid)
    if token is None:
        return None
    settings = get_settings()
    base = f"https://customer-{settings.CF_STREAM_CUSTOMER_CODE}.cloudflarestream.com"
    return {
        "hls": f"{base}/{token}/manifest/video.m3u8",
        "dash": f"{base}/{token}/manifest/video.mpd",
        "thumbnail": f"{base}/{token}/thumbnails/thumbnail.jpg",
        "iframe": f"{base}/{token}/iframe",
        "expires_in": settings.STREAM_TOKEN_TTL_SECONDS,
    }
