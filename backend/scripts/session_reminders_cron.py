#!/usr/bin/env python3
"""What the Render cron job `proreadyengineer-session-reminders` runs every 10 minutes.

It asks the live API to send whatever live-session reminders are due:

    POST {API_URL}/api/admin/session-reminders/run
    X-Cron-Secret: {CRON_SECRET}

and prints the summary so the run log on Render shows who was emailed.
All the logic (which courses, which registrants, the one-hour window, the
once-only guard) lives in app/session_reminders.py inside the API, so this
script needs no database access and nothing beyond `requests`.

Exit status is non-zero when the API could not be reached or refused the
call, which Render shows as a failed run.
"""
from __future__ import annotations

import os
import sys

import requests

API_URL = os.environ.get("API_URL", "https://proreadyengineer-training-api-jd9a.onrender.com").rstrip("/")
SECRET = os.environ.get("CRON_SECRET", "")


def main() -> int:
    if not SECRET:
        print("CRON_SECRET is not set", file=sys.stderr)
        return 2
    try:
        r = requests.post(
            f"{API_URL}/api/admin/session-reminders/run",
            headers={"X-Cron-Secret": SECRET},
            timeout=120,
        )
    except requests.RequestException as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1
    print(f"status: {r.status_code}")
    print(r.text[:4000])
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
