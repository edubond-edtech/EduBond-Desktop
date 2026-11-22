"""Route-map LED renderer for the journey game (Indonesia -> Makkah).

Mirrors firmware/map_controller/src/main.cpp so the simulator and the
teacher's preview look like the real strip on the classroom map.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .effects import _hash

RGB = tuple[int, int, int]

TRAIL: RGB = (0, 200, 60)  # travelled route (green)
GOLD: RGB = (255, 170, 0)  # passed station / Makkah
FUTURE_STATION: RGB = (60, 60, 60)
HINT: RGB = (0, 0, 28)  # route still to travel (faint blue)
HEAD: RGB = (255, 255, 255)  # the travellers
FAIL: RGB = (255, 0, 0)

# Default stations, east -> west (the order of the LED strip)
DEFAULT_STATIONS_AR = ["إندونيسيا", "ماليزيا", "الهند", "عُمان", "اليمن", "جدة", "مكة المكرمة"]


@dataclass
class RouteConfig:
    num_leds: int = 60
    steps: int = 6  # number of correct answers needed to reach Makkah
    waypoints: list[int] = field(default_factory=list)  # optional LED index of each station (steps + 1 values)
    brightness: int = 150

    def pos(self, step: int) -> int:
        step = max(0, min(self.steps, step))
        if len(self.waypoints) == self.steps + 1:
            return max(0, min(self.num_leds - 1, int(self.waypoints[step])))
        return round(step * (self.num_leds - 1) / max(1, self.steps))

    def stations(self) -> set[int]:
        return {self.pos(k) for k in range(self.steps + 1)}


@dataclass
class RouteState:
    mode: str = "path"  # path | advance | fail | festival | off
    step: int = 0
    to_step: int = 0
    started_ms: int = 0
    duration_ms: int = 0


def _scale(c: RGB, f: float) -> RGB:
    f = max(0.0, min(1.0, f))
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


def _breathe(t: int, period: int) -> float:
    return 0.5 - 0.5 * math.cos(2 * math.pi * (t % period) / period)


class RouteRenderer:
    def __init__(self, cfg: RouteConfig | None = None):
        self.cfg = cfg or RouteConfig()
        self.state = RouteState()

    # -- commands (same names/params as the protocol) --------------------------
    def path_set(self, step: int, now_ms: int) -> None:
        self.state = RouteState("path", step, step, now_ms, 0)

    def path_advance(self, from_step: int, to_step: int, now_ms: int, duration_ms: int = 1800) -> None:
        self.state = RouteState("advance", from_step, to_step, now_ms, duration_ms)

    def path_back(self, from_step: int, to_step: int, now_ms: int, duration_ms: int = 1800) -> None:
        self.state = RouteState("back", from_step, to_step, now_ms, duration_ms)

    def path_fail(self, step: int, now_ms: int, duration_ms: int = 1500) -> None:
        self.state = RouteState("fail", step, step, now_ms, duration_ms)

    def festival(self, now_ms: int, duration_ms: int = 10000) -> None:
        self.state = RouteState("festival", self.cfg.steps, self.cfg.steps, now_ms, duration_ms)

    def off(self, now_ms: int) -> None:
        self.state = RouteState("off", self.state.step, self.state.step, now_ms, 0)

    # -- rendering ------------------------------------------------------------------
    def _path(self, step: int, t: int) -> list[RGB]:
        c = self.cfg
        n = c.num_leds
        p = c.pos(step)
        dest = c.pos(c.steps)
        stations = c.stations()
        out: list[RGB] = []
        for i in range(n):
            px = TRAIL if i <= p else HINT
            if i in stations:
                px = GOLD if i <= p else FUTURE_STATION
            if i == dest:
                px = _scale(GOLD, 0.3 + 0.7 * _breathe(t, 2000))
            if i == p:
                px = _scale(HEAD, 0.45 + 0.55 * _breathe(t, 900))
            out.append(px)
        return out

    def frame(self, now_ms: int) -> list[RGB]:
        st = self.state
        t = max(0, now_ms - st.started_ms)
        c = self.cfg
        n = c.num_leds
        if st.duration_ms and t >= st.duration_ms and st.mode in ("advance", "back", "fail", "festival"):
            self.path_set(st.to_step, now_ms)
            st, t = self.state, 0
        if st.mode == "off":
            px = [(0, 0, 0)] * n
        elif st.mode == "path":
            px = self._path(st.step, now_ms)
        elif st.mode == "advance":
            a, b = c.pos(st.step), c.pos(st.to_step)
            frac = min(1.0, t / max(1, st.duration_ms * 0.8))
            head = a + (b - a) * frac
            px = self._path(st.step, now_ms)
            lo, hi = (a, int(head)) if b >= a else (int(math.ceil(head)), a)
            for i in range(max(0, lo), min(n, hi + 1)):
                px[i] = TRAIL
            h = int(round(head))
            for k, f in ((0, 1.0), (1, 0.45), (2, 0.15)):  # comet tail
                j = h - k if b >= a else h + k
                if 0 <= j < n:
                    px[j] = _scale(HEAD, f) if k == 0 else _scale(TRAIL, 1.0 - f / 2)
        elif st.mode == "back":
            # red step back: the lost segment blinks red while a red head slides back
            a, b = c.pos(st.step), c.pos(st.to_step)
            frac = min(1.0, t / max(1, st.duration_ms * 0.8))
            head = a + (b - a) * frac
            px = self._path(st.to_step, now_ms)
            on = (t // 200) % 2 == 0
            for i in range(min(a, b) + 1, max(a, b) + 1):
                if 0 <= i < n:
                    px[i] = FAIL if on else HINT
            h = int(round(head))
            if 0 <= h < n:
                px[h] = FAIL
        elif st.mode == "fail":
            px = self._path(st.step, now_ms)
            if (t // 250) % 2 == 0:
                p = c.pos(st.step)
                for i in range(0, p + 1):
                    px[i] = FAIL
        elif st.mode == "festival":
            px = []
            dest = c.pos(c.steps)
            for i in range(n):
                base = TRAIL if ((i + t // 120) % 4) < 2 else GOLD
                if _hash((t // 80) * 131 + i * 7) % 7 == 0:
                    base = (255, 255, 255)
                if abs(i - dest) <= 2:
                    base = (255, 255, 255) if (t // 200) % 2 == 0 else GOLD
                px.append(base)
        else:
            px = [(0, 0, 0)] * n
        return [_scale(p, c.brightness / 255.0) for p in px]
