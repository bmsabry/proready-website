"""Consulting calls: the public booking API and the admin API.

Public, no sign-in (a booking is reached with its reference and manage token):

  GET  /api/consult/availability?tz=IANA     open times. Never a price.
  POST /api/consult/quote                    price and terms for one time
  POST /api/consult/book                     hold the time, open card entry
  GET  /api/consult/booking/{ref}?t=token    the client's own booking
  POST /api/consult/booking/{ref}/cancel     cancel it
  POST /api/consult/booking/{ref}/card       a card page (finish, or replace)

The owner's links from the post-meeting summary email (a signed token, no
sign-in; they open in his mail app):

  GET  /api/consult/decision?token=          a confirm page. Changes nothing.
  POST /api/consult/decision?token=          the button on that page: decides.

Admin (cookie session or bearer token):

  GET/PUT /api/admin/consult/settings
  GET     /api/admin/consult/bookings?status=&q=
  GET     /api/admin/consult/bookings/{id}
  POST    /api/admin/consult/bookings/{id}/charge | no-show | waive | cancel | refund
  POST    /api/admin/consult/bookings/{id}/review-settled | review-not-charged
                                             close a payment attempt parked
                                             as "needs review" (Stripe is
                                             asked to confirm; no money moves)
  GET     /api/admin/consult/status
  POST    /api/admin/consult/tick            the settlement tick (cron secret
                                             or admin): holds, reminders,
                                             attendance, automatic outcome

Rates leave this API in exactly two answers: the quote and the booking.
The logic is in app/consult.py and app/consult_auto.py; money moves only in
app/consult_money.py.
"""
from __future__ import annotations

import ipaddress
import logging
import secrets
import threading
import time
from collections import deque
from datetime import datetime
from html import escape
from typing import Optional
from urllib.parse import quote as url_quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from .. import consult, consult_auto
from ..activity import client_ip
from ..config import get_settings
from ..consult_models import ConsultBooking
from ..db import get_db
from ..deps import require_admin
from .reminders import require_admin_or_cron

log = logging.getLogger(__name__)

# With the cron job stopped nothing automatic runs and nothing says so. Every
# consulting request, public or admin, therefore looks (after it has
# answered, and at most this often per process) whether the tick is overdue
# while a confirmed call is near, and has the owner emailed: consult.watch_tick.
# None switches the watch off (the tests do, except the ones about it).
TICK_WATCH_SECONDS: float | None = 60.0
_last_watch = [0.0]


def _watch_tick(request: Request, background: BackgroundTasks) -> None:
    if TICK_WATCH_SECONDS is None or request.url.path.endswith("/tick"):
        return
    moment = time.monotonic()
    if moment - _last_watch[0] < TICK_WATCH_SECONDS:
        return
    _last_watch[0] = moment
    background.add_task(consult.watch_tick_later)


public_router = APIRouter(prefix="/api/consult", tags=["consult"], dependencies=[Depends(_watch_tick)])
admin_router = APIRouter(prefix="/api/admin/consult", tags=["consult-admin"], dependencies=[Depends(_watch_tick)])


# -----------------------------------------------------------------------------
# Per-IP rate limits (in this process; the booking caps in consult.py are in
# the database and hold across restarts)
# -----------------------------------------------------------------------------

class _Window:
    """At most `limit` hits per `seconds` for one key."""

    def __init__(self, limit: int, seconds: int):
        self.limit, self.seconds = limit, seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 5000:  # drop keys that have gone quiet
                for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.seconds]:
                    del self._hits[k]
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.seconds:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITS = {
    "quote": _Window(40, 300),    # a quote per click on a length, with room
    "book": _Window(8, 3600),
    "card": _Window(12, 3600),
    "cancel": _Window(20, 3600),
    "decision": _Window(60, 3600),
    # A decision request whose token is not one of ours (made up, changed,
    # incomplete) is counted here, never in the bucket above: whoever sends
    # such requests "from" the owner's address cannot use up the allowance
    # his own, valid links are counted against.
    "decision_invalid": _Window(30, 3600),
}


def _ip(request: Request) -> str:
    """The visitor's address, for the per-address limits and the consent
    record: `CF-Connecting-IP`, else the first entry of X-Forwarded-For (the
    rule the rest of the site uses), else the socket's own address. Each is
    taken only if it IS an IP address (review 2, N7); "" when none is.

    Whether a caller can write `CF-Connecting-IP` depends on the platform's
    edge, which this code cannot see: where the edge sets it, it replaces
    what the caller wrote; where it does not, a caller can still send any
    real address here, as with X-Forwarded-For. The limits that cannot be
    talked around are the site-wide ones in consult.py, and the owner's
    decision links are counted only after their token has been checked."""
    for said in (
        request.headers.get("cf-connecting-ip") or "",
        client_ip(request.headers, ""),                      # first entry of X-Forwarded-For
        request.client.host if request.client else "",       # the socket's own address
    ):
        address = _address(said)
        if address:
            return address
    return ""


def _address(text: str) -> str:
    """`text` as an IP address in its usual spelling, or "" when it is not
    one. A header is only ever taken as an address when it is one: the
    value is stored in the consent record and keys the per-address limits,
    and neither may hold whatever text a caller chose to send."""
    try:
        return str(ipaddress.ip_address((text or "").strip()))
    except ValueError:
        return ""


def _limit(request: Request, bucket: str) -> None:
    if not LIMITS[bucket].allow(_ip(request) or "unknown"):
        raise HTTPException(
            status_code=429,
            detail="Too many requests in a short time. Please wait a few minutes and try again.",
            headers={"Retry-After": str(LIMITS[bucket].seconds)},
        )


def _refuse(exc: consult.ConsultError) -> HTTPException:
    """A domain refusal as the HTTP answer the contract names: 409 with a
    sentence, or 422 in FastAPI's list shape for a wrong field."""
    if isinstance(exc, consult.InvalidInput):
        return HTTPException(status_code=422, detail=[{
            "type": "value_error", "loc": ["body", exc.field], "msg": exc.message, "input": None,
        }])
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _no_store(payload: dict) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

@public_router.get("/availability")
def availability(tz: str = "", db: Session = Depends(get_db)) -> JSONResponse:
    return _no_store(consult.availability(db, tz[:64]))


class QuoteIn(BaseModel):
    start: datetime
    minutes: int = Field(ge=1, le=1440)


@public_router.post("/quote")
def quote(body: QuoteIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    _limit(request, "quote")
    try:
        q = consult.quote_for(db, body.start, body.minutes)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _no_store(q.out())


class BookIn(BaseModel):
    start: datetime
    minutes: int = Field(ge=1, le=1440)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    company: Optional[str] = Field(default="", max_length=200)
    phone: Optional[str] = Field(default="", max_length=40)
    topic: str = Field(min_length=3, max_length=4000)
    timezone: str = Field(min_length=1, max_length=64)
    terms_version: str = Field(min_length=1, max_length=64)
    agree: bool
    # Honeypot: people leave it empty. Filled, the request is answered as if
    # it had worked and nothing is done.
    website: str = Field(default="", max_length=500)

    @field_validator("full_name", "topic", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("agree")
    @classmethod
    def _must_agree(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Please confirm that you have read and agree to the booking terms.")
        return value

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        if not consult.valid_zone(value):
            raise ValueError("Unknown time zone.")
        return value.strip()


@public_router.post("/book")
def book(body: BookIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    if body.website.strip():
        log.info("Consult honeypot triggered; answering as if booked.")
        ref = "C-" + "".join(secrets.choice(consult._REF_ALPHABET) for _ in range(8))
        token = secrets.token_urlsafe(32)
        return _no_store({
            "ref": ref, "manage_token": token,
            "checkout_url": f"{get_settings().SITE_URL.rstrip('/')}/consult/booking/{ref}?t={token}&card=cancelled",
        })
    _limit(request, "book")
    try:
        booking, token, url = consult.create_booking(
            db, start=body.start, minutes=body.minutes, full_name=body.full_name,
            email=str(body.email), company=body.company or "", phone=body.phone or "",
            topic=body.topic, timezone_name=body.timezone, terms_version=body.terms_version,
            ip=_ip(request), user_agent=request.headers.get("user-agent", ""),
        )
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _no_store({"ref": booking.ref, "manage_token": token, "checkout_url": url})


def _booking_or_404(db: Session, ref: str, token: str) -> ConsultBooking:
    booking = consult.find_booking(db, ref, token)
    if booking is None:
        # One answer for "no such booking" and "wrong token".
        raise HTTPException(status_code=404, detail="Booking not found. Check the link in your confirmation email.")
    return booking


@public_router.get("/booking/{ref}")
def get_booking(ref: str, t: str = "", db: Session = Depends(get_db)) -> JSONResponse:
    booking = _booking_or_404(db, ref, t)
    return _no_store(consult.public_view(booking))


class TokenIn(BaseModel):
    t: str = Field(min_length=1, max_length=200)


@public_router.post("/booking/{ref}/cancel")
def cancel_booking(ref: str, body: TokenIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    _limit(request, "cancel")
    booking = _booking_or_404(db, ref, body.t)
    try:
        booking = consult.cancel_by_client(db, booking)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _no_store(consult.public_view(booking))


@public_router.post("/booking/{ref}/card")
def booking_card(ref: str, body: TokenIn, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    _limit(request, "card")
    booking = _booking_or_404(db, ref, body.t)
    try:
        url = consult.card_setup_url(db, booking, body.t)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _no_store({"checkout_url": url})


# -----------------------------------------------------------------------------
# The owner's links from the summary email
# -----------------------------------------------------------------------------
# Mail scanners (and link previews) open every link in an email. So opening
# one of these shows a page and does nothing; only pressing the button on
# that page, a POST, decides. The page is plain HTML from this API because
# the link has to work from a phone's mail app with no sign-in.

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title} | ProReadyEngineer</title>
<style>
  body {{ margin:0; padding:24px 16px; background:#060b18; color:#e2e8f0;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  main {{ max-width:560px; margin:0 auto; background:#0f172a; border:1px solid #1e293b;
          border-radius:14px; padding:28px; }}
  .eyebrow {{ font-size:11px; font-weight:600; letter-spacing:.16em; text-transform:uppercase; color:#67e8f9; }}
  h1 {{ margin:10px 0 18px; font-size:22px; line-height:1.3; color:#f8fafc; }}
  p {{ margin:0 0 14px; font-size:16px; line-height:1.6; color:#cbd5e1; word-break:break-word; }}
  button {{ display:block; width:100%; margin:22px 0 8px; padding:16px 20px; border:0; border-radius:10px;
            background:linear-gradient(90deg,#22d3ee,#3b82f6); color:#04121f; font-size:17px;
            font-weight:700; cursor:pointer; }}
  a {{ color:#67e8f9; }}
  .small {{ font-size:14px; color:#94a3b8; }}
</style>
</head>
<body>
<main>
  <div class="eyebrow">ProReadyEngineer &middot; Consulting</div>
  <h1>{title}</h1>
  {body}
</main>
</body>
</html>"""


def _decision_page(d: consult_auto.Decision, token: str) -> HTMLResponse:
    body = "".join(f"<p>{escape(line)}</p>" for line in d.lines)
    if d.state == "ready" and d.button:
        action = f"/api/consult/decision?token={url_quote(token, safe='')}"
        body += (
            f'<form method="post" action="{escape(action)}">'
            f"<button type=\"submit\">{escape(d.button)}</button></form>"
        )
    if d.admin_url:
        body += f'<p class="small">Or <a href="{escape(d.admin_url)}">open the booking in the admin panel</a>.</p>'
    return HTMLResponse(
        _PAGE.format(title=escape(d.title), body=body),
        status_code=d.http,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
        },
    )


@public_router.get("/decision", include_in_schema=False)
def decision_page(request: Request, token: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    """The confirm page. Reads; never writes."""
    seen = consult_auto.look_at_decision(db, token[:1000])
    _limit(request, "decision_invalid" if seen.state == "invalid" else "decision")
    return _decision_page(seen, token[:1000])


@public_router.post("/decision", include_in_schema=False)
def decision_confirm(request: Request, token: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    """The button on the confirm page. The token is looked at first (that
    changes nothing), so that only a request carrying one of our own links
    is counted against the address's allowance for deciding."""
    if consult_auto.look_at_decision(db, token[:1000]).state == "invalid":
        _limit(request, "decision_invalid")
    else:
        _limit(request, "decision")
    return _decision_page(consult_auto.decide(db, token[:1000]), token[:1000])


# -----------------------------------------------------------------------------
# Admin
# -----------------------------------------------------------------------------

class SettingsIn(BaseModel):
    enabled: Optional[bool] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    weekly_hours: Optional[dict] = None
    step_minutes: Optional[int] = None
    durations: Optional[list[int]] = None
    buffer_minutes: Optional[int] = None
    min_notice_hours: Optional[int] = None
    horizon_days: Optional[int] = None
    max_per_day: Optional[int] = None
    # Integer cents per hour for any of: same_day, next_day, priority, standard.
    rates_cents_per_hour: Optional[dict[str, int]] = None
    standard_from_days: Optional[int] = None
    fee_percent: Optional[int] = None
    free_cancel_hours: Optional[int] = None
    hold_lead_hours: Optional[int] = None
    auto_settle_hours: Optional[int] = None
    reminder_before_deadline_hours: Optional[int] = None
    reminder_before_start_hours: Optional[int] = None


@admin_router.get("/settings")
def get_settings_(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    return consult.settings_out(consult.settings_row(db))


@admin_router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    try:
        cs = consult.update_settings(db, body.model_dump(exclude_none=True))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    consult.clear_cache()
    return consult.settings_out(cs)


@admin_router.get("/bookings")
def list_bookings(
    status: str = "", q: str = "", db: Session = Depends(get_db), _: str = Depends(require_admin),
) -> dict:
    return {"bookings": consult.admin_bookings(db, status=status, q=q[:200])}


def _one(db: Session, booking_id: int) -> dict:
    rows = consult.admin_bookings(db, booking_id=booking_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return rows[0]


def _load(db: Session, booking_id: int) -> ConsultBooking:
    booking = db.get(ConsultBooking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking


def _with_action(db: Session, booking_id: int, result: consult.PayResult | None) -> dict:
    """The updated booking, plus what the action just did with the card
    (`action`), so the screen can say 'declined' without guessing."""
    out = _one(db, booking_id)
    if result is not None:
        out["action"] = {
            "ok": result.ok, "status": result.status, "amount_cents": result.amount_cents,
            "code": result.code, "message": result.message,
        }
    return out


@admin_router.get("/bookings/{booking_id}")
def get_admin_booking(booking_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    return _one(db, booking_id)


class ChargeIn(BaseModel):
    # Minutes to bill, when fewer than booked. Absent = the booked length.
    minutes: Optional[int] = Field(default=None, ge=30, le=1440)


@admin_router.post("/bookings/{booking_id}/charge")
def charge_booking(
    booking_id: int, body: Optional[ChargeIn] = None,
    db: Session = Depends(get_db), admin: str = Depends(require_admin),
) -> dict:
    booking = _load(db, booking_id)
    try:
        _, result = consult.settle(db, booking, "charge", actor=admin, minutes=body.minutes if body else None)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, result)


@admin_router.post("/bookings/{booking_id}/no-show")
def no_show_booking(booking_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)) -> dict:
    booking = _load(db, booking_id)
    try:
        _, result = consult.settle(db, booking, "no_show", actor=admin)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, result)


@admin_router.post("/bookings/{booking_id}/waive")
def waive_booking(booking_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)) -> dict:
    booking = _load(db, booking_id)
    try:
        _, result = consult.settle(db, booking, "waive", actor=admin)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, result)


class CancelIn(BaseModel):
    note: Optional[str] = Field(default="", max_length=2000)


@admin_router.post("/bookings/{booking_id}/cancel")
def cancel_admin_booking(
    booking_id: int, body: Optional[CancelIn] = None,
    db: Session = Depends(get_db), admin: str = Depends(require_admin),
) -> dict:
    booking = _load(db, booking_id)
    try:
        consult.cancel_by_owner(db, booking, actor=admin, note=(body.note if body else "") or "")
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, None)


class RefundIn(BaseModel):
    # The ceiling is a guard on a typed number (one million dollars), not a price.
    cents: int = Field(ge=1, le=10**8)
    note: Optional[str] = Field(default="", max_length=300)


@admin_router.post("/bookings/{booking_id}/refund")
def refund_booking(
    booking_id: int, body: RefundIn, db: Session = Depends(get_db), admin: str = Depends(require_admin),
) -> dict:
    booking = _load(db, booking_id)
    try:
        _, result = consult.refund(db, booking, body.cents, actor=admin, note=body.note or "")
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, result)


class ReviewSettledIn(BaseModel):
    # The amount Stripe shows for the payment, in cents. It must be the
    # amount of the parked attempt.
    cents: int = Field(ge=1, le=10**8)
    # Which ledger row (`needs_review[].charge_id`), when more than one waits.
    charge_id: Optional[int] = None


class ReviewNotChargedIn(BaseModel):
    charge_id: Optional[int] = None


@admin_router.post("/bookings/{booking_id}/review-settled")
def review_settled(
    booking_id: int, body: ReviewSettledIn,
    db: Session = Depends(get_db), admin: str = Depends(require_admin),
) -> dict:
    """ "Paid in Stripe": the owner looked the parked payment up and it is
    there. Stripe is asked to confirm a completed payment of that amount for
    that attempt; then the ledger records it. 409 with a sentence when Stripe
    does not show it; 503 when Stripe cannot be asked."""
    booking = _load(db, booking_id)
    try:
        _, result = consult.resolve_review(
            db, booking, "settled", actor=admin, cents=body.cents, charge_id=body.charge_id)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, result)


@admin_router.post("/bookings/{booking_id}/review-not-charged")
def review_not_charged(
    booking_id: int, body: Optional[ReviewNotChargedIn] = None,
    db: Session = Depends(get_db), admin: str = Depends(require_admin),
) -> dict:
    """ "Not charged": the owner looked and Stripe has no such payment. Stripe
    is asked to confirm that nothing was taken or is on hold for that
    attempt; then it is closed and Charge can be tried again. 409 with a
    sentence when Stripe does show a payment (trying again would take the
    money twice); 503 when Stripe cannot be asked."""
    booking = _load(db, booking_id)
    try:
        _, result = consult.resolve_review(
            db, booking, "not_charged", actor=admin, charge_id=body.charge_id if body else None)
    except consult.ConsultError as exc:
        raise _refuse(exc) from exc
    return _with_action(db, booking_id, result)


@admin_router.get("/status")
def status_(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    return consult.system_status(db)


@admin_router.post("/tick")
def tick(db: Session = Depends(get_db), _who: str = Depends(require_admin_or_cron)) -> dict:
    """Everything that is due for consulting bookings: holds, the failed-hold
    follow-up, reminders, attendance, the owner's summary, the automatic
    outcome. Called every five minutes by the Render cron job
    (scripts/consult_tick_cron.py) with `X-Cron-Secret: <CRON_SECRET>`; the
    admin session or token works too. Safe to call at any time and as often
    as you like: a second call finds nothing left to do."""
    return consult_auto.run_tick(db)
