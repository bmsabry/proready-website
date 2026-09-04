"""Per-copy fingerprinting for protected HTML assets.

Every time the simulator (or any HTML lab) is served, it is stamped with a
token that is unique to *that download* — not to the learner, not to the
session: that download. The token is written into the file four separate
ways, and a matching row is recorded in `academy_asset_deliveries`.

Two questions this answers, which are different questions:

  ATTRIBUTION — "somebody sent me this file; who leaked it?"
      Paste the file (or any fragment of it) into the admin trace box.
      `extract_tokens()` finds the token in whichever carrier survived and
      the delivery row names the account, the minute, and the IP.

  DETECTION — "has anything leaked at all, that I don't know about?"
      Carrier 4 is a beacon: every copy calls home once when it is opened.
      A copy opened from a hard drive, from another website, by a logged-out
      visitor, or by a *different* account than it was issued to reports
      itself. See `classify_ping()`.

The four carriers, deliberately different in kind so that stripping one by
hand does not strip the rest:

  1. An HTML comment near the top of the document.       (obvious; quick check)
  2. Zero-width characters woven into the visible banner text. Invisible on
     screen, survives select-all-copy of the rendered page, and survives a
     "delete the comment" edit because there is nothing to see.
  3. A `data-` attribute on the banner element, dressed as ordinary markup.
  4. A constant inside the injected beacon script.

None of this stops a determined engineer — nothing can, for code that runs
in a browser. It makes a leaked copy *attributable*, and an opened leak
*noisy*, which is the part that changes behaviour.
"""
from __future__ import annotations

import re
import secrets

# Zero-width alphabet. U+200D (ZWJ) and U+FEFF are deliberately unused —
# ZWJ carries meaning inside emoji sequences and FEFF gets eaten by editors.
_Z0 = "​"  # ZERO WIDTH SPACE      -> bit 0
_Z1 = "‌"  # ZERO WIDTH NON-JOINER -> bit 1
_ZS = "⁠"  # WORD JOINER           -> sentinel, marks start and end

TOKEN_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # no l/o/0/1 — read aloud safely
TOKEN_LEN = 20
_TOKEN_RE = re.compile(rf"[{TOKEN_ALPHABET}]{{{TOKEN_LEN}}}")


def new_token() -> str:
    """A fresh delivery token. ~100 bits; collision is not a concern."""
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LEN))


# ---------------------------------------------------------------------------
# Zero-width encoding
# ---------------------------------------------------------------------------

def zw_encode(token: str) -> str:
    """Token -> an invisible string of zero-width characters."""
    bits = "".join(f"{ord(c):08b}" for c in token)
    return _ZS + "".join(_Z1 if b == "1" else _Z0 for b in bits) + _ZS


def zw_decode_all(text: str) -> list[str]:
    """Every zero-width-encoded token found in `text`."""
    out: list[str] = []
    for run in re.findall(rf"{_ZS}([{_Z0}{_Z1}]+){_ZS}", text):
        bits = "".join("1" if ch == _Z1 else "0" for ch in run)
        try:
            chars = [
                chr(int(bits[i:i + 8], 2))
                for i in range(0, len(bits) - len(bits) % 8, 8)
            ]
        except ValueError:  # pragma: no cover — malformed run
            continue
        cand = "".join(chars)
        if _TOKEN_RE.fullmatch(cand):
            out.append(cand)
    return out


def extract_tokens(blob: str) -> list[str]:
    """Pull every delivery token out of a pasted file, in confidence order.

    Accepts a whole HTML file, a fragment, or a bare token typed by hand —
    whatever actually reached the admin. Returns unique tokens, most
    trustworthy carrier first (zero-width beats a comment: a comment is
    trivial to forge or to copy from someone else's file).
    """
    found: list[str] = []

    def add(vals) -> None:
        for v in vals:
            if v and v not in found:
                found.append(v)

    add(zw_decode_all(blob))                                     # carrier 2
    add(re.findall(r"data-pre-copy=\"([a-z2-9]{20})\"", blob))    # carrier 3
    add(re.findall(r"__PRE_COPY__\s*=\s*[\"']([a-z2-9]{20})", blob))  # carrier 4
    add(re.findall(r"pre-copy:\s*([a-z2-9]{20})", blob))          # carrier 1
    # Carrier 5, the run-lock loader (app/asset_lock.py). Not removable
    # without killing the copy: the id is the AAD every script was
    # encrypted under, and it names the key endpoint.
    add(re.findall(r"asset-key/([a-z2-9]{20})", blob))
    add(re.findall(r"var T=\"([a-z2-9]{20})\"", blob))

    if not found:  # a bare token pasted on its own, or an unknown carrier
        stripped = blob.strip()
        if _TOKEN_RE.fullmatch(stripped):
            found.append(stripped)
        else:
            add(_TOKEN_RE.findall(blob))
    return found


# ---------------------------------------------------------------------------
# Stamping
# ---------------------------------------------------------------------------

_BANNER_CSS = """
<style>
#pre-license-banner{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;
background:rgba(12,18,32,.92);color:#cfe3ff;font:12px/1.5 system-ui,Segoe UI,sans-serif;
padding:6px 14px;display:flex;gap:14px;justify-content:space-between;align-items:center;
border-top:1px solid rgba(120,160,255,.35);pointer-events:none}
#pre-license-banner b{color:#fff;font-weight:600}
</style>
"""


def _beacon_script(token: str, endpoint: str) -> str:
    """Carrier 4 — the call-home ping.

    `sendBeacon` with a text/plain body is a CORS *simple* request: no
    preflight, no CORS response headers needed, and it still fires when the
    copy is opened from a `file://` path (origin `null`). Wrapped so that a
    failure can never affect the app.
    """
    return f"""
<script>
(function(){{
  var __PRE_COPY__ = "{token}";
  try {{
    var p = JSON.stringify({{
      t: __PRE_COPY__,
      u: String(location.href).slice(0, 400),
      o: String(location.origin),
      r: String(document.referrer || "").slice(0, 300),
      s: (screen.width + "x" + screen.height),
      z: (Intl.DateTimeFormat().resolvedOptions().timeZone || "")
    }});
    var url = "{endpoint}";
    if (navigator.sendBeacon) {{
      navigator.sendBeacon(url, new Blob([p], {{type: "text/plain;charset=UTF-8"}}));
    }} else {{
      fetch(url, {{method: "POST", body: p, mode: "no-cors",
                   keepalive: true, headers: {{"Content-Type": "text/plain"}}}});
    }}
  }} catch (e) {{}}
}})();
</script>
"""


def stamp_html(html: str, *, email: str, token: str, beacon_url: str) -> str:
    """Return `html` with the licence banner and all four carriers applied."""
    zw = zw_encode(token)

    # Carrier 2 lives inside the sentence a reader actually sees, which is
    # also the text most likely to be copied along with anything else.
    banner = (
        f"{_BANNER_CSS}"
        f'<div id="pre-license-banner" data-pre-copy="{token}">'
        f"<span>Licensed to <b>{email}</b>{zw} — personal, non-transferable "
        f"training use only.{zw} Do not copy or redistribute.</span>"
        f"<span>Training simulation — NOT for operation of any real engine. "
        f"&copy; ProReadyEngineer LLC</span>"
        f"</div>"
        f"{_beacon_script(token, beacon_url)}"
    )

    lowered = html.lower()
    idx = lowered.rfind("</body>")
    html = (html[:idx] + banner + html[idx:]) if idx != -1 else html + banner

    # Carrier 1, at the very top where anyone told "look for the id" finds it.
    head = f"<!-- pre-copy: {token} -->\n"
    if lowered.startswith("<!doctype"):
        cut = html.find(">") + 1
        html = html[:cut] + "\n" + head + html[cut:]
    else:
        html = head + html
    return html


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Ping statuses, worst first. `offsite` is the one that means "this file is
# not on my website any more" — the others are softer signals.
PING_OFFSITE = "offsite"          # opened from disk or from another host
PING_OTHER_ACCOUNT = "other_account"  # a different learner is holding it
PING_ANONYMOUS = "anonymous"      # nobody signed in — expired session, or shared
PING_UNKNOWN = "unknown_token"    # token we never issued: edited or very old
PING_OK = "ok"                    # our site, right account

ALERT_STATUSES = (PING_OFFSITE, PING_OTHER_ACCOUNT, PING_UNKNOWN)


def classify_ping(
    *,
    page_url: str,
    origin: str,
    allowed_hosts: set[str],
    issued_to_learner_id: int | None,
    session_learner_id: int | None,
) -> str:
    """Decide what a call-home ping means.

    `allowed_hosts` is the set of hostnames the material is *supposed* to be
    served from. Anything else — a `file://` path, a classroom intranet, a
    competitor's site — is the loud signal.
    """
    if issued_to_learner_id is None:
        return PING_UNKNOWN

    url = (page_url or "").strip()
    host = ""
    m = re.match(r"^[a-zA-Z][\w+.-]*://([^/?#]*)", url)
    if m:
        host = m.group(1).split("@")[-1].split(":")[0].lower()
    scheme = url.split(":", 1)[0].lower() if ":" in url else ""

    if scheme in ("file", "blob", "data") or origin in ("null", "file://"):
        return PING_OFFSITE
    if host and host not in allowed_hosts:
        return PING_OFFSITE
    if not host:
        return PING_OFFSITE

    if session_learner_id is None:
        return PING_ANONYMOUS
    if session_learner_id != issued_to_learner_id:
        return PING_OTHER_ACCOUNT
    return PING_OK
