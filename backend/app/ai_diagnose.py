"""Admin → AI Settings → "Test the connection".

The website uses one AI model for everything: support triage and reply
drafts, which need an answer in JSON, and the admin assistant's chat, which
needs tool calling. The test makes one tiny real request of each kind, so
"working" means the site will work — not that a key merely looks right.

Nothing here raises: every failure comes back as a failed step saying what
went wrong and what to change.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from . import support_service as svc
from .crypto import CryptoNotConfigured, decrypt

PING_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Connection check. Call it with value 'ok'.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    },
}


def _step(key: str, title: str, status: str, detail: str = "", seconds: float | None = None) -> dict:
    return {"key": key, "title": title, "status": status, "detail": detail, "seconds": seconds}


def _tool_test(row: Any, api_key: str) -> tuple[bool, str, float]:
    """Ask the model to call a tool, the way the admin assistant does."""
    provider = svc._provider(row.api_url)
    payload = {
        "model": row.model_name,
        "messages": [
            {
                "role": "system",
                "content": "You are checking a connection. Call the ping tool once with "
                'value "ok". Do not answer in text.',
            },
            {"role": "user", "content": "Call ping now."},
        ],
        "tools": [PING_TOOL],
        "tool_choice": "auto",
        "temperature": 0.3,
        "stream": False,
    }
    started = time.monotonic()

    def secs() -> float:
        return round(time.monotonic() - started, 1)

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            resp = client.post(
                svc._chat_url(row.api_url),
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as e:
        return False, f"{provider}: could not be reached ({type(e).__name__})", secs()
    if resp.status_code >= 400:
        return False, svc._http_failure(provider, resp), secs()
    try:
        body = resp.json()
    except ValueError:
        body = None
    choices = body.get("choices") if isinstance(body, dict) else None
    if not choices or not isinstance(choices[0], dict):
        if isinstance(body, dict) and body.get("error"):
            return False, svc._http_failure(provider, resp), secs()
        return False, f"{provider}: the answer came back in an unexpected shape", secs()
    msg = choices[0].get("message") or {}
    names = [((c or {}).get("function") or {}).get("name") for c in msg.get("tool_calls") or []]
    if "ping" in names:
        return True, "", secs()
    text = msg.get("content") or ""
    snippet = " ".join(str(text).split())[:80]
    return (
        False,
        f"{provider}: the model answered in text instead of using a tool, and the AI "
        "Assistant needs a model that supports tool calling" + (f" (“{snippet}”)" if snippet else ""),
        secs(),
    )


def diagnose(db: Session) -> dict[str, Any]:
    row = svc.get_support_settings(db)
    provider = svc._provider(row.api_url) if row is not None else ""
    steps: list[dict] = []
    api_key = ""

    if row is None:
        steps.append(_step(
            "settings", "Settings saved", "fail",
            "Enter the API URL, the model name and the API key, then Save.",
        ))
    else:
        try:
            api_key = decrypt(row.api_key_encrypted)
        except CryptoNotConfigured:
            api_key = ""
        if api_key:
            steps.append(_step("settings", "Settings saved", "pass", f"{row.model_name} via {provider}"))
        else:
            steps.append(_step(
                "settings", "Settings saved", "fail",
                "The saved API key can't be read. Paste the key again and Save.",
            ))

    connect_title = f"Reach {provider or 'the AI provider'} and sign in with your key"
    json_title = "Support replies and drafts: answer in the form the desk reads (JSON)"
    tools_title = "AI Assistant chat: use tools (look things up, act on the site)"

    if steps[0]["status"] != "pass":
        for key, title in (("connect", connect_title), ("json", json_title), ("tools", tools_title)):
            steps.append(_step(key, title, "skipped", "Needs the settings first."))
    else:
        probe = svc.probe_json(db)
        reached = probe["ok"] or probe["stage"] == "answer"
        steps.append(_step(
            "connect", connect_title, "pass" if reached else "fail",
            "Connected and the key was accepted." if reached else probe["error"],
            probe["seconds"] if reached else None,
        ))
        if not reached:
            steps.append(_step("json", json_title, "skipped", "Needs a working connection first."))
            steps.append(_step("tools", tools_title, "skipped", "Needs a working connection first."))
        else:
            steps.append(_step(
                "json", json_title, "pass" if probe["ok"] else "fail",
                f"Answered in {probe['seconds']} s." if probe["ok"] else probe["error"],
                probe["seconds"],
            ))
            ok, error, seconds = _tool_test(row, api_key)
            steps.append(_step(
                "tools", tools_title, "pass" if ok else "fail",
                f"Called the test tool in {seconds} s." if ok else error, seconds,
            ))

    ok = all(s["status"] == "pass" for s in steps)
    failed = next((s for s in steps if s["status"] == "fail"), None)
    return {
        "ok": ok,
        "model": row.model_name if row is not None else "",
        "provider": provider,
        "verdict": (
            f"Working perfectly. {row.model_name} via {provider} is answering support "
            "messages, drafting replies and running the AI Assistant."
            if ok and row is not None
            else f"Not working — {failed['detail']}" if failed else "Not working."
        ),
        "steps": steps,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "health": svc.ai_health(db),
    }
