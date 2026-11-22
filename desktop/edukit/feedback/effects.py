"""LED effect catalogue + reference renderer.

The same effect algorithms run in firmware/output_controller/src/main.cpp.
This Python port is used by the hardware simulator and the teacher's effect
preview, so what the teacher sees on screen matches the real strip.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

RGB = tuple[int, int, int]

COLORS: dict[str, RGB] = {
    "off": (0, 0, 0),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 60, 255),
    "yellow": (255, 180, 0),
    "orange": (255, 80, 0),
    "purple": (160, 0, 255),
    "pink": (255, 40, 120),
    "cyan": (0, 220, 255),
}

# Base effects implemented by firmware and renderer.
BASE_EFFECTS = ("off", "solid", "blink", "breathe", "wipe", "chase", "rainbow", "sparkle", "progress", "celebrate")

# Named presets: outcome-oriented aliases with default parameters.
PRESETS: dict[str, dict[str, Any]] = {
    "correct": {"base": "wipe", "color": "green", "duration_ms": 3000},
    "incorrect": {"base": "blink", "color": "red", "duration_ms": 3000},
    "partial": {"base": "breathe", "color": "yellow", "duration_ms": 3000},
    "waiting": {"base": "breathe", "color": "blue", "duration_ms": 0},
    "timeout": {"base": "blink", "color": "orange", "duration_ms": 2000},
    "celebrate": {"base": "celebrate", "color": "white", "duration_ms": 5000},
}

ALL_EFFECT_NAMES = tuple(PRESETS) + tuple(e for e in BASE_EFFECTS if e not in PRESETS)


def parse_color(value: Any, default: RGB = (255, 255, 255)) -> RGB:
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(max(0, min(255, int(v))) for v in value)  # type: ignore[return-value]
    if isinstance(value, str):
        v = value.strip().lower()
        if v in COLORS:
            return COLORS[v]
        if v.startswith("#") and len(v) == 7:
            try:
                return (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))
            except ValueError:
                return default
    return default


def color_to_hex(c: RGB) -> str:
    return "#%02x%02x%02x" % c


@dataclass
class EffectState:
    base: str = "off"
    color: RGB = (0, 0, 0)
    color2: RGB = (0, 0, 0)
    brightness: int = 120  # 0..255
    duration_ms: int = 0  # 0 = until replaced
    speed: int = 5  # 1..10
    value: float = 0.0  # progress 0..1
    started_ms: int = 0
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_command(cls, cmd: dict[str, Any], now_ms: int) -> "EffectState":
        name = str(cmd.get("effect", "solid")).lower()
        preset = PRESETS.get(name, {})
        base = preset.get("base", name)
        if base not in BASE_EFFECTS:
            raise ValueError(f"unknown effect {name!r}")
        return cls(
            base=base,
            color=parse_color(cmd.get("color", preset.get("color")), (255, 255, 255)),
            color2=parse_color(cmd.get("color2"), (0, 0, 0)),
            brightness=max(0, min(255, int(cmd.get("brightness", 120)))),
            duration_ms=max(0, int(cmd.get("duration_ms", preset.get("duration_ms", 0)))),
            speed=max(1, min(10, int(cmd.get("speed", 5)))),
            value=max(0.0, min(1.0, float(cmd.get("value", 0.0)))),
            started_ms=now_ms,
            params=dict(cmd),
        )

    def expired(self, now_ms: int) -> bool:
        return self.duration_ms > 0 and now_ms - self.started_ms >= self.duration_ms


def _hash(n: int) -> int:
    """Small deterministic integer hash (mirrors firmware) for sparkle effects."""
    n = (n ^ 61) ^ (n >> 16)
    n = (n + (n << 3)) & 0xFFFFFFFF
    n ^= n >> 4
    n = (n * 0x27D4EB2D) & 0xFFFFFFFF
    n ^= n >> 15
    return n


def _wheel(pos: int) -> RGB:
    pos = 255 - (pos & 255)
    if pos < 85:
        return (255 - pos * 3, 0, pos * 3)
    if pos < 170:
        pos -= 85
        return (0, pos * 3, 255 - pos * 3)
    pos -= 170
    return (pos * 3, 255 - pos * 3, 0)


def _scale(c: RGB, f: float) -> RGB:
    f = max(0.0, min(1.0, f))
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


def render(state: EffectState, now_ms: int, n: int) -> list[RGB]:
    """Render ``n`` pixels for ``state`` at time ``now_ms`` (brightness applied)."""
    t = max(0, now_ms - state.started_ms)
    unit = max(40, 1600 // state.speed)  # ms; speed 5 -> 320 ms
    c, c2 = state.color, state.color2
    px: list[RGB] = [(0, 0, 0)] * n
    b = state.base
    if b == "off" or n == 0:
        pass
    elif b == "solid":
        px = [c] * n
    elif b == "blink":
        on = (t // (unit // 2 or 1)) % 2 == 0
        px = [c if on else c2] * n
    elif b == "breathe":
        f = 0.15 + 0.85 * (0.5 - 0.5 * math.cos(2 * math.pi * t / (unit * 4)))
        px = [_scale(c, f)] * n
    elif b == "wipe":
        lit = min(n, int(t / max(1, (unit * 2) / n)) + 1) if n else 0
        px = [c if i < lit else c2 for i in range(n)]
    elif b == "chase":
        offset = t // max(1, unit // 4)
        px = [c if (i + offset) % 3 == 0 else c2 for i in range(n)]
    elif b == "rainbow":
        shift = (t * 256 // max(1, unit * 4)) & 255
        px = [_wheel((i * 256 // max(1, n) + shift) & 255) for i in range(n)]
    elif b == "sparkle":
        frame = t // max(1, unit // 4)
        px = [c if _hash(frame * 977 + i) % 6 == 0 else c2 for i in range(n)]
    elif b == "celebrate":
        frame = t // max(1, unit // 4)
        shift = (t * 256 // max(1, unit * 2)) & 255
        px = []
        for i in range(n):
            if _hash(frame * 131 + i * 7) % 5 == 0:
                px.append((255, 255, 255))
            else:
                px.append(_wheel((i * 256 // max(1, n) + shift) & 255))
    elif b == "progress":
        lit = int(round(state.value * n))
        px = [c if i < lit else c2 for i in range(n)]
    f = state.brightness / 255.0
    return [_scale(p, f) for p in px]
