"""Learner history survives every content update. Enforced, not assumed.

A trainee's watch progress, quiz attempts and quiz-app state are keyed by
lesson / module id, and every content-load endpoint upserts by stable code,
so replacing a deck, a video, a chapter list or a question bank keeps those
ids and therefore keeps the history. This module makes that a property of
the database layer rather than of each endpoint's good behaviour:

  * rows in the history tables (lesson progress, quiz attempts, module
    state) cannot be deleted, by ORM or by Core statement;
  * a lesson, module or product that has history beneath it cannot be
    deleted either — the update path must keep the row and change its
    content instead;
  * the one legitimate exception (a migration that has already moved the
    history elsewhere, or a test resetting its own fixtures) opts in with
    `allow_progress_loss("reason")`, which is visible in the code that uses
    it and in the log.

Anything that trips the guard raises ProgressLossBlocked before the
statement reaches the database, so a mistake shows up as a 500 with a clear
message during development instead of as missing progress in production.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete

from .models import (
    Enrollment,
    Lesson,
    LessonProgress,
    Module,
    ModuleState,
    Product,
    QuizAttempt,
)

log = logging.getLogger(__name__)

# What a learner has done. Never deleted.
HISTORY_TABLES = {
    LessonProgress.__tablename__,
    QuizAttempt.__tablename__,
    ModuleState.__tablename__,
}
# What the history hangs off. Deletable only when nothing hangs off it.
STRUCTURE_TABLES = {
    Lesson.__tablename__,
    Module.__tablename__,
    Product.__tablename__,
}

_allowed: ContextVar[str] = ContextVar("progress_loss_allowed", default="")


class ProgressLossBlocked(RuntimeError):
    """Raised instead of executing a statement that would erase learner history."""


@contextmanager
def allow_progress_loss(reason: str) -> Iterator[None]:
    """Opt out of the guard for one block. The reason is logged."""
    if not reason.strip():
        raise ValueError("allow_progress_loss needs a reason")
    log.warning("[progress_guard] deletion of learner history allowed: %s", reason)
    token = _allowed.set(reason)
    try:
        yield
    finally:
        _allowed.reset(token)


def _history_under_lesson(session: Session, lesson_id: int) -> int:
    return session.execute(
        select(func.count(LessonProgress.id)).where(LessonProgress.lesson_id == lesson_id)
    ).scalar_one()


def _history_under_module(session: Session, module: Module) -> int:
    lesson_ids = select(Lesson.id).where(Lesson.module_id == module.id)
    n = session.execute(
        select(func.count(LessonProgress.id)).where(LessonProgress.lesson_id.in_(lesson_ids))
    ).scalar_one()
    n += session.execute(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.module_id == module.id)
    ).scalar_one()
    n += session.execute(
        select(func.count(ModuleState.id)).where(ModuleState.module_id == module.code.lower())
    ).scalar_one()
    return n


def _history_under_product(session: Session, product: Product) -> int:
    module_ids = select(Module.id).where(Module.product_code == product.code)
    lesson_ids = select(Lesson.id).where(Lesson.module_id.in_(module_ids))
    n = session.execute(
        select(func.count(LessonProgress.id)).where(LessonProgress.lesson_id.in_(lesson_ids))
    ).scalar_one()
    n += session.execute(
        select(func.count(QuizAttempt.id)).where(
            (QuizAttempt.module_id.in_(module_ids)) | (QuizAttempt.product_code == product.code)
        )
    ).scalar_one()
    n += session.execute(
        select(func.count(Enrollment.id)).where(Enrollment.product_code == product.code)
    ).scalar_one()
    return n


def _blocked(what: str) -> ProgressLossBlocked:
    return ProgressLossBlocked(
        f"Refusing to delete {what}: it carries learner progress or quiz history. "
        "Content updates must overwrite the row in place (same code, same id). "
        "If this deletion is deliberate, wrap it in allow_progress_loss(reason)."
    )


_VETTED_KEY = "progress_guard_vetted"


def _param_sets(multiparams, params) -> list[dict]:
    out: list[dict] = []
    if isinstance(params, dict) and params:
        out.append(params)
    for group in multiparams or ():
        if isinstance(group, dict):
            out.append(group)
        elif isinstance(group, (list, tuple)):
            out.extend(g for g in group if isinstance(g, dict))
    return out


def install(engine) -> None:
    """Attach the guard to the engine (Core statements) and to every Session (ORM deletes).

    The ORM deletes a vetted object by emitting a Core DELETE of its own, so
    before_flush records the primary keys it has approved on the connection
    and before_execute lets exactly those through; every other DELETE against
    a protected table is refused.
    """

    @event.listens_for(engine, "before_execute", retval=True)
    def _core_delete(conn, clauseelement, multiparams, params, execution_options):
        if isinstance(clauseelement, Delete) and not _allowed.get():
            table = getattr(clauseelement.table, "name", "")
            if table in HISTORY_TABLES:
                raise _blocked(f"rows of {table}")
            if table in STRUCTURE_TABLES:
                vetted: set = conn.info.get(_VETTED_KEY) or set()
                pk = list(clauseelement.table.primary_key.columns)[0].name
                sets = _param_sets(multiparams, params)
                keys = [(table, ps.get(pk)) for ps in sets if pk in ps]
                if not keys or any(k not in vetted for k in keys):
                    # A bulk statement cannot be checked row by row; the ORM
                    # path (session.delete(obj)) can, and is the way to remove
                    # an unused lesson, module or product.
                    raise _blocked(f"rows of {table} with a bulk statement")
                for k in keys:
                    vetted.discard(k)
        return clauseelement, multiparams, params

    @event.listens_for(Session, "before_flush")
    def _orm_delete(session: Session, flush_context, instances) -> None:
        if _allowed.get() or not session.deleted:
            return
        approved: list[tuple[str, object]] = []
        for obj in list(session.deleted):
            if isinstance(obj, (LessonProgress, QuizAttempt, ModuleState)):
                raise _blocked(f"{type(obj).__name__} #{obj.id}")
            if isinstance(obj, Lesson):
                if _history_under_lesson(session, obj.id):
                    raise _blocked(f"lesson {obj.code} (#{obj.id})")
                approved.append((Lesson.__tablename__, obj.id))
            elif isinstance(obj, Module):
                if _history_under_module(session, obj):
                    raise _blocked(f"module {obj.code} (#{obj.id})")
                approved.append((Module.__tablename__, obj.id))
            elif isinstance(obj, Product):
                if _history_under_product(session, obj):
                    raise _blocked(f"product {obj.code}")
                approved.append((Product.__tablename__, obj.code))
        if approved:
            session.connection().info.setdefault(_VETTED_KEY, set()).update(approved)
