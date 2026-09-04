"""Server-side simulator engine host.

Why this exists: an HTML simulator that runs in the browser hands its model
to whoever opens it — every coefficient, every schedule, every equation is
in the file, however well it is obfuscated or locked (app/asset_lock.py).
The only way to keep the model is to not ship it. Here the engine runs in
V8 embedded in this process; the browser gets a thin display that sends
control changes and receives frames. What a learner can download is the
UI; what they cannot download is the physics.

Where the engine comes from: a protected blob (SIM_ENGINE_ASSET_KEY in
academy_asset_blobs), the same store that holds the simulator page itself.
It is evaluated into one V8 isolate at first use and never written to disk,
never committed to the repository (which is public), never served. The
generic plumbing around it — sessions, whitelists, snapshots — is
app/sim_host.js and is loaded after the engine.

One isolate, many engines: a session is an entry in the isolate's `__S`
map. V8 is single-threaded, so every call is serialised through the
isolate's own thread; we hand calls off with asyncio.to_thread so the event
loop keeps serving everyone else. Measured: 60 engines stepping four times
a tick cost 1.3 ms per session-tick and 22 MB in total.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AssetBlob

log = logging.getLogger(__name__)

_HOST_JS = Path(__file__).with_name("sim_host.js").read_text(encoding="utf-8")


class EngineUnavailable(RuntimeError):
    """No engine blob installed, or V8 is missing on this host."""


@dataclass
class SimSession:
    id: str
    learner_id: int
    learner_email: str
    lesson_id: int
    copy_token: str
    ctx: Any                      # the MiniRacer isolate this engine lives in
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    speed: int = 4
    running: bool = False
    want_margin_until: float = 0.0
    ops: int = 0                  # total ops, for the admin view
    run_task: Optional[asyncio.Task] = None
    ws: Any = None                # the socket, so a withdrawal can close it


class SimHost:
    """Owns the isolate(s) and the session table. One per process."""

    def __init__(self) -> None:
        self.ctx: Any = None
        self.sha: str = ""
        self.loaded_at: float = 0.0
        self.sessions: dict[str, SimSession] = {}
        self._load_lock = asyncio.Lock()
        self._checked_at: float = 0.0

    # ------------------------------------------------------------ engine --
    def _read_engine(self, db: Session) -> tuple[bytes, str]:
        key = get_settings().SIM_ENGINE_ASSET_KEY
        blob = db.execute(select(AssetBlob).where(AssetBlob.key == key)).scalar_one_or_none()
        if blob is None:
            raise EngineUnavailable(f"engine blob '{key}' is not installed")
        return blob.data, hashlib.sha256(blob.data).hexdigest()

    def _build_isolate(self, engine_src: bytes) -> Any:
        try:
            from py_mini_racer import MiniRacer
        except Exception as exc:  # pragma: no cover — dependency missing
            raise EngineUnavailable(f"V8 runtime unavailable: {exc}")
        ctx = MiniRacer()
        ctx.eval("var window = globalThis;")
        ctx.eval(engine_src.decode("utf-8"))
        ctx.eval(_HOST_JS)
        ctx.eval("if (typeof DLN === 'undefined' || !DLN.Engine) throw new Error('engine bundle defines no DLN.Engine');")
        return ctx

    async def ensure_engine(self, db: Session, *, force: bool = False) -> None:
        """Load the engine bundle into a fresh isolate if it changed.

        Existing sessions keep the isolate they started in; only new
        sessions get the new engine. That is what makes an engine upgrade
        safe while learners are mid-run. The blob is re-read at most once
        a minute unless forced (the admin reload endpoint), so a class
        connecting at once does not read 160 KB per socket."""
        async with self._load_lock:
            now = time.time()
            if self.ctx is not None and not force and now - self._checked_at < 60:
                return
            data, sha = await asyncio.to_thread(self._read_engine, db)
            self._checked_at = now
            if self.ctx is not None and sha == self.sha and not force:
                return
            ctx = await asyncio.to_thread(self._build_isolate, data)
            self.ctx, self.sha, self.loaded_at = ctx, sha, time.time()
            log.info("Simulator engine loaded (%d bytes, sha %s)", len(data), sha[:12])

    # ---------------------------------------------------------- sessions --
    def count_for(self, learner_id: int) -> int:
        return sum(1 for s in self.sessions.values() if s.learner_id == learner_id)

    async def _eval(self, ctx: Any, code: str) -> Any:
        return await asyncio.to_thread(ctx.eval, code)

    async def create(self, *, learner_id: int, learner_email: str, lesson_id: int,
                     copy_token: str, key: str, shaft: str, limit_set: str) -> tuple[SimSession, dict]:
        if self.ctx is None:
            raise EngineUnavailable("engine not loaded")
        sid = secrets.token_urlsafe(12)
        s = SimSession(id=sid, learner_id=learner_id, learner_email=learner_email,
                       lesson_id=lesson_id, copy_token=copy_token, ctx=self.ctx)
        out = await self._eval(s.ctx, f"__new({_js(sid)}, {_js(key)}, {_js(shaft)}, {_js(limit_set)})")
        self.sessions[sid] = s
        return s, json.loads(out)

    async def rebuild(self, s: SimSession, *, key: str, shaft: str, limit_set: str) -> dict:
        """The UI's Reset: a brand-new engine in the same session."""
        out = await self._eval(s.ctx, f"__new({_js(s.id)}, {_js(key)}, {_js(shaft)}, {_js(limit_set)})")
        return json.loads(out)

    async def drop(self, s: SimSession) -> None:
        self.sessions.pop(s.id, None)
        if s.run_task is not None:
            s.run_task.cancel()
        try:
            await self._eval(s.ctx, f"__drop({_js(s.id)})")
        except Exception:  # pragma: no cover
            log.exception("drop failed for session %s", s.id)

    async def set(self, s: SimSession, path: list, value: Any) -> dict:
        out = await self._eval(s.ctx, f"__set({_js(s.id)}, {_js(json.dumps(path))}, {_js(json.dumps(value))})")
        return json.loads(out)

    async def delete(self, s: SimSession, path: list) -> dict:
        out = await self._eval(s.ctx, f"__del({_js(s.id)}, {_js(json.dumps(path))})")
        return json.loads(out)

    async def call(self, s: SimSession, fn: str, args: list) -> dict:
        out = await self._eval(s.ctx, f"__call({_js(s.id)}, {_js(fn)}, {_js(json.dumps(args))})")
        return json.loads(out)

    async def prime(self, s: SimSession) -> dict:
        return json.loads(await self._eval(s.ctx, f"__prime({_js(s.id)})"))

    async def tick(self, s: SimSession, n: int, want_margin: bool) -> str:
        """Advance n seconds; returns the raw JSON (it goes straight to the
        socket, no need to parse it here)."""
        n = max(1, min(int(n), get_settings().SIM_MAX_SPEED))
        return await self._eval(s.ctx, f"__tick({_js(s.id)}, {n}, {'true' if want_margin else 'false'})")

    async def consts(self, ctx: Any) -> dict:
        return json.loads(await self._eval(ctx, "__consts()"))

    async def kill(self, *, copy_token: str = "", learner_id: int | None = None,
                   reason: str = "") -> int:
        """End live sessions for a withdrawn copy or a whole account. The
        socket is told why, then closed; the engine is dropped."""
        victims = [
            s for s in list(self.sessions.values())
            if (copy_token and s.copy_token == copy_token)
            or (learner_id is not None and s.learner_id == learner_id)
        ]
        for s in victims:
            ws = s.ws
            try:
                if ws is not None:
                    await ws.send_text(json.dumps({"op": "bye", "code": 4410, "reason": reason or
                        "This copy has been withdrawn by the instructor. Launch a fresh one from your course page."}))
                    await ws.close(code=4410)
            except Exception:  # pragma: no cover — socket may already be gone
                pass
            await self.drop(s)
        return len(victims)

    def status(self) -> dict:
        now = time.time()
        return {
            "engine_loaded": self.ctx is not None,
            "engine_sha": self.sha[:12],
            "loaded_at": self.loaded_at,
            "sessions": [
                {
                    "id": s.id[:6], "email": s.learner_email, "lesson_id": s.lesson_id,
                    "copy_token": s.copy_token,
                    "age_s": int(now - s.created), "idle_s": int(now - s.last_seen),
                    "running": s.running, "speed": s.speed, "ops": s.ops,
                    "current_engine": s.ctx is self.ctx,
                }
                for s in self.sessions.values()
            ],
        }


def _js(s: str) -> str:
    """A JS string literal. json.dumps escapes everything that matters."""
    return json.dumps(str(s))


host = SimHost()
