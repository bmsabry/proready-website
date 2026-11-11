"""The public AI assistant: its public API and its admin API.

Public, no sign-in:

  GET  /api/chat/status   what the widget shows when it opens (no cookie set)
  POST /api/chat          one visitor message -> one reply

Every conversational outcome answers 200 with a `status` field (ok, limit,
banned, unavailable, disabled, error) and the sentence to show, so the widget
never has to interpret an HTTP error. 422 is for an empty or over-long
message, 403 for a request another website made a visitor's browser send.

Admin (cookie session or bearer token):

  GET/PUT /api/admin/chat/settings
  POST    /api/admin/chat/try                    the owner's own test message
  GET     /api/admin/chat/conversations?q=&flagged=&limit=&offset=
  GET     /api/admin/chat/conversations/{id}
  GET     /api/admin/chat/bans?active=
  POST    /api/admin/chat/bans/{id}/unban
  GET     /api/admin/chat/events?limit=

The rules are in app/chat.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from .. import chat
from ..activity import client_ip
from ..chat_models import ChatBan, ChatConversation, ChatEvent, ChatMessage
from ..db import get_db
from ..deps import require_admin
from ..origin_guard import origin_is_ours

log = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/chat", tags=["chat"])
admin_router = APIRouter(
    prefix="/api/admin/chat", tags=["chat-admin"], dependencies=[Depends(require_admin)]
)


def _ip(request: Request) -> str:
    """The visitor's address. Cloudflare's own header first (it overwrites
    whatever a client sends under that name), then the helper the rest of
    the API uses."""
    direct = (request.headers.get("cf-connecting-ip") or "").strip()[:64]
    return direct or client_ip(request.headers, request.client.host if request.client else "")


def _no_store(payload: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

@public_router.get("/status")
def status(
    request: Request,
    chat_visitor: str = Cookie(default=""),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Is the assistant on, and how many messages does this visitor have left.

    Reads the cookie if there is one and never sets it: a visitor who has
    not written to the assistant gets no cookie from it.
    """
    return _no_store(
        chat.status_for(
            db, visitor_id=chat.read_visitor(chat_visitor), ip_hash=chat.hash_ip(_ip(request))
        )
    )


class ChatIn(BaseModel):
    # The real cap (chat.MAX_MESSAGE_CHARS) is checked in chat.py so that it
    # answers with a sentence; this one only stops absurd bodies early.
    message: str = Field(max_length=8000)
    conversation_id: str = Field(default="", max_length=64)
    page: str = Field(default="", max_length=300)


@public_router.post("")
def send(
    body: ChatIn,
    request: Request,
    chat_visitor: str = Cookie(default=""),
    db: Session = Depends(get_db),
) -> JSONResponse:
    ip_hash = chat.hash_ip(_ip(request))
    visitor_id = chat.read_visitor(chat_visitor)

    # A page on another site can make a visitor's browser post here with the
    # visitor's cookie and address, and so spend their messages or get them
    # banned. Browsers name the sending site in Origin; ours only.
    origin = request.headers.get("origin")
    if origin and not origin_is_ours(origin, request.headers.get("host", "")):
        log.info("[chat] refused a request sent from %s", origin[:200])
        raise HTTPException(status_code=403, detail="This request came from another website and was refused.")

    fresh_cookie = not visitor_id
    if fresh_cookie:
        visitor_id = chat.new_visitor_id()

    outcome = chat.handle_message(
        db,
        message=body.message,
        visitor_id=visitor_id,
        ip_hash=ip_hash,
        user_agent=request.headers.get("user-agent", ""),
        conversation_id=body.conversation_id,
        page_path=body.page,
    )
    if outcome.status == "rejected":
        raise HTTPException(status_code=422, detail=outcome.reply)

    response = _no_store(outcome.out())
    if fresh_cookie and outcome.status != "disabled":
        # Same attributes as the site's other cookies (the API is on the
        # site's own domain; previews are cross-site), but scoped to the
        # assistant's own path: no other endpoint ever receives it.
        response.set_cookie(
            key=chat.COOKIE_NAME,
            value=chat.sign_visitor(visitor_id),
            max_age=chat.COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="none",
            path=chat.COOKIE_PATH,
        )
    return response


# -----------------------------------------------------------------------------
# Admin
# -----------------------------------------------------------------------------

@admin_router.get("/settings")
def get_settings_endpoint(db: Session = Depends(get_db)) -> dict:
    chat.maybe_purge(db, chat.utcnow())
    return chat.settings_out(db)


class SettingsIn(BaseModel):
    enabled: Optional[bool] = None
    daily_limit: Optional[int] = Field(default=None, ge=1, le=200)
    spend_cap_cents: Optional[int] = Field(default=None, ge=0, le=90_000)
    ban_days: Optional[int] = Field(default=None, ge=1, le=3650)
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)


@admin_router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)) -> dict:
    row = chat.get_chat_settings(db)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.daily_limit is not None:
        row.daily_limit = body.daily_limit
    if body.spend_cap_cents is not None:
        row.spend_cap_micro_usd = body.spend_cap_cents * 10_000
    if body.ban_days is not None:
        row.ban_days = body.ban_days
    if body.retention_days is not None:
        row.retention_days = body.retention_days
    db.commit()
    return chat.settings_out(db)


class TryIn(BaseModel):
    message: str = Field(max_length=8000)
    conversation_id: str = Field(default="", max_length=64)


@admin_router.post("/try")
def try_it(body: TryIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)) -> dict:
    """The owner's own message through the reply pipeline (chat.admin_try).
    Works while the assistant is switched off; counted against no visitor."""
    try:
        return chat.admin_try(db, message=body.message, admin=admin, conversation_id=body.conversation_id)
    except chat.TryRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin_router.get("/conversations")
def list_conversations(
    q: str = "",
    flagged: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    chat.maybe_purge(db, chat.utcnow())
    query = select(ChatConversation)
    count = select(func.count()).select_from(ChatConversation)
    conds = []
    if flagged:
        conds.append(ChatConversation.flagged.is_(True))
    needle = q.strip()
    if needle:
        like = f"%{needle.lower()}%"
        in_messages = select(ChatMessage.conversation_id).where(func.lower(ChatMessage.content).like(like))
        conds.append(
            or_(
                ChatConversation.id.in_(in_messages),
                ChatConversation.visitor_id.like(f"{needle.lower()}%"),
                ChatConversation.ip_hash.like(f"{needle.lower()}%"),
            )
        )
    for c in conds:
        query, count = query.where(c), count.where(c)
    rows = db.execute(
        query.order_by(desc(ChatConversation.last_message_at), desc(ChatConversation.id))
        .limit(limit)
        .offset(offset)
    ).scalars()
    return {
        "total": int(db.execute(count).scalar() or 0),
        "conversations": [chat.conversation_out(db, c) for c in rows],
    }


@admin_router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ChatConversation, conversation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return chat.conversation_out(db, row, full=True)


@admin_router.get("/bans")
def list_bans(active: bool = False, db: Session = Depends(get_db)) -> dict:
    now = chat.utcnow()
    query = select(ChatBan).order_by(desc(ChatBan.id)).limit(500)
    if active:
        query = query.where(ChatBan.lifted_at.is_(None), ChatBan.expires_at > now)
    return {"bans": [chat.ban_out(b, now) for b in db.execute(query).scalars()]}


@admin_router.post("/bans/{ban_id}/unban")
def unban(ban_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)) -> dict:
    row = db.get(ChatBan, ban_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ban not found.")
    return chat.ban_out(chat.lift_ban(db, row, by=admin))


@admin_router.get("/events")
def list_events(
    limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)
) -> dict:
    rows = db.execute(select(ChatEvent).order_by(desc(ChatEvent.id)).limit(limit)).scalars()
    return {"events": [chat.event_out(e) for e in rows]}
