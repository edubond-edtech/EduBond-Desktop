"""Answer evaluation engine.

Evaluators are pure functions registered per question type, so new activity
types (numeric keypads, sensor thresholds, ordering puzzles) plug in without
touching the quiz flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..core.models import Question


class Outcome(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


@dataclass
class EvaluationResult:
    outcome: Outcome
    score: float
    max_score: float
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_correct(self) -> bool:
        return self.outcome == Outcome.CORRECT


Evaluator = Callable[[Question, Any], EvaluationResult]
_EVALUATORS: dict[str, Evaluator] = {}


def register_evaluator(qtype: str) -> Callable[[Evaluator], Evaluator]:
    def deco(fn: Evaluator) -> Evaluator:
        _EVALUATORS[qtype] = fn
        return fn

    return deco


def _as_keys(answer: Any) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, str):
        return [a.strip().upper() for a in answer.split(",") if a.strip()]
    return [str(a).strip().upper() for a in answer]


@register_evaluator("single_choice")
@register_evaluator("true_false")
def eval_single(q: Question, answer: Any) -> EvaluationResult:
    correct = set(_as_keys(q.correct))
    given = _as_keys(answer)
    ok = len(given) == 1 and given[0] in correct
    return EvaluationResult(
        Outcome.CORRECT if ok else Outcome.INCORRECT,
        float(q.points) if ok else 0.0,
        float(q.points),
        {"given": given, "expected": sorted(correct)},
    )


@register_evaluator("multi_choice")
def eval_multi(q: Question, answer: Any) -> EvaluationResult:
    """Partial credit: (hits - wrong picks) / number of correct keys, floored at 0."""
    correct = set(_as_keys(q.correct))
    given = set(_as_keys(answer))
    if not correct:
        raise ValueError(f"question {q.code} has no correct answer configured")
    hits = len(given & correct)
    wrong = len(given - correct)
    frac = max(0.0, (hits - wrong) / len(correct))
    if frac >= 1.0 and not wrong:
        outcome = Outcome.CORRECT
    elif frac > 0:
        outcome = Outcome.PARTIAL
    else:
        outcome = Outcome.INCORRECT
    return EvaluationResult(outcome, round(q.points * frac, 3), float(q.points), {"given": sorted(given), "expected": sorted(correct)})


@register_evaluator("numeric")
def eval_numeric(q: Question, answer: Any) -> EvaluationResult:
    spec = q.correct if isinstance(q.correct, dict) else {"value": q.correct, "tolerance": 0}
    try:
        val = float(answer)
    except (TypeError, ValueError):
        return EvaluationResult(Outcome.INCORRECT, 0.0, float(q.points), {"given": answer})
    target = float(spec["value"])
    tol = float(spec.get("tolerance", 0))
    ok = abs(val - target) <= tol
    return EvaluationResult(Outcome.CORRECT if ok else Outcome.INCORRECT, float(q.points) if ok else 0.0, float(q.points), {"given": val, "expected": target})


@register_evaluator("arrange")
def eval_arrange(q: Question, answer: Any) -> EvaluationResult:
    """Word arrangement: ``answer`` is the plate placed in each socket (socket 1 first)."""
    expected = [str(k) for k in (q.correct or [])]
    given = [str(a).strip() for a in (answer.split(",") if isinstance(answer, str) else (answer or []))]
    in_place = sum(1 for e, g in zip(expected, given) if e == g)
    ok = len(given) == len(expected) and in_place == len(expected)
    return EvaluationResult(
        Outcome.CORRECT if ok else Outcome.INCORRECT,
        float(q.points) if ok else 0.0,
        float(q.points),
        {"given": given, "expected": expected, "in_place": in_place},
    )


def evaluate(q: Question, answer: Any) -> EvaluationResult:
    try:
        fn = _EVALUATORS[q.qtype]
    except KeyError:
        raise ValueError(f"no evaluator for question type {q.qtype!r}") from None
    return fn(q, answer)


def timeout_result(q: Question) -> EvaluationResult:
    return EvaluationResult(Outcome.TIMEOUT, 0.0, float(q.points), {"given": None})
