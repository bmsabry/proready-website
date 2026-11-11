"""Shared fakes and fixtures for the public-assistant tests (test_chat_*.py).

Nothing here reaches a network:

  * The model is replaced at the one seam the app uses (chat.call_model) by
    FakeModel, which records the messages it was given and answers from a
    list. The one test of the real call_model replaces httpx.Client instead.
  * The website reader (site_content) is given its pages directly, so it
    never fetches anything.
  * `no_network` (autouse) makes any socket connection or DNS lookup fail the
    test that tried it.

The clock of the assistant is chat.utcnow; the `clock` fixture pins it to
1 March 2032, 12:00 UTC, far from any date another test module uses.
"""
from __future__ import annotations

import re
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import conftest  # noqa: F401,E402  (sets the environment before app.main is imported)
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app import chat  # noqa: E402
from app import crypto  # noqa: E402
from app import site_content  # noqa: E402
from app.chat_models import (  # noqa: E402
    ChatBan,
    ChatConversation,
    ChatEvent,
    ChatMessage,
    ChatSettings,
    ChatUsageDaily,
)
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AISettings  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
API = "/api/chat"
ADMIN_API = "/api/admin/chat"
NOW = datetime(2032, 3, 1, 12, 0, tzinfo=timezone.utc)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTES_TS = REPO_ROOT / "src" / "routes.ts"

MENU = "Home Services Products Training Insights Case Studies Testimonials Contact Book a call Sign In "
FOOTER = " Expertise Company Start a Conversation Get in touch All rights reserved. combustion industrial AI training"

# Paths that must never reach the model, whatever lists them.
PRIVATE_PATHS = [
    "/admin",
    "/admin/login",
    "/learn",
    "/learn/micro-gas-turbine-design",
    "/verify/ABC123",
    "/consult/booking/C-TEST1234",
]
PRIVATE_MARKER = "PRIVATE-MARKER-9Q"


def public_route_paths() -> list[str]:
    """The paths in src/routes.ts: what the site build prerenders and lists
    in sitemap.xml."""
    text = ROUTES_TS.read_text(encoding="utf-8")
    return re.findall(r"\{\s*path:\s*'([^']+)'", text)


def fake_site_pages(extra: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    """One page per public route, each with a body nobody else has, plus the
    private paths (which the assistant must drop)."""
    pages: dict[str, dict[str, str]] = {}
    for path in public_route_paths():
        slug = path.strip("/").replace("/", " ").replace("-", " ") or "home"
        body = f"This page is about {slug}. Unique body text for {path}."
        if path == "/training/micro-gas-turbine-design":
            body += " The on-demand course costs $1,495 and has seven modules."
        if path == "/insights/transitioning-dle-combustion-systems-to-100-hydrogen":
            body += " Hydrogen raises flame speed and flashback risk in lean premixed combustors."
        pages[path] = {"title": f"Title of {path}", "text": MENU + body + FOOTER}
    for path in PRIVATE_PATHS:
        pages[path] = {
            "title": f"Private {path}",
            "text": MENU + f"{PRIVATE_MARKER} hydrogen secret learner admin data for {path}." + FOOTER,
        }
    for path, body in (extra or {}).items():
        pages[path] = {"title": f"Title of {path}", "text": MENU + body + FOOTER}
    return pages


class FakeModel:
    """Stands in for chat.call_model."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.replies: list[object] = []
        self.default = "Lean premixed flames trade NOx against stability. For your unit, book a call at /consult."
        self.tokens = (900, 120)

    def __call__(self, db, messages):
        self.calls.append(messages)
        nxt = self.replies.pop(0) if self.replies else self.default
        if isinstance(nxt, Exception):
            raise nxt
        if isinstance(nxt, chat.ModelReply):
            return nxt
        return chat.ModelReply(text=str(nxt), tokens_in=self.tokens[0], tokens_out=self.tokens[1], model="fake-model")

    @property
    def system(self) -> str:
        """The system message of the last call."""
        return self.calls[-1][0]["content"]


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float = 0, **kw) -> datetime:
        self.now = self.now + timedelta(seconds=seconds, **kw)
        return self.now


def _wipe() -> None:
    with SessionLocal() as db:
        for model in (ChatMessage, ChatConversation, ChatEvent, ChatBan, ChatUsageDaily, ChatSettings):
            db.query(model).delete()
        db.commit()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A test that reaches for the network fails instead of quietly passing."""

    def refuse(name):
        def _refuse(*args, **kwargs):
            raise AssertionError(f"network use in a chat test: {name} {args[1:2]}")

        return _refuse

    monkeypatch.setattr(socket.socket, "connect", refuse("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("connect_ex"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))


@pytest.fixture(autouse=True)
def clean():
    _wipe()
    chat.BURST.reset()
    chat.reset_site_cache()
    yield
    _wipe()
    chat.BURST.reset()
    chat.reset_site_cache()


@pytest.fixture
def clock(monkeypatch) -> Clock:
    c = Clock(NOW)
    monkeypatch.setattr(chat, "utcnow", c)
    return c


@pytest.fixture
def site(monkeypatch):
    """The website, as the reader would have fetched it. Returns the dict so
    a test can add or change pages before the first question."""
    pages = fake_site_pages()
    monkeypatch.setitem(site_content._cache, "pages", pages)
    monkeypatch.setitem(site_content._cache, "order", list(pages))
    monkeypatch.setitem(site_content._cache, "fetched_at", time.time())
    return pages


@pytest.fixture
def switched_on():
    """The assistant ships switched off; most tests need it on."""
    with SessionLocal() as db:
        chat.get_chat_settings(db).enabled = True
        db.commit()


@pytest.fixture
def fake_model(monkeypatch) -> FakeModel:
    """The model seam replaced, the assistant left as it ships (off)."""
    fake = FakeModel()
    monkeypatch.setattr(chat, "call_model", fake)
    monkeypatch.setattr(chat, "ai_configured", lambda db: True)
    return fake


@pytest.fixture
def model(fake_model, switched_on) -> FakeModel:
    """The model seam replaced and the assistant switched on."""
    return fake_model


# ---- the real provider call, against a fake HTTP client --------------------------

FERNET_KEY = "u5Ml1_hZ8b7cQvVQ0M6RH8HRlqYRIbNJ0lWfR0dO5vE="


@pytest.fixture
def ai_connection(monkeypatch):
    """The site's one AI connection, as Admin -> AI Settings would save it."""
    monkeypatch.setenv("AI_SETTINGS_KEY", FERNET_KEY)
    crypto._fernet.cache_clear()
    with SessionLocal() as db:
        row = db.execute(select(AISettings).where(AISettings.scope == "assistant")).scalar_one_or_none()
        created = row is None
        if created:
            row = AISettings(scope="assistant")
            db.add(row)
        before = (row.api_url, row.api_key_encrypted, row.model_name)
        row.api_url = "https://llm.invalid/v1"
        row.api_key_encrypted = crypto.encrypt("test-key-abc")
        row.model_name = "test-model-1"
        db.commit()
        yield row
        if created:
            db.delete(row)
        else:
            row.api_url, row.api_key_encrypted, row.model_name = before
        db.commit()
    monkeypatch.undo()
    crypto._fernet.cache_clear()


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeHttp:
    """Stands in for httpx.Client inside chat.call_model."""

    sent: list = []
    answer: object = None

    def __init__(self, *a, **kw):
        FakeHttp.timeout = kw.get("timeout")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        FakeHttp.sent.append({"url": url, "json": json, "headers": headers})
        if isinstance(FakeHttp.answer, Exception):
            raise FakeHttp.answer
        return FakeHttp.answer


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def new_client() -> TestClient:
    """A browser with no cookies."""
    return TestClient(app, base_url="https://testserver")


def ask(client: TestClient, text: str, *, ip: str = "203.0.113.10", conversation: str = "", **kw):
    """POST one message as a visitor at `ip`."""
    body = {"message": text}
    if conversation:
        body["conversation_id"] = conversation
    headers = {"X-Forwarded-For": ip, "User-Agent": "pytest-browser/1.0", **kw.pop("headers", {})}
    return client.post(API, json=body, headers=headers, **kw)


def status(client: TestClient, *, ip: str = "203.0.113.10"):
    return client.get(f"{API}/status", headers={"X-Forwarded-For": ip})
