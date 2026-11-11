#!/usr/bin/env python3
"""What the Render cron job `proreadyengineer-consult-tick` runs every 5 minutes.

It asks the live API to do everything that is due for consulting bookings:

    POST {API_URL}/api/admin/consult/tick      with X-Cron-Secret: {CRON_SECRET}

and prints the summary, so the run log on Render shows what happened: holds
placed, clients asked for another card, bookings cancelled for want of a hold,
reminders sent, attendance read, summaries sent to the owner, outcomes
applied, and anything that failed (`problems`).

All the logic lives inside the API (app/consult_auto.py), so this script needs
no database access and nothing beyond `requests`. Running it twice, or at any
time by hand, is harmless: the second call finds nothing left to do.

Exit status, which Render shows as a failed run when it is not 0:

  0  the tick ran and reported no problem
  1  the API could not be reached, or refused the call
  2  CRON_SECRET is not set
  3  the tick ran, and at least one step raised an error (`problems` in the
     answer names the booking). The API tries it again on the next tick, so
     one failed run that is followed by good ones needs nobody; a run of
     failures is what should be looked at. A card that is declined, or an
     email the service refuses, is not a problem in this sense.
"""
from __future__ import annotations

import os
import sys

import requests

API_URL = os.environ.get("API_URL", "https://proreadyengineer-training-api-jd9a.onrender.com").rstrip("/")
SECRET = os.environ.get("CRON_SECRET", "")
PATH = "/api/admin/consult/tick"


def main() -> int:
    if not SECRET:
        print("CRON_SECRET is not set", file=sys.stderr)
        return 2
    try:
        r = requests.post(f"{API_URL}{PATH}", headers={"X-Cron-Secret": SECRET}, timeout=240)
    except requests.RequestException as exc:
        print(f"{PATH}: request failed: {exc}", file=sys.stderr)
        return 1
    print(f"{PATH}: status {r.status_code}")
    print(r.text[:6000])
    if not r.ok:
        return 1
    try:
        answer = r.json()
    except ValueError:
        print(f"{PATH}: the answer is not JSON", file=sys.stderr)
        return 1
    if answer.get("problems") or answer.get("ok") is False:
        print(f"{PATH}: {len(answer.get('problems') or [])} step(s) failed in this run", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
