"""Academy service layer: entitlements, mastery gates, progress, grading.

Every rule that decides "may this learner see this?" or "has this learner
passed?" lives here rather than in the route handlers, so there is exactly
one place to audit and the same answer is given to the API, the admin
dashboard, and the AI tools.
"""
from __future__ import annotations

import math
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    Certificate,
    Enrollment,
    Learner,
    Lesson,
    LessonProgress,
    Module,
    QuizAttempt,
    QuizItem,
)

# A lesson counts as complete once the learner has watched this share of it.
# Below 1.0 because trailing credits/silence shouldn't strand a learner at 97%.
COMPLETION_RATIO = 0.92


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres hands back aware ones."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# -----------------------------------------------------------------------------
# Entitlements
# -----------------------------------------------------------------------------

def active_enrollment(
    db: Session, learner: Learner | None, product_code: str
) -> Enrollment | None:
    """The live access grant for this learner+product, or None.

    A row is live when status='active' AND it hasn't expired. A purchase
    writes expires_at=NULL, which is what "lifetime access" means here.
    """
    if learner is None:
        return None
    row = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id,
            Enrollment.product_code == product_code,
            Enrollment.status == "active",
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    expires = _aware(row.expires_at)
    if expires is not None and expires <= datetime.now(timezone.utc):
        return None
    return row


def any_active_enrollment(db: Session, learner: Learner | None) -> bool:
    """True when this learner holds live access to anything at all.

    Used where the question is "does this account already carry something
    worth stealing?" rather than "can they open this particular course."
    """
    if learner is None:
        return False
    rows = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id,
            Enrollment.status == "active",
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        expires = _aware(row.expires_at)
        if expires is None or expires > now:
            return True
    return False


def is_owner(learner: Learner | None) -> bool:
    """Owner accounts bypass every paywall and gate.

    The OWNER_EMAILS setting is the only source of truth, deliberately. An
    earlier version also honoured the is_staff column, which made the grant
    impossible to take back: once a row had been flagged, dropping the address
    from the config left the bypass in place forever. is_staff is now a cache
    of this answer (see sync_owner_flag), never an independent grant.

    Keyed on an email that is already proven — a magic link had to be opened,
    or a password set on that address from a session. Typing the owner's email
    at checkout grants nothing, because purchases are provisioned from Stripe's
    verified email in the webhook, never from client input.
    """
    if learner is None:
        return False
    return learner.email.lower() in get_settings().owner_emails_list


def sync_owner_flag(db: Session, learner: Learner) -> Learner:
    """Make the stored is_staff column agree with the config list.

    Called on every path that authenticates someone, so the admin table and
    any query against the column tell the truth in both directions — promoting
    a newly-added owner and demoting one who has been removed.
    """
    should_be = is_owner(learner)
    if learner.is_staff != should_be:
        learner.is_staff = should_be
        db.commit()
        db.refresh(learner)
    return learner


# Kept so older call sites keep working; the behaviour is now two-way.
promote_if_owner = sync_owner_flag


def has_access(db: Session, learner: Learner | None, product_code: str) -> bool:
    if is_owner(learner):
        return True
    return active_enrollment(db, learner, product_code) is not None


def grant_enrollment(
    db: Session,
    learner: Learner,
    product_code: str,
    *,
    source: str = "stripe",
    order_id: int | None = None,
    note: str = "",
) -> Enrollment:
    """Create or reactivate an access grant. Idempotent by (learner, product).

    Re-granting a revoked enrollment flips it back to active rather than
    inserting a duplicate, so a refund-then-repurchase leaves one clean row.
    """
    existing = db.execute(
        select(Enrollment).where(
            Enrollment.learner_id == learner.id,
            Enrollment.product_code == product_code,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "active"
        existing.expires_at = None
        existing.source = source
        if order_id is not None:
            existing.order_id = order_id
        if note:
            existing.note = note
        db.commit()
        return existing

    row = Enrollment(
        learner_id=learner.id,
        product_code=product_code,
        source=source,
        order_id=order_id,
        status="active",
        expires_at=None,
        note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_learner(db: Session, email: str, full_name: str = "") -> Learner:
    """Find-or-create a learner by email. Email is normalised to lowercase."""
    email_norm = email.lower().strip()
    learner = db.execute(
        select(Learner).where(Learner.email == email_norm)
    ).scalar_one_or_none()
    if learner is None:
        learner = Learner(email=email_norm, full_name=(full_name or "").strip())
        db.add(learner)
        db.commit()
        db.refresh(learner)
    elif full_name and not learner.full_name:
        learner.full_name = full_name.strip()
        db.commit()
    return promote_if_owner(db, learner)


# -----------------------------------------------------------------------------
# Progress
# -----------------------------------------------------------------------------

def progress_map(db: Session, learner: Learner | None, lesson_ids: list[int]) -> dict:
    if learner is None or not lesson_ids:
        return {}
    rows = db.execute(
        select(LessonProgress).where(
            LessonProgress.learner_id == learner.id,
            LessonProgress.lesson_id.in_(lesson_ids),
        )
    ).scalars().all()
    return {r.lesson_id: r for r in rows}


def record_progress(
    db: Session, learner: Learner, lesson: Lesson, position_s: int, watched_delta_s: int
) -> LessonProgress:
    """Apply one player heartbeat.

    `watched_delta_s` is clamped so a client can't fabricate completion by
    posting a huge delta: the most a single heartbeat can add is 60s, and
    total watched time never exceeds the lesson's own duration.
    """
    row = db.execute(
        select(LessonProgress).where(
            LessonProgress.learner_id == learner.id,
            LessonProgress.lesson_id == lesson.id,
        )
    ).scalar_one_or_none()
    if row is None:
        # Column defaults are applied by the database at INSERT, so a freshly
        # constructed instance still has None in these fields until flush.
        # Seed them here rather than reading None a line later.
        row = LessonProgress(
            learner_id=learner.id, lesson_id=lesson.id, position_s=0, watched_s=0
        )
        db.add(row)

    delta = max(0, min(int(watched_delta_s), 60))
    row.watched_s = (row.watched_s or 0) + delta
    if lesson.duration_s:
        row.watched_s = min(row.watched_s, lesson.duration_s)
    row.position_s = max(0, int(position_s))

    if row.completed_at is None and lesson_is_complete(lesson, row):
        row.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(row)
    return row


def lesson_is_complete(lesson: Lesson, prog: LessonProgress | None) -> bool:
    if prog is None:
        return False
    if prog.completed_at is not None:
        return True
    if lesson.duration_s <= 0:
        # Non-timed lessons (decks, labs, readings) complete on first open.
        return prog.watched_s > 0
    return prog.watched_s >= math.floor(lesson.duration_s * COMPLETION_RATIO)


# -----------------------------------------------------------------------------
# Mastery gates
# -----------------------------------------------------------------------------

def best_attempt(
    db: Session, learner: Learner | None, module_id: int, item_set: str
) -> QuizAttempt | None:
    if learner is None:
        return None
    rows = db.execute(
        select(QuizAttempt).where(
            QuizAttempt.learner_id == learner.id,
            QuizAttempt.module_id == module_id,
            QuizAttempt.item_set == item_set,
        )
    ).scalars().all()
    if not rows:
        return None
    return max(rows, key=lambda a: (a.passed, a.score_pct))


def module_has_items(db: Session, module_id: int, item_set: str) -> bool:
    row = db.execute(
        select(QuizItem.id).where(
            QuizItem.module_id == module_id, QuizItem.item_set == item_set
        ).limit(1)
    ).first()
    return row is not None


def module_gate_passed(db: Session, learner: Learner | None, module: Module) -> bool:
    """Has this learner cleared the module's formative gate?

    A module with no formative items cannot gate anything, so it falls back
    to "did you finish its lessons" — otherwise seeding a module without a
    quiz would silently lock the rest of the course forever.
    """
    if learner is None:
        return False
    if module_has_items(db, module.id, "formative"):
        attempt = best_attempt(db, learner, module.id, "formative")
        return bool(attempt and attempt.passed)

    lessons = db.execute(
        select(Lesson).where(Lesson.module_id == module.id)
    ).scalars().all()
    if not lessons:
        return True
    prog = progress_map(db, learner, [l.id for l in lessons])
    return all(lesson_is_complete(l, prog.get(l.id)) for l in lessons)


def module_unlocked(db: Session, learner: Learner | None, module: Module) -> bool:
    """Is this one module open to this learner?

    Sequential mastery: every module before it must have its gate passed.
    Kept separate from `course_state` because the progress heartbeat calls
    this on every beat, and building the entire course view (with all
    lessons serialized) just to answer one boolean was the hot path.
    """
    if not has_access(db, learner, module.product_code):
        return False
    if is_owner(learner):
        return True
    earlier = db.execute(
        select(Module).where(
            Module.product_code == module.product_code,
            Module.position < module.position,
        )
    ).scalars().all()
    return all(module_gate_passed(db, learner, m) for m in earlier)


def course_state(db: Session, learner: Learner | None, product_code: str) -> list[dict]:
    """The learner's whole course view: modules, lock state, progress.

    Locking is strictly sequential — module N unlocks when N-1's gate is
    passed — which is the mastery model signed off in the curriculum draft.
    Without an enrollment, everything except preview lessons reads as locked.
    """
    settings = get_settings()
    entitled = has_access(db, learner, product_code)
    owner = is_owner(learner)

    modules = db.execute(
        select(Module)
        .where(Module.product_code == product_code)
        .order_by(Module.position)
    ).scalars().all()

    all_lessons = db.execute(
        select(Lesson)
        .where(Lesson.module_id.in_([m.id for m in modules] or [0]))
        .order_by(Lesson.position)
    ).scalars().all()
    by_module: dict[int, list[Lesson]] = {}
    for l in all_lessons:
        by_module.setdefault(l.module_id, []).append(l)

    prog = progress_map(db, learner, [l.id for l in all_lessons])

    out: list[dict] = []
    previous_passed = True  # module 1 is always open
    for module in modules:
        lessons = by_module.get(module.id, [])
        unlocked = entitled and (previous_passed or owner)

        done = sum(1 for l in lessons if lesson_is_complete(l, prog.get(l.id)))
        watched = sum(
            (prog[l.id].watched_s if l.id in prog else 0) for l in lessons
        )
        total_s = sum(l.duration_s for l in lessons)

        formative = best_attempt(db, learner, module.id, "formative")
        summative = best_attempt(db, learner, module.id, "summative")

        out.append(
            {
                "id": module.id,
                "code": module.code,
                "title": module.title,
                "summary": module.summary,
                "position": module.position,
                "hours": module.hours,
                "objectives": module.objectives or [],
                "topics": module.topics or [],
                "quiz_app_url": module.quiz_app_url if unlocked else "",
                "unlocked": unlocked,
                "lesson_count": len(lessons),
                "lessons_completed": done,
                "duration_s": total_s,
                "watched_s": watched,
                "percent": round(100.0 * done / len(lessons), 1) if lessons else 0.0,
                "has_formative": module_has_items(db, module.id, "formative"),
                "has_summative": module_has_items(db, module.id, "summative"),
                "formative_score": formative.score_pct if formative else None,
                "formative_passed": bool(formative and formative.passed),
                "summative_score": summative.score_pct if summative else None,
                "summative_passed": bool(summative and summative.passed),
                "mastery_threshold": settings.MASTERY_THRESHOLD_PCT,
                "lessons": [
                    {
                        "id": l.id,
                        "code": l.code,
                        "title": l.title,
                        "kind": l.kind,
                        "position": l.position,
                        "duration_s": l.duration_s,
                        "is_preview": l.is_preview,
                        "playable": bool(l.video_uid) or l.kind != "video",
                        # A preview lesson stays open to everyone; that is the
                        # free sample the sales page links to.
                        "accessible": unlocked or l.is_preview,
                        "position_s": prog[l.id].position_s if l.id in prog else 0,
                        "watched_s": prog[l.id].watched_s if l.id in prog else 0,
                        "completed": lesson_is_complete(l, prog.get(l.id)),
                    }
                    for l in lessons
                ],
            }
        )
        previous_passed = module_gate_passed(db, learner, module)

    return out


def lesson_accessible(
    db: Session, learner: Learner | None, lesson: Lesson
) -> tuple[bool, str]:
    """Can this learner open this lesson? Returns (ok, reason_if_not).

    Two independent checks, both of which must pass: the entitlement (did
    you pay) and the sequential gate (did you clear the previous module).
    Preview lessons bypass both.
    """
    if lesson.is_preview:
        return True, ""

    module = db.get(Module, lesson.module_id)
    if module is None:
        return False, "This lesson is not part of an active course."

    if not has_access(db, learner, module.product_code):
        return False, "This lesson requires an enrollment."

    if not module_unlocked(db, learner, module):
        return False, "Finish the previous module to unlock this one."
    return True, ""


# -----------------------------------------------------------------------------
# Grading
# -----------------------------------------------------------------------------

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _grade_numeric(response, answer: dict) -> bool | None:
    """Compare a numeric response against value ± tolerance.

    Accepts a bare number or a string with units ("335 m/s") — engineers
    type units, and rejecting them would be a UX trap, not a knowledge test.
    """
    if response is None or response == "":
        return False
    if isinstance(response, (int, float)):
        value = float(response)
    else:
        match = _NUM_RE.search(str(response).replace(",", ""))
        if not match:
            return False
        value = float(match.group())

    target = answer.get("value")
    if target is None:
        return None
    target = float(target)

    if "tolerance_pct" in answer and answer["tolerance_pct"] is not None:
        tol = abs(target) * float(answer["tolerance_pct"]) / 100.0
    elif "tolerance" in answer and answer["tolerance"] is not None:
        tol = abs(float(answer["tolerance"]))
    else:
        tol = abs(target) * 0.02
    return abs(value - target) <= tol


def _grade_match(response, answer: dict) -> bool | None:
    pairs = answer.get("pairs")
    if not pairs:
        return None
    if not isinstance(response, dict):
        return False
    return all(str(response.get(str(left), "")).strip() == str(right).strip()
               for left, right in pairs)


def grade_item(item: QuizItem, response) -> bool | None:
    """Grade one response. Returns True/False, or None if not auto-gradable.

    `None` is not a failure — short-answer items are held for rubric grading
    and excluded from the gate arithmetic entirely.
    """
    if item.kind == "mcq":
        key = item.answer.get("key") if isinstance(item.answer, dict) else None
        if key is None:
            return None
        return str(response).strip().upper() == str(key).strip().upper()
    if item.kind == "numeric":
        return _grade_numeric(response, item.answer or {})
    if item.kind == "match":
        return _grade_match(response, item.answer or {})
    return None  # 'short' — rubric-graded elsewhere


def grade_submission(
    db: Session,
    learner: Learner,
    module: Module,
    item_set: str,
    responses: dict,
) -> QuizAttempt:
    """Grade a whole set server-side and persist the attempt.

    The score is computed over auto-gradable items only. Passing requires
    meeting the configured mastery threshold; a set with no auto-gradable
    items (all short-answer) passes on submission, since blocking on an
    ungraded essay would deadlock the course.
    """
    settings = get_settings()
    items = db.execute(
        select(QuizItem)
        .where(QuizItem.module_id == module.id, QuizItem.item_set == item_set)
        .order_by(QuizItem.position)
    ).scalars().all()

    detail: dict = {}
    auto_total = 0
    auto_correct = 0
    for item in items:
        raw = responses.get(item.code)
        verdict = grade_item(item, raw)
        if verdict is not None:
            auto_total += 1
            if verdict:
                auto_correct += 1
        detail[item.code] = {
            "response": raw,
            "correct": verdict,
            "kind": item.kind,
        }

    score = round(100.0 * auto_correct / auto_total, 1) if auto_total else 100.0
    passed = score >= settings.MASTERY_THRESHOLD_PCT

    attempt = QuizAttempt(
        learner_id=learner.id,
        module_id=module.id,
        item_set=item_set,
        score_pct=score,
        passed=passed,
        auto_total=auto_total,
        auto_correct=auto_correct,
        responses=detail,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


# -----------------------------------------------------------------------------
# Certificates
# -----------------------------------------------------------------------------

def course_complete(db: Session, learner: Learner, product_code: str) -> bool:
    """Every module gate cleared, and every summative set that exists passed."""
    modules = db.execute(
        select(Module).where(Module.product_code == product_code)
    ).scalars().all()
    if not modules:
        return False
    for module in modules:
        if not module_gate_passed(db, learner, module):
            return False
        if module_has_items(db, module.id, "summative"):
            attempt = best_attempt(db, learner, module.id, "summative")
            if not (attempt and attempt.passed):
                return False
    return True


def issue_certificate(
    db: Session, learner: Learner, product_code: str
) -> Certificate | None:
    """Issue once, then return the existing row on every later call."""
    existing = db.execute(
        select(Certificate).where(
            Certificate.learner_id == learner.id,
            Certificate.product_code == product_code,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if not course_complete(db, learner, product_code):
        return None

    row = Certificate(
        learner_id=learner.id,
        product_code=product_code,
        code=f"PRE-{secrets.token_hex(5).upper()}",
        learner_name=learner.full_name or learner.email,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
