#!/usr/bin/env python3
"""What the Render cron job `proreadyengineer-session-reminders` runs every 10 minutes.

It asks the live API to do two things, each with `X-Cron-Secret: {CRON_SECRET}`:

    POST {API_URL}/api/admin/session-reminders/run   — send the live-session
                                                       reminders that are due
    POST {API_URL}/api/admin/email-delivery/sweep    — check with Resend what
                                                       happened to recent customer
                                                       emails; alert on any that
                                                       were not delivered

and prints both summaries so the run log on Render shows what happened.
All the logic lives inside the API (app/session_reminders.py,
app/delivery_watch.py), so this script needs no database access and nothing
beyond `requests`.

Both calls are always made, even if the first fails. Exit status is non-zero
when either could not be reached or was refused, which Render shows as a
failed run.
"""
from __future__ import annotations

import os
import sys

import requests

API_URL = os.environ.get("API_URL", "https://proreadyengineer-training-api-jd9a.onrender.com").rstrip("/")
SECRET = os.environ.get("CRON_SECRET", "")
CALLS = (
    "/api/admin/session-reminders/run",
    "/api/admin/email-delivery/sweep",
)


def call(path: str) -> bool:
    try:
        r = requests.post(f"{API_URL}{path}", headers={"X-Cron-Secret": SECRET}, timeout=120)
    except requests.RequestException as exc:
        print(f"{path}: request failed: {exc}", file=sys.stderr)
        return False
    print(f"{path}: status {r.status_code}")
    print(r.text[:4000])
    return r.ok


def main() -> int:
    if not SECRET:
        print("CRON_SECRET is not set", file=sys.stderr)
        return 2
    results = [call(path) for path in CALLS]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
