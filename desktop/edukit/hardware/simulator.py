"""In-process hardware simulator.

Simulated devices speak the *exact* same JSON protocol as the ESP32 firmware
(hello, acks, event sequence numbers, retransmission), so simulation mode
exercises the whole stack: DeviceLink -> DeviceManager -> activity engine.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Callable, Iterable

from ..comms import protocol as P
from ..comms.transport import DiscoverySource, Transport, TransportError
from ..feedback.effects import EffectState, render
from ..feedback.route import RouteConfig, RouteRenderer

FW_VERSION = "sim-1.0.0"


class SimulatedDevice:
    role = "abstract"

    def __init__(self, device_id: str, clock: Callable[[], float] = time.monotonic):
        self.device_id = device_id
        self.clock = clock
        self.plugged_in = True
        self.boot_id = secrets.token_hex(4)
        self.respond = True  # set False to simulate a hung device (no acks / heartbeats)
        self._emit: Callable[[dict[str, Any]], None] | None = None
        self._on_unplug: Callable[[str], None] | None = None
        self.received: list[dict[str, Any]] = []
        self.listeners: list[Callable[[SimulatedDevice], None]] = []
        self._lock = threading.RLock()

    # transport wiring
    def attach(self, emit: Callable[[dict[str, Any]], None], on_unplug: Callable[[str], None]) -> None:
        self._emit, self._on_unplug = emit, on_unplug
        self.reboot()

    def detach(self) -> None:
        self._emit = None
        self._on_unplug = None

    def unplug(self) -> None:
        self.plugged_in = False
        cb = self._on_unplug
        self.detach()
        if cb:
            cb("device unplugged")
        self._changed()

    def plug_in(self) -> None:
        self.plugged_in = True
        self._changed()

    def reboot(self) -> None:
        self.boot_id = secrets.token_hex(4)
        self._send(self.hello())

    def hello(self) -> dict[str, Any]:
        return {
            "type": P.T_HELLO,
            "device_id": self.device_id,
            "role": self.role,
            "fw": FW_VERSION,
            "proto": P.PROTOCOL_VERSION,
            "boot_id": self.boot_id,
            "caps": self.caps(),
        }

    def caps(self) -> dict[str, Any]:
        return {}

    def _send(self, msg: dict[str, Any]) -> None:
        if self._emit and self.respond:
            self._emit(msg)

    def _changed(self) -> None:
        for fn in list(self.listeners):
            fn(self)

    # command handling
    def receive(self, msg: dict[str, Any]) -> None:
        with self._lock:
            self.received.append(msg)
            cmd = msg.get("command")
            mid = msg.get("id")
            if cmd == P.C_ACK:
                self.on_event_ack(int(msg.get("seq", -1)))
                return
            try:
                if cmd == P.C_IDENTIFY:
                    self._send(self.hello())
                elif cmd == P.C_PING:
                    pass
                elif cmd == P.C_SET_ID:
                    new_id = str(msg.get("new_id", "")).strip()
                    if not new_id or len(new_id) > 23:
                        raise ValueError("invalid new_id")
                    self.device_id = new_id
                else:
                    self.handle(cmd, msg)
            except Exception as exc:
                if mid is not None:
                    self._send({"type": P.T_NACK, "id": mid, "error": str(exc)})
                return
            if mid is not None:
                self._send({"type": P.T_ACK, "id": mid})
            if cmd == P.C_SET_ID:
                self._send(self.hello())  # firmware announces its new identity
        self._changed()

    def handle(self, cmd: str, msg: dict[str, Any]) -> None:
        raise ValueError(f"unknown command {cmd}")

    def on_event_ack(self, seq: int) -> None:
        pass


class SimulatedInputDevice(SimulatedDevice):
    role = P.ROLE_INPUT

    def __init__(self, device_id: str = "INPUT_01", channels: int = 4, **kw: Any):
        super().__init__(device_id, **kw)
        self.channels = channels
        self.mapping: dict[int, str] = {i: "ABCDEFGH"[i] for i in range(channels)}
        self.mode = "answer"  # "answer" | "raw"
        self.input_type = "buttons"
        self.armed = False
        self.question_id: str | None = None
        self.allowed: list[str] = []
        self.button_leds: list[bool] = [False] * channels
        self.seq = 0
        self.unacked: dict[int, dict[str, Any]] = {}
        self.lockout_ms = 400
        self._last_press = -1e9

    def caps(self) -> dict[str, Any]:
        return {"channels": self.channels, "buttons": True, "touch": True, "button_leds": True}

    def handle(self, cmd: str, msg: dict[str, Any]) -> None:
        if cmd == P.C_CONFIGURE:
            if "mapping" in msg:
                self.mapping = {int(k): str(v) for k, v in dict(msg["mapping"]).items()}
            self.mode = msg.get("mode", self.mode)
            self.input_type = msg.get("input_type", self.input_type)
            self.lockout_ms = int(msg.get("lockout_ms", self.lockout_ms))
        elif cmd == P.C_ARM:
            self.armed = True
            self.question_id = msg.get("question_id")
            self.allowed = list(msg.get("options") or self.mapping.values())
            self.button_leds = [self.mapping.get(i) in self.allowed for i in range(self.channels)]
        elif cmd == P.C_DISARM:
            self.armed = False
            self.button_leds = [False] * self.channels
        elif cmd == P.C_SET_BUTTON_LEDS:
            states = list(msg.get("states", []))
            self.button_leds = [bool(states[i]) if i < len(states) else False for i in range(self.channels)]
        else:
            super().handle(cmd, msg)

    def press(self, what: str | int) -> bool:
        """Simulate a physical press. ``what`` is a channel index or an answer label."""
        if not self.plugged_in:
            return False
        if isinstance(what, str):
            ch = next((c for c, lbl in self.mapping.items() if lbl == what.upper()), None)
            if ch is None:
                return False
        else:
            ch = what
        now = self.clock()
        if (now - self._last_press) * 1000 < self.lockout_ms:
            return False  # firmware-side repeat guard (after an accepted press)
        if self.mode == "raw":
            self._last_press = now
            self._emit_event({"event": "input_pressed", "channel": ch, "label": self.mapping.get(ch)})
            return True
        label = self.mapping.get(ch)
        if not self.armed or label not in self.allowed:
            return False
        self._last_press = now
        self.armed = False  # one answer per arm: prevents accidental double selection
        self.button_leds = [i == ch for i in range(self.channels)]
        self._emit_event({"event": "answer_selected", "question_id": self.question_id, "selected_answer": label, "channel": ch})
        self._changed()
        return True

    def _emit_event(self, body: dict[str, Any]) -> None:
        self.seq += 1
        msg = {"type": P.T_EVENT, "device_id": self.device_id, "seq": self.seq, **body}
        self.unacked[self.seq] = msg
        self._send(msg)

    def on_event_ack(self, seq: int) -> None:
        self.unacked.pop(seq, None)

    def retransmit_unacked(self) -> int:
        """What the firmware does every 300 ms until acked; exposed for tests."""
        for msg in list(self.unacked.values()):
            self._send(msg)
        return len(self.unacked)


class SimulatedOutputDevice(SimulatedDevice):
    role = P.ROLE_OUTPUT

    def __init__(self, device_id: str = "OUTPUT_01", num_leds: int = 30, **kw: Any):
        super().__init__(device_id, **kw)
        self.num_leds = num_leds
        self.max_brightness = 200
        self.effect = EffectState()
        self.effect_started_wall = time.monotonic()
        self.history: list[dict[str, Any]] = []
        self.buzzes: list[dict[str, Any]] = []
        self.motor_runs: list[dict[str, Any]] = []

    def caps(self) -> dict[str, Any]:
        return {"leds": self.num_leds, "buzzer": True, "motors": 2}

    def handle(self, cmd: str, msg: dict[str, Any]) -> None:
        now_ms = int(time.monotonic() * 1000)
        if cmd == P.C_PLAY_EFFECT or cmd == P.C_PROGRESS:
            m = dict(msg)
            if cmd == P.C_PROGRESS:
                m["effect"] = "progress"
            st = EffectState.from_command(m, now_ms)  # raises on unknown effect -> nack
            st.brightness = min(st.brightness, self.max_brightness)
            self.effect = st
            self.history.append(msg)
        elif cmd == P.C_STOP:
            self.effect = EffectState(started_ms=now_ms)
        elif cmd == P.C_CONFIGURE:
            self.num_leds = int(msg.get("num_leds", self.num_leds))
            self.max_brightness = int(msg.get("max_brightness", self.max_brightness))
        elif cmd == P.C_BUZZ:
            self.buzzes.append(msg)
        elif cmd == P.C_MOTOR:
            self.motor_runs.append(msg)
        else:
            super().handle(cmd, msg)

    def frame(self) -> list[tuple[int, int, int]]:
        now_ms = int(time.monotonic() * 1000)
        if self.effect.expired(now_ms):
            self.effect = EffectState(started_ms=now_ms)
        return render(self.effect, now_ms, self.num_leds)


class SimulatedPuzzleBoard(SimulatedDevice):
    """Word-plate board: 6 sockets, each plate identified by its resistor (plate id "1".."6")."""

    role = P.ROLE_PUZZLE

    def __init__(self, device_id: str = "PUZZLE_01", sockets: int = 6, **kw: Any):
        super().__init__(device_id, **kw)
        self.num_sockets = sockets
        self.sockets: list[str | None] = [None] * sockets
        self.armed = False
        self.question_id: str | None = None
        self.expected: list[str] = []
        self.need_clear = False
        self.judged = False
        self.results: list[dict[str, Any]] = []
        self.seq = 0
        self.unacked: dict[int, dict[str, Any]] = {}

    def caps(self) -> dict[str, Any]:
        return {"sockets": self.num_sockets, "plates": 6, "detect": "resistor", "submit_button": True, "ble": True}

    @property
    def n(self) -> int:
        return len(self.expected) or self.num_sockets

    def handle(self, cmd: str, msg: dict[str, Any]) -> None:
        if cmd == P.C_ARM:
            qid = msg.get("question_id")
            n = int(msg.get("sockets", self.num_sockets))
            if not 1 <= n <= self.num_sockets:
                raise ValueError("sockets must be 1..6")
            # fixed firmware key: socket k expects plate k ("expected" is an advanced override)
            expected = [str(x) for x in (msg.get("expected") or range(1, n + 1))]
            if qid != self.question_id:
                self.need_clear = any(self.sockets)
            self.question_id, self.expected, self.armed = qid, expected, True
            self.judged = False
            self._emit_event({"event": "board_state", "state": "clear_required" if self.need_clear else "ready", "question_id": qid})
        elif cmd == P.C_DISARM:
            self.armed = False
        elif cmd in (P.C_CONFIGURE, "learn_plate"):
            pass
        else:
            super().handle(cmd, msg)

    def insert(self, socket: int, plate: str | int | None) -> None:
        """Plug ``plate`` into ``socket`` (0-based). ``None`` removes the plate."""
        if not self.plugged_in:
            return
        plate = None if plate in (None, "", 0, "0") else str(plate)
        if self.sockets[socket] is not None:
            self.sockets[socket] = None
            self._emit_event({"event": "plate_removed", "socket": socket + 1})
        if plate is not None:
            self.sockets[socket] = plate
            self._emit_event({"event": "plate_inserted", "socket": socket + 1, "plate": int(plate)})
        self._after_change()
        self._changed()

    def clear(self) -> None:
        for i in range(self.num_sockets):
            if self.sockets[i] is not None:
                self.insert(i, None)

    def place_all(self, plates: list[str | int], submit: bool = True) -> None:
        """Lay the cards in sockets 1.., then (by default) press the SEND button."""
        for i, p in enumerate(plates):
            self.insert(i, p)
        if submit:
            self.submit()

    def _after_change(self) -> None:
        self.judged = False  # any change allows a new judgement (same as the firmware)
        if self.need_clear and not any(self.sockets):
            self.need_clear = False
            self._emit_event({"event": "board_state", "state": "ready", "question_id": self.question_id})

    def submit(self) -> bool:
        """The SEND button (GPIO27): judge sockets 1..n; a card in a socket beyond n makes it wrong."""
        if not self.plugged_in:
            return False
        self._emit_event({"event": "submit_pressed"})
        if not self.armed or not self.expected:
            return False
        if self.need_clear:
            self._emit_event({"event": "board_state", "state": "clear_required", "question_id": self.question_id})
            return False
        placed = self.sockets[: self.n]
        if not all(placed):
            self._emit_event({"event": "puzzle_incomplete", "question_id": self.question_id,
                              "missing": [i + 1 for i, p in enumerate(placed) if not p]})
            return False
        if self.judged:
            return False
        self.judged = True
        extra = [int(x) for x in self.sockets[self.n:] if x]
        in_place = sum(1 for a, b in zip(placed, self.expected) if a == b)
        win = in_place == len(self.expected) and not extra
        res = {
            "event": "puzzle_result",
            "question_id": self.question_id,
            "placed": [int(x) for x in placed] + extra,  # type: ignore[arg-type]
            "expected": [int(x) for x in self.expected],
            "in_place": in_place,
            "extra_cards": bool(extra),
            "result": "win" if win else "fail",
        }
        self.armed = False  # one judgement per arm; the PC re-arms for a retry
        self.results.append(res)
        self._emit_event(res)
        return True

    def _emit_event(self, body: dict[str, Any]) -> None:
        self.seq += 1
        msg = {"type": P.T_EVENT, "device_id": self.device_id, "seq": self.seq, **body}
        self.unacked[self.seq] = msg
        self._send(msg)

    def on_event_ack(self, seq: int) -> None:
        self.unacked.pop(seq, None)


class SimulatedMapDevice(SimulatedDevice):
    """LED route map Indonesia -> Makkah, optionally with 4 answer buttons on the same ESP32 (JOURNEY_01)."""

    role = P.ROLE_MAP

    def __init__(self, device_id: str = "MAP_01", num_leds: int = 60, steps: int = 6, buttons: int = 0, **kw: Any):
        super().__init__(device_id, **kw)
        self.renderer = RouteRenderer(RouteConfig(num_leds=num_leds, steps=steps))
        self.history: list[dict[str, Any]] = []
        self.buzzes: list[dict[str, Any]] = []
        self.buttons = buttons
        self.mapping: dict[int, str] = {i: "ABCD"[i] for i in range(buttons)}
        self.armed = False
        self.question_id: str | None = None
        self.allowed: list[str] = []
        self.button_leds: list[bool] = [False] * buttons
        self.seq = 0
        self.unacked: dict[int, dict[str, Any]] = {}
        self.lockout_ms = 400
        self._last_press = -1e9
        self.input_type = "both"
        self.touch_sensitivity = 20

    def caps(self) -> dict[str, Any]:
        c = self.renderer.cfg
        caps: dict[str, Any] = {"leds": c.num_leds, "steps": c.steps, "buzzer": True}
        if self.buttons:
            caps.update({"buttons": self.buttons, "button_leds": True, "touch": True, "input_type": self.input_type})
        return caps

    # -- buttons (same behaviour as the input firmware) ---------------------------------
    def press(self, what: str | int) -> bool:
        if not self.plugged_in or not self.buttons:
            return False
        ch = next((c for c, lbl in self.mapping.items() if lbl == what.upper()), None) if isinstance(what, str) else what
        if ch is None:
            return False
        now = self.clock()
        if (now - self._last_press) * 1000 < self.lockout_ms:
            return False
        label = self.mapping.get(ch)
        if not self.armed or label not in self.allowed:
            return False
        self._last_press = now
        self.armed = False  # one answer per question
        self.button_leds = [i == ch for i in range(self.buttons)]
        self.seq += 1
        msg = {"type": P.T_EVENT, "device_id": self.device_id, "seq": self.seq, "event": "answer_selected",
               "question_id": self.question_id, "selected_answer": label, "channel": ch}
        self.unacked[self.seq] = msg
        self._send(msg)
        self._changed()
        return True

    def on_event_ack(self, seq: int) -> None:
        self.unacked.pop(seq, None)

    @staticmethod
    def _now() -> int:
        return int(time.monotonic() * 1000)

    def handle(self, cmd: str, msg: dict[str, Any]) -> None:
        r, c = self.renderer, self.renderer.cfg
        if cmd in (P.C_ARM, P.C_DISARM) and self.buttons:
            if cmd == P.C_ARM:
                self.armed = True
                self.question_id = msg.get("question_id")
                self.allowed = list(msg.get("options") or self.mapping.values())
                self.button_leds = [self.mapping.get(i) in self.allowed for i in range(self.buttons)]
            else:
                self.armed = False
                self.button_leds = [False] * self.buttons
            return
        if cmd == "calibrate":
            return
        if cmd == "read_touch":
            self.seq += 1
            self._send({"type": P.T_EVENT, "device_id": self.device_id, "seq": self.seq, "event": "touch_readings",
                        "values": [100, 105, 110, 111], "baselines": [100, 105, 110, 111], "touched": [False] * 4,
                        "input_type": self.input_type, "sensitivity": self.touch_sensitivity})
            return
        if cmd == P.C_PATH_BACK:
            r.path_back(int(msg.get("from", 0)), int(msg.get("to", 0)), self._now(), int(msg.get("duration_ms", 1800)))
            self.history.append(msg)
            return
        if cmd == P.C_CONFIGURE:
            self.input_type = msg.get("input_type", self.input_type)
            self.touch_sensitivity = int(msg.get("touch_sensitivity", self.touch_sensitivity))
            if "mapping" in msg and self.buttons:
                self.mapping = {int(k): str(v) for k, v in dict(msg["mapping"]).items()}
            c.num_leds = max(1, min(300, int(msg.get("num_leds", c.num_leds))))
            c.steps = max(1, min(20, int(msg.get("steps", c.steps))))
            c.waypoints = [int(x) for x in msg.get("waypoints", c.waypoints) or []]
            c.brightness = max(1, min(255, int(msg.get("brightness", c.brightness))))
        elif cmd == P.C_PATH_SET:
            r.path_set(int(msg.get("step", 0)), self._now())
        elif cmd == P.C_PATH_ADVANCE:
            r.path_advance(int(msg.get("from", 0)), int(msg.get("to", 0)), self._now(), int(msg.get("duration_ms", 1800)))
        elif cmd == P.C_PATH_FAIL:
            r.path_fail(int(msg.get("step", 0)), self._now(), int(msg.get("duration_ms", 1500)))
        elif cmd == P.C_FESTIVAL:
            r.festival(self._now(), int(msg.get("duration_ms", 10000)))
        elif cmd in (P.C_STOP, P.C_PLAY_EFFECT):
            r.off(self._now())
        elif cmd == P.C_BUZZ:
            self.buzzes.append(msg)
        else:
            super().handle(cmd, msg)
        if cmd != P.C_BUZZ:
            self.history.append(msg)

    def frame(self) -> list[tuple[int, int, int]]:
        return self.renderer.frame(self._now())


def sim_address(device: SimulatedDevice) -> str:
    """Stable 'port name' for a simulated device (survives set_id renames, like a USB port)."""
    if not getattr(device, "_address", None):
        device._address = f"sim:{device.device_id}"  # type: ignore[attr-defined]
    return device._address  # type: ignore[attr-defined]


class SimTransport(Transport):
    kind = "sim"

    def __init__(self, device: SimulatedDevice):
        super().__init__(sim_address(device))
        self.device = device
        self._open = False

    def open(self) -> None:
        if not self.device.plugged_in:
            raise TransportError("simulated device is unplugged")
        self._open = True
        self.device.attach(self._deliver, self._unplugged)

    def _deliver(self, msg: dict[str, Any]) -> None:
        if self._open:
            # round-trip through the real encoder/decoder to catch serialisation bugs
            import json

            self.on_message(json.loads(P.encode(msg)))

    def _unplugged(self, reason: str) -> None:
        if self._open:
            self._open = False
            self.on_closed(reason)

    def send(self, msg: dict[str, Any]) -> None:
        if not self._open:
            raise TransportError(f"{self.name} is not open")
        P.encode(msg)  # size/serialisability check
        self.device.receive(msg)

    def close(self) -> None:
        if self._open:
            self._open = False
            self.device.detach()

    @property
    def is_open(self) -> bool:
        return self._open


class SimulationDiscovery(DiscoverySource):
    def __init__(self, devices: Iterable[SimulatedDevice] = ()):
        self.devices: list[SimulatedDevice] = list(devices)

    def discover(self, busy: set[str]) -> Iterable[Transport]:
        for d in self.devices:
            if d.plugged_in and sim_address(d) not in busy:
                yield SimTransport(d)
