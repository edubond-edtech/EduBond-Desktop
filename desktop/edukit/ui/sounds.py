"""Offline sound effects: tones are synthesised to WAV files on first run."""
from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

log = logging.getLogger(__name__)

RATE = 22050
# (frequency Hz, duration s) sequences; 0 Hz = silence
MELODIES = {
    "correct": [(660, 0.10), (880, 0.10), (1320, 0.22)],
    "incorrect": [(220, 0.18), (0, 0.04), (180, 0.30)],
    "partial": [(660, 0.12), (740, 0.20)],
    "timeout": [(440, 0.12), (0, 0.05), (440, 0.12), (0, 0.05), (330, 0.3)],
    "celebrate": [(523, 0.1), (659, 0.1), (784, 0.1), (1047, 0.18), (0, 0.05), (784, 0.1), (1047, 0.35)],
    "tick": [(1200, 0.03)],
    # built-in festival tune (used when the teacher has not chosen a nasheed / duaa recording)
    "festival": [(523, 0.18), (659, 0.18), (784, 0.18), (1047, 0.36), (0, 0.06), (988, 0.18), (880, 0.18), (784, 0.36), (0, 0.06),
                 (659, 0.18), (784, 0.18), (880, 0.18), (1047, 0.30), (0, 0.06), (1175, 0.18), (1047, 0.18), (1319, 0.6)],
}


def _write_wav(path: Path, notes: list[tuple[int, float]]) -> None:
    frames = bytearray()
    for freq, dur in notes:
        n = int(RATE * dur)
        for i in range(n):
            env = min(1.0, i / (RATE * 0.01), (n - i) / (RATE * 0.02))  # click-free attack/release
            v = 0.0 if freq == 0 else math.sin(2 * math.pi * freq * i / RATE) * 0.45 * env
            frames += struct.pack("<h", int(v * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


class SoundPlayer:
    def __init__(self, folder: Path):
        self.enabled = True
        self._effects = {}
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
        except Exception as exc:  # QtMultimedia missing on some minimal installs
            log.warning("sound disabled: %s", exc)
            return
        for name, notes in MELODIES.items():
            p = folder / f"{name}.wav"
            if not p.exists() or p.stat().st_size == 0:
                _write_wav(p, notes)
            eff = QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(str(p)))
            eff.setVolume(0.8)
            self._effects[name] = eff

    def path(self, name: str) -> Path | None:
        p = self.folder / f"{name}.wav"
        return p if p.exists() else None

    def play(self, name: str | None) -> None:
        if not name or not self.enabled:
            return
        eff = self._effects.get(name)
        if eff is not None:
            eff.play()
