"""Activity engine base classes and registry.

An Activity is a self-contained classroom game/lesson. It receives
InputEvents (from any device, via the DeviceManager/EventBus), drives
feedback through the FeedbackEngine and records results through a
ResultRecorder. New activity types register themselves with
``@register_activity`` and need no firmware change: the input firmware can
report raw presses (``mode: "raw"``) and the output firmware renders any
parametrised effect.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..core.events import Scheduler
from ..core.models import Question
from ..evaluation.evaluator import EvaluationResult
from ..feedback.engine import FeedbackEngine
from ..hardware.models import DeviceStatus, InputEvent


class ResultRecorder(Protocol):
    def record(self, question: Question, answer: Any, result: EvaluationResult, response_ms: int | None, source: str, device_id: str | None) -> None: ...

    def finish(self, total: float, max_score: float) -> None: ...


class NullRecorder:
    def __init__(self) -> None:
        self.records: list[tuple] = []
        self.finished: tuple[float, float] | None = None

    def record(self, question, answer, result, response_ms, source, device_id) -> None:  # noqa: ANN001
        self.records.append((question.code, answer, result.outcome.value, result.score, response_ms, source, device_id))

    def finish(self, total: float, max_score: float) -> None:
        self.finished = (total, max_score)


@dataclass
class ActivityContext:
    devices: Any  # DeviceManager
    feedback: FeedbackEngine
    scheduler: Scheduler
    recorder: ResultRecorder


class Activity(ABC):
    type_id: str = "base"
    display_name: dict[str, str] = {"en": "Activity", "ar": "نشاط"}

    def __init__(self, ctx: ActivityContext):
        self.ctx = ctx
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    def add_listener(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        snap = self.snapshot()
        for fn in list(self._listeners):
            fn(snap)

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def handle_input(self, event: InputEvent) -> None: ...

    @abstractmethod
    def snapshot(self) -> dict[str, Any]: ...

    def submit_from_ui(self, answer: Any, source: str = "screen") -> bool:
        return False

    def on_device_status(self, status: DeviceStatus) -> None:
        """Called when a device connects/disconnects (e.g. to re-arm inputs)."""


ACTIVITY_TYPES: dict[str, type[Activity]] = {}


def register_activity(cls: type[Activity]) -> type[Activity]:
    ACTIVITY_TYPES[cls.type_id] = cls
    return cls
