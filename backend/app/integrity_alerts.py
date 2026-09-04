"""Email the instructor when protected material misbehaves.

The Integrity tab is the record; this module is the doorbell. Until it
existed a leak produced one server-log line and a row on a page nobody is
obliged to open. Now each of these sends one email to ADMIN_NOTIFY_EMAIL
(or INTEGRITY_ALERT_EMAIL when set):

  * a copy calling home from off-site, from a different account, or with
    an id we never issued (beacon or key request);
  * one login active on two devices inside ten minutes (account sharing);
  * a learner launching the simulator more often in a day than a person
    plausibly would.

Two rules that hold everywhere here:

  1. Never break the request. Every entry point swallows its own errors.
     An alert that raises inside the auth path would lock learners out to
     report a leak, which is backwards.
  2. One email per subject per day. A leaked file opened forty times is one
     leak; the fortieth email would only teach the recipient to ignore the
     first. Deduplication reads the evidence tables themselves so there is
     no separate state to get out of sync.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import provenance as prov
from .config import get_settings
from .emailer import integrity_alert_html, send_email
from .models import (
    AssetDelivery,
    AssetPing,
    Course,
    Learner,
    LearnerOverlapEvent,
    Lesson,
)

log = logging.getLogger(__name__)

DEDUP_WINDOW = timedelta(hours=24)

PLAIN = {
    prov.PING_OFFSITE: (
        "A copy of protected material was opened off your site",
        "A stamped copy reported itself from a hard drive or from another "
        "website. It is no longer on proreadyengineer.com, which is a leak, "
        "not a maybe. The account it was issued to is named below.",
    ),
    prov.PING_OTHER_ACCOUNT: (
        "A copy was opened by a different account than it was issued to",
        "The person who opened this copy was signed in as somebody else, so "
        "the file was passed from one account to another.",
    ),
    prov.PING_UNKNOWN: (
        "A copy with an id you never issued called home",
        "Usually a file whose id was tampered with, or one built from a copy "
        "made before stamping existed.",
    ),
}


def _recipient() -> str:
    s = get_settings()
    return (s.INTEGRITY_ALERT_EMAIL or s.ADMIN_NOTIFY_EMAIL or "").strip()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _when(dt: datetime | None) -> str:
    dt = _aware(dt)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "unknown"


def integrity_url(db: Session, product_code: str) -> str:
    """Deep link to the Integrity tab of the course that sells this product."""
    base = get_settings().SITE_URL.rstrip("/")
    if product_code:
        course = db.execute(
            select(Course).where(Course.recorded_product_code == product_code)
        ).scalars().first()
        if course is not None:
            return f"{base}/admin#courses/{course.code}/integrity"
    return f"{base}/admin#courses"


def _send(db: Session | None, *, subject: str, html: str, template: str,
          scope_code: str) -> bool:
    to = _recipient()
    if not to:
        log.warning("Integrity alert dropped: no recipient configured (%s)", subject)
        return False
    return send_email(
        to=to, subject=subject, html=html, db=db,
        scope_kind="integrity", scope_code=scope_code,
        audience="admin", template=template,
    )


# ---------------------------------------------------------------------------
# Leak signal: a ping (beacon or key request) with an alert status
# ---------------------------------------------------------------------------

def _already_alerted(db: Session, ping: AssetPing) -> bool:
    """Another alert-status ping for the same copy inside the window."""
    since = datetime.now(timezone.utc) - DEDUP_WINDOW
    prior = db.execute(
        select(AssetPing.id).where(
            AssetPing.token == ping.token,
            AssetPing.id != ping.id,
            AssetPing.status.in_(list(prov.ALERT_STATUSES)),
            AssetPing.seen_at >= since,
        ).limit(1)
    ).scalar_one_or_none()
    return prior is not None


def leak_signal(
    db: Session, *, ping: AssetPing, delivery: AssetDelivery | None, via: str
) -> bool:
    """Email once per copy per day about an off-site / other-account /
    unknown-id ping. `via` is 'beacon' or 'key request'. Returns whether an
    email went out. Never raises."""
    try:
        if ping.status not in prov.ALERT_STATUSES:
            return False
        if _already_alerted(db, ping):
            return False
        headline, meaning = PLAIN[ping.status]
        issued_to = delivery.learner_email if delivery else "unknown (id not issued by us)"
        facts: list[tuple[str, str]] = [
            ("Issued to", issued_to),
            ("Signal", f"{ping.status.replace('_', ' ')} via {via}"),
            ("Opened at", ping.page_url or "(no page address; typical of a file on disk)"),
            ("From IP", ping.ip or "unknown"),
            ("Time zone", ping.timezone or "unknown"),
            ("Signed in as", ping.session_email or "nobody"),
            ("Seen", _when(ping.seen_at)),
            ("Copy id", ping.token),
        ]
        if delivery is not None:
            facts.insert(1, ("Downloaded", f"{_when(delivery.served_at)} from {delivery.ip or 'unknown'}"))
            facts.append(("File", delivery.asset_key))
        if delivery is not None and delivery.key_b64 and not delivery.revoked_at:
            next_steps = (
                "This copy is run-locked: wherever it is, it cannot start without "
                "a key this platform only issues to the account it was made for, "
                "on your site, within its time-to-live. You can withdraw it "
                "outright, and every other copy held by that account, from the "
                "Integrity tab. Nothing has been withdrawn automatically."
            )
        elif delivery is not None and delivery.revoked_at:
            next_steps = (
                "This copy was already withdrawn; it cannot run. The signal is "
                "recorded as further evidence."
            )
        else:
            next_steps = (
                "This copy predates the run-lock, so it still runs. The account "
                "it was issued to is on record; the Integrity tab holds the full "
                "history of this copy."
            )
        html = integrity_alert_html(
            headline, meaning, facts, next_steps=next_steps,
            integrity_url=integrity_url(db, delivery.product_code if delivery else ""),
        )
        subject = f"[Integrity] {headline}: {issued_to}"
        return _send(db, subject=subject, html=html, template="integrity_leak",
                     scope_code=delivery.product_code if delivery else "")
    except Exception:  # pragma: no cover — alerts must never break a request
        log.exception("Leak alert failed for token=%s", getattr(ping, "token", "?"))
        try:
            db.rollback()
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Account sharing: one login on two devices at once
# ---------------------------------------------------------------------------

def _spawn(fn: Callable[[], None]) -> None:
    """Run `fn` off the request thread. Module-level so tests can make it
    synchronous; the auth path must not wait on an email API."""
    threading.Thread(target=fn, daemon=True).start()


def sharing_signal(learner_id: int, event_at: datetime) -> None:
    """Email once per learner per day when simultaneous use is recorded.

    Called from the auth funnel right after the overlap row is committed,
    so everything here runs on a fresh session in a background thread and
    must not touch the caller's session at all."""
    def work() -> None:
        from .db import SessionLocal
        db = SessionLocal()
        try:
            since = datetime.now(timezone.utc) - DEDUP_WINDOW
            prior = db.execute(
                select(LearnerOverlapEvent.id).where(
                    LearnerOverlapEvent.learner_id == learner_id,
                    LearnerOverlapEvent.at >= since,
                    LearnerOverlapEvent.at < event_at,
                ).limit(1)
            ).scalar_one_or_none()
            if prior is not None:
                return
            learner = db.get(Learner, learner_id)
            if learner is None:
                return
            # The instructor on a phone and a laptop is not a shared login.
            if learner.email.lower() in get_settings().owner_emails_list:
                return
            events = db.execute(
                select(LearnerOverlapEvent)
                .where(LearnerOverlapEvent.learner_id == learner_id)
                .order_by(LearnerOverlapEvent.at.desc())
                .limit(2)
            ).scalars().all()
            latest = events[0] if events else None
            facts = [
                ("Account", learner.email),
                ("Name", learner.full_name or "(none on file)"),
                ("When", _when(event_at)),
            ]
            if latest is not None:
                facts += [
                    ("Device A", f"{latest.ip_a or 'ip unknown'}"),
                    ("Device B", f"{latest.ip_b or 'ip unknown'}"),
                ]
            html = integrity_alert_html(
                "One login was active on two devices at the same time",
                "The same account was used from two different browsers within "
                "ten minutes of each other. One person on a phone and a laptop "
                "can do this once; a purchased login shared with colleagues does "
                "it again and again. Nothing has been blocked.",
                facts,
                next_steps=(
                    "Look at the pattern in the Integrity tab before drawing a "
                    "conclusion. If it repeats, the terms allow you to suspend the "
                    "account from the Access tab."
                ),
                integrity_url=integrity_url(db, ""),
            )
            _send(db, subject=f"[Integrity] Simultaneous use of one login: {learner.email}",
                  html=html, template="integrity_sharing", scope_code="")
        except Exception:  # pragma: no cover
            log.exception("Sharing alert failed for learner %s", learner_id)
        finally:
            db.close()

    try:
        _spawn(work)
    except Exception:  # pragma: no cover
        log.exception("Could not schedule sharing alert")


# ---------------------------------------------------------------------------
# Launch cap: too many downloads of one asset by one learner in a day
# ---------------------------------------------------------------------------

def launch_cap(db: Session, *, learner: Learner, lesson: Lesson,
               product_code: str, launches_24h: int) -> bool:
    """Email exactly once when a learner crosses the daily launch threshold.

    `launches_24h` counts this launch. The email fires when the count equals
    threshold + 1: crossing it once is the news; every later launch that day
    is the same news."""
    try:
        cap = get_settings().ASSET_LAUNCH_ALERT_PER_DAY
        if cap <= 0 or launches_24h != cap + 1:
            return False
        html = integrity_alert_html(
            f"{learner.email} launched protected material {launches_24h} times today",
            "Each launch downloads a fresh stamped copy. A person opens a "
            "simulator a few times in a day; a script collecting copies, or a "
            "group behind one login, opens it far more. This is a prompt to "
            "look, not proof of anything.",
            [
                ("Account", learner.email),
                ("Name", learner.full_name or "(none on file)"),
                ("Material", lesson.title or lesson.code or f"lesson {lesson.id}"),
                ("Launches in the last 24 h", str(launches_24h)),
                ("Threshold", str(cap)),
            ],
            next_steps=(
                "Every copy is run-locked and expires on its own. If this looks "
                "wrong, withdraw the account's copies from the Integrity tab and "
                "ask the learner what happened."
            ),
            integrity_url=integrity_url(db, product_code),
        )
        return _send(db, subject=f"[Integrity] Unusual launch count: {learner.email}",
                     html=html, template="integrity_launch_cap", scope_code=product_code)
    except Exception:  # pragma: no cover
        log.exception("Launch-cap alert failed for %s", getattr(learner, "email", "?"))
        try:
            db.rollback()
        except Exception:
            pass
        return False
