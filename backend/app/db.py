"""Database engine + session factory.

SQLAlchemy 2.x declarative base. `DATABASE_URL` controls the dialect —
sqlite:// for local dev, postgresql+psycopg:// in Render production.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


def _normalize_db_url(url: str) -> str:
    """Force the psycopg3 dialect for Postgres URLs.

    Render provides `postgresql://...`, which SQLAlchemy resolves to the
    psycopg2 driver by default. We ship `psycopg[binary]` (v3) instead, so
    we rewrite the scheme to `postgresql+psycopg://` to pick up psycopg3.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


db_url = _normalize_db_url(settings.DATABASE_URL)

# For SQLite we need check_same_thread=False; harmless on Postgres.
connect_args = (
    {"check_same_thread": False} if db_url.startswith("sqlite") else {}
)

# Pool sized to the request threadpool (Starlette runs sync endpoints on 40
# threads), so a burst of parallel requests waits on a thread, never on a
# connection — which holds only because dependencies release their
# connection before returning (see release_connection below). The default
# 5 + 10 overflow was exhausted by one learner's slide-thumbnail strip
# (≈40 simultaneous image requests over HTTP/2) and answered the rest with
# 500s (2026-09-03). Render's Basic Postgres allows ~100 connections; one
# web instance uses at most 40 of them.
pool_kwargs = (
    {}
    if db_url.startswith("sqlite")
    else {"pool_size": 10, "max_overflow": 30, "pool_timeout": 30, "pool_recycle": 1800}
)

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
    **pool_kwargs,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def release_connection(db: Session) -> None:
    """Hand the session's pooled connection back without expiring what it
    has loaded. Never raises.

    FastAPI runs each sync dependency and then the endpoint as separate hops
    on one shared pool of 40 threads. A dependency that has queried keeps its
    connection checked out while its request queues for the next hop, so a
    burst of requests (one browser opening a deck's thumbnail strip, ~90
    images) can leave every thread waiting for a connection that is held by
    a request waiting for a thread. Nothing moves until pool_timeout, the
    whole API stalls for 30 s and the waiters fail with 500s (production,
    2026-09-16 to -19). Dependencies that query call this before returning,
    so a request holds a connection only while one of its own hops runs.
    """
    prev = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    except Exception:  # pragma: no cover — auth must not fail on this
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.expire_on_commit = prev


def get_db():
    """FastAPI dependency — yields a session, closes it on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
