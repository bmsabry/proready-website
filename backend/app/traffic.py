"""Website traffic for Admin → Website Traffic, from Cloudflare Web Analytics.

Cloudflare's Web Analytics beacon (automatic setup on proreadyengineer.com)
records every page load in a real browser. We read it through Cloudflare's
GraphQL Analytics API with CF_ANALYTICS_TOKEN, a read-only token (Account
Analytics: Read, Zone Analytics: Read). Bots are excluded, as on
Cloudflare's own dashboard ("Exclude bots: Yes").

Cloudflare's two terms, used as they are:
  page view — one page loaded in a browser;
  visit     — a page view that arrived from another website, a link or the
              address bar, not a click within the site (about one sitting).

Admin pages (/admin…) are left out unless asked for: that is the owner at
work, not a visitor. Cloudflare keeps only a sample of events for a small site
(about one in ten, multiplied back up), so numbers move in steps of about
ten — the same figures its own dashboard shows; `sampled` says so.

Answers are cached for five minutes. Nothing here raises: a missing token or
a Cloudflare failure comes back as `configured: false` / `error`.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
CACHE_SECONDS = 300
# Cloudflare answers at most 93 days per query and keeps 184 days (this
# plan, per the API's own settings), so 90 days is the longest range and
# still has a full previous period to compare with.
RANGES = (1, 7, 30, 90)
# Mobile apps send their package name instead of a website.
APP_REFERRERS = {
    "com.linkedin.android": "LinkedIn app",
    "com.google.android.gm": "Gmail app",
    "com.google.android.googlequicksearchbox": "Google app",
    "com.facebook.katana": "Facebook app",
    "com.whatsapp": "WhatsApp",
    "org.telegram.messenger": "Telegram",
}

_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _filter(since_var: str, until_var: str, include_admin: bool) -> str:
    parts = ["{siteTag:$site}", f"{{datetime_geq:${since_var}}}", f"{{datetime_lt:${until_var}}}",
             "{bot:0}"]
    if not include_admin:
        parts.append('{requestPath_notlike:"/admin%"}')
    return "{AND:[" + ",".join(parts) + "]}"


def _query(bucket: str, include_admin: bool, with_previous: bool) -> str:
    f = _filter("since", "until", include_admin)
    g = "rumPageloadEventsAdaptiveGroups"
    blocks = [
        f"total: {g}(limit: 1, filter: {f}) {{ count sum {{ visits }} avg {{ sampleInterval }} }}",
        f"series: {g}(limit: 5000, orderBy: [{bucket}_ASC], filter: {f}) "
        f"{{ count sum {{ visits }} dimensions {{ {bucket} }} }}",
        f"pages: {g}(limit: 25, orderBy: [count_DESC], filter: {f}) "
        f"{{ count sum {{ visits }} dimensions {{ requestPath }} }}",
        f"referrers: {g}(limit: 40, orderBy: [sum_visits_DESC], filter: {f}) "
        f"{{ count sum {{ visits }} dimensions {{ refererHost }} }}",
        # by page views: in sampled data a country's visits can read 0
        f"countries: {g}(limit: 30, orderBy: [count_DESC], filter: {f}) "
        f"{{ count sum {{ visits }} dimensions {{ countryName }} }}",
        f"devices: {g}(limit: 10, orderBy: [sum_visits_DESC], filter: {f}) "
        f"{{ count sum {{ visits }} dimensions {{ deviceType }} }}",
        f"browsers: {g}(limit: 10, orderBy: [sum_visits_DESC], filter: {f}) "
        f"{{ count sum {{ visits }} dimensions {{ userAgentBrowser }} }}",
    ]
    variables = "$account: string!, $site: string!, $since: Time!, $until: Time!"
    if with_previous:
        pf = _filter("psince", "puntil", include_admin)
        blocks.append(f"previous: {g}(limit: 1, filter: {pf}) {{ count sum {{ visits }} }}")
        variables += ", $psince: Time!, $puntil: Time!"
    body = "\n      ".join(blocks)
    return (f"query ({variables}) {{ viewer {{ accounts(filter: {{accountTag: $account}}) {{\n"
            f"      {body}\n    }} }} }}")


def _num(row: dict | None, *path: str) -> float:
    cur = row or {}
    for p in path:
        cur = (cur or {}).get(p) if isinstance(cur, dict) else None
    try:
        return float(cur or 0)
    except (TypeError, ValueError):
        return 0.0


def _pv(row: dict) -> int:
    return int(round(_num(row, "count")))


def _visits(row: dict) -> int:
    return int(round(_num(row, "sum", "visits")))


def _dim(row: dict, name: str) -> str:
    return str(((row or {}).get("dimensions") or {}).get(name) or "")


def _source(host: str, own: set[str]) -> str:
    h = host.strip().lower().removeprefix("www.")
    if not h:
        return "Direct (typed, bookmarked or an app)"
    if h in own:
        return ""  # a click within the site, not a way in
    if h in APP_REFERRERS:
        return APP_REFERRERS[h]
    if "teams" in h and "microsoft" in h:  # links opened from a Teams chat
        return "Microsoft Teams"
    return h


def _series(rows: list[dict], bucket: str, since: datetime, until: datetime) -> list[dict]:
    got: dict[str, tuple[int, int]] = {}
    for r in rows:
        key = _dim(r, bucket)
        if bucket == "datetimeHour":
            key = key[:13]  # "2026-09-22T14"
        v, p = got.get(key, (0, 0))
        got[key] = (v + _visits(r), p + _pv(r))
    out = []
    if bucket == "datetimeHour":
        t = since.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        while t < until:
            key = t.strftime("%Y-%m-%dT%H")
            v, p = got.get(key, (0, 0))
            out.append({"t": t.strftime("%Y-%m-%dT%H:00:00Z"), "visits": v, "page_views": p})
            t += timedelta(hours=1)
    else:
        d: date = since.astimezone(timezone.utc).date()
        end = until.astimezone(timezone.utc).date()
        while d <= end:
            v, p = got.get(d.isoformat(), (0, 0))
            out.append({"t": d.isoformat(), "visits": v, "page_views": p})
            d += timedelta(days=1)
    return out


def _shape(acct: dict, bucket: str, since: datetime, until: datetime, own: set[str]) -> dict:
    total = (acct.get("total") or [{}])[0] if acct.get("total") else {}
    visits, views = _visits(total), _pv(total)
    sample = _num(total, "avg", "sampleInterval")

    refs: dict[str, int] = {}
    for r in acct.get("referrers") or []:
        src = _source(_dim(r, "refererHost"), own)
        if src and _visits(r) > 0:
            refs[src] = refs.get(src, 0) + _visits(r)

    prev = None
    if acct.get("previous") is not None:
        p = (acct.get("previous") or [{}])[0] if acct.get("previous") else {}
        prev = {"visits": _visits(p), "page_views": _pv(p)}

    def rows(key: str, dim: str, label: str, limit: int, blank: str) -> list[dict]:
        out = []
        for r in acct.get(key) or []:
            out.append({label: _dim(r, dim) or blank, "visits": _visits(r), "page_views": _pv(r)})
        return out[:limit]

    return {
        "totals": {
            "visits": visits,
            "page_views": views,
            "pages_per_visit": round(views / visits, 1) if visits else None,
        },
        "previous": prev,
        "sampled": sample > 1.01,
        "series": _series(acct.get("series") or [], bucket, since, until),
        "pages": rows("pages", "requestPath", "path", 20, "/"),
        "referrers": [{"source": k, "visits": v}
                      for k, v in sorted(refs.items(), key=lambda kv: -kv[1])][:15],
        "countries": rows("countries", "countryName", "country", 25, "Unknown"),
        "devices": rows("devices", "deviceType", "device", 6, "unknown"),
        "browsers": rows("browsers", "userAgentBrowser", "browser", 8, "Other"),
    }


def report(days: int = 30, include_admin: bool = False, *, now: datetime | None = None) -> dict:
    """Traffic for the last `days` days (1 = the last 24 hours, by hour)."""
    days = min(RANGES, key=lambda r: abs(r - int(days or 30)))
    s = get_settings()
    token = (s.CF_ANALYTICS_TOKEN or "").strip()
    base = {
        "configured": bool(token and s.CF_WEB_ANALYTICS_SITE_TAG and s.CF_ANALYTICS_ACCOUNT_ID),
        "days": days,
        "include_admin": include_admin,
        "ranges": list(RANGES),
        "source": "Cloudflare Web Analytics (bots excluded)",
        "error": "",
    }
    if not base["configured"]:
        return base
    key = (days, include_admin)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic() and now is None:
            return hit[1]

    until = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    since = until - timedelta(days=days)
    bucket = "datetimeHour" if days <= 1 else "date"
    with_previous = days * 2 <= s.CF_ANALYTICS_LOOKBACK_DAYS
    variables = {
        "account": s.CF_ANALYTICS_ACCOUNT_ID,
        "site": s.CF_WEB_ANALYTICS_SITE_TAG,
        "since": _iso(since),
        "until": _iso(until),
    }
    if with_previous:
        variables.update(psince=_iso(since - timedelta(days=days)), puntil=_iso(since))
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(GRAPHQL_URL, headers={"Authorization": f"Bearer {token}"},
                            json={"query": _query(bucket, include_admin, with_previous),
                                  "variables": variables})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        errors = body.get("errors") or []
        accounts = ((body.get("data") or {}).get("viewer") or {}).get("accounts") or []
        if r.status_code != 200 or errors or not accounts:
            msg = "; ".join(str(e.get("message", e)) for e in errors)[:300] or f"HTTP {r.status_code}"
            log.warning("[traffic] Cloudflare refused: %s", msg)
            return {**base, "error": f"Cloudflare did not answer: {msg}"}
        own = {h.strip().lower().removeprefix("www.") for h in s.CF_ANALYTICS_OWN_HOSTS.split(",") if h.strip()}
        out = {
            **base,
            "since": _iso(since),
            "until": _iso(until),
            "bucket": "hour" if bucket == "datetimeHour" else "day",
            **_shape(accounts[0], bucket, since, until, own),
            "fetched_at": _iso(datetime.now(timezone.utc)),
        }
    except Exception as e:  # network, JSON, anything: never break the admin page
        log.warning("[traffic] lookup failed", exc_info=True)
        return {**base, "error": f"Could not reach Cloudflare ({type(e).__name__})."}
    with _lock:
        _cache[key] = (time.monotonic() + CACHE_SECONDS, out)
    return out


def clear_cache() -> None:
    with _lock:
        _cache.clear()
