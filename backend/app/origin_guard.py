"""Refuse requests that another website makes on a signed-in person's behalf.

The admin and learner sessions are cookies marked SameSite=None (the site and
the API are different hosts, and preview deployments have to work). A browser
therefore attaches them to a request that ANY page starts. CORS only stops that
page from reading the answer; it does not stop the request from running. So a
page the owner merely opened could mark a registration paid, grant a course or
replace the simulator, and a page a learner opened could set their password or
erase their progress.

Every browser states where such a request comes from in the `Origin` header.
This refuses a state-changing request that carries a session cookie and names
an origin that is not ours.

Left alone, on purpose:
  * requests with no Origin (curl, the cron job, Stripe and Resend webhooks);
  * requests without a session cookie (the public forms, and the quiz apps,
    which authenticate with a bearer token);
  * the call-home beacon and the usage pings, which are posted from files
    opened off-site by design.
"""
from __future__ import annotations

from typing import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .config import get_settings
from .deps import SESSION_COOKIE_NAME
from .learner_auth import LEARNER_COOKIE_NAME

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SESSION_COOKIES = (SESSION_COOKIE_NAME, LEARNER_COOKIE_NAME)
_OPEN_PATHS = (
    "/api/academy/beacon",
    "/api/track/",
    "/api/academy/webhook/",
    "/api/webhooks/",
)


def _host(value: str) -> str:
    """Lower-case host name of an origin or a Host header, without the port."""
    value = (value or "").strip().lower()
    if "://" in value:
        return urlsplit(value).hostname or ""
    return value.split(":")[0]


def origin_is_ours(origin: str, request_host: str) -> bool:
    """True when `origin` is the site, a listed preview, or the API itself."""
    settings = get_settings()
    if origin in settings.cors_origins_list:
        return True
    host = _host(origin)
    if not host:
        return False  # "null" (a local file, a sandboxed frame) is never ours
    return host in {_host(request_host), _host(settings.API_PUBLIC_URL)}


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def refuse_cross_site_writes(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _UNSAFE_METHODS and not request.url.path.startswith(_OPEN_PATHS):
            origin = request.headers.get("origin")
            if (
                origin
                and any(name in request.cookies for name in _SESSION_COOKIES)
                and not origin_is_ours(origin, request.headers.get("host", ""))
            ):
                return JSONResponse(
                    {"detail": "This request came from another website and was refused."},
                    status_code=403,
                )
        return await call_next(request)
