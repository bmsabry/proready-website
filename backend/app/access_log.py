"""Keep secrets that travel in a URL out of the server's access log.

uvicorn's access log prints the whole request line, query string included.
Two kinds of link on this site carry their authority in the query string:

  ?t=<manage token>      a client's consulting booking: whoever holds it can
                         cancel the booking (at the client's cost once the
                         free period is over) and open a card page for it
  ?token=<signed token>  the owner's decision links for a consulting call
                         (what the client pays), and the other signed links
                         the site emails

Anyone who can read the logs could use them. `install()` puts a filter on
the `uvicorn.access` logger that replaces the VALUE of every `t=` and
`token=` query parameter with "(hidden)" before the line is written; the
path, the other parameters and the status stay. The email log already hides
the same values (emailer.py).
"""
from __future__ import annotations

import logging
import re

_SECRET = re.compile(r"([?&](?:t|token)=)[^&#\s\"']*")
HIDDEN = "(hidden)"


def redact(text: str) -> str:
    """`text` with the value of every `t=` / `token=` query parameter hidden."""
    return _SECRET.sub(lambda m: m.group(1) + HIDDEN, text) if ("t=" in text or "token=" in text) else text


class _RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        except Exception:  # noqa: BLE001 — a log line must never be lost to its own filter
            pass
        return True


def install() -> None:
    """Idempotent. The filter sits on the logger itself, so it applies
    whatever handlers uvicorn's own logging setup attaches before or after."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _RedactTokens) for f in logger.filters):
        logger.addFilter(_RedactTokens())
