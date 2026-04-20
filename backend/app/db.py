"""Database engine + session factory.

SQLAlchemy 2.x declarative base. `DATABASE_URL` controls the dialect —
sqlite:// for local dev, postgresql+psycopg:// in Render production.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# For SQLite we need check_same_thread=False; harmless on Postgres.
connect_args = (
    {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    settings.DATABASE_URL,
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
