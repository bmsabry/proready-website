"""Run-lock and integrity alerts.

The promise under test, in the order a leak actually happens:

  1. What the learner receives contains no runnable script — every inline
     script is ciphertext, and only that copy's key opens it.
  2. The copy can fetch its key while it is live: our origin, the account
     it was issued to, inside its TTL, not withdrawn, access still held.
  3. Every other situation is refused with a sentence for the screen, is
     recorded as a ping, and — where it looks like a leak — emails the
     instructor once.
  4. The instructor can withdraw one copy or an account's copies.

Emails are captured at the Resend seam. The sharing alert normally runs on
a background thread; the test makes it synchronous.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import asset_lock as lock  # noqa: E402
from app import emailer as E  # noqa: E402
from app import integrity_alerts as alerts  # noqa: E402
from app import provenance as prov  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AssetDelivery, AssetPing  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "lock-test"
OWNER_A = "lock.one@example.com"
OWNER_B = "lock.two@example.com"

# Three scripts like the real simulator: data, model, UI (which boots on
# DOMContentLoaded). Plus a JSON block that must NOT be locked.
SIM_HTML = b"""<!DOCTYPE html>
<html><head><title>Sim</title></head>
<body><h1>Mapping simulator</h1>
<script type="application/json" id="cfg">{"public": true}</script>
<script>window.DLN_DATA={"schedules":{"9FB":{"key":"9FB"}}};</script>
<script>
function solveSplits(x){ return x * 2; }
</script>
<script>
(function(){ 'use strict';
  window.addEventListener('DOMContentLoaded', function(){ window.__booted = solveSplits(21); });
})();
</script>
</body></html>"""

ON_SITE = {
    "Referer": "https://testserver/api/academy/asset/1",
    "Sec-Fetch-Site": "same-origin",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Capture every email at the wire seam and make sends 'succeed'."""
    sent: list[dict] = []

    class _Resp:
        status_code = 200
        text = "ok"

        def json(self):
            return {"id": "email_test"}

    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (sent.append(payload), _Resp())[1])
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "re_test", raising=False)
    monkeypatch.setattr(alerts, "_spawn", lambda fn: fn())  # sharing alert inline
    # This module launches the asset far more than a person would; the cap
    # is tested on its own with an explicit threshold.
    monkeypatch.setattr(get_settings(), "ASSET_LAUNCH_ALERT_PER_DAY", 10_000, raising=False)
    return sent


def _sign_in(email: str) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/admin/academy/login-link",
               json={"email": email, "send_email": False}, headers=ADMIN)
    assert r.status_code == 200, r.text
    token = r.json()["link"].split("token=")[1]
    assert c.post("/api/academy/auth/verify", json={"token": token}).status_code == 200
    return c


@pytest.fixture(scope="module")
def setup(client):
    r = client.post("/api/admin/academy/products", json={
        "code": PRODUCT, "title": "Lock test", "status": "draft",
        "sequential_gate": False,
    }, headers=ADMIN)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", json={
        "code": "SIM", "title": "Simulator", "position": 1, "gate_exempt": True,
    }, headers=ADMIN)
    module_id = r.json()["module_id"]
    client.post("/api/admin/academy/assets", json={
        "key": "lock-sim.html", "content_type": "text/html",
        "data_b64": base64.b64encode(SIM_HTML).decode(),
    }, headers=ADMIN)
    r = client.post(f"/api/admin/academy/modules/{module_id}/lessons", json={
        "code": "lock-sim", "title": "Simulator", "kind": "lab",
        "asset_path": "blob:lock-sim.html",
    }, headers=ADMIN)
    lesson_id = r.json()["lesson_id"]
    for email in (OWNER_A, OWNER_B):
        client.post("/api/admin/academy/grant", json={
            "email": email, "product_code": PRODUCT, "send_email_invite": False,
        }, headers=ADMIN)
    return {"lesson_id": lesson_id, "module_id": module_id}


def _fetch_copy(s: TestClient, lesson_id: int) -> tuple[str, str]:
    r = s.get(f"/api/academy/asset/{lesson_id}")
    assert r.status_code == 200, r.text
    body = r.text
    return body, prov.extract_tokens(body)[0]


def _delivery(token: str) -> AssetDelivery:
    db = SessionLocal()
    try:
        return db.query(AssetDelivery).filter_by(token=token).one()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. What the learner receives
# ---------------------------------------------------------------------------

def test_served_copy_contains_no_runnable_script(client, setup):
    s = _sign_in(OWNER_A)
    body, token = _fetch_copy(s, setup["lesson_id"])

    assert lock.locked_script_count(body) == 3
    # None of the app's code or data survives in the clear.
    for needle in ("DLN_DATA", "solveSplits", "__booted", "schedules"):
        assert needle not in body
    # The JSON block is not ours to lock, and the beacon and loader are plain.
    assert '<script type="application/json" id="cfg">{"public": true}</script>' in body
    assert "__PRE_COPY__" in body
    assert f"asset-key/{token}" in body
    assert "credentials:'same-origin'" in body
    assert "Licensed to" in body and OWNER_A in body


def test_only_that_copys_key_opens_it(client, setup):
    s = _sign_in(OWNER_A)
    body_a, token_a = _fetch_copy(s, setup["lesson_id"])
    body_b, token_b = _fetch_copy(s, setup["lesson_id"])
    key_a = lock.key_from_b64(_delivery(token_a).key_b64)
    key_b = lock.key_from_b64(_delivery(token_b).key_b64)
    assert key_a != key_b

    scripts = lock.unlock_html(body_a, token=token_a, key=key_a)
    assert len(scripts) == 3
    assert scripts[0].startswith("window.DLN_DATA=")
    assert "function solveSplits" in scripts[1]
    assert "DOMContentLoaded" in scripts[2]

    with pytest.raises(Exception):
        lock.unlock_html(body_a, token=token_a, key=key_b)
    # The id is authenticated data: change it and the key is useless too.
    with pytest.raises(Exception):
        lock.unlock_html(body_a, token=token_b, key=key_a)


# ---------------------------------------------------------------------------
# 2. The live copy gets its key
# ---------------------------------------------------------------------------

def test_live_copy_on_site_gets_its_key(client, setup):
    s = _sign_in(OWNER_A)
    body, token = _fetch_copy(s, setup["lesson_id"])
    r = s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 200, r.text
    assert "no-store" in r.headers["cache-control"]
    assert r.json()["k"] == _delivery(token).key_b64
    d = _delivery(token)
    assert d.key_fetches == 1 and d.key_denied == 0 and d.worst_status == prov.PING_OK


def test_older_browser_without_sec_fetch_is_judged_by_referer(client, setup):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    r = s.get(f"/api/academy/asset-key/{token}",
              headers={"Referer": "https://testserver/api/academy/asset/1"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3. Every other situation is refused, recorded, and (if a leak) emailed
# ---------------------------------------------------------------------------

def test_saved_copy_opened_from_disk_is_refused_and_alerts(client, setup, outbox):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    # A file:// page: no Referer, opaque origin, cross-site fetch — and, in
    # the worst case for us, the leaker's own valid cookie still attached.
    r = s.get(f"/api/academy/asset-key/{token}",
              headers={"Sec-Fetch-Site": "cross-site", "Origin": "null"})
    assert r.status_code == 403
    assert "not on proreadyengineer.com" in r.json()["detail"]

    d = _delivery(token)
    assert d.key_denied == 1 and d.worst_status == prov.PING_OFFSITE
    assert len(outbox) == 1
    mail = outbox[0]
    assert mail["to"] == [get_settings().ADMIN_NOTIFY_EMAIL]
    assert "off your site" in mail["subject"] and OWNER_A in mail["subject"]
    assert token in mail["html"] and "key request" in mail["html"]
    assert "cannot start without" in mail["html"]  # it is run-locked

    # Opened again from disk an hour later: recorded, not emailed again.
    r = s.get(f"/api/academy/asset-key/{token}",
              headers={"Sec-Fetch-Site": "cross-site", "Origin": "null"})
    assert r.status_code == 403
    assert len(outbox) == 1
    assert _delivery(token).key_denied == 2


def test_copy_rehosted_elsewhere_is_refused(client, setup, outbox):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    r = s.get(f"/api/academy/asset-key/{token}", headers={
        "Referer": "https://free-courses.example.net/dle/sim.html",
        "Sec-Fetch-Site": "cross-site",
        "Origin": "https://free-courses.example.net",
    })
    assert r.status_code == 403
    assert len(outbox) == 1
    assert "free-courses.example.net" in outbox[0]["html"]


def test_copy_passed_to_another_account_is_refused(client, setup, outbox):
    a = _sign_in(OWNER_A)
    _, token = _fetch_copy(a, setup["lesson_id"])
    b = _sign_in(OWNER_B)
    r = b.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 403
    assert "different account" in r.json()["detail"]
    assert _delivery(token).worst_status == prov.PING_OTHER_ACCOUNT
    assert len(outbox) == 1
    assert "different account" in outbox[0]["subject"]
    assert OWNER_B in outbox[0]["html"]


def test_expired_session_is_told_to_sign_in_not_alerted(client, setup, outbox):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    anon = TestClient(app, base_url="https://testserver")
    r = anon.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 401
    assert "Sign in" in r.json()["detail"]
    assert outbox == []


def test_unknown_id_is_refused_and_alerts(client, setup, outbox):
    s = _sign_in(OWNER_A)
    r = s.get("/api/academy/asset-key/aaaabbbbccccddddeeee", headers=ON_SITE)
    assert r.status_code == 404
    assert len(outbox) == 1
    assert "never issued" in outbox[0]["subject"]


def test_copy_expires_after_its_ttl(client, setup, outbox):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    db = SessionLocal()
    try:
        d = db.query(AssetDelivery).filter_by(token=token).one()
        d.served_at = datetime.now(timezone.utc) - timedelta(
            hours=get_settings().ASSET_COPY_TTL_HOURS + 1)
        db.commit()
    finally:
        db.close()
    r = s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 410
    assert "expired" in r.json()["detail"]
    assert outbox == []  # the learner's own old copy is not a leak

    # ...and a fresh launch works immediately.
    _, token2 = _fetch_copy(s, setup["lesson_id"])
    assert s.get(f"/api/academy/asset-key/{token2}", headers=ON_SITE).status_code == 200


def test_reload_budget_is_finite(client, setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "ASSET_KEY_MAX_FETCHES", 3, raising=False)
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    for _ in range(3):
        assert s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE).status_code == 200
    r = s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 429


def test_losing_access_kills_live_copies(client, setup):
    client.post("/api/admin/academy/grant", json={
        "email": "lock.ex@example.com", "product_code": PRODUCT, "send_email_invite": False,
    }, headers=ADMIN)
    s = _sign_in("lock.ex@example.com")
    _, token = _fetch_copy(s, setup["lesson_id"])
    assert s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE).status_code == 200
    client.post("/api/admin/academy/revoke", json={
        "email": "lock.ex@example.com", "product_code": PRODUCT,
    }, headers=ADMIN)
    r = s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 403
    assert "access to this material has ended" in r.json()["detail"]


def test_beacon_leak_signal_emails_once(client, setup, outbox):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    anon = TestClient(app, base_url="https://testserver")
    payload = json.dumps({"t": token, "u": "file:///C:/Users/pirate/sim.html",
                          "o": "null", "r": "", "s": "1920x1080", "z": "Africa/Cairo"})
    for _ in range(3):
        assert anon.post("/api/academy/beacon", content=payload,
                         headers={"Content-Type": "text/plain"}).status_code == 204
    assert len(outbox) == 1
    assert "off your site" in outbox[0]["subject"]
    assert "via beacon" in outbox[0]["html"]
    assert "Africa/Cairo" in outbox[0]["html"]
    assert "/admin#courses" in outbox[0]["html"]


def test_launch_cap_emails_exactly_once_when_crossed(client, setup, outbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "ASSET_LAUNCH_ALERT_PER_DAY", 2, raising=False)
    client.post("/api/admin/academy/grant", json={
        "email": "lock.many@example.com", "product_code": PRODUCT, "send_email_invite": False,
    }, headers=ADMIN)
    s = _sign_in("lock.many@example.com")
    for _ in range(5):
        _fetch_copy(s, setup["lesson_id"])
    assert len(outbox) == 1
    assert "Unusual launch count" in outbox[0]["subject"]
    assert "3 times today" in outbox[0]["html"]


def test_owner_launches_never_trip_the_cap(client, setup, outbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "ASSET_LAUNCH_ALERT_PER_DAY", 1, raising=False)
    owner_email = get_settings().owner_emails_list[0]
    client.post("/api/admin/academy/grant", json={
        "email": owner_email, "product_code": PRODUCT, "send_email_invite": False,
    }, headers=ADMIN)
    owner = _sign_in(owner_email)
    for _ in range(4):
        _fetch_copy(owner, setup["lesson_id"])
    assert outbox == []


def test_simultaneous_use_of_one_login_emails_once(client, setup, outbox):
    """Two browsers (two device cookies), one account, inside ten minutes."""
    client.post("/api/admin/academy/grant", json={
        "email": "lock.shared@example.com", "product_code": PRODUCT, "send_email_invite": False,
    }, headers=ADMIN)
    first = _sign_in("lock.shared@example.com")
    first.get("/api/academy/me")
    second = _sign_in("lock.shared@example.com")   # a second device
    second.get("/api/academy/me")
    second.get("/api/academy/me")
    assert len(outbox) == 1
    assert "Simultaneous use" in outbox[0]["subject"]
    assert "lock.shared@example.com" in outbox[0]["subject"]


# ---------------------------------------------------------------------------
# 4. The kill switch
# ---------------------------------------------------------------------------

def test_admin_can_withdraw_one_copy(client, setup, outbox):
    s = _sign_in(OWNER_A)
    _, token = _fetch_copy(s, setup["lesson_id"])
    _, other = _fetch_copy(s, setup["lesson_id"])
    r = client.post("/api/admin/academy/integrity/revoke",
                    json={"token": token, "reason": "seen on a file-sharing site"},
                    headers=ADMIN)
    assert r.json() == {"ok": True, "revoked": 1}

    r = s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 403 and "withdrawn" in r.json()["detail"]
    assert outbox == []  # the legitimate learner opening a withdrawn copy is not a leak
    # The sibling copy is untouched.
    assert s.get(f"/api/academy/asset-key/{other}", headers=ON_SITE).status_code == 200

    log = client.get("/api/admin/academy/integrity",
                     params={"product_code": PRODUCT}, headers=ADMIN).json()
    row = next(d for d in log["recent"] if d["token"] == token)
    assert row["revoked_at"] and row["revoke_reason"] == "seen on a file-sharing site"
    assert row["alive"] is False and row["locked"] is True
    live = next(d for d in log["recent"] if d["token"] == other)
    assert live["alive"] is True


def test_admin_can_withdraw_every_copy_an_account_holds(client, setup):
    s = _sign_in(OWNER_B)
    _, t1 = _fetch_copy(s, setup["lesson_id"])
    _, t2 = _fetch_copy(s, setup["lesson_id"])
    a = _sign_in(OWNER_A)
    _, ta = _fetch_copy(a, setup["lesson_id"])

    learner_id = _delivery(t1).learner_id
    r = client.post("/api/admin/academy/integrity/revoke",
                    json={"learner_id": learner_id}, headers=ADMIN)
    assert r.json()["ok"] and r.json()["revoked"] >= 2
    for t in (t1, t2):
        assert s.get(f"/api/academy/asset-key/{t}", headers=ON_SITE).status_code == 403
    # Another learner's copy is untouched, and the withdrawn account can
    # still launch a fresh copy: access was not removed, the files were.
    assert a.get(f"/api/academy/asset-key/{ta}", headers=ON_SITE).status_code == 200
    _, fresh = _fetch_copy(s, setup["lesson_id"])
    assert s.get(f"/api/academy/asset-key/{fresh}", headers=ON_SITE).status_code == 200


def test_revoke_is_admin_only_and_validated(client, setup):
    s = _sign_in(OWNER_A)
    assert s.post("/api/admin/academy/integrity/revoke",
                  json={"token": "x"}).status_code in (401, 403)
    r = client.post("/api/admin/academy/integrity/revoke", json={}, headers=ADMIN)
    assert r.status_code == 422


def test_lock_can_be_switched_off(client, setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "ASSET_LOCK_ENABLED", False, raising=False)
    s = _sign_in(OWNER_A)
    body, token = _fetch_copy(s, setup["lesson_id"])
    assert lock.locked_script_count(body) == 0
    assert "function solveSplits" in body
    assert _delivery(token).key_b64 == ""
    r = s.get(f"/api/academy/asset-key/{token}", headers=ON_SITE)
    assert r.status_code == 410  # nothing to unlock; the copy already runs


def test_trace_still_finds_the_id_in_a_locked_copy(client, setup):
    s = _sign_in(OWNER_A)
    body, token = _fetch_copy(s, setup["lesson_id"])
    stripped = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    stripped = re.sub(r"[​‌⁠]", "", stripped)
    stripped = stripped.replace(f' data-pre-copy="{token}"', "")
    stripped = stripped.replace(f'__PRE_COPY__ = "{token}"', '__PRE_COPY__ = ""')
    r = client.post("/api/admin/academy/integrity/trace",
                    json={"content": stripped}, headers=ADMIN)
    assert r.json()["verdict"] == "traced"
    assert r.json()["matches"][0]["email"] == OWNER_A
