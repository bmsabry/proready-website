"""The deployer identity: a GitHub Actions OIDC token for the simulator repo.

GitHub's real keys are replaced by a key pair generated here; what is under
test is every check we make on the token (issuer, audience, repository,
branch, age, signature) and how small the deployer's reach is.
"""
from __future__ import annotations

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deploy_auth  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
REPO = "bmsabry/ProDLEMappingSim"
AUD = "proreadyengineer-sim-deploy"

_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUB = _PRIV.public_key()
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(k) -> bytes:
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())


def mint(**over) -> str:
    now = int(time.time())
    claims = {
        "iss": deploy_auth.GITHUB_OIDC_ISSUER, "aud": AUD, "sub": f"repo:{REPO}:ref:refs/heads/main",
        "repository": REPO, "ref": "refs/heads/main", "iat": now, "nbf": now, "exp": now + 300,
        "run_id": "12345", "workflow": "deploy",
    }
    claims.update({k: v for k, v in over.items() if k != "key"})
    return jwt.encode(claims, _pem(over.get("key", _PRIV)), algorithm="RS256", headers={"kid": "test"})


@pytest.fixture(autouse=True)
def deployer_on(monkeypatch):
    monkeypatch.setenv("SIM_DEPLOY_GITHUB_REPO", REPO)
    monkeypatch.setenv("SIM_DEPLOY_TOKEN", "")
    get_settings.cache_clear()
    monkeypatch.setattr(deploy_auth, "_signing_key", lambda token: _PUB)
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def bearer(tok: str) -> dict:
    return {"Authorization": "Bearer " + tok}


def test_good_token_reaches_status(client):
    r = client.get("/api/admin/academy/sim/status", headers=bearer(mint()))
    assert r.status_code == 200, r.text
    assert "engine_loaded" in r.json()


@pytest.mark.parametrize("bad", [
    dict(repository="someone-else/ProDLEMappingSim"),
    dict(ref="refs/heads/feature"),
    dict(aud="another-service"),
    dict(iss="https://accounts.example.com"),
    dict(exp=int(time.time()) - 60),
    dict(iat=int(time.time()) - 3600),          # minted an hour ago — never accepted
    dict(key=_OTHER),                            # signed by someone else
])
def test_bad_tokens_are_refused(client, bad):
    r = client.get("/api/admin/academy/sim/status", headers=bearer(mint(**bad)))
    assert r.status_code == 401, (bad, r.text)


def test_switched_off_when_repo_unset(client, monkeypatch):
    monkeypatch.setenv("SIM_DEPLOY_GITHUB_REPO", "")
    get_settings.cache_clear()
    r = client.get("/api/admin/academy/sim/status", headers=bearer(mint()))
    assert r.status_code == 401


def test_garbage_bearer_is_refused(client):
    for tok in ("", "abc", "a.b", "not.a.jwt", conftest.ADMIN_TOKEN + "x"):
        r = client.get("/api/admin/academy/sim/status", headers=bearer(tok))
        assert r.status_code == 401, tok


def test_admin_token_still_works(client):
    r = client.get("/api/admin/academy/sim/status", headers=ADMIN)
    assert r.status_code == 200


def test_deployer_writes_only_the_simulator_keys(client):
    body = lambda key: {"key": key, "filename": key, "content_type": "text/html",
                        "data_b64": base64.b64encode(b"<html>x</html>").decode()}
    ok = client.post("/api/admin/academy/assets", json=body("prodlemappingsim-thin.html"), headers=bearer(mint()))
    assert ok.status_code == 200, ok.text
    assert ok.json()["sha256"] and ok.json()["bytes"] == 14
    ok2 = client.post("/api/admin/academy/assets", json=body("sim-engine.js"), headers=bearer(mint()))
    assert ok2.status_code == 200, ok2.text
    no = client.post("/api/admin/academy/assets", json=body("instructor-signature.png"), headers=bearer(mint()))
    assert no.status_code == 403
    no2 = client.post("/api/admin/academy/assets", json=body("prodlemappingsim.html"), headers=bearer(mint()))
    assert no2.status_code == 403
    # the admin is not restricted
    yes = client.post("/api/admin/academy/assets", json=body("some-handout.pdf"), headers=ADMIN)
    assert yes.status_code == 200


def test_deployer_cannot_reach_anything_else(client):
    for path in ("/api/admin/academy/learners", "/api/admin/academy/products", "/api/admin/registrations",
                 "/api/admin/academy/integrity/alerts"):
        r = client.get(path, headers=bearer(mint()))
        assert r.status_code in (401, 404, 405), (path, r.status_code)
        assert r.status_code != 200


def test_static_fallback_token(client, monkeypatch):
    monkeypatch.setenv("SIM_DEPLOY_TOKEN", "static-deploy-secret")
    get_settings.cache_clear()
    r = client.get("/api/admin/academy/sim/status", headers=bearer("static-deploy-secret"))
    assert r.status_code == 200
    r = client.get("/api/admin/academy/sim/status", headers=bearer("static-deploy-secre"))
    assert r.status_code == 401
    r = client.get("/api/admin/academy/learners", headers=bearer("static-deploy-secret"))
    assert r.status_code != 200
