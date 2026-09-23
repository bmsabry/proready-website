"""IP location and network type for the Student Activity page."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import conftest  # noqa: F401
from fastapi.testclient import TestClient

from app import ip_intel
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import IpLookup, Learner, LearnerVisit

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}

# What ipapi.is actually answers (trimmed to the fields we read).
KEYLESS_TELUS = {  # real keyless answer for a trainee's address, 2026-09-22
    "ip": "75.157.171.195", "is_bogon": False, "company": "TELUS-FIBRE-KTMTBC01",
    "asn": "AS852 TELUS Communications Inc.", "city": "Kitimat",
    "region": "British Columbia", "country": "Canada",
}


def keyed(ip, *, mobile=False, dc=False, vpn=False, ctype="isp", city="Cairo",
          state="Cairo", country="Egypt", cc="EG", org="Telecom Egypt"):
    return {
        "ip": ip, "is_mobile": mobile, "is_datacenter": dc, "is_vpn": vpn,
        "is_proxy": False, "is_tor": False, "is_satellite": False,
        "company": {"name": org, "type": ctype, "netname": "NET-1"},
        "asn": {"asn": 8452, "org": org, "type": ctype},
        "location": {"city": city, "state": state, "country": country, "country_code": cc},
    }


@pytest.fixture
def enabled(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "IP_LOOKUP_ENABLED", True)
    monkeypatch.setattr(ip_intel, "_paused_until", None)
    return s


REAL_CLIENT = httpx.Client


def _client_with(monkeypatch, handler):
    monkeypatch.setattr(ip_intel.httpx, "Client",
                        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def test_keyless_answer_gives_place_and_provider_but_no_network_type():
    row = IpLookup(ip="75.157.171.195", **ip_intel.parse(KEYLESS_TELUS, keyed=False))
    d = ip_intel.describe(row, row.ip)
    assert d["place"] == "Kitimat, British Columbia, Canada"
    assert d["provider"] == "TELUS Communications Inc."
    assert d["netname"] == "TELUS-FIBRE-KTMTBC01"
    assert d["kind"] == "unknown" and d["flags_known"] is False


@pytest.mark.parametrize("kw,kind", [
    ({"mobile": True}, "mobile"),
    ({}, "home"),
    ({"ctype": "business"}, "business"),
    ({"dc": True, "ctype": "hosting"}, "datacenter"),
    ({"vpn": True, "dc": True}, "vpn"),
])
def test_keyed_answer_says_what_kind_of_network(kw, kind):
    row = IpLookup(ip="1.2.3.4", **ip_intel.parse(keyed("1.2.3.4", **kw), keyed=True))
    d = ip_intel.describe(row, "1.2.3.4")
    assert d["kind"] == kind and d["flags_known"] is True
    assert d["place"] == "Cairo, Cairo, Egypt" and d["country_code"] == "EG"


def test_private_and_bad_addresses_are_never_looked_up(enabled, monkeypatch):
    calls = []
    monkeypatch.setattr(ip_intel, "fetch", lambda ips, **k: calls.append(ips) or {})
    db = SessionLocal()
    try:
        out = ip_intel.lookup_many(db, ["10.0.0.1", "192.168.1.5", "testclient", "203.0.113.9"])
    finally:
        db.close()
    assert calls == []
    assert out["10.0.0.1"]["kind"] == "local"


def test_bulk_lookup_with_key_then_served_from_cache(enabled, monkeypatch):
    monkeypatch.setattr(enabled, "IPAPI_KEY", "k-test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={
            **{ip: keyed(ip, mobile=(ip == "81.10.1.1")) for ip in body["ips"]},
            "total_elapsed_ms": 1.0,
        })

    _client_with(monkeypatch, handler)
    db = SessionLocal()
    try:
        out = ip_intel.lookup_many(db, ["81.10.1.1", "81.10.1.2"])
        again = ip_intel.lookup_many(db, ["81.10.1.1", "81.10.1.2"])
    finally:
        db.close()
    assert len(seen) == 1 and seen[0]["key"] == "k-test"
    assert sorted(seen[0]["ips"]) == ["81.10.1.1", "81.10.1.2"]
    assert out["81.10.1.1"]["kind"] == "mobile" and out["81.10.1.2"]["kind"] == "home"
    assert again == out


def test_keyless_rows_are_refreshed_once_a_key_exists(enabled, monkeypatch):
    monkeypatch.setattr(enabled, "IPAPI_KEY", "")
    _client_with(monkeypatch, lambda r: httpx.Response(200, json={**KEYLESS_TELUS, "ip": "75.157.1.1"}))
    db = SessionLocal()
    try:
        first = ip_intel.lookup_many(db, ["75.157.1.1"])
        assert first["75.157.1.1"]["kind"] == "unknown"
        monkeypatch.setattr(enabled, "IPAPI_KEY", "k-test")
        _client_with(monkeypatch, lambda r: httpx.Response(200, json={
            "75.157.1.1": keyed("75.157.1.1", city="Kitimat", country="Canada", cc="CA",
                                org="TELUS Communications Inc.")}))
        second = ip_intel.lookup_many(db, ["75.157.1.1"])
    finally:
        db.close()
    assert second["75.157.1.1"]["kind"] == "home"
    assert second["75.157.1.1"]["flags_known"] is True


def test_out_of_lookups_pauses_until_midnight(enabled, monkeypatch):
    monkeypatch.setattr(enabled, "IPAPI_KEY", "")
    hits = []

    def handler(request):
        hits.append(1)
        return httpx.Response(429, json={"error": "ERR_FREE_TIER_EXHAUSTED"})

    _client_with(monkeypatch, handler)
    assert ip_intel.fetch(["8.8.4.4", "8.8.8.8"]) == {}
    assert ip_intel.fetch(["9.9.9.9"]) == {}
    assert len(hits) == 1  # stopped at the first refusal, and stays stopped


def test_network_failure_shows_unknown_instead_of_breaking(enabled, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")

    _client_with(monkeypatch, handler)
    db = SessionLocal()
    try:
        out = ip_intel.lookup_many(db, ["4.4.4.4"])
    finally:
        db.close()
    assert out["4.4.4.4"]["kind"] == "unknown" and out["4.4.4.4"]["place"] == ""


def test_detail_shows_locations_and_flags_two_countries_within_an_hour(monkeypatch):
    info = {
        "41.33.1.1": keyed("41.33.1.1", city="Cairo", country="Egypt", cc="EG", org="TE Data"),
        "24.114.2.2": keyed("24.114.2.2", mobile=True, city="Toronto", state="Ontario",
                            country="Canada", cc="CA", org="Rogers"),
    }
    monkeypatch.setattr(ip_intel, "fetch",
                        lambda ips, **k: {ip: ip_intel.parse(info[ip], keyed=True) for ip in ips if ip in info})
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/admin/academy/grant", headers=ADMIN, json={
            "email": "two.countries@example.com", "product_code": "micro-gas-turbine-design",
            "send_email_invite": False})
        db = SessionLocal()
        try:
            lid = db.query(Learner).filter(Learner.email == "two.countries@example.com").one().id
            now = datetime.now(timezone.utc)
            db.add(LearnerVisit(learner_id=lid, device_id="x" * 32, ip="41.33.1.1",
                                started_at=now - timedelta(hours=3), last_seen_at=now - timedelta(hours=2, minutes=40)))
            db.add(LearnerVisit(learner_id=lid, device_id="y" * 32, ip="24.114.2.2",
                                started_at=now - timedelta(hours=2, minutes=20), last_seen_at=now - timedelta(hours=2)))
            db.commit()
        finally:
            db.close()
        d = c.get(f"/api/admin/academy/activity/{lid}", headers=ADMIN).json()
    assert d["ip_info"]["41.33.1.1"]["place"] == "Cairo, Cairo, Egypt"
    assert d["ip_info"]["24.114.2.2"]["kind"] == "mobile"
    places = {p["place"]: p for p in d["locations"]}
    assert places["Toronto, Ontario, Canada"]["kind_label"] == "Mobile network (cell data)"
    titles = [f["title"] for f in d["learner"]["flags"]]
    assert "Used in Egypt and Canada within an hour" in titles
    assert any(t.startswith("Used from 2 countries in 30 days") for t in titles)


def test_relay_first_then_direct_when_the_relay_is_down(enabled, monkeypatch):
    monkeypatch.setattr(enabled, "IPAPI_KEY", "k-test")
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "proreadyengineer.com":
            raise httpx.ConnectError("relay down")
        body = json.loads(request.content)
        return httpx.Response(200, json={ip: keyed(ip) for ip in body["ips"]})

    _client_with(monkeypatch, handler)
    out = ip_intel.fetch(["81.20.1.1"])
    assert hosts == ["proreadyengineer.com", "api.ipapi.is"]
    assert out["81.20.1.1"]["city"] == "Cairo"
