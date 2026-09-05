#!/usr/bin/env python3
"""Fix the login-card footer of the five standalone quiz apps.

Each `smallgasturbine.gt-XX.proreadyengineer.com` app is a Cloudflare Worker
serving a Vite build whose login card ends with a line left over from the
combustion-toolkit era:

    Your ProReadyEngineer account works across combustion-toolkit.proreadyengineer.com
    and this learning module.

That site has been suspended since 2026-05-31 (it answers 503), no learner
has any entitlement there, and the line reads to a paying learner as if they
had been given a product they never bought. The apps also have no "forgot
password" screen. This script replaces that one JSX expression with

    Forgot your password? [Reset it by email link] — one ProReadyEngineer
    account opens every module.

pointing at the platform's reset route (/learn/signin?reason=password),
which proves the mailbox by email link and then offers a new password.

Mechanics are the same as repoint_quiz_apps.py: the deployed assets are the
only readable copy of these apps (Cloudflare refuses to serve Worker source
to API tokens), so every file is fetched from the live app, the bundle is
patched, and the patch is refused unless it changed exactly that expression
and nothing else. Originals go to --backup-dir first.

Deploying needs wrangler (npx) with CLOUDFLARE_API_TOKEN (Workers Scripts:
Edit) and CLOUDFLARE_ACCOUNT_ID in the environment. Each Worker is deployed
as an assets-only Worker with the same name, so the custom domain already
attached to it keeps pointing at it.

    python scripts/patch_quiz_apps_footer.py            # dry run
    python scripts/patch_quiz_apps_footer.py --apply    # deploy all five
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

APPS = {
    "smallgasturbine-gt05": "https://smallgasturbine.gt-05.proreadyengineer.com",
    "smallgasturbine-gt06": "https://smallgasturbine.gt-06.proreadyengineer.com",
    "smallgasturbine-gt07": "https://smallgasturbine.gt-07.proreadyengineer.com",
    "smallgasturbine-gt13": "https://smallgasturbine.gt-13.proreadyengineer.com",
    "smallgasturbine-gt15": "https://smallgasturbine.gt-15.proreadyengineer.com",
}

RESET_URL = "https://proreadyengineer.com/learn/signin?reason=password"

# The whole footer expression, with the JSX runtime alias captured so the
# replacement uses the same identifier the bundle does.
OLD_RE = re.compile(
    r"\(0,(?P<j>[A-Za-z_$][\w$]*)\.jsxs\)\(`div`,\{className:`footer-note`,children:\["
    r"`Your ProReadyEngineer account works across `,"
    r"\(0,(?P=j)\.jsx\)\(`span`,\{className:`mono`,children:`combustion-toolkit\.proreadyengineer\.com`\}\),"
    r"` and this learning module\.`\]\}\)"
)


def new_footer(j: str) -> str:
    return (
        f"(0,{j}.jsxs)(`div`,{{className:`footer-note`,children:[`Forgot your password? `,"
        f"(0,{j}.jsx)(`a`,{{href:`{RESET_URL}`,target:`_blank`,rel:`noopener noreferrer`,"
        f"children:`Reset it by email link`}}),` — one ProReadyEngineer account opens every module.`]}})"
    )


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "proready-quiz-patch/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def discover_assets(origin: str) -> dict[str, bytes]:
    html = fetch(f"{origin}/")
    files = {"index.html": html}
    for path in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html.decode("utf-8", "replace")):
        files[path.lstrip("/")] = fetch(origin + path)
    if b"/favicon.svg" in html:
        files["favicon.svg"] = fetch(origin + "/favicon.svg")
    return files


def already_patched(js: str) -> bool:
    return "Reset it by email link" in js and "combustion-toolkit" not in js


def patch(js: str) -> str:
    hits = list(OLD_RE.finditer(js))
    if len(hits) != 1:
        raise ValueError(f"expected the footer expression exactly once, found {len(hits)}")
    m = hits[0]
    patched = js[: m.start()] + new_footer(m.group("j")) + js[m.end():]
    # nothing but that expression may differ
    if patched[: m.start()] != js[: m.start()] or patched[m.start() + len(new_footer(m.group("j"))):] != js[m.end():]:
        raise ValueError("patch touched more than the footer")
    if "combustion-toolkit" in patched:
        raise ValueError("a combustion-toolkit mention survived")
    return patched


def deploy(name: str, files: dict[str, bytes]) -> None:
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        raise SystemExit("deploy needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dist = root / "dist"
        for rel, data in files.items():
            dest = dist / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        (root / "wrangler.jsonc").write_text(json.dumps({
            "name": name,
            "compatibility_date": "2025-01-01",
            # the apps live on their custom domains only; no workers.dev alias
            "workers_dev": False,
            "assets": {"directory": "./dist", "not_found_handling": "single-page-application"},
        }, indent=2))
        env = dict(os.environ, CLOUDFLARE_API_TOKEN=token, CLOUDFLARE_ACCOUNT_ID=account)
        subprocess.run(["npx", "--yes", "wrangler@4", "deploy"], cwd=root, env=env, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="deploy the patched apps (default: dry run)")
    ap.add_argument("--backup-dir", default="./quiz-app-backup")
    ap.add_argument("--only", help="a single worker name, e.g. smallgasturbine-gt05")
    ap.add_argument("--force-redeploy", action="store_true",
                    help="redeploy an app that already carries the patch (e.g. to change Worker settings)")
    args = ap.parse_args()

    backup = Path(args.backup_dir)
    ok = True
    patched_apps: dict[str, dict[str, bytes]] = {}
    for name, origin in APPS.items():
        if args.only and name != args.only:
            continue
        print(f"\n=== {name} ({origin}) ===")
        try:
            files = discover_assets(origin)
        except Exception as exc:
            print(f"  ! could not read the live app: {exc}")
            ok = False
            continue
        out = backup / name
        out.mkdir(parents=True, exist_ok=True)
        for rel, data in files.items():
            (out / rel.replace("/", "__")).write_bytes(data)
        js_files = [rel for rel in files if rel.endswith(".js")]
        if len(js_files) != 1:
            print(f"  ! expected one bundle, found {js_files}")
            ok = False
            continue
        rel = js_files[0]
        js = files[rel].decode("utf-8")
        if already_patched(js):
            print(f"  · {rel}: already carries the new footer" + (" — will redeploy as is" if args.force_redeploy else " — nothing to do"))
            if args.force_redeploy:
                patched_apps[name] = files
            continue
        try:
            patched = patch(js)
        except ValueError as exc:
            print(f"  ! {rel}: {exc} — refusing")
            ok = False
            continue
        files[rel] = patched.encode("utf-8")
        print(f"  ✓ {rel}: footer replaced ({len(files[rel]):,} bytes); other files unchanged: "
              + ", ".join(r for r in files if r != rel))
        patched_apps[name] = files

    print("\n" + "=" * 60)
    print(f"originals saved to {backup.resolve()}")
    if not ok:
        print("dry run FAILED — nothing deployed.")
        return 1
    if not args.apply:
        print("dry run complete. Re-run with --apply to deploy.")
        return 0
    for name, files in patched_apps.items():
        print(f"\n--- deploying {name}")
        deploy(name, files)
        live = fetch(APPS[name] + "/" + [r for r in files if r.endswith(".js")][0]).decode("utf-8", "replace")
        if "combustion-toolkit" in live or "Reset it by email link" not in live:
            print(f"  ! {name}: live bundle does not show the patch yet (cache?) — check manually")
            ok = False
        else:
            print(f"  ✓ {name}: live bundle carries the new footer")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
