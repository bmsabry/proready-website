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

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a session, closes it on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
