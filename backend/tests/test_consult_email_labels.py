"""Consulting calls: every email the code sends has a readable name in the admin's email log.

The log shows `email_copies.KIND_LABELS[kind]` for each email's kind (its
`template`), and falls back to the raw identifier when there is none. The
first test reads the consulting code itself: every kind it can pass to the
email sender must have a label, and no label may be left for a kind that is
no longer sent. The second sends real ones and reads the log.
"""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

from consult_support import (  # noqa: F401  (fixtures)
    ADMIN,
    client,
    confirmed,
    env,
    ny,
    tick,
    world,
)

from app import email_copies

APP = Path(__file__).resolve().parent.parent / "app"
# Every module that sends consulting email.
SOURCES = ("consult.py", "consult_auto.py", "consult_money.py", "routes/consult.py")

# The kinds as they stand. A new email kind fails the test below until it is
# added here and given a label.
EXPECTED = {
    # to the client
    "consult_confirmed", "consult_slot_lost", "consult_cancelled", "consult_reminder_first",
    "consult_reminder_last", "consult_hold_placed", "consult_hold_failed", "consult_receipt",
    "consult_fee_notice",
    # to the owner
    "consult_owner_new", "consult_owner_cancelled", "consult_owner_charge_result", "consult_owner_summary",
    "consult_owner_hold_failed", "consult_owner_hold_cancelled", "consult_owner_calendar_fixed",
    "consult_owner_dispute", "consult_owner_needs_review", "consult_owner_tick_stopped",
}


def _outcomes(node: ast.AST) -> tuple[set[str], bool]:
    """The strings an expression can come to, following `a if test else b`
    into both arms (not into the test). (strings, whether all of it was read)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}, True
    if isinstance(node, ast.IfExp):
        a, a_ok = _outcomes(node.body)
        b, b_ok = _outcomes(node.orelse)
        return a | b, a_ok and b_ok
    return set(), False


def kinds_sent_by_the_code() -> tuple[set[str], list[str]]:
    """Every value given as `template=` in a call anywhere in the consulting
    code, and the places where the value could not be read (anything but a
    string, a choice between strings, or a parameter handed on unchanged)."""
    kinds: set[str] = set()
    unread: list[str] = []
    for name in SOURCES:
        tree = ast.parse((APP / name).read_text(encoding="utf-8"), name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "template":
                    continue
                if isinstance(kw.value, ast.Name) and kw.value.id == "template":
                    continue                    # handed on by a helper; its callers are read too
                found, complete = _outcomes(kw.value)
                kinds |= found
                if not complete:
                    unread.append(f"{name}:{kw.value.lineno}")
    return kinds, unread


def test_every_consulting_email_kind_the_code_sends_has_a_label():
    kinds, unread = kinds_sent_by_the_code()
    assert unread == [], f"a template the test cannot read: {unread}"
    assert kinds == EXPECTED, (sorted(kinds - EXPECTED), sorted(EXPECTED - kinds))
    for kind in sorted(kinds):
        assert kind in email_copies.KIND_LABELS, f"{kind} has no label in email_copies.KIND_LABELS"
        label = email_copies.kind_label(kind)
        assert label.startswith("Consulting: ") and len(label) > len("Consulting: ") + 4, (kind, label)
        assert "_" not in label and "consult_" not in label, (kind, label)
    labels = [email_copies.KIND_LABELS[k] for k in kinds]
    assert len(set(labels)) == len(labels)                         # each kind can be told from the others
    owner = [k for k in kinds if k.startswith("consult_owner_")]
    assert all(email_copies.KIND_LABELS[k].endswith("(alert)") for k in owner)   # as the other alerts to him do


def test_no_label_is_left_for_a_consulting_kind_that_is_no_longer_sent():
    kinds, _ = kinds_sent_by_the_code()
    labelled = {k for k in email_copies.KIND_LABELS if k.startswith("consult")}
    assert labelled == kinds, sorted(labelled ^ kinds)


def test_without_a_label_the_log_would_show_the_raw_identifier():
    # what the test above protects against
    assert email_copies.kind_label("consult_some_new_kind") == "Consult some new kind"


def test_the_admin_email_log_names_the_consulting_emails(client, env):
    start = ny(2031, 6, 11, 10)
    b = confirmed(client, env, start)
    for at in (start - timedelta(hours=48), start - timedelta(hours=24), start - timedelta(hours=1),
               start + timedelta(hours=1), start + timedelta(hours=3)):
        env.clock.set(at)
        tick(client)
    answer = client.get("/api/admin/comms/log", params={"scope_code": "consult"}, headers=ADMIN)
    assert answer.status_code == 200, answer.text
    rows = answer.json()["rows"]
    assert len(rows) == 8 and answer.json()["has_more"] is False
    shown = {r["template"]: r["kind_label"] for r in rows}
    assert set(shown) == {
        "consult_confirmed", "consult_owner_new", "consult_reminder_first", "consult_hold_placed",
        "consult_reminder_last", "consult_owner_summary", "consult_receipt", "consult_owner_charge_result",
    }
    assert shown == {k: email_copies.KIND_LABELS[k] for k in shown}
    assert shown["consult_reminder_first"] == "Consulting: reminder while cancelling is still free"
    assert shown["consult_receipt"] == "Consulting: receipt"
    assert all(b["ref"] in r["subject"] or "Casey Client" in r["subject"] for r in rows)
