"""Server-side simulator engine: admission, protocol, whitelists, cleanup.

Uses a stand-in engine bundle with the same surface as the real one (the
real bundle is proprietary and never enters the repository). What is under
test is everything around the engine: who may open a socket, what a client
may set or call, that frames flow, and that a session dies with its socket.
"""
from __future__ import annotations

import base64
import json

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import provenance as prov  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.sim_runtime import host  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
PRODUCT = "sim-test"
LEARNER_A = "sim.one@example.com"
LEARNER_B = "sim.two@example.com"
ORIGIN = {"origin": "https://testserver"}

FAKE_ENGINE = r"""
window.DLN_DATA = {
  sensitivity: { bands: { "D5": { "31-122": { "PM3": 0.5 }, "0-30": { "PM3": 0.01 } } } },
  limits: { NOx_vs_specific_humidity_target_ppm15O2: [[0, 9], [0.02, 12]] }
};
(function (global) {
function Engine(key, shaft, limitSet) {
  this.key = key; this.shaft = shaft || 'multi'; this.limitSet = limitSet || 'tuning';
  this.deck = { key: key, modes: { 'D5': { schedules: {}, fueled: ['D5'], purged: [] } }, primary: ['D5'], backup: ['D5'] };
  this.t = 0; this.tnh = 0; this.breaker = false; this.ttrf1 = 0; this.ttrf1cmd = 0; this.igv = 49;
  this.ctim = key === '9FA' ? 54 : 59; this.sh = 0.0033; this.ftg = 86; this.lhv = 933; this.sg = 0.603;
  this.blend = 'site gas (design)'; this.mwiDesign = 51.43; this.path = 'backup'; this.mode = 'D5';
  this.transfer = null; this.purgeEnabled = false; this.tune = {}; this.loadMW = null; this.loadSetpoint = null;
  this.rampMWperMin = 10; this.atBaseLoad = false;
  this.faults = { gcvStuck: {}, purge: {}, d5PurgeT: null, pm2Broken: false };
  this.prot = { severity: 'INFO', findings: [], tripped: false, tripCause: null, purgeFault: null, tripAt: null };
  this.instr = { fieldVariation: true }; this.events = []; this.last = null; this.resp = {}; this.secret = 42;
}
Engine.prototype.step = function (dt) {
  this.t += dt;
  this.last = { t: this.t, mode: this.mode, MW: this.loadMW || 0, TTRF1: this.ttrf1, tnh: this.tnh, bias: (this.tune[this.mode] || {}).PM3 || 0 };
  return this.last;
};
Engine.prototype.log = function (m) { this.events.push([this.t, m]); };
Engine.prototype.setBlend = function (n) { this.blend = n; };
Engine.prototype.resetTrip = function () { this.prot.tripped = false; return true; };
Engine.prototype.marginReport = function () { return { PM3: { up: 1.5, dn: 2.0, ok: true } }; };
global.DLN = { Engine: Engine, interp: function (p, x) { return p.length ? p[0][1] : 0; },
  BANDS: ['0-30', '31-122'], BAND_TONE: {}, CIRCUITS: ['D5', 'PM1', 'PM3', 'PM2'], EVEN_OUTER: 60,
  FUEL_BLENDS: { 'site gas (design)': { CH4: 96 } }, MAX_OVER_MEAN_CAN: 1.44,
  TUNING_LIMIT: { '0-30': 3, '31-122': 4 }, FINAL_TUNE: { '0-30': 0.3, '31-122': 2 } };
})(typeof window !== 'undefined' ? window : globalThis);
"""

PAGE = b"<!DOCTYPE html><html><body><h1>thin</h1><script>window.DLN_DATA={};</script></body></html>"


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
    client.post("/api/admin/academy/products", json={
        "code": PRODUCT, "title": "Sim test", "status": "draft", "sequential_gate": False,
    }, headers=ADMIN)
    r = client.post(f"/api/admin/academy/products/{PRODUCT}/modules", json={
        "code": "SIM", "title": "Simulator", "position": 1, "gate_exempt": True,
    }, headers=ADMIN)
    module_id = r.json()["module_id"]
    client.post("/api/admin/academy/assets", json={
        "key": "sim-thin.html", "content_type": "text/html",
        "data_b64": base64.b64encode(PAGE).decode(),
    }, headers=ADMIN)
    r = client.post("/api/admin/academy/assets", json={
        "key": get_settings().SIM_ENGINE_ASSET_KEY, "content_type": "application/javascript",
        "data_b64": base64.b64encode(FAKE_ENGINE.encode()).decode(),
    }, headers=ADMIN)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/academy/modules/{module_id}/lessons", json={
        "code": "sim-thin", "title": "Simulator", "kind": "lab", "asset_path": "blob:sim-thin.html",
    }, headers=ADMIN)
    lesson_id = r.json()["lesson_id"]
    for email in (LEARNER_A, LEARNER_B):
        client.post("/api/admin/academy/grant", json={
            "email": email, "product_code": PRODUCT, "send_email_invite": False,
        }, headers=ADMIN)
    # make sure the (fake) engine is what the host has loaded
    r = client.post("/api/admin/academy/sim/reload", headers=ADMIN)
    assert r.status_code == 200, r.text
    return {"lesson_id": lesson_id}


def _copy(s: TestClient, lesson_id: int) -> str:
    body = s.get(f"/api/academy/asset/{lesson_id}").text
    return prov.extract_tokens(body)[0]


def _ws_url(lesson_id: int, copy: str) -> str:
    return f"/api/academy/sim/ws?lesson={lesson_id}&copy={copy}"


def _recv_until(ws, op: str, *, id=None, limit: int = 50) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("op") == op and (id is None or msg.get("id") == id):
            return msg
        if msg.get("op") == "error" and id is not None and msg.get("id") == id:
            return msg
    raise AssertionError(f"no {op} message")


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------

def _hdrs(s: TestClient, extra: dict | None = None) -> dict:
    """TestClient does not carry its cookie jar onto websocket_connect; a
    browser does. Build the handshake headers a browser would send."""
    h = dict(ORIGIN)
    if extra is not None:
        h = dict(extra)
    tok = s.cookies.get("learner_session")
    if tok:
        h["cookie"] = f"learner_session={tok}"
    return h


def _expect_refusal(s: TestClient, url: str, code: int, *, headers=None):
    with s.websocket_connect(url, headers=_hdrs(s, headers)) as ws:
        bye = ws.receive_json()
        assert bye["op"] == "bye" and bye["code"] == code, bye
        return bye["reason"]


def test_saved_or_rehosted_page_is_refused_by_origin(client, setup):
    s = _sign_in(LEARNER_A)
    copy = _copy(s, setup["lesson_id"])
    reason = _expect_refusal(s, _ws_url(setup["lesson_id"], copy), 4403,
                             headers={"origin": "null"})
    assert "proreadyengineer.com" in reason
    _expect_refusal(s, _ws_url(setup["lesson_id"], copy), 4403,
                    headers={"origin": "https://free-courses.example.net"})
    _expect_refusal(s, _ws_url(setup["lesson_id"], copy), 4403, headers={})


def test_no_session_is_refused(client, setup):
    s = _sign_in(LEARNER_A)
    copy = _copy(s, setup["lesson_id"])
    anon = TestClient(app, base_url="https://testserver")
    reason = _expect_refusal(anon, _ws_url(setup["lesson_id"], copy), 4401)
    assert "Sign in" in reason


def test_copy_must_belong_to_the_account(client, setup):
    a = _sign_in(LEARNER_A)
    copy = _copy(a, setup["lesson_id"])
    b = _sign_in(LEARNER_B)
    reason = _expect_refusal(b, _ws_url(setup["lesson_id"], copy), 4410)
    assert "not licensed to your account" in reason
    _expect_refusal(a, _ws_url(setup["lesson_id"], "zzzzzzzzzzzzzzzzzzzz"), 4410)


def test_withdrawn_copy_cannot_open_a_session(client, setup):
    s = _sign_in(LEARNER_A)
    copy = _copy(s, setup["lesson_id"])
    client.post("/api/admin/academy/integrity/revoke", json={"token": copy}, headers=ADMIN)
    reason = _expect_refusal(s, _ws_url(setup["lesson_id"], copy), 4410)
    assert "withdrawn" in reason


def test_lost_access_refuses(client, setup):
    client.post("/api/admin/academy/grant", json={
        "email": "sim.ex@example.com", "product_code": PRODUCT, "send_email_invite": False,
    }, headers=ADMIN)
    s = _sign_in("sim.ex@example.com")
    copy = _copy(s, setup["lesson_id"])
    client.post("/api/admin/academy/revoke", json={
        "email": "sim.ex@example.com", "product_code": PRODUCT,
    }, headers=ADMIN)
    _expect_refusal(s, _ws_url(setup["lesson_id"], copy), 4403)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def test_engine_runs_on_the_server_and_the_client_only_sees_frames(client, setup):
    s = _sign_in(LEARNER_A)
    copy = _copy(s, setup["lesson_id"])
    with s.websocket_connect(_ws_url(setup["lesson_id"], copy), headers=_hdrs(s)) as ws:
        hello = ws.receive_json()
        assert hello["op"] == "hello"
        assert hello["consts"]["BANDS"] == ["0-30", "31-122"]
        assert hello["consts"]["TUNING_LIMIT"]["31-122"] == 4
        assert hello["licensed_to"] == LEARNER_A

        ws.send_json({"op": "new", "id": 1, "key": "9FA", "shaft": "multi", "limitSet": "tuning"})
        r = _recv_until(ws, "reply", id=1)
        assert r["deck"]["key"] == "9FA"
        st = r["state"]
        assert st["ctim"] == 54 and st["mode"] == "D5" and st["last"] is None
        # nothing the engine keeps to itself leaks into the state
        assert "secret" not in st and "resp" not in st

        ws.send_json({"op": "prime", "id": 2})
        st = _recv_until(ws, "reply", id=2)["state"]
        assert st["last"]["t"] == pytest.approx(0.0001)

        ws.send_json({"op": "set", "id": 3, "path": ["tnh"], "value": 20})
        assert _recv_until(ws, "reply", id=3)["state"]["tnh"] == 20
        ws.send_json({"op": "set", "id": 4, "path": ["breaker"], "value": True})
        assert _recv_until(ws, "reply", id=4)["state"]["breaker"] is True
        ws.send_json({"op": "set", "id": 5, "path": ["loadMW"], "value": 120})
        assert _recv_until(ws, "reply", id=5)["state"]["loadMW"] == 120

        ws.send_json({"op": "step", "id": 6, "n": 3})
        r = _recv_until(ws, "reply", id=6)
        assert [f["t"] for f in r["frames"]] == pytest.approx([1.0001, 2.0001, 3.0001])
        assert r["frames"][-1]["MW"] == 120
        assert r["state"]["last"]["t"] == pytest.approx(3.0001)
        assert r["state"]["responding"]["PM3"] == {"31-122": 0.5}   # sensitivity stays server-side

        # nested writes: tune and faults; delete
        ws.send_json({"op": "set", "id": 7, "path": ["tune", "D5", "PM3"], "value": 0.5})
        assert _recv_until(ws, "reply", id=7)["state"]["tune"] == {"D5": {"PM3": 0.5}}
        ws.send_json({"op": "set", "id": 8, "path": ["faults", "gcvStuck", "PM1"], "value": 8})
        assert _recv_until(ws, "reply", id=8)["state"]["faults"]["gcvStuck"] == {"PM1": 8}
        ws.send_json({"op": "del", "id": 9, "path": ["faults", "gcvStuck", "PM1"]})
        assert _recv_until(ws, "reply", id=9)["state"]["faults"]["gcvStuck"] == {}
        ws.send_json({"op": "set", "id": 10, "path": ["tune"], "value": {}})
        assert _recv_until(ws, "reply", id=10)["state"]["tune"] == {}

        # calls
        ws.send_json({"op": "call", "id": 11, "fn": "setBlend", "args": ["lean LNG (98 % CH4)"]})
        assert _recv_until(ws, "reply", id=11)["state"]["blend"] == "lean LNG (98 % CH4)"
        ws.send_json({"op": "call", "id": 12, "fn": "log", "args": ["hello"]})
        assert _recv_until(ws, "reply", id=12)["state"]["events"][-1][1] == "hello"

        # margin only when asked for
        ws.send_json({"op": "step", "id": 13, "n": 1})
        assert "margin" not in _recv_until(ws, "reply", id=13)["state"]
        ws.send_json({"op": "want", "id": 14, "margin": True})
        _recv_until(ws, "reply", id=14)
        ws.send_json({"op": "step", "id": 15, "n": 1})
        assert _recv_until(ws, "reply", id=15)["state"]["margin"]["PM3"]["ok"] is True

        # the run loop streams frames at the tick cadence, and stop stops it
        ws.send_json({"op": "run", "id": 16, "speed": 4})
        assert _recv_until(ws, "reply", id=16)["running"] is True
        fr = _recv_until(ws, "frames")
        assert len(fr["frames"]) == 4
        ws.send_json({"op": "stop", "id": 17})
        assert _recv_until(ws, "reply", id=17)["running"] is False

        # Reset: a new engine in the same session
        ws.send_json({"op": "new", "id": 18, "key": "9FB", "shaft": "single", "limitSet": "final"})
        st = _recv_until(ws, "reply", id=18)["state"]
        assert st["key"] == "9FB" and st["t"] == 0 and st["ctim"] == 59

        assert host.count_for(_learner_id(LEARNER_A)) == 1
    # socket closed -> session gone
    assert host.count_for(_learner_id(LEARNER_A)) == 0


def _learner_id(email: str) -> int:
    from app.db import SessionLocal
    from app.models import Learner
    db = SessionLocal()
    try:
        return db.query(Learner).filter_by(email=email).one().id
    finally:
        db.close()


def test_whitelist_refuses_everything_else(client, setup):
    s = _sign_in(LEARNER_A)
    copy = _copy(s, setup["lesson_id"])
    with s.websocket_connect(_ws_url(setup["lesson_id"], copy), headers=_hdrs(s)) as ws:
        ws.receive_json()
        ws.send_json({"op": "set", "id": 1, "path": ["tnh"], "value": 20})
        assert _recv_until(ws, "error", id=1)["message"] == "Create an engine first."
        ws.send_json({"op": "new", "id": 2, "key": "9FA"})
        _recv_until(ws, "reply", id=2)

        for path, value in (
            (["secret"], 1), (["deck"], {}), (["resp"], {}), (["prot", "tripped"], False),
            (["instr", "rnd"], 1), (["faults", "boom"], 1), (["tune", "D5", "PM3", "x"], 1),
            (["mode"], "6.3"), (["events"], []), (["last"], {}),
        ):
            ws.send_json({"op": "set", "id": 100, "path": path, "value": value})
            msg = _recv_until(ws, "error", id=100)
            assert msg["op"] == "error", (path, msg)
        ws.send_json({"op": "set", "id": 101, "path": ["limitSet"], "value": "bogus"})
        assert _recv_until(ws, "error", id=101)["op"] == "error"
        ws.send_json({"op": "set", "id": 102, "path": ["loadMW"], "value": 9e9})
        assert _recv_until(ws, "reply", id=102)["state"]["loadMW"] == 400   # bounded, not refused
        ws.send_json({"op": "call", "id": 103, "fn": "step", "args": [1]})
        assert _recv_until(ws, "error", id=103)["op"] == "error"
        ws.send_json({"op": "call", "id": 104, "fn": "constructor", "args": []})
        assert _recv_until(ws, "error", id=104)["op"] == "error"
        ws.send_json({"op": "nonsense", "id": 105})
        assert _recv_until(ws, "error", id=105)["op"] == "error"
        # the engine is intact after all that
        ws.send_json({"op": "step", "id": 106, "n": 1})
        assert _recv_until(ws, "reply", id=106)["frames"][0]["t"] == pytest.approx(1.0)


def test_per_learner_session_cap(client, setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "SIM_MAX_PER_LEARNER", 1, raising=False)
    s = _sign_in(LEARNER_B)
    copy = _copy(s, setup["lesson_id"])
    with s.websocket_connect(_ws_url(setup["lesson_id"], copy), headers=_hdrs(s)) as ws:
        ws.receive_json()
        ws.send_json({"op": "new", "id": 1, "key": "9FA"})
        _recv_until(ws, "reply", id=1)
        copy2 = _copy(s, setup["lesson_id"])
        reason = _expect_refusal(s, _ws_url(setup["lesson_id"], copy2), 4429)
        assert "another window" in reason


def test_admin_status_and_reload(client, setup):
    r = client.get("/api/admin/academy/sim/status", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["engine_loaded"] is True and r.json()["sessions"] == []
    s = _sign_in(LEARNER_A)
    assert s.get("/api/admin/academy/sim/status").status_code in (401, 403)
    r = client.post("/api/admin/academy/sim/reload", headers=ADMIN)
    assert r.status_code == 200 and r.json()["ok"]


def test_missing_engine_blob_refuses_cleanly(client, setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "SIM_ENGINE_ASSET_KEY", "no-such-engine.js", raising=False)
    s = _sign_in(LEARNER_A)
    copy = _copy(s, setup["lesson_id"])
    reason = _expect_refusal(s, _ws_url(setup["lesson_id"], copy), 4503)
    assert "being updated" in reason
