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
    "san diego": "America/Los_Angeles",
    "san jose": "America/Los_Angeles",
    "sacramento": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles",
    "salt lake city": "America/Denver",
    "san antonio": "America/Chicago",
    "austin": "America/Chicago",
    "fort worth": "America/Chicago",
    "oklahoma city": "America/Chicago",
    "tulsa": "America/Chicago",
    "new orleans": "America/Chicago",
    "baton rouge": "America/Chicago",
    "minneapolis": "America/Chicago",
    "st louis": "America/Chicago",
    "indianapolis": "America/Indiana/Indianapolis",
    "detroit": "America/Detroit",
    "pittsburgh": "America/New_York",
    "philadelphia": "America/New_York",
    "baltimore": "America/New_York",
    # "Washington, DC" and "Washington, D.C." (punctuation is removed before
    # matching). Without these the bare word reads as Washington State.
    "washington dc": "America/New_York",
    "washington d c": "America/New_York",
    "schenectady": "America/New_York",
    "greenville": "America/New_York",
    "charlotte": "America/New_York",
    "orlando": "America/New_York",
    "tampa": "America/New_York",
    "miami": "America/New_York",
    "jacksonville": "America/New_York",
    "hartford": "America/New_York",
    "anchorage": "America/Anchorage",
    "honolulu": "Pacific/Honolulu",
    "winnipeg": "America/Winnipeg",
    "regina": "America/Regina",
    "saskatoon": "America/Regina",
    "halifax": "America/Halifax",
    "mississauga": "America/Toronto",
    "quebec city": "America/Toronto",
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
    "new brunswick": "America/Moncton",
    "district of columbia": "America/New_York",
    "virginia": "America/New_York",  # also matches West Virginia: same zone
    "north carolina": "America/New_York",
    "south carolina": "America/New_York",
    "massachusetts": "America/New_York",
    "connecticut": "America/New_York",
    "new jersey": "America/New_York",
    "new hampshire": "America/New_York",
    "maryland": "America/New_York",
    "michigan": "America/Detroit",
    "wisconsin": "America/Chicago",
    "minnesota": "America/Chicago",
    "missouri": "America/Chicago",
    "alabama": "America/Chicago",
    "mississippi": "America/Chicago",
    "arkansas": "America/Chicago",
    "iowa": "America/Chicago",
    "new mexico": "America/Denver",  # must be found before the country "mexico"
    "utah": "America/Denver",
    "arizona": "America/Phoenix",
    "nevada": "America/Los_Angeles",
}

# Two-letter state and province codes, read only where they are written the
# usual way: straight after a comma ("Midland, TX"). Anywhere else two letters
# are too easily part of something different (a company called "NH Industries",
# the word "ok"). Only codes whose letters mean nothing else a registrant is
# likely to type are listed. Left out on purpose: codes that are also a
# country's (CA Canada, DE Germany, IL Israel, MA Morocco, TN Tunisia,
# CO Colombia, IN India, PA Panama, GA Gabon, AZ Azerbaijan...), WA (also
# Western Australia), and states that straddle two zones.
REGION_CODES: dict[str, str] = {
    "tx": "America/Chicago",
    "ok": "America/Chicago",
    "wi": "America/Chicago",
    "fl": "America/New_York",
    "ny": "America/New_York",
    "nj": "America/New_York",
    "nh": "America/New_York",
    "ct": "America/New_York",
    "oh": "America/New_York",
    "dc": "America/New_York",
    "va": "America/New_York",
    "nc": "America/New_York",
    "sc": "America/New_York",
    "mi": "America/Detroit",
    "nm": "America/Denver",
    "ut": "America/Denver",
    "nv": "America/Los_Angeles",
    "mb": "America/Winnipeg",
    "ns": "America/Halifax",
    "nb": "America/Moncton",
}


def _code_after_comma(raw: str) -> Optional[tuple[str, str]]:
    for code in re.findall(r",\s*([a-z]{2})(?![a-z])", raw):
        if code in REGION_CODES:
            return code, REGION_CODES[code]
    return None


def _find(table: dict[str, str], text: str) -> Optional[tuple[str, str]]:
    """(key, zone) for the longest key of `table` that appears in `text` as
    whole words. Longest first so "new york" beats "york" and "south africa"
    beats "africa"."""
    for key in sorted(table, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", text):
            return key, table[key]
    return None


def resolve_zone(location: str) -> Optional[str]:
    """Best IANA zone for a free-text location, or None if we can't tell.

    City beats region beats country, because "Kitimat, BC, CAN" is Pacific and
    matching on the country would put it three hours out. One exception: a
    state or province outranks a city that only shares its name with one
    elsewhere, so "London, Ontario" is Toronto time, "Lima, Ohio" is not Peru,
    "Manchester, NH" is not England and "Vancouver, Washington" is not British
    Columbia. The state counts when it is spelled out, or when its two-letter
    code is written the usual way, straight after a comma.

    A country that spans several zones is never used on its own. "Midland,
    USA" could be Texas or Michigan, and this module would rather print the
    UTC time alone than a confident local time that is an hour or three out.
    """
    if not location or not location.strip():
        return None
    raw = location.lower().strip()
    # Accent-insensitive comparison is not needed because the tables carry
    # both spellings (montreal/montréal).
    cleaned = re.sub(r"[.,/()]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    city = _find(CITY_ZONES, cleaned)
    # Look for the region in what is left once the city's own words are taken
    # out, so the "washington" of "washington dc" is not read as the state.
    region = _find(REGION_ZONES, cleaned.replace(city[0], " ") if city else cleaned)
    if region and len(region[0]) == 2 and not re.search(
        rf",\s*{re.escape(region[0])}(?![a-z])", raw
    ):
        # "bc", "ab", "on", "qc" away from a comma still place an unknown town
        # ("Fort St John BC"), but do not outrank a city: "on" is also a word.
        region_outranks_city = False
    else:
        region_outranks_city = True
    region = region or _code_after_comma(raw)
    if city and region and region[1] != city[1] and region_outranks_city:
        return region[1]
    if city:
        return city[1]
    country = _find(COUNTRY_ZONES, cleaned)
    if region and not (country and not region_outranks_city):
        return region[1]
    # A named country beats a stray two-letter word: "Stratford on Avon, UK".
    return country[1] if country else None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


# Three Canadian provinces stopped changing clocks in 2026 and stay on what
# used to be their summer time. The IANA database labels that with the name of
# the zone to the east ("MST" for Vancouver, "CST" for Edmonton, "EST" for
# Winnipeg), which reads as the wrong time zone to someone who lives there:
# each province still calls its own time Pacific, Mountain and Central. The
# hour is right either way; this only fixes the label a person sees.
_LOCAL_NAME_FOR_BORROWED_ABBREV: dict[str, tuple[str, str]] = {
    "America/Vancouver": ("MST", "PT"),
    "America/Edmonton": ("CST", "MT"),
    "America/Winnipeg": ("EST", "CT"),
}


def zone_abbrev(local: datetime) -> str:
    """The zone abbreviation to print next to a local time (e.g. "EDT", "PT")."""
    abbrev = local.strftime("%Z")
    borrowed, own = _LOCAL_NAME_FOR_BORROWED_ABBREV.get(
        getattr(local.tzinfo, "key", ""), ("", "")
    )
    return own if abbrev == borrowed and own else abbrev


# -----------------------------------------------------------------------------
# When a course's session starts, date by date
# -----------------------------------------------------------------------------
# Bassam sets the start on his own clock — New York — and every other place's
# time is derived from that, one session date at a time. A single stored UTC
# time cannot carry this: 14:00 UTC is 10:00 in New York in September and
# 09:00 in November, so a fixed UTC time moves the instructor's own start by
# an hour when the US changes its clocks, and moves Europe's on a different
# weekend. Saudi Arabia and Algeria never change. So the rule is:
#
#   his wall-clock time on that date, in his zone, with that date's rules
#     -> the UTC instant
#       -> each viewer's zone, with that date's rules for them.
#
# `session_time_utc` survives only as a mirror of Day 1 (older clients read
# it) and as the fallback for a course that predates `session_time_local`.

INSTRUCTOR_ZONE = "America/New_York"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def valid_hhmm(value: Optional[str]) -> bool:
    return bool(value) and bool(_HHMM.match(value or ""))


def is_known_zone(name: Optional[str]) -> bool:
    try:
        ZoneInfo((name or "").strip())
        return bool((name or "").strip())
    except (ZoneInfoNotFoundError, ValueError):
        return False


def _zone(name: Optional[str]) -> ZoneInfo:
    return ZoneInfo(name.strip()) if is_known_zone(name) else ZoneInfo(INSTRUCTOR_ZONE)


def wall_clock_to_utc(day: date, hhmm: str, zone: Optional[str]) -> datetime:
    """`hhmm` on `day` as read on a clock in `zone`, as a UTC instant."""
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=_zone(zone)).astimezone(timezone.utc)


def utc_to_wall_clock(day: date, hhmm_utc: str, zone: Optional[str]) -> str:
    """`hhmm_utc` on `day` (UTC), as read on a clock in `zone`."""
    hh, mm = (int(x) for x in hhmm_utc.split(":"))
    instant = datetime.combine(day, time(hh, mm), tzinfo=timezone.utc)
    return instant.astimezone(_zone(zone)).strftime("%H:%M")


def course_days(course: Any) -> list[date]:
    out = []
    for d in course.day_dates or []:
        try:
            out.append(date.fromisoformat(str(d)))
        except (TypeError, ValueError):
            continue
    return out


def _first_day(course: Any) -> date:
    days = course_days(course)
    if days:
        return days[0]
    start = getattr(course, "start_date", None)
    return start if isinstance(start, date) else date.today()


def session_time_local(course: Any) -> str:
    return (getattr(course, "session_time_local", "") or "").strip()


def session_timezone(course: Any) -> str:
    name = (getattr(course, "session_timezone", "") or "").strip()
    return name if is_known_zone(name) else INSTRUCTOR_ZONE


def has_session_time(course: Any) -> bool:
    return valid_hhmm(session_time_local(course)) or valid_hhmm(
        (course.session_time_utc or "").strip()
    )


def session_start_utc(course: Any, day: date) -> Optional[datetime]:
    """When `course`'s session on `day` starts, as a UTC instant (or None)."""
    local = session_time_local(course)
    if valid_hhmm(local):
        return wall_clock_to_utc(day, local, session_timezone(course))
    legacy = (course.session_time_utc or "").strip()
    if valid_hhmm(legacy):
        hh, mm = (int(x) for x in legacy.split(":"))
        return datetime.combine(day, time(hh, mm), tzinfo=timezone.utc)
    return None


def session_starts_utc(course: Any) -> list[datetime]:
    """One UTC start per session day, in day order (empty when no time is set)."""
    out = []
    for day in course_days(course):
        start = session_start_utc(course, day)
        if start is not None:
            out.append(start)
    return out


def day_one_utc_hhmm(course: Any) -> str:
    """Day 1's start as "HH:MM" UTC — the legacy single-time field."""
    start = session_start_utc(course, _first_day(course))
    return start.strftime("%H:%M") if start else ""


def instructor_hhmm(course: Any) -> str:
    """The start on the instructor's clock, derived for a legacy UTC-only course."""
    local = session_time_local(course)
    if valid_hhmm(local):
        return local
    legacy = (course.session_time_utc or "").strip()
    if valid_hhmm(legacy):
        return utc_to_wall_clock(_first_day(course), legacy, session_timezone(course))
    return ""


def set_session_time(course: Any, local_hhmm: str, zone: Optional[str] = None) -> None:
    """Set (or clear, with "") the start on the instructor's clock.

    Keeps session_time_utc as the Day 1 mirror, so clearing the time clears
    both and the startup backfill can never bring an old time back.
    """
    if zone is not None:
        course.session_timezone = zone.strip() or INSTRUCTOR_ZONE
    course.session_time_local = local_hhmm.strip()
    if course.session_time_local:
        refresh_utc_mirror(course)
    else:
        course.session_time_utc = ""


def set_session_time_from_utc(course: Any, hhmm_utc: str) -> None:
    """Legacy input: a UTC time, read as Day 1's instant on the instructor's clock."""
    t = hhmm_utc.strip()
    if not t:
        set_session_time(course, "")
        return
    set_session_time(course, utc_to_wall_clock(_first_day(course), t, session_timezone(course)))


def refresh_utc_mirror(course: Any) -> None:
    """Recompute session_time_utc after the time, zone or day dates change.

    A course with no instructor time (legacy, UTC only) is left alone.
    """
    if valid_hhmm(session_time_local(course)):
        course.session_time_utc = day_one_utc_hhmm(course)


def local_schedule(
    *,
    session_time_utc: str,
    duration_minutes: int,
    day_dates: list[str],
    locations: list[str],
    extra_zones: Optional[list[str]] = None,
    starts_utc: Optional[list[datetime]] = None,
    instructor_time: str = "",
) -> dict[str, Any]:
    """Per-location local times for every session day.

    Pass `starts_utc` (one instant per session day, from session_starts_utc)
    for a course whose start is set on the instructor's clock; the instants
    then differ by date across a clock change, as they should. The older
    `session_time_utc` + `day_dates` pair is still accepted.

    Returns zones we resolved, and — separately and explicitly —
    the locations we could not resolve, so a caller can ask rather than
    print something plausible and wrong.
    """
    if starts_utc is None and (
        not session_time_utc or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", session_time_utc)
    ):
        return {
            "ok": False,
            "error": (
                "This course has no session time set, so local times cannot "
                "be calculated. Read the course's page on the website for the "
                "published times, or set it with update_course."
            ),
        }
    if not day_dates and not starts_utc:
        return {"ok": False, "error": "This course has no day_dates set."}

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
    if starts_utc is not None:
        days_utc = sorted(starts_utc)
    else:
        hh, mm = (int(x) for x in session_time_utc.split(":"))
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
                    "abbrev": zone_abbrev(start),
                    # The offset ON THIS DATE — it changes across a clock change.
                    "utc_offset": start.strftime("%z"),
                    # True when the local calendar day differs from the UTC
                    # one — the thing that quietly makes someone a day late.
                    "day_shift": start.date() != start_utc.date(),
                }
            )
        zones_out.append(
            {
                "timezone": zone,
                "locations": locs,
                # Day 1's offset; each session carries its own.
                "utc_offset": sessions[0]["utc_offset"] if sessions else "",
                "sessions": sessions,
            }
        )

    utc_times = sorted({_fmt(d) for d in days_utc})
    out: dict[str, Any] = {
        "ok": True,
        "session_time_utc": _fmt(days_utc[0]) if days_utc else session_time_utc,
        "duration_minutes": dur,
        "utc_sessions": [
            {"date": d.date().isoformat(), "start": _fmt(d)} for d in days_utc
        ],
        "zones": zones_out,
        "unresolved_locations": unresolved,
        "note": (
            "Times are computed from the IANA timezone database, so daylight "
            "saving on each session date is already accounted for. "
            + (
                "Always give the UTC time alongside the local times so anyone "
                "whose zone is not listed can convert for themselves — and give "
                "it per date from utc_sessions: it differs between dates here "
                "because a clock change falls inside the cohort."
                if len(utc_times) > 1
                else f"Always give {utc_times[0] if utc_times else session_time_utc} UTC "
                "alongside the local times so anyone whose zone is not listed can "
                "convert for themselves."
            )
        ),
    }
    if instructor_time:
        out["instructor_time"] = instructor_time
    return out
