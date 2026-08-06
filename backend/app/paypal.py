"""Minimal PayPal Orders v2 client.

Speaks only the three calls the payment routes need — create, capture,
get — over httpx (same HTTP library the Resend emailer uses). OAuth
client-credentials tokens are cached in module state until 60s before
expiry so we don't hit /v1/oauth2/token on every order.

Secrets never appear in exceptions or logs: error messages carry status
codes and (truncated) PayPal response bodies, never the client secret or
a bearer token.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from .config import get_settings

log = logging.getLogger(__name__)


class PayPalError(RuntimeError):
    """Raised for any PayPal API failure (network, auth, non-2xx, bad shape)."""


# Module-level token cache: {"access_token": str, "expires_at": epoch_seconds}.
_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}


def _token() -> str:
    """Client-credentials access token, cached until 60s before expiry."""
    now = time.time()
    if _token_cache["access_token"] and now < float(_token_cache["expires_at"]):
        return str(_token_cache["access_token"])

    settings = get_settings()
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                f"{settings.paypal_base_url}/v1/oauth2/token",
                auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                data={"grant_type": "client_credentials"},
            )
    except httpx.HTTPError as exc:
        raise PayPalError(f"PayPal token request failed: {exc}") from exc
    if r.status_code >= 300:
        # Deliberately no response body here — auth error bodies are the one
        # place PayPal echoes credential hints.
        raise PayPalError(f"PayPal token request rejected (status={r.status_code})")

    data = r.json()
    token = str(data.get("access_token") or "")
    if not token:
        raise PayPalError("PayPal token response missing access_token")
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + float(data.get("expires_in") or 0) - 60.0
    return token


def _request(method: str, path: str, json_body: Optional[dict] = None) -> dict:
    token = _token()
    settings = get_settings()
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.request(
                method,
                f"{settings.paypal_base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise PayPalError(f"PayPal {method} {path} failed: {exc}") from exc
    if r.status_code >= 300:
        raise PayPalError(
            f"PayPal {method} {path} returned {r.status_code}: {r.text[:300]}"
        )
    try:
        return r.json() if r.content else {}
    except ValueError as exc:
        raise PayPalError(f"PayPal {method} {path} returned a non-JSON body") from exc


def create_order(
    amount_cents: int, currency: str, description: str, custom_id: str
) -> str:
    """Create a CAPTURE-intent order; returns the PayPal order id."""
    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": currency.upper(),
                    # Integer math — no float rounding in money values.
                    "value": f"{amount_cents // 100}.{amount_cents % 100:02d}",
                },
                # PayPal caps both fields at 127 chars.
                "description": description[:127],
                "custom_id": custom_id[:127],
            }
        ],
    }
    data = _request("POST", "/v2/checkout/orders", body)
    order_id = str(data.get("id") or "")
    if not order_id:
        raise PayPalError("PayPal create-order response missing id")
    return order_id


def capture_order(order_id: str) -> dict:
    """Capture an approved order. Raises unless the result is COMPLETED."""
    data = _request("POST", f"/v2/checkout/orders/{order_id}/capture", {})
    if data.get("status") != "COMPLETED":
        raise PayPalError(
            f"PayPal capture for order {order_id} not completed "
            f"(status={data.get('status')})"
        )
    return data


def get_order(order_id: str) -> dict:
    return _request("GET", f"/v2/checkout/orders/{order_id}")
