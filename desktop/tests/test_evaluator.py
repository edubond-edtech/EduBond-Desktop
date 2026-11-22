import pytest

from edukit.core.models import Option, Question
from edukit.evaluation.evaluator import Outcome, evaluate, timeout_result


def q(**kw):
    base = dict(code="Q1", prompt={"en": "?"}, options=[Option(k, {"en": k}) for k in "ABCD"], correct=["C"], points=2)
    base.update(kw)
    return Question(**base)


def test_single_choice():
    assert evaluate(q(), "C").outcome == Outcome.CORRECT
    assert evaluate(q(), "c").score == 2
    r = evaluate(q(), "A")
    assert r.outcome == Outcome.INCORRECT and r.score == 0 and r.max_score == 2


def test_multi_choice_partial_credit():
    mq = q(qtype="multi_choice", correct=["A", "C"])
    assert evaluate(mq, ["A", "C"]).outcome == Outcome.CORRECT
    r = evaluate(mq, ["A"])
    assert r.outcome == Outcome.PARTIAL and r.score == 1
    assert evaluate(mq, ["A", "B"]).outcome == Outcome.INCORRECT


def test_numeric_tolerance():
    nq = q(qtype="numeric", options=[], correct={"value": 3.14, "tolerance": 0.01})
    assert evaluate(nq, "3.145").is_correct
    assert not evaluate(nq, "3.2").is_correct
    assert not evaluate(nq, "pi").is_correct


def test_timeout_and_unknown_type():
    assert timeout_result(q()).outcome == Outcome.TIMEOUT
    with pytest.raises(ValueError):
        evaluate(q(qtype="mystery"), "A")
