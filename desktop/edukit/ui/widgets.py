"""Reusable widgets: LED strip renderer, status dots, round buttons."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

RGB = tuple[int, int, int]


class LedStripWidget(QWidget):
    """Draws a strip of WS2812B pixels; ``frame_fn`` is polled at ~30 fps."""

    def __init__(self, frame_fn: Callable[[], list[RGB]], parent: QWidget | None = None):
        super().__init__(parent)
        self.frame_fn = frame_fn
        self.pixels: list[RGB] = []
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self) -> None:
        if self.isVisible():
            self.pixels = self.frame_fn()
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#1b1f2a"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), 8, 8)
        n = len(self.pixels)
        if not n:
            return
        w = (self.width() - 12) / n
        d = min(w * 0.8, self.height() - 12)
        for i, (r, g, b) in enumerate(self.pixels):
            cx = 6 + w * i + w / 2
            cy = self.height() / 2
            lit = max(r, g, b) > 8
            c = QColor(r, g, b) if lit else QColor("#353b4a")
            if lit:
                grad = QRadialGradient(cx, cy, d)
                glow = QColor(r, g, b)
                glow.setAlpha(90)
                grad.setColorAt(0, glow)
                grad.setColorAt(1, QColor(0, 0, 0, 0))
                p.setBrush(QBrush(grad))
                p.drawEllipse(QRectF(cx - d, cy - d, 2 * d, 2 * d))
            p.setBrush(c)
            p.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))


class StatusDot(QLabel):
    COLORS = {"online": "#2fb86e", "connecting": "#f5a524", "lost": "#e5484d", "closed": "#a9b0bf", "none": "#a9b0bf"}

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self.set_state("none")

    def set_state(self, state: str, detail: str = "") -> None:
        c = self.COLORS.get(state, "#a9b0bf")
        label = f"{self._text} {detail}".strip()
        self.setText(f"<span style='color:{c};font-size:16px'>●</span> {label}")
        self.setToolTip(state)


class RoundButton(QWidget):
    """Arcade-style round button with an illumination ring (simulated hardware)."""

    def __init__(self, label: str, color: str, on_press: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.label, self.color, self.on_press = label, QColor(color), on_press
        self.lit = False
        self.pressed = False
        self.setFixedSize(64, 64)
        self.setCursor(Qt.PointingHandCursor)

    def set_lit(self, lit: bool) -> None:
        if lit != self.lit:
            self.lit = lit
            self.update()

    def mousePressEvent(self, _e) -> None:  # noqa: N802
        self.pressed = True
        self.update()
        self.on_press()

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self.pressed = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ring = QColor(self.color) if self.lit else QColor("#c9ced9")
        p.setPen(QPen(ring, 5))
        base = self.color.darker(140) if self.pressed else (self.color if self.lit else self.color.darker(115))
        p.setBrush(base)
        p.drawEllipse(5, 5, 54, 54)
        p.setPen(QColor("white"))
        f = p.font()
        f.setPointSize(18)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.label)
