"""Student Activity report: what each trainee did, when, and what looks wrong.

Read-only. Combines the new visit/activity log (activity.py) with every table
that already remembers something about a learner — lesson progress,
evaluation attempts, certificates, simulator copies and their call-home
pings, devices and simultaneous-use events, sign-in links, requests, terms —
so the history before the activity log existed is still shown ("from
records"), and nothing is stored twice.

Two entry points, both used by routes/activity_admin.py:
  summaries(db, product_code, since) — one row per learner for the list
  detail(db, learner, since)         — the full picture for one learner

Every flag is written so the instructor can say to the trainee exactly why
it was raised, and every sharing signal says what else can explain it.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import academy as svc
from .activity import APP_DEVICE, VISIT_GAP
from .certificates import TIER_TITLES
from .config import get_settings
from .models import (
    AssetDelivery,
    AssetPing,
    Certificate,
    Enrollment,
    Learner,
    LearnerActivity,
    LearnerDevice,
    LearnerOverlapEvent,
    LearnerRequest,
    LearnerVisit,
    Lesson,
    LessonProgress,
    LoginToken,
    Module,
    ModuleGrant,
    Product,
    QuizAttempt,
    QuizItem,
    TermsAcceptance,
)
from .provenance import ALERT_STATUSES

# --------------------------------------------------------------- thresholds --
# Deliberately simple, so each can be explained to the trainee in a sentence.
FAILED_PASSWORDS_PER_HOUR = 5        # wrong quiz-app passwords within one hour
FAST_PASS_SECONDS_PER_ITEM = 6       # passed faster than this per question …
FAST_PASS_MIN_SECONDS = 60           # … and in under a minute overall
FAST_PASS_MIN_ITEMS = 5              # only sets big enough to mean something
SIM_STEPS_SCRIPTED = 300             # Step presses in one simulator session
SIM_COMMANDS_HIGH = 5000             # control commands in one simulator session
DEVICES_30D_NOTE = 4                 # browsers in 30 days worth mentioning
IPS_30D_NOTE = 6                     # networks in 30 days worth mentioning
SEVERITY_RANK = {"": 0, "info": 1, "warn": 2, "alert": 3}
SIGNED_OUT_KINDS = {"link_requested", "sign_in_failed"}
# Events that mean the learner was actually here using the site. A group of
# other records alone (an admin granting access, a copy calling home from
# elsewhere, a failed password) is shown but not counted as a visit.
PRESENCE_KINDS = {
    "sign_in", "course_open", "lesson_open", "lesson_time", "lesson_complete",
    "lesson_touch", "quiz_open", "quiz_submit", "quiz_app", "sim_launch",
    "sim_session", "request", "terms", "course_reset",
}


def _aw(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime | None) -> str | None:
    dt = _aw(dt)
    return dt.isoformat() if dt else None


def fmt_minutes(seconds: float) -> str:
    m = int(round(seconds / 60.0))
    if m < 1:
        return "under a minute"
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


def ua_summary(ua: str) -> str:
    """'Chrome on Windows', 'Safari on iPhone' — enough to tell devices apart."""
    if not ua:
        return "Unknown browser"
    if ua == APP_DEVICE:
        return "Quiz app"
    os_ = (
        "iPhone" if "iPhone" in ua else
        "iPad" if "iPad" in ua else
        "Android" if "Android" in ua else
        "Windows" if "Windows" in ua else
        "Mac" if "Macintosh" in ua or "Mac OS X" in ua else
        "Linux" if "Linux" in ua else "unknown OS"
    )
    browser = (
        "Edge" if "Edg/" in ua else
        "Opera" if "OPR/" in ua else
        "Firefox" if "Firefox/" in ua or "FxiOS" in ua else
        "Chrome" if "Chrome/" in ua or "CriOS" in ua else
        "Safari" if "Safari/" in ua else
        "In-app browser" if "Mobile/" in ua else "Browser"
    )
    if re.search(r"HeadlessChrome|python|curl|bot|spider", ua, re.I):
        browser = "Automated client"
    return f"{browser} on {os_}"


def overlap_kind(o: LearnerOverlapEvent, kinds: dict[str, str]) -> str:
    """'networks' — two networks at once (the strongest sharing sign);
    'devices' — two different kinds of device on one network;
    'same' — the same kind of browser twice on one network, which is most
    often one browser that lost its device cookie."""
    if o.ip_a and o.ip_b and o.ip_a != o.ip_b:
        return "networks"
    a, b = kinds.get(o.device_a), kinds.get(o.device_b)
    if a is not None and a == b:
        return "same"
    return "devices"


# -------------------------------------------------------------- the events --

@dataclass
class Event:
    at: datetime
    kind: str
    label: str
    severity: str = "info"          # info | warn | alert
    source: str = "tracked"         # tracked (activity log) | records
    end: datetime | None = None
    product_code: str = ""
    visit_id: int | None = None
    ip: str = ""
    device: str = ""                # browser summary when known
    detail: dict = field(default_factory=dict)

    def out(self) -> dict:
        return {
            "at": _iso(self.at),
            "end": _iso(self.end),
            "kind": self.kind,
            "label": self.label,
            "severity": self.severity,
            "source": self.source,
            "product_code": self.product_code,
            "ip": self.ip,
            "device": self.device,
            "detail": self.detail,
        }


@dataclass
class Bundle:
    """Everything loaded for a set of learners, grouped by learner id."""
    learners: dict[int, Learner]
    visits: dict[int, list[LearnerVisit]]
    events: dict[int, list[Event]]
    devices: dict[int, list[LearnerDevice]]
    overlaps: dict[int, list[LearnerOverlapEvent]]
    deliveries: dict[int, list[AssetDelivery]]
    alert_pings: dict[int, list[tuple[AssetPing, AssetDelivery | None]]]
    certificates: dict[int, list[Certificate]]
    products: dict[int, set[str]]
    tracking_since: datetime | None


def _group(rows: Iterable, key) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def _tracking_since(db: Session) -> datetime | None:
    first = db.execute(select(func.min(LearnerVisit.started_at))).scalar_one_or_none()
    return _aw(first)


def load(db: Session, learner_ids: list[int], since: datetime) -> Bundle:
    ids = list(learner_ids) or [0]
    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)
    tracking = _tracking_since(db)
    # Before the activity log existed, "last worked on a lesson" can only
    # come from the progress table; after it, the log's time-on-lesson rows
    # say the same thing better.
    cutoff = tracking or now

    learners = {l.id: l for l in db.execute(select(Learner).where(Learner.id.in_(ids))).scalars()}
    visits = _group(db.execute(
        select(LearnerVisit).where(
            LearnerVisit.learner_id.in_(ids), LearnerVisit.last_seen_at >= since,
        )
    ).scalars(), lambda v: v.learner_id)

    lessons = {l.id: l for l in db.execute(select(Lesson)).scalars()}
    modules = {m.id: m for m in db.execute(select(Module)).scalars()}
    product_titles = dict(db.execute(select(Product.code, Product.title)).all())

    def lesson_product(lesson_id: int) -> str:
        l = lessons.get(lesson_id)
        m = modules.get(l.module_id) if l else None
        return m.product_code if m else ""

    events: dict[int, list[Event]] = defaultdict(list)
    visit_device = {v.id: ua_summary(v.user_agent if v.device_id != APP_DEVICE else APP_DEVICE)
                    for vs in visits.values() for v in vs}

    # ---- the activity log
    for a in db.execute(
        select(LearnerActivity).where(
            LearnerActivity.learner_id.in_(ids),
            or_(LearnerActivity.at >= since, LearnerActivity.last_at >= since),
        )
    ).scalars():
        ev = _activity_event(a, lessons, modules)
        ev.device = visit_device.get(a.visit_id or -1, "")
        events[a.learner_id].append(ev)

    # ---- sign-in links: the token table knows every link issued and used,
    # including links the admin minted; skip the ones the log already holds.
    def logged(lid: int, kind: str, at: datetime) -> bool:
        return any(e.kind == kind and abs((e.at - at).total_seconds()) <= 120
                   for e in events.get(lid, []))

    for t in db.execute(
        select(LoginToken).where(
            LoginToken.learner_id.in_(ids), LoginToken.created_at >= since,
        )
    ).scalars():
        made = _aw(t.created_at)
        if not logged(t.learner_id, "link_requested", made):
            events[t.learner_id].append(Event(
                at=made, kind="link_requested", source="records",
                label="A sign-in link was issued"))
        used = _aw(t.used_at)
        if used is not None and not logged(t.learner_id, "sign_in", used):
            events[t.learner_id].append(Event(
                at=used, kind="sign_in", source="records",
                label="Signed in with an email link"))

    # ---- lesson progress: completions (always) and last touch (before the log)
    for p in db.execute(
        select(LessonProgress).where(
            LessonProgress.learner_id.in_(ids),
            or_(LessonProgress.completed_at >= since, LessonProgress.updated_at >= since),
        )
    ).scalars():
        l = lessons.get(p.lesson_id)
        title = l.title if l else f"lesson {p.lesson_id}"
        pc = lesson_product(p.lesson_id)
        done = _aw(p.completed_at)
        if done is not None and done >= since:
            events[p.learner_id].append(Event(
                at=done, kind="lesson_complete", source="records", product_code=pc,
                label=f"Completed “{title}”"))
        touched = _aw(p.updated_at)
        if (touched is not None and since <= touched < cutoff
                and (done is None or abs((touched - done).total_seconds()) > 120)):
            events[p.learner_id].append(Event(
                at=touched, kind="lesson_touch", source="records", product_code=pc,
                label=f"Worked on “{title}”"))

    # ---- evaluations
    for q in db.execute(
        select(QuizAttempt).where(
            QuizAttempt.learner_id.in_(ids), QuizAttempt.submitted_at >= since,
        )
    ).scalars():
        m = modules.get(q.module_id)
        what = ("Written examination" if q.item_set == "advanced" else
                "Mastery check" if q.item_set == "summative" else "Evaluation")
        where = m.title if m else (q.product_code or "")
        ev = Event(
            at=_aw(q.submitted_at), kind="quiz_submit", source="records",
            product_code=(m.product_code if m else q.product_code),
            label=f"{what} — {where}: {q.score_pct:.0f}% ({'passed' if q.passed else 'not passed'})",
            detail={"module_id": q.module_id, "item_set": q.item_set,
                    "score": q.score_pct, "passed": q.passed,
                    "items": len(q.responses or {})},
        )
        events[q.learner_id].append(ev)

    # ---- certificates (all time: the page lists what was ever issued)
    certificates = _group(db.execute(
        select(Certificate).where(Certificate.learner_id.in_(ids))
        .order_by(Certificate.issued_at)
    ).scalars(), lambda c: c.learner_id)
    for lid, certs in certificates.items():
        for c in certs:
            at = _aw(c.issued_at)
            if at is None or at < since:
                continue
            title = TIER_TITLES.get(c.tier, c.tier)
            revoked = " — later revoked" if c.status == "revoked" else ""
            events[lid].append(Event(
                at=at, kind="certificate", source="records", product_code=c.product_code,
                label=f"{title} issued ({c.code}){revoked}"))

    # ---- protected material (the simulator and other HTML labs)
    deliveries = _group(db.execute(
        select(AssetDelivery).where(AssetDelivery.learner_id.in_(ids))
    ).scalars(), lambda d: d.learner_id)
    by_token = {d.token: d for ds in deliveries.values() for d in ds}
    for lid, ds in deliveries.items():
        for d in ds:
            at = _aw(d.served_at)
            if at is None or at < since:
                continue
            l = lessons.get(d.lesson_id)
            events[lid].append(Event(
                at=at, kind="sim_launch", source="records", product_code=d.product_code,
                ip=d.ip or "", device=ua_summary(d.user_agent or ""),
                label=f"Launched “{l.title if l else d.asset_key}”",
                detail={"copy": d.token[:8]}))

    alert_pings: dict[int, list[tuple[AssetPing, AssetDelivery | None]]] = defaultdict(list)
    pq = select(AssetPing).where(
        AssetPing.status.in_(list(ALERT_STATUSES)),
        or_(AssetPing.token.in_(list(by_token) or [""]),
            AssetPing.session_learner_id.in_(ids)),
    )
    for p in db.execute(pq).scalars():
        d = by_token.get(p.token) or (
            db.execute(select(AssetDelivery).where(AssetDelivery.token == p.token))
            .scalar_one_or_none()
        )
        owners = set()
        if d is not None and d.learner_id in learners:
            owners.add(d.learner_id)
        if p.session_learner_id in learners:
            owners.add(p.session_learner_id)
        for lid in owners:
            alert_pings[lid].append((p, d))
            at = _aw(p.seen_at)
            if at is None or at < since:
                continue
            events[lid].append(Event(
                at=at, kind="copy_alert", source="records",
                severity="info" if p.reviewed_at else "alert",
                ip=p.ip or "", label=_ping_label(p, d, lid)
                + (" (reviewed)" if p.reviewed_at else ""),
                detail={"status": p.status, "page": (p.page_url or "")[:200]}))

    # ---- devices and simultaneous use
    devices = _group(db.execute(
        select(LearnerDevice).where(LearnerDevice.learner_id.in_(ids))
    ).scalars(), lambda d: d.learner_id)
    for lid, ds in devices.items():
        for d in ds:
            at = _aw(d.first_seen_at)
            if at is not None and at >= since:
                events[lid].append(Event(
                    at=at, kind="new_device", source="records", ip=d.ip or "",
                    device=ua_summary(d.user_agent or ""),
                    label=f"First use of a new browser: {ua_summary(d.user_agent or '')}"))
    overlaps = _group(db.execute(
        select(LearnerOverlapEvent).where(
            LearnerOverlapEvent.learner_id.in_(ids),
            LearnerOverlapEvent.at >= min(since, d30),
        )
    ).scalars(), lambda o: o.learner_id)
    for lid, os_ in overlaps.items():
        kinds = {d.device_id: ua_summary(d.user_agent or "") for d in devices.get(lid, [])}
        for o in os_:
            at = _aw(o.at)
            if at is None or at < since:
                continue
            k = overlap_kind(o, kinds)
            events[lid].append(Event(
                at=at, kind="overlap", source="records",
                severity="warn" if k == "networks" else "info",
                label={
                    "networks": f"In use on two browsers at once, on different networks ({o.ip_a} and {o.ip_b})",
                    "devices": f"In use on two different devices at once, same network ({o.ip_a or o.ip_b})",
                    "same": f"Two sessions of the same browser type at once, same network ({o.ip_a or o.ip_b})",
                }[k]))

    # ---- requests, access, terms
    for r in db.execute(
        select(LearnerRequest).where(LearnerRequest.learner_id.in_(ids),
                                     LearnerRequest.created_at >= since)
    ).scalars():
        what = "completion marks" if r.kind == "completion" else "the answer key"
        events[r.learner_id].append(Event(
            at=_aw(r.created_at), kind="request", source="records",
            product_code=r.product_code,
            label=f"Asked the instructor for {what} ({r.status})"))
    for e in db.execute(
        select(Enrollment).where(Enrollment.learner_id.in_(ids), Enrollment.granted_at >= since)
    ).scalars():
        events[e.learner_id].append(Event(
            at=_aw(e.granted_at), kind="access", source="records", product_code=e.product_code,
            label=f"Given access to {product_titles.get(e.product_code, e.product_code)} ({e.source})"))
    for g in db.execute(
        select(ModuleGrant).where(ModuleGrant.learner_id.in_(ids), ModuleGrant.granted_at >= since)
    ).scalars():
        m = modules.get(g.module_id)
        events[g.learner_id].append(Event(
            at=_aw(g.granted_at), kind="access", source="records",
            product_code=m.product_code if m else "",
            label=f"Given access to {m.title if m else 'a module'} ({g.source})"))
    for t in db.execute(
        select(TermsAcceptance).where(TermsAcceptance.learner_id.in_(ids),
                                      TermsAcceptance.accepted_at >= since)
    ).scalars():
        events[t.learner_id].append(Event(
            at=_aw(t.accepted_at), kind="terms", source="records",
            label=f"Accepted the training terms ({t.doc_version})"))

    # ---- which courses each learner is in
    products: dict[int, set[str]] = defaultdict(set)
    for e in db.execute(
        select(Enrollment).where(Enrollment.learner_id.in_(ids), Enrollment.status == "active")
    ).scalars():
        products[e.learner_id].add(e.product_code)
    for g in db.execute(
        select(ModuleGrant).where(ModuleGrant.learner_id.in_(ids), ModuleGrant.status == "active")
    ).scalars():
        m = modules.get(g.module_id)
        if m:
            products[g.learner_id].add(m.product_code)
    for lid, lesson_id in db.execute(
        select(LessonProgress.learner_id, LessonProgress.lesson_id)
        .where(LessonProgress.learner_id.in_(ids))
    ).all():
        pc = lesson_product(lesson_id)
        if pc:
            products[lid].add(pc)
    for lid, mid in db.execute(
        select(QuizAttempt.learner_id, QuizAttempt.module_id).where(QuizAttempt.learner_id.in_(ids))
    ).all():
        m = modules.get(mid)
        if m:
            products[lid].add(m.product_code)

    for lid in events:
        events[lid].sort(key=lambda e: e.at)

    return Bundle(
        learners=learners, visits=visits, events=events, devices=devices,
        overlaps=overlaps, deliveries=deliveries, alert_pings=alert_pings,
        certificates=certificates, products=products, tracking_since=tracking,
    )


def _ping_label(p: AssetPing, d: AssetDelivery | None, lid: int) -> str:
    key = p.referrer == "key-request"
    where = p.page_url or p.origin or "an unknown place"
    if where.startswith("file:"):
        where = "a file saved on a computer"
    if p.status == "unknown_token":
        return "A copy with an id this site never issued asked for its unlock key" if key \
            else "A copy with an id this site never issued called home"
    if d is not None and d.learner_id != lid:
        return f"While signed in here, opened a protected copy issued to {d.learner_email}"
    if p.status == "other_account":
        who = p.session_email or "another account"
        return f"A protected copy issued to this account was opened by {who}"
    verb = "asked for its unlock key from" if key else "was opened in"
    return f"A protected copy issued to this account {verb} {where}"


def _activity_event(a: LearnerActivity, lessons: dict, modules: dict) -> Event:
    d = dict(a.detail or {})
    ev = Event(at=_aw(a.at), kind=a.kind, label=a.label or a.kind, end=_aw(a.last_at),
               product_code=a.product_code or "", visit_id=a.visit_id, ip=a.ip or "",
               detail=d)
    if a.kind == "lesson_time":
        ev.label = f"Spent {fmt_minutes(a.amount or 0)} on “{a.label}”"
        d["seconds"] = int(a.amount or 0)
    elif a.kind == "quiz_open":
        d["module_id"] = a.module_id
    elif a.kind == "sim_session":
        minutes = float(d.get("minutes") or 0)
        counts = d.get("op_counts") or {}
        control = int(d.get("ops") or 0) - int(counts.get("ping", 0))
        steps = int(counts.get("step", 0))
        sim_min = int(d.get("sim_seconds") or 0) // 60
        ev.label = (f"Ran the simulator for {fmt_minutes(minutes * 60)} — "
                    f"{control} commands, {sim_min} simulated min")
        if steps >= SIM_STEPS_SCRIPTED:
            ev.severity = "alert"
            ev.label += f", Step pressed {steps}×"
        elif control >= SIM_COMMANDS_HIGH:
            ev.severity = "warn"
    elif a.kind == "sim_refused":
        why = d.get("why", "")
        ev.severity = ("alert" if why in ("offsite", "other_copy") else
                       "warn" if why == "withdrawn" else "info")
    elif a.kind == "sign_in_failed":
        ev.severity = "info"
    return ev


# ----------------------------------------------------------------- visits --

def build_visits(bundle: Bundle, lid: int) -> list[dict]:
    """Visits newest first, each with the events that happened during it.

    Tracked visits come from the visit log. Events outside every tracked
    visit (history from before the log, or signed-out attempts) are grouped
    by 30-minute gaps into visits reconstructed from records."""
    events = bundle.events.get(lid, [])
    tracked = sorted(bundle.visits.get(lid, []), key=lambda v: _aw(v.started_at))
    slots: list[dict] = []
    by_id: dict[int, dict] = {}
    for v in tracked:
        slot = {
            "start": _aw(v.started_at), "end": _aw(v.last_seen_at), "ip": v.ip or "",
            "device": ua_summary(v.user_agent if v.device_id != APP_DEVICE else APP_DEVICE),
            "how": {"link": "Email-link sign-in", "password": "Password (quiz apps)"}.get(
                v.sign_in, "Already signed in"),
            "source": "tracked", "events": [],
        }
        slots.append(slot)
        by_id[v.id] = slot

    loose: list[Event] = []
    for e in events:
        if e.visit_id is not None and e.visit_id in by_id:
            by_id[e.visit_id]["events"].append(e)
            continue
        home = None
        for s in slots:
            if s["start"] - timedelta(minutes=2) <= e.at <= s["end"] + timedelta(minutes=5):
                if home is None or (e.ip and e.ip == s["ip"]):
                    home = s
        if home is not None:
            home["events"].append(e)
        else:
            loose.append(e)

    cluster: list[Event] = []
    rebuilt: list[list[Event]] = []
    for e in loose:
        if cluster and e.at - max(x.end or x.at for x in cluster) > VISIT_GAP:
            rebuilt.append(cluster)
            cluster = []
        cluster.append(e)
    if cluster:
        rebuilt.append(cluster)
    known = [(_aw(d.first_seen_at), _aw(d.last_seen_at), d) for d in bundle.devices.get(lid, [])
             if d.first_seen_at and d.last_seen_at]
    for c in rebuilt:
        ips = [x.ip for x in c if x.ip]
        devs = [x.device for x in c if x.device and x.kind != "new_device"] or \
               [x.device for x in c if x.device]
        if not ips or not devs:
            # Records such as evaluation attempts carry no browser. When exactly
            # one of the learner's browsers was in use around that time, it is
            # the one — say so; otherwise leave it blank rather than guess.
            lo, hi = c[0].at, max(x.end or x.at for x in c)
            pad = timedelta(minutes=5)
            cover = [d for f, l, d in known if f - pad <= hi and lo <= l + pad]
            if len(cover) == 1:
                ips = ips or ([cover[0].ip] if cover[0].ip else [])
                devs = devs or [ua_summary(cover[0].user_agent or "")]
        present = any(x.kind in PRESENCE_KINDS for x in c)
        signed_out = not present and any(x.kind in SIGNED_OUT_KINDS for x in c)
        slots.append({
            "start": c[0].at, "end": max(x.end or x.at for x in c),
            "ip": ips[0] if ips else "", "device": devs[0] if devs else "",
            "how": ("Sign-in attempt" if signed_out else
                    "Email-link sign-in" if any(x.kind == "sign_in" for x in c) else
                    "Record" if not present else "—"),
            "source": "records", "events": c, "not_a_visit": not present,
        })

    out = []
    for s in sorted(slots, key=lambda s: s["start"], reverse=True):
        evs = sorted(s["events"], key=lambda e: e.at)
        worst = max((e.severity for e in evs), key=lambda x: SEVERITY_RANK[x], default="")
        out.append({
            "start": _iso(s["start"]),
            "end": _iso(s["end"]),
            "minutes": round(max(0.0, (s["end"] - s["start"]).total_seconds()) / 60.0, 1),
            "device": s["device"],
            "ip": s["ip"],
            "how": s["how"],
            "source": s["source"],
            "counts_as_visit": not s.get("not_a_visit", False),
            "summary": _visit_summary(evs),
            "worst": worst if SEVERITY_RANK.get(worst, 0) >= 2 else "",
            "events": [e.out() for e in evs],
        })
    return out


def _visit_summary(evs: list[Event]) -> str:
    """One line: the most telling things done in the visit."""
    parts: list[str] = []
    certs = [e for e in evs if e.kind == "certificate"]
    parts += [e.label for e in certs]
    quizzes = [e for e in evs if e.kind == "quiz_submit"]
    if quizzes:
        best = [e for e in quizzes if e.detail.get("passed")] or quizzes
        parts.append(best[-1].label + (f" (+{len(quizzes) - 1} more)" if len(quizzes) > 1 else ""))
    done = [e for e in evs if e.kind == "lesson_complete"]
    if len(done) == 1:
        parts.append(done[0].label)
    elif done:
        parts.append(f"Completed {len(done)} lessons")
    spent = [e for e in evs if e.kind == "lesson_time"]
    if spent:
        top = max(spent, key=lambda e: int(e.detail.get("seconds") or 0))
        parts.append(top.label + (f" (+{len(spent) - 1} more lessons)" if len(spent) > 1 else ""))
    sims = [e for e in evs if e.kind == "sim_session"]
    if sims:
        parts.append(sims[-1].label if len(sims) == 1 else f"Ran the simulator {len(sims)}×")
    elif any(e.kind == "sim_launch" for e in evs):
        parts.append(next(e for e in evs if e.kind == "sim_launch").label)
    if not parts:
        opened = [e for e in evs if e.kind in ("lesson_open", "lesson_touch", "quiz_app",
                                               "quiz_open", "course_open")]
        if opened:
            parts.append(opened[-1].label + (f" (+{len(opened) - 1} more)" if len(opened) > 1 else ""))
    if not parts:
        signed = [e for e in evs if e.kind == "sign_in"]
        if signed:
            parts.append(signed[-1].label)
    if not parts and evs:
        parts.append(evs[-1].label)
    alerts = [e for e in evs if e.severity in ("warn", "alert")]
    if alerts and alerts[-1].label not in parts:
        parts.append(alerts[-1].label)
    return " · ".join(parts[:4]) if parts else "Browsed the site"


# -------------------------------------------------------------- integrity --

def integrity(bundle: Bundle, lid: int) -> dict:
    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)
    devices = bundle.devices.get(lid, [])
    recent = [d for d in devices if (_aw(d.last_seen_at) or now) >= d30]
    once = [d for d in recent if (d.seen_count or 0) <= 1]
    ips = {d.ip for d in recent if d.ip}
    overlaps = [o for o in bundle.overlaps.get(lid, []) if (_aw(o.at) or now) >= d30]
    kinds = {d.device_id: ua_summary(d.user_agent or "") for d in devices}
    classes = [overlap_kind(o, kinds) for o in overlaps]
    pings = bundle.alert_pings.get(lid, [])
    open_alerts = [p for p, _ in pings if p.reviewed_at is None]
    deliveries = bundle.deliveries.get(lid, [])
    return {
        "devices_total": len(devices),
        "devices_30d": len(recent),
        "devices_seen_once_30d": len(once),
        "ips_30d": len(ips),
        "browser_kinds_30d": len({ua_summary(d.user_agent or "") for d in recent}),
        "overlaps_30d": len(overlaps),
        "overlaps_different_networks_30d": classes.count("networks"),
        "overlaps_different_devices_30d": classes.count("devices"),
        "overlaps_same_browser_30d": classes.count("same"),
        "copy_alerts": len(pings),
        "copy_alerts_open": len(open_alerts),
        "launches": len(deliveries),
        "key_refusals": sum(d.key_denied or 0 for d in deliveries),
        "copies_withdrawn": sum(1 for d in deliveries if d.revoked_at is not None),
    }


def integrity_devices(bundle: Bundle, lid: int) -> list[dict]:
    rows = sorted(bundle.devices.get(lid, []),
                  key=lambda d: _aw(d.last_seen_at) or datetime.min.replace(tzinfo=timezone.utc),
                  reverse=True)
    return [{
        "browser": ua_summary(d.user_agent or ""),
        "ip": d.ip or "",
        "first_seen_at": _iso(d.first_seen_at),
        "last_seen_at": _iso(d.last_seen_at),
        "seen_count": d.seen_count or 0,
    } for d in rows[:40]]


# ------------------------------------------------------------------ flags --

def flags(bundle: Bundle, lid: int) -> list[dict]:
    """Concerns worth the instructor's attention, worst first. Each has a
    plain-English title and the evidence behind it."""
    out: list[dict] = []
    learner = bundle.learners.get(lid)
    integ = integrity(bundle, lid)
    events = bundle.events.get(lid, [])

    def add(sev: str, title: str, detail: str = "", at: datetime | None = None) -> None:
        out.append({"severity": sev, "title": title, "detail": detail, "at": _iso(at)})

    # Account sharing
    n = integ["overlaps_different_networks_30d"]
    if n:
        add("alert" if n >= 3 else "warn",
            f"In use on two browsers at the same time from different networks ×{n} in 30 days",
            "The strongest sign of a shared login. One person using a phone on mobile data "
            "and a laptop on Wi-Fi together can also cause it.")
    n = integ["overlaps_different_devices_30d"]
    if n:
        add("warn" if n >= 3 else "info",
            f"In use on two different devices at the same time on the same network ×{n} in 30 days",
            "One person with a phone and a laptop, or colleagues sharing one login in the same office.")
    n = integ["overlaps_same_browser_30d"]
    if n:
        add("info",
            f"Two sessions of the same browser type at the same time on the same network ×{n} in 30 days",
            "Usually one browser counted twice: until 22 Sep 2026 the first page requests after "
            "a sign-in could each be given their own device id, and private browsing starts "
            "afresh every time. Identical office computers would look the same.")
    if integ["devices_30d"] >= DEVICES_30D_NOTE:
        k = integ["browser_kinds_30d"]
        add("warn" if k >= DEVICES_30D_NOTE else "info",
            f"{integ['devices_30d']} browser sessions in 30 days — {k} kind{'s' if k != 1 else ''} of browser",
            "A browser shows up as new whenever it has no device cookie: private browsing, "
            "cleared cookies, or (until 22 Sep 2026) the first moments after each sign-in. "
            "Many different kinds of browser is the stronger sign.")
    if integ["ips_30d"] >= IPS_30D_NOTE:
        add("info", f"{integ['ips_30d']} different networks (IP addresses) in 30 days",
            "Travel and mobile data change addresses often; worth a look only with other signs.")

    # Protected copies
    open_ = [(p, d) for p, d in bundle.alert_pings.get(lid, []) if p.reviewed_at is None]
    for p, d in open_[:5]:
        add("alert", _ping_label(p, d, lid), (p.page_url or p.origin or "")[:200], _aw(p.seen_at))
    if integ["key_refusals"]:
        add("warn", f"Protected copies were refused their unlock key {integ['key_refusals']}×",
            "A copy asked to run after it expired, was withdrawn, or from the wrong place/account.")
    settings = get_settings()
    launches = sorted(_aw(d.served_at) for d in bundle.deliveries.get(lid, []) if d.served_at)
    peak = 0
    j = 0
    for i, t in enumerate(launches):
        while launches[j] < t - timedelta(hours=24):
            j += 1
        peak = max(peak, i - j + 1)
    if peak > settings.ASSET_LAUNCH_ALERT_PER_DAY:
        add("warn", f"Launched protected material {peak}× within 24 hours",
            f"More than the {settings.ASSET_LAUNCH_ALERT_PER_DAY} a day that normal study needs.")

    # Simulator behaviour
    for e in events:
        if e.kind == "sim_session" and e.severity in ("warn", "alert"):
            add(e.severity,
                "Simulator driven far faster than by hand — possibly a script reading the model"
                if e.severity == "alert" else "Unusually many simulator commands in one session",
                e.label, e.at)
        if e.kind == "sim_refused" and e.severity in ("warn", "alert"):
            add(e.severity, e.label, e.detail.get("origin", ""), e.at)

    # Passwords
    fails = [e.at for e in events if e.kind == "sign_in_failed"]
    j = 0
    worst = 0
    for i, t in enumerate(fails):
        while fails[j] < t - timedelta(hours=1):
            j += 1
        worst = max(worst, i - j + 1)
    if worst >= FAILED_PASSWORDS_PER_HOUR:
        add("warn", f"{worst} wrong passwords within one hour on the quiz-app sign-in",
            "Either a forgotten password or someone guessing it.")

    # Evaluations passed implausibly fast (needs the open time, so only
    # attempts made after activity tracking began can be judged).
    opens = [e for e in events if e.kind == "quiz_open"]
    for q in (e for e in events if e.kind == "quiz_submit" and e.detail.get("passed")):
        items = int(q.detail.get("items") or 0)
        if items < FAST_PASS_MIN_ITEMS:
            continue
        before = [o for o in opens
                  if o.detail.get("module_id") == q.detail.get("module_id")
                  and o.detail.get("item_set") == q.detail.get("item_set")
                  # the attempt's time is the database clock (whole seconds
                  # on SQLite); allow for that against the app clock
                  and o.at <= q.at + timedelta(seconds=5)]
        if not before:
            continue
        secs = max(0.0, (q.at - before[-1].at).total_seconds())
        if secs < max(FAST_PASS_MIN_SECONDS, items * FAST_PASS_SECONDS_PER_ITEM):
            add("warn", f"Passed in {int(secs)} s — {q.label}",
                f"{items} questions answered in {int(secs)} seconds after opening. "
                "Can mean the answers were known in advance.", q.at)

    if learner is not None and learner.status != "active":
        add("info", "Account is blocked")

    out.sort(key=lambda f: SEVERITY_RANK[f["severity"]], reverse=True)
    return out


# --------------------------------------------------------------- progress --

def progress(db: Session, learner_ids: list[int], product_codes: set[str]) -> dict:
    """Lessons and evaluation sets done per (learner, product), computed in
    bulk with the same rule as certificates.completion_status."""
    codes = sorted(product_codes)
    if not codes or not learner_ids:
        return {}
    modules = db.execute(
        select(Module).where(Module.product_code.in_(codes)).order_by(Module.position)
    ).scalars().all()
    mids = [m.id for m in modules] or [0]
    lessons = db.execute(select(Lesson).where(Lesson.module_id.in_(mids))).scalars().all()
    totals = svc.slide_totals(db, mids)
    sets = {(mid, s) for mid, s in db.execute(
        select(QuizItem.module_id, QuizItem.item_set)
        .where(QuizItem.module_id.in_(mids), QuizItem.item_set.in_(["formative", "summative"]))
        .distinct()
    ).all()}
    prog: dict[tuple[int, int], LessonProgress] = {
        (p.learner_id, p.lesson_id): p for p in db.execute(
            select(LessonProgress).where(
                LessonProgress.learner_id.in_(learner_ids),
                LessonProgress.lesson_id.in_([l.id for l in lessons] or [0]),
            )
        ).scalars()
    }
    passed = {(lid, mid, s) for lid, mid, s in db.execute(
        select(QuizAttempt.learner_id, QuizAttempt.module_id, QuizAttempt.item_set)
        .where(QuizAttempt.learner_id.in_(learner_ids), QuizAttempt.module_id.in_(mids),
               QuizAttempt.passed.is_(True))
    ).all()}
    mod_product = {m.id: m.product_code for m in modules}
    out: dict[tuple[int, str], dict] = {}
    for lid in learner_ids:
        for code in codes:
            out[(lid, code)] = {"lessons_done": 0, "lessons_total": 0,
                                "sets_passed": 0, "sets_total": 0}
        for l in lessons:
            row = out[(lid, mod_product[l.module_id])]
            row["lessons_total"] += 1
            if svc.lesson_is_complete(l, prog.get((lid, l.id)), totals.get(l.module_id)):
                row["lessons_done"] += 1
        for mid, s in sets:
            row = out[(lid, mod_product[mid])]
            row["sets_total"] += 1
            if (lid, mid, s) in passed:
                row["sets_passed"] += 1
    for row in out.values():
        row["complete"] = (row["lessons_total"] > 0
                           and row["lessons_done"] == row["lessons_total"]
                           and row["sets_passed"] == row["sets_total"])
    return out


def course_breakdown(db: Session, learner: Learner, code: str) -> dict:
    """Per module: every lesson with its completion date, and each evaluation
    set with its best score, attempts and when it was first passed."""
    modules = db.execute(
        select(Module).where(Module.product_code == code).order_by(Module.position)
    ).scalars().all()
    mids = [m.id for m in modules] or [0]
    lessons = db.execute(
        select(Lesson).where(Lesson.module_id.in_(mids)).order_by(Lesson.position)
    ).scalars().all()
    prog = svc.progress_map(db, learner, [l.id for l in lessons])
    totals = svc.slide_totals(db, mids)
    attempts = _group(db.execute(
        select(QuizAttempt).where(QuizAttempt.learner_id == learner.id,
                                  QuizAttempt.module_id.in_(mids))
        .order_by(QuizAttempt.submitted_at)
    ).scalars(), lambda a: a.module_id)
    sets = {(mid, s) for mid, s in db.execute(
        select(QuizItem.module_id, QuizItem.item_set)
        .where(QuizItem.module_id.in_(mids)).distinct()
    ).all()}
    out_modules = []
    for m in modules:
        ls = []
        for l in (x for x in lessons if x.module_id == m.id):
            p = prog.get(l.id)
            ls.append({
                "id": l.id, "title": l.title, "kind": l.kind,
                "done": svc.lesson_is_complete(l, p, totals.get(m.id)),
                "completed_at": _iso(p.completed_at) if p else None,
                "time_s": (p.watched_s or 0) if p else 0,
                "last_at": _iso(p.updated_at) if p else None,
            })
        evals = []
        for s in ("formative", "summative"):
            if (m.id, s) not in sets:
                continue
            tries = [a for a in attempts.get(m.id, []) if a.item_set == s]
            first_pass = next((a for a in tries if a.passed), None)
            evals.append({
                "item_set": s,
                "name": "Evaluation" if s == "formative" else "Mastery check",
                "attempts": len(tries),
                "best_score": max((a.score_pct for a in tries), default=None),
                "passed": first_pass is not None,
                "passed_at": _iso(first_pass.submitted_at) if first_pass else None,
                "last_at": _iso(tries[-1].submitted_at) if tries else None,
            })
        out_modules.append({"id": m.id, "code": m.code, "title": m.title,
                            "lessons": ls, "evaluations": evals})
    return {"modules": out_modules}


# ---------------------------------------------------------------- outputs --

def _cert_out(c: Certificate) -> dict:
    return {
        "tier": c.tier,
        "title": TIER_TITLES.get(c.tier, c.tier),
        "code": c.code,
        "status": c.status,
        "product_code": c.product_code,
        "course_title": c.course_title,
        "issued_at": _iso(c.issued_at),
        "email_sent_at": _iso(c.email_sent_at),
        "revoke_reason": c.revoke_reason or "",
    }


def _last_seen(bundle: Bundle, lid: int) -> datetime | None:
    stamps = [_aw(v.last_seen_at) for v in bundle.visits.get(lid, [])]
    stamps += [_aw(d.last_seen_at) for d in bundle.devices.get(lid, [])]
    stamps += [e.end or e.at for e in bundle.events.get(lid, [])
               if e.kind not in ("access", "certificate", "new_device")]
    learner = bundle.learners.get(lid)
    if learner is not None:
        stamps.append(_aw(learner.last_login_at))
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def _worst(fl: list[dict]) -> str:
    return max((f["severity"] for f in fl), key=lambda s: SEVERITY_RANK[s], default="")


def summary_row(db: Session, bundle: Bundle, lid: int, prog: dict,
                product_titles: dict[str, str], only_product: str = "") -> dict:
    learner = bundle.learners[lid]
    visits = build_visits(bundle, lid)
    owner = svc.is_owner(learner)
    fl = flags(bundle, lid)
    codes = sorted(bundle.products.get(lid, set()))
    if only_product:
        codes = [c for c in codes if c == only_product]
    return {
        "id": lid,
        "email": learner.email,
        "full_name": learner.full_name or "",
        "status": learner.status,
        "is_owner": owner,
        "created_at": _iso(learner.created_at),
        "last_seen_at": _iso(_last_seen(bundle, lid)),
        "visits": sum(1 for v in visits if v["counts_as_visit"]),
        "visits_tracked": sum(1 for v in visits if v["source"] == "tracked"),
        "sign_ins": sum(1 for e in bundle.events.get(lid, []) if e.kind == "sign_in"),
        "courses": [{
            "code": c, "title": product_titles.get(c, c),
            **prog.get((lid, c), {"lessons_done": 0, "lessons_total": 0,
                                  "sets_passed": 0, "sets_total": 0, "complete": False}),
        } for c in codes],
        "certificates": [_cert_out(c) for c in bundle.certificates.get(lid, [])],
        "integrity": integrity(bundle, lid),
        "flags": fl,
        "worst": _worst(fl),
    }


def learner_ids_for(db: Session, product_code: str, q: str) -> list[int]:
    stmt = select(Learner.id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Learner.email).like(like),
                              func.lower(Learner.full_name).like(like)))
    ids = [r[0] for r in db.execute(stmt.order_by(Learner.id)).all()]
    if not product_code:
        return ids
    keep = {r[0] for r in db.execute(
        select(Enrollment.learner_id).where(Enrollment.product_code == product_code))}
    mids = [r[0] for r in db.execute(
        select(Module.id).where(Module.product_code == product_code))] or [0]
    keep |= {r[0] for r in db.execute(
        select(ModuleGrant.learner_id).where(ModuleGrant.module_id.in_(mids)))}
    lids = [r[0] for r in db.execute(select(Lesson.id).where(Lesson.module_id.in_(mids)))] or [0]
    keep |= {r[0] for r in db.execute(
        select(LessonProgress.learner_id).where(LessonProgress.lesson_id.in_(lids)))}
    keep |= {r[0] for r in db.execute(
        select(Certificate.learner_id).where(Certificate.product_code == product_code))}
    return [i for i in ids if i in keep]


def summaries(db: Session, product_code: str, since: datetime, q: str = "") -> dict:
    ids = learner_ids_for(db, product_code, q)
    bundle = load(db, ids, since)
    all_codes = set().union(*bundle.products.values()) if bundle.products else set()
    prog = progress(db, ids, all_codes)
    titles = dict(db.execute(select(Product.code, Product.title)).all())
    rows = [summary_row(db, bundle, lid, prog, titles, product_code)
            for lid in ids if lid in bundle.learners]
    rows.sort(key=lambda r: r["last_seen_at"] or "", reverse=True)
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    students = [r for r in rows if not r["is_owner"]]
    return {
        "since": since.isoformat(),
        "tracking_since": _iso(bundle.tracking_since),
        "product_code": product_code,
        "totals": {
            "students": len(students),
            "active_7d": sum(1 for r in students if (r["last_seen_at"] or "") >= week),
            "visits": sum(r["visits"] for r in students),
            "certificates": sum(1 for r in students for c in r["certificates"]
                                if c["status"] == "issued"),
            "flagged": sum(1 for r in students if r["worst"] in ("warn", "alert")),
        },
        "learners": rows,
    }


def detail(db: Session, learner: Learner, since: datetime) -> dict:
    bundle = load(db, [learner.id], since)
    codes = bundle.products.get(learner.id, set())
    prog = progress(db, [learner.id], codes)
    titles = dict(db.execute(select(Product.code, Product.title)).all())
    row = summary_row(db, bundle, learner.id, prog, titles)
    courses = []
    for c in row["courses"]:
        courses.append({**c, **course_breakdown(db, learner, c["code"])})
    return {
        "since": since.isoformat(),
        "tracking_since": _iso(bundle.tracking_since),
        "learner": row,
        "visits": build_visits(bundle, learner.id)[:400],
        "courses": courses,
        "devices": integrity_devices(bundle, learner.id),
    }
