"""Consulting calls: what the cron tick does once the meeting is over.

  attendance   at the scheduled end, from the Google Meet REST API (faked
               here at the calendar code's own seam): both joined, the client
               did not, the host did not, or "unknown" when the Meet
               permission is missing or Google will not answer
  the summary  one email to the owner with what will happen by itself and
               three links. A link shows a confirm page on GET and changes
               nothing; the POST behind the page's button decides, once;
               after the automatic outcome's time it has expired
  the outcome  two hours after the scheduled end unless he chose: both
               joined, the booked amount is captured from the hold; client
               absent, 20% is captured and the rest released; host absent,
               everything is released; unknown, charged in full. With no
               hold, the saved card is charged directly
  the client   a receipt after a charge, a fee notice after a no-show fee

The Wednesday call is 60 minutes at the tests' artificial $111: fee $22.20.
FakeStripe.money_taken() is what cards were really charged.
"""
from __future__ import annotations

import re
import threading
from datetime import timedelta

import pytest

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    ADMIN_API,
    OWNER,
    PUBLIC,
    booking_row,
    charges_of,
    client,
    confirmed,
    env,
    events_of,
    grant_meet_scope,
    iso,
    ny,
    save_card,
    state_of_everything,
    subjects,
    tick,
    to,
    world,
)

from app import consult
from app import consult_auto
from app import consult_money as money
from app import emailer
from app import exam_calendar as xcal
from app.config import get_settings
from app.consult_models import ConsultBooking
from app.db import SessionLocal
from app.models import EmailLog

START = ny(2031, 6, 11, 10)                 # Wednesday 10:00 New York
END = START + timedelta(hours=1)
DUE = END + timedelta(hours=2)              # when the automatic outcome runs
CLIENT = "client@example.com"
DECISION = "/api/consult/decision"


def _mails(env, addr: str, words: str) -> list[dict]:
    return [m for m in to(env.outbox, addr) if words in m["subject"]]


def _held(client, env, start=START, minutes=60, **kw) -> dict:
    """A confirmed booking whose hold was placed by the tick the day before."""
    b = confirmed(client, env, start, minutes, **kw)
    env.clock.set(start - timedelta(hours=24))
    tick(client)
    assert booking_row(b["ref"]).hold_state == "authorized"
    return b


def _meet(env, b: dict, *people, start=None, end=None):
    """Who was in the meeting: (who, name, minutes after START joined, left)."""
    url = booking_row(b["ref"]).meet_url
    rows = [
        (who, name, START + timedelta(minutes=a), None if z is None else START + timedelta(minutes=z))
        for who, name, a, z in people
    ]
    return env.google.conference(url, start or START - timedelta(minutes=2), end, *rows)


HOST = ("host", "Bassam Abdelnabi", 0, 58)
GUEST = ("guest", "Casey Client", 1, 58)


def _links(env) -> dict[str, str]:
    """The three decision links in the owner's summary email, as paths."""
    (mail,) = _mails(env, OWNER, "Call ended")
    found = re.findall(r'href="https://api\.proreadyengineer\.com(/api/consult/decision\?token=[^"]+)"', mail["html"])
    assert len(found) == 3, found
    return dict(zip(("charge", "no_show", "waive"), found))


def _admin(client, b: dict, action: str, body: dict | None = None):
    return client.post(f"{ADMIN_API}/bookings/{b['id']}/{action}", headers=ADMIN, json=body or {})


def _a(client, b: dict) -> dict:
    return client.get(f"{ADMIN_API}/bookings/{b['id']}", headers=ADMIN).json()


# -----------------------------------------------------------------------------
# Attendance
# -----------------------------------------------------------------------------

def test_without_the_meet_permission_attendance_is_unknown_and_google_is_not_asked(client, env):
    b = _held(client, env)
    env.clock.set(END - timedelta(minutes=1))
    tick(client)
    assert booking_row(b["ref"]).attendance_state == ""            # not before the scheduled end
    env.clock.set(END)
    out = tick(client)
    assert out["done"]["attendance:unknown"] == 1 and out["done"]["summary"] == 1
    a = _a(client, b)
    assert a["attendance"]["state"] == "unknown" and a["attendance"]["checked_at"] == iso(END)
    assert "does not include the Meet permission" in a["attendance"]["note"]
    assert env.google.meet_calls() == 0
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["meet_scope_ok"] is False


def test_both_joined(client, env):
    grant_meet_scope()
    assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["meet_scope_ok"] is True
    b = _held(client, env)
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    env.clock.set(END)
    assert tick(client)["done"]["attendance:both"] == 1
    a = _a(client, b)["attendance"]
    assert (a["state"], a["host_joined"], a["others_joined"]) == ("both", True, 1)
    assert a["participants"] == [
        "You (Bassam Abdelnabi): joined 10:00 AM EDT, left 10:58 AM EDT",
        "Casey Client (not signed in): joined 10:01 AM EDT, left 10:58 AM EDT (56 min in the call with you)",
    ]
    # asked the way the Meet API wants it: by meeting code, then each record's participants
    code = booking_row(b["ref"]).meet_url.rsplit("/", 1)[-1]
    asked = [(u, c["params"]) for m, u, c in env.google.calls if u.startswith(consult_auto.MEET_API)]
    assert asked[0] == (f"{consult_auto.MEET_API}/conferenceRecords",
                        {"filter": f'space.meeting_code = "{code}"', "pageSize": 100})
    assert asked[1][0] == f"{consult_auto.MEET_API}/conferenceRecords/rec-{code}-1/participants"
    assert "attendance_read" in events_of(b["id"])


def test_the_client_did_not_join(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, ("host", "Bassam Abdelnabi", 0, 20), end=START + timedelta(minutes=20))
    env.clock.set(END)
    tick(client)
    a = _a(client, b)["attendance"]
    assert (a["state"], a["host_joined"], a["others_joined"]) == ("client_absent", True, 0)
    assert a["note"] == "You joined; nobody else did."


def test_the_host_did_not_join(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, GUEST, end=START + timedelta(minutes=15))
    env.clock.set(END)
    tick(client)
    a = _a(client, b)["attendance"]
    assert (a["state"], a["host_joined"], a["others_joined"]) == ("host_absent", False, 1)
    assert "no record of the connected account joining" in a["note"]


def test_nobody_opened_the_link(client, env):
    grant_meet_scope()
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    a = _a(client, b)["attendance"]
    assert (a["state"], a["host_joined"], a["others_joined"], a["participants"]) == ("host_absent", False, 0, [])
    assert a["note"] == "Google Meet has no record of anyone joining this meeting."


@pytest.mark.parametrize(
    "break_it, words",
    [
        (lambda g: setattr(g, "meet_refuses", (403, "Google Meet API has not been used in project 1 before or it is disabled.")),
         "Google Meet refused the attendance check: Google Meet API has not been used"),
        (lambda g: setattr(g, "meet_down", True), "Google could not be asked who joined"),
        (lambda g: setattr(g, "userinfo_fails", True), "Google did not say which account is connected"),
    ],
)
def test_when_google_will_not_answer_attendance_is_unknown(client, env, break_it, words):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    break_it(env.google)
    env.clock.set(END)
    out = tick(client)
    assert out["ok"] is True and out["done"]["attendance:unknown"] == 1     # a failure to read is not a failed tick
    a = _a(client, b)["attendance"]
    assert a["state"] == "unknown" and words in a["note"] and a["host_joined"] is None


def test_a_booking_without_a_meet_link_is_unknown(client, env):
    grant_meet_scope()
    env.google.event_fails = True                                  # no event, so no link, the whole way
    b = confirmed(client, env, START)
    env.clock.set(END)
    tick(client)
    assert "no Google Meet link" in _a(client, b)["attendance"]["note"]
    assert env.google.meet_calls() == 0


def test_who_counts_as_another_participant(client, env):
    """A second signed-in account, a caller by phone and a guest each count.
    The host on two devices is still one host. A conference on the same link
    at some other time is not this call. Long lists come in pages."""
    grant_meet_scope()
    b = _held(client, env)
    url = booking_row(b["ref"]).meet_url
    # yesterday he and the client tried the link together for ten minutes: not this call
    env.google.conference(url, START - timedelta(hours=20), START - timedelta(hours=19, minutes=50),
                          ("host", "Bassam Abdelnabi", START - timedelta(hours=20), START - timedelta(hours=19, minutes=50)),
                          ("guest", "Casey Client", START - timedelta(hours=20), START - timedelta(hours=19, minutes=50)))
    _meet(env, b, HOST, ("host", "Bassam Abdelnabi", 5, 30), end=START + timedelta(minutes=30))   # two devices
    env.clock.set(END)
    tick(client)
    assert _a(client, b)["attendance"]["state"] == "client_absent"

    c = _held(client, env, ny(2031, 6, 12, 10), email="second@example.com", ip="203.0.113.2")
    url = booking_row(c["ref"]).meet_url
    day = ny(2031, 6, 12, 10)
    env.google.page_size = 1
    env.google.conference(url, day, day + timedelta(minutes=10), ("host", "Bassam Abdelnabi", day, day + timedelta(minutes=10)))
    env.google.conference(                                         # they dropped and came back: a second record
        url, day + timedelta(minutes=12), None,
        ("host", "Bassam Abdelnabi", day + timedelta(minutes=12), None),
        ("118000000000000000009", "Dana Signed-In", day + timedelta(minutes=13), None),
        ("phone", "+1 555-0100", day + timedelta(minutes=14), day + timedelta(minutes=40)),
    )
    env.clock.set(day + timedelta(hours=1))
    tick(client)
    a = _a(client, c)["attendance"]
    assert (a["state"], a["host_joined"], a["others_joined"]) == ("both", True, 2)
    assert a["participants"] == [
        "You (Bassam Abdelnabi): joined 10:00 AM EDT, still in the call",
        "Dana Signed-In: joined 10:13 AM EDT, still in the call (46 min in the call with you)",
        "+1 555-0100 (by phone): joined 10:14 AM EDT, left 10:40 AM EDT (25 min in the call with you)",
    ]


def test_a_record_that_arrives_late_is_seen_before_the_outcome_is_decided(client, env):
    grant_meet_scope()
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    assert booking_row(b["ref"]).attendance_state == "host_absent"     # Meet has nothing yet
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    env.clock.set(DUE)
    tick(client)
    row = booking_row(b["ref"])
    assert (row.attendance_state, row.settlement, row.charged_cents) == ("both", "charged", 11_100)


def test_a_later_read_that_fails_does_not_erase_what_was_seen(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, HOST, end=START + timedelta(minutes=30))
    env.clock.set(END)
    tick(client)
    env.google.meet_down = True
    env.clock.set(DUE)
    tick(client)
    row = booking_row(b["ref"])
    assert (row.attendance_state, row.settlement, row.charged_cents) == ("client_absent", "no_show", 2_220)


def test_attendance_is_recorded_for_a_call_he_settled_by_hand(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    env.clock.set(START + timedelta(minutes=50))
    assert _admin(client, b, "charge").status_code == 200          # he did not wait for the email
    env.outbox.clear()
    env.clock.set(END)
    tick(client)
    assert _a(client, b)["attendance"]["state"] == "both"          # kept with the booking, for the record
    assert env.outbox == [] and env.stripe.money_taken() == 11_100  # no summary, nothing more


# -----------------------------------------------------------------------------
# The Meet permission: asked for at the next connect, never required
# -----------------------------------------------------------------------------

def _consent_scopes(monkeypatch) -> list[str]:
    from urllib.parse import parse_qs, urlparse

    s = get_settings()
    monkeypatch.setattr(s, "GOOGLE_OAUTH_CLIENT_ID", "cid-123.apps.googleusercontent.com")
    monkeypatch.setattr(s, "GOOGLE_OAUTH_CLIENT_SECRET", "s3cret")
    db = SessionLocal()
    try:
        url = xcal.authorization_url(db, "admin@example.com")
    finally:
        db.close()
    return parse_qs(urlparse(url).query)["scope"][0].split()


def test_the_next_connect_asks_google_for_the_meet_permission(env, monkeypatch):
    asked = _consent_scopes(monkeypatch)
    assert "https://www.googleapis.com/auth/meetings.space.readonly" in asked
    assert "https://www.googleapis.com/auth/calendar.freebusy" in asked
    assert "https://www.googleapis.com/auth/calendar.events" in asked
    assert asked[:2] == ["openid", "email"] and len(asked) == 5      # read-only, and nothing else new
    # the way back, should Google's consent screen ever refuse it
    monkeypatch.setattr(get_settings(), "GOOGLE_REQUEST_MEET_SCOPE", False)
    assert _consent_scopes(monkeypatch) == [
        "openid", "email",
        "https://www.googleapis.com/auth/calendar.freebusy", "https://www.googleapis.com/auth/calendar.events",
    ]


@pytest.mark.parametrize("ticked_meet", [True, False])
def test_the_calendar_connects_with_or_without_the_meet_box_ticked(client, env, monkeypatch, ticked_meet):
    from urllib.parse import parse_qs, urlparse

    from app.models import ExamCalendar

    s = get_settings()
    monkeypatch.setattr(s, "GOOGLE_OAUTH_CLIENT_ID", "cid-123.apps.googleusercontent.com")
    monkeypatch.setattr(s, "GOOGLE_OAUTH_CLIENT_SECRET", "s3cret")
    granted = "openid https://www.googleapis.com/auth/userinfo.email " \
              "https://www.googleapis.com/auth/calendar.freebusy https://www.googleapis.com/auth/calendar.events"
    if ticked_meet:
        granted += " https://www.googleapis.com/auth/meetings.space.readonly"
    real = env.google

    def google(method, url, **kw):
        if url == xcal.TOKEN_URL and (kw.get("data") or {}).get("grant_type") == "authorization_code":
            return 200, {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 3600, "scope": granted}
        return real(method, url, **kw)

    monkeypatch.setattr(xcal, "_google", google)
    db = SessionLocal()
    before = db.get(ExamCalendar, 1).refresh_token_encrypted
    try:
        state = parse_qs(urlparse(xcal.authorization_url(db, "admin@example.com")).query)["state"][0]
        cal = xcal.complete_authorization(db, "c0de", state, "admin@example.com")
        assert xcal.connected(db) is True                           # the calendar itself connects either way
        assert xcal.has_scope(cal, xcal.MEET_SCOPE) is ticked_meet
        assert client.get(f"{ADMIN_API}/status", headers=ADMIN).json()["meet_scope_ok"] is ticked_meet
        assert client.get(f"{PUBLIC}/availability").json()["enabled"] is True
    finally:
        db.get(ExamCalendar, 1).refresh_token_encrypted = before
        db.commit()
        db.close()
        xcal._TOKEN.clear()


# -----------------------------------------------------------------------------
# The summary email
# -----------------------------------------------------------------------------

def test_the_owner_gets_one_summary_at_the_scheduled_end(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    env.outbox.clear()
    env.clock.set(END)
    assert tick(client)["done"]["summary"] == 1
    (mail,) = to(env.outbox, OWNER)
    assert mail["subject"] == "[Consulting] Call ended: confirm the outcome: Casey Client"
    html, text = mail["html"], mail["text"]
    assert "Wednesday, June 11, 2031 at 10:00 AM EDT (America/New_York), 60 minutes" in html
    assert "You and at least one other participant joined" in html
    assert "You (Bassam Abdelnabi): joined 10:00 AM EDT, left 10:58 AM EDT" in html
    assert "Casey Client (not signed in)" in html
    assert "$111 authorized on Visa ending 4242" in html
    assert "If you do nothing:</strong> The booked amount, $111, is charged." in html
    # the deadline, on his clock: two hours after the end
    assert html.count("Wednesday, June 11, 2031 at 1:00 PM EDT (America/New_York)") == 2
    for label in ("Charge in full: $111", "No-show: charge the 20% fee, $22.20", "Do not charge"):
        assert label in html and label in text
    assert "nothing happens until you press the button there" in html
    assert f"/admin#consult/booking/{b['id']}" in html
    links = _links(env)
    assert len(set(links.values())) == 3
    assert to(env.outbox, CLIENT) == []                             # nothing to the client yet
    assert env.stripe.money_taken() == 0                            # and nothing charged yet

    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert len(to(env.outbox, OWNER)) == 1 and events_of(b["id"]).count("summary_sent") == 1


def test_the_summary_says_what_the_default_is_for_each_kind_of_attendance(client, env):
    grant_meet_scope()
    other = ny(2031, 6, 12, 10)
    absent = confirmed(client, env, START, email="absent@example.com", ip="203.0.113.1")
    confirmed(client, env, other, email="nohost@example.com", ip="203.0.113.2", name="Nora Nohost")
    _meet(env, absent, HOST, end=START + timedelta(minutes=20))
    env.clock.set(END)
    tick(client)
    (mail,) = _mails(env, OWNER, "Call ended")
    assert "You joined; nobody else did" in mail["html"]
    assert "The no-show fee of 20% ($22.20) is charged and the rest of the hold is released." in mail["html"]

    env.clock.set(other + timedelta(hours=1))
    tick(client)
    (mail,) = _mails(env, OWNER, "Call ended: confirm the outcome: Nora Nohost")
    assert "Google Meet has no record of you joining" in mail["html"]
    assert "Nothing is charged and any hold is released" in mail["html"]


def test_the_copy_of_the_summary_in_the_email_log_has_no_working_link(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    token = _links(env)["charge"].split("token=")[1]
    db = SessionLocal()
    kept = db.query(EmailLog).filter(EmailLog.template == "consult_owner_summary").one()
    assert kept.recipient == OWNER and kept.audience == "admin"
    assert token not in kept.body_html and token not in kept.body_text
    assert "decision?token=" in kept.body_html and b["ref"] in kept.body_html
    db.close()


# -----------------------------------------------------------------------------
# The owner's links
# -----------------------------------------------------------------------------

def test_opening_a_link_shows_a_page_and_changes_nothing(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    links = _links(env)
    before = state_of_everything(env)
    for outcome, words in (("charge", "$111 will be charged to Visa ending 4242"),
                           ("no_show", "The no-show fee of 20% ($22.20) will be charged"),
                           ("waive", "Nothing will be charged")):
        for _ in range(3):                                          # a mail scanner opens each link, more than once
            r = client.get(links[outcome])
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
            assert words in r.text and "Nothing has been done yet" in r.text
            assert '<form method="post"' in r.text and "<button" in r.text
            assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
            assert "form-action 'self'" in r.headers["content-security-policy"]
    assert state_of_everything(env) == before
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.owner_choice) == ("confirmed", "", "")
    assert env.stripe.money_taken() == 0 and env.stripe.count("PaymentIntent.capture") == 0


def test_the_button_decides_once_and_then_every_link_is_spent(client, env):
    """He says no-show before the automatic 'charge in full' would run."""
    b = _held(client, env)                                          # attendance unknown: the default is the full amount
    env.clock.set(END)
    tick(client)
    links = _links(env)
    env.outbox.clear()
    env.clock.set(END + timedelta(minutes=30))

    r = client.post(links["no_show"])
    assert r.status_code == 200 and "Done: no-show fee" in r.text
    assert "$22.20 was charged to Visa ending 4242" in r.text
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.owner_choice, row.charged_cents) == ("no_show", "no_show", "no_show", 2_220)
    assert row.settled_by == "admin@example.com (email link)" and row.owner_choice_at is not None
    assert env.stripe.last("PaymentIntent.capture")["amount_to_capture"] == 2_220
    assert env.stripe.money_taken() == 2_220 and env.stripe.authorized() == 0   # the rest of the hold is released
    assert "owner_chose" in events_of(b["id"])
    assert _mails(env, OWNER, "No-show fee: $22.20 went through")
    assert "You chose this from the summary email." in to(env.outbox, OWNER)[0]["html"]
    assert subjects(env.outbox, CLIENT) == [f"No-show fee for your consulting call ({b['ref']})"]

    # The same link again, and the other two: spent. Nothing more happens.
    after = state_of_everything(env)
    for outcome in ("no_show", "charge", "waive"):
        for method in (client.post, client.get):
            r = method(links[outcome])
            assert r.status_code == 409 and "Already decided" in r.text
            assert "recorded as a no-show" in r.text and "$22.20 has been charged" in r.text
            assert "<form" not in r.text
    assert state_of_everything(env) == after

    # The automatic outcome's time comes and goes: he chose, so it does not run.
    env.clock.set(DUE + timedelta(minutes=5))
    assert tick(client)["done"] == {}
    assert state_of_everything(env) == after and env.stripe.money_taken() == 2_220


def test_he_can_say_do_not_charge(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    links = _links(env)
    env.outbox.clear()
    r = client.post(links["waive"])
    assert r.status_code == 200 and "Nothing was charged. Any hold on the card was released." in r.text
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.hold_state, row.charged_cents) == ("completed", "waived", "released", 0)
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0
    assert to(env.outbox, CLIENT) == []
    env.clock.set(DUE)
    tick(client)
    assert env.stripe.money_taken() == 0 and booking_row(b["ref"]).settlement == "waived"


def test_he_can_say_charge_in_full_when_the_default_was_not(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, GUEST, end=START + timedelta(minutes=58))        # he joined from another account
    env.clock.set(END)
    tick(client)
    assert booking_row(b["ref"]).attendance_state == "host_absent"
    r = client.post(_links(env)["charge"])
    assert r.status_code == 200 and "$111 was charged" in r.text
    assert env.stripe.money_taken() == 11_100 and booking_row(b["ref"]).status == "completed"


def test_a_link_expires_when_the_automatic_outcome_is_due(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    links = _links(env)
    env.clock.set(DUE - timedelta(seconds=1))
    assert client.get(links["waive"]).status_code == 200            # still good one second before
    env.clock.set(DUE)
    before = state_of_everything(env)
    for method in (client.get, client.post):
        r = method(links["waive"])
        assert r.status_code == 410 and "This link has expired" in r.text
        assert "Wednesday, June 11, 2031 at 1:00 PM EDT" in r.text and "<form" not in r.text
    assert state_of_everything(env) == before                       # the POST did nothing
    assert booking_row(b["ref"]).owner_choice == ""
    tick(client)                                                    # so the default runs
    row = booking_row(b["ref"])
    assert (row.settlement, row.settled_by, row.charged_cents) == ("charged", "auto", 11_100)


def test_a_link_that_was_changed_or_made_up_does_nothing(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    good = _links(env)["waive"]
    before = state_of_everything(env)
    token = good.split("token=")[1]
    forged = [
        f"{DECISION}?token={token[:-2]}xx",                         # signature changed
        f"{DECISION}?token=" + token.replace(token.split(".")[0], consult_auto._signer().dumps([b["id"], b["ref"], "charge", 4102444800]).split(".")[0]),
        f"{DECISION}?token=not-a-token",
        f"{DECISION}",
        f"{DECISION}?token=" + consult_auto._signer().dumps([999_999, "C-NOSUCHXX", "waive", 4102444800]),
        f"{DECISION}?token=" + consult_auto._signer().dumps([b["id"], b["ref"], "refund_everything", 4102444800]),
    ]
    for url in forged:
        for method in (client.get, client.post):
            r = method(url)
            assert r.status_code == 400 and "not valid" in r.text and "<form" not in r.text, url
    # a token signed with another secret
    from itsdangerous import URLSafeSerializer

    other = URLSafeSerializer("someone-elses-secret", salt="consult-owner-decision").dumps([b["id"], b["ref"], "waive", 4102444800])
    assert client.post(f"{DECISION}?token={other}").status_code == 400
    assert state_of_everything(env) == before and booking_row(b["ref"]).settlement == ""


def test_the_page_shows_a_clients_name_as_text(client, env):
    b = confirmed(client, env, START, name='<script>alert(1)</script> "Mallory"')
    env.clock.set(END)
    tick(client)
    r = client.get(_links(env)["charge"])
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    mail = _mails(env, OWNER, "Call ended")[0]["html"]
    assert "<script>alert(1)</script>" not in mail and "&lt;script&gt;" in mail
    assert booking_row(b["ref"]).settlement == ""


def test_once_he_used_the_admin_panel_the_links_are_dead(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    links = _links(env)
    assert _admin(client, b, "charge", {"minutes": 30}).json()["charged_cents"] == 5_550
    before = state_of_everything(env)
    r = client.post(links["charge"])
    assert r.status_code == 409 and "charged in full, by admin@example.com" in r.text
    assert "$55.50 has been charged" in r.text
    assert state_of_everything(env) == before
    env.clock.set(DUE)
    assert tick(client)["done"] == {}
    assert env.stripe.money_taken() == 5_550                        # his 30 minutes stand; no automatic top-up


def test_two_clicks_at_the_same_instant_decide_once(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    links = _links(env)
    env.outbox.clear()
    go = threading.Barrier(4)
    pages: list = []

    def press(outcome: str) -> None:
        db = SessionLocal()
        try:
            go.wait(timeout=10)
            pages.append(consult_auto.decide(db, links[outcome].split("token=")[1]).state)
        except Exception as exc:  # noqa: BLE001
            pages.append(repr(exc))
        finally:
            db.close()

    threads = [threading.Thread(target=press, args=(o,)) for o in ("charge", "charge", "no_show", "waive")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(pages) == ["decided", "decided", "decided", "done"], pages
    row = booking_row(b["ref"])
    assert row.owner_choice in ("charge", "no_show", "waive") and events_of(b["id"]).count("owner_chose") == 1
    assert events_of(b["id"]).count("outcome_decided") == 1
    expected = {"charge": 11_100, "no_show": 2_220, "waive": 0}[row.owner_choice]
    assert env.stripe.money_taken() == expected == row.charged_cents and env.stripe.authorized() == 0
    assert len(_mails(env, OWNER, "")) == 1


def test_a_choice_that_cannot_be_carried_out_yet_is_kept_and_applied_by_the_tick(client, env):
    """A call booked for the same afternoon: the hold is placed as the card
    is saved, Stripe authorizes it, and the answer is lost. The tick does
    not run before the meeting is over. While that payment is unconfirmed no
    outcome can be decided; his choice is recorded, and applied by the next
    tick once Stripe has been asked what became of the hold."""
    today = ny(2031, 6, 2, 15)                                     # same day: $444, fee $88.80
    env.stripe.card = "network_after"
    b = confirmed(client, env, today)
    env.stripe.card = "ok"
    assert charges_of(b["id"])[0].status == "pending" and booking_row(b["ref"]).hold_state == ""
    assert env.stripe.authorized() == 44_400                       # it IS on the card
    db = SessionLocal()
    env.clock.set(today + timedelta(hours=1))
    assert consult_auto.send_summary(db, b["id"]) is True          # the summary alone: no tick yet
    db.close()
    links = _links(env)
    r = client.post(links["no_show"])
    assert r.status_code == 200 and "Your choice is recorded" in r.text
    assert "still being confirmed" in r.text and "tried again within a few minutes" in r.text
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.owner_choice) == ("confirmed", "", "no_show")
    assert env.stripe.money_taken() == 0
    assert client.get(links["charge"]).status_code == 409          # the links are spent all the same
    assert "You already chose: no-show fee." in client.get(links["charge"]).text

    env.clock.advance(minutes=5)
    out = tick(client)                                             # asks Stripe about the hold, then applies his choice
    assert out["ok"] is True and out["done"]["settled:no_show"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.settled_by, row.charged_cents) == (
        "no_show", "no_show", "admin@example.com (email link)", 8_880)
    assert len(env.stripe.payment_intents) == 1                    # the one hold, found again by its key
    assert env.stripe.last("PaymentIntent.capture")["amount_to_capture"] == 8_880
    assert env.stripe.money_taken() == 8_880 and env.stripe.authorized() == 0
    env.clock.set(today + timedelta(hours=3, minutes=1))
    assert tick(client)["done"] == {}
    assert env.stripe.money_taken() == 8_880


# -----------------------------------------------------------------------------
# The automatic outcome
# -----------------------------------------------------------------------------

def test_both_joined_captures_the_booked_amount_and_sends_the_receipt(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE - timedelta(minutes=1))
    assert tick(client)["done"] == {}                               # his two hours are not over
    assert env.stripe.money_taken() == 0

    env.clock.set(DUE)
    assert tick(client)["done"]["settled:charge"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.settled_by, row.billed_minutes) == ("completed", "charged", "auto", 60)
    assert (row.charged_cents, row.charge_state, row.hold_state) == (11_100, "paid", "captured")
    assert env.stripe.count("PaymentIntent.create") == 1            # the hold; no second payment
    assert env.stripe.last("PaymentIntent.capture")["amount_to_capture"] == 11_100
    assert env.stripe.money_taken() == 11_100 and env.stripe.authorized() == 0

    (receipt,) = to(env.outbox, CLIENT)
    assert receipt["subject"] == f"Receipt for your consulting call ({b['ref']})"
    for needle in ("$111", "Visa ending 4242", "60 minutes", "Wednesday, June 11, 2031 at 3:00 PM BST",
                   "taken from the temporary hold", "To contest this charge", "reply to this email",
                   "support team handles every request", b["ref"]):
        assert needle in receipt["html"], needle
    (result,) = to(env.outbox, OWNER)
    assert result["subject"] == "[Consulting] Automatic charge for the call: $111 went through: Casey Client"
    assert "both joined" in result["html"]
    kinds = events_of(b["id"])
    assert kinds.count("outcome_decided") == 1 and kinds.count("charge_succeeded") == 1

    # again, and again later: nothing more
    before = state_of_everything(env)
    tick(client)
    env.clock.advance(hours=6)
    tick(client)
    assert state_of_everything(env) == before


def test_client_absent_captures_twenty_percent_and_releases_the_rest(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, HOST, end=START + timedelta(minutes=20))
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE)
    assert tick(client)["done"]["settled:no_show"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.amount_due_cents, row.charged_cents) == ("no_show", "no_show", 2_220, 2_220)
    capture = env.stripe.last("PaymentIntent.capture")
    assert capture["amount_to_capture"] == 2_220                    # 20% of the $111 that was held
    assert env.stripe.money_taken() == 2_220 and env.stripe.authorized() == 0
    assert env.stripe.count("PaymentIntent.create") == 1

    (notice,) = to(env.outbox, CLIENT)
    assert notice["subject"] == f"No-show fee for your consulting call ({b['ref']})"
    assert "nobody joined your consulting call from your side" in notice["html"]
    assert "no-show fee of 20% of the booked amount" in notice["html"] and "$22.20" in notice["html"]
    assert "To contest this charge" in notice["html"] and "reply to this email" in notice["html"]
    assert "$111" not in notice["html"]                             # only what was taken
    (result,) = to(env.outbox, OWNER)
    assert result["subject"] == "[Consulting] Automatic no-show fee: $22.20 went through: Casey Client"


def test_host_absent_charges_nothing_releases_the_hold_and_tells_the_owner(client, env):
    grant_meet_scope()
    b = _held(client, env)
    _meet(env, b, GUEST, end=START + timedelta(minutes=10))
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE)
    assert tick(client)["done"]["settled:waive"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.charged_cents, row.hold_state) == ("completed", "waived", 0, "released")
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 0
    assert env.stripe.count("PaymentIntent.capture") == 0 and env.stripe.count("PaymentIntent.cancel") == 1
    assert to(env.outbox, CLIENT) == []                             # the client is not charged and not bothered
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == (
        "[Consulting] Not charged: Meet has no record of you joining: nothing to charge: Casey Client")
    assert "If that is not right, open the booking and press Charge." in alert["html"]
    # and he still can: nothing was taken, so the outcome may be changed in the admin panel
    assert _a(client, b)["actions"]["can_charge"] is True
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100


def test_unknown_attendance_charges_in_full(client, env):
    b = _held(client, env)                                          # no Meet permission
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE)
    assert tick(client)["done"]["settled:charge"] == 1
    assert env.stripe.money_taken() == 11_100 and booking_row(b["ref"]).settled_by == "auto"
    (result,) = to(env.outbox, OWNER)
    assert result["subject"] == (
        "[Consulting] Automatic charge for the call (attendance unknown): $111 went through: Casey Client")
    assert "Attendance could not be read" in result["html"] and "Meet permission" in result["html"]
    assert subjects(env.outbox, CLIENT) == [f"Receipt for your consulting call ({b['ref']})"]


@pytest.mark.parametrize(
    "when, minutes, total, fee",
    [
        (ny(2031, 6, 11, 10), 30, 5_550, 1_110),                    # standard, 30 minutes
        (ny(2031, 6, 11, 10), 120, 22_200, 4_440),                  # standard, two hours
        (ny(2031, 6, 5, 10), 90, 33_300, 6_660),                    # priority (3 days ahead), 90 minutes
        (ny(2031, 6, 3, 10), 60, 33_300, 6_660),                    # next day
    ],
)
def test_a_no_show_captures_exactly_the_fee_whatever_was_held(client, env, when, minutes, total, fee):
    grant_meet_scope()
    b = confirmed(client, env, when, minutes)
    env.clock.set(max(when - timedelta(hours=24), consult.utcnow()))
    tick(client)
    row = booking_row(b["ref"])
    assert (row.total_cents, row.fee_cents, row.hold_cents, row.hold_state) == (total, fee, total, "authorized")
    env.google.conference(row.meet_url, when, when + timedelta(minutes=10),
                          ("host", "Bassam Abdelnabi", when, when + timedelta(minutes=10)))
    env.clock.set(when + timedelta(minutes=minutes))
    tick(client)                                                    # the scheduled end: attendance, summary
    assert env.stripe.money_taken() == 0
    env.clock.advance(hours=2)
    tick(client)                                                    # two hours on: the default outcome
    assert env.stripe.last("PaymentIntent.capture")["amount_to_capture"] == fee
    assert env.stripe.money_taken() == fee and env.stripe.authorized() == 0
    (hold,) = charges_of(b["id"])
    assert (hold.amount_cents, hold.captured_cents, hold.status) == (total, fee, "captured")
    assert total - fee == hold.amount_cents - hold.captured_cents   # what went back to the client's card
    assert fee * 5 == total                                          # 20%, to the cent


def test_with_no_hold_the_saved_card_is_charged_directly(client, env):
    """The tick did not run before the meeting, so no hold was placed."""
    grant_meet_scope()
    b = confirmed(client, env, START)
    _meet(env, b, HOST, GUEST, end=START + timedelta(minutes=58))
    env.clock.set(DUE + timedelta(minutes=1))                       # first tick ever, after everything
    out = tick(client)
    assert out["ok"] is True
    row = booking_row(b["ref"])
    assert row.hold_state == "" and row.status == "confirmed"       # late: he gets his two hours from now
    assert row.settle_due_at.replace(tzinfo=DUE.tzinfo) == DUE + timedelta(minutes=1, hours=2)
    assert "Wednesday, June 11, 2031 at 3:01 PM EDT" in _mails(env, OWNER, "Call ended")[0]["html"]
    assert "None: the card is charged directly" in _mails(env, OWNER, "Call ended")[0]["html"]
    env.clock.set(DUE + timedelta(minutes=1, hours=2))
    assert tick(client)["done"]["settled:charge"] == 1
    call = env.stripe.last("PaymentIntent.create")
    assert call["amount"] == 11_100 and call["capture_method"] == "automatic" and call["off_session"] is True
    assert call["idempotency_key"] == f"consult:{b['ref']}:charge:meeting:1"
    assert env.stripe.count("PaymentIntent.capture") == 0
    assert env.stripe.money_taken() == 11_100 == booking_row(b["ref"]).charged_cents
    receipt = _mails(env, CLIENT, "Receipt")[0]["html"]
    assert "$111" in receipt and "temporary hold" not in receipt


def test_a_no_show_with_no_hold_charges_only_the_fee(client, env):
    grant_meet_scope()
    b = confirmed(client, env, START)
    _meet(env, b, HOST, end=START + timedelta(minutes=20))
    env.clock.set(END + timedelta(minutes=5))                       # the summary goes out five minutes late
    tick(client)
    env.clock.set(DUE)
    assert tick(client)["done"] == {}                               # his two hours count from when it was sent
    assert env.stripe.count("PaymentIntent.create") == 0
    env.clock.set(DUE + timedelta(minutes=5))
    tick(client)
    call = env.stripe.last("PaymentIntent.create")
    assert call["amount"] == 2_220 and call["capture_method"] == "automatic"
    assert call["metadata"]["reason"] == "no_show_fee"
    assert env.stripe.money_taken() == 2_220 and booking_row(b["ref"]).status == "no_show"


def test_the_automatic_outcome_at_the_same_instant_four_times_charges_once(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE)
    go = threading.Barrier(4)
    results: list = []

    def run() -> None:
        db = SessionLocal()
        try:
            go.wait(timeout=10)
            results.append(consult_auto.settle_due(db, b["id"]))
        except Exception as exc:  # noqa: BLE001
            results.append(repr(exc))
        finally:
            db.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) in (["charge"] * 4, ["charge", "closed", "closed", "closed"],
                               ["charge", "charge", "closed", "closed"], ["charge", "charge", "charge", "closed"]), results
    assert env.stripe.money_taken() == 11_100 and env.stripe.count("PaymentIntent.capture") == 1
    assert events_of(b["id"]).count("outcome_decided") == 1 and events_of(b["id"]).count("charge_succeeded") == 1
    assert len(to(env.outbox, CLIENT)) == 1 and len(to(env.outbox, OWNER)) == 1     # one receipt, one result


def test_a_declined_automatic_charge_is_reported_and_collected_on_a_new_card(client, env):
    b = confirmed(client, env, START)                               # no hold was placed
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE)
    env.stripe.card = "declined"
    out = tick(client)
    assert out["ok"] is True and out["done"]["settled:charge"] == 1
    row = booking_row(b["ref"])
    assert (row.status, row.settlement, row.charge_state, row.charged_cents) == ("completed", "charged", "failed", 0)
    assert to(env.outbox, CLIENT) == []                             # no receipt for money that was not taken
    assert "FAILED" in to(env.outbox, OWNER)[0]["subject"]
    for _ in range(3):                                              # the tick does not keep trying a declined card
        env.clock.advance(minutes=5)
        tick(client)
    assert env.stripe.count("PaymentIntent.create") == 1 and env.stripe.money_taken() == 0

    env.stripe.card = "ok"
    env.outbox.clear()
    client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    save_card(client, env, b["ref"], brand="amex", last4="0005")
    row = booking_row(b["ref"])
    assert (row.charge_state, row.charged_cents) == ("paid", 11_100) and env.stripe.money_taken() == 11_100
    (receipt,) = to(env.outbox, CLIENT)
    assert receipt["subject"].startswith("Receipt for your consulting call") and "Amex ending 0005" in receipt["html"]


def test_a_charge_stripe_did_not_answer_about_is_finished_by_a_later_tick(client, env):
    b = confirmed(client, env, START)
    env.clock.set(END)
    tick(client)
    env.outbox.clear()
    env.clock.set(DUE)
    env.stripe.card = "network_after"                               # the money is taken; the answer is lost
    out = tick(client)
    assert out["ok"] is True
    row = booking_row(b["ref"])
    assert (row.settlement, row.charge_state, row.charged_cents) == ("charged", "pending", 0)
    assert env.stripe.money_taken() == 11_100 and to(env.outbox, CLIENT) == []

    env.stripe.card = "ok"
    env.clock.advance(minutes=1)
    assert "collection:collected" not in tick(client)["done"]       # a moment's grace for a request still running
    env.clock.advance(minutes=4)
    assert tick(client)["done"]["collection:collected"] == 1
    row = booking_row(b["ref"])
    assert (row.charge_state, row.charged_cents) == ("paid", 11_100)
    keys = [kw["idempotency_key"] for name, kw in env.stripe.calls if name == "PaymentIntent.create"]
    assert keys == [f"consult:{b['ref']}:charge:meeting:1"] * 2 and len(env.stripe.payment_intents) == 1
    assert env.stripe.money_taken() == 11_100                       # once
    assert len(_mails(env, CLIENT, "Receipt")) == 1 and len(_mails(env, OWNER, "went through")) == 1
    env.clock.advance(minutes=5)
    assert tick(client)["done"] == {}


def test_a_hold_whose_answer_was_lost_for_good_does_not_block_the_outcome(client, env):
    """The hold's answer never came and nobody could ask again for a day:
    it is parked for a person ('needs review'). It took no money and can no
    longer be captured, so the call is still settled, by a direct charge."""
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=24))
    env.stripe.card = "network_before"                              # Stripe never heard of it
    tick(client)
    env.stripe.card = "ok"
    (hold,) = charges_of(b["id"])
    assert hold.status == "pending"
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=3))                       # 21 hours later the tick is back
    tick(client)
    assert charges_of(b["id"])[0].status == "needs_review" and booking_row(b["ref"]).hold_state == ""
    assert booking_row(b["ref"]).status == "confirmed"              # not cancelled: the card was never refused
    (alert,) = _mails(env, OWNER, "needs checking")                 # nobody pressed a button: he is told
    assert alert["subject"] == "[Consulting] A hold needs checking in Stripe: Casey Client"
    assert "cancel it there" in alert["html"] and "https://dashboard.stripe.com/payments" in alert["html"]
    env.clock.advance(minutes=5)
    tick(client)
    assert len(_mails(env, OWNER, "needs checking")) == 1           # once
    env.clock.set(END)
    tick(client)
    env.clock.set(DUE)
    out = tick(client)
    assert out["ok"] is True and out["done"]["settled:charge"] == 1
    # once the call is settled the parked hold is looked up at Stripe by the tick itself: there is none
    assert [(c.kind, c.status) for c in charges_of(b["id"])] == [("hold", "failed"), ("charge", "succeeded")]
    assert charges_of(b["id"])[0].error_code == "never_placed"
    assert env.stripe.money_taken() == 11_100 == booking_row(b["ref"]).charged_cents


def test_a_charge_nobody_could_ask_about_for_a_day_is_handed_to_the_owner(client, env):
    """The automatic charge got no answer and the tick then stopped for 21
    hours. Asking again that late could charge twice, so it is not asked:
    the booking shows the payment as failed and he is told to look in Stripe."""
    b = confirmed(client, env, START)
    env.clock.set(END)
    tick(client)
    env.clock.set(DUE)
    env.stripe.card = "network_before"
    tick(client)
    assert booking_row(b["ref"]).charge_state == "pending"
    env.stripe.card = "ok"
    env.outbox.clear()
    env.clock.advance(hours=21)
    out = tick(client)
    assert out["ok"] is True
    row = booking_row(b["ref"])
    assert (row.settlement, row.charge_state, row.charged_cents) == ("charged", "review", 0)
    assert charges_of(b["id"])[-1].status == "needs_review" and env.stripe.count("PaymentIntent.create") == 1
    (alert,) = to(env.outbox, OWNER)
    assert alert["subject"] == "[Consulting] A charge needs checking in Stripe: Casey Client"
    # what to do about it: the two buttons on the booking, and what each means
    assert "&quot;Paid in Stripe&quot;, with the amount" in alert["html"]
    assert "the client has paid and nothing more is owed" in alert["html"]
    assert "&quot;Not charged&quot; if it is not: the Charge button then works again" in alert["html"]
    assert "the site asks Stripe to confirm before it changes anything" in alert["html"]
    assert to(env.outbox, "client@example.com") == []
    for _ in range(3):
        env.clock.advance(minutes=5)
        assert tick(client)["done"] == {}
    assert len(to(env.outbox, OWNER)) == 1 and env.stripe.money_taken() == 0


def test_a_hold_release_stripe_did_not_confirm_is_asked_again(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    env.stripe.cancel_fails = True
    assert client.post(_links(env)["waive"]).status_code == 200
    assert booking_row(b["ref"]).hold_state == "authorized" and env.stripe.authorized() == 11_100
    assert events_of(b["id"]).count("hold_release_failed") == 1
    env.clock.advance(minutes=5)
    tick(client)
    assert events_of(b["id"]).count("hold_release_failed") == 2
    env.stripe.cancel_fails = False
    env.clock.advance(minutes=5)
    assert tick(client)["done"]["release:released"] == 1
    assert booking_row(b["ref"]).hold_state == "released" and env.stripe.authorized() == 0
    assert env.stripe.money_taken() == 0


def test_a_release_that_keeps_failing_is_left_to_lapse_after_six_tries(client, env):
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    env.stripe.cancel_fails = True
    client.post(_links(env)["waive"])
    for _ in range(12):
        env.clock.advance(minutes=5)
        tick(client)
    assert events_of(b["id"]).count("hold_release_failed") == consult_auto.RELEASE_RETRY_LIMIT == 6


def test_a_late_summary_gives_him_his_whole_two_hours(client, env):
    """The tick was down from before the end until three hours after it."""
    b = _held(client, env)
    env.outbox.clear()
    late = END + timedelta(hours=3)
    env.clock.set(late)
    out = tick(client)
    assert out["done"]["summary"] == 1 and "settled:charge" not in out["done"]
    assert env.stripe.money_taken() == 0                            # not charged behind his back
    row = booking_row(b["ref"])
    assert row.settle_due_at.replace(tzinfo=late.tzinfo) == late + timedelta(hours=2)
    assert "Wednesday, June 11, 2031 at 4:00 PM EDT" in to(env.outbox, OWNER)[0]["html"]
    links = _links(env)
    env.clock.set(late + timedelta(hours=1, minutes=59))
    assert client.get(links["charge"]).status_code == 200
    tick(client)
    assert env.stripe.money_taken() == 0
    env.clock.set(late + timedelta(hours=2))
    assert client.get(links["charge"]).status_code == 410
    assert tick(client)["done"]["settled:charge"] == 1 and env.stripe.money_taken() == 11_100


def test_with_no_time_to_choose_there_is_no_summary_and_the_outcome_runs_at_the_end(client, env):
    assert client.put(f"{ADMIN_API}/settings", headers=ADMIN, json={"auto_settle_hours": 0}).status_code == 200
    b = _held(client, env)
    env.outbox.clear()
    env.clock.set(END)
    out = tick(client)
    assert "summary" not in out["done"] and out["done"]["settled:charge"] == 1
    assert _mails(env, OWNER, "Call ended") == [] and len(_mails(env, OWNER, "went through")) == 1
    assert booking_row(b["ref"]).charged_cents == 11_100


@pytest.mark.parametrize("missing", ["ADMIN_NOTIFY_EMAIL", "RESEND_API_KEY"])
def test_if_the_summary_cannot_be_sent_nothing_is_charged_by_itself(client, env, monkeypatch, missing):
    """He was never asked, so nothing is decided for him (review finding 8).
    The admin status says so, and his own buttons still work."""
    b = _held(client, env)
    monkeypatch.setattr(get_settings(), missing, "")
    env.clock.set(END)
    tick(client)
    for at in (DUE, DUE + timedelta(hours=6), DUE + timedelta(days=2)):
        env.clock.set(at)
        assert "settled:charge" not in tick(client)["done"]
    row = booking_row(b["ref"])
    assert row.summary_sent_at is None and row.settlement == "" and row.status == "confirmed"
    assert env.stripe.money_taken() == 0 and env.stripe.authorized() == 11_100
    status = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert status["summaries_unsent"] == 1 and status["summaries_unsent_since"] == iso(END)
    assert missing in status["summaries_unsent_note"]
    assert "Nothing is charged automatically for these calls" in status["summaries_unsent_note"]
    # he decides from the admin
    assert _admin(client, b, "charge").json()["charged_cents"] == 11_100
    status = client.get(f"{ADMIN_API}/status", headers=ADMIN).json()
    assert (status["summaries_unsent"], status["summaries_unsent_since"], status["summaries_unsent_note"]) == (0, None, "")


# -----------------------------------------------------------------------------
# The guards under the automatic steps, each on its own
# -----------------------------------------------------------------------------

def _set(booking_id: int, **values) -> None:
    db = SessionLocal()
    row = db.get(ConsultBooking, booking_id)
    for key, value in values.items():
        setattr(row, key, value)
    db.commit()
    db.close()


def _settle(booking_id: int, outcome: str, **kw):
    db = SessionLocal()
    try:
        return consult.settle(db, db.get(ConsultBooking, booking_id), outcome, **kw)
    finally:
        db.close()


def test_the_default_outcome_never_overrides_a_choice_he_has_just_made(client, env):
    """His click is recorded a moment before the tick looks. The default
    ('charge in full') must not run on top of it: his choice is what the
    tick applies."""
    b = _held(client, env)
    env.clock.set(DUE)                                              # the default is due this very minute
    _set(b["id"], owner_choice="no_show", owner_choice_at=DUE)      # ...and he has just chosen
    with pytest.raises(consult.AlreadyDecided):
        _settle(b["id"], "charge", actor="auto", only_undecided=True, expect_choice="")
    assert env.stripe.money_taken() == 0 and booking_row(b["ref"]).settlement == ""
    db = SessionLocal()
    assert consult_auto.settle_due(db, b["id"]) == "no_show"
    db.close()
    row = booking_row(b["ref"])
    assert (row.settlement, row.charged_cents) == ("no_show", 2_220) and env.stripe.money_taken() == 2_220


def test_an_automatic_step_never_changes_what_a_person_decided(client, env):
    """He pressed 'Do not charge' in the admin panel. Nothing was taken, so
    HE may still change his mind there; the tick and the email links may not."""
    b = _held(client, env)
    env.clock.set(END + timedelta(minutes=10))
    assert _admin(client, b, "waive").status_code == 200
    for kw in (dict(actor="auto", expect_choice=""), dict(actor="owner (email link)")):
        with pytest.raises(consult.AlreadyDecided):
            _settle(b["id"], "charge", only_undecided=True, **kw)
    env.clock.set(DUE)
    db = SessionLocal()
    assert consult_auto.settle_due(db, b["id"]) == "closed"
    db.close()
    row = booking_row(b["ref"])
    assert (row.settlement, row.charged_cents) == ("waived", 0) and env.stripe.money_taken() == 0


def test_a_second_choice_cannot_replace_the_first_even_from_a_page_opened_before(client, env, monkeypatch):
    """Two confirm pages were open. The first button was pressed and its
    choice recorded; the second page still believes nothing is decided."""
    b = _held(client, env)
    env.clock.set(END)
    tick(client)
    links = _links(env)
    db = SessionLocal()
    stale = consult_auto.look_at_decision(db, links["charge"].split("token=")[1])
    db.close()
    assert stale.state == "ready"
    _set(b["id"], owner_choice="waive", owner_choice_at=END)        # the first press, not yet carried out
    real_look = consult_auto.look_at_decision
    looks: list[int] = []

    def stale_once(db, token, now=None):
        # What the second page saw: once for the route (which looks at the
        # token before it counts the request) and once for decide itself.
        looks.append(1)
        return stale if len(looks) <= 2 else real_look(db, token, now)

    monkeypatch.setattr(consult_auto, "look_at_decision", stale_once)
    r = client.post(links["charge"])
    assert len(looks) == 3                                          # route, decide, and the look after the claim failed
    assert r.status_code == 409 and "You already chose: do not charge." in r.text
    row = booking_row(b["ref"])
    assert row.owner_choice == "waive" and row.settlement == "" and env.stripe.money_taken() == 0
    assert "owner_chose" not in events_of(b["id"])                  # the second press recorded nothing


def test_the_default_outcome_does_not_run_early_even_if_asked(client, env):
    b = _held(client, env)
    db = SessionLocal()
    for at in (START + timedelta(minutes=30), END, DUE - timedelta(seconds=1)):
        env.clock.set(at)
        if at == END:
            assert consult_auto.send_summary(db, b["id"]) is True    # he is asked at the scheduled end
        assert consult_auto.settle_due(db, b["id"]) == "waiting"
    assert env.stripe.money_taken() == 0 and booking_row(b["ref"]).settlement == ""
    env.clock.set(DUE)
    assert consult_auto.settle_due(db, b["id"]) == "charge"
    db.close()
    assert env.stripe.money_taken() == 11_100


def test_a_marker_is_claimed_by_one_caller_only(client, env):
    b = confirmed(client, env, START)
    db = SessionLocal()
    assert consult_auto._claim(db, b["id"], "reminder_1h_sent_at", START) is True
    assert consult_auto._claim(db, b["id"], "reminder_1h_sent_at", START) is False
    assert consult_auto._unclaim(db, b["id"], "reminder_1h_sent_at") is True
    assert consult_auto._claim(db, b["id"], "reminder_1h_sent_at", START) is True
    db.close()


def test_without_a_server_secret_no_link_is_issued_or_accepted(client, env, monkeypatch):
    """A link decides what a client pays, with no sign-in. It is signed with
    the server's secret or it does not exist."""
    b = _held(client, env)
    db = SessionLocal()
    good = consult_auto.decision_token(db.get(ConsultBooking, b["id"]), "waive", DUE)
    s = get_settings()
    monkeypatch.setattr(s, "SESSION_SECRET", "")
    monkeypatch.setattr(s, "ADMIN_TOKEN", "")
    env.clock.set(END)
    assert consult_auto.links_available() is False
    assert consult_auto.send_summary(db, b["id"]) is True
    (mail,) = _mails(env, OWNER, "Call ended")
    assert "decision?token=" not in mail["html"] and "If you do nothing" in mail["html"]
    assert f"/admin#consult/booking/{b['id']}" in mail["html"]      # the admin panel is the way to decide
    forged = consult_auto.decision_token(db.get(ConsultBooking, b["id"]), "waive", DUE)   # signed with the fallback
    for token in (good, forged):
        assert consult_auto.look_at_decision(db, token).state == "invalid"
        assert consult_auto.decide(db, token).state == "invalid"
    db.close()
    assert booking_row(b["ref"]).owner_choice == "" and booking_row(b["ref"]).settlement == ""


def test_without_an_email_service_a_send_is_not_tried_again_on_every_tick(client, env, monkeypatch):
    b = confirmed(client, env, START)
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "")
    for at in (START - timedelta(hours=48), START - timedelta(hours=24)):
        env.clock.set(at)
        for _ in range(4):
            tick(client)
            env.clock.advance(minutes=5)
    db = SessionLocal()
    for template in ("consult_reminder_first", "consult_hold_placed"):
        tried = db.query(EmailLog).filter(EmailLog.template == template).all()
        assert len(tried) == 1 and tried[0].ok is False, template   # logged once as not sent, not once per tick
    db.close()
    assert booking_row(b["ref"]).hold_state == "authorized"         # the money steps do not depend on email


# -----------------------------------------------------------------------------
# Receipts from the admin's own buttons
# -----------------------------------------------------------------------------

def test_a_charge_for_fewer_minutes_says_so_on_the_receipt(client, env):
    b = _held(client, env)
    env.clock.set(START + timedelta(minutes=40))
    env.outbox.clear()
    assert _admin(client, b, "charge", {"minutes": 30}).json()["charged_cents"] == 5_550
    (receipt,) = to(env.outbox, CLIENT)
    assert "30 of the 60 minutes booked" in receipt["html"] and "$55.50" in receipt["html"]
    assert env.stripe.money_taken() == 5_550 and env.stripe.authorized() == 0
    # a refund is his to explain: no automatic email to the client
    env.clock.advance(minutes=5)
    env.outbox.clear()
    _admin(client, b, "refund", {"cents": 1_000})
    assert to(env.outbox, CLIENT) == [] and len(to(env.outbox, OWNER)) == 1


def test_pressing_charge_twice_sends_one_receipt(client, env):
    b = _held(client, env)
    env.clock.set(START + timedelta(minutes=61))
    env.outbox.clear()
    _admin(client, b, "charge")
    _admin(client, b, "charge")
    assert len(to(env.outbox, CLIENT)) == 1 and env.stripe.money_taken() == 11_100


def test_a_late_cancellation_fee_names_how_to_contest_it(client, env):
    b = _held(client, env)
    env.outbox.clear()
    env.clock.set(START - timedelta(hours=3))
    client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    (mail,) = to(env.outbox, CLIENT)                                # the cancellation email is the fee notice
    assert "20% fee of $22.20 was charged" in mail["html"] and "To contest this charge, reply to this email" in mail["html"]
    assert env.stripe.money_taken() == 2_220


def test_a_late_fee_collected_later_on_a_new_card_gets_its_own_notice(client, env):
    b = confirmed(client, env, START)
    env.clock.set(START - timedelta(hours=3))
    env.stripe.card = "declined"
    client.post(f"{PUBLIC}/booking/{b['ref']}/cancel", json={"t": b["token"]})
    env.stripe.card = "ok"
    env.outbox.clear()
    client.post(f"{PUBLIC}/booking/{b['ref']}/card", json={"t": b["token"]})
    save_card(client, env, b["ref"], last4="1881")
    (notice,) = to(env.outbox, CLIENT)
    assert notice["subject"] == f"Cancellation fee for your consulting call ({b['ref']})"
    assert "cancelled after the free-cancellation time" in notice["html"] and "$22.20" in notice["html"]
    assert "To contest this charge" in notice["html"]


# -----------------------------------------------------------------------------
# The new emails: what a stranger typed arrives as text; the house rules hold
# -----------------------------------------------------------------------------

EVIL = '<a href="https://evil.example/pay">Pay here</a><script>x</script>"onmouseover="y'


def _new_templates(v: str = "Ada Lovelace") -> dict:
    when = "Wednesday, June 11, 2031 at 3:00 PM BST (Europe/London)"
    manage = "https://proreadyengineer.com/consult/booking/C-ABCD2345?t=tok"
    link = "https://api.proreadyengineer.com/api/consult/decision?token=abc.def"
    common = dict(full_name=v, when=when if v == "Ada Lovelace" else v)
    return {
        "reminder_first": emailer.consult_reminder_html(
            **common, minutes=60, kind="first", in_words=v if v != "Ada Lovelace" else "in two days",
            meet_url="https://meet.google.com/abc-defg-hij", manage_url=manage,
            ref=v if v != "Ada Lovelace" else "C-ABCD2345", cancel_line=v, expert=v),
        "reminder_last_no_link": emailer.consult_reminder_html(
            **common, minutes=30, kind="last", in_words="in about an hour", meet_url="", manage_url=manage,
            ref="C-1"),
        "hold_placed": emailer.consult_hold_placed_html(
            **common, amount=v if v != "Ada Lovelace" else "$111", card=v, manage_url=manage, ref="C-1",
            fee_percent=20, fee=v if v != "Ada Lovelace" else "$22.20"),
        "hold_failed": emailer.consult_hold_failed_html(
            **common, amount="$111", card=v, reason=v, deadline=v, manage_url=manage, ref="C-1"),
        "receipt": emailer.consult_receipt_html(
            **common, kind="meeting", amount="$111", card=v, charged_on=v, ref="C-1", minutes_line=v,
            from_hold=True),
        "no_show_fee": emailer.consult_receipt_html(
            **common, kind="no_show_fee", amount="$22.20", card=v, charged_on=v, ref="C-1", fee_percent=20),
        "late_cancel_fee": emailer.consult_receipt_html(
            **common, kind="late_cancel_fee", amount="$22.20", card="", charged_on=v, ref="C-1", fee_percent=20),
        "cancelled_no_hold": emailer.consult_cancelled_html(
            **common, kind="hold_failed", money_line=v, ref="C-1", rebook_url="https://proreadyengineer.com/consult"),
        "owner_summary": emailer.consult_owner_summary_html(
            intro=f"{v} has reached its end.", rows=[("Client", v), (v, v)], participants=[v, v], default_line=v,
            deadline=v, choices=[(f"Charge {v}", link), ("No-show", link), ("Do not charge", link)],
            admin_url="https://proreadyengineer.com/admin#consult/booking/1"),
        "owner_update_two_buttons": emailer.consult_owner_update_html(
            headline=f"Dispute: {v}", detail=f"{v}\n\n{v}", rows=[("Client", v)],
            admin_url="https://proreadyengineer.com/admin#consult/booking/1",
            extra_link=(f"Open {v}", "https://dashboard.stripe.com/disputes/dp_1")),
        "calendar_problem": emailer.exam_calendar_problem_html(v, "https://proreadyengineer.com/admin#certification"),
    }


@pytest.mark.parametrize("name", sorted(_new_templates()))
def test_every_value_in_the_new_templates_is_escaped(name):
    html = _new_templates(EVIL)[name]
    assert "<script>x</script>" not in html
    assert '<a href="https://evil.example' not in html and '"onmouseover="' not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>x</script>" in emailer.html_to_text(html)       # the text part shows what was typed


@pytest.mark.parametrize("name", sorted(_new_templates()))
def test_the_new_templates_follow_the_house_rules_for_mail_clients(name):
    from test_email_rendering import _UncolouredText

    html = _new_templates()[name]
    parser = _UncolouredText()
    parser.feed(html)
    assert not parser.offenders, "\n  ".join(parser.offenders)
    assert "gradient" not in html
    assert html.count("<!doctype html>") == 1 and "ProReadyEngineer &middot; Thermal Fluid Sciences" in html
    assert len(emailer.html_to_text(html)) > 120


def test_the_calendar_alert_speaks_of_examinations_and_of_consulting(client, env):
    env.google.errors["primary"] = "forbidden"
    assert client.get(f"{PUBLIC}/availability").json()["enabled"] is False
    (alert,) = [m for m in to(env.outbox, OWNER) if "[Calendar]" in m["subject"]]
    assert "Oral examinations:" in alert["html"] and "propose times instead" in alert["html"]
    assert "Consulting calls:" in alert["html"] and "takes no new" in alert["html"]
    assert "forbidden" in alert["html"]
