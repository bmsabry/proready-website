"""The inbound-email webhook accepts only what Resend signed, once it has the secret.

Without a check, one POST from anyone creates a support ticket that looks as
if a real customer wrote it and makes the desk email whatever address the
sender chose. The check switches on when RESEND_INBOUND_WEBHOOK_SECRET is set,
so deploying the code changes nothing until the owner adds the secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

SECRET = "whsec_" + base64.b64encode(b"inbound-test-signing-key").decode()
URL = "/api/webhooks/resend-inbound"
# Addressed to another domain, so the handler drops it without creating anything.
PAYLOAD = json.dumps({
    "type": "email.received",
    "data": {"from": "Someone <someone@example.org>", "to": ["hello@not-our-domain.example"],
             "subject": "signature test", "text": "hello"},
}).encode()


def _signed_headers(body: bytes, secret: str = SECRET, when: int | None = None) -> dict:
    msg_id, ts = "msg_test_1", str(when or int(time.time()))
    key = base64.b64decode(secret.split("_", 1)[1])
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}",
            "Content-Type": "application/json"}


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_without_the_secret_the_endpoint_behaves_as_before(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESEND_INBOUND_WEBHOOK_SECRET", "", raising=False)
    r = client.post(URL, content=PAYLOAD, headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_with_the_secret_an_unsigned_or_forged_payload_is_refused(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESEND_INBOUND_WEBHOOK_SECRET", SECRET, raising=False)
    assert client.post(URL, content=PAYLOAD, headers={"Content-Type": "application/json"}).status_code == 401
    other = "whsec_" + base64.b64encode(b"someone-elses-key").decode()
    assert client.post(URL, content=PAYLOAD, headers=_signed_headers(PAYLOAD, other)).status_code == 401
    # a genuine signature on a different body
    assert client.post(URL, content=PAYLOAD + b" ", headers=_signed_headers(PAYLOAD)).status_code == 401
    # a genuine signature replayed an hour later
    old = _signed_headers(PAYLOAD, when=int(time.time()) - 3600)
    assert client.post(URL, content=PAYLOAD, headers=old).status_code == 401


def test_with_the_secret_a_payload_resend_signed_is_accepted(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESEND_INBOUND_WEBHOOK_SECRET", SECRET, raising=False)
    r = client.post(URL, content=PAYLOAD, headers=_signed_headers(PAYLOAD))
    assert r.status_code == 200 and r.json()["ok"] is True
