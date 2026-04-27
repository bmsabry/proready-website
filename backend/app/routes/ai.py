"""Admin AI assistant routes (slice 2 — tool calling + audit + spend cap).

Endpoints (all admin-protected):
  GET    /api/admin/ai/settings                   — read config (api key masked)
  PUT    /api/admin/ai/settings                   — write config
  POST   /api/admin/ai/chat                       — chat turn; runs tool loop
  POST   /api/admin/ai/actions/{id}/approve       — execute a pending action
  POST   /api/admin/ai/actions/{id}/deny          — discard a pending action
  GET    /api/admin/ai/audit                      — paginated audit log

Design:
- One row per LLM turn into ai_audit (kind='chat'); one per executed tool
  call (kind='tool'); one per cap-rejected request (kind='cap_hit').
- High-stakes tool calls are intercepted: their full state is stashed in
  ai_pending_actions, the loop returns a pending_action to the frontend,
  the admin clicks Approve, /actions/{id}/approve resumes the loop.
- Daily spend cap is checked BEFORE each LLM call. Tracks live.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..ai_pricing import (
    DEFAULT_DAILY_CAP_MICRO_USD,
    estimate_cost_micro,
    format_micro_usd,
)
from ..ai_tools import (
    TOOL_HANDLERS,
    TOOL_SPECS,
    is_high_stakes,
    summarize_call,
)
from ..crypto import CryptoNotConfigured, decrypt, encrypt
from ..db import get_db
from ..deps import require_admin
from ..models import AIAudit, AIPendingAction, AISettings, AIUsageDaily
from ..schemas import (
    AIAuditOut,
    AIChatIn,
    AIChatMessage,
    AIChatOut,
    AISettingsIn,
    AISettingsOut,
    PendingActionOut,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/ai",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

# Hard cap on the tool-calling loop — the model gets this many "go again"
# rounds before we bail with an error. Stops runaway loops.
MAX_TOOL_ITERATIONS = 8

# How long a pending action stays clickable.
PENDING_TTL = timedelta(minutes=10)


SYSTEM_PROMPT = """\
You are an admin assistant for the ProReadyEngineer training website.
You can read and modify the database through tools. Be concise.

Conventions:
- Course codes look like 'gas-turbine-emissions-mapping-2026-05'.
- Dates: ISO YYYY-MM-DD.
- day_dates is the full ordered list of per-day dates for a cohort. Length = number of days. Send the FULL list when calling update_course (it replaces wholesale).
- Email body is PLAIN TEXT. Newlines become paragraphs and <br> in the email; the backend handles HTML.

Confirmation:
- Sending broadcast emails (notify_course) ALWAYS waits for the admin to click Approve in the chat. You will not see the result until they confirm.
- Bulk operations on 3+ rows wait for Approve too.
- Single-row mark_paid / cancel and other edits run immediately.

When asked something open-ended ('how are seats looking?'), prefer reading first (list_courses, list_registrations) before suggesting changes."""


# ---------------------------------------------------------------------------
# Settings helpers (unchanged from slice 1)
# ---------------------------------------------------------------------------


def _get_or_create_settings(db: Session) -> AISettings:
    row = db.execute(select(AISettings).limit(1)).scalar_one_or_none()
    if row is None:
        row = AISettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _settings_to_out(row: AISettings) -> AISettingsOut:
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
    url = api_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


# ---------------------------------------------------------------------------
# Spend cap + usage tracking
# ---------------------------------------------------------------------------


def _today_usage(db: Session) -> AIUsageDaily:
    today = datetime.now(timezone.utc).date()
    row = db.get(AIUsageDaily, today)
    if row is None:
        row = AIUsageDaily(date=today)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _check_cap(db: Session) -> None:
    """Raise 429 if today's usage already exceeds the cap."""
    row = _today_usage(db)
    if row.cost_usd_micro >= DEFAULT_DAILY_CAP_MICRO_USD:
        # Audit the rejection so the admin can see why the chat refused.
        db.add(
            AIAudit(
                kind="cap_hit",
                tool_name="",
                params={},
                summary=(
                    f"Daily spend cap reached: {format_micro_usd(row.cost_usd_micro)} "
                    f"used / {format_micro_usd(DEFAULT_DAILY_CAP_MICRO_USD)} cap"
                ),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily AI spend cap reached "
                f"({format_micro_usd(row.cost_usd_micro)} of "
                f"{format_micro_usd(DEFAULT_DAILY_CAP_MICRO_USD)}). "
                "Resets at UTC midnight."
            ),
        )


def _record_usage(db: Session, tokens_in: int, tokens_out: int) -> int:
    """Add tokens to today's row, return cost_usd_micro added."""
    cost = estimate_cost_micro(tokens_in, tokens_out)
    row = _today_usage(db)
    row.tokens_in = (row.tokens_in or 0) + int(tokens_in)
    row.tokens_out = (row.tokens_out or 0) + int(tokens_out)
    row.cost_usd_micro = (row.cost_usd_micro or 0) + cost
    db.commit()
    return cost


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _audit(
    db: Session,
    *,
    kind: str,
    tool_name: str = "",
    params: Optional[Dict[str, Any]] = None,
    summary: str = "",
    error: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd_micro: int = 0,
    model: str = "",
) -> None:
    db.add(
        AIAudit(
            kind=kind,
            tool_name=tool_name,
            params=params or {},
            summary=summary[:500],
            error=(error or None) and str(error)[:2000],
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            cost_usd_micro=int(cost_usd_micro),
            model=model[:200],
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------


def _call_llm(
    *,
    api_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], int, int]:
    """Returns (response_message, tokens_in, tokens_out). Raises HTTPException on transport errors."""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = client.post(api_url, json=payload, headers=headers)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the LLM provider: {e}",
        ) from e

    if resp.status_code >= 400:
        snippet = resp.text[:500]
        log.warning("LLM upstream error %s: %s", resp.status_code, snippet)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider returned HTTP {resp.status_code}: {snippet}",
        )

    data = resp.json()
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected LLM response shape: {e}; raw={str(data)[:300]}",
        ) from e

    usage = data.get("usage") or {}
    return msg, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


# ---------------------------------------------------------------------------
# Tool execution + pending-action storage
# ---------------------------------------------------------------------------


def _execute_tool(
    db: Session,
    tool_name: str,
    args: Dict[str, Any],
    *,
    model: str = "",
) -> Dict[str, Any]:
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        result = {"ok": False, "error": f"unknown tool '{tool_name}'"}
        _audit(
            db,
            kind="tool",
            tool_name=tool_name,
            params=args,
            summary=f"unknown tool: {tool_name}",
            error="unknown tool",
            model=model,
        )
        return result
    try:
        result = handler(db, **args)
    except TypeError as e:
        # Bad argument shape from the model.
        result = {"ok": False, "error": f"invalid arguments: {e}"}
    except Exception as e:  # noqa: BLE001 — agent-facing errors must be friendly
        log.exception("Tool %s failed", tool_name)
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    _audit(
        db,
        kind="tool",
        tool_name=tool_name,
        params=args,
        summary=summarize_call(tool_name, args),
        error=None if result.get("ok") else str(result.get("error", "")),
        model=model,
    )
    return result


def _new_pending_id() -> str:
    return f"act_{secrets.token_urlsafe(8)}"


def _create_pending(
    db: Session,
    *,
    tool_name: str,
    args: Dict[str, Any],
    snapshot: List[Dict[str, Any]],
    tool_call_id: str,
) -> AIPendingAction:
    """Persist a high-stakes tool call awaiting approval.

    `snapshot` is the full message list AT the moment the model emitted
    this tool call (NOT including the would-be tool result). On approve,
    we resume the loop with this snapshot + the new tool result message.
    """
    pa = AIPendingAction(
        id=_new_pending_id(),
        tool_name=tool_name,
        params={
            "args": args,
            "snapshot": snapshot,
            "tool_call_id": tool_call_id,
        },
        summary=summarize_call(tool_name, args),
        expires_at=datetime.now(timezone.utc) + PENDING_TTL,
    )
    db.add(pa)
    db.commit()
    db.refresh(pa)
    return pa


# ---------------------------------------------------------------------------
# Internal-message <-> public-message conversion
# ---------------------------------------------------------------------------


def _build_initial_messages(public_msgs: List[AIChatMessage]) -> List[Dict[str, Any]]:
    """Drop any user-supplied system message; backend owns the system prompt."""
    out: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in public_msgs:
        if m.role == "system":
            continue  # ignore — backend owns this
        out.append({"role": m.role, "content": m.content})
    return out


# ---------------------------------------------------------------------------
# The main loop
# ---------------------------------------------------------------------------


def _run_loop(
    db: Session,
    *,
    settings_row: AISettings,
    api_key: str,
    messages: List[Dict[str, Any]],
    actions_executed: Optional[List[str]] = None,
) -> AIChatOut:
    """Run the tool-calling loop.

    Returns either a final assistant text response, or a pending_action
    (when a high-stakes tool call needs approval).
    """
    if actions_executed is None:
        actions_executed = []
    api_url = _normalize_chat_url(settings_row.api_url)
    model = settings_row.model_name

    for _ in range(MAX_TOOL_ITERATIONS):
        _check_cap(db)
        msg, t_in, t_out = _call_llm(
            api_url=api_url,
            api_key=api_key,
            model=model,
            messages=messages,
            tools=TOOL_SPECS,
        )
        cost = _record_usage(db, t_in, t_out)
        _audit(
            db,
            kind="chat",
            tool_name="",
            params={},
            summary=f"LLM turn ({t_in}→{t_out} tokens)",
            tokens_in=t_in,
            tokens_out=t_out,
            cost_usd_micro=cost,
            model=model,
        )

        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            # Append the assistant's tool_calls turn to history.
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                if is_high_stakes(tool_name, args):
                    pa = _create_pending(
                        db,
                        tool_name=tool_name,
                        args=args,
                        snapshot=messages,
                        tool_call_id=tc["id"],
                    )
                    return AIChatOut(
                        content=(
                            (msg.get("content") or "").strip()
                            or f"I'd like to: {pa.summary}. Approve to proceed."
                        ),
                        pending_action=PendingActionOut(
                            id=pa.id,
                            tool=tool_name,
                            summary=pa.summary,
                            expires_at=pa.expires_at,
                        ),
                        actions_executed=actions_executed,
                    )

                # Low-stakes — execute now, append result, keep looping.
                result = _execute_tool(db, tool_name, args, model=model)
                actions_executed.append(summarize_call(tool_name, args))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tool_name,
                    "content": json.dumps(result)[:50_000],
                })
            # Loop continues with the new tool messages in context.
            continue

        # Plain text reply — done.
        return AIChatOut(
            content=(msg.get("content") or "").strip() or "(model returned an empty response)",
            actions_executed=actions_executed,
            raw_finish_reason=None,
        )

    return AIChatOut(
        content=(
            "Reached the maximum tool-calling iterations without finishing. "
            "Try a simpler request or split into smaller steps."
        ),
        actions_executed=actions_executed,
    )


# ---------------------------------------------------------------------------
# Routes — settings (unchanged from slice 1)
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=AISettingsOut)
def get_settings_endpoint(db: Session = Depends(get_db)) -> AISettingsOut:
    return _settings_to_out(_get_or_create_settings(db))


@router.put("/settings", response_model=AISettingsOut)
def put_settings(body: AISettingsIn, db: Session = Depends(get_db)) -> AISettingsOut:
    try:
        encrypted = encrypt(body.api_key)
    except CryptoNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    row = _get_or_create_settings(db)
    row.api_url = body.api_url.strip()
    row.api_key_encrypted = encrypted
    row.model_name = body.model_name.strip()
    db.commit()
    db.refresh(row)
    return _settings_to_out(row)


# ---------------------------------------------------------------------------
# Routes — chat + actions
# ---------------------------------------------------------------------------


def _resolve_settings_for_chat(db: Session) -> Tuple[AISettings, str]:
    row = _get_or_create_settings(db)
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
    return row, api_key


@router.post("/chat", response_model=AIChatOut)
def chat(body: AIChatIn, db: Session = Depends(get_db)) -> AIChatOut:
    row, api_key = _resolve_settings_for_chat(db)
    messages = _build_initial_messages(body.messages)
    return _run_loop(db, settings_row=row, api_key=api_key, messages=messages)


@router.post("/actions/{action_id}/approve", response_model=AIChatOut)
def approve_action(action_id: str, db: Session = Depends(get_db)) -> AIChatOut:
    pa = db.get(AIPendingAction, action_id)
    if pa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    if pa.consumed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action already used.")
    if pa.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Action expired. Ask the assistant again.")

    row, api_key = _resolve_settings_for_chat(db)
    args = pa.params.get("args") or {}
    snapshot = pa.params.get("snapshot") or []
    tool_call_id = pa.params.get("tool_call_id") or ""

    # Execute now (audit logged inside).
    result = _execute_tool(db, pa.tool_name, args, model=row.model_name)
    pa.consumed_at = datetime.now(timezone.utc)
    db.commit()

    # Resume the loop with the tool result fed in.
    messages = list(snapshot)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": pa.tool_name,
        "content": json.dumps(result)[:50_000],
    })
    actions_executed = [f"✓ {summarize_call(pa.tool_name, args)}"]
    return _run_loop(
        db,
        settings_row=row,
        api_key=api_key,
        messages=messages,
        actions_executed=actions_executed,
    )


@router.post("/actions/{action_id}/deny", response_model=AIChatOut)
def deny_action(action_id: str, db: Session = Depends(get_db)) -> AIChatOut:
    pa = db.get(AIPendingAction, action_id)
    if pa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    if pa.consumed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action already used.")

    row, api_key = _resolve_settings_for_chat(db)
    snapshot = pa.params.get("snapshot") or []
    tool_call_id = pa.params.get("tool_call_id") or ""
    pa.consumed_at = datetime.now(timezone.utc)
    db.commit()

    # Tell the model the action was denied so it can react.
    messages = list(snapshot)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": pa.tool_name,
        "content": json.dumps({
            "ok": False,
            "denied_by_admin": True,
            "error": "Admin denied this action. Suggest alternatives or stop.",
        }),
    })
    return _run_loop(
        db,
        settings_row=row,
        api_key=api_key,
        messages=messages,
        actions_executed=[f"✗ denied: {pa.summary}"],
    )


# ---------------------------------------------------------------------------
# Routes — audit log
# ---------------------------------------------------------------------------


@router.get("/audit", response_model=List[AIAuditOut])
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[AIAuditOut]:
    rows = list(
        db.execute(
            select(AIAudit).order_by(desc(AIAudit.created_at)).limit(limit)
        ).scalars()
    )
    return [
        AIAuditOut(
            id=r.id,
            created_at=r.created_at,
            kind=r.kind,
            tool_name=r.tool_name,
            summary=r.summary,
            error=r.error,
            tokens_in=r.tokens_in or 0,
            tokens_out=r.tokens_out or 0,
            cost_usd=(r.cost_usd_micro or 0) / 1_000_000,
            model=r.model or "",
        )
        for r in rows
    ]
