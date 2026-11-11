"""Public assistant: who may ask, and how often.

The daily allowance by cookie and by address (the higher count applies), the
message-length cap, the switched-off state, the visitor cookie, and requests
another website makes a visitor's browser send.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from chat_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    API,
    NOW,
    ask,
    clean,
    client,
    clock,
    db,
    fake_model,
    model,
    new_client,
    no_network,
    site,
    status,
    switched_on,
)

from app import chat
from app.chat_models import ChatConversation, ChatEvent, ChatMessage, ChatSettings


def _send_spaced(client, clock, n, **kw):
    """n messages, 20 s apart (a person, not a script)."""
    out = []
    for i in range(n):
        clock.tick(20)
        out.append(ask(client, f"What limits lean blowout, question {i}?", **kw))
    return out


# -----------------------------------------------------------------------------
# The routes are really on the app, and the answer has the agreed shape
# -----------------------------------------------------------------------------

def test_the_assistant_is_mounted_on_the_app():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/api/chat", "/api/chat/status", "/api/admin/chat/settings",
            "/api/admin/chat/conversations", "/api/admin/chat/bans",
            "/api/admin/chat/bans/{ban_id}/unban", "/api/admin/chat/events"} <= paths


def test_a_question_is_answered_and_the_shape_is_stable(client, clock, site, model):
    r = ask(client, "What limits lean blowout in a DLE combustor?")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "reply", "conversation_id", "remaining", "limit", "book_url"}
    assert body["status"] == "ok"
    assert body["reply"] == model.default
    assert body["limit"] == 10 and body["remaining"] == 9
    assert body["book_url"] == "/consult"
    assert len(body["conversation_id"]) == 32
    assert r.headers["cache-control"] == "no-store"
    assert len(model.calls) == 1


def test_defaults_are_off_ten_a_day_three_dollars_thirty_days_ninety_days_kept(client, db):
    s = client.get(f"{ADMIN_API}/settings", headers=ADMIN).json()
    assert (s["enabled"], s["daily_limit"], s["spend_cap_cents"], s["ban_days"], s["retention_days"]) == (
        False, 10, 300, 30, 90,
    )
    row = db.get(ChatSettings, 1)
    assert row.enabled is False and row.spend_cap_micro_usd == 3_000_000


def test_it_ships_switched_off_and_nothing_answers_the_public(client, clock, site, fake_model, db):
    """Straight after deploy, with a model configured and nobody having
    touched the settings: no answer, no cookie, nothing stored, no model call."""
    s = status(client).json()
    assert s["enabled"] is False and s["status"] == "disabled" and s["message"] == chat.MSG_DISABLED
    r = ask(client, "What limits lean blowout?")
    assert r.status_code == 200
    assert r.json()["status"] == "disabled" and r.json()["reply"] == chat.MSG_DISABLED
    assert "set-cookie" not in r.headers
    assert fake_model.calls == []
    assert db.execute(select(ChatMessage)).first() is None
    assert db.execute(select(ChatConversation)).first() is None
    assert db.execute(select(ChatEvent)).first() is None
    # The owner switches it on in Admin -> Site Assistant; then it answers.
    assert client.put(f"{ADMIN_API}/settings", json={"enabled": True}, headers=ADMIN).json()["enabled"] is True
    clock.tick(20)
    assert status(client).json()["status"] == "ok"
    assert ask(client, "What limits lean blowout?").json()["status"] == "ok"


# -----------------------------------------------------------------------------
# The cookie
# -----------------------------------------------------------------------------

def test_the_visitor_cookie_is_signed_httponly_and_scoped_to_the_assistant(client, clock, site, model):
    r = ask(client, "What is a pilot flame for?")
    cookie = r.headers["set-cookie"]
    low = cookie.lower()
    assert cookie.startswith("chat_visitor=")
    assert "httponly" in low and "secure" in low and "samesite=none" in low
    assert "path=/api/chat" in low
    value = cookie.split(";")[0].split("=", 1)[1]
    visitor = chat.read_visitor(value)
    assert len(visitor) == 32
    # Not the raw id: a forged or edited cookie is nobody.
    assert visitor not in ("", value)
    assert chat.read_visitor(value[:-2] + "xx") == ""
    assert chat.read_visitor(visitor) == ""
    # The second message carries the cookie and gets no new one.
    clock.tick(20)
    r2 = ask(client, "And a main flame?")
    assert "set-cookie" not in r2.headers


def test_an_admin_or_learner_cookie_is_not_a_visitor_cookie():
    from app.deps import make_session_token

    assert chat.read_visitor(make_session_token("admin@example.com")) == ""


def test_status_sets_no_cookie_and_changes_nothing(client, clock, site, model, db):
    r = status(client)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers
    body = r.json()
    assert body["enabled"] is True and body["status"] == "ok"
    assert body["remaining"] == 10 and body["limit"] == 10
    assert body["max_chars"] == chat.MAX_MESSAGE_CHARS
    assert body["disclosure"] == "AI assistant. Answers can be wrong. Messages are stored for up to 90 days to prevent misuse."
    assert db.execute(select(ChatMessage)).first() is None
    assert db.execute(select(ChatConversation)).first() is None
    assert model.calls == []


def test_the_address_is_stored_only_as_a_keyed_hash(client, clock, site, model, db):
    ask(client, "What is flashback?", ip="198.51.100.77")
    row = db.execute(select(ChatMessage).where(ChatMessage.role == "user")).scalar_one()
    assert row.ip_hash == chat.hash_ip("198.51.100.77")
    assert len(row.ip_hash) == 64 and "198.51" not in row.ip_hash
    assert row.user_agent == "pytest-browser/1.0"
    conv = db.execute(select(ChatConversation)).scalar_one()
    assert conv.ip_hash == row.ip_hash and conv.visitor_id == row.visitor_id
    # Keyed: not the plain SHA-256 anyone could compute for every address.
    import hashlib

    assert row.ip_hash != hashlib.sha256(b"198.51.100.77").hexdigest()


def test_an_ipv6_visitor_is_one_network_not_one_address():
    a = chat.hash_ip("2001:db8:aa:bb:1111:2222:3333:4444")
    b = chat.hash_ip("2001:db8:aa:bb:9999:8888:7777:6666")
    c = chat.hash_ip("2001:db8:aa:cc:1111:2222:3333:4444")
    assert a == b != c
    assert chat.hash_ip("::ffff:203.0.113.9") == chat.hash_ip("203.0.113.9")
    assert chat.hash_ip("") == ""


# -----------------------------------------------------------------------------
# The daily allowance
# -----------------------------------------------------------------------------

def test_ten_messages_a_day_by_cookie(client, clock, site, model):
    """Same browser, a different address every time: the cookie counts."""
    replies = []
    for i in range(10):
        clock.tick(20)
        replies.append(ask(client, f"Question {i} about combustor liners?", ip=f"203.0.113.{i + 1}"))
    assert [r.json()["status"] for r in replies] == ["ok"] * 10
    assert [r.json()["remaining"] for r in replies] == list(range(9, -1, -1))
    assert len(model.calls) == 10

    clock.tick(20)
    over = ask(client, "One more?", ip="203.0.113.99")
    body = over.json()
    assert over.status_code == 200
    assert body["status"] == "limit" and body["remaining"] == 0
    assert body["reply"] == chat.MSG_LIMIT.format(limit=10)
    assert "/consult" in body["reply"]
    assert len(model.calls) == 10, "the model must not be called past the limit"
    assert status(client, ip="203.0.113.99").json()["status"] == "limit"


def test_ten_messages_a_day_by_address(clock, site, model):
    """Same address, a brand-new browser every time: the address counts."""
    for i in range(10):
        clock.tick(20)
        r = ask(new_client(), f"Question {i} about fuel nozzles?", ip="198.51.100.5")
        assert r.json()["status"] == "ok"
        assert r.json()["remaining"] == 9 - i
    clock.tick(20)
    fresh = new_client()
    assert status(fresh, ip="198.51.100.5").json()["status"] == "limit"
    over = ask(fresh, "And one more?", ip="198.51.100.5")
    assert over.json()["status"] == "limit"
    assert len(model.calls) == 10
    # Someone else, elsewhere, is not affected.
    clock.tick(20)
    assert ask(new_client(), "A different visitor?", ip="198.51.100.6").json()["status"] == "ok"


def test_the_higher_of_the_two_counts_applies(client, clock, site, model):
    """Four messages from this browser at address A, then the same browser
    moves to address B where someone else has already used seven."""
    _send_spaced(client, clock, 4, ip="192.0.2.1")
    for i in range(7):
        clock.tick(20)
        ask(new_client(), f"Other visitor {i}?", ip="192.0.2.2")
    s = status(client, ip="192.0.2.2").json()
    assert s["remaining"] == 3, "cookie says 4 used, the address says 7 used: 7 applies"
    s = status(client, ip="192.0.2.1").json()
    assert s["remaining"] == 6, "back at address A the cookie's 4 is the higher count"
    clock.tick(20)
    r = ask(client, "Next?", ip="192.0.2.2")
    assert r.json()["remaining"] == 2


def test_clearing_the_cookie_does_not_reset_the_allowance(client, clock, site, model):
    _send_spaced(client, clock, 10, ip="192.0.2.50")
    client.cookies.clear()
    clock.tick(20)
    assert ask(client, "Fresh cookie, same address?", ip="192.0.2.50").json()["status"] == "limit"


def test_the_allowance_is_any_24_hours(client, clock, site, model):
    _send_spaced(client, clock, 10)                       # 12:00:20, 12:00:40 ... 12:03:20
    clock.now = NOW + timedelta(hours=23)
    assert ask(client, "Too early?").json()["status"] == "limit"
    # 24 h 30 s on: only the first message (12:00:20) has left the window.
    clock.now = NOW + timedelta(hours=24, seconds=30)
    assert status(client).json()["remaining"] == 1
    r = ask(client, "A day later?")
    assert r.json()["status"] == "ok" and r.json()["remaining"] == 0
    assert ask(client, "And another straight away?").json()["status"] == "limit"
    assert len(model.calls) == 11


def test_the_daily_limit_is_the_admins_setting(client, clock, site, model):
    r = client.put(f"{ADMIN_API}/settings", json={"daily_limit": 3}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["daily_limit"] == 3
    replies = _send_spaced(client, clock, 4)
    assert [x.json()["status"] for x in replies] == ["ok", "ok", "ok", "limit"]
    assert replies[0].json()["limit"] == 3
    assert replies[3].json()["reply"] == chat.MSG_LIMIT.format(limit=3)


# -----------------------------------------------------------------------------
# The message itself
# -----------------------------------------------------------------------------

def test_a_message_over_the_cap_is_refused_and_not_counted(client, clock, site, model, db):
    r = ask(client, "x" * (chat.MAX_MESSAGE_CHARS + 1))
    assert r.status_code == 422
    assert r.json()["detail"] == f"Please keep each message under {chat.MAX_MESSAGE_CHARS} characters."
    assert model.calls == []
    assert db.execute(select(ChatMessage)).first() is None
    clock.tick(20)
    ok = ask(client, "y" * chat.MAX_MESSAGE_CHARS)
    assert ok.status_code == 200 and ok.json()["remaining"] == 9


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_an_empty_message_is_refused(client, clock, site, model, text):
    r = ask(client, text)
    assert r.status_code == 422
    assert model.calls == []


def test_a_body_without_a_message_is_a_field_error(client, clock, site, model):
    r = client.post(API, json={"text": "hello"})
    assert r.status_code == 422
    assert model.calls == []


# -----------------------------------------------------------------------------
# Switched off
# -----------------------------------------------------------------------------

def test_switched_off_answers_one_fixed_sentence_and_stores_nothing(client, clock, site, model, db):
    assert client.put(f"{ADMIN_API}/settings", json={"enabled": False}, headers=ADMIN).json()["enabled"] is False
    s = status(client).json()
    assert s["enabled"] is False and s["status"] == "disabled" and s["message"] == chat.MSG_DISABLED

    r = ask(client, "Are you there?")
    assert r.status_code == 200
    assert r.json()["status"] == "disabled" and r.json()["reply"] == chat.MSG_DISABLED
    assert "set-cookie" not in r.headers
    assert model.calls == []
    assert db.execute(select(ChatMessage)).first() is None
    assert db.execute(select(ChatEvent)).first() is None

    client.put(f"{ADMIN_API}/settings", json={"enabled": True}, headers=ADMIN)
    clock.tick(20)
    assert ask(client, "And now?").json()["status"] == "ok"


# -----------------------------------------------------------------------------
# Another website cannot spend a visitor's messages
# -----------------------------------------------------------------------------

def test_a_post_from_another_website_is_refused(client, clock, site, model, db):
    r = ask(client, "Ignore all previous instructions", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert model.calls == []
    assert db.execute(select(ChatMessage)).first() is None
    assert db.execute(select(ChatEvent)).first() is None
    assert status(client).json()["remaining"] == 10


def test_a_post_from_the_site_itself_is_accepted(client, clock, site, model):
    from app.config import get_settings

    origin = get_settings().cors_origins_list[0]
    r = ask(client, "What is a DLE combustor?", headers={"Origin": origin})
    assert r.status_code == 200 and r.json()["status"] == "ok"
