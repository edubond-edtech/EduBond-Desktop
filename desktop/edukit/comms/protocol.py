"""EduKit wire protocol (v1): newline-delimited JSON (NDJSON) over any byte stream.

Every message is one UTF-8 JSON object terminated by ``\\n``.

PC -> device (commands)::

    {"id": 42, "command": "play_effect", "device_id": "OUTPUT_01", ...params}

    The device answers every command that carries an ``id`` with
    ``{"type": "ack", "id": 42}`` or ``{"type": "nack", "id": 42, "error": "..."}``.

PC -> device (event acknowledgement, no reply expected)::

    {"command": "ack", "seq": 17}

Device -> PC::

    {"type": "hello", "device_id": "INPUT_01", "role": "input", "fw": "1.0.0",
     "proto": 1, "boot_id": "a1b2c3d4", "caps": {...}}
    {"type": "event", "device_id": "INPUT_01", "seq": 17, "event": "answer_selected",
     "question_id": "Q001", "selected_answer": "C"}
    {"type": "ack" | "nack", "id": 42, ...}
    {"type": "log", "level": "info", "msg": "..."}

The full specification lives in docs/PROTOCOL.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
BAUD_RATE = 115200
MAX_LINE_BYTES = 1024

# Device -> PC message types
T_HELLO = "hello"
T_EVENT = "event"
T_ACK = "ack"
T_NACK = "nack"
T_LOG = "log"
INBOUND_TYPES = {T_HELLO, T_EVENT, T_ACK, T_NACK, T_LOG}

# Well-known commands (devices ignore unknown ones with a nack, never crash)
C_IDENTIFY = "identify"
C_PING = "ping"
C_ACK = "ack"
C_CONFIGURE = "configure"
C_ARM = "arm"
C_DISARM = "disarm"
C_SET_BUTTON_LEDS = "set_button_leds"
C_PLAY_EFFECT = "play_effect"
C_STOP = "stop"
C_BUZZ = "buzz"
C_MOTOR = "motor"
C_PROGRESS = "progress"
C_SET_ID = "set_id"

ROLE_INPUT = "input"
ROLE_OUTPUT = "output"
ROLE_PUZZLE = "puzzle"  # word-plate board (resistor-coded plates)
ROLE_MAP = "map"  # LED route map (Indonesia -> Makkah)
KNOWN_ROLES = (ROLE_INPUT, ROLE_OUTPUT, ROLE_PUZZLE, ROLE_MAP, "sensor", "hybrid")

# Journey game commands
C_PATH_SET = "path_set"
C_PATH_ADVANCE = "path_advance"
C_PATH_FAIL = "path_fail"
C_PATH_BACK = "path_back"  # wrong answer: travellers step back with a red animation
C_FESTIVAL = "festival"


class ProtocolError(ValueError):
    """Raised for malformed or invalid protocol messages."""


def encode(msg: dict[str, Any]) -> bytes:
    data = json.dumps(msg, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(data) > MAX_LINE_BYTES:
        raise ProtocolError(f"message too large ({len(data)} bytes > {MAX_LINE_BYTES})")
    return data


def validate_inbound(msg: Any) -> dict[str, Any]:
    """Validate a device->PC message. Returns the message or raises ProtocolError."""
    if not isinstance(msg, dict):
        raise ProtocolError("message is not a JSON object")
    mtype = msg.get("type")
    if mtype not in INBOUND_TYPES:
        raise ProtocolError(f"unknown message type: {mtype!r}")
    if mtype == T_HELLO:
        if not isinstance(msg.get("device_id"), str) or not msg["device_id"]:
            raise ProtocolError("hello without device_id")
        if msg.get("role") not in KNOWN_ROLES:
            raise ProtocolError(f"hello with invalid role: {msg.get('role')!r}")
    elif mtype == T_EVENT:
        if not isinstance(msg.get("seq"), int):
            raise ProtocolError("event without integer seq")
        if not isinstance(msg.get("event"), str):
            raise ProtocolError("event without event name")
    elif mtype in (T_ACK, T_NACK):
        if not isinstance(msg.get("id"), int):
            raise ProtocolError(f"{mtype} without integer id")
    return msg


@dataclass
class Noise:
    """A non-JSON line from the device (e.g. ESP32 ROM boot banner)."""

    text: str


class LineDecoder:
    """Incremental NDJSON decoder tolerant of partial reads, boot noise and overflow."""

    def __init__(self, max_line: int = MAX_LINE_BYTES):
        self._buf = bytearray()
        self._max = max_line
        self._discarding = False

    def feed(self, data: bytes) -> list[dict[str, Any] | Noise]:
        out: list[dict[str, Any] | Noise] = []
        self._buf.extend(data)
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                if len(self._buf) > self._max:
                    # Line too long: drop everything until the next newline.
                    self._buf.clear()
                    self._discarding = True
                    out.append(Noise("<overflow: line discarded>"))
                break
            line = bytes(self._buf[:nl]).strip(b"\r ")
            del self._buf[: nl + 1]
            if self._discarding:
                self._discarding = False
                continue
            if not line:
                continue
            out.append(self._parse(line))
        return out

    @staticmethod
    def _parse(line: bytes) -> dict[str, Any] | Noise:
        text = line.decode("utf-8", errors="replace")
        if not text.startswith("{"):
            return Noise(text)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return Noise(text)
        if not isinstance(obj, dict):
            return Noise(text)
        return obj
