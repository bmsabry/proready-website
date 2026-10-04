"""Written-examination sampling and the per-competency diagnosis.

The bank for a course may hold more questions than one paper: each attempt
draws a fixed number, balanced across the certificate's competencies, so the
retake is a different paper of the same shape and the per-competency scores of
two attempts are comparable. These tests cover the drawing, the persistence of
the drawn paper, the grading boundary, and the breakdown the instructor reads
before the oral examination.
"""
from __future__ import annotations

import conftest  # noqa: F401  (sets the environment before app import)

from app.main import app  # noqa: E402,F401  (import builds the schema)
from app import advanced_cert as adv  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AdvancedCertification,
    Learner,
    Product,
    QuizItem,
)

CODE = "sampling-test-course"
COMPETENCIES = [f"Competency {n}" for n in range(1, 9)]
POOL = {"C1": 24, "C2": 22, "C3": 26, "C4": 24, "C5": 22, "C6": 30, "C7": 30, "C8": 22}


def _seed() -> int:
    """A product with its eight competencies, a 200-question bank, one candidate."""
    db = SessionLocal()
    product = Product(
        code=CODE, title="Sampling Test Course",
        certificate_competencies=COMPETENCIES,
        advanced_cert_enabled=True, advanced_cert_price_cents=30000,
    )
    db.add(product)
    position = 0
    for competency, count in POOL.items():
        for n in range(1, count + 1):
            position += 1
            db.add(QuizItem(
                module_id=0, product_code=CODE, item_set="advanced",
                code=f"{competency}-{n:02d}", position=position, kind="mcq",
                outcome_id=competency, cognitive_level="Analyze",
                stem=f"{competency} question {n}",
                options=[{"key": k, "text": f"option {k}"} for k in "ABCD"],
                answer={"key": "B"}, explanation="", rubric="",
            ))
    learner = Learner(email="sampling.candidate@example.com", full_name="Sam Candidate")
    db.add(learner)
    db.commit()
    learner_id = learner.id
    db.close()
    return learner_id


def _row(db, learner_id: int) -> AdvancedCertification:
    row = AdvancedCertification(
        learner_id=learner_id, product_code=CODE, status="purchased",
        source="manual", amount_cents=0, currency="usd",
    )
    db.add(row)
    db.commit()
    return row


def test_bank_is_two_hundred_questions():
    _seed()
    db = SessionLocal()
    assert len(adv.exam_items(db, CODE)) == 200
    assert sum(POOL.values()) == 200
    db.close()


def test_the_completion_email_offer_quotes_one_paper_not_the_bank():
    """The invitation in the completion email states how many questions the
    candidate will sit, which is one drawn paper, not the size of the bank."""
    from app import certificates as certs

    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    offer = certs.examined_tier_offer(db, learner, db.get(Product, CODE))
    assert offer is not None and offer["bookable"] is True
    assert offer["exam_item_count"] == 100
    assert len(adv.exam_items(db, CODE)) == 200
    db.close()


def test_a_paper_is_one_hundred_balanced_across_the_competencies():
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    row = _row(db, learner.id)
    paper = adv.served_items(db, CODE, row)
    assert len(paper) == 100
    seats: dict[str, int] = {}
    for item in paper:
        seats[item.outcome_id] = seats.get(item.outcome_id, 0) + 1
    # Half of each competency's share of the bank, by largest remainder.
    assert seats == {"C1": 12, "C2": 11, "C3": 13, "C4": 12,
                     "C5": 11, "C6": 15, "C7": 15, "C8": 11}
    assert sum(seats.values()) == 100
    # Served in course order, and no question twice.
    assert [i.position for i in paper] == sorted(i.position for i in paper)
    assert len({i.code for i in paper}) == 100
    db.close()


def test_the_same_paper_comes_back_until_it_is_handed_in():
    """A reload during the exam must not reshuffle the questions."""
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    row = adv.current(db, learner, CODE)
    first = [i.code for i in adv.served_items(db, CODE, row)]
    second = [i.code for i in adv.served_items(db, CODE, row)]
    assert first == second == list(row.exam_item_codes)
    db.close()


def test_grading_scores_the_paper_that_was_sat_and_ignores_the_rest():
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    product = db.query(Product).filter(Product.code == CODE).one()
    row = adv.current(db, learner, CODE)
    paper = adv.served_items(db, CODE, row)
    sat = {i.code for i in paper}
    # Answer the paper: right for C1-C6, wrong for C7 and C8.
    responses = {i.code: ("B" if i.outcome_id not in ("C7", "C8") else "A") for i in paper}
    # Plus an answer to a question that was not on this paper — it must not score.
    unseen = next(i.code for i in adv.exam_items(db, CODE) if i.code not in sat)
    responses[unseen] = "B"
    attempt = adv.grade_exam(db, learner, product, row, responses)
    assert attempt.auto_total == 100
    assert attempt.auto_correct == 100 - 15 - 11  # C7 and C8 wrong
    assert unseen not in attempt.responses
    assert attempt.score_pct == 74.0
    assert attempt.passed is False
    # The paper has been handed in, so the next attempt draws its own.
    assert list(row.exam_item_codes) == []
    assert row.status == "purchased"  # one attempt left of two
    db.close()


def test_the_retake_is_a_different_paper_of_the_same_shape():
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    row = adv.current(db, learner, CODE)
    first = set(db.get(AdvancedCertification, row.id).exam_item_codes or [])
    retake = adv.served_items(db, CODE, row)
    assert len(retake) == 100
    # A fresh draw from a 200-question bank: identical papers are vanishingly
    # unlikely, and the overlap must leave real new ground.
    codes = {i.code for i in retake}
    assert codes != first
    db.close()


def test_the_breakdown_names_the_weak_competencies_first():
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    product = db.query(Product).filter(Product.code == CODE).one()
    attempt = adv.best_attempt(db, learner.id, CODE)
    rows = adv.competency_breakdown(db, product, attempt)
    assert [r["id"] for r in rows][:2] == ["C7", "C8"]  # the two answered wrong
    weak = {r["id"]: r for r in rows}
    assert weak["C7"]["pct"] == 0.0 and weak["C7"]["total"] == 15
    assert weak["C8"]["pct"] == 0.0 and weak["C8"]["total"] == 11
    assert all(r["pct"] == 100.0 for r in rows if r["id"] not in ("C7", "C8"))
    # The competency text from the certificate, not the bare code.
    assert weak["C7"]["label"] == "Competency 7"
    assert sum(r["total"] for r in rows) == 100
    db.close()


def test_the_candidate_sees_the_breakdown_only_after_an_outcome():
    db = SessionLocal()
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    product = db.query(Product).filter(Product.code == CODE).one()
    row = adv.current(db, learner, CODE)
    row.status = "scheduled"
    db.commit()
    assert adv.learner_out(db, learner, product, row)["state"]["exam_breakdown"] == []
    # The instructor sees it before the interview either way.
    assert len(adv.admin_out(db, row)["exam_breakdown"]) == 8
    row.status = "failed"
    db.commit()
    assert len(adv.learner_out(db, learner, product, row)["state"]["exam_breakdown"]) == 8
    db.close()


def test_a_bank_no_bigger_than_one_paper_is_served_whole():
    """The other course's 23-question bank must keep working unchanged."""
    db = SessionLocal()
    small = [QuizItem(
        module_id=0, product_code="small-bank-course", item_set="advanced",
        code=f"ADV-{n:02d}", position=n, kind="mcq", outcome_id="M1.O1",
        stem=f"question {n}", options=[{"key": k, "text": k} for k in "ABCD"],
        answer={"key": "A"}, explanation="", rubric="",
    ) for n in range(1, 24)]
    db.add_all(small)
    learner = db.query(Learner).filter(Learner.email == "sampling.candidate@example.com").one()
    row = AdvancedCertification(
        learner_id=learner.id, product_code="small-bank-course", status="purchased",
        source="manual", amount_cents=0, currency="usd",
    )
    db.add(row)
    db.commit()
    paper = adv.served_items(db, "small-bank-course", row)
    assert len(paper) == 23
    assert adv.serve_count(db, "small-bank-course") == 23
    # A bank tagged to module outcomes rather than certificate competencies
    # gets no breakdown, instead of one group per question.
    product = Product(code="small-bank-course", title="Small Bank Course",
                      certificate_competencies=COMPETENCIES)
    db.add(product)
    db.commit()
    responses = {i.code: "A" for i in paper}
    learner_row = db.get(AdvancedCertification, row.id)
    attempt = adv.grade_exam(db, learner, product, learner_row, responses)
    assert attempt.auto_total == 23
    assert adv.competency_breakdown(db, product, attempt) == []
    db.close()
