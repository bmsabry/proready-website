"""Database models.

Tables:
  courses        — one row per cohort/course offering
  registrations  — one row per registration attempt, linked to a course by `course_code`

Registration status transitions:
  pending -> paid      (admin marks paid after invoice clears)
  pending -> cancelled (admin releases a stale lead)

Only `paid` rows count toward a course's seat cap.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # URL-friendly identifier used in registrations.course_code and public API.
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    total_seats: Mapped[int] = mapped_column(Integer, default=15)

    # ISO date strings, ordered Day 1 -> Day N. Number of days = len(day_dates).
    # Stored as JSON for portability (Postgres uses native json, SQLite text).
    day_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 'open' | 'closed' — 'closed' rejects new registrations.
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Foreign-key-by-string to Course.code. String chosen over a real FK so
    # admins can rename/replace courses without cascading migrations.
    course_code: Mapped[str] = mapped_column(String(128), index=True)

    # Applicant fields mirror the frontend form.
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), index=True)
    job_title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200))
    years_experience: Mapped[str] = mapped_column(String(16))
    location: Mapped[str] = mapped_column(String(200))

    # 'pending' | 'paid' | 'cancelled'
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)

    # Free-text admin notes (optional, nullable).
    admin_notes: Mapped[str | None] = mapped_column(String(2000), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


# Composite index: common "count paid rows for this course" query.
Index(
    "ix_registrations_course_status",
    Registration.course_code,
    Registration.status,
)


class AISettings(Base):
    """LLM credentials + model preference for the admin AI assistant.

    Single-row table — there's only ever one config (the admin's). The API
    key is stored Fernet-encrypted using the AI_SETTINGS_KEY env var; the
    plaintext never touches the DB or the wire after entry.
    """

    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    api_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIAudit(Base):
    """One row per tool call (or attempted tool call) made by the AI agent.

    Captures enough to reconstruct what the agent did, when, with what
    parameters, and whether it succeeded — so a compromised admin chat
    can be reviewed and undone.
    """

    __tablename__ = "ai_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # 'tool' for an executed tool call; 'chat' for a plain assistant turn;
    # 'cap_hit' when the daily spend cap rejected a request.
    kind: Mapped[str] = mapped_column(String(32), index=True, default="tool")
    tool_name: Mapped[str] = mapped_column(String(64), default="")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_micro: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(200), default="")


class AIPendingAction(Base):
    """A tool call the agent wants to take but that requires admin sign-off.

    Created when the agent emits a 'high-stakes' tool call (any notify
    email send, or bulk mark-paid/cancel ≥ 3 rows). The admin clicks
    Approve in the chat UI; backend then re-validates the row, executes,
    and marks it consumed. Expires after 10 minutes.
    """

    __tablename__ = "ai_pending_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class AIUsageDaily(Base):
    """Per-day rollup of token usage so the daily spend cap can be enforced.

    A single row per UTC date. Token counts come from the LLM provider's
    `usage` block. Cost is estimated using rates configured below in
    routes/ai.py — conservative defaults that overestimate slightly so we
    fail closed rather than fail rich.
    """

    __tablename__ = "ai_usage_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_micro: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductDownload(Base):
    """One row per download of a free product (e.g. Pro3DWorks).

    Logged by the Cloudflare Pages Function that serves the file: it sees the
    visitor's edge geo (country/region/city/timezone) and forwards it here.
    The API never stores IP addresses — geo granularity stops at city, which
    keeps the table safe to expose in aggregate on the public site.
    """

    __tablename__ = "product_downloads"
    __table_args__ = (
        Index("ix_product_downloads_product_ts", "product", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    country: Mapped[str] = mapped_column(String(8), default="")
    region: Mapped[str] = mapped_column(String(128), default="")
    city: Mapped[str] = mapped_column(String(128), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    colo: Mapped[str] = mapped_column(String(8), default="")
    referrer: Mapped[str] = mapped_column(Text, default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")


# =============================================================================
# Academy — self-serve, on-demand course platform
# =============================================================================
# These tables are deliberately namespaced `academy_*` and kept independent of
# the cohort `courses`/`registrations` tables above. A cohort registration is a
# lead for a live class; an academy enrollment is a paid, permanent grant of
# access to recorded material. They never share rows.
#
# Access rule enforced everywhere: a learner may read a lesson's protected
# payload only if an Enrollment row exists with status='active' for that
# lesson's product AND (expires_at IS NULL OR expires_at > now).


class Learner(Base):
    """A person who bought (or was granted) access to an academy product.

    Separate from Registration on purpose: a learner is an identity that
    persists across purchases, whereas a registration is one lead for one
    cohort. Email is the natural key — lowercased on write so lookups are
    case-insensitive without a functional index.
    """

    __tablename__ = "academy_learners"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")

    # Optional bcrypt hash. Empty for anyone who only ever uses the magic
    # link; populated for learners migrated from the legacy quiz-app login,
    # whose bcrypt hashes port across verbatim. Both paths resolve to the
    # same Learner row, so one purchase unlocks both surfaces.
    password_hash: Mapped[str] = mapped_column(String(128), default="")

    # Grants the legacy /learning admin views. Not the academy admin — that
    # is still ADMIN_EMAIL + ADMIN_PASSWORD_HASH and entirely separate.
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)

    # 'active' | 'blocked'. Blocked learners keep their rows but fail auth.
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class LoginToken(Base):
    """A single-use magic-link token for passwordless learner sign-in.

    Only the SHA-256 hash of the token is stored, so a database leak does
    not hand out live sign-in links. Tokens are consumed on first use
    (`used_at` set) and expire via `expires_at` regardless.
    """

    __tablename__ = "academy_login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(Integer, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Where to land the learner after a successful exchange (relative path).
    next_path: Mapped[str] = mapped_column(String(300), default="/learn")


class Product(Base):
    """A sellable course. One row per thing a visitor can buy."""

    __tablename__ = "academy_products"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    # Optional: a pre-made Stripe Price. When empty we build price_data
    # inline at Checkout time from price_cents/currency.
    stripe_price_id: Mapped[str] = mapped_column(String(120), default="")

    total_hours: Mapped[float] = mapped_column(Float, default=0.0)

    # 'draft' — visible to nobody but admin; 'live' — purchasable.
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Order(Base):
    """One payment attempt for one product.

    The email is captured here as well as on Learner because an order can
    exist before we have ever seen the buyer — Stripe Checkout collects the
    address, and we only mint the Learner when the webhook confirms payment.
    """

    __tablename__ = "academy_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)
    product_code: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True, default="")

    # 'stripe' | 'paypal' | 'manual'
    provider: Mapped[str] = mapped_column(String(16), default="stripe")
    # Stripe Checkout Session id — unique so webhook replays are idempotent.
    provider_ref: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    payment_ref: Mapped[str] = mapped_column(String(200), default="")

    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="usd")

    # 'pending' | 'paid' | 'refunded' | 'failed'
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Enrollment(Base):
    """The access grant itself. This row is what gates every protected read.

    `expires_at IS NULL` means lifetime access, which is what a purchase
    buys. Time-boxed grants exist so comp/trial access can be handed out
    without a code change.
    """

    __tablename__ = "academy_enrollments"
    __table_args__ = (
        Index(
            "ix_academy_enrollment_unique",
            "learner_id",
            "product_code",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(Integer, index=True)
    product_code: Mapped[str] = mapped_column(String(64), index=True)

    # 'stripe' | 'manual' | 'invite' | 'comp'
    source: Mapped[str] = mapped_column(String(16), default="stripe")
    order_id: Mapped[int | None] = mapped_column(Integer, default=None)

    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # 'active' | 'revoked'
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    note: Mapped[str] = mapped_column(String(500), default="")


class Module(Base):
    """A top-level unit of a product — one GT session (GT-05, GT-06, ...)."""

    __tablename__ = "academy_modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    hours: Mapped[float] = mapped_column(Float, default=0.0)

    # Marketing/curriculum detail, rendered on the sales page and in-app.
    objectives: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # The standalone interactive quiz app for this session, if one exists.
    quiz_app_url: Mapped[str] = mapped_column(String(300), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Lesson(Base):
    """A single playable/readable unit inside a module."""

    __tablename__ = "academy_lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # 'video' | 'slides' | 'reading' | 'lab' | 'calculator' | 'quiz'
    kind: Mapped[str] = mapped_column(String(16), default="video", index=True)

    duration_s: Mapped[int] = mapped_column(Integer, default=0)

    # Cloudflare Stream UID. Empty until the upload pipeline fills it in,
    # which is why lessons can be seeded before any video exists.
    video_uid: Mapped[str] = mapped_column(String(64), default="")
    # Source filename on Bassam's library — the join key for the uploader.
    source_file: Mapped[str] = mapped_column(String(300), default="")
    # For labs/simulators/decks: a path served behind the entitlement check.
    asset_path: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")

    # A preview lesson is readable by anyone — the free sample on the
    # sales page. Everything else requires an active enrollment.
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Chapter(Base):
    """A named, seekable span inside one continuous lecture recording.

    The source recordings arrive split into a dozen or more files, but those
    splits are an artefact of upload size limits — a boundary can land
    mid-sentence — so they are rejoined into one master per module and
    navigated by chapter instead. Chapter names come from the deck's own
    section structure ('Slip Factor', 'Disc Stress'), and the timestamps come
    from matching what is on screen to the slides, so they mark where a topic
    is genuinely taught rather than where a file happened to be cut.
    """

    __tablename__ = "academy_chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(Integer, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)

    title: Mapped[str] = mapped_column(String(300))
    start_s: Mapped[int] = mapped_column(Integer, default=0)
    end_s: Mapped[int] = mapped_column(Integer, default=0)

    # Slide numbers covered, so the player can show the deck alongside.
    slides: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Slide(Base):
    """One rendered slide, and the moment it appears in the recording.

    Slides ship as images, never as the .pptx: the deck is the intellectual
    property the whole platform exists to protect, so it is served through a
    signed, watermarked endpoint and there is no file to hand around.

    `text` is kept for two jobs that pay for themselves later — grounding the
    course assistant in what was actually taught, and letting a learner search
    the deck rather than scrub the video.
    """

    __tablename__ = "academy_slides"
    __table_args__ = (
        Index("ix_academy_slide_unique", "module_id", "number", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer, default=0)

    title: Mapped[str] = mapped_column(String(300), default="")
    section: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text, default="")

    # Where this slide first appears in the master recording. -1 when the
    # module has no recording (GT-03 and GT-12 today) or the alignment could
    # not place it — the slide is still shown, just not seekable.
    appears_at_s: Mapped[int] = mapped_column(Integer, default=-1)

    # Stored asset keys, resolved to signed URLs at request time.
    image_lg: Mapped[str] = mapped_column(String(300), default="")
    image_sm: Mapped[str] = mapped_column(String(300), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LessonProgress(Base):
    """Per-learner, per-lesson watch state. Upserted by the player heartbeat."""

    __tablename__ = "academy_lesson_progress"
    __table_args__ = (
        Index(
            "ix_academy_progress_unique",
            "learner_id",
            "lesson_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(Integer, index=True)
    lesson_id: Mapped[int] = mapped_column(Integer, index=True)

    # Where the player should resume from.
    position_s: Mapped[int] = mapped_column(Integer, default=0)
    # Monotonic count of seconds actually watched — the honest completion
    # signal. Seeking to the end does not inflate it.
    watched_s: Mapped[int] = mapped_column(Integer, default=0)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuizItem(Base):
    """One assessment item, seeded from the signed-off assessment bank.

    `answer` never leaves the server: the learner-facing serializer strips
    it, and grading happens in-process. That keeps the bank usable as a
    real gate rather than a formality.
    """

    __tablename__ = "academy_quiz_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)

    # 'formative' (gates the next module) | 'summative' (counts toward final)
    item_set: Mapped[str] = mapped_column(String(16), default="formative", index=True)
    # 'mcq' | 'numeric' | 'short' | 'match'
    kind: Mapped[str] = mapped_column(String(16), default="mcq")

    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    answer: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rubric: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")

    cognitive_level: Mapped[str] = mapped_column(String(32), default="")
    outcome_id: Mapped[str] = mapped_column(String(32), default="")
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)


class QuizAttempt(Base):
    """One submitted attempt at a module's formative or summative set."""

    __tablename__ = "academy_quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(Integer, index=True)
    module_id: Mapped[int] = mapped_column(Integer, index=True)
    item_set: Mapped[str] = mapped_column(String(16), default="formative", index=True)

    # Percentage over auto-gradable items only (mcq/numeric/match). Short
    # answers are stored for tutor review and excluded from the gate so a
    # learner is never blocked waiting on a human/AI grade.
    score_pct: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    auto_total: Mapped[int] = mapped_column(Integer, default=0)
    auto_correct: Mapped[int] = mapped_column(Integer, default=0)

    # {item_code: {"response": ..., "correct": bool|None}}
    responses: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Certificate(Base):
    """Issued once a learner clears every module gate plus the capstone."""

    __tablename__ = "academy_certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(Integer, index=True)
    product_code: Mapped[str] = mapped_column(String(64), index=True)
    # Public verification code shown on the certificate and checkable at
    # /verify/{code} without authentication.
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    learner_name: Mapped[str] = mapped_column(String(200), default="")
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModuleState(Base):
    """Opaque per-learner, per-module blob owned by the standalone quiz apps.

    The five `smallgasturbine.gt-XX` apps PUT their whole progress object here
    and GET it back verbatim. The shape is the app's business, not ours — we
    deliberately do not parse or validate it, so their behaviour is unchanged
    by the backend swap. `academy_quiz_attempts` remains the server-graded
    store for assessments the platform itself runs.
    """

    __tablename__ = "academy_module_state"
    __table_args__ = (
        Index(
            "ix_academy_module_state_unique", "learner_id", "module_id", unique=True
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    learner_id: Mapped[int] = mapped_column(Integer, index=True)
    # Legacy lowercase id as the apps use it, e.g. 'gt-05'.
    module_id: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppLaunch(Base):
    """One anonymous launch signal from the Pro3DWorks in-app update check.

    The app sends only its name and version; geography comes from the edge
    at city level. No IP addresses are ever stored.
    """

    __tablename__ = "app_launches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    version: Mapped[str | None] = mapped_column(String(24))
    country: Mapped[str | None] = mapped_column(String(8))
    region: Mapped[str | None] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128))


Index("ix_app_launches_product_ts", AppLaunch.product, AppLaunch.ts)


class AppUsage(Base):
    """One anonymous, opt-in usage ping from a closing Pro3DWorks session.

    Counts only: which features ran, and for how many minutes the app was
    open. No identifiers, no file names, no model data; location stops at
    city level and no IP addresses are ever stored.
    """

    __tablename__ = "app_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    version: Mapped[str | None] = mapped_column(String(24))
    minutes: Mapped[int | None] = mapped_column(Integer)
    features: Mapped[str | None] = mapped_column(String(1024))  # JSON counts: {"bom": 2, ...}
    country: Mapped[str | None] = mapped_column(String(8))
    region: Mapped[str | None] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128))


Index("ix_app_usage_product_ts", AppUsage.product, AppUsage.ts)
