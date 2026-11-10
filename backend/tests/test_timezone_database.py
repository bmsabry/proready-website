"""The time-zone database the API reads must be the current one.

A stale database is silent: every conversion still returns an answer, just
the wrong hour for the places whose rules changed. These pin the 2026 changes
that affect people this business teaches, and the labels they are shown.
"""
from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import app  # noqa: F401  (selects the packaged database)
from app.local_times import local_schedule, zone_abbrev
from app.session_reminders import when_lines

NOV_14 = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)  # 09:00 New York
JULY = datetime(2027, 7, 15, 14, 0, tzinfo=timezone.utc)


def _at(instant: datetime, zone: str) -> str:
    return instant.astimezone(ZoneInfo(zone)).strftime("%H:%M %z")


def test_zoneinfo_reads_the_packaged_database_not_the_hosts():
    assert zoneinfo.TZPATH == ()


def test_provinces_that_stopped_changing_clocks_in_2026():
    # British Columbia: permanent UTC-7 (no fall-back on 1 Nov 2026).
    assert _at(NOV_14, "America/Vancouver") == "07:00 -0700"
    assert _at(JULY, "America/Vancouver") == "07:00 -0700"
    # Alberta: permanent UTC-6. Manitoba: permanent UTC-5.
    assert _at(NOV_14, "America/Edmonton") == "08:00 -0600"
    assert _at(NOV_14, "America/Winnipeg") == "09:00 -0500"
    # The US west coast still changes: Seattle is an hour behind Vancouver in winter.
    assert _at(NOV_14, "America/Los_Angeles") == "06:00 -0800"
    assert _at(JULY, "America/Los_Angeles") == "07:00 -0700"


def test_morocco_is_on_utc_all_year():
    assert _at(NOV_14, "Africa/Casablanca") == "14:00 +0000"
    assert _at(JULY, "Africa/Casablanca") == "14:00 +0000"


def test_labels_read_as_the_residents_own_zone():
    # The database borrows the neighbouring zone's name for these three.
    assert zone_abbrev(NOV_14.astimezone(ZoneInfo("America/Vancouver"))) == "PT"
    assert zone_abbrev(NOV_14.astimezone(ZoneInfo("America/Edmonton"))) == "MT"
    assert zone_abbrev(NOV_14.astimezone(ZoneInfo("America/Winnipeg"))) == "CT"
    # Before the change the real abbreviations still apply.
    before = datetime(2025, 12, 1, 14, 0, tzinfo=timezone.utc)
    assert zone_abbrev(before.astimezone(ZoneInfo("America/Vancouver"))) == "PST"
    # Everyone else is untouched.
    assert zone_abbrev(NOV_14.astimezone(ZoneInfo("America/New_York"))) == "EST"
    assert zone_abbrev(JULY.astimezone(ZoneInfo("America/New_York"))) == "EDT"
    assert zone_abbrev(NOV_14.astimezone(ZoneInfo("America/Denver"))) == "MST"
    assert zone_abbrev(NOV_14.astimezone(ZoneInfo("Asia/Riyadh"))) == "+03"


def test_the_reminder_line_for_this_novembers_cohort():
    lines, zone = when_lines(NOV_14, "Kitimat, BC, CAN")
    assert zone == "America/Vancouver"
    assert lines == [
        "14:00 UTC on Saturday, November 14",
        "07:00 PT in Kitimat, BC, CAN — your local time",
    ]
    lines, _ = when_lines(NOV_14, "Calgary, Alberta")
    assert lines[1] == "08:00 MT in Calgary, Alberta — your local time"


def test_the_schedule_tool_reports_the_same_hours_and_labels():
    out = local_schedule(
        session_time_utc="14:00", duration_minutes=340,
        day_dates=["2026-11-14", "2026-11-15", "2026-11-21", "2026-11-22"],
        locations=["Kitimat, BC, CAN", "Seattle", "Yanbu"],
    )
    first = {z["timezone"]: z["sessions"][0] for z in out["zones"]}
    assert (first["America/Vancouver"]["start"], first["America/Vancouver"]["abbrev"]) == ("07:00", "PT")
    assert first["America/Vancouver"]["utc_offset"] == "-0700"
    assert (first["America/Los_Angeles"]["start"], first["America/Los_Angeles"]["abbrev"]) == ("06:00", "PST")
    assert first["Asia/Riyadh"]["start"] == "17:00"
