"""Feedback effect profile editor with live preview."""
from __future__ import annotations

import time

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...feedback.effects import BASE_EFFECTS, COLORS, EffectState, color_to_hex, parse_color, render
from ...feedback.engine import FEEDBACK_KEYS, merged_profile
from ..sounds import MELODIES
from ..widgets import LedStripWidget

LABELS = {
    "waiting": "Waiting for an answer",
    "correct": "Correct answer",
    "incorrect": "Wrong answer",
    "partial": "Partially correct",
    "timeout": "Time is up",
    "celebrate": "End of quiz celebration",
    "idle": "Idle / lesson ended",
}


class EffectRow(QGroupBox):
    def __init__(self, key: str, entry: dict, on_test):
        super().__init__(LABELS.get(key, key))
        self.key = key
        led = dict(entry.get("led") or {})
        g = QGridLayout(self)
        self.effect = QComboBox()
        self.effect.addItems(list(BASE_EFFECTS))
        self.effect.setCurrentText(led.get("effect", "solid") if led.get("effect") in BASE_EFFECTS else "solid")
        self.color = parse_color(led.get("color"), (255, 255, 255))
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick)
        self._paint_btn()
        self.bright = QSpinBox()
        self.bright.setRange(0, 255)
        self.bright.setValue(int(led.get("brightness", 120)))
        self.duration = QSpinBox()
        self.duration.setRange(0, 60000)
        self.duration.setSingleStep(500)
        self.duration.setSuffix(" ms")
        self.duration.setSpecialValueText("until next")
        self.duration.setValue(int(led.get("duration_ms", 0)))
        self.speed = QSpinBox()
        self.speed.setRange(1, 10)
        self.speed.setValue(int(led.get("speed", 5)))
        self.sound = QComboBox()
        self.sound.addItem("— none —", None)
        for m in MELODIES:
            if m != "tick":
                self.sound.addItem(m, m)
        self.sound.setCurrentIndex(max(0, self.sound.findData(entry.get("sound"))))
        self.motor = QCheckBox("Vibrate")
        self.motor.setChecked(bool(entry.get("motor")))
        self.preview = LedStripWidget(self._frame)
        self.preview.setMinimumHeight(26)
        self._started = int(time.monotonic() * 1000)
        for w in (self.effect, self.bright, self.duration, self.speed):
            (w.currentTextChanged if isinstance(w, QComboBox) else w.valueChanged).connect(self._restart)
        test = QPushButton("Send to device")
        test.clicked.connect(lambda: on_test(self.key, self.to_entry()))
        g.addWidget(QLabel("Animation"), 0, 0)
        g.addWidget(self.effect, 0, 1)
        g.addWidget(QLabel("Colour"), 0, 2)
        g.addWidget(self.color_btn, 0, 3)
        g.addWidget(QLabel("Brightness"), 0, 4)
        g.addWidget(self.bright, 0, 5)
        g.addWidget(QLabel("Duration"), 1, 0)
        g.addWidget(self.duration, 1, 1)
        g.addWidget(QLabel("Speed"), 1, 2)
        g.addWidget(self.speed, 1, 3)
        g.addWidget(QLabel("Sound"), 1, 4)
        g.addWidget(self.sound, 1, 5)
        g.addWidget(self.motor, 1, 6)
        g.addWidget(self.preview, 2, 0, 1, 6)
        g.addWidget(test, 2, 6)

    def _paint_btn(self) -> None:
        name = next((n for n, c in COLORS.items() if c == self.color and n not in ("black",)), color_to_hex(self.color))
        fg = "#000" if sum(self.color) > 380 else "#fff"
        self.color_btn.setText(name)
        self.color_btn.setStyleSheet(f"background: {color_to_hex(self.color)}; color: {fg};")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self.color), self, "LED colour")
        if c.isValid():
            self.color = (c.red(), c.green(), c.blue())
            self._paint_btn()
            self._restart()

    def _restart(self, *_a) -> None:
        self._started = int(time.monotonic() * 1000)

    def _frame(self):
        now = int(time.monotonic() * 1000)
        led = self.to_entry()["led"]
        st = EffectState.from_command({**led, "duration_ms": 0, "value": 0.6}, self._started)
        # loop finite effects in the preview
        if led["duration_ms"] and now - self._started > led["duration_ms"] + 600:
            self._started = now
        return render(st, now, 30)

    def to_entry(self) -> dict:
        return {
            "led": {
                "effect": self.effect.currentText(),
                "color": color_to_hex(self.color),
                "brightness": self.bright.value(),
                "duration_ms": self.duration.value(),
                "speed": self.speed.value(),
            },
            "sound": self.sound.currentData(),
            "motor": {"channel": 0, "speed": 180, "duration_ms": 400} if self.motor.isChecked() else None,
        }


class EffectsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        intro = QLabel("Choose how the LED strip, buzzer and vibration motor react to each outcome. "
                       "Changes are sent as parameters, so no firmware update is needed.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.rows_layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        btns = QHBoxLayout()
        save = QPushButton("Save effects")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(self.reset)
        self.saved_lbl = QLabel()
        self.saved_lbl.setObjectName("Muted")
        btns.addWidget(save)
        btns.addWidget(reset)
        btns.addWidget(self.saved_lbl)
        btns.addStretch(1)
        outer.addLayout(btns)
        self.rows: list[EffectRow] = []
        self.load(merged_profile(ctx.repo.get_setting("effect_profile", {})))

    def load(self, profile: dict) -> None:
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        for key in FEEDBACK_KEYS:
            r = EffectRow(key, profile[key], self._test)
            self.rows.append(r)
            self.rows_layout.addWidget(r)

    def _test(self, key: str, entry: dict) -> None:
        self.ctx.devices.send("output", "play_effect", **entry["led"])
        if entry.get("sound"):
            self.ctx.sounds.play(entry["sound"])
            self.ctx.devices.send("output", "buzz", pattern=entry["sound"])
        if entry.get("motor"):
            self.ctx.devices.send("output", "motor", **entry["motor"])

    def save(self) -> None:
        self.ctx.repo.set_setting("effect_profile", {r.key: r.to_entry() for r in self.rows})
        self.saved_lbl.setText("Saved ✓")

    def reset(self) -> None:
        self.ctx.repo.set_setting("effect_profile", {})
        self.load(merged_profile({}))
        self.saved_lbl.setText("Defaults restored")
