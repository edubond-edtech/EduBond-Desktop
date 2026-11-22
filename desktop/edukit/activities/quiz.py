"""Multiple-choice quiz activity (push buttons / touch pads / on-screen)."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from ..comms import protocol as P
from ..core.events import TimerHandle
from ..core.models import Question
from ..evaluation.evaluator import EvaluationResult, Outcome, evaluate, timeout_result
from ..hardware.models import DeviceStatus, InputEvent, LinkState
from .base import Activity, ActivityContext, register_activity


class QuizState(str, Enum):
    READY = "ready"
    ASKING = "asking"
    FEEDBACK = "feedback"
    FINISHED = "finished"
    STOPPED = "stopped"


@dataclass
class QuizSettings:
    feedback_seconds: float = 3.0  # how long the result stays before moving on
    auto_advance: bool = True  # False: teacher presses "Next"
    shuffle: bool = False
    use_question_timers: bool = True
    default_time_limit_s: int = 30  # used when a question has time_limit_s = 0 and timers are on
    allow_screen_answers: bool = True
    show_correct_answer: bool = True
    max_questions: int = 0  # 0 = all

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "QuizSettings":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@register_activity
class QuizActivity(Activity):
    type_id = "mcq"
    display_name = {"en": "Multiple-choice quiz", "ar": "اختبار اختيار من متعدد"}

    def __init__(self, ctx: ActivityContext, questions: list[Question], settings: QuizSettings | None = None, input_target: str = P.ROLE_INPUT):
        super().__init__(ctx)
        if not questions:
            raise ValueError("the selected question bank is empty")
        self.settings = settings or QuizSettings()
        qs = list(questions)
        if self.settings.shuffle:
            random.shuffle(qs)
        if self.settings.max_questions > 0:
            qs = qs[: self.settings.max_questions]
        self.questions = qs
        self.input_target = input_target
        self.state = QuizState.READY
        self.index = -1
        self.score = 0.0
        self.max_score = 0.0
        self.results: list[EvaluationResult | None] = [None] * len(qs)
        self.answers: list[Any] = [None] * len(qs)
        self.last_result: EvaluationResult | None = None
        self.last_source: str | None = None
        self.asked_at = 0.0
        self.deadline: float | None = None
        self.ignored_events = 0
        self._timer: TimerHandle | None = None

    # ----------------------------------------------------------- properties
    @property
    def current(self) -> Question | None:
        return self.questions[self.index] if 0 <= self.index < len(self.questions) else None

    def time_limit(self, q: Question) -> int:
        if not self.settings.use_question_timers:
            return 0
        return q.time_limit_s or self.settings.default_time_limit_s

    def remaining_s(self) -> float | None:
        if self.deadline is None or self.state != QuizState.ASKING:
            return None
        return max(0.0, self.deadline - self.ctx.scheduler.now())

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._ask(0)

    def stop(self) -> None:
        self._cancel_timer()
        if self.state not in (QuizState.FINISHED, QuizState.STOPPED):
            self.state = QuizState.STOPPED
            self.ctx.devices.send(self.input_target, P.C_DISARM)
            self.ctx.feedback.play("idle")
            self.ctx.recorder.finish(self.score, self.max_score)
            self._notify()

    def next(self) -> None:
        """Teacher/manual advance. Skips the current question if still unanswered."""
        if self.state == QuizState.ASKING:
            self._cancel_timer()
            self._resolve(None, timeout_result(self.current), "skipped", None, schedule_next=False)  # type: ignore[arg-type]
        if self.state in (QuizState.FEEDBACK,):
            self._advance()

    def _ask(self, i: int) -> None:
        self._cancel_timer()
        if i >= len(self.questions):
            self._finish()
            return
        self.index = i
        q = self.questions[i]
        self.state = QuizState.ASKING
        self.last_result = None
        self.last_source = None
        self.asked_at = self.ctx.scheduler.now()
        limit = self.time_limit(q)
        self.deadline = self.asked_at + limit if limit else None
        self._arm_inputs()
        self.ctx.feedback.play("waiting")
        if limit:
            self._timer = self.ctx.scheduler.call_later(limit, self._on_timeout)
        self._notify()

    def _arm_inputs(self) -> None:
        q = self.current
        if q is None:
            return
        remaining = self.remaining_s()
        self.ctx.devices.send(
            self.input_target,
            P.C_ARM,
            question_id=q.code,
            options=q.option_keys,
            timeout_s=int(remaining) if remaining else 0,
        )

    def _on_timeout(self) -> None:
        if self.state == QuizState.ASKING and self.current is not None:
            self._resolve(None, timeout_result(self.current), "timeout", None)

    # ---------------------------------------------------------------- input
    def handle_input(self, event: InputEvent) -> None:
        if event.event != "answer_selected":
            self.ignored_events += 1
            return
        q = self.current
        if self.state != QuizState.ASKING or q is None:
            self.ignored_events += 1  # late press after the question closed
            return
        if event.question_id and event.question_id != q.code:
            self.ignored_events += 1  # stale event for an earlier question
            return
        self.submit(event.selected_answer, source="device", device_id=event.device_id)

    def submit_from_ui(self, answer: Any, source: str = "screen") -> bool:
        if not self.settings.allow_screen_answers:
            return False
        return self.submit(answer, source=source, device_id=None)

    def submit(self, answer: Any, source: str, device_id: str | None) -> bool:
        q = self.current
        if self.state != QuizState.ASKING or q is None:
            return False  # duplicate / late answers are ignored
        if q.qtype != "numeric" and str(answer).upper() not in q.option_keys:
            self.ignored_events += 1
            return False
        self._cancel_timer()
        self._resolve(answer, evaluate(q, answer), source, device_id)
        return True

    def _resolve(self, answer: Any, result: EvaluationResult, source: str, device_id: str | None, schedule_next: bool = True) -> None:
        q = self.current
        assert q is not None
        self.state = QuizState.FEEDBACK
        self.deadline = None
        self.answers[self.index] = answer
        self.results[self.index] = result
        self.last_result = result
        self.last_source = source
        self.score += result.score
        self.max_score += result.max_score
        response_ms = int((self.ctx.scheduler.now() - self.asked_at) * 1000) if answer is not None else None
        self.ctx.devices.send(self.input_target, P.C_DISARM)
        self.ctx.feedback.play(result.outcome.value)
        self.ctx.recorder.record(q, answer, result, response_ms, source, device_id)
        self._notify()
        if schedule_next and self.settings.auto_advance:
            self._timer = self.ctx.scheduler.call_later(self.settings.feedback_seconds, self._advance)

    def _advance(self) -> None:
        if self.state == QuizState.FEEDBACK:
            self._ask(self.index + 1)

    def _finish(self) -> None:
        self._cancel_timer()
        self.state = QuizState.FINISHED
        self.deadline = None
        self.ctx.devices.send(self.input_target, P.C_DISARM)
        self.ctx.feedback.play("celebrate")
        self.ctx.recorder.finish(self.score, self.max_score)
        self._notify()

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def on_device_status(self, status: DeviceStatus) -> None:
        # An input controller that (re)connects mid-question must be re-armed.
        if status.state == LinkState.ONLINE and status.role == P.ROLE_INPUT and self.state == QuizState.ASKING:
            self._arm_inputs()
        if status.state == LinkState.ONLINE and status.role == P.ROLE_OUTPUT and self.state == QuizState.ASKING:
            self.ctx.feedback.play("waiting")
        self._notify()

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        q = self.current
        return {
            "type": self.type_id,
            "state": self.state.value,
            "index": self.index,
            "total": len(self.questions),
            "question": q,
            "score": self.score,
            "max_score": self.max_score,
            "possible_score": float(sum(x.points for x in self.questions)),
            "correct_count": sum(1 for r in self.results if r and r.outcome == Outcome.CORRECT),
            "remaining_s": self.remaining_s(),
            "time_limit_s": self.time_limit(q) if q else 0,
            "last_result": self.last_result,
            "last_answer": self.answers[self.index] if 0 <= self.index < len(self.answers) else None,
            "last_source": self.last_source,
            "results": list(self.results),
        }
