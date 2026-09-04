"""Per-copy fingerprinting, call-home detection, and the admin trace.

The feature answers two different questions and each is tested separately:

  ATTRIBUTION — paste a leaked file, get the account it was issued to. Tested
  against a file that has had three of its four id carriers deliberately
  destroyed, because that is what a leaker who has been told "there's an id
  in it" actually does.

  DETECTION — a copy opened from a hard drive, or under a second account,
  reports itself. Tested by replaying the exact beacon payload the stamped
  file would send, with no session cookie at all.
"""
from __future__ import annotations

import base64
import json
import re

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import provenance as prov  # noqa: E402
from app.main import app  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "prov-test"
OWNER_A = "prov.one@example.com"
OWNER_B = "prov.two@example.com"

SIM_HTML = (
    b"<!DOCTYPE html>\n<html><head><title>Sim</title></head>"
    b"<body><h1>Mapping simulator</h1></body></html>"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


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
        "code": PRODUCT, "title": "Provenance test", "status": "draft",
        "sequential_gate": False,
    }, headers=ADMIN)
    assert r.status_code == 200, r.text

    r = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", json={
        "code": "SIM", "title": "Simulator", "position": 1, "gate_exempt": True,
    }, headers=ADMIN)
    module_id = r.json()["module_id"]

    client.post("/api/admin/academy/assets", json={
        "key": "prov-sim.html", "content_type": "text/html",
        "data_b64": base64.b64encode(SIM_HTML).decode(),
    }, headers=ADMIN)

    r = client.post(f"/api/admin/academy/modules/{module_id}/lessons", json={
        "code": "prov-sim", "title": "Simulator", "kind": "lab",
        "asset_path": "blob:prov-sim.html",
    }, headers=ADMIN)
    lesson_id = r.json()["lesson_id"]

    for email in (OWNER_A, OWNER_B):
        client.post("/api/admin/academy/grant", json={
            "email": email, "product_code": PRODUCT, "send_email_invite": False,
        }, headers=ADMIN)
    return {"lesson_id": lesson_id, "module_id": module_id}


# ---------------------------------------------------------------------------
# The encoding itself
# ---------------------------------------------------------------------------

def test_zero_width_carrier_is_invisible_and_recoverable():
    token = prov.new_token()
    sentence = f"Licensed to a@b.com{prov.zw_encode(token)} — do not redistribute."
    # Nothing a human can see changed.
    assert re.sub(r"[\u200b\u200c\u2060]", "", sentence) == (
        "Licensed to a@b.com — do not redistribute."
    )
    assert prov.zw_decode_all(sentence) == [token]


def test_tokens_are_unique_per_call():
    assert len({prov.new_token() for _ in range(2000)}) == 2000


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def test_served_copy_is_stamped_and_recorded(client, setup):
    s = _sign_in(OWNER_A)
    r = s.get(f"/api/academy/asset/{setup['lesson_id']}")
    assert r.status_code == 200
    body = r.text

    assert "Licensed to" in body and OWNER_A in body
    tokens = prov.extract_tokens(body)
    assert len(set(tokens)) == 1, "all four carriers must agree"
    token = tokens[0]

    # Every carrier is actually present.
    assert f"<!-- pre-copy: {token} -->" in body
    assert f'data-pre-copy="{token}"' in body
    assert f'__PRE_COPY__ = "{token}"' in body
    assert prov.zw_decode_all(body) == [token] * body.count(prov.zw_encode(token))

    r = client.post("/api/admin/academy/integrity/trace",
                    json={"content": body}, headers=ADMIN)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["verdict"] == "traced"
    assert data["matches"][0]["email"] == OWNER_A
    assert data["matches"][0]["token"] == token
    assert data["matches"][0]["served_at"]


def test_every_download_gets_its_own_id(client, setup):
    s = _sign_in(OWNER_A)
    a = prov.extract_tokens(s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]
    b = prov.extract_tokens(s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]
    assert a != b, "two downloads must be distinguishable, not just two accounts"


def test_trace_survives_a_leaker_stripping_the_obvious_carriers(client, setup):
    """The attack: delete the comment, the attribute and the JS constant."""
    s = _sign_in(OWNER_B)
    body = s.get(f"/api/academy/asset/{setup['lesson_id']}").text
    token = prov.extract_tokens(body)[0]

    tampered = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    tampered = tampered.replace(f' data-pre-copy="{token}"', "")
    tampered = tampered.replace(f'__PRE_COPY__ = "{token}"', '__PRE_COPY__ = ""')
    # ...and the run-lock loader's two mentions, which kills the copy (the id
    # is the AAD every script was encrypted under) but a leaker may try.
    tampered = tampered.replace(f'var T="{token}"', 'var T=""')
    tampered = tampered.replace(f"asset-key/{token}", "asset-key/")
    assert token not in re.sub(r"[\u200b\u200c\u2060]", "", tampered)

    r = client.post("/api/admin/academy/integrity/trace",
                    json={"content": tampered}, headers=ADMIN)
    assert r.json()["verdict"] == "traced"
    assert r.json()["matches"][0]["email"] == OWNER_B


def test_trace_accepts_a_bare_id_and_reports_an_unknown_one(client, setup):
    s = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]

    r = client.post("/api/admin/academy/integrity/trace",
                    json={"content": f"  {token}  "}, headers=ADMIN)
    assert r.json()["matches"][0]["email"] == OWNER_A

    r = client.post("/api/admin/academy/integrity/trace",
                    json={"content": "zzzzzzzzzzzzzzzzzzzz"}, headers=ADMIN)
    assert r.json()["verdict"] == "id-not-issued-by-us"

    r = client.post("/api/admin/academy/integrity/trace",
                    json={"content": "<html>nothing here</html>"}, headers=ADMIN)
    assert r.json()["verdict"] == "no-id-found"


def test_trace_is_admin_only(client, setup):
    s = _sign_in(OWNER_A)
    body = s.get(f"/api/academy/asset/{setup['lesson_id']}").text
    assert s.post("/api/admin/academy/integrity/trace",
                  json={"content": body}).status_code in (401, 403)
    assert client.get("/api/admin/academy/integrity").status_code in (401, 403)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _beacon(c: TestClient, token: str, url: str, origin: str = ""):
    """Replay exactly what the stamped file's sendBeacon would send."""
    return c.post(
        "/api/academy/beacon",
        content=json.dumps({
            "t": token, "u": url,
            "o": origin or (url.split("/")[0] + "//" + url.split("/")[2]
                            if url.startswith("http") else "null"),
            "r": "", "s": "1920x1080", "z": "Africa/Cairo",
        }),
        headers={"Content-Type": "text/plain"},
    )


def test_copy_opened_from_a_hard_drive_reports_itself(client, setup):
    s = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]

    # No session at all — a leaked file on somebody else's laptop.
    anon = TestClient(app, base_url="https://testserver")
    assert _beacon(anon, token, "file:///C:/Users/pirate/sim.html").status_code == 204

    r = client.get("/api/admin/academy/integrity",
                   params={"product_code": PRODUCT}, headers=ADMIN)
    alerts = [a for a in r.json()["alerts"] if a["token"] == token]
    assert alerts and alerts[0]["status"] == prov.PING_OFFSITE
    assert alerts[0]["issued_to"] == OWNER_A
    assert alerts[0]["page_url"].startswith("file://")


def test_copy_rehosted_on_another_site_reports_itself(client, setup):
    s = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]
    anon = TestClient(app, base_url="https://testserver")
    _beacon(anon, token, "https://free-courses.example.net/dle/sim.html")

    r = client.get("/api/admin/academy/integrity", headers=ADMIN)
    hit = [a for a in r.json()["alerts"] if a["token"] == token]
    assert hit and hit[0]["status"] == prov.PING_OFFSITE
    assert hit[0]["issued_to"] == OWNER_A


def test_copy_open_under_a_second_account_reports_itself(client, setup):
    a = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        a.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]

    b = _sign_in(OWNER_B)          # the file was passed to a colleague
    _beacon(b, token, "https://testserver/api/academy/asset/1")

    r = client.get("/api/admin/academy/integrity", headers=ADMIN)
    hit = [x for x in r.json()["alerts"] if x["token"] == token]
    assert hit and hit[0]["status"] == prov.PING_OTHER_ACCOUNT
    assert hit[0]["issued_to"] == OWNER_A
    assert hit[0]["session_email"] == OWNER_B


def test_normal_use_raises_no_alert(client, setup):
    s = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]
    _beacon(s, token, "https://testserver/api/academy/asset/1")

    r = client.get("/api/admin/academy/integrity", headers=ADMIN)
    assert not [a for a in r.json()["alerts"] if a["token"] == token]

    t = client.post("/api/admin/academy/integrity/trace",
                    json={"content": token}, headers=ADMIN).json()
    assert t["matches"][0]["ping_count"] == 1
    assert t["matches"][0]["worst_status"] == prov.PING_OK
    assert t["matches"][0]["pings"][0]["status"] == prov.PING_OK


def test_copy_opened_on_the_host_that_served_it_is_never_an_alert(client, setup):
    """The false-positive that would make this feature useless.

    `testserver` is deliberately NOT in ASSET_ALLOWED_HOSTS. Normal use must
    still read as normal, because the host a copy was served from is recorded
    on the delivery and counts as on-site for that copy. Nothing about "where
    does the API live" is left to a config value somebody has to keep right.
    """
    from app.config import get_settings
    assert "testserver" not in get_settings().asset_allowed_hosts_set

    s = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]
    _beacon(s, token, "https://testserver/api/academy/asset/1")

    r = client.get("/api/admin/academy/integrity", headers=ADMIN)
    assert not [a for a in r.json()["alerts"] if a["token"] == token]


def test_reviewing_an_alert_takes_it_out_of_the_inbox(client, setup):
    s = _sign_in(OWNER_A)
    token = prov.extract_tokens(
        s.get(f"/api/academy/asset/{setup['lesson_id']}").text)[0]
    anon = TestClient(app, base_url="https://testserver")
    _beacon(anon, token, "file:///D:/shared/sim.html")

    live = client.get("/api/admin/academy/integrity", headers=ADMIN).json()
    mine = [a for a in live["alerts"] if a["token"] == token]
    assert mine, "the alert must appear before it is reviewed"

    r = client.post("/api/admin/academy/integrity/dismiss",
                    json={"ping_ids": [mine[0]["id"]], "note": "spoke to them"},
                    headers=ADMIN)
    assert r.json()["reviewed"] == 1

    after = client.get("/api/admin/academy/integrity", headers=ADMIN).json()
    assert not [a for a in after["alerts"] if a["token"] == token]

    # Reviewing hides it; it never deletes the evidence.
    hist = client.get("/api/admin/academy/integrity",
                      params={"include_reviewed": "true"}, headers=ADMIN).json()
    kept = [a for a in hist["alerts"] if a["token"] == token]
    assert kept and kept[0]["reviewed_at"]


def test_beacon_never_errors_on_junk(client):
    anon = TestClient(app, base_url="https://testserver")
    for payload in (b"", b"not json", b"{}", b'{"t":""}', b'{"t":"never-issued"}',
                    b'{"t":"' + b"x" * 400 + b'"}'):
        r = anon.post("/api/academy/beacon", content=payload,
                      headers={"Content-Type": "text/plain"})
        assert r.status_code == 204


def test_unknown_id_calling_home_is_itself_an_alert(client, setup):
    anon = TestClient(app, base_url="https://testserver")
    _beacon(anon, "aaaabbbbccccddddeeee", "https://proreadyengineer.com/x")
    r = client.get("/api/admin/academy/integrity", headers=ADMIN)
    hit = [a for a in r.json()["alerts"]
           if a["token"] == "aaaabbbbccccddddeeee"]
    assert hit and hit[0]["status"] == prov.PING_UNKNOWN


def test_report_lists_downloads_and_flags_unusual_accounts(client, setup):
    r = client.get("/api/admin/academy/integrity",
                   params={"product_code": PRODUCT}, headers=ADMIN)
    data = r.json()
    assert data["totals"]["downloads"] >= 5
    assert any(d["email"] == OWNER_A for d in data["recent"])
    assert all(d["asset_key"] == "prov-sim.html" for d in data["recent"])
    # OWNER_A has copies that called home from off-site → on the watch list
    watched = {w["email"]: w for w in data["watch"]}
    assert OWNER_A in watched
    assert watched[OWNER_A]["alerts"] >= 1
    assert any("off-site" in reason for reason in watched[OWNER_A]["reasons"])


def test_no_entitlement_means_no_copy_and_no_row(client, setup):
    # An account that exists but holds nothing — granted, then revoked.
    client.post("/api/admin/academy/grant", json={
        "email": "prov.stranger@example.com", "product_code": PRODUCT,
        "send_email_invite": False,
    }, headers=ADMIN)
    client.post("/api/admin/academy/revoke", json={
        "email": "prov.stranger@example.com", "product_code": PRODUCT,
    }, headers=ADMIN)

    stranger = _sign_in("prov.stranger@example.com")
    assert stranger.get(
        f"/api/academy/asset/{setup['lesson_id']}").status_code == 403
    r = client.get("/api/admin/academy/integrity",
                   params={"product_code": PRODUCT}, headers=ADMIN)
    assert not [d for d in r.json()["recent"]
                if d["email"] == "prov.stranger@example.com"]
