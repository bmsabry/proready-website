"""Shared fakes and fixtures for the consulting-call tests (test_consult_*.py).

Nothing here reaches a network:

  * Stripe is replaced at the one seam the app uses (routes.checkout._stripe)
    by FakeStripe, which keeps customers, checkout sessions, payment intents
    and refunds in memory and honours idempotency keys the way Stripe does.
  * Google is replaced at exam_calendar._google by FakeGoogle (token
    endpoint, FreeBusy, events, and for attendance the userinfo endpoint
    and the Meet REST API's conference records and participants), the way
    test_exam_calendar.py does it.
  * Email is captured at emailer._resend_post.

The clock of the consulting code is consult_money.utcnow; the `clock`
fixture pins it to Monday 2 June 2031, 10:00 in New York, far from any date
another test module uses.

Rates: the code carries none (the repository is public; the owner enters
them in the admin panel). Every test starts with the plainly artificial
RATES below saved and booking switched on. They are not anyone's prices.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import stripe as stripe_sdk
from sqlalchemy import func

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import consult  # noqa: E402
from app import consult_auto  # noqa: E402
from app import consult_money as money  # noqa: E402
from app import crypto  # noqa: E402
from app import emailer as E  # noqa: E402
from app import exam_calendar as xcal  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.consult_models import (  # noqa: E402
    ConsultBooking,
    ConsultBookingEvent,
    ConsultCharge,
    ConsultSettings,
)
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import EmailLog, ExamCalendar  # noqa: E402
from app.routes import checkout as checkout_routes  # noqa: E402
from app.routes import consult as consult_routes  # noqa: E402

ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
NY = ZoneInfo("America/New_York")
COMPANY = "bassam.abdelnabi@proreadyengineer.com"
PERSONAL = "bmsabry@gmail.com"
OWNER = "owner@example.com"
FERNET_KEY = "u5Ml1_hZ8b7cQvVQ0M6RH8HRlqYRIbNJ0lWfR0dO5vE="
PUBLIC = "/api/consult"
ADMIN_API = "/api/admin/consult"

# Monday 2 June 2031, 10:00 in New York (EDT, UTC-4).
NOW = datetime(2031, 6, 2, 14, 0, tzinfo=timezone.utc)

# Artificial hourly rates, in cents, for the tests only: four different
# numbers, so a price taken from the wrong tier never passes by accident.
RATES = {"same_day": 44_400, "next_day": 33_300, "priority": 22_200, "standard": 11_100}
# What Google had granted before the Meet permission was added to the consent
# screen: production's state until the owner reconnects the calendar.
CALENDAR_SCOPES = (
    "openid email "
    "https://www.googleapis.com/auth/calendar.freebusy "
    "https://www.googleapis.com/auth/calendar.events"
)


def ny(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A New York wall-clock time as a UTC instant."""
    return datetime(year, month, day, hour, minute, tzinfo=NY).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Obj(dict):
    """A dict with attribute access, like the SDK's objects."""

    __getattr__ = dict.get


class _NS:
    def __init__(self, **members):
        self.__dict__.update(members)


# -----------------------------------------------------------------------------
# Stripe
# -----------------------------------------------------------------------------

class FakeStripe:
    """Just enough Stripe: Customer, Checkout Session (setup mode),
    SetupIntent, PaymentIntent (create / capture / cancel / retrieve / list),
    Refund, Webhook. Idempotency keys replay the first answer.

    card:    'ok' | 'declined' | 'auth' | 'network_before' | 'network_after'
             | 'processing' | 'invalid' (the request is refused: 400)
             | 'bad_key' (401) | 'forbidden' (403) | 'rate_limit' (429)
    capture: 'ok' | 'network_after' | 'expired' | 'refused' (no connection) | 'invalid' (400)
    """

    CardError = stripe_sdk.CardError
    InvalidRequestError = stripe_sdk.InvalidRequestError
    StripeError = stripe_sdk.StripeError

    def __init__(self):
        self.customers: dict[str, Obj] = {}
        self.sessions: dict[str, Obj] = {}
        self.setup_intents: dict[str, Obj] = {}
        self.payment_intents: dict[str, Obj] = {}
        self.refunds: dict[str, Obj] = {}
        self.calls: list[tuple[str, dict]] = []
        self.idem: dict[str, tuple[str, object]] = {}
        self.replays = 0
        self.card = "ok"
        self.capture = "ok"
        self.cancel_fails = False
        self.refund_mode = "ok"
        self.refund_status = "succeeded"   # what Stripe reports for a new refund ('pending', 'failed', ...)
        self.session_fails = False
        self.refuse_expires_at = False
        self.refuse_wallet_options = False
        self.setup_intent_fails = False
        self.list_fails = False          # PaymentIntent.list gets no answer
        self.list_page = 0               # > 0: the list comes in pages this big
        self.event: dict | None = None
        self.n = 0
        self.Customer = _NS(create=self._customer_create)
        self.checkout = _NS(Session=_NS(create=self._session_create))
        self.SetupIntent = _NS(retrieve=self._setup_intent_retrieve)
        self.PaymentIntent = _NS(
            create=self._pi_create, capture=self._pi_capture,
            cancel=self._pi_cancel, retrieve=self._pi_retrieve, list=self._pi_list,
        )
        self.Refund = _NS(create=self._refund_create, list=self._refund_list)
        self.Webhook = _NS(construct_event=lambda payload, sig, secret: self.event)

    # -- helpers ---------------------------------------------------------------
    def _id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}_test_{self.n}"

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)

    def last(self, name: str) -> dict:
        return [kw for n, kw in self.calls if n == name][-1]

    def _replay(self, key):
        if key and key in self.idem:
            self.replays += 1
            kind, value = self.idem[key]
            if kind == "raise":
                raise value
            return value
        return None

    # -- customers and card pages ----------------------------------------------
    def _customer_create(self, **kw):
        self.calls.append(("Customer.create", kw))
        cid = self._id("cus")
        self.customers[cid] = Obj(id=cid, **kw)
        return self.customers[cid]

    def _session_create(self, **kw):
        self.calls.append(("Session.create", kw))
        if self.session_fails:
            raise stripe_sdk.APIConnectionError("Stripe is down")
        if self.refuse_expires_at and "expires_at" in kw:
            raise stripe_sdk.InvalidRequestError(
                "Received unknown parameter: expires_at", "expires_at", code="parameter_unknown")
        if self.refuse_wallet_options and "wallet_options" in kw:
            # The parameter as Stripe names it in the error for a nested value.
            raise stripe_sdk.InvalidRequestError(
                "Received unknown parameter: wallet_options[link][display]", "wallet_options[link][display]",
                code="parameter_unknown")
        sid = self._id("cs")
        self.sessions[sid] = Obj(id=sid, url=f"https://checkout.stripe.com/c/pay/{sid}", **kw)
        return self.sessions[sid]

    def card_saved_event(self, session_id: str, *, brand: str = "visa", last4: str = "4242") -> dict:
        """The checkout.session.completed event Stripe sends once the client
        has saved a card on that page."""
        session = self.sessions[session_id]
        seti = session.get("_setup_intent")
        if not seti:
            seti = self._id("seti")
            pm = self._id("pm")
            self.setup_intents[seti] = Obj(
                id=seti, status="succeeded", customer=session["customer"],
                payment_method=Obj(id=pm, card=Obj(brand=brand, last4=last4)),
            )
            session["_setup_intent"] = seti
            session["_completed"] = int(money.utcnow().timestamp())    # when the client finished the page
        return {
            "type": "checkout.session.completed",
            "created": session["_completed"],
            "data": {"object": {
                "id": session_id, "object": "checkout.session", "mode": "setup",
                "payment_status": "no_payment_required", "setup_intent": seti,
                "customer": session["customer"], "metadata": dict(session["metadata"]),
                "success_url": session["success_url"],
            }},
        }

    def _setup_intent_retrieve(self, seti_id, **kw):
        self.calls.append(("SetupIntent.retrieve", {"id": seti_id, **kw}))
        if self.setup_intent_fails:
            raise stripe_sdk.APIConnectionError("Stripe is down")
        return self.setup_intents[seti_id]

    # -- payment intents ------------------------------------------------------
    def _pi_create(self, **kw):
        self.calls.append(("PaymentIntent.create", kw))
        key = kw.get("idempotency_key")
        replayed = self._replay(key)
        if replayed is not None:
            return replayed
        assert kw["off_session"] is True and kw["confirm"] is True
        assert kw["customer"] in self.customers, "charge on an unknown customer"
        if self.card == "network_before":
            raise stripe_sdk.APIConnectionError("connection reset")
        if self.card == "bad_key":
            raise stripe_sdk.AuthenticationError("Invalid API Key provided: sk_live_****")
        if self.card == "forbidden":
            raise stripe_sdk.PermissionError("The provided key does not have the required permissions.")
        if self.card == "rate_limit":
            raise stripe_sdk.RateLimitError("Too many requests hit the API too quickly.")
        if self.card == "invalid":
            exc = stripe_sdk.InvalidRequestError(
                "The payment method does not belong to this customer.", "payment_method",
                code="payment_method_unexpected_state",
            )
            if key:
                self.idem[key] = ("raise", exc)
            raise exc
        pid = self._id("pi")
        manual = kw.get("capture_method") == "manual"
        pi = Obj(
            id=pid, amount=kw["amount"], currency=kw["currency"], customer=kw["customer"],
            payment_method=kw["payment_method"], capture_method=kw.get("capture_method"),
            metadata=kw.get("metadata") or {}, amount_received=0, refunded=0, status="",
            created=int(money.utcnow().timestamp()),
        )
        self.payment_intents[pid] = pi
        if self.card in ("declined", "auth"):
            pi["status"] = "requires_payment_method"
            code = "card_declined" if self.card == "declined" else "authentication_required"
            message = (
                "Your card was declined." if self.card == "declined"
                else "This payment requires authentication."
            )
            exc = stripe_sdk.CardError(
                message, None, code,
                json_body={"error": {
                    "code": code,
                    "decline_code": "insufficient_funds" if self.card == "declined" else "authentication_required",
                    "payment_intent": {"id": pid, "status": "requires_payment_method"},
                }},
            )
            if key:
                self.idem[key] = ("raise", exc)
            raise exc
        if self.card == "processing":
            pi["status"] = "processing"
        elif manual:
            pi["status"] = "requires_capture"
        else:
            pi["status"], pi["amount_received"] = "succeeded", kw["amount"]
        if key:
            self.idem[key] = ("return", pi)
        if self.card == "network_after":
            # The charge went through, but the answer never arrived.
            raise stripe_sdk.APIConnectionError("connection reset after the request was sent")
        return pi

    def _pi_capture(self, pi_id, **kw):
        self.calls.append(("PaymentIntent.capture", {"id": pi_id, **kw}))
        key = kw.get("idempotency_key")
        replayed = self._replay(key)
        if replayed is not None:
            return replayed
        pi = self.payment_intents[pi_id]
        if self.capture == "expired":
            pi["status"] = "canceled"
        if self.capture == "refused":
            raise stripe_sdk.APIConnectionError("connection reset")
        if self.capture == "invalid":
            # Stripe refuses the capture request itself; the authorization stands.
            raise stripe_sdk.InvalidRequestError("This capture request is not valid.", "amount_to_capture",
                                                 code="parameter_invalid_integer")
        if pi["status"] != "requires_capture":
            raise stripe_sdk.InvalidRequestError(
                f"This PaymentIntent could not be captured because it has a status of {pi['status']}.",
                None, code="payment_intent_unexpected_state",
            )
        amount = kw.get("amount_to_capture", pi["amount"])
        assert amount <= pi["amount"], "captured more than was authorized"
        pi["status"], pi["amount_received"] = "succeeded", amount
        if key:
            self.idem[key] = ("return", pi)
        if self.capture == "network_after":
            raise stripe_sdk.APIConnectionError("connection reset after the request was sent")
        return pi

    def _pi_cancel(self, pi_id, **kw):
        self.calls.append(("PaymentIntent.cancel", {"id": pi_id, **kw}))
        if self.cancel_fails:
            raise stripe_sdk.APIConnectionError("connection reset")
        pi = self.payment_intents[pi_id]
        if pi["status"] == "succeeded":
            raise stripe_sdk.InvalidRequestError(
                "You cannot cancel this PaymentIntent because it has a status of succeeded.",
                None, code="payment_intent_unexpected_state",
            )
        pi["status"] = "canceled"
        return pi

    def _pi_retrieve(self, pi_id, **kw):
        self.calls.append(("PaymentIntent.retrieve", {"id": pi_id}))
        return self.payment_intents[pi_id]

    def _pi_list(self, **kw):
        """The customer's payment intents, newest first, in pages."""
        self.calls.append(("PaymentIntent.list", kw))
        if self.list_fails:
            raise stripe_sdk.APIConnectionError("connection reset")
        assert kw.get("customer"), "a list that is not narrowed to one customer"
        mine = [pi for pi in reversed(list(self.payment_intents.values())) if pi["customer"] == kw["customer"]]
        after = kw.get("starting_after")
        if after:
            ids = [pi["id"] for pi in mine]
            mine = mine[ids.index(after) + 1:]
        size = min(self.list_page or 100, int(kw.get("limit") or 10))
        return Obj(object="list", data=mine[:size], has_more=len(mine) > size)

    # -- refunds --------------------------------------------------------------
    def _refund_create(self, **kw):
        self.calls.append(("Refund.create", kw))
        key = kw.get("idempotency_key")
        replayed = self._replay(key)
        if replayed is not None:
            return replayed
        if self.refund_mode == "network_before":
            raise stripe_sdk.APIConnectionError("connection reset")
        pi = self.payment_intents[kw["payment_intent"]]
        if kw["amount"] > pi["amount_received"] - pi["refunded"]:
            exc = stripe_sdk.InvalidRequestError(
                "Refund amount is greater than the unrefunded amount on the charge.", "amount",
                code="charge_already_refunded",
            )
            if key:
                self.idem[key] = ("raise", exc)
            raise exc
        rid = self._id("re")
        if self.refund_status in ("succeeded", "pending", "requires_action"):
            pi["refunded"] += kw["amount"]
        self.refunds[rid] = Obj(
            id=rid, status=self.refund_status, amount=kw["amount"], payment_intent=pi["id"],
            metadata=dict(kw.get("metadata") or {}),
        )
        if key:
            self.idem[key] = ("return", self.refunds[rid])
        if self.refund_mode == "network_after":
            raise stripe_sdk.APIConnectionError("connection reset after the request was sent")
        return self.refunds[rid]

    def _refund_list(self, **kw):
        """The refunds on one payment, newest first."""
        self.calls.append(("Refund.list", kw))
        if self.list_fails:
            raise stripe_sdk.APIConnectionError("connection reset")
        assert kw.get("payment_intent"), "a refund list that is not narrowed to one payment"
        mine = [r for r in reversed(list(self.refunds.values())) if r["payment_intent"] == kw["payment_intent"]]
        after = kw.get("starting_after")
        if after:
            ids = [r["id"] for r in mine]
            mine = mine[ids.index(after) + 1:]
        size = min(self.list_page or 100, int(kw.get("limit") or 10))
        return Obj(object="list", data=mine[:size], has_more=len(mine) > size)

    # -- totals ---------------------------------------------------------------
    def money_taken(self) -> int:
        """Cents actually taken from cards, across every payment intent."""
        return sum(pi["amount_received"] for pi in self.payment_intents.values())

    def money_returned(self) -> int:
        """Cents actually sent back to cards (refunds Stripe has completed)."""
        return sum(r["amount"] for r in self.refunds.values() if r["status"] == "succeeded")

    def authorized(self) -> int:
        return sum(pi["amount"] for pi in self.payment_intents.values() if pi["status"] == "requires_capture")


# -----------------------------------------------------------------------------
# Google
# -----------------------------------------------------------------------------

HOST_SUB = "117000000000000000001"      # the connected Google account's id


class FakeGoogle:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.busy: dict[str, list[tuple[datetime, datetime]]] = {"primary": [], PERSONAL: []}
        self.errors: dict[str, str] = {}
        self.events: dict[str, dict] = {}
        self.event_fails = False
        self.delete_fails = False
        self.n = 0
        # Meet: {meeting code: [conference record, ...]}; each record is
        # {"name", "startTime", "endTime"?, "participants": [...]}.
        self.meet: dict[str, list[dict]] = {}
        self.meet_refuses: tuple[int, str] | None = None   # (HTTP status, Google's words)
        self.meet_down = False                              # the request never gets an answer
        self.userinfo_fails = False
        self.page_size = 0                                  # > 0: participants come in pages this big

    def freebusy_calls(self) -> int:
        return sum(1 for _, url, _ in self.calls if url.endswith("/freeBusy"))

    def meet_calls(self) -> int:
        return sum(1 for _, url, _ in self.calls if url.startswith(consult_auto.MEET_API))

    def conference(self, meet_url: str, start: datetime, end: datetime | None, *people) -> dict:
        """Record that a conference ran on this Meet link. Each of `people`
        is (who, display name, joined, left): who is 'host', 'guest' (not
        signed in), 'phone', or a Google user id for another signed-in
        account; left may be None (still in the call)."""
        code = meet_url.rsplit("/", 1)[-1]
        records = self.meet.setdefault(code, [])
        name = f"conferenceRecords/rec-{code}-{len(records) + 1}"
        participants = []
        for i, (who, label, joined, left) in enumerate(people, 1):
            p = {"name": f"{name}/participants/p{i}", "earliestStartTime": iso(joined)[:-1] + ".123456789Z"}
            if left is not None:
                p["latestEndTime"] = iso(left)
            if who == "host":
                p["signedinUser"] = {"user": f"users/{HOST_SUB}", "displayName": label}
            elif who == "guest":
                p["anonymousUser"] = {"displayName": label}
            elif who == "phone":
                p["phoneUser"] = {"displayName": label}
            else:
                p["signedinUser"] = {"user": f"users/{who}", "displayName": label}
            participants.append(p)
        record = {"name": name, "startTime": iso(start), "space": f"spaces/{code}", "participants": participants}
        if end is not None:
            record["endTime"] = iso(end)
        records.append(record)
        return record

    def _meet(self, url: str, params: dict | None):
        if self.meet_down:
            raise xcal.CalendarError("Google could not be reached (ConnectTimeout).")
        if self.meet_refuses:
            status, words = self.meet_refuses
            return status, {"error": {"code": status, "message": words, "status": "PERMISSION_DENIED"}}
        params = params or {}
        if url == f"{consult_auto.MEET_API}/conferenceRecords":
            code = re.fullmatch(r'space\.meeting_code = "([a-z0-9-]+)"', params["filter"]).group(1)
            return 200, {"conferenceRecords": [
                {k: v for k, v in r.items() if k != "participants"} for r in self.meet.get(code, [])
            ]}
        found = re.fullmatch(rf"{re.escape(consult_auto.MEET_API)}/(conferenceRecords/[^/]+)/participants", url)
        assert found, f"unexpected Meet call {url}"
        people = next(r["participants"] for rs in self.meet.values() for r in rs if r["name"] == found.group(1))
        if not self.page_size:
            return 200, {"participants": people}
        at = int(params.get("pageToken") or 0)
        page = {"participants": people[at:at + self.page_size]}
        if at + self.page_size < len(people):
            page["nextPageToken"] = str(at + self.page_size)
        return 200, page

    def __call__(self, method, url, *, token=None, data=None, json_body=None, params=None):
        self.calls.append((method, url, {"data": data, "json": json_body, "params": params}))
        if url == xcal.TOKEN_URL:
            return 200, {"access_token": "at-consult", "expires_in": 3600}
        assert token, "calendar API called without a token"
        if url == consult_auto.USERINFO_URL:
            assert method == "GET"
            if self.userinfo_fails:
                return 401, {"error": "invalid_token", "error_description": "Invalid Credentials"}
            return 200, {"sub": HOST_SUB, "email": COMPANY, "email_verified": True}
        if url.startswith(consult_auto.MEET_API):
            assert method == "GET", "attendance is read, never written"
            return self._meet(url, params)
        if url.endswith("/freeBusy"):
            out = {}
            for item in json_body["items"]:
                cid = item["id"]
                if cid in self.errors:
                    out[cid] = {"errors": [{"domain": "global", "reason": self.errors[cid]}], "busy": []}
                    continue
                blocks = list(self.busy.get(cid, []))
                if cid == "primary":  # events made through us sit on his own calendar
                    blocks += [(e["_start"], e["_end"]) for e in self.events.values()]
                out[cid] = {"busy": [{"start": iso(s), "end": iso(e)} for s, e in blocks]}
            return 200, {"calendars": out}
        if "/events" in url:
            if method == "POST":
                if self.event_fails:
                    return 403, {"error": {"message": "Calendar usage limits exceeded."}}
                self.n += 1
                eid = f"cevt{self.n}"
                ev = dict(json_body)
                ev["_start"] = datetime.fromisoformat(json_body["start"]["dateTime"].replace("Z", "+00:00"))
                ev["_end"] = datetime.fromisoformat(json_body["end"]["dateTime"].replace("Z", "+00:00"))
                ev["_params"] = params
                self.events[eid] = ev
                return 200, {
                    "id": eid, "htmlLink": f"https://calendar.google.com/event?eid={eid}",
                    "hangoutLink": f"https://meet.google.com/con-{eid}",
                }
            eid = url.rsplit("/", 1)[-1]
            if method == "DELETE":
                if self.delete_fails:
                    return 500, {"error": {"message": "Backend Error"}}
                self.events.pop(eid, None)
                return 204, {}
            if method == "GET":
                return 200, {"id": eid, "hangoutLink": f"https://meet.google.com/con-{eid}"}
        raise AssertionError(f"unexpected Google call {method} {url}")


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

class Clock:
    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def set(self, at: datetime) -> None:
        self.at = at.astimezone(timezone.utc)

    def advance(self, **delta) -> None:
        self.at = self.at + timedelta(**delta)


def wipe_consult(db) -> None:
    db.query(ConsultCharge).delete()
    db.query(ConsultBookingEvent).delete()
    db.query(ConsultBooking).delete()
    db.query(ConsultSettings).delete()
    db.commit()


def seed_settings(db) -> None:
    """What the owner does once in the admin panel: save the four rates and
    switch booking on. (Here with the artificial RATES.)"""
    cs = consult.settings_row(db)
    for tier, cents in RATES.items():
        setattr(cs, f"rate_{tier}_cents", cents)
    cs.enabled = True
    db.commit()


@pytest.fixture(scope="module", autouse=True)
def world():
    """A connected calendar (company + personal), an encryption key for its
    stored token, and empty consulting tables. All undone afterwards."""
    old_key = os.environ.get("AI_SETTINGS_KEY")
    os.environ["AI_SETTINGS_KEY"] = FERNET_KEY
    crypto._fernet.cache_clear()
    db = SessionLocal()
    wipe_consult(db)
    db.query(ExamCalendar).delete()
    db.add(ExamCalendar(
        id=1, check_calendars=["primary", PERSONAL], weekly_hours=dict(xcal.DEFAULT_HOURS),
        refresh_token_encrypted=crypto.encrypt("rt-consult"), account_email=COMPANY,
        scopes=CALENDAR_SCOPES, timezone="America/New_York", self_booking=True,
        connected_at=datetime.now(timezone.utc),
    ))
    db.commit()
    # The test window must start empty: no other module's course sits in it.
    foreign = consult.course_blocks(db, NOW - timedelta(days=2), NOW + timedelta(days=70))
    assert foreign == [], f"another test left a course session in June 2031: {foreign}"
    last_email = db.query(func.max(EmailLog.id)).scalar() or 0
    db.close()
    yield
    db = SessionLocal()
    wipe_consult(db)
    db.query(ExamCalendar).delete()
    # Every email-log row these tests wrote (nothing was sent anywhere).
    db.query(EmailLog).filter(EmailLog.id > last_email).delete(synchronize_session=False)
    db.commit()
    db.close()
    xcal._TOKEN.clear()
    consult.clear_cache()
    if old_key is None:
        os.environ.pop("AI_SETTINGS_KEY", None)
    else:
        os.environ["AI_SETTINGS_KEY"] = old_key
    crypto._fernet.cache_clear()


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"id": "msg-consult"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Every test: fake Stripe, fake Google, captured email, the pinned
    clock, clean consulting tables, default settings with the artificial
    RATES saved and booking switched on, no rate-limit history."""
    s = get_settings()
    monkeypatch.setattr(s, "STRIPE_SECRET_KEY", "sk_test_consult")
    monkeypatch.setattr(s, "STRIPE_WEBHOOK_SECRET", "whsec_consult")
    monkeypatch.setattr(s, "ADMIN_NOTIFY_EMAIL", OWNER)
    monkeypatch.setattr(s, "RESEND_API_KEY", "re_test", raising=False)

    stripe = FakeStripe()
    monkeypatch.setattr(checkout_routes, "_stripe", lambda: stripe)

    google = FakeGoogle()
    monkeypatch.setattr(xcal, "_google", google)
    xcal._TOKEN.clear()

    outbox: list[dict] = []
    monkeypatch.setattr(E, "_resend_post", lambda url, payload, key: (outbox.append(payload), _Resp())[1])

    clock = Clock(NOW)
    monkeypatch.setattr(money, "utcnow", clock)

    # No cache between steps of a test, unless the test asks for it.
    monkeypatch.setattr(consult, "BUSY_CACHE_SECONDS", 0)
    consult.clear_cache()
    for window in consult_routes.LIMITS.values():
        window.reset()
    # The "automation has stopped" watch runs off every consulting request;
    # it is off here, and switched on by the tests that are about it.
    monkeypatch.setattr(consult_routes, "TICK_WATCH_SECONDS", None)

    db = SessionLocal()
    wipe_consult(db)
    seed_settings(db)
    db.query(EmailLog).filter(EmailLog.scope_code == "consult").delete(synchronize_session=False)
    # The calendar-problem alert goes out at most twice a day: start each
    # test as if none had been sent. The Meet permission is not granted
    # unless a test grants it.
    cal = db.get(ExamCalendar, 1)
    cal.last_error, cal.last_alert_at, cal.scopes = "", None, CALENDAR_SCOPES
    db.commit()
    db.close()
    return _NS(stripe=stripe, google=google, outbox=outbox, clock=clock)


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


# -----------------------------------------------------------------------------
# Steps a test takes
# -----------------------------------------------------------------------------

def to(outbox: list[dict], addr: str) -> list[dict]:
    return [m for m in outbox if addr in m["to"]]


def get_quote(client, start: datetime, minutes: int = 60, **kw):
    return client.post(f"{PUBLIC}/quote", json={"start": iso(start), "minutes": minutes}, **kw)


def book(client, start: datetime, minutes: int = 60, *, email: str = "client@example.com",
         name: str = "Casey Client", ip: str = "198.51.100.7", terms_version: str | None = None,
         **fields):
    """Quote, then book. Returns the /book response."""
    headers = {"X-Forwarded-For": ip, "User-Agent": "pytest-consult/1.0"}
    if terms_version is None:
        q = get_quote(client, start, minutes, headers=headers)
        # A time that is not open gets no quote; /book is still asked, so
        # the caller sees what the booking endpoint answers for it.
        assert q.status_code in (200, 409), q.text
        terms_version = q.json().get("terms_version", "no-quote-was-given")
    body = {
        "start": iso(start), "minutes": minutes, "full_name": name, "email": email,
        "company": "Example Turbines", "phone": "+1 555 0100",
        "topic": "Lean blowout margin on a DLE combustor at part load.",
        "timezone": "Europe/London", "terms_version": terms_version, "agree": True, "website": "",
    }
    body.update(fields)
    return client.post(f"{PUBLIC}/book", json=body, headers=headers)


def post_webhook(client, env, event: dict):
    env.stripe.event = event
    return client.post(
        "/api/academy/webhook/stripe", json={}, headers={"Stripe-Signature": "t=1,v1=test"},
    )


def save_card(client, env, ref: str, **card):
    """Stripe tells us the client saved a card on the booking's card page."""
    row = booking_row(ref)
    return post_webhook(client, env, env.stripe.card_saved_event(row.stripe_checkout_session_id, **card))


def confirmed(client, env, start: datetime, minutes: int = 60, **kw) -> dict:
    """A booking taken all the way to confirmed. Returns {ref, token, id}."""
    r = book(client, start, minutes, **kw)
    assert r.status_code == 200, r.text
    data = r.json()
    w = save_card(client, env, data["ref"])
    assert w.status_code == 200, w.text
    row = booking_row(data["ref"])
    assert row.status == "confirmed", row.status
    return {"ref": data["ref"], "token": data["manage_token"], "id": row.id}


def booking_row(ref: str) -> ConsultBooking:
    db = SessionLocal()
    try:
        row = db.query(ConsultBooking).filter(ConsultBooking.ref == ref).one()
        db.expunge(row)
        return row
    finally:
        db.close()


def events_of(booking_id: int) -> list[str]:
    db = SessionLocal()
    try:
        return [e.kind for e in db.query(ConsultBookingEvent)
                .filter(ConsultBookingEvent.booking_id == booking_id)
                .order_by(ConsultBookingEvent.id).all()]
    finally:
        db.close()


def charges_of(booking_id: int) -> list[ConsultCharge]:
    db = SessionLocal()
    try:
        rows = db.query(ConsultCharge).filter(ConsultCharge.booking_id == booking_id).order_by(ConsultCharge.id).all()
        for r in rows:
            db.expunge(r)
        return rows
    finally:
        db.close()


def slot_starts(client, tz: str = "America/New_York") -> list[str]:
    r = client.get(f"{PUBLIC}/availability", params={"tz": tz})
    assert r.status_code == 200, r.text
    return [s["start"] for d in r.json()["days"] for s in d["slots"]]


# -----------------------------------------------------------------------------
# The settlement automation (test_consult_tick.py and its neighbours)
# -----------------------------------------------------------------------------

def tick(client) -> dict:
    """What the cron job does every five minutes."""
    r = client.post(f"{ADMIN_API}/tick", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def grant_meet_scope() -> None:
    """The owner has reconnected the calendar and ticked the Meet permission."""
    db = SessionLocal()
    db.get(ExamCalendar, 1).scopes = xcal.SCOPES
    db.commit()
    db.close()


def state_of_everything(env) -> tuple:
    """Everything a tick could change: every consulting row, every email,
    every call to Stripe, and every call to Google that writes."""
    db = SessionLocal()
    try:
        def rows(model, skip=("updated_at",)):
            return [
                tuple((c.name, getattr(r, c.name)) for c in model.__table__.columns if c.name not in skip)
                for r in db.query(model).order_by(model.id).all()
            ]
        return (
            rows(ConsultBooking), rows(ConsultBookingEvent), rows(ConsultCharge),
            len(env.outbox), list(env.stripe.calls),
            [(m, u) for m, u, _ in env.google.calls if m != "GET" and not u.endswith("/freeBusy") and u != xcal.TOKEN_URL],
        )
    finally:
        db.close()


def subjects(outbox: list[dict], addr: str) -> list[str]:
    return [m["subject"] for m in to(outbox, addr)]
