"""Tables of the public AI assistant (2026-11).

Six tables, all new (create_all builds them complete; a column added to any
of them in a LATER release needs an `_ensure_column` line in main.py):

  chat_settings       one row (id 1): on/off, daily limit, spend cap, ban length,
                      how long conversations are kept
  chat_conversations  one row per conversation a visitor opens
  chat_messages       every message of it, the visitor's and the assistant's
  chat_events         append-only log of every abuse decision, with its reason
  chat_bans           who is shut out, why, until when, and who lifted it
  chat_usage_daily    model spend per UTC day, for the assistant's own cap

A visitor is never stored as an address. `visitor_id` is the random id inside
the signed cookie; `ip_hash` is a keyed hash of the address (see
chat.hash_ip), kept so that limits and bans survive a cleared cookie.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ChatSettings(Base):
    """Admin-editable rules of the public assistant: one row (id 1)."""

    __tablename__ = "chat_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Off until the owner switches it on (Admin -> Site Assistant): nothing
    # answers the public and the widget is not drawn.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Messages one visitor may send in any 24 hours.
    daily_limit: Mapped[int] = mapped_column(Integer, default=10)
    # The assistant's own daily model budget, in millionths of a dollar.
    spend_cap_micro_usd: Mapped[int] = mapped_column(Integer, default=3_000_000)
    # How long an automatic ban lasts.
    ban_days: Mapped[int] = mapped_column(Integer, default=30)
    # Conversations and their messages are deleted this many days after they
    # were written. The widget's disclosure states this number.
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    # When old records were last deleted (chat.maybe_purge: once a day).
    last_purge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # What the browser holds to continue the conversation. Random, and only
    # honoured for the visitor (cookie id or address hash) who started it.
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    visitor_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    ip_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    # The page the visitor was on when they first wrote (a site path).
    page_path: Mapped[str] = mapped_column(String(300), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    # True once anything in it was refused, blocked or counted as abuse.
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # The owner trying the assistant from the admin screen: no visitor, no
    # address, counted against nobody's allowance.
    admin_test: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_email: Mapped[str] = mapped_column(String(320), default="")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(16))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    visitor_id: Mapped[str] = mapped_column(String(32), default="")
    ip_hash: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    # A visitor's message that used up one of the day's allowance.
    counted: Mapped[bool] = mapped_column(Boolean, default=False)
    # What this message was: see chat.KINDS.
    kind: Mapped[str] = mapped_column(String(24), default="")
    # The model's own words when a check replaced them (price, instructions).
    blocked_text: Mapped[str] = mapped_column(Text, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_micro: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(200), default="")

    __table_args__ = (
        Index("ix_chat_messages_visitor_time", "visitor_id", "created_at"),
        Index("ix_chat_messages_ip_time", "ip_hash", "created_at"),
    )


class ChatEvent(Base):
    """One abuse decision or refusal, with the reason. Rows are only added."""

    __tablename__ = "chat_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # See chat.EVENT_LABELS.
    kind: Mapped[str] = mapped_column(String(32), index=True)
    visitor_id: Mapped[str] = mapped_column(String(32), default="")
    ip_hash: Mapped[str] = mapped_column(String(64), default="")
    conversation_id: Mapped[int | None] = mapped_column(Integer, default=None)
    detail: Mapped[str] = mapped_column(String(600), default="")

    __table_args__ = (
        Index("ix_chat_events_visitor_kind", "visitor_id", "kind", "at"),
        Index("ix_chat_events_ip_kind", "ip_hash", "kind", "at"),
    )


class ChatBan(Base):
    """A visitor shut out of the assistant: by cookie id AND by address hash."""

    __tablename__ = "chat_bans"

    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    ip_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    # 'injection' | 'abuse' | 'over_limit' | 'burst'
    reason: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[str] = mapped_column(String(600), default="")
    conversation_id: Mapped[int | None] = mapped_column(Integer, default=None)
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    lifted_by: Mapped[str] = mapped_column(String(320), default="")
    # Requests refused while the ban stood (not logged one by one).
    refused_count: Mapped[int] = mapped_column(Integer, default=0)
    last_refused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ChatUsageDaily(Base):
    """The public assistant's model spend per UTC day.

    Kept apart from ai_usage_daily (the admin assistant's): the two have
    separate caps, and visitors must not be able to use up the owner's own.
    Costs use the same conservative estimate (app/ai_pricing.py).
    """

    __tablename__ = "chat_usage_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_micro: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
