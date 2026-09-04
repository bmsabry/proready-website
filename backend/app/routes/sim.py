"""The simulator's WebSocket: a thin client talking to an engine it never sees.

  WS   /api/academy/sim/ws?lesson={id}&copy={token}   learner session cookie
  GET  /api/admin/academy/sim/status                   admin
  POST /api/admin/academy/sim/reload                   admin

Admission, in order: the request must come from our own origin (the page is
served on the API origin, so a re-hosted or saved copy shows another
origin or none); the learner cookie must resolve; the lesson must be one
the learner can open now; the `copy` token must be a live delivery issued
to this learner (so withdrawing a copy in the Integrity tab also ends its
simulator); and the session caps must have room. Refusals close the socket
with a 44xx code and a sentence the client shows.

Protocol (JSON text frames):

  client -> server
    {op:"new",  id, key, shaft, limitSet}     a fresh engine (Reset / boot)
    {op:"set",  id, path:[...], value}        whitelisted property write
    {op:"del",  id, path:[...]}               delete a nested key
    {op:"call", id, fn, args:[...]}           setBlend | resetTrip | log
    {op:"prime", id}                          first frame if none yet
    {op:"step", id, n}                        advance n seconds, reply frames
    {op:"run", speed} / {op:"stop"} / {op:"speed", speed}
    {op:"want", margin:true|false}            include margin report in ticks
    {op:"ping"}
  server -> client
    {op:"hello", session, consts, tick_s, max_speed}
    {op:"reply", id, ...}                     answer to an id'd request
    {op:"frames", frames:[...], state:{...}}  one tick of a running engine
    {op:"error", id?, message}
    {op:"bye", reason}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import academy as svc
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import require_admin
from ..learner_auth import LEARNER_COOKIE_NAME, verify_learner_token
from ..models import AssetDelivery, Learner, Lesson
from ..sim_runtime import EngineUnavailable, SimSession, host

log = logging.getLogger(__name__)

router = APIRouter(tags=["academy-sim"])

# Close codes (4000-4999 are application-defined).
CLOSE_ORIGIN = 4403
CLOSE_AUTH = 4401
CLOSE_ACCESS = 4403
CLOSE_COPY = 4410
CLOSE_FULL = 4429
CLOSE_IDLE = 4408
CLOSE_ENGINE = 4503


def _same_origin(ws: WebSocket) -> bool:
    origin = (ws.headers.get("origin") or "").rstrip("/").lower()
    host_hdr = (ws.headers.get("host") or "").lower()
    if not origin or origin == "null" or not host_hdr:
        return False
    scheme_host = origin.split("://", 1)
    return len(scheme_host) == 2 and scheme_host[1] == host_hdr


def _admit(ws: WebSocket, lesson_id: int, copy: str) -> tuple[Learner, Lesson, AssetDelivery] | tuple[int, str]:
    """Everything that must be true before an engine is spent on a socket."""
    settings = get_settings()
    if not _same_origin(ws):
        return CLOSE_ORIGIN, "The simulator runs only from proreadyengineer.com. Launch it from your course page."
    token = ws.cookies.get(LEARNER_COOKIE_NAME, "")
    learner_id = verify_learner_token(token) if token else None
    if learner_id is None:
        return CLOSE_AUTH, "Your sign-in has expired. Sign in on proreadyengineer.com and launch the simulator again."
    db = SessionLocal()
    try:
        learner = db.get(Learner, learner_id)
        if learner is None or learner.status != "active":
            return CLOSE_AUTH, "Your sign-in has expired. Sign in on proreadyengineer.com and launch the simulator again."
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return CLOSE_ACCESS, "This simulator is no longer available."
        ok, _reason = svc.lesson_accessible(db, learner, lesson)
        if not ok:
            return CLOSE_ACCESS, "Your access to this material has ended."
        delivery = db.execute(
            select(AssetDelivery).where(AssetDelivery.token == (copy or "")[:32])
        ).scalar_one_or_none()
        if delivery is None or delivery.learner_id != learner.id or delivery.lesson_id != lesson.id:
            return CLOSE_COPY, "This copy is not licensed to your account. Launch the simulator from your course page."
        if delivery.revoked_at is not None:
            return CLOSE_COPY, "This copy has been withdrawn by the instructor. Launch a fresh one from your course page."
        served = delivery.served_at
        if served is not None and served.tzinfo is None:
            served = served.replace(tzinfo=timezone.utc)
        if served is not None and datetime.now(timezone.utc) - served > timedelta(hours=settings.ASSET_COPY_TTL_HOURS):
            return CLOSE_COPY, "This copy has expired. Launch a fresh one from your course page."
        # Caps. Owners get a little more room: the instructor demonstrates
        # on several screens.
        per = settings.SIM_MAX_PER_LEARNER * (2 if svc.is_owner(learner) else 1)
        if host.count_for(learner.id) >= per:
            return CLOSE_FULL, "The simulator is already open in another window on your account. Close it and try again."
        if len(host.sessions) >= settings.SIM_MAX_SESSIONS:
            return CLOSE_FULL, "The simulator is busy right now. Try again in a few minutes."
        db.expunge(learner)
        db.expunge(lesson)
        db.expunge(delivery)
        return learner, lesson, delivery
    finally:
        db.close()


async def _refuse(ws: WebSocket, code: int, reason: str) -> None:
    try:
        await ws.accept()
        await ws.send_text(json.dumps({"op": "bye", "code": code, "reason": reason}))
        await ws.close(code=code, reason=reason[:120])
    except Exception:  # pragma: no cover
        pass


@router.websocket("/api/academy/sim/ws")
async def sim_ws(websocket: WebSocket, lesson: int = 0, copy: str = "") -> None:
    settings = get_settings()
    admitted = await asyncio.to_thread(_admit, websocket, int(lesson), copy)
    if isinstance(admitted[0], int):
        code, reason = admitted  # type: ignore[misc]
        log.warning("SIM refused %s lesson=%s copy=%s: %s", code, lesson, (copy or "")[:8], reason)
        await _refuse(websocket, code, reason)
        return
    learner, lesson_row, delivery = admitted  # type: ignore[misc]

    try:
        db = SessionLocal()
        try:
            await host.ensure_engine(db)
        finally:
            db.close()
    except EngineUnavailable as exc:
        log.error("SIM engine unavailable: %s", exc)
        await _refuse(websocket, CLOSE_ENGINE, "The simulator engine is being updated. Try again in a few minutes.")
        return

    await websocket.accept()
    # _serve records its session here the moment it exists, so a disconnect
    # raised from anywhere inside still ends in host.drop().
    holder: dict[str, SimSession] = {}
    try:
        consts = await host.consts(host.ctx)
        # The engine is created on the client's "new"; until then the socket
        # is just a greeting so the UI can build its constants.
        await websocket.send_text(json.dumps({
            "op": "hello", "consts": consts,
            "tick_s": settings.SIM_TICK_SECONDS, "max_speed": settings.SIM_MAX_SPEED,
            "licensed_to": learner.email,
        }))
        await _serve(websocket, learner, lesson_row, delivery, holder)
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        # uvicorn's "send/receive after close": the client is simply gone
        log.info("SIM socket gone for %s: %s", learner.email, str(exc)[:100])
    except Exception:  # pragma: no cover
        log.exception("SIM session error for %s", learner.email)
    finally:
        session = holder.get("session")
        if session is not None:
            await host.drop(session)
            log.info("SIM session ended for %s (%d ops)", learner.email, session.ops)


async def _serve(ws: WebSocket, learner: Learner, lesson: Lesson, delivery: AssetDelivery,
                 holder: dict) -> None:
    settings = get_settings()
    session: SimSession | None = None
    # A simple token bucket for control messages.
    bucket = float(settings.SIM_OPS_PER_SECOND)
    bucket_at = time.monotonic()

    async def reply(msg_id, **payload) -> None:
        await ws.send_text(json.dumps({"op": "reply", "id": msg_id, **payload}))

    async def error(msg_id, message: str) -> None:
        await ws.send_text(json.dumps({"op": "error", "id": msg_id, "message": message[:300]}))

    while True:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
        except WebSocketDisconnect:
            log.info("SIM client disconnected (%s)", learner.email)
            return
        except RuntimeError as exc:
            # uvicorn raises this when the socket is gone under us
            log.info("SIM receive after close (%s): %s", learner.email, str(exc)[:120])
            return
        except asyncio.TimeoutError:
            if session is not None and not session.running and \
                    time.time() - session.last_seen > settings.SIM_IDLE_SECONDS:
                await ws.send_text(json.dumps({"op": "bye", "code": CLOSE_IDLE,
                                               "reason": "Closed after a long idle. Launch again from your course page."}))
                await ws.close(code=CLOSE_IDLE)
                return
            continue

        # rate limit
        now = time.monotonic()
        bucket = min(float(settings.SIM_OPS_PER_SECOND), bucket + (now - bucket_at) * settings.SIM_OPS_PER_SECOND)
        bucket_at = now
        if bucket < 1.0:
            await asyncio.sleep(0.1)
            continue
        bucket -= 1.0

        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue
        op = msg.get("op")
        mid = msg.get("id")
        if session is not None:
            session.last_seen = time.time()
            session.ops += 1

        try:
            if op == "ping":
                await ws.send_text(json.dumps({"op": "pong", "id": mid}))

            elif op == "new":
                key = str(msg.get("key", "9FA"))[:8]
                shaft = str(msg.get("shaft", "multi"))[:8]
                limit_set = str(msg.get("limitSet", "tuning"))[:8]
                if session is None:
                    session, out = await host.create(
                        learner_id=learner.id, learner_email=learner.email,
                        lesson_id=lesson.id, copy_token=delivery.token,
                        key=key, shaft=shaft, limit_set=limit_set,
                    )
                    holder["session"] = session
                else:
                    await _stop(session)
                    out = await host.rebuild(session, key=key, shaft=shaft, limit_set=limit_set)
                await reply(mid, deck=out["deck"], state=out["state"])

            elif session is None:
                await error(mid, "Create an engine first.")

            elif op == "set":
                path = msg.get("path")
                if not isinstance(path, list) or not path or len(path) > 3:
                    await error(mid, "bad path")
                    continue
                st = await host.set(session, [str(p)[:32] for p in path], msg.get("value"))
                await reply(mid, state=st)

            elif op == "del":
                path = msg.get("path")
                if not isinstance(path, list) or len(path) < 2 or len(path) > 3:
                    await error(mid, "bad path")
                    continue
                st = await host.delete(session, [str(p)[:32] for p in path])
                await reply(mid, state=st)

            elif op == "call":
                fn = str(msg.get("fn", ""))[:16]
                args = msg.get("args") or []
                if not isinstance(args, list) or len(args) > 4:
                    await error(mid, "bad args")
                    continue
                st = await host.call(session, fn, args)
                await reply(mid, state=st)

            elif op == "prime":
                st = await host.prime(session)
                await reply(mid, state=st)

            elif op == "step":
                n = int(msg.get("n", 1) or 1)
                out = await host.tick(session, n, _want_margin(session))
                await ws.send_text('{"op":"reply","id":%s,' % json.dumps(mid) + out[1:])

            elif op == "run":
                session.speed = max(1, min(settings.SIM_MAX_SPEED, int(msg.get("speed", session.speed) or 4)))
                if not session.running:
                    session.running = True
                    session.run_task = asyncio.create_task(_run_loop(ws, session))
                await reply(mid, running=True, speed=session.speed)

            elif op == "stop":
                await _stop(session)
                await reply(mid, running=False)

            elif op == "speed":
                session.speed = max(1, min(settings.SIM_MAX_SPEED, int(msg.get("speed", 4) or 4)))
                await reply(mid, speed=session.speed)

            elif op == "want":
                session.want_margin_until = (time.time() + 3600) if msg.get("margin") else 0.0
                await reply(mid, ok=True)

            else:
                await error(mid, f"unknown op {op!r}")
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            # A refused write or a JS error must not end the session.
            log.info("SIM op %s failed for %s: %s", op, learner.email, str(exc)[:200])
            await error(mid, _clean_js_error(str(exc)))


def _want_margin(session: SimSession) -> bool:
    return session.want_margin_until > time.time()


def _clean_js_error(text: str) -> str:
    # "<anonymous>:1: Error: not settable: foo\n..." -> "not settable: foo"
    line = text.splitlines()[0] if text else "error"
    if "Error: " in line:
        line = line.split("Error: ", 1)[1]
    return line[:200]


async def _stop(session: SimSession) -> None:
    session.running = False
    task, session.run_task = session.run_task, None
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def _run_loop(ws: WebSocket, session: SimSession) -> None:
    """Tick at a fixed cadence while the engine is running. The client
    renders each batch as it arrives; if the client falls behind, sending
    blocks and the cadence stretches rather than piling up frames."""
    tick = get_settings().SIM_TICK_SECONDS
    loop = asyncio.get_running_loop()
    try:
        # Wait first, like the browser build's setInterval did: Run then
        # Pause inside one interval produces no frame in either build.
        next_at = loop.time() + tick
        while session.running:
            await asyncio.sleep(max(0.0, next_at - loop.time()))
            if not session.running:
                break
            next_at += tick
            out = await host.tick(session, session.speed, _want_margin(session))
            await ws.send_text('{"op":"frames",' + out[1:])
            if loop.time() > next_at + tick:   # fell far behind (slow client): resync
                next_at = loop.time() + tick
    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        session.running = False
    except Exception:  # pragma: no cover
        log.exception("SIM run loop died for %s", session.learner_email)
        session.running = False


# ---------------------------------------------------------------- admin --

admin_router = APIRouter(prefix="/api/admin/academy/sim", tags=["academy-sim-admin"])


@admin_router.get("/status")
def sim_status(_: str = Depends(require_admin)) -> dict:
    return host.status()


@admin_router.post("/reload")
async def sim_reload(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    """Pick up a newly uploaded engine blob. Running sessions keep the old
    engine until they end; new sessions get the new one."""
    try:
        await host.ensure_engine(db, force=True)
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"ok": True, "engine_sha": host.sha[:12]}
