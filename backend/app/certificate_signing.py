"""Ed25519 signing of issued certificates.

Every certificate carries a signature over its canonical facts. The public
verify endpoint re-checks that signature, so a certificate whose name,
course, tier or date has been altered is reported as invalid even if the
code itself is real. The short fingerprint printed on the certificate is
derived from the signature, so it too changes if anything is tampered with.

Key management: `CERT_SIGNING_KEY` is the base64 of the 32-byte Ed25519 seed.
It must never be rotated casually — every certificate ever issued verifies
against it. When it is unset (local dev, tests) a key is derived from
SESSION_SECRET so signatures are at least stable across restarts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import date
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def _private_key() -> Ed25519PrivateKey:
    settings = get_settings()
    raw = (settings.CERT_SIGNING_KEY or "").strip()
    if raw:
        seed = base64.b64decode(raw)
        if len(seed) != 32:
            raise RuntimeError("CERT_SIGNING_KEY must be the base64 of a 32-byte seed")
        return Ed25519PrivateKey.from_private_bytes(seed)
    log.warning(
        "CERT_SIGNING_KEY unset — deriving the certificate signing key from "
        "SESSION_SECRET. Set CERT_SIGNING_KEY in production."
    )
    seed = hashlib.sha256(
        b"proreadyengineer-certificate-signing:" + (settings.SESSION_SECRET or "dev").encode()
    ).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_b64() -> str:
    pub = _private_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(pub).decode()


def key_id() -> str:
    """Short identifier of the signing key, shown on the verify page."""
    pub = base64.b64decode(public_key_b64())
    return hashlib.sha256(pub).hexdigest()[:12].upper()


def canonical_payload(
    *,
    code: str,
    tier: str,
    learner_name: str,
    product_code: str,
    course_title: str,
    issued_on: date,
    exam_date: date | None,
) -> bytes:
    """The exact bytes that get signed. Sorted keys, no whitespace, UTF-8.

    Any change to this function invalidates every signature ever produced,
    so treat it as frozen.
    """
    doc = {
        "code": code,
        "tier": tier,
        "learner_name": learner_name,
        "product_code": product_code,
        "course_title": course_title,
        "issued_on": issued_on.isoformat(),
        "exam_date": exam_date.isoformat() if exam_date else "",
        "issuer": "ProReadyEngineer LLC",
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(payload: bytes) -> str:
    return base64.b64encode(_private_key().sign(payload)).decode()


def verify(payload: bytes, signature_b64: str) -> bool:
    if not signature_b64:
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64()))
        pub.verify(base64.b64decode(signature_b64), payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def fingerprint(signature_b64: str) -> str:
    """`XXXX-XXXX-XXXX-XXXX` — the first 16 hex of SHA-256(signature)."""
    h = hashlib.sha256(base64.b64decode(signature_b64)).hexdigest().upper()[:16]
    return "-".join(h[i : i + 4] for i in range(0, 16, 4))
