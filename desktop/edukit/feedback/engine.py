"""Feedback engine: maps outcomes ("correct", "waiting", ...) to device commands.

The mapping ("effect profile") is data, edited by the teacher and stored in
SQLite, so changing colours, animations, sounds or motor patterns never needs
a firmware update.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from ..comms import protocol as P
from ..core.events import FEEDBACK, EventBus

FEEDBACK_KEYS = ("waiting", "correct", "incorrect", "partial", "timeout", "celebrate", "idle")

DEFAULT_PROFILE: dict[str, dict[str, Any]] = {
    "waiting": {"led": {"effect": "breathe", "color": "blue", "brightness": 90, "duration_ms": 0, "speed": 4}, "sound": None, "motor": None},
    "correct": {"led": {"effect": "wipe", "color": "green", "brightness": 160, "duration_ms": 3000, "speed": 6}, "sound": "correct", "motor": None},
    "incorrect": {"led": {"effect": "blink", "color": "red", "brightness": 160, "duration_ms": 3000, "speed": 5}, "sound": "incorrect", "motor": {"channel": 0, "speed": 180, "duration_ms": 400}},
    "partial": {"led": {"effect": "breathe", "color": "yellow", "brightness": 150, "duration_ms": 3000, "speed": 6}, "sound": "partial", "motor": None},
    "timeout": {"led": {"effect": "blink", "color": "orange", "brightness": 140, "duration_ms": 2000, "speed": 4}, "sound": "timeout", "motor": None},
    "celebrate": {"led": {"effect": "celebrate", "color": "white", "brightness": 170, "duration_ms": 6000, "speed": 6}, "sound": "celebrate", "motor": None},
    "idle": {"led": {"effect": "off", "duration_ms": 0}, "sound": None, "motor": None},
}


def merged_profile(overrides: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    prof = copy.deepcopy(DEFAULT_PROFILE)
    for key, val in (overrides or {}).items():
        if key in prof and isinstance(val, dict):
            for part, conf in val.items():
                prof[key][part] = conf
    return prof


class FeedbackEngine:
    def __init__(
        self,
        devices: Any,  # DeviceManager (duck-typed: .send(target, command, **params))
        bus: EventBus,
        profile_provider: Callable[[], dict[str, Any]] = lambda: {},
        output_target: str = P.ROLE_OUTPUT,
    ):
        self.devices = devices
        self.bus = bus
        self.profile_provider = profile_provider
        self.output_target = output_target
        self.hardware_sound = True  # also beep on the device buzzer
        self.hardware_motor = True

    def profile(self) -> dict[str, dict[str, Any]]:
        return merged_profile(self.profile_provider())

    def play(self, key: str, **overrides: Any) -> list[Any]:
        """Send the configured feedback for ``key``. Returns command handles (may be empty)."""
        entry = self.profile().get(key)
        if entry is None:
            raise KeyError(f"unknown feedback key {key!r}")
        handles: list[Any] = []
        led = entry.get("led")
        if led:
            params = dict(led)
            params.update(overrides)
            h = self.devices.send(self.output_target, P.C_PLAY_EFFECT, **params)
            if h is not None:
                handles.append(h)
        if self.hardware_sound and entry.get("sound"):
            h = self.devices.send(self.output_target, P.C_BUZZ, pattern=entry["sound"])
            if h is not None:
                handles.append(h)
        if self.hardware_motor and entry.get("motor"):
            h = self.devices.send(self.output_target, P.C_MOTOR, **entry["motor"])
            if h is not None:
                handles.append(h)
        self.bus.publish(FEEDBACK, (key, entry))
        return handles

    def progress(self, fraction: float, color: str = "purple", brightness: int = 120) -> Any:
        return self.devices.send(self.output_target, P.C_PROGRESS, value=round(max(0.0, min(1.0, fraction)), 3), color=color, brightness=brightness)
