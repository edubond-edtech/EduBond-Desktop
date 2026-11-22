"""Resistor coding of the word plates (reference values, mirrored in firmware/puzzle_controller).

Each socket is a voltage divider:

    3V3 ── plate resistor Rp ──┬── ADC pin
                               └── Rref 10 kΩ ── GND      (+ 100 nF to GND)

    V = 3.3 V · Rref / (Rref + Rp)        empty socket -> 0 V (pulled down by Rref)

Values are picked from the resistors on hand so every plate sits in the ESP32
ADC's usable range (0.25–2.75 V) with at least 320 mV between neighbours.
"""
from __future__ import annotations

VCC_MV = 3300
RREF_OHM = 10_000
EMPTY_BELOW_MV = 150

PLATE_RESISTORS = {1: 2_000, 2: 4_700, 3: 12_000, 4: 20_000, 5: 47_000, 6: 120_000}
PLATE_COLORS = {1: "#e5484d", 2: "#2f6fed", 3: "#2fb86e", 4: "#f5a524", 5: "#8e4ec6", 6: "#12a594"}
PLATE_COLOR_NAMES_AR = {1: "أحمر", 2: "أزرق", 3: "أخضر", 4: "برتقالي", 5: "بنفسجي", 6: "فيروزي"}


def expected_mv(plate: int, vcc_mv: int = VCC_MV, rref: int = RREF_OHM) -> int:
    return round(vcc_mv * rref / (rref + PLATE_RESISTORS[plate]))


def classify_mv(mv: float, table: dict[int, int] | None = None, tolerance_mv: int = 140) -> int | None:
    """Return the plate number for a measured voltage, 0 for empty, None if unrecognised."""
    if mv < EMPTY_BELOW_MV:
        return 0
    table = table or {p: expected_mv(p) for p in PLATE_RESISTORS}
    plate, ref = min(table.items(), key=lambda kv: abs(kv[1] - mv))
    return plate if abs(ref - mv) <= tolerance_mv else None
