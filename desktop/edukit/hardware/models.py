from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LinkState(str, Enum):
    CONNECTING = "connecting"  # transport open, waiting for hello
    ONLINE = "online"
    LOST = "lost"  # heartbeat timeout / unplugged; manager will try to reconnect
    CLOSED = "closed"


@dataclass
class DeviceInfo:
    device_id: str
    role: str
    fw: str = "?"
    proto: int = 1
    boot_id: str = ""
    caps: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceStatus:
    device_id: str
    role: str
    state: LinkState
    transport: str  # "serial" / "sim" / ...
    address: str
    fw: str = "?"
    caps: dict[str, Any] = field(default_factory=dict)
    last_seen: float = 0.0
    rtt_ms: float | None = None


@dataclass
class InputEvent:
    device_id: str
    role: str
    event: str
    data: dict[str, Any]
    received_at: float = field(default_factory=time.monotonic)

    @property
    def question_id(self) -> str | None:
        return self.data.get("question_id")

    @property
    def selected_answer(self) -> str | None:
        return self.data.get("selected_answer")
