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
  * Resend's signed webhook records the receiving server's own words and
    alerts within seconds; unsigned or foreign events change nothing.
  * The DNS records email depends on are checked every run (alert at most
    once a day); a daily canary goes to the instructor's own mailboxes and a
    refused canary is reported as a provider problem.
  * Every email the site sends is logged (sign-in links included), and the
    registration form's optional WhatsApp/phone reaches the alerts.

Resend is faked at its two seams: emailer._resend_post and
email_copies._resend_get.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import base64
import hashlib
import hmac
import json
import time

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


GOOD_DNS = {
    (name, rtype): [needle + " ok"] for name, rtype, needle, _why in watch.DNS_EXPECTED
}


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """No network in tests: DNS answers are scripted (all good by default)."""
    answers = dict(GOOD_DNS)
    monkeypatch.setattr(watch, "_doh", lambda name, rtype: answers.get((name, rtype)))
    return answers


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


# ---------------------------------------------------------------------------
# Resend's webhook: the provider's own words, within seconds
# ---------------------------------------------------------------------------

SECRET = "whsec_" + base64.b64encode(b"test-webhook-key-0123456789").decode()


def _signed(event: dict, secret: str = SECRET, ts: int | None = None) -> tuple[bytes, dict]:
    body = json.dumps(event).encode()
    ts = ts or int(time.time())
    key = base64.b64decode(secret.split("_", 1)[1])
    sig = base64.b64encode(hmac.new(key, f"msg_1.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return body, {"svix-id": "msg_1", "svix-timestamp": str(ts), "svix-signature": f"v1,{sig}",
                  "content-type": "application/json"}


def _bounce(email_id: str) -> dict:
    return {"type": "email.bounced", "data": {
        "email_id": email_id, "to": ["x@hotmail.example"],
        "bounce": {"type": "Transient", "subType": "General",
                   "message": "The recipient's email provider sent a general bounce message.",
                   "diagnosticCode": ["smtp; 550 5.7.1 Message rejected: Message lacks SPF/DKIM/DMARC Auth Records"]},
    }}


def test_a_signed_bounce_records_the_reason_and_alerts_at_once(db, resend, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESEND_WEBHOOK_SECRET", SECRET, raising=False)
    row = _send(db, "x@hotmail.example")
    body, headers = _signed(_bounce(row.provider_id))
    with TestClient(app) as client:
        r = client.post("/api/webhooks/resend-events", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["result"] == "bounced, alerted"
    db.expire_all()
    got = db.get(EmailLog, row.id)
    assert got.delivery == "bounced"
    assert "550 5.7.1 Message rejected" in got.delivery_detail
    assert "550 5.7.1" in resend["sent"][-1]["html"], "the alert quotes the provider"
    assert len(_alerts(db, row.id)) == 1
    assert _sweep(db)["alerts_sent"] == 0, "the sweep does not alert twice"


def test_unsigned_or_wrongly_signed_events_are_refused(db, resend, monkeypatch):
    row = _send(db, "y@hotmail.example")
    monkeypatch.setattr(get_settings(), "RESEND_WEBHOOK_SECRET", SECRET, raising=False)
    with TestClient(app) as client:
        body, headers = _signed(_bounce(row.provider_id), secret="whsec_" + base64.b64encode(b"other").decode())
        assert client.post("/api/webhooks/resend-events", content=body, headers=headers).status_code == 401
        body, headers = _signed(_bounce(row.provider_id), ts=int(time.time()) - 3600)
        assert client.post("/api/webhooks/resend-events", content=body, headers=headers).status_code == 401
        monkeypatch.setattr(get_settings(), "RESEND_WEBHOOK_SECRET", "", raising=False)
        body, headers = _signed(_bounce(row.provider_id))
        assert client.post("/api/webhooks/resend-events", content=body, headers=headers).status_code == 401
    db.expire_all()
    assert db.get(EmailLog, row.id).delivery == "" and not _alerts(db)


def test_events_for_the_other_business_are_ignored(db, resend, monkeypatch):
    monkeypatch.setattr(get_settings(), "RESEND_WEBHOOK_SECRET", SECRET, raising=False)
    body, headers = _signed(_bounce("promech-email-id"))
    with TestClient(app) as client:
        r = client.post("/api/webhooks/resend-events", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["result"] == "not ours"
    assert not _alerts(db)


def test_a_late_delivered_event_does_not_undo_a_bounce(db, resend):
    row = _send(db, "z@hotmail.example")
    assert watch.apply_event(db, _bounce(row.provider_id)) == "bounced, alerted"
    assert watch.apply_event(db, {"type": "email.delivered", "data": {"email_id": row.provider_id}}) == "delivered"
    db.expire_all()
    assert db.get(EmailLog, row.id).delivery == "bounced"


# ---------------------------------------------------------------------------
# DNS guard and daily canary
# ---------------------------------------------------------------------------


def test_dns_all_good_sends_nothing(db, resend):
    out = watch.dns_check(db, datetime.now(timezone.utc))
    assert out == {"failures": [], "unchecked": 0, "alerted": False}


def test_a_missing_dmarc_record_alerts_once_a_day(db, resend, dns):
    dns[("_dmarc.proreadyengineer.com", "TXT")] = []
    now = datetime.now(timezone.utc)
    first = watch.dns_check(db, now)
    assert first["alerted"] is True and first["failures"] == ["TXT _dmarc.proreadyengineer.com"]
    html = resend["sent"][-1]["html"]
    assert "Microsoft refuses mail without one" in html and "no record" in html
    assert watch.dns_check(db, now + timedelta(hours=1))["alerted"] is False


def test_dns_that_cannot_be_reached_is_not_an_alarm(db, resend, dns):
    for k in list(dns):
        dns[k] = None
    out = watch.dns_check(db, datetime.now(timezone.utc))
    assert out["unchecked"] == len(watch.DNS_EXPECTED) and out["alerted"] is False


def test_the_canary_goes_once_a_day_after_the_hour(db, resend, monkeypatch):
    monkeypatch.setattr(get_settings(), "CANARY_EMAILS", "me@hotmail.example, me@yahoo.example", raising=False)
    monkeypatch.setattr(get_settings(), "CANARY_HOUR_UTC", 13, raising=False)
    early = datetime(2030, 1, 5, 9, 0, tzinfo=timezone.utc)
    assert watch.send_canaries(db, early)["sent"] == 0
    noon = datetime(2030, 1, 5, 14, 0, tzinfo=timezone.utc)
    assert watch.send_canaries(db, noon)["sent"] == 2
    assert {p["to"][0] for p in resend["sent"]} == {"me@hotmail.example", "me@yahoo.example"}
    assert watch.send_canaries(db, datetime.now(timezone.utc))["sent"] == 0, "once a day"


def test_a_refused_canary_is_reported_as_a_provider_problem(db, resend, monkeypatch):
    monkeypatch.setattr(get_settings(), "CANARY_EMAILS", "me@hotmail.example", raising=False)
    monkeypatch.setattr(get_settings(), "CANARY_HOUR_UTC", 0, raising=False)
    watch.send_canaries(db, datetime.now(timezone.utc))
    row = db.query(EmailLog).filter(EmailLog.template == watch.CANARY_TEMPLATE).one()
    resend["events"][row.provider_id] = "bounced"
    assert _sweep(db)["alerts_sent"] == 1
    alert = _alerts(db, row.id)[0]
    assert alert.subject == "[Email problem] hotmail.example refused our daily test email"
    assert "probably not receiving" in resend["sent"][-1]["html"]


# ---------------------------------------------------------------------------
# Every email logged; the trainee's other channel reaches the alert
# ---------------------------------------------------------------------------


def test_a_sign_in_link_is_logged_and_watched(db, resend):
    from app.models import Learner
    if not db.query(Learner).filter(Learner.email == "signin-watch@example.com").first():
        db.add(Learner(email="signin-watch@example.com", full_name="Sign In", status="active"))
        db.commit()
    with TestClient(app) as client:
        assert client.post("/api/academy/auth/request-link",
                           json={"email": "signin-watch@example.com"}).status_code == 200
    db.expire_all()
    row = db.query(EmailLog).filter(EmailLog.recipient == "signin-watch@example.com").one()
    assert row.template == "login_link" and row.ok and "token=(hidden)" in row.body_html
    resend["events"][row.provider_id] = "bounced"
    assert _sweep(db)["alerts_sent"] == 1


def test_the_whatsapp_number_reaches_the_admin_and_the_alert(db, resend):
    code = "delivery-watch-phone"
    if not db.query(Course).filter(Course.code == code).first():
        db.add(Course(code=code, title="Phone Cohort", start_date=date(2030, 11, 14),
                      total_seats=15, status="open"))
        db.commit()
    with TestClient(app) as client:
        r = client.post("/api/register", json={
            "course_code": code, "full_name": "Wa Trainee", "email": "wa@hotmail.example",
            "job_title": "Engineer", "company": "Co", "years_experience": "3-5",
            "location": "Algiers", "phone": "+213 555 12 34 56",
        })
        assert r.status_code == 200, r.text
        regs = client.get("/api/admin/registrations", headers=ADMIN).json()
    assert next(x for x in regs if x["email"] == "wa@hotmail.example")["phone"] == "+213 555 12 34 56"
    admin_mail = next(p for p in resend["sent"] if p["to"][0] == ALERT_TO)
    assert "+213 555 12 34 56" in admin_mail["html"]
    assert "Seats held now: 1 of 15 (paid and pending together)" in admin_mail["html"]
    db.expire_all()
    row = db.query(EmailLog).filter(EmailLog.recipient == "wa@hotmail.example").one()
    resend["events"][row.provider_id] = "bounced"
    _sweep(db)
    assert "+213 555 12 34 56" in resend["sent"][-1]["html"], "the alert gives the other way to reach them"
