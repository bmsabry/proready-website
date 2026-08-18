"""Session times in each registrant's own local zone.

Generic zone labels ("UTC+1", "Eastern") make a reader do work and get it
wrong. People are registered from specific places — Yanbu, Laghouat,
Kitimat, Montréal — and the useful sentence is "17:00 for you in Saudi
Arabia", not "UTC+3".

Two rules shape this module:

  The arithmetic is done here, not by the model. Offsets move: 14:00 UTC
  is 10:00 in Montréal in September and 09:00 in December, and Algeria
  does not observe DST while Britain does. zoneinfo knows all of that
  from the IANA database; a language model doing offset maths in its head
  does not, and an hour wrong in a joining email is an attendee who
  misses the session.

  An unrecognised place is reported as unrecognised. It is never quietly
  bucketed into UTC — a confident wrong local time is worse than an
  admitted gap, because nobody checks the one that looks right.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

# Place → IANA zone. Cities first (they win over the country they sit in),
# then countries. Deliberately hand-curated rather than a geocoding service:
# these are the places this business actually recruits from, and a lookup
# that works offline cannot fail in the middle of writing an email.
CITY_ZONES: dict[str, str] = {
    # North America
    "west chester": "America/New_York",
    "cincinnati": "America/New_York",
    "mason": "America/New_York",
    "montreal": "America/Toronto",
    "montréal": "America/Toronto",
    "toronto": "America/Toronto",
    "ottawa": "America/Toronto",
    "kitimat": "America/Vancouver",
    "vancouver": "America/Vancouver",
    "calgary": "America/Edmonton",
    "edmonton": "America/Edmonton",
    "houston": "America/Chicago",
    "dallas": "America/Chicago",
    "chicago": "America/Chicago",
    "new york": "America/New_York",
    "boston": "America/New_York",
    "atlanta": "America/New_York",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    # UK / Europe
    "london": "Europe/London",
    "kingston upon thames": "Europe/London",
    "manchester": "Europe/London",
    "aberdeen": "Europe/London",
    "glasgow": "Europe/London",
    "paris": "Europe/Paris",
    "lyon": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "munich": "Europe/Berlin",
    "milan": "Europe/Rome",
    "rome": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "amsterdam": "Europe/Amsterdam",
    "rotterdam": "Europe/Amsterdam",
    "oslo": "Europe/Oslo",
    "stavanger": "Europe/Oslo",
    "stockholm": "Europe/Stockholm",
    "copenhagen": "Europe/Copenhagen",
    "zurich": "Europe/Zurich",
    "vienna": "Europe/Vienna",
    "warsaw": "Europe/Warsaw",
    "istanbul": "Europe/Istanbul",
    "moscow": "Europe/Moscow",
    # Africa
    "algiers": "Africa/Algiers",
    "alger": "Africa/Algiers",
    "laghouat": "Africa/Algiers",
    "hassi messaoud": "Africa/Algiers",
    "oran": "Africa/Algiers",
    "cairo": "Africa/Cairo",
    "alexandria": "Africa/Cairo",
    "tripoli": "Africa/Tripoli",
    "tunis": "Africa/Tunis",
    "casablanca": "Africa/Casablanca",
    "lagos": "Africa/Lagos",
    "port harcourt": "Africa/Lagos",
    "luanda": "Africa/Luanda",
    "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    # Middle East
    "yanbu": "Asia/Riyadh",
    "riyadh": "Asia/Riyadh",
    "jubail": "Asia/Riyadh",
    "dammam": "Asia/Riyadh",
    "dhahran": "Asia/Riyadh",
    "jeddah": "Asia/Riyadh",
    "abu dhabi": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "sharjah": "Asia/Dubai",
    "doha": "Asia/Qatar",
    "kuwait": "Asia/Kuwait",
    "manama": "Asia/Bahrain",
    "muscat": "Asia/Muscat",
    "tehran": "Asia/Tehran",
    "baghdad": "Asia/Baghdad",
    "basra": "Asia/Baghdad",
    # Asia-Pacific
    "karachi": "Asia/Karachi",
    "lahore": "Asia/Karachi",
    "islamabad": "Asia/Karachi",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "dhaka": "Asia/Dhaka",
    "bangkok": "Asia/Bangkok",
    "singapore": "Asia/Singapore",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "jakarta": "Asia/Jakarta",
    "manila": "Asia/Manila",
    "hong kong": "Asia/Hong_Kong",
    "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "seoul": "Asia/Seoul",
    "tokyo": "Asia/Tokyo",
    "perth": "Australia/Perth",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "auckland": "Pacific/Auckland",
    # Latin America
    "mexico city": "America/Mexico_City",
    "monterrey": "America/Monterrey",
    "bogota": "America/Bogota",
    "lima": "America/Lima",
    "santiago": "America/Santiago",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "rio de janeiro": "America/Sao_Paulo",
    "sao paulo": "America/Sao_Paulo",
    "são paulo": "America/Sao_Paulo",
}

COUNTRY_ZONES: dict[str, str] = {
    "algeria": "Africa/Algiers",
    "dz": "Africa/Algiers",
    "saudi arabia": "Asia/Riyadh",
    "ksa": "Asia/Riyadh",
    "sa": "Asia/Riyadh",
    "uae": "Asia/Dubai",
    "united arab emirates": "Asia/Dubai",
    "qatar": "Asia/Qatar",
    "kuwait": "Asia/Kuwait",
    "bahrain": "Asia/Bahrain",
    "oman": "Asia/Muscat",
    "iraq": "Asia/Baghdad",
    "iran": "Asia/Tehran",
    "egypt": "Africa/Cairo",
    "libya": "Africa/Tripoli",
    "tunisia": "Africa/Tunis",
    "morocco": "Africa/Casablanca",
    "nigeria": "Africa/Lagos",
    "angola": "Africa/Luanda",
    "south africa": "Africa/Johannesburg",
    "uk": "Europe/London",
    "united kingdom": "Europe/London",
    "england": "Europe/London",
    "scotland": "Europe/London",
    "ireland": "Europe/Dublin",
    "france": "Europe/Paris",
    "germany": "Europe/Berlin",
    "italy": "Europe/Rome",
    "spain": "Europe/Madrid",
    "portugal": "Europe/Lisbon",
    "netherlands": "Europe/Amsterdam",
    "norway": "Europe/Oslo",
    "sweden": "Europe/Stockholm",
    "denmark": "Europe/Copenhagen",
    "switzerland": "Europe/Zurich",
    "austria": "Europe/Vienna",
    "poland": "Europe/Warsaw",
    "turkey": "Europe/Istanbul",
    "russia": "Europe/Moscow",
    "india": "Asia/Kolkata",
    "pakistan": "Asia/Karachi",
    "bangladesh": "Asia/Dhaka",
    "thailand": "Asia/Bangkok",
    "singapore": "Asia/Singapore",
    "malaysia": "Asia/Kuala_Lumpur",
    "indonesia": "Asia/Jakarta",
    "philippines": "Asia/Manila",
    "china": "Asia/Shanghai",
    "japan": "Asia/Tokyo",
    "korea": "Asia/Seoul",
    "south korea": "Asia/Seoul",
    "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland",
    "mexico": "America/Mexico_City",
    "brazil": "America/Sao_Paulo",
    "colombia": "America/Bogota",
    "peru": "America/Lima",
    "chile": "America/Santiago",
    "argentina": "America/Argentina/Buenos_Aires",
}

# Canadian provinces and US states, for "Kitimat, BC, CAN" style strings
# where the city may be unknown but the region pins the zone.
REGION_ZONES: dict[str, str] = {
    "bc": "America/Vancouver",
    "british columbia": "America/Vancouver",
    "alberta": "America/Edmonton",
    "ab": "America/Edmonton",
    "ontario": "America/Toronto",
    "on": "America/Toronto",
    "quebec": "America/Toronto",
    "qc": "America/Toronto",
    "québec": "America/Toronto",
    "nova scotia": "America/Halifax",
    "newfoundland": "America/St_Johns",
    "manitoba": "America/Winnipeg",
    "saskatchewan": "America/Regina",
    "texas": "America/Chicago",
    "california": "America/Los_Angeles",
    "ohio": "America/New_York",
    "florida": "America/New_York",
    "new york": "America/New_York",
    "pennsylvania": "America/New_York",
    "illinois": "America/Chicago",
    "colorado": "America/Denver",
    "washington": "America/Los_Angeles",
    "oklahoma": "America/Chicago",
    "louisiana": "America/Chicago",
}

# Bare country words that appear inside longer strings ("Kitimat, BC, CAN").
COUNTRY_SUFFIX: dict[str, str] = {
    "can": "America/Toronto",
    "canada": "America/Toronto",
    "usa": "America/New_York",
    "us": "America/New_York",
    "united states": "America/New_York",
}


def resolve_zone(location: str) -> Optional[str]:
    """Best IANA zone for a free-text location, or None if we can't tell.

    Order matters: city beats region beats country, because "Kitimat, BC,
    CAN" is Pacific and matching on "CAN" first would put it on Toronto
    time — three hours out.
    """
    if not location or not location.strip():
        return None
    raw = location.lower().strip()
    # Normalise separators and strip accents-insensitive comparison is not
    # needed because the tables carry both spellings (montreal/montréal).
    cleaned = re.sub(r"[.,/()]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = cleaned.split(" ")

    for table in (CITY_ZONES, REGION_ZONES, COUNTRY_ZONES):
        # Longest key first so "new york" beats "york", "south africa"
        # beats "africa".
        for key in sorted(table, key=len, reverse=True):
            if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", cleaned):
                return table[key]

    for key, zone in COUNTRY_SUFFIX.items():
        if key in tokens:
            return zone
    return None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def local_schedule(
    *,
    session_time_utc: str,
    duration_minutes: int,
    day_dates: list[str],
    locations: list[str],
    extra_zones: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Per-location local times for every session day.

    Returns zones we resolved, and — separately and explicitly —
    the locations we could not resolve, so a caller can ask rather than
    print something plausible and wrong.
    """
    if not session_time_utc or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", session_time_utc):
        return {
            "ok": False,
            "error": (
                "This course has no session_time_utc set, so local times cannot "
                "be calculated. Read the course's page on the website for the "
                "published times, or set it with update_course."
            ),
        }
    if not day_dates:
        return {"ok": False, "error": "This course has no day_dates set."}

    hh, mm = (int(x) for x in session_time_utc.split(":"))
    dur = max(0, int(duration_minutes or 0))

    resolved: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for loc in locations:
        zone = resolve_zone(loc)
        if zone is None:
            if loc and loc not in unresolved:
                unresolved.append(loc)
            continue
        resolved.setdefault(zone, [])
        if loc not in resolved[zone]:
            resolved[zone].append(loc)

    # Zones the caller worked out another way (e.g. from a company name that
    # names a city the bare location does not).
    for zone in extra_zones or []:
        resolved.setdefault(zone, [])

    days_utc: list[datetime] = []
    for d in day_dates:
        try:
            day = date.fromisoformat(d)
        except (TypeError, ValueError):
            continue
        days_utc.append(datetime.combine(day, time(hh, mm), tzinfo=timezone.utc))

    zones_out = []
    for zone, locs in sorted(resolved.items()):
        try:
            tz = ZoneInfo(zone)
        except ZoneInfoNotFoundError:  # pragma: no cover - depends on tzdata
            log.warning("[local_times] zone %s unavailable", zone)
            continue
        sessions = []
        for start_utc in days_utc:
            start = start_utc.astimezone(tz)
            end = (start_utc + timedelta(minutes=dur)).astimezone(tz)
            sessions.append(
                {
                    "date": start.date().isoformat(),
                    "weekday": start.strftime("%A"),
                    "start": _fmt(start),
                    "end": _fmt(end) if dur else "",
                    "abbrev": start.strftime("%Z"),
                    # True when the local calendar day differs from the UTC
                    # one — the thing that quietly makes someone a day late.
                    "day_shift": start.date() != start_utc.date(),
                }
            )
        zones_out.append(
            {
                "timezone": zone,
                "locations": locs,
                "utc_offset": sessions[0] and datetime.now(tz).strftime("%z"),
                "sessions": sessions,
            }
        )

    return {
        "ok": True,
        "session_time_utc": session_time_utc,
        "duration_minutes": dur,
        "utc_sessions": [
            {"date": d.date().isoformat(), "start": _fmt(d)} for d in days_utc
        ],
        "zones": zones_out,
        "unresolved_locations": unresolved,
        "note": (
            "Times are computed from the IANA timezone database, so daylight "
            "saving on each session date is already accounted for. Always give "
            f"{session_time_utc} UTC alongside the local times so anyone whose "
            "zone is not listed can convert for themselves."
        ),
    }
