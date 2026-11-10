"""ProReadyEngineer training API.

Time-zone rules come from the `tzdata` package in requirements.txt, not from
whatever database the host operating system happens to ship.

Why this matters: governments change their clocks, and a host image can lag
the change by months. British Columbia stopped changing clocks in 2026 (no
fall-back on 1 November 2026: it stays on UTC-7), Alberta and Manitoba did the
same, and Morocco moved to permanent UTC+0. A server still reading the old
rules tells a registrant in Kitimat that a 14:00 UTC session starts at 06:00
when it starts at 07:00. requirements.txt asks for the current database at
every deploy, and this makes zoneinfo read it, so tests and production always
agree.

It has to run before the first ZoneInfo is built, which is why it lives here.
"""
import zoneinfo

try:
    import tzdata  # noqa: F401  (the packaged IANA database)
except ImportError:  # pragma: no cover - requirements.txt always installs it
    pass  # keep the host's database rather than have none at all
else:
    zoneinfo.reset_tzpath(to=())
