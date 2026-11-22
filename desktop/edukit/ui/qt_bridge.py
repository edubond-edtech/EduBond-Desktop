"""Qt adapters for the Qt-free core: scheduler, main-thread dispatch, bus bridge."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal, Slot

from ..core.events import EventBus, Scheduler, TimerHandle


class QtScheduler(Scheduler):
    def __init__(self) -> None:
        self._clock = QElapsedTimer()
        self._clock.start()

    def now(self) -> float:
        return self._clock.elapsed() / 1000.0

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle:
        h = TimerHandle()

        def run() -> None:
            if not h.cancelled:
                fn()

        QTimer.singleShot(int(max(0.0, delay_s) * 1000), run)
        return h


class MainThreadDispatcher(QObject):
    """Runs callables on the GUI thread, whatever thread calls ``dispatch``."""

    _call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._call.connect(self._run)

    def dispatch(self, fn: Callable[[], None]) -> None:
        self._call.emit(fn)

    @Slot(object)
    def _run(self, fn: Callable[[], None]) -> None:
        fn()


class BusBridge(QObject):
    """Re-emits EventBus messages as a Qt signal delivered on the GUI thread."""

    message = Signal(str, object)

    def __init__(self, bus: EventBus, topics: list[str]):
        super().__init__()
        for t in topics:
            bus.subscribe(t, lambda payload, t=t: self.message.emit(t, payload))

    def on(self, topic: str, fn: Callable[[Any], None]) -> None:
        self.message.connect(lambda t, p: fn(p) if t == topic else None)
