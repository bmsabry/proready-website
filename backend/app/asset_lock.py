"""Run-lock for protected HTML assets: a saved copy is inert.

Fingerprinting (app/provenance.py) makes a leaked copy attributable. This
module makes a leaked copy *useless*, which is the part a buyer of stolen
material cares about.

At serve time every inline `<script>` in the asset is encrypted with a key
that belongs to that one copy (AES-256-GCM, the copy's delivery token as
additional authenticated data). The scripts are replaced by inert
`<script type="text/x-pre-locked">` blocks and a short plain loader is
appended. When the copy opens, the loader asks this API for the key; the
API answers only while the copy is live: served to the signed-in learner
asking for it, from our own origin, inside its time-to-live, not revoked.
A file saved to disk asks from a `file://` origin (where browsers also
refuse to expose WebCrypto), gets nothing, and shows a licence notice
instead of a simulator.

What this does and does not do, plainly: a copy on a hard drive, a copy
mailed to a colleague, a copy uploaded to a file-sharing site, a copy
opened after the instructor withdraws it — all dead. A person who opens
the simulator legitimately, captures the key from their own browser and
rebuilds the file by hand can still do so; that is deliberate cracking,
leaves the delivery token behind, and is what the terms and the trace tool
exist for. Nothing that runs in a browser can be made uncopyable.
"""
from __future__ import annotations

import base64
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

LOCKED_TYPE = "text/x-pre-locked"

# Inline scripts only. A script with `src` is fetched separately and is not
# ours to lock; a non-JS type (JSON data, templates) is left alone too.
_SCRIPT_RE = re.compile(
    r"<script(?P<attrs>(?:\s[^>]*)?)>(?P<body>.*?)</script>", re.I | re.S
)
_TYPE_RE = re.compile(r"""\btype\s*=\s*["']?([^"'\s>]+)""", re.I)
_SRC_RE = re.compile(r"\bsrc\s*=", re.I)
_JS_TYPES = {"", "text/javascript", "application/javascript", "module"}


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def key_to_b64(key: bytes) -> str:
    return base64.b64encode(key).decode("ascii")


def key_from_b64(b64: str) -> bytes:
    return base64.b64decode(b64)


def _lockable(attrs: str) -> tuple[bool, str]:
    """(should this script be locked, its type attribute or '')."""
    if _SRC_RE.search(attrs or ""):
        return False, ""
    m = _TYPE_RE.search(attrs or "")
    typ = (m.group(1).strip().lower() if m else "")
    return typ in _JS_TYPES, typ


def lock_html(html: str, *, token: str, key: bytes, key_url: str) -> str:
    """Encrypt every inline script in `html`; append the loader."""
    aead = AESGCM(key)
    aad = token.encode("ascii")

    def _replace(m: "re.Match[str]") -> str:
        ok, typ = _lockable(m.group("attrs"))
        if not ok:
            return m.group(0)
        iv = os.urandom(12)
        ct = aead.encrypt(iv, m.group("body").encode("utf-8"), aad)
        typ_attr = f' data-type="{typ}"' if typ and typ != "text/javascript" else ""
        return (
            f'<script type="{LOCKED_TYPE}" data-iv="{base64.b64encode(iv).decode()}"'
            f"{typ_attr}>{base64.b64encode(ct).decode()}</script>"
        )

    locked = _SCRIPT_RE.sub(_replace, html)
    loader = _loader_script(token, key_url)
    idx = locked.lower().rfind("</body>")
    return (locked[:idx] + loader + locked[idx:]) if idx != -1 else locked + loader


def unlock_html(html: str, *, token: str, key: bytes) -> list[str]:
    """Decrypt every locked script (tests, and the admin trace on demand)."""
    aead = AESGCM(key)
    aad = token.encode("ascii")
    out: list[str] = []
    for m in re.finditer(
        rf'<script type="{LOCKED_TYPE}" data-iv="([^"]+)"[^>]*>([^<]*)</script>', html
    ):
        iv = base64.b64decode(m.group(1))
        ct = base64.b64decode(re.sub(r"\s+", "", m.group(2)))
        out.append(aead.decrypt(iv, ct, aad).decode("utf-8"))
    return out


def locked_script_count(html: str) -> int:
    return len(re.findall(rf'<script type="{LOCKED_TYPE}"', html))


def _loader_script(token: str, key_url: str) -> str:
    """The plain loader. Deliberately readable: hiding it would buy nothing,
    because the security is in the key the server withholds, not in the
    loader's shape. `credentials: same-origin` is what a real copy on our
    origin needs; a copy anywhere else has no cookie to send anyway."""
    return f"""
<script>
(function(){{
  var T="{token}", U="{key_url}";
  function fail(msg){{
    var d=document.createElement('div');
    d.setAttribute('style','position:fixed;inset:0;z-index:2147483646;background:#0b1220;color:#e2e8f0;font:16px/1.6 system-ui,Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;padding:32px;text-align:center');
    d.innerHTML='<div style="max-width:560px"><div style="font-size:22px;font-weight:600;color:#fff;margin-bottom:12px">Simulator locked</div><div id="pre-lock-msg"></div><div style="margin-top:18px;font-size:13px;color:#94a3b8">Launch it from your course page at <a href="https://proreadyengineer.com/learn" style="color:#67e8f9">proreadyengineer.com/learn</a>. Every copy is licensed to one learner for personal training use on that site only.</div></div>';
    (document.body||document.documentElement).appendChild(d);
    document.getElementById('pre-lock-msg').textContent=msg;
  }}
  function b64(s){{var b=atob(s),a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a.buffer;}}
  async function run(){{
    /* Ask first, always: a plain GET with no custom header is sent even from
       a file on disk or another site (the browser then refuses to show us
       the answer, but the server has seen and recorded the ask). */
    var r;
    try{{ r=await fetch(U,{{credentials:'same-origin',cache:'no-store'}}); }}
    catch(e){{ return fail('This copy could not be licensed where it was opened. If you are on proreadyengineer.com, check your connection and reload; otherwise launch the simulator from your course page.'); }}
    if(!r.ok){{
      var m='This copy is not licensed to run here.';
      try{{ var j=await r.json(); if(j&&j.detail) m=String(j.detail); }}catch(e){{}}
      return fail(m);
    }}
    if(!/^https?:$/.test(location.protocol)||!(window.crypto&&crypto.subtle)){{
      return fail('This copy cannot run from a file on disk or from an unsecured page.');
    }}
    var j=await r.json();
    var key=await crypto.subtle.importKey('raw',b64(j.k),{{name:'AES-GCM'}},false,['decrypt']);
    var aad=new TextEncoder().encode(T);
    var nodes=Array.prototype.slice.call(document.querySelectorAll('script[type="{LOCKED_TYPE}"]'));
    for(var i=0;i<nodes.length;i++){{
      var n=nodes[i];
      var buf=await crypto.subtle.decrypt({{name:'AES-GCM',iv:b64(n.getAttribute('data-iv')),additionalData:aad}},key,b64(n.textContent.replace(/\\s+/g,'')));
      var s=document.createElement('script');
      if(n.getAttribute('data-type')) s.type=n.getAttribute('data-type');
      s.textContent=new TextDecoder().decode(buf);
      n.parentNode.replaceChild(s,n);
    }}
    document.dispatchEvent(new Event('DOMContentLoaded',{{bubbles:true}}));
  }}
  run().catch(function(e){{ fail('Could not start the simulator. Reload the page, or launch it again from your course page.'); }});
}})();
</script>
"""
