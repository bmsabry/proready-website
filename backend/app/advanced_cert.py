"""The paid, instructor-examined certification tier — a strict state machine.

    purchased → exam_passed → slots_proposed → scheduled → passed
                                   ↑              ↓
                              retake_pending ←────┘ ('not yet', once)
                                                  ↓
                                               failed

Invariants that matter:
  * Nothing in this module issues a certificate except `record_outcome`
    with result='pass', which only the admin endpoint calls.
  * The written examination is a product-level QuizItem set
    (item_set='advanced', module_id=0) graded by the same engine as the
    module quizzes; the answer key never leaves the server.
  * The Certificate of Completion is a prerequisite for the written exam,
    so "advanced" is literally true.

Fee waivers (2026-10): instead of paying, a candidate may ask the instructor
to waive the fee. The request is a row in 'waiver_requested'; only the
instructor's decision in the admin panel moves it on:

    waiver_requested ─ waive ──────────→ purchased, fee waived
                     ├ pay before the interview → purchased, fee due
                     │                   (interview locked until paid)
                     ├ ask them to pay ─→ waiver_declined
                     └ they pay by card → waiver_withdrawn (+ a paid row)
"""
from __future__ import annotations

import logging
import random
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import academy as svc
from . import certificates as certs
from .config import get_settings
from .emailer import (
    advanced_exam_passed_html,
    advanced_extra_payment_admin_html,
    advanced_fee_deferred_html,
    advanced_fee_paid_html,
    advanced_fee_waived_html,
    advanced_outcome_failed_html,
    advanced_outcome_retake_html,
    advanced_purchased_html,
    advanced_scheduled_html,
    advanced_slots_admin_html,
    advanced_waiver_declined_html,
    advanced_waiver_request_admin_html,
    send_email,
)
from .models import AdvancedCertification, Course, Learner, Order, Product, QuizAttempt, QuizItem

log = logging.getLogger(__name__)

TERMINAL = {"passed", "failed", "cancelled", "waiver_declined", "waiver_withdrawn"}
OPEN_STATES = {
    "purchased", "exam_passed", "slots_proposed", "scheduled", "retake_pending", "exam_failed"
}
WAIVER_PENDING = "waiver_requested"
RETAKE_STUDY_DAYS = 14

# The reasons a candidate can give, as they read on the request form, and as
# the instructor reads them in his email and admin panel.
WAIVER_REASONS = {
    "employer": "My employer is paying for it",
    "training_contract": "It is part of a training contract",
    "other": "Another reason (explained in my note)",
}
WAIVER_REASONS_ADMIN = {
    "employer": "Their employer is paying",
    "training_contract": "Part of a training contract",
    "other": "Another reason (see their note)",
}


def money(cents: int, currency: str = "usd") -> str:
    """'$300', '$300.50', '250 EUR' — how a fee reads in an email."""
    cents = int(cents or 0)
    amount = f"{cents / 100:,.0f}" if cents % 100 == 0 else f"{cents / 100:,.2f}"
    cur = (currency or "usd").upper()
    return f"${amount}" if cur == "USD" else f"{amount} {cur}"


def fee_due(row: AdvancedCertification | None) -> bool:
    """An open examination whose fee the instructor deferred and nobody paid."""
    return row is not None and row.status in OPEN_STATES and (row.fee_status or "") == "due"


def _log_fee(row: AdvancedCertification, event: str, by: str, note: str = "", amount_cents: int = 0) -> None:
    """Append one money event to the row's record. Reassigned, not appended
    in place, so the JSON column is seen as changed."""
    entry = {"at": datetime.now(timezone.utc).isoformat(), "event": event, "by": by or "", "note": note or ""}
    if amount_cents:
        entry["amount_cents"] = int(amount_cents)
    row.fee_log = [*(row.fee_log or []), entry]


def course_for_product(db: Session, product_code: str) -> Course | None:
    """The course whose Certification tab shows this product's candidates.
    Course codes are not product codes (micro-gas-turbine-design-2026-10 sells
    micro-gas-turbine-design). With several cohorts on one product, the
    newest: every one of them shows the same candidates."""
    if not product_code:
        return None
    return db.execute(
        select(Course)
        .where(Course.recorded_product_code == product_code)
        .order_by(Course.start_date.desc(), Course.id.desc())
    ).scalars().first()


def admin_cert_url(db: Session, product_code: str) -> str:
    """Deep link to that course's Certification tab, else to the admin
    panel's Certification page."""
    base = get_settings().SITE_URL.rstrip("/")
    course = course_for_product(db, product_code)
    if course is not None:
        return f"{base}/admin#courses/{course.code}/certification"
    return f"{base}/admin#certification"


def _notify_admin(db: Session, product: Product, *, subject: str, html: str, template: str) -> None:
    to = get_settings().ADMIN_NOTIFY_EMAIL
    if not to:
        log.warning("ADMIN_NOTIFY_EMAIL unset; not sending %r", subject)
        return
    send_email(
        to=to, subject=subject, html=html,
        db=db, scope_kind="product", scope_code=product.code,
        audience="admin", template=template,
    )


# -----------------------------------------------------------------------------
# Lookups + eligibility
# -----------------------------------------------------------------------------

def _rows(db: Session, learner_id: int, product_code: str) -> list[AdvancedCertification]:
    """Every row of this learner on this product, newest first."""
    return db.execute(
        select(AdvancedCertification)
        .where(
            AdvancedCertification.learner_id == learner_id,
            AdvancedCertification.product_code == product_code,
        )
        .order_by(AdvancedCertification.created_at.desc(), AdvancedCertification.id.desc())
    ).scalars().all()


def current(db: Session, learner: Learner | None, product_code: str) -> AdvancedCertification | None:
    """The learner's live journey for this product: the most recent open row,
    else a fee-waiver request still waiting, else the most recent closed row
    so the dashboard can show the outcome."""
    if learner is None:
        return None
    rows = _rows(db, learner.id, product_code)
    for r in rows:
        if r.status in OPEN_STATES:
            return r
    for r in rows:
        if r.status == WAIVER_PENDING:
            return r
    return rows[0] if rows else None


def exam_items(db: Session, product_code: str) -> list[QuizItem]:
    return db.execute(
        select(QuizItem)
        .where(
            QuizItem.product_code == product_code,
            QuizItem.item_set == "advanced",
        )
        .order_by(QuizItem.position)
    ).scalars().all()


def offered(db: Session, product: Product) -> bool:
    """Purchasable at all: switched on AND the written exam bank exists."""
    return bool(product.advanced_cert_enabled) and bool(exam_items(db, product.code))


def eligibility(db: Session, learner: Learner, product: Product) -> tuple[bool, str]:
    """May this learner buy the examined tier right now?"""
    if not offered(db, product):
        return False, "The instructor-examined certification is not offered for this course yet."
    if not svc.has_access(db, learner, product.code):
        return False, "You need access to the course first."
    completion = certs.get_certificate(db, learner, product.code, "completion")
    if completion is None or completion.status != "issued":
        return False, "Earn the Certificate of Completion first — it is the prerequisite."
    if certs.get_certificate(db, learner, product.code, "verified") is not None:
        return False, "You already hold the Certificate of Verified Competency for this course."
    row = current(db, learner, product.code)
    if row is not None and row.status in OPEN_STATES:
        return False, "Your examination is already in progress."
    # A fee-waiver request that is still waiting does not block: the
    # candidate may decide to pay after all, and paying closes the request.
    return True, ""


def waiver_check(db: Session, learner: Learner, product: Product) -> tuple[bool, str]:
    """May this learner ask the instructor to waive the fee right now?"""
    ok, why = eligibility(db, learner, product)
    if not ok:
        return False, why
    if (product.advanced_cert_price_cents or 0) <= 0:
        return False, "There is no fee to waive."
    rows = _rows(db, learner.id, product.code)
    if any(r.status == WAIVER_PENDING for r in rows):
        return False, "Your request is already with the instructor."
    if rows and rows[0].status == "waiver_declined":
        return False, "The instructor has answered your request. Register with payment to begin."
    return True, ""


# -----------------------------------------------------------------------------
# Creation (payment webhook / admin comp)
# -----------------------------------------------------------------------------

def _close_pending_waivers(db: Session, learner_id: int, product_code: str, how: str) -> None:
    """The candidate got in another way (paid, or the instructor comped
    them) while a fee-waiver request was waiting: that request is moot."""
    for r in _rows(db, learner_id, product_code):
        if r.status != WAIVER_PENDING:
            continue
        r.status = "waiver_withdrawn"
        r.waiver_decision = how
        r.waiver_decided_at = datetime.now(timezone.utc)
        _log_fee(
            r, "withdrawn", "",
            "Paid by card while the request waited." if how == "paid"
            else "Opened without charge while the request waited.",
        )


def create(
    db: Session,
    learner: Learner,
    product: Product,
    *,
    source: str,
    order_id: int | None,
    amount_cents: int,
    currency: str,
    send_welcome: bool = True,
    by: str = "",
) -> AdvancedCertification:
    """Idempotent on order_id — Stripe delivers at least once. `by` names
    the admin who comped the candidate, for the fee record."""
    if order_id is not None:
        existing = db.execute(
            select(AdvancedCertification).where(AdvancedCertification.order_id == order_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    paid = source != "manual"  # 'manual' is the instructor's comp: no charge
    row = AdvancedCertification(
        learner_id=learner.id,
        product_code=product.code,
        order_id=order_id,
        source=source,
        amount_cents=amount_cents,
        currency=currency,
        status="purchased",
        fee_status="paid" if paid else "waived",
    )
    _log_fee(row, "paid" if paid else "comped", source if paid else by, "", amount_cents if paid else 0)
    _close_pending_waivers(db, learner.id, product.code, "paid" if paid else "comped")
    db.add(row)
    db.commit()
    db.refresh(row)
    if send_welcome:
        settings = get_settings()
        # No price on a comp: the email then says the place is free rather
        # than thanking the candidate for a payment they never made.
        price = money(amount_cents, currency) if paid and amount_cents else ""
        send_email(
            to=learner.email,
            subject=f"Instructor-examined certification — {product.title}",
            html=advanced_purchased_html(
                learner.full_name or "", product.title,
                f"{settings.SITE_URL}/learn/{product.code}", price,
            ),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_purchased",
        )
    return row


# -----------------------------------------------------------------------------
# Fee waivers — the candidate asks, only the instructor decides
# -----------------------------------------------------------------------------

def request_waiver(
    db: Session, learner: Learner, product: Product, reason: str, note: str
) -> AdvancedCertification:
    """Record the candidate's request and tell the instructor. Opens nothing."""
    ok, why = waiver_check(db, learner, product)
    if not ok:
        raise ValueError(why)
    reason = reason if reason in WAIVER_REASONS else "other"
    note = (note or "").strip()[:1000]
    if reason == "other" and not note:
        raise ValueError("Tell the instructor a little about your situation in the note.")
    now = datetime.now(timezone.utc)
    row = AdvancedCertification(
        learner_id=learner.id,
        product_code=product.code,
        order_id=None,
        source="waiver",
        amount_cents=0,
        currency=product.currency,
        status=WAIVER_PENDING,
        waiver_reason=reason,
        waiver_note=note,
        waiver_requested_at=now,
    )
    _log_fee(row, "requested", learner.email, note)
    db.add(row)
    db.commit()
    db.refresh(row)

    completion = certs.get_certificate(db, learner, product.code, "completion")
    completion_line = (
        f"Certificate of Completion {completion.code}, issued "
        f"{svc._aware(completion.issued_at).strftime('%B %d, %Y')}"
        if completion is not None and completion.issued_at else ""
    )
    _notify_admin(
        db, product,
        subject=f"[Fee waiver] {learner.full_name or learner.email} — {product.title}",
        html=advanced_waiver_request_admin_html(
            learner_name=learner.full_name or "",
            learner_email=learner.email,
            course_title=product.title,
            price_display=money(product.advanced_cert_price_cents, product.currency),
            reason_label=WAIVER_REASONS_ADMIN[reason],
            note=note,
            completion_line=completion_line,
            request_id=row.id,
            review_url=admin_cert_url(db, product.code),
        ),
        template="advanced_waiver_request",
    )
    return row


def decide_waiver(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    decision: str, note: str, by: str,
) -> AdvancedCertification:
    """The instructor's answer to a waiting request.

      waive    the written examination opens at no charge
      defer    it opens now; the fee is due before the interview can be booked
      decline  nothing opens; the candidate is asked to register and pay
    """
    if decision not in ("waive", "defer", "decline"):
        raise ValueError("decision must be 'waive', 'defer' or 'decline'.")
    if row.status != WAIVER_PENDING:
        raise ValueError("This request has already been answered.")
    price = product.advanced_cert_price_cents or 0
    if decision == "defer" and price <= 0:
        raise ValueError("No price is set for the examined tier, so there is no fee to defer.")
    if decision in ("waive", "defer"):
        # Opening the examination must not create a second open journey.
        others = [r for r in _rows(db, learner.id, product.code)
                  if r.id != row.id and r.status in OPEN_STATES]
        if others:
            raise ValueError("This candidate already has an examination in progress.")
    note = (note or "").strip()[:2000]
    row.waiver_decided_at = datetime.now(timezone.utc)
    row.waiver_decided_by = by or ""
    row.waiver_admin_note = note
    settings = get_settings()
    course_url = f"{settings.SITE_URL}/learn/{product.code}"
    price_display = money(price, product.currency)

    if decision == "waive":
        row.status = "purchased"
        row.fee_status = "waived"
        row.amount_cents = 0
        row.waiver_decision = "waived"
        _log_fee(row, "waived", by, note)
        db.commit()
        send_email(
            to=learner.email,
            subject=f"Your examination fee is waived — {product.title}",
            html=advanced_fee_waived_html(
                learner.full_name or "", product.title, price_display, note, course_url,
                stage="exam",
            ),
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_fee_waived",
        )
    elif decision == "defer":
        row.status = "purchased"
        row.fee_status = "due"
        # The amount owed is fixed now, whatever the price later becomes.
        row.amount_cents = price
        row.currency = product.currency
        row.waiver_decision = "deferred"
        _log_fee(row, "deferred", by, note, price)
        db.commit()
        send_email(
            to=learner.email,
            subject=f"Your written examination is open — {product.title}",
            html=advanced_fee_deferred_html(
                learner.full_name or "", product.title, price_display, note, course_url,
            ),
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_fee_deferred",
        )
    else:
        row.status = "waiver_declined"
        row.waiver_decision = "declined"
        _log_fee(row, "declined", by, note)
        db.commit()
        send_email(
            to=learner.email,
            subject=f"About your fee-waiver request — {product.title}",
            html=advanced_waiver_declined_html(
                learner.full_name or "", product.title, price_display, note,
                f"{course_url}?advanced=start",
            ),
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_waiver_declined",
        )
    return row


def waive_fee(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    note: str, by: str,
) -> AdvancedCertification:
    """The instructor waives a fee he had earlier left due."""
    if not fee_due(row):
        raise ValueError("No fee is due on this examination.")
    note = (note or "").strip()[:2000]
    owed = row.amount_cents
    row.fee_status = "waived"
    row.amount_cents = 0
    _log_fee(row, "fee_waived", by, note, owed)
    db.commit()
    settings = get_settings()
    can_book, _why = can_propose(row)
    send_email(
        to=learner.email,
        subject=f"Your examination fee is waived — {product.title}",
        html=advanced_fee_waived_html(
            learner.full_name or "", product.title, money(owed, row.currency), note,
            f"{settings.SITE_URL}/learn/{product.code}",
            stage="book" if can_book else "continue",
        ),
        db=db, scope_kind="product", scope_code=product.code,
        template="advanced_fee_waived",
    )
    return row


def row_for_payment(
    db: Session, learner_id: int, product_code: str, row_id: str | int | None
) -> AdvancedCertification | None:
    """The open examination a payment belongs to, if there is one.

    A payment for a deferred fee names its row. Any other payment that
    arrives while the candidate already has an open examination (the
    instructor waived the fee while they were at checkout, say) lands on
    that examination rather than opening a second one."""
    if row_id:
        try:
            row = db.get(AdvancedCertification, int(row_id))
        except (TypeError, ValueError):
            row = None
        if (
            row is not None and row.learner_id == learner_id
            and row.product_code == product_code and row.status in OPEN_STATES
        ):
            return row
    for r in _rows(db, learner_id, product_code):
        if r.status in OPEN_STATES:
            return r
    return None


def record_fee_payment(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification, order: Order
) -> AdvancedCertification:
    """A payment reached an open examination. If the fee was due it is now
    paid; otherwise nothing was owed, and the instructor is told so he can
    refund it — that payment is kept off the row, so a refund of it never
    cancels the examination."""
    amount = int(order.amount_cents or 0)
    if fee_due(row):
        row.fee_status = "paid"
        row.order_id = order.id
        row.source = order.provider or "stripe"
        row.amount_cents = amount
        row.currency = (order.currency or row.currency or "usd").lower()
        _log_fee(row, "paid", row.source, f"order #{order.id}", amount)
        db.commit()
        settings = get_settings()
        can_book, _why = can_propose(row)
        send_email(
            to=learner.email,
            subject=f"Payment received — {product.title}",
            html=advanced_fee_paid_html(
                learner.full_name or "", product.title, money(amount, row.currency),
                f"{settings.SITE_URL}/learn/{product.code}", can_book=can_book,
            ),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_fee_paid",
        )
        return row
    state = {"waived": "waived", "paid": "paid"}.get(row.fee_status or "", "paid")
    _log_fee(row, "extra_payment", order.provider or "stripe",
             f"order #{order.id}; nothing was owed (fee already {state})", amount)
    db.commit()
    log.warning("Payment for order %s reached examination %s, which owed nothing", order.id, row.id)
    _notify_admin(
        db, product,
        subject=f"[Examination fee] Payment not owed — {learner.full_name or learner.email}",
        html=advanced_extra_payment_admin_html(
            learner_name=learner.full_name or "",
            learner_email=learner.email,
            course_title=product.title,
            amount_display=money(amount, order.currency or row.currency),
            fee_state=state,
            order_ref=f"#{order.id} ({order.provider_ref or 'no reference'})",
            admin_url=admin_cert_url(db, product.code),
        ),
        template="advanced_extra_payment",
    )
    return row


# -----------------------------------------------------------------------------
# Written examination
# -----------------------------------------------------------------------------

def exam_open(row: AdvancedCertification | None) -> bool:
    return row is not None and row.status == "purchased"


def _balanced_draw(
    items: list[QuizItem], target: int, avoid: frozenset[str] | set[str] = frozenset()
) -> list[QuizItem]:
    """Draw `target` items, spread across the competencies the bank is tagged with.

    Items carry the competency in `outcome_id`, so every paper has the same
    number from each one: the per-competency score of one attempt is then
    comparable with the next, which is what the instructor reads before the
    oral examination. Seats are allocated by largest remainder, so a competency
    with a bigger share of the bank gets a bigger share of the paper.

    Within each competency the questions in `avoid` (those the candidate has
    already sat) are drawn only when there are not enough unseen ones, so with
    a bank twice the size of the paper a retake shares no question with the
    first paper.
    """
    if target <= 0 or target >= len(items):
        return list(items)
    groups: dict[str, list[QuizItem]] = {}
    for it in items:
        groups.setdefault(it.outcome_id or "", []).append(it)
    total = len(items)
    exact = {g: len(v) * target / total for g, v in groups.items()}
    seats = {g: int(q) for g, q in exact.items()}
    short = target - sum(seats.values())
    for g in sorted(exact, key=lambda k: (exact[k] - seats[k], len(groups[k])), reverse=True)[:short]:
        seats[g] += 1
    rng = random.SystemRandom()
    drawn: list[QuizItem] = []
    for g, members in groups.items():
        want = min(seats.get(g, 0), len(members))
        fresh = [m for m in members if m.code not in avoid]
        if len(fresh) >= want:
            drawn.extend(rng.sample(fresh, want))
        else:
            seen = [m for m in members if m.code in avoid]
            drawn.extend(fresh + rng.sample(seen, want - len(fresh)))
    drawn.sort(key=lambda i: i.position)
    return drawn


def _codes_already_sat(db: Session, learner_id: int, product_code: str) -> set[str]:
    """Every question this candidate was served on a paper already handed in."""
    seen: set[str] = set()
    for responses in db.execute(
        select(QuizAttempt.responses).where(
            QuizAttempt.learner_id == learner_id,
            QuizAttempt.product_code == product_code,
            QuizAttempt.item_set == "advanced",
        )
    ).scalars():
        seen.update((responses or {}).keys())
    return seen


def served_items(db: Session, product_code: str, row: AdvancedCertification) -> list[QuizItem]:
    """The paper for the attempt that is open, drawing one if there is none yet."""
    pool = exam_items(db, product_code)
    if row.exam_item_codes:
        by_code = {i.code: i for i in pool}
        kept = [by_code[c] for c in row.exam_item_codes if c in by_code]
        if len(kept) == len(row.exam_item_codes):
            return kept
        # The bank was edited under an open paper; draw a fresh one rather than
        # grading the candidate on questions that no longer exist.
    drawn = _balanced_draw(
        pool, get_settings().ADVANCED_EXAM_SERVE_COUNT,
        avoid=_codes_already_sat(db, row.learner_id, product_code),
    )
    row.exam_item_codes = [i.code for i in drawn]
    db.commit()
    return drawn


def serve_count(db: Session, product_code: str) -> int:
    return min(get_settings().ADVANCED_EXAM_SERVE_COUNT, len(exam_items(db, product_code))) or 0


_COMPETENCY_CODE = re.compile(r"^C(\d+)$")


def best_attempt(db: Session, learner_id: int, product_code: str) -> QuizAttempt | None:
    return db.execute(
        select(QuizAttempt)
        .where(
            QuizAttempt.learner_id == learner_id,
            QuizAttempt.product_code == product_code,
            QuizAttempt.item_set == "advanced",
        )
        .order_by(QuizAttempt.score_pct.desc(), QuizAttempt.id.desc())
    ).scalars().first()


def competency_breakdown(db: Session, product: Product, attempt: QuizAttempt | None) -> list[dict]:
    """Score per certificate competency for one attempt, weakest first.

    This is the diagnosis the examined tier exists to produce: the instructor
    sees which competency a candidate is thin in before the oral examination,
    and the candidate sees the same breakdown once the outcome is recorded.
    """
    if attempt is None:
        return []
    items = exam_items(db, product.code)
    # Only a bank whose questions are tagged to the certificate's competencies
    # (C1, C2, ...) can produce this diagnosis. An older bank tagged to module
    # outcomes gets no breakdown rather than a list of one-question groups.
    if not any(_COMPETENCY_CODE.match(i.outcome_id or "") for i in items):
        return []
    pool = {i.code: i for i in items}
    labels = certs.course_competencies(db, product)
    tally: dict[str, list[int]] = {}
    for code, detail in (attempt.responses or {}).items():
        item = pool.get(code)
        if item is None or not isinstance(detail, dict) or detail.get("correct") is None:
            continue
        slot = tally.setdefault(item.outcome_id or "", [0, 0])
        slot[1] += 1
        if detail.get("correct"):
            slot[0] += 1
    rows = []
    for key, (correct, total) in tally.items():
        label = key
        match = _COMPETENCY_CODE.match(key or "")
        if match and 1 <= int(match.group(1)) <= len(labels):
            label = labels[int(match.group(1)) - 1]
        rows.append({
            "id": key,
            "label": label,
            "correct": correct,
            "total": total,
            "pct": round(100.0 * correct / total, 1) if total else 0.0,
        })
    rows.sort(key=lambda r: (r["pct"], r["id"]))
    return rows


def grade_exam(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification, responses: dict
) -> QuizAttempt:
    settings = get_settings()
    items = served_items(db, product.code, row)
    detail: dict = {}
    auto_total = auto_correct = 0
    for item in items:
        raw = responses.get(item.code)
        verdict = svc.grade_item(item, raw)
        if verdict is not None:
            auto_total += 1
            if verdict:
                auto_correct += 1
        detail[item.code] = {"response": raw, "correct": verdict, "kind": item.kind}
    score = round(100.0 * auto_correct / auto_total, 1) if auto_total else 0.0
    passed = auto_total > 0 and score >= settings.ADVANCED_EXAM_THRESHOLD_PCT

    attempt = QuizAttempt(
        learner_id=learner.id,
        module_id=0,
        product_code=product.code,
        item_set="advanced",
        score_pct=score,
        passed=passed,
        auto_total=auto_total,
        auto_correct=auto_correct,
        responses=detail,
    )
    db.add(attempt)
    # The paper is handed in: the next attempt draws its own.
    row.exam_item_codes = []
    row.exam_attempts = (row.exam_attempts or 0) + 1
    row.exam_best_pct = max(row.exam_best_pct or 0.0, score)
    if passed:
        row.status = "exam_passed"
        row.exam_passed_at = datetime.now(timezone.utc)
    elif row.exam_attempts >= settings.ADVANCED_EXAM_MAX_ATTEMPTS:
        row.status = "exam_failed"
    db.commit()
    db.refresh(attempt)

    if passed:
        send_email(
            to=learner.email,
            subject=f"Written examination passed — {product.title}",
            html=advanced_exam_passed_html(
                learner.full_name or "", product.title, score,
                f"{settings.SITE_URL}/learn/{product.code}",
                fee_due_display=money(row.amount_cents, row.currency) if fee_due(row) else "",
            ),
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_exam_passed",
        )
    return attempt


# -----------------------------------------------------------------------------
# Scheduling
# -----------------------------------------------------------------------------

def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def when_lines(at: datetime, tz_name: str) -> list[str]:
    """Human lines for one instant: learner's zone (if known), Eastern, UTC."""
    at = svc._aware(at)
    lines = []
    seen = set()
    for label, zone in (
        (tz_name, _zone(tz_name)),
        ("US Eastern", ZoneInfo("America/New_York")),
        ("UTC", timezone.utc),
    ):
        if zone is None:
            continue
        local = at.astimezone(zone)
        key = local.strftime("%Y-%m-%d %H:%M %z")
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{local.strftime('%A, %B %d, %Y at %H:%M')} ({label})")
    return lines


def can_propose(row: AdvancedCertification | None) -> tuple[bool, str]:
    if row is None:
        return False, "No examination in progress."
    if row.status in ("exam_passed", "slots_proposed"):
        ok, why = True, ""
    elif row.status == "retake_pending":
        after = row.retake_after or date.today()
        if date.today() >= after:
            ok, why = True, ""
        else:
            return False, f"Your re-examination can be proposed on or after {after.strftime('%B %d, %Y')}."
    else:
        return False, "Not at the scheduling step."
    if fee_due(row):
        # "Pay before the interview": the instructor let them start unpaid.
        return False, (
            f"Pay the {money(row.amount_cents, row.currency)} examination fee to "
            "book your oral examination."
        )
    return ok, why


def propose_slots(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    slots: list[datetime], tz_name: str, note: str,
) -> AdvancedCertification:
    now = datetime.now(timezone.utc)
    clean = sorted({svc._aware(s) for s in slots if svc._aware(s) > now + timedelta(hours=12)})
    if len(clean) < 1:
        raise ValueError("Propose at least one window at least 12 hours from now.")
    row.proposed_slots = [s.isoformat() for s in clean[:5]]
    row.learner_timezone = tz_name if _zone(tz_name) else ""
    row.learner_note = (note or "").strip()[:1000]
    row.status = "slots_proposed"
    db.commit()

    settings = get_settings()
    lines = []
    for iso in row.proposed_slots:
        lines.append(" / ".join(when_lines(datetime.fromisoformat(iso), row.learner_timezone)))
    send_email(
        to=settings.ADMIN_NOTIFY_EMAIL,
        subject=f"[Oral exam] {learner.full_name or learner.email} — {product.title}",
        html=advanced_slots_admin_html(
            learner.full_name or "", learner.email, product.title, lines, row.learner_note,
            # The course's own tab: a course code is not the product code.
            admin_cert_url(db, product.code),
        ),
        db=db, scope_kind="product", scope_code=product.code,
        template="advanced_slots_admin",
    )
    return row


def _ics(row: AdvancedCertification, product: Product, learner: Learner, minutes: int) -> str:
    start = svc._aware(row.scheduled_at)
    end = start + timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%SZ"
    what = "re-examination" if row.interview_no > 1 else "oral examination"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ProReadyEngineer//Certification//EN",
        "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:advcert-{row.id}-{row.interview_no}@proreadyengineer.com",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.astimezone(timezone.utc).strftime(fmt)}",
        f"DTEND:{end.astimezone(timezone.utc).strftime(fmt)}",
        f"SUMMARY:ProReadyEngineer {what} — {product.title}",
        f"DESCRIPTION:Live one-on-one {what} with the instructor. Meeting link: {row.meeting_url}",
        f"LOCATION:{row.meeting_url}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def schedule(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    at: datetime, meeting_url: str,
) -> AdvancedCertification:
    if row.status not in ("slots_proposed", "exam_passed", "retake_pending", "scheduled"):
        raise ValueError("This candidate is not at the scheduling step.")
    if fee_due(row):
        raise ValueError(
            "The examination fee is still due. Waive it, or wait for the payment, "
            "before booking the interview."
        )
    row.scheduled_at = svc._aware(at)
    row.meeting_url = (meeting_url or "").strip()[:500]
    row.status = "scheduled"
    db.commit()

    settings = get_settings()
    minutes = settings.ADVANCED_INTERVIEW_MINUTES
    import base64  # noqa: PLC0415

    ics = base64.b64encode(_ics(row, product, learner, minutes).encode()).decode()
    send_email(
        to=learner.email,
        subject=f"Your oral examination is booked — {product.title}",
        html=advanced_scheduled_html(
            learner.full_name or "", product.title,
            when_lines(row.scheduled_at, row.learner_timezone),
            row.meeting_url, minutes, row.interview_no,
            f"{settings.SITE_URL}/learn/{product.code}",
        ),
        bcc=settings.ADMIN_NOTIFY_EMAIL or None,
        db=db, scope_kind="product", scope_code=product.code,
        template="advanced_scheduled",
        attachments=[{"filename": "oral-examination.ics", "content": ics}],
    )
    return row


def reopen_scheduling(db: Session, row: AdvancedCertification) -> AdvancedCertification:
    """Admin: the booked time fell through — ask the learner for new windows."""
    if row.status != "scheduled":
        raise ValueError("Nothing is scheduled.")
    row.status = "retake_pending" if row.interview_no > 1 else "exam_passed"
    if row.interview_no > 1:
        row.retake_after = date.today()
    row.scheduled_at = None
    row.meeting_url = ""
    row.proposed_slots = []
    db.commit()
    return row


# -----------------------------------------------------------------------------
# Outcome — the only path to a verified certificate
# -----------------------------------------------------------------------------

def record_outcome(
    db: Session, learner: Learner, product: Product, row: AdvancedCertification,
    result: str, note: str, retake_after: date | None = None,
):
    if row.status != "scheduled":
        raise ValueError("Record an outcome only for a scheduled examination.")
    settings = get_settings()
    row.outcome_note = (note or "").strip()
    row.outcome_at = datetime.now(timezone.utc)
    exam_day = svc._aware(row.scheduled_at).date() if row.scheduled_at else date.today()

    if result == "pass":
        cert = certs.issue_verified(
            db, learner, product,
            exam_date=exam_day, exam_minutes=settings.ADVANCED_INTERVIEW_MINUTES,
        )
        row.status = "passed"
        row.certificate_id = cert.id
        db.commit()
        return cert

    if result == "retake":
        if row.interview_no >= 2:
            raise ValueError("The complimentary re-examination has already been used.")
        row.status = "retake_pending"
        row.interview_no = 2
        row.retake_after = retake_after or (date.today() + timedelta(days=RETAKE_STUDY_DAYS))
        row.proposed_slots = []
        row.scheduled_at = None
        row.meeting_url = ""
        db.commit()
        send_email(
            to=learner.email,
            subject=f"Your oral examination — {product.title}",
            html=advanced_outcome_retake_html(
                learner.full_name or "", product.title,
                row.retake_after.strftime("%B %d, %Y"),
                f"{settings.SITE_URL}/learn/{product.code}",
            ),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_retake",
        )
        return None

    if result == "fail":
        row.status = "failed"
        db.commit()
        send_email(
            to=learner.email,
            subject=f"Your re-examination — {product.title}",
            html=advanced_outcome_failed_html(learner.full_name or "", product.title),
            bcc=settings.ADMIN_NOTIFY_EMAIL or None,
            db=db, scope_kind="product", scope_code=product.code,
            template="advanced_failed",
        )
        return None

    raise ValueError("result must be 'pass', 'retake' or 'fail'.")


def reset_exam(db: Session, row: AdvancedCertification) -> AdvancedCertification:
    """Admin: give the written exam back after the attempt cap."""
    if row.status not in ("exam_failed", "purchased"):
        raise ValueError("The written examination is not what is blocking this candidate.")
    row.status = "purchased"
    row.exam_attempts = 0
    db.commit()
    return row


def cancel(db: Session, row: AdvancedCertification, note: str) -> AdvancedCertification:
    if row.status in TERMINAL:
        raise ValueError("Already closed.")
    if row.status == WAIVER_PENDING:
        # A request is answered, not cancelled: the candidate must hear back.
        raise ValueError("Answer the fee-waiver request instead: waive, pay before the interview, or ask them to pay.")
    row.status = "cancelled"
    row.outcome_note = (note or "").strip()
    row.outcome_at = datetime.now(timezone.utc)
    db.commit()
    return row


# -----------------------------------------------------------------------------
# Serialisers
# -----------------------------------------------------------------------------

def learner_out(db: Session, learner: Learner, product: Product, row: AdvancedCertification | None) -> dict:
    settings = get_settings()
    ok, reason = eligibility(db, learner, product)
    can_ask, _ask_why = waiver_check(db, learner, product)
    declined = row is not None and row.status == "waiver_declined"
    out = {
        "offered": offered(db, product),
        "price_cents": product.advanced_cert_price_cents,
        "currency": product.currency,
        "interview_minutes": settings.ADVANCED_INTERVIEW_MINUTES,
        "exam_threshold": settings.ADVANCED_EXAM_THRESHOLD_PCT,
        "exam_max_attempts": settings.ADVANCED_EXAM_MAX_ATTEMPTS,
        "exam_item_count": serve_count(db, product.code),
        "exam_bank_size": len(exam_items(db, product.code)),
        "can_purchase": ok,
        "purchase_blocked_reason": reason,
        "competencies": certs.course_competencies(db, product),
        # The "Request a fee waiver" link under the register button.
        "waiver": {
            "can_request": can_ask,
            "reasons": [{"key": k, "label": v} for k, v in WAIVER_REASONS.items()],
            # The last request was answered "please pay": the course page
            # says so above the register button, with the instructor's words.
            "declined": declined,
            "message": row.waiver_admin_note if declined else "",
        },
        "state": None,
    }
    # A closed request is not a journey: the page offers registration again.
    if row is None or row.status in ("waiver_declined", "waiver_withdrawn"):
        return out
    can_prop, why = can_propose(row)
    # The candidate sees their own competency breakdown once the journey has
    # reached an outcome — never while a paper or an interview is still open.
    show_breakdown = row.status in ("passed", "failed", "exam_failed")
    out["state"] = {
        "id": row.id,
        "status": row.status,
        "exam_attempts": row.exam_attempts,
        "exam_best_pct": row.exam_best_pct,
        "exam_open": exam_open(row),
        "can_propose": can_prop,
        "propose_blocked_reason": why,
        "proposed_slots": list(row.proposed_slots or []),
        "learner_timezone": row.learner_timezone,
        "scheduled_at": row.scheduled_at,
        "scheduled_lines": when_lines(row.scheduled_at, row.learner_timezone) if row.scheduled_at else [],
        "meeting_url": row.meeting_url if row.status == "scheduled" else "",
        "interview_no": row.interview_no,
        "retake_after": row.retake_after,
        "created_at": row.created_at,
        # '' (settled at registration) | 'paid' | 'waived' | 'due'
        "fee_status": row.fee_status or "",
        "fee_due_cents": row.amount_cents if fee_due(row) else 0,
        "waiver_reason": row.waiver_reason or "",
        "waiver_requested_at": row.waiver_requested_at,
        "exam_breakdown": competency_breakdown(
            db, product, best_attempt(db, learner.id, product.code)
        ) if show_breakdown else [],
    }
    return out


def admin_out(db: Session, row: AdvancedCertification) -> dict:
    learner = db.get(Learner, row.learner_id)
    cert = db.get(certs.Certificate, row.certificate_id) if row.certificate_id else None
    product = db.execute(
        select(Product).where(Product.code == row.product_code)
    ).scalars().first()
    return {
        "id": row.id,
        "learner_id": row.learner_id,
        "email": learner.email if learner else "",
        "full_name": learner.full_name if learner else "",
        "product_code": row.product_code,
        "status": row.status,
        "source": row.source,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "exam_attempts": row.exam_attempts,
        "exam_best_pct": row.exam_best_pct,
        "exam_passed_at": row.exam_passed_at,
        # Read this before the oral examination: weakest competency first.
        "exam_breakdown": competency_breakdown(
            db, product, best_attempt(db, row.learner_id, row.product_code)
        ) if product else [],
        "proposed_slots": [
            {"iso": iso, "lines": when_lines(datetime.fromisoformat(iso), row.learner_timezone)}
            for iso in (row.proposed_slots or [])
        ],
        "learner_timezone": row.learner_timezone,
        "learner_note": row.learner_note,
        "scheduled_at": row.scheduled_at,
        "scheduled_lines": when_lines(row.scheduled_at, row.learner_timezone) if row.scheduled_at else [],
        "meeting_url": row.meeting_url,
        "interview_no": row.interview_no,
        "retake_after": row.retake_after,
        "outcome_note": row.outcome_note,
        "outcome_at": row.outcome_at,
        "certificate_code": cert.code if cert else "",
        "fee_status": row.fee_status or "",
        "fee_due": fee_due(row),
        "waiver_reason": row.waiver_reason or "",
        "waiver_reason_label": WAIVER_REASONS_ADMIN.get(row.waiver_reason or "", ""),
        "waiver_note": row.waiver_note,
        "waiver_requested_at": row.waiver_requested_at,
        "waiver_decision": row.waiver_decision,
        "waiver_decided_at": row.waiver_decided_at,
        "waiver_decided_by": row.waiver_decided_by,
        "waiver_admin_note": row.waiver_admin_note,
        "fee_log": list(row.fee_log or []),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
