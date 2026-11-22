"""SessionController: glues activities to devices, feedback and the database."""
from __future__ import annotations

from typing import Any, Callable

from ..activities.base import Activity, ActivityContext
from ..activities.journey import JourneyActivity, JourneySettings
from ..activities.quiz import QuizActivity, QuizSettings
from ..core.events import DEVICE_INPUT, DEVICE_STATUS, EventBus, Scheduler, immediate_dispatch
from ..core.models import CHOICE_QTYPES, Question
from ..data.repository import Repository
from ..evaluation.evaluator import EvaluationResult
from ..feedback.engine import FeedbackEngine
from ..hardware.models import DeviceStatus, InputEvent


class DbRecorder:
    def __init__(self, repo: Repository, session_id: int, student_id: int | None):
        self.repo = repo
        self.session_id = session_id
        self.student_id = student_id

    def record(self, question: Question, answer: Any, result: EvaluationResult, response_ms: int | None, source: str, device_id: str | None) -> None:
        self.repo.add_response(self.session_id, self.student_id, question, answer, result.outcome.value, result.score, result.max_score, response_ms, source, device_id)

    def finish(self, total: float, max_score: float) -> None:
        self.repo.finish_session(self.session_id, total, max_score)


class SessionController:
    def __init__(
        self,
        repo: Repository,
        devices: Any,
        feedback: FeedbackEngine,
        bus: EventBus,
        scheduler: Scheduler,
        dispatch: Callable[[Callable[[], None]], None] = immediate_dispatch,
    ):
        self.repo = repo
        self.devices = devices
        self.feedback = feedback
        self.bus = bus
        self.scheduler = scheduler
        self.dispatch = dispatch
        self.activity: Activity | None = None
        self.session_id: int | None = None
        self.hardware_mode = "simulation"
        bus.subscribe(DEVICE_INPUT, self._on_input)
        bus.subscribe(DEVICE_STATUS, self._on_status)

    def _on_input(self, evt: InputEvent) -> None:
        self.dispatch(lambda: self.activity.handle_input(evt) if self.activity else None)

    def _on_status(self, status: DeviceStatus) -> None:
        def run() -> None:
            if self.activity:
                self.activity.on_device_status(status)

        self.dispatch(run)

    def start_quiz(self, bank_id: int, student_id: int | None, class_id: int | None, settings: QuizSettings, questions: list[Question] | None = None) -> QuizActivity:
        self.stop()
        qs = questions if questions is not None else self.repo.list_questions(bank_id)
        qs = [q for q in qs if q.qtype in CHOICE_QTYPES or q.qtype == "numeric"]
        if not qs:
            raise ValueError("The selected question bank has no multiple-choice questions.")
        self.session_id = self.repo.start_session("mcq", bank_id, class_id, student_id, settings.to_dict(), self.hardware_mode)
        ctx = ActivityContext(self.devices, self.feedback, self.scheduler, DbRecorder(self.repo, self.session_id, student_id))
        act = QuizActivity(ctx, qs, settings)
        self.activity = act
        return act

    def stop(self) -> None:
        if self.activity is not None:
            self.activity.stop()
            self.activity = None

    def start_journey(self, bank_id: int | None, student_id: int | None, class_id: int | None, settings: JourneySettings, questions: list[Question] | None = None, team_id: int | None = None) -> JourneyActivity:
        self.stop()
        qs = questions if questions is not None else self.repo.list_questions(bank_id)  # type: ignore[arg-type]
        from ..activities.journey import JOURNEY_QTYPES

        qs = [q for q in qs if q.qtype in JOURNEY_QTYPES]
        if not qs:
            raise ValueError("لا توجد أسئلة مناسبة للرحلة في هذا البنك.")
        self.session_id = self.repo.start_session("journey", bank_id, class_id, student_id, settings.to_dict(), self.hardware_mode, settings.team_name, team_id)
        ctx = ActivityContext(self.devices, self.feedback, self.scheduler, DbRecorder(self.repo, self.session_id, student_id))
        act = JourneyActivity(ctx, qs, settings)
        self.activity = act
        return act
