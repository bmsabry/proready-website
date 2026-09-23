"""Admin → Website Traffic (Cloudflare Web Analytics)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

import conftest  # noqa: F401
from fastapi.testclient import TestClient

from app import traffic
from app.config import get_settings
from app.main import app

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
NOW = datetime(2026, 9, 22, 15, 30, tzinfo=timezone.utc)
REAL_CLIENT = httpx.Client


def g(count, visits, **dims):
    return {"count": count, "sum": {"visits": visits}, "dimensions": dims}


ANSWER = {
    "total": [{"count": 1970, "sum": {"visits": 450}, "avg": {"sampleInterval": 10}}],
    "previous": [{"count": 1500, "sum": {"visits": 300}}],
    "series": [g(40, 10, date="2026-09-20"), g(55, 20, date="2026-09-22")],
    "pages": [g(700, 200, requestPath="/"), g(300, 60, requestPath="/training")],
    "referrers": [
        g(900, 250, refererHost=""),
        g(500, 0, refererHost="proreadyengineer.com"),
        g(120, 60, refererHost="www.google.com"),
        g(40, 20, refererHost="google.com"),
        g(30, 15, refererHost="www.linkedin.com"),
        g(30, 30, refererHost="com.linkedin.android"),
        g(10, 10, refererHost="statics.gov.teams.microsoft.us"),
    ],
    "countries": [g(900, 200, countryName="US"), g(500, 120, countryName="EG")],
    "devices": [g(1500, 350, deviceType="desktop"), g(470, 100, deviceType="mobile")],
    "browsers": [g(1200, 300, userAgentBrowser="Chrome")],
}


@pytest.fixture
def cf(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "CF_ANALYTICS_TOKEN", "t-test")
    traffic.clear_cache()
    seen: list[dict] = []

    def use(handler):
        def wrapped(request):
            seen.append({"auth": request.headers.get("authorization"), **json.loads(request.content)})
            return handler(request)
        monkeypatch.setattr(traffic.httpx, "Client",
                            lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kw))

    yield use, seen
    traffic.clear_cache()


def ok(request):
    return httpx.Response(200, json={"data": {"viewer": {"accounts": [ANSWER]}}, "errors": None})


def test_without_a_token_it_says_so_and_asks_nobody(monkeypatch):
    monkeypatch.setattr(get_settings(), "CF_ANALYTICS_TOKEN", "")
    monkeypatch.setattr(traffic.httpx, "Client", lambda **kw: pytest.fail("no call expected"))
    out = traffic.report(30)
    assert out["configured"] is False and out["error"] == ""


def test_numbers_are_shaped_for_the_page(cf):
    use, seen = cf
    use(ok)
    out = traffic.report(30, now=NOW)
    assert out["totals"] == {"visits": 450, "page_views": 1970, "pages_per_visit": 4.4}
    assert out["previous"] == {"visits": 300, "page_views": 1500}
    assert out["sampled"] is True
    # every day of the range is there, quiet days as zero
    assert len(out["series"]) == 31 and out["series"][0]["t"] == "2026-08-23"
    days = {p["t"]: p for p in out["series"]}
    assert days["2026-09-21"] == {"t": "2026-09-21", "visits": 0, "page_views": 0}
    assert days["2026-09-22"]["visits"] == 20
    # www. merged, clicks within the site dropped, no referrer = direct
    assert out["referrers"] == [
        {"source": "Direct (typed, bookmarked or an app)", "visits": 250},
        {"source": "google.com", "visits": 80},
        {"source": "LinkedIn app", "visits": 30},
        {"source": "linkedin.com", "visits": 15},
        {"source": "Microsoft Teams", "visits": 10},
    ]
    assert out["pages"][0] == {"path": "/", "visits": 200, "page_views": 700}
    assert out["countries"][1]["country"] == "EG"
    # the request: read-only token, our account and site, bots excluded
    req = seen[0]
    assert req["auth"] == "Bearer t-test"
    assert req["variables"]["account"] == "aad152269e08fce6c2330f02888046ac"
    assert req["variables"]["site"] == "6cabcb640027410d9d15f33a755ca9cb"
    assert req["variables"]["since"] == "2026-08-23T15:30:00Z"
    assert req["variables"]["psince"] == "2026-07-24T15:30:00Z"
    assert "{bot:0}" in req["query"] and '"/admin%"' in req["query"]


def test_admin_pages_can_be_included(cf):
    use, seen = cf
    use(ok)
    traffic.report(7, include_admin=True, now=NOW)
    assert "/admin%" not in seen[0]["query"]


def test_last_24_hours_is_by_hour(cf):
    use, seen = cf
    use(lambda r: httpx.Response(200, json={"data": {"viewer": {"accounts": [{
        "total": [{"count": 5, "sum": {"visits": 2}, "avg": {"sampleInterval": 1}}],
        "series": [g(5, 2, datetimeHour="2026-09-22T14:00:00Z")]}]}}}))
    out = traffic.report(1, now=NOW)
    # 15:30 to 15:30 touches 25 clock hours; the first and last are partial
    assert out["bucket"] == "hour" and len(out["series"]) == 25
    assert out["series"][0]["t"] == "2026-09-21T15:00:00Z"
    assert out["series"][-2] == {"t": "2026-09-22T14:00:00Z", "visits": 2, "page_views": 5}
    assert out["sampled"] is False
    assert "datetimeHour_ASC" in seen[0]["query"]


def test_ninety_days_is_the_longest_and_still_compares(cf):
    use, seen = cf
    use(ok)
    out = traffic.report(180, now=NOW)  # snaps to what Cloudflare can answer
    assert out["days"] == 90 and out["ranges"] == [1, 7, 30, 90]
    assert seen[0]["variables"]["psince"] == "2026-03-26T15:30:00Z"


def test_the_previous_period_is_skipped_beyond_what_cloudflare_keeps(cf, monkeypatch):
    monkeypatch.setattr(get_settings(), "CF_ANALYTICS_LOOKBACK_DAYS", 120)
    use, seen = cf
    use(ok)
    traffic.report(90, now=NOW)
    assert "psince" not in seen[0]["variables"] and "previous:" not in seen[0]["query"]


def test_cloudflare_errors_are_shown_not_raised(cf):
    use, _ = cf
    use(lambda r: httpx.Response(200, json={"data": None, "errors": [{"message": "not authorized"}]}))
    out = traffic.report(30, now=NOW)
    assert out["configured"] is True and "not authorized" in out["error"]
    assert "totals" not in out


def test_network_failure_is_shown_not_raised(cf):
    use, _ = cf

    def down(request):
        raise httpx.ConnectError("down")

    use(down)
    out = traffic.report(30, now=NOW)
    assert out["error"].startswith("Could not reach Cloudflare")


def test_cached_for_five_minutes_and_refresh_asks_again(cf):
    use, seen = cf
    use(ok)
    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/api/admin/traffic").status_code == 401
        a = c.get("/api/admin/traffic?days=30", headers=ADMIN).json()
        b = c.get("/api/admin/traffic?days=30", headers=ADMIN).json()
        assert a == b and len(seen) == 1
        c.get("/api/admin/traffic?days=30&refresh=true", headers=ADMIN)
        assert len(seen) == 2
