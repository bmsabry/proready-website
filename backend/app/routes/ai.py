"""Admin AI assistant routes.

Endpoints (all admin-protected):
  GET  /api/admin/ai/settings   — return current config (api key masked)
  PUT  /api/admin/ai/settings   — replace url/key/model
  POST /api/admin/ai/chat       — send a chat turn to the configured LLM

Slice 1: chat is a plain proxy to an OpenAI-compatible chat/completions
endpoint. No tool calling yet — that comes in slice 2 along with audit logs.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto import CryptoNotConfigured, decrypt, encrypt
from ..db import get_db
from ..deps import require_admin
from ..models import AISettings
from ..schemas import (
    AIChatIn,
    AIChatOut,
    AISettingsIn,
    AISettingsOut,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/ai",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ----- Helpers --------------------------------------------------------------


def _get_or_create(db: Session) -> AISettings:
    """The settings table holds at most one row. Lazy-create on first read."""
    row = db.execute(select(AISettings).limit(1)).scalar_one_or_none()
    if row is None:
        row = AISettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _to_out(row: AISettings) -> AISettingsOut:
    """Render the settings to the admin without exposing the key."""
    masked = ""
    if row.api_key_encrypted:
        try:
            plaintext = decrypt(row.api_key_encrypted)
        except CryptoNotConfigured:
            plaintext = ""
        if plaintext:
            tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
            masked = f"…{tail}"
    return AISettingsOut(
        api_url=row.api_url or "",
        model_name=row.model_name or "",
        api_key_masked=masked,
        is_configured=bool(row.api_url and row.api_key_encrypted and row.model_name),
    )


def _normalize_chat_url(api_url: str) -> str:
    """OpenAI-compatible providers expose POST {base}/chat/completions.

    Admins paste anything from a base URL ('https://api.openai.com/v1') to
    a full endpoint ('https://api.openai.com/v1/chat/completions'). Make
    both work without surprise.
    """
    url = api_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


# ----- Routes ---------------------------------------------------------------


@router.get("/settings", response_model=AISettingsOut)
def get_settings(db: Session = Depends(get_db)) -> AISettingsOut:
    return _to_out(_get_or_create(db))


@router.put("/settings", response_model=AISettingsOut)
def put_settings(body: AISettingsIn, db: Session = Depends(get_db)) -> AISettingsOut:
    try:
        encrypted = encrypt(body.api_key)
    except CryptoNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    row = _get_or_create(db)
    row.api_url = body.api_url.strip()
    row.api_key_encrypted = encrypted
    row.model_name = body.model_name.strip()
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/chat", response_model=AIChatOut)
def chat(body: AIChatIn, db: Session = Depends(get_db)) -> AIChatOut:
    row = _get_or_create(db)
    if not (row.api_url and row.api_key_encrypted and row.model_name):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="AI assistant is not configured. Set the API URL, key, and model in /admin → AI Settings.",
        )

    try:
        api_key = decrypt(row.api_key_encrypted)
    except CryptoNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    url = _normalize_chat_url(row.api_url)
    payload = {
        "model": row.model_name,
        "messages": [m.model_dump() for m in body.messages],
        "temperature": 0.4,
        # No streaming yet; one-shot response is simpler for slice 1.
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the LLM provider: {e}",
        ) from e

    if resp.status_code >= 400:
        # Surface the upstream message but trim any leaking 'Authorization' echo.
        snippet = resp.text[:500]
        log.warning("LLM upstream error %s: %s", resp.status_code, snippet)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider returned HTTP {resp.status_code}: {snippet}",
        )

    data = resp.json()
    try:
        choice = data["choices"][0]
        message = choice["message"]
        content = (message.get("content") or "").strip()
        finish_reason: Optional[str] = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected LLM response shape: {e}; raw={str(data)[:300]}",
        ) from e

    if not content:
        content = "(model returned an empty response)"

    return AIChatOut(content=content, raw_finish_reason=finish_reason)
