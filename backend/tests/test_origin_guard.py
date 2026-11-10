"""A request another website makes with a signed-in person's cookie is refused.

Both sessions are SameSite=None cookies, so a browser sends them along with a
request started by any page. These pin the rule in app/origin_guard.py: a
state-changing request that carries a session cookie and names a foreign
Origin never reaches its handler, and nothing legitimate is caught by it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.deps import SESSION_COOKIE_NAME
from app.learner_auth import LEARNER_COOKIE_NAME
from app.main import app
from app.origin_guard import origin_is_ours

from conftest import ADMIN_TOKEN

SITE = "http://localhost:5173"  # in the default CORS_ORIGINS used by the tests
EVIL = "https://evil.example"
REFUSED = "This request came from another website and was refused."


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _post(client, path, *, origin=None, cookie=None, json=None, headers=None):
    h = dict(headers or {})
    if origin is not None:
        h["Origin"] = origin
    if cookie:
        h["Cookie"] = f"{cookie}=anything"
    return client.post(path, json=json, headers=h)


@pytest.mark.parametrize("cookie", [SESSION_COOKIE_NAME, LEARNER_COOKIE_NAME])
def test_foreign_origin_with_a_session_cookie_is_refused_before_the_handler(client, cookie):
    r = _post(client, "/api/admin/mark-paid", origin=EVIL, cookie=cookie, json={"registration_id": 1})
    assert r.status_code == 403 and r.json()["detail"] == REFUSED
    # a bodyless POST, which a plain cross-site <form> can send in every browser
    r = _post(client, "/api/admin/academy/calendar/disconnect", origin=EVIL, cookie=cookie)
    assert r.status_code == 403 and r.json()["detail"] == REFUSED
    # a local file or sandboxed frame announces itself as "null"
    r = _post(client, "/api/academy/auth/set-password", origin="null", cookie=cookie, json={"password": "x" * 12})
    assert r.status_code == 403 and r.json()["detail"] == REFUSED


def test_the_site_itself_is_let_through_to_the_handler(client):
    # Reaches the handler, which then rejects the made-up cookie in its own way.
    r = _post(client, "/api/admin/mark-paid", origin=SITE, cookie=SESSION_COOKIE_NAME, json={"registration_id": 1})
    assert r.status_code == 401
    r = _post(client, "/api/academy/auth/set-password", origin=SITE, cookie=LEARNER_COOKIE_NAME, json={"password": "x" * 12})
    assert r.status_code == 401


def test_pages_served_by_the_api_host_are_ours(client):
    # the simulator page is served from the API's own host
    r = _post(client, "/api/academy/auth/logout", origin="https://testserver", cookie=LEARNER_COOKIE_NAME)
    assert r.status_code == 200
    assert origin_is_ours("https://api.proreadyengineer.com", "whatever.internal:10000")


def test_requests_without_an_origin_are_untouched(client):
    # curl, the cron job and webhooks send no Origin
    r = client.post("/api/admin/mark-paid", json={"registration_id": 999999},
                    headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert r.status_code == 404  # handler ran (no such registration)
    r = _post(client, "/api/admin/session-reminders/run", cookie=SESSION_COOKIE_NAME)
    assert r.status_code == 401  # reached the handler; the made-up cookie is not a session


def test_requests_without_a_session_cookie_are_untouched(client):
    # the public forms and the bearer-token quiz apps, from any origin
    r = _post(client, "/api/interest", origin=EVIL, json={"course_slug": "origin-guard-test", "email": "a@example.com"})
    assert r.status_code == 200
    r = _post(client, "/auth/login", origin=EVIL, json={"email": "nobody@example.com", "password": "wrong-password"})
    assert r.status_code in (400, 401)


def test_reads_are_never_refused(client):
    r = client.get("/api/academy/me", headers={"Origin": EVIL, "Cookie": f"{LEARNER_COOKIE_NAME}=anything"})
    assert r.status_code == 200 and r.json()["signed_in"] is False


def test_the_beacon_and_usage_pings_stay_open_to_off_site_files(client):
    # posted on purpose from copies opened as local files (Origin: null)
    r = _post(client, "/api/track/usage", origin="null", cookie=LEARNER_COOKIE_NAME,
              json={"product": "origin-guard-test"})
    assert r.status_code != 403
