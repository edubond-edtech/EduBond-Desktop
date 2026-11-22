"""Thread-safe publish/subscribe bus plus scheduling/dispatch abstractions.

The core never imports Qt. Hosts provide:
  * a ``Scheduler`` (QtScheduler in the app, ManualScheduler in tests)
  * a ``dispatch`` callable that runs a function on the host's main thread.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# Topics
DEVICE_STATUS = "device.status"  # payload: DeviceStatus
DEVICE_INPUT = "device.input"  # payload: InputEvent
DEVICE_LOG = "device.log"  # payload: (device_name, level, text)
FEEDBACK = "feedback.played"  # payload: (outcome_key, profile_entry)


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, fn: Callable[[Any], None]) -> Callable[[], None]:
        with self._lock:
            self._subs[topic].append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._subs[topic]:
                    self._subs[topic].remove(fn)

        return unsubscribe

    def publish(self, topic: str, payload: Any = None) -> None:
        with self._lock:
            subs = list(self._subs.get(topic, ()))
        for fn in subs:
            try:
                fn(payload)
            except Exception:
                log.exception("subscriber for %s failed", topic)


class TimerHandle:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class Scheduler(ABC):
    @abstractmethod
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle: ...

    @abstractmethod
    def now(self) -> float: ...


@dataclass(order=True)
class _Job:
    due: float
    order: int
    fn: Callable[[], None] = field(compare=False)
    handle: TimerHandle = field(compare=False)


class ManualScheduler(Scheduler):
    """Deterministic scheduler for tests: time only moves when ``advance`` is called."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start
        self._jobs: list[_Job] = []
        self._counter = itertools.count()

    def now(self) -> float:
        return self._now

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle:
        h = TimerHandle()
        heapq.heappush(self._jobs, _Job(self._now + max(0.0, delay_s), next(self._counter), fn, h))
        return h

    def advance(self, seconds: float) -> None:
        target = self._now + seconds
        while self._jobs and self._jobs[0].due <= target:
            job = heapq.heappop(self._jobs)
            self._now = max(self._now, job.due)
            if not job.handle.cancelled:
                job.fn()
        self._now = target


class ThreadScheduler(Scheduler):
    """Simple threading.Timer based scheduler (headless use)."""

    def now(self) -> float:
        return time.monotonic()

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle:
        h = TimerHandle()

        def run() -> None:
            if not h.cancelled:
                fn()

        t = threading.Timer(delay_s, run)
        t.daemon = True
        t.start()
        return h


def immediate_dispatch(fn: Callable[[], None]) -> None:
    fn()
