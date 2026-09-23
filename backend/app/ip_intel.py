"""Where an IP address is, and whether it is a home/office line, a mobile
carrier, a data centre or a VPN — for the admin Student Activity page.

Source: ipapi.is. With IPAPI_KEY (free account: 1,000 lookups a day,
commercial use allowed) one POST resolves up to 100 addresses and returns
the network flags. Without a key the keyless tier answers 30 lookups a day
with location and provider only. Every answer is cached in ip_lookups, so
an address is looked up once; keyless rows are refreshed once a key exists.

Lookups happen only when an admin opens a learner — never on a learner's
request — within a small time budget; whatever is not resolved in time is
shown as unknown and resolved on the next open. Nothing here raises.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import release_connection
from .models import IpLookup

log = logging.getLogger(__name__)

SOURCE_KEYED = "ipapi.is"
SOURCE_KEYLESS = "ipapi.is-keyless"
# Addresses move between customers slowly; a quarter is fresh enough.
FRESH_FOR = timedelta(days=90)
BULK = 100
# Set when the service says we are out of lookups; nothing is tried again
# until then (its quota resets at UTC midnight).
_paused_until: datetime | None = None

KIND_LABELS = {
    "mobile": "Mobile network (cell data)",
    "home": "Home or office internet",
    "business": "Company network",
    "education": "University or school network",
    "government": "Government network",
    "datacenter": "Data centre / cloud server",
    "vpn": "VPN, proxy or Tor",
    "satellite": "Satellite internet",
    "local": "Private address",
    "unknown": "Network type not known yet",
}


def is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    return addr.is_global


def kind_of(row: IpLookup) -> str:
    if row.is_vpn or row.is_proxy or row.is_tor:
        return "vpn"
    if row.is_datacenter or row.company_type == "hosting":
        return "datacenter"
    if row.is_mobile:
        return "mobile"
    if row.is_satellite:
        return "satellite"
    if row.source != SOURCE_KEYED:
        return "unknown"
    return {
        "isp": "home",
        "business": "business",
        "banking": "business",
        "education": "education",
        "government": "government",
    }.get(row.company_type, "unknown")


def describe(row: IpLookup | None, ip: str) -> dict:
    if row is None:
        kind = "local" if not is_public(ip) and ip else "unknown"
        return {"ip": ip, "place": "", "country": "", "country_code": "", "city": "",
                "provider": "", "netname": "", "kind": kind, "kind_label": KIND_LABELS[kind],
                "flags_known": False}
    kind = kind_of(row)
    place = ", ".join(x for x in (row.city, row.region, row.country) if x)
    return {
        "ip": ip,
        "place": place,
        "city": row.city,
        "country": row.country,
        "country_code": row.country_code,
        "provider": row.provider,
        "netname": row.netname,
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "flags_known": row.source == SOURCE_KEYED,
    }


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _needs_lookup(row: IpLookup | None, keyed: bool) -> bool:
    if row is None:
        return True
    if keyed and row.source != SOURCE_KEYED:
        return True  # a key now exists: fetch the network flags
    at = _aware(row.looked_up_at)
    return at is None or datetime.now(timezone.utc) - at > FRESH_FOR


def _truthy(v) -> bool:
    return bool(v) and v not in ("false", "False", 0)


def parse(data: dict, keyed: bool) -> dict | None:
    """ipapi.is answer -> IpLookup column values (None if it is no answer)."""
    if not isinstance(data, dict) or data.get("error"):
        return None
    if keyed:
        loc = data.get("location") or {}
        company = data.get("company") or {}
        asn = data.get("asn") or {}
        provider = asn.get("org") or company.get("name") or ""
        return {
            "city": (loc.get("city") or "")[:120],
            "region": (loc.get("state") or "")[:120],
            "country": (loc.get("country") or "")[:120],
            "country_code": (loc.get("country_code") or "")[:4],
            "provider": str(provider)[:200],
            "netname": str(company.get("netname") or company.get("name") or "")[:200],
            "asn": int(asn.get("asn") or 0),
            "company_type": str(company.get("type") or asn.get("type") or "")[:24],
            "is_mobile": _truthy(data.get("is_mobile")),
            "is_datacenter": _truthy(data.get("is_datacenter")),
            "is_vpn": _truthy(data.get("is_vpn")),
            "is_proxy": _truthy(data.get("is_proxy")),
            "is_tor": _truthy(data.get("is_tor")),
            "is_satellite": _truthy(data.get("is_satellite")),
            "source": SOURCE_KEYED,
        }
    # Keyless: flat strings. "asn" reads "AS852 TELUS Communications Inc."
    asn_text = str(data.get("asn") or "")
    asn_no, _, org = asn_text.partition(" ")
    try:
        asn_int = int(asn_no.upper().removeprefix("AS"))
    except ValueError:
        asn_int, org = 0, asn_text
    return {
        "city": str(data.get("city") or "")[:120],
        "region": str(data.get("region") or "")[:120],
        "country": str(data.get("country") or "")[:120],
        "country_code": "",
        "provider": org[:200],
        "netname": str(data.get("company") or "")[:200],
        "asn": asn_int,
        "company_type": "",
        "is_mobile": None, "is_datacenter": None, "is_vpn": None,
        "is_proxy": None, "is_tor": None, "is_satellite": None,
        "source": SOURCE_KEYLESS,
    }


def _pause_until_midnight() -> None:
    global _paused_until
    now = datetime.now(timezone.utc)
    _paused_until = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)


def fetch(ips: list[str], *, budget_s: float = 8.0) -> dict[str, dict]:
    """Ask ipapi.is about these addresses. Returns {ip: column values} for the
    ones it answered within the time budget."""
    settings = get_settings()
    if not ips or not settings.IP_LOOKUP_ENABLED:
        return {}
    if _paused_until is not None and datetime.now(timezone.utc) < _paused_until:
        return {}
    key = settings.IPAPI_KEY.strip()
    url = settings.IP_LOOKUP_URL
    out: dict[str, dict] = {}
    deadline = time.monotonic() + budget_s
    try:
        with httpx.Client(timeout=6.0) as client:
            if key:
                for k in range(0, len(ips), BULK):
                    if time.monotonic() > deadline:
                        break
                    r = client.post(url, json={"ips": ips[k:k + BULK], "key": key})
                    if r.status_code == 429:
                        _pause_until_midnight()
                        break
                    r.raise_for_status()
                    body = r.json()
                    for ip in ips[k:k + BULK]:
                        row = parse(body.get(ip), keyed=True)
                        if row is not None:
                            out[ip] = row
            else:
                for ip in ips:
                    if time.monotonic() > deadline:
                        break
                    r = client.get(url, params={"q": ip})
                    if r.status_code == 429:
                        _pause_until_midnight()
                        break
                    if r.status_code != 200:
                        continue
                    row = parse(r.json(), keyed=False)
                    if row is not None:
                        out[ip] = row
    except Exception:
        log.warning("[ip] lookup failed; showing what is cached", exc_info=True)
    return out


def lookup_many(db: Session, ips: Iterable[str], *, budget_s: float = 8.0) -> dict[str, dict]:
    """{ip: description} for every address given; unknown ones are looked up
    (cached for next time) within the budget."""
    wanted = sorted({(ip or "").strip() for ip in ips if ip})
    public = [ip for ip in wanted if is_public(ip)]
    try:
        rows = {r.ip: r for r in db.execute(
            select(IpLookup).where(IpLookup.ip.in_(public or [""]))
        ).scalars()}
        keyed = bool(get_settings().IPAPI_KEY.strip())
        todo = [ip for ip in public if _needs_lookup(rows.get(ip), keyed)]
        # Never hold a pooled connection across network calls.
        release_connection(db)
        found = fetch(todo, budget_s=budget_s) if todo else {}
        for ip, values in found.items():
            row = rows.get(ip) or db.execute(
                select(IpLookup).where(IpLookup.ip == ip)).scalar_one_or_none()
            if row is None:
                row = IpLookup(ip=ip)
                db.add(row)
            for col, val in values.items():
                setattr(row, col, val)
            row.looked_up_at = datetime.now(timezone.utc)
            rows[ip] = row
        if found:
            try:
                db.commit()
            except IntegrityError:  # another admin tab stored it first
                db.rollback()
                rows = {r.ip: r for r in db.execute(
                    select(IpLookup).where(IpLookup.ip.in_(public or [""]))
                ).scalars()}
    except Exception:  # pragma: no cover — never break the admin page
        log.exception("[ip] lookup_many failed")
        try:
            db.rollback()
        except Exception:
            pass
        rows = {}
    return {ip: describe(rows.get(ip), ip) for ip in wanted}
