"""Customer emails that never arrive must reach the instructor, not wait for a complaint.

What happened (2026-11-09): Hotmail refused a registration confirmation
("Message lacks SPF/DKIM/DMARC Auth Records"). The site only asked Resend
about an email when it was opened in Admin -> Comms, so nobody knew.

What is asserted:

  * A customer email that bounced (or was suppressed, or never accepted)
    produces exactly one alert to ADMIN_NOTIFY_EMAIL, naming the person and
    linking to the email in Resend; the next sweep sends nothing more.
  * Delivered emails are recorded and not asked about again.
  * Emails to the instructor himself, and emails older than the watch
    window, are left alone.
  * A failed alert is retried on the next sweep; a Resend outage changes
    nothing and is retried.
  * Only the cron secret or the admin can trigger a sweep.

Resend is faked at its two seams: emailer._resend_post and
email_copies._resend_get.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import conftest  # noqa: F401
from app import delivery_watch as watch
from app import email_copies as copies
from app import emailer as E
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Course, EmailLog, Registration

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
ALERT_TO = "bmsabry@gmail.com"


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture()
def db():
    s = SessionLocal()
    s.query(EmailLog).delete()
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def resend(monkeypatch):
    """Sends succeed (or fail when told to); delivery reports are scripted."""
    settings = get_settings()
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test", raising=False)
    monkeypatch.setattr(settings, "ADMIN_NOTIFY_EMAIL", ALERT_TO, raising=False)
    state = {"n": 0, "refuse_to": set(), "sent": [], "events": {}, "asked": [], "down": False}

    def post(url, payload, key):
        to = payload["to"][0]
        if to in state["refuse_to"]:
            return _Resp(500, {"message": "temporary failure"})
        state["n"] += 1
        state["sent"].append(payload)
        return _Resp(body={"id": f"re-{state['n']}"})

    def get(url, key):
        rid = url.rsplit("/", 1)[-1]
        state["asked"].append(rid)
        if state["down"]:
            return None
        if rid in state["events"]:
            return _Resp(body={"id": rid, "last_event": state["events"][rid]})
        return _Resp(body={"id": rid, "last_event": "sent"})

    monkeypatch.setattr(E, "_resend_post", post)
    monkeypatch.setattr(copies, "_resend_get", get)
    return state


def _send(db, to, template="applicant_confirmation", subject="Registration received — GT", **kw):
    E.send_email(to=to, subject=subject, html="<p>Hello</p>", db=db, template=template, **kw)
    db.expire_all()
    return db.query(EmailLog).filter(EmailLog.recipient == to).order_by(EmailLog.id.desc()).first()


def _alerts(db, row_id=None):
    db.expire_all()
    q = db.query(EmailLog).filter(EmailLog.template == watch.ALERT_TEMPLATE)
    if row_id is not None:
        q = q.filter(EmailLog.scope_code == f"email:{row_id}")
    return q.all()


def _sweep(db, **kw):
    return watch.sweep(db, pause=0, **kw)


def test_a_bounced_confirmation_alerts_once_with_who_it_was(db, resend):
    code = "delivery-watch-course"
    if not db.query(Course).filter(Course.code == code).first():
        db.add(Course(
            code=code, title="Gas Turbine Emissions Mapping", start_date=date(2030, 11, 14),
            total_seats=15, status="open",
        ))
        db.commit()
    db.add(Registration(
        course_code=code, full_name="Sabry Mohammad", email="trainee@hotmail.example",
        job_title="Engineer", company="Self employed", years_experience="6-10",
        location="Egypt", status="pending",
    ))
    db.commit()
    row = _send(db, "trainee@hotmail.example", scope_kind="course", scope_code=code)
    resend["events"][row.provider_id] = "bounced"

    out = _sweep(db)
    assert out["alerts_sent"] == 1 and out["alerts_failed"] == 0
    db.expire_all()
    assert db.get(EmailLog, row.id).delivery == "bounced", "Comms shows it without opening"

    (alert,) = _alerts(db, row.id)
    assert alert.recipient == ALERT_TO and alert.audience == "admin" and alert.ok
    assert "trainee@hotmail.example" in alert.subject and "Bounced" in alert.subject
    html = resend["sent"][-1]["html"]
    assert "Sabry Mohammad" in html
    assert "Gas Turbine Emissions Mapping" in html and "pending" in html
    assert "Egypt" in html
    assert f"https://resend.com/emails/{row.provider_id}" in html
    assert "/admin#comms" in html

    asked_before = len(resend["asked"])
    again = _sweep(db)
    assert again["alerts_sent"] == 0 and len(_alerts(db, row.id)) == 1, "one alert per email"
    assert len(resend["asked"]) == asked_before, "a settled email is not asked about again"


def test_delivered_is_recorded_and_left_alone(db, resend):
    row = _send(db, "fine@example.com")
    resend["events"][row.provider_id] = "delivered"
    out = _sweep(db)
    assert out["alerts_sent"] == 0 and out["looked_up"] == 1
    db.expire_all()
    assert db.get(EmailLog, row.id).delivery == "delivered"
    _sweep(db)
    assert resend["asked"].count(row.provider_id) == 1


def test_not_yet_settled_is_asked_again_next_time(db, resend):
    row = _send(db, "slow@example.com")
    resend["events"][row.provider_id] = "delivery_delayed"
    assert _sweep(db)["still_pending"] == 1
    resend["events"][row.provider_id] = "suppressed"
    out = _sweep(db)
    assert out["alerts_sent"] == 1 and len(_alerts(db, row.id)) == 1


def test_an_email_resend_never_accepted_alerts_without_asking_resend(db, resend):
    resend["refuse_to"].add("never@example.com")
    row = _send(db, "never@example.com")
    assert row.ok is False
    out = _sweep(db)
    assert out["alerts_sent"] == 1 and row.provider_id not in resend["asked"]
    assert "Not sent" in _alerts(db, row.id)[0].subject


def test_emails_to_the_instructor_are_not_watched(db, resend):
    row = _send(db, ALERT_TO, template="admin_new_registration", audience="admin")
    resend["events"][row.provider_id] = "bounced"
    out = _sweep(db)
    assert out == {**out, "looked_up": 0, "alerts_sent": 0}
    assert not _alerts(db)


def test_old_emails_are_outside_the_window(db, resend):
    row = _send(db, "old@example.com")
    resend["events"][row.provider_id] = "bounced"
    later = datetime.now(timezone.utc) + timedelta(hours=watch.WATCH_HOURS + 1)
    out = _sweep(db, now=later)
    assert out["looked_up"] == 0 and out["alerts_sent"] == 0


def test_a_failed_alert_is_retried(db, resend):
    row = _send(db, "bounce2@example.com")
    resend["events"][row.provider_id] = "bounced"
    resend["refuse_to"].add(ALERT_TO)
    out = _sweep(db)
    assert out["alerts_failed"] == 1 and out["alerts_sent"] == 0
    resend["refuse_to"].discard(ALERT_TO)
    out = _sweep(db)
    assert out["alerts_sent"] == 1
    assert len([a for a in _alerts(db, row.id) if a.ok]) == 1


def test_a_resend_outage_changes_nothing_and_is_retried(db, resend):
    row = _send(db, "later@example.com")
    resend["events"][row.provider_id] = "bounced"
    resend["down"] = True
    out = _sweep(db)
    assert out["lookup_errors"] == 1 and out["alerts_sent"] == 0
    db.expire_all()
    assert db.get(EmailLog, row.id).delivery == ""
    resend["down"] = False
    assert _sweep(db)["alerts_sent"] == 1


def test_one_run_is_capped(db, resend):
    rows = [_send(db, f"cap{i}@example.com") for i in range(5)]
    out = _sweep(db, max_lookups=3)
    assert out["looked_up"] == 3, "the rest wait for the next run"
    assert out["still_pending"] == 5, "all five are still unsettled after this run"
    assert {r.provider_id for r in rows[:3]} <= set(resend["asked"]), "oldest first"


def test_only_the_cron_secret_or_the_admin_can_sweep(db, resend, monkeypatch):
    monkeypatch.setattr(get_settings(), "CRON_SECRET", "cron-secret-xyz", raising=False)
    with TestClient(app) as client:
        assert client.post("/api/admin/email-delivery/sweep").status_code == 401
        assert client.post(
            "/api/admin/email-delivery/sweep", headers={"X-Cron-Secret": "wrong"}
        ).status_code == 401
        ok = client.post("/api/admin/email-delivery/sweep", headers={"X-Cron-Secret": "cron-secret-xyz"})
        assert ok.status_code == 200 and "alerts_sent" in ok.json()
        assert client.post("/api/admin/email-delivery/sweep", headers=ADMIN).status_code == 200


def test_the_alert_reads_as_a_problem_in_comms(db, resend):
    row = _send(db, "comms@example.com")
    resend["events"][row.provider_id] = "bounced"
    _sweep(db)
    with TestClient(app) as client:
        rows = client.get("/api/admin/comms/log?problems=true", headers=ADMIN).json()["rows"]
        assert row.id in [r["id"] for r in rows], "the bounce is under Problems only"
        alert = _alerts(db, row.id)[0]
        d = client.get(f"/api/admin/comms/log/{alert.id}", headers=ADMIN).json()
        assert d["kind_label"] == "Email problem (alert)"
        assert d["about"]["label"] == f"Email #{row.id} not delivered"
