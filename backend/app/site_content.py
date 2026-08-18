"""The public website, readable by the assistant.

The assistant knew every row in the database and not one word of the site
those rows belong to — so it could tell you how many people registered for
a course but not what the course page says, what the consulting services
are, or what any of the twelve case studies claim.

Where the text comes from: every public route is prerendered to static
HTML at build time (see routes.ts and the prerender pipeline), and the
build also emits sitemap.xml. So the live site is itself the index — no
second copy to maintain, nothing to regenerate, and no chance of the
assistant quoting page copy that was edited three deploys ago. The
sitemap is fetched, the pages are fetched, the markup is stripped, and
the result is cached in memory.

Fetching is best-effort by design. If the site is unreachable the tools
return an error the agent can reason about and it falls back to database
answers, rather than the whole chat failing.
"""
from __future__ import annotations

import html as _html
import logging
import re
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# Pages change on deploy, not on the minute. An hour keeps the assistant
# current without re-fetching 33 pages every time it is asked a question.
CACHE_TTL_SECONDS = 3600

# Guardrails on what we will pull into a prompt.
MAX_PAGES = 60
MAX_PAGE_CHARS = 20_000

_lock = threading.Lock()
_cache: dict[str, Any] = {"fetched_at": 0.0, "pages": {}, "order": []}

# Chrome that repeats on every page and tells the assistant nothing.
_BOILERPLATE = (
    "Skip to main content",
    "ProReady Engineer",
)


def _site_root() -> str:
    return (get_settings().SITE_URL or "https://proreadyengineer.com").rstrip("/")


def _strip_html(raw: str) -> str:
    """Markup to readable text.

    Script/style/noscript are dropped whole — their contents are the
    hydration payload and would otherwise swamp the real copy.
    """
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    # Keep block boundaries as newlines so headings don't run into body text.
    text = re.sub(r"(?i)</(p|div|section|h[1-6]|li|tr|article|header|footer)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    for junk in _BOILERPLATE:
        text = text.replace(junk, " ")
    return text.strip()


def _title_of(raw: str, path: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if m:
        return _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return path


def _fetch(client: httpx.Client, url: str) -> Optional[str]:
    try:
        r = client.get(url, follow_redirects=True)
    except httpx.HTTPError as e:
        log.warning("[site] fetch failed %s: %s", url, e)
        return None
    if r.status_code >= 300:
        log.warning("[site] fetch %s returned %s", url, r.status_code)
        return None
    return r.text


def _paths_from_sitemap(client: httpx.Client, root: str) -> list[str]:
    xml = _fetch(client, f"{root}/sitemap.xml")
    if not xml:
        return []
    out: list[str] = []
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
        p = urlparse(loc).path or "/"
        if p not in out:
            out.append(p)
    return out[:MAX_PAGES]


def _refresh(force: bool = False) -> dict[str, Any]:
    """Rebuild the cache if stale. Returns the cache dict."""
    with _lock:
        fresh = (time.time() - _cache["fetched_at"]) < CACHE_TTL_SECONDS
        if fresh and _cache["pages"] and not force:
            return _cache

        root = _site_root()
        pages: dict[str, dict[str, str]] = {}
        order: list[str] = []
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, connect=10.0),
                headers={"User-Agent": "ProReadyEngineer-Admin-Assistant"},
            ) as client:
                paths = _paths_from_sitemap(client, root)
                if not paths:
                    log.warning("[site] sitemap empty or unreachable at %s", root)
                for path in paths:
                    raw = _fetch(client, f"{root}{path}")
                    if not raw:
                        continue
                    body = _strip_html(raw)[:MAX_PAGE_CHARS]
                    if not body:
                        continue
                    pages[path] = {"title": _title_of(raw, path), "text": body}
                    order.append(path)
        except Exception:
            log.exception("[site] refresh failed")

        if pages:
            # Only replace a good cache with another good one; a transient
            # network failure should not blank what we already had.
            _cache["pages"] = pages
            _cache["order"] = order
            _cache["fetched_at"] = time.time()
            log.info("[site] cached %d pages from %s", len(pages), root)
        return _cache


def list_pages(force: bool = False) -> list[dict[str, Any]]:
    """Every public page: path, title, and size."""
    c = _refresh(force=force)
    return [
        {
            "path": p,
            "title": c["pages"][p]["title"],
            "chars": len(c["pages"][p]["text"]),
        }
        for p in c["order"]
    ]


def read_page(path: str) -> Optional[dict[str, Any]]:
    """Full readable text of one page, or None if we don't have it."""
    c = _refresh()
    key = "/" + (path or "").strip().strip("/")
    if key == "/" and (path or "").strip() not in ("", "/"):
        key = "/" + (path or "").strip().lstrip("/")
    page = c["pages"].get(key)
    if page is None and key.rstrip("/") != key:
        page = c["pages"].get(key.rstrip("/"))
    if page is None:
        return None
    return {"path": key, "title": page["title"], "text": page["text"]}


def search(query: str, limit: int = 6, context: int = 400) -> list[dict[str, Any]]:
    """Find pages mentioning the query, with the surrounding sentence.

    Scores on how often the terms appear, so "what do we say about
    hydrogen" surfaces the hydrogen article rather than every page whose
    footer happens to contain the word once.
    """
    c = _refresh()
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) > 2]
    if not terms:
        return []

    hits: list[dict[str, Any]] = []
    for path in c["order"]:
        page = c["pages"][path]
        low = page["text"].lower()
        score = sum(low.count(t) for t in terms)
        if not score:
            continue
        first = min((low.find(t) for t in terms if low.find(t) != -1), default=0)
        start = max(0, first - context // 2)
        excerpt = page["text"][start : start + context].strip()
        hits.append(
            {
                "path": path,
                "title": page["title"],
                "score": score,
                "excerpt": ("…" if start else "") + excerpt + "…",
            }
        )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def index_summary(max_pages: int = 40) -> str:
    """A compact "what pages exist" list, cheap enough for a system prompt.

    The support auto-replier gets this rather than the full text: it needs
    to know the site HAS a page on hydrogen conversion so it can point
    someone at it, without carrying 100k characters of prose per ticket.
    """
    pages = list_pages()
    if not pages:
        return ""
    lines = [f"- {p['path']} — {p['title']}" for p in pages[:max_pages]]
    return "\n".join(lines)
