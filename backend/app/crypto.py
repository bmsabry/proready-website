"""Encryption helpers for at-rest secrets (LLM API keys, etc).

Uses Fernet (symmetric authenticated encryption) keyed off the
AI_SETTINGS_KEY environment variable. Generate one once with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

…and set it on Render. Without this env var, encryption ops will raise
RuntimeError (failing loud is the right answer — silently storing a key
in plaintext is the wrong answer).
"""
from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class CryptoNotConfigured(RuntimeError):
    """Raised when AI_SETTINGS_KEY is missing or invalid."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = os.environ.get("AI_SETTINGS_KEY", "").strip()
    if not raw:
        raise CryptoNotConfigured(
            "AI_SETTINGS_KEY env var is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and add it to Render."
        )
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError) as e:
        raise CryptoNotConfigured(
            f"AI_SETTINGS_KEY is malformed (must be a 32-byte url-safe base64 string): {e}"
        )


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a url-safe base64 token."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a Fernet token back to plaintext. Returns '' for empty input."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise CryptoNotConfigured(
            "Stored API key cannot be decrypted (likely the AI_SETTINGS_KEY "
            "env var changed since it was saved). Re-enter the key in /admin."
        ) from e
