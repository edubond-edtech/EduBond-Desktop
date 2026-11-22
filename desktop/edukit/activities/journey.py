"""Game 1 — «رحلة إلى مكة»: answer questions, travel the LED map to Makkah.

Two hardware layouts are supported (chosen per question type):
  * buttons (default): ONE ESP32 ``JOURNEY_01`` = LED route map + 4 answer buttons.
    The PC shows a multiple-choice question; correct -> one green step forward,
    wrong -> one red step back.
  * plates (alternative): resistor-coded word plates on a separate board.

Hardware roles
  * ``puzzle`` — word-plate board. Plates look identical to students; each hides
    a resistor (plate 1..6). The answer key is FIXED in the firmware: socket k
    expects plate k. The teacher writes word k of the sentence on plate k (using
    their own key to recognise the plates). The PC only tells the board which
    sentence is active and how many words it has; when the last socket is filled
    the firmware compares and reports ``puzzle_result``.
  * ``map``    — LED strip on the route map. Each correct arrangement moves the
    travellers one station towards Makkah; reaching Makkah starts the festival.

The PC re-checks every result itself (the firmware verdict is advisory), so a
mis-flashed board can never award a wrong step.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from ..comms import protocol as P
from ..core.events import TimerHandle
from ..core.models import Question
from ..evaluation.evaluator import EvaluationResult, Outcome, evaluate
from ..hardware.models import DeviceStatus, InputEvent, LinkState
from .base import Activity, ActivityContext, register_activity

PUZZLE = P.ROLE_PUZZLE
MAP = P.ROLE_MAP
NUM_SOCKETS = 6
JOURNEY_QTYPES = ("single_choice", "true_false", "arrange")


class JourneyState(str, Enum):
    READY = "ready"
    ASKING = "asking"
    FEEDBACK = "feedback"
    ARRIVED = "arrived"  # reached Makkah — festival (win)
    LOST = "lost"  # question limit used up before reaching Makkah
    STOPPED = "stopped"


@dataclass
class JourneySettings:
    steps_to_makkah: int = 6  # correct answers needed (one per station)
    on_wrong: str = "next"  # "next" question, or "retry" the same one
    step_back_on_wrong: bool = True  # wrong answer moves the travellers one station back (red)
    feedback_seconds: float = 4.0
    shuffle: bool = True
    use_timer: bool = False  # use each question's time limit
    allow_screen_answers: bool = True  # teacher can enter the order on screen (no board)
    festival_seconds: int = 20
    advance_ms: int = 1800  # LED travel animation length
    team_name: str = ""
    max_questions: int = 0  # 0 = unlimited; otherwise the team loses if Makkah is not reached within this many answers
    manual_next_cards: bool = True  # card sentences wait for the teacher's «next» button (time to take the cards out)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "JourneySettings":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@register_activity
class JourneyActivity(Activity):
    type_id = "journey"
    display_name = {"en": "Journey to Makkah", "ar": "رحلة إلى مكة"}

    def __init__(self, ctx: ActivityContext, questions: list[Question], settings: JourneySettings | None = None):
        super().__init__(ctx)
        qs = [q for q in questions if q.qtype in JOURNEY_QTYPES]
        if not qs:
            raise ValueError("لا توجد أسئلة مناسبة للرحلة في هذا البنك / no journey questions in this bank")
        self.settings = settings or JourneySettings()
        self.settings.steps_to_makkah = max(1, min(20, int(self.settings.steps_to_makkah)))
        self.pool = qs
        self.queue: list[Question] = []
        self.current: Question | None = None
        self.state = JourneyState.READY
        self.step = 0
        self.correct_count = 0
        self.wrong_count = 0
        self.attempts = 0  # attempts on the current sentence
        self.answered = 0
        self.board: list[int | None] = [None] * NUM_SOCKETS
        self.board_state = "unknown"  # ready | clear_required | incomplete | unknown
        self.missing: list[int] = []
        self.last_result: EvaluationResult | None = None
        self.last_placed: list[str] = []
        self.last_source: str | None = None
        self.firmware_mismatches = 0
        self.ignored_events = 0
        self.asked_at = 0.0
        self.deadline: float | None = None
        self._pending: InputEvent | None = None
        self._timer: TimerHandle | None = None
        self.last_step_back = False
        self.waiting_next = False  # card sentence judged: waiting for the teacher's «next» button
        self._after_feedback = None  # what «next» does: ask a new sentence or retry this one

    # ---------------------------------------------------------------- helpers
    @property
    def steps(self) -> int:
        return self.settings.steps_to_makkah

    def _next_question(self) -> Question:
        if not self.queue:
            batch = list(self.pool)
            if self.settings.shuffle:
                random.shuffle(batch)
                if self.current is not None and len(batch) > 1 and batch[0].code == self.current.code:
                    batch.append(batch.pop(0))  # never repeat the same sentence back-to-back
            self.queue = batch
        return self.queue.pop(0)

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _later(self, seconds: float, fn) -> None:  # noqa: ANN001
        self._cancel_timer()
        self._timer = self.ctx.scheduler.call_later(seconds, fn)

    def remaining_s(self) -> float | None:
        if self.deadline is None or self.state != JourneyState.ASKING:
            return None
        return max(0.0, self.deadline - self.ctx.scheduler.now())

    def _map(self, command: str, **params: Any) -> None:
        self.ctx.devices.send(MAP, command, **params)

    def mode_of(self, q: Question | None) -> str:
        return "plates" if q is not None and q.qtype == "arrange" else "buttons"

    def buttons_target(self) -> str:
        """The 4 answer buttons live on the map ESP32 (JOURNEY_01); a separate quiz box also works."""
        link = self.ctx.devices.device_for(MAP)
        if link is not None and link.info and link.info.caps.get("buttons"):
            return MAP
        return P.ROLE_INPUT

    def _disarm_all(self) -> None:
        self.ctx.devices.send(PUZZLE, P.C_DISARM)
        self.ctx.devices.send(self.buttons_target(), P.C_DISARM)

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._map(P.C_CONFIGURE, steps=self.steps)
        self._map(P.C_PATH_SET, step=0)
        self._ask(self._next_question())

    def stop(self) -> None:
        self._cancel_timer()
        if self.state not in (JourneyState.ARRIVED, JourneyState.LOST, JourneyState.STOPPED):
            self._disarm_all()
            self.ctx.recorder.finish(float(self.correct_count), float(self.answered))
        self.state = JourneyState.STOPPED
        self._notify()

    def next(self) -> None:
        """Teacher: skip to another sentence (no step change)."""
        if self.state in (JourneyState.ASKING, JourneyState.FEEDBACK):
            self._ask(self._next_question())

    def proceed(self) -> bool:
        """Teacher's «next question» button after a card sentence was judged."""
        if self.state != JourneyState.FEEDBACK or not self.waiting_next or self._after_feedback is None:
            return False
        action, self._after_feedback = self._after_feedback, None
        self.waiting_next = False
        action()
        return True

    def _ask(self, q: Question, retry: bool = False) -> None:
        self._cancel_timer()
        self.waiting_next = False
        self._after_feedback = None
        if not retry:
            self.attempts = 0
            self._pending = None
        self.current = q
        self.state = JourneyState.ASKING
        self.last_result = None
        self.asked_at = self.ctx.scheduler.now()
        limit = q.time_limit_s if self.settings.use_timer else 0
        self.deadline = self.asked_at + limit if limit else None
        self._arm()
        if limit:
            self._timer = self.ctx.scheduler.call_later(limit, self._on_timeout)
        self._notify()
        if retry and self._pending is not None:  # board was completed again during the feedback
            evt, self._pending = self._pending, None
            self.handle_input(evt)

    def _arm(self) -> None:
        q = self.current
        if q is None:
            return
        if self.mode_of(q) == "plates":
            self.ctx.devices.send(PUZZLE, P.C_ARM, question_id=q.code, sockets=len(q.correct))
        else:
            remaining = self.remaining_s()
            self.ctx.devices.send(self.buttons_target(), P.C_ARM, question_id=q.code, options=q.option_keys, timeout_s=int(remaining) if remaining else 0)

    def _on_timeout(self) -> None:
        if self.state == JourneyState.ASKING:
            self._resolve([], "timeout", None, None)

    # ------------------------------------------------------------------ input
    def handle_input(self, event: InputEvent) -> None:
        if event.event == "answer_selected" and event.role in (MAP, P.ROLE_INPUT):
            q = self.current
            if self.state != JourneyState.ASKING or q is None or self.mode_of(q) != "buttons":
                self.ignored_events += 1  # late / duplicate press
                return
            if event.question_id and event.question_id != q.code:
                self.ignored_events += 1  # stale press for an earlier question
                return
            answer = str(event.selected_answer or "").upper()
            if answer not in q.option_keys:
                self.ignored_events += 1
                return
            self._resolve([answer], "device", event.device_id, None)
            return
        if event.role != PUZZLE:
            self.ignored_events += 1
            return
        d = event.data
        if event.event == "plate_inserted":
            if self.board_state == "incomplete":
                self.board_state = "ready"
            s = int(d.get("socket", 0)) - 1
            if 0 <= s < NUM_SOCKETS:
                self.board[s] = int(d.get("plate", 0)) or None
            self._notify()
        elif event.event == "plate_removed":
            s = int(d.get("socket", 0)) - 1
            if 0 <= s < NUM_SOCKETS:
                self.board[s] = None
            self._notify()
        elif event.event == "board_state":
            self.board_state = str(d.get("state", "unknown"))
            self._notify()
        elif event.event == "puzzle_incomplete":
            self.board_state = "incomplete"  # SEND pressed with an empty place
            self.missing = [int(x) for x in d.get("missing", [])]
            self._notify()
        elif event.event == "puzzle_result":
            q = self.current
            if q is None or d.get("question_id") != q.code:
                self.ignored_events += 1  # stale result for an earlier sentence
                return
            if self.state == JourneyState.ASKING:
                placed = [str(x) for x in d.get("placed", [])]
                self._resolve(placed, "device", event.device_id, d.get("result"))
            elif self.state == JourneyState.FEEDBACK and self.settings.on_wrong == "retry" and self.last_result and not self.last_result.is_correct:
                self._pending = event  # students fixed the order while feedback was showing
            else:
                self.ignored_events += 1
        else:
            self.ignored_events += 1

    def submit_from_ui(self, answer: Any, source: str = "screen") -> bool:
        """On-screen answer: an option key ("B") for button questions, or the plate order for plate sentences."""
        if not self.settings.allow_screen_answers or self.state != JourneyState.ASKING or self.current is None:
            return False
        if self.mode_of(self.current) == "buttons":
            key = str(answer).strip().upper()
            if key not in self.current.option_keys:
                return False
            self._resolve([key], source, None, None)
            return True
        placed = [str(x).strip() for x in (answer.split(",") if isinstance(answer, str) else answer)]
        self._resolve(placed, source, None, None)
        return True

    # ---------------------------------------------------------------- results
    def _resolve(self, placed: list[str], source: str, device_id: str | None, device_verdict: str | None) -> None:
        q = self.current
        assert q is not None
        self._cancel_timer()
        if source == "timeout":
            result = EvaluationResult(Outcome.TIMEOUT, 0.0, float(q.points), {"given": [], "expected": list(q.correct), "in_place": 0})
        else:
            result = evaluate(q, placed if self.mode_of(q) == "plates" else placed[0])
            if device_verdict is not None and (device_verdict == "win") != result.is_correct:
                self.firmware_mismatches += 1  # firmware has a different expected order; PC decides
        self.state = JourneyState.FEEDBACK
        self.deadline = None
        self.last_result = result
        self.last_placed = placed
        self.last_source = source
        self.attempts += 1
        self.answered += 1
        response_ms = int((self.ctx.scheduler.now() - self.asked_at) * 1000) if placed else None
        self.ctx.recorder.record(q, ",".join(placed) if placed else None, result, response_ms, source, device_id)

        old = self.step
        self.last_step_back = False
        if result.is_correct:
            self.correct_count += 1
            self.step = min(self.steps, self.step + 1)
            self._map(P.C_PATH_ADVANCE, **{"from": old, "to": self.step, "duration_ms": self.settings.advance_ms})
            self._disarm_all()
        else:
            self.wrong_count += 1
            if self.mode_of(q) == "buttons":
                self.ctx.devices.send(self.buttons_target(), P.C_DISARM)
            if self.settings.step_back_on_wrong and self.step > 0:
                self.step -= 1
                self.last_step_back = True
                self._map(P.C_PATH_BACK, **{"from": old, "to": self.step, "duration_ms": self.settings.advance_ms})
            else:
                self._map(P.C_PATH_FAIL, step=self.step)
        self._notify()

        if self.step >= self.steps:
            self._later(self.settings.advance_ms / 1000 + 0.3, self._arrive)
        elif self.settings.max_questions and self.answered >= self.settings.max_questions:
            self._later(self.settings.feedback_seconds, self._lose)
        else:
            if result.is_correct or self.settings.on_wrong == "next":
                action = lambda: self._ask(self._next_question())  # noqa: E731
            else:
                action = lambda: self._ask(self.current, retry=True)  # type: ignore[arg-type]  # noqa: E731
            if self.mode_of(q) == "plates" and self.settings.manual_next_cards:
                self._after_feedback = action  # students take the cards out; the teacher presses «next»
                self.waiting_next = True
                self._notify()
            else:
                self._later(self.settings.feedback_seconds, action)

    def _arrive(self) -> None:
        self.state = JourneyState.ARRIVED
        self._disarm_all()
        self._map(P.C_FESTIVAL, duration_ms=self.settings.festival_seconds * 1000)
        self.ctx.recorder.finish(float(self.correct_count), float(self.answered))
        self._notify()

    def _lose(self) -> None:
        self.state = JourneyState.LOST
        self._disarm_all()
        self._map(P.C_PATH_FAIL, step=self.step, duration_ms=4000)
        self.ctx.recorder.finish(float(self.correct_count), float(self.answered))
        self._notify()

    def questions_left(self) -> int | None:
        return max(0, self.settings.max_questions - self.answered) if self.settings.max_questions else None

    def on_device_status(self, status: DeviceStatus) -> None:
        if status.state == LinkState.ONLINE:
            if status.role == PUZZLE and self.state == JourneyState.ASKING:
                self.board = [None] * NUM_SOCKETS  # the board re-reports its plates after reconnecting
                self._arm()
            elif status.role == P.ROLE_INPUT and self.state == JourneyState.ASKING and self.mode_of(self.current) == "buttons":
                self._arm()
            elif status.role == MAP and self.state != JourneyState.READY:
                self._map(P.C_CONFIGURE, steps=self.steps)
                if self.state == JourneyState.ASKING and self.mode_of(self.current) == "buttons":
                    self._arm()  # the combined map+buttons board restarted: re-arm its buttons
                if self.state == JourneyState.ARRIVED:
                    self._map(P.C_FESTIVAL, duration_ms=self.settings.festival_seconds * 1000)
                else:
                    self._map(P.C_PATH_SET, step=self.step)
        self._notify()

    # --------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        return {
            "type": self.type_id,
            "mode": self.mode_of(self.current),
            "state": self.state.value,
            "question": self.current,
            "step": self.step,
            "steps": self.steps,
            "board": list(self.board),
            "board_state": self.board_state,
            "last_result": self.last_result,
            "last_placed": list(self.last_placed),
            "last_source": self.last_source,
            "attempts": self.attempts,
            "answered": self.answered,
            "correct_count": self.correct_count,
            "wrong_count": self.wrong_count,
            "team_name": self.settings.team_name,
            "remaining_s": self.remaining_s(),
            "on_wrong": self.settings.on_wrong,
            "last_step_back": self.last_step_back,
            "max_questions": self.settings.max_questions,
            "questions_left": self.questions_left(),
            "waiting_next": self.waiting_next,
        }
