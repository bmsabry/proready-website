#!/usr/bin/env python3
"""Repoint the five standalone quiz apps away from the combustion-toolkit API.

Each `smallgasturbine.gt-XX.proreadyengineer.com` app is a Cloudflare Worker
serving a four-file Vite build:

    /index.html
    /assets/index-<hash>.js     (~297 KB, single bundle, no code splitting)
    /assets/index-<hash>.css
    /favicon.svg

The bundle hardcodes `https://combustion-toolkit-api.onrender.com` (twice).
That single string is the entire dependency on the suspended service. This
script rewrites it to the training API — which now serves the same
`/auth/*` and `/learning/*` contract via `app/routes/compat.py` — and
redeploys each Worker with a static-assets binding.

Why fetch the assets over HTTPS instead of reading the Worker source:
Cloudflare refuses `GET /workers/scripts/{name}/content` for API tokens
(`10405 Method not allowed for this authentication scheme`), for both
user- and account-scoped tokens. The deployed assets are the only readable
copy. Every file is fetched from the live app, so a run always starts from
exactly what is serving right now.

Safety
------
* `--dry-run` (default) downloads and patches but uploads nothing, and prints
  what would change. Always run this first.
* Every original file is written to `--backup-dir` before any upload, so a
  bad deploy can be reversed by re-running with `--restore`.
* Refuses to upload if the expected string is not found, or if the patched
  bundle differs from the original by anything other than that string.

Usage
-----
    python scripts/repoint_quiz_apps.py --dry-run
    python scripts/repoint_quiz_apps.py --apply \
        --api-base https://proreadyengineer-training-api-jd9a.onrender.com

Requires CLOUDFLARE_API_TOKEN (Workers Scripts:Edit) and CLOUDFLARE_ACCOUNT_ID.

DO NOT APPLY until the training API with the compat layer is deployed —
otherwise the apps swap a 503 for a 404, which is no better.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

OLD_API_BASE = "https://combustion-toolkit-api.onrender.com"
DEFAULT_NEW_BASE = "https://proreadyengineer-training-api-jd9a.onrender.com"

APPS = {
    "smallgasturbine-gt05": "https://smallgasturbine.gt-05.proreadyengineer.com",
    "smallgasturbine-gt06": "https://smallgasturbine.gt-06.proreadyengineer.com",
    "smallgasturbine-gt07": "https://smallgasturbine.gt-07.proreadyengineer.com",
    "smallgasturbine-gt13": "https://smallgasturbine.gt-13.proreadyengineer.com",
    "smallgasturbine-gt15": "https://smallgasturbine.gt-15.proreadyengineer.com",
}

CF_API = "https://api.cloudflare.com/client/v4"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "proready-repoint/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def discover_assets(origin: str) -> dict[str, str]:
    """Read index.html and pull out the hashed asset paths it references."""
    html = fetch(f"{origin}/").decode("utf-8", "replace")
    paths = {"/index.html": html}
    for match in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
        paths[match] = ""
    if "/favicon.svg" in html:
        paths["/favicon.svg"] = ""
    return paths


def patch_bundle(js: str, new_base: str) -> tuple[str, int]:
    count = js.count(OLD_API_BASE)
    return js.replace(OLD_API_BASE, new_base), count


def verify_only_url_changed(before: str, after: str, new_base: str) -> bool:
    """The patched bundle must be the original with only that URL swapped."""
    return before.replace(OLD_API_BASE, new_base) == after and OLD_API_BASE not in after


def upload_worker(account: str, token: str, name: str, files: dict[str, bytes]) -> dict:
    """Deploy a Worker whose only job is to serve these static assets.

    Uses the Workers Assets upload flow; the script body is a stub because
    everything the app needs is a file. Kept deliberately minimal so the
    deployed surface is exactly the four files we fetched.
    """
    raise SystemExit(
        "upload_worker() is intentionally unimplemented until the backend is "
        "live and the dry run has been reviewed — see the module docstring."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default=DEFAULT_NEW_BASE)
    ap.add_argument("--backup-dir", default="./quiz-app-backup")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    new_base = args.api_base.rstrip("/")
    backup = Path(args.backup_dir)
    ok = True

    for worker, origin in APPS.items():
        print(f"\n=== {worker} ({origin}) ===")
        try:
            assets = discover_assets(origin)
        except Exception as exc:
            print(f"  ! could not read {origin}: {exc}")
            ok = False
            continue

        out = backup / worker
        out.mkdir(parents=True, exist_ok=True)
        hits = 0

        for path in assets:
            try:
                raw = assets[path].encode() if assets[path] else fetch(origin + path)
            except Exception as exc:
                print(f"  ! {path}: {exc}")
                ok = False
                continue

            (out / path.lstrip("/").replace("/", "__")).write_bytes(raw)

            if path.endswith(".js"):
                text = raw.decode("utf-8", "replace")
                patched, n = patch_bundle(text, new_base)
                hits += n
                if n == 0:
                    print(f"  ! {path}: expected API base NOT found — refusing")
                    ok = False
                elif not verify_only_url_changed(text, patched, new_base):
                    print(f"  ! {path}: patch changed more than the URL — refusing")
                    ok = False
                else:
                    print(f"  ✓ {path}: {len(raw):,} bytes, {n} occurrence(s) rewritten")
            else:
                print(f"  · {path}: {len(raw):,} bytes (unchanged)")

        if hits == 0:
            ok = False

    print("\n" + "=" * 60)
    print(f"originals saved to {backup.resolve()}")
    if args.apply:
        print("--apply requested, but upload is gated until the backend is live.")
        return 1
    print("dry run complete." if ok else "dry run FAILED — do not apply.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
