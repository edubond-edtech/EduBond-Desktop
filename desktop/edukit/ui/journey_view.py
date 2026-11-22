"""Projector screen for Game 1 «رحلة إلى مكة» — entirely in Arabic, right-to-left."""
from __future__ import annotations

import math
from pathlib import Path
import random
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..activities.journey import NUM_SOCKETS, JourneyActivity
from ..core.events import DEVICE_STATUS
from ..core.models import Question
from ..feedback.route import DEFAULT_STATIONS_AR
from . import theme
from .theme import Scaled, apply_scale, fs
from .i18n import letter
from .event_audio import EventSounds
from .lang import L, direction
from .speech import speech_settings
from .student_view import OptionCard

AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


def is_video(path: str | None) -> bool:
    return bool(path) and Path(path).suffix.lower() in VIDEO_EXT
DUA = "رَبَّنَا تَقَبَّلْ مِنَّا إِنَّكَ أَنتَ السَّمِيعُ الْعَلِيمُ"


def ar(n: object) -> str:
    """Number in Arabic-Indic digits for the Arabic interface, Western digits for English."""
    from .lang import is_ar

    return str(n).translate(AR_DIGITS) if is_ar() else str(n)


STATIONS_EN = ["Indonesia", "Malaysia", "India", "Oman", "Yemen", "Jeddah", "Makkah"]


def station_names(steps: int) -> list[str]:
    from .lang import is_ar

    names = DEFAULT_STATIONS_AR if is_ar() else STATIONS_EN
    if steps + 1 <= len(names):
        idx = [round(i * (len(names) - 1) / steps) for i in range(steps + 1)]
        return [names[i] for i in idx]
    return [names[0]] + [L(f"المحطة {ar(i)}", f"Station {i}") for i in range(1, steps)] + [names[-1]]


def display_order(code: str, plates: list[int]) -> list[int]:
    """Scrambled, stable display order of the words (plate k holds word k, so never show 1..n)."""
    order = list(plates)
    random.Random(code).shuffle(order)
    if order == sorted(order) and len(order) > 1:
        order = order[1:] + order[:1]
    return order


# ---------------------------------------------------------------------------
class RouteMapWidget(QWidget):
    """Stylised sea/land route from Indonesia (right) to Makkah (left) with animated travellers."""

    def __init__(self) -> None:
        super().__init__()
        self.steps = 6
        self.pos = 0.0  # animated position in steps
        self.fail_flash = 0
        self.festival = False
        self._t = 0
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(1800)
        self.anim.valueChanged.connect(self._on_anim)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self._tick)
        self.clock.start(40)

    def _on_anim(self, v: Any) -> None:
        self.pos = float(v)
        self.update()

    def _tick(self) -> None:
        self._t += 40
        if self.fail_flash > 0:
            self.fail_flash -= 1
        self.update()

    def set_step(self, step: int, steps: int, animate: bool = True) -> None:
        self.steps = max(1, steps)
        if animate and abs(step - self.pos) > 0.01:
            self.anim.stop()
            self.anim.setStartValue(float(self.pos))
            self.anim.setEndValue(float(step))
            self.anim.start()
        elif not animate:
            self.anim.stop()
            self.pos = float(step)
        self.update()

    def flash_fail(self) -> None:
        self.fail_flash = 30

    def _point(self, s: float) -> QPointF:
        w, h = self.width(), self.height()
        margin = 70
        x = w - margin - (w - 2 * margin) * (s / self.steps)  # right -> left
        y = h * 0.52 + math.sin(s / self.steps * math.pi * 2.2) * h * 0.16
        return QPointF(x, y)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        # sea background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#dff1fb"))
        p.drawRoundedRect(r, 26, 26)
        p.setBrush(QColor("#f3e6c4"))  # desert (left) / islands (right)
        p.drawEllipse(QRectF(-r.width() * 0.08, r.height() * 0.05, r.width() * 0.36, r.height() * 1.1))
        p.drawEllipse(QRectF(r.width() * 0.84, r.height() * 0.35, r.width() * 0.22, r.height() * 0.5))

        n = 60
        path = QPainterPath(self._point(0))
        for i in range(1, n + 1):
            path.lineTo(self._point(self.steps * i / n))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#9fb3c8"), 6, Qt.DashLine, Qt.RoundCap))
        p.drawPath(path)

        # travelled trail
        trail = QPainterPath(self._point(0))
        k = max(1, int(n * self.pos / self.steps))
        for i in range(1, k + 1):
            trail.lineTo(self._point(self.pos * i / k))
        col = QColor(theme.BAD) if self.fail_flash and (self.fail_flash // 4) % 2 == 0 else QColor("#1f9d55")
        p.setPen(QPen(col, 9, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(trail)

        names = station_names(self.steps)
        k = max(0.55, min(1.4, self.height() / 330))
        f = QFont()
        f.setPointSize(max(9, round(15 * k)))
        f.setBold(True)
        p.setFont(f)
        for i, name in enumerate(names):
            pt = self._point(i)
            last = i == self.steps
            passed = i <= self.pos + 0.01
            rad = round((22 if last else 13) * k)
            if last:
                glow = 0.5 + 0.5 * math.sin(self._t / 300)
                p.setBrush(QColor(255, 190, 40, int(90 + 120 * glow)) if not self.festival else QColor.fromHsv((self._t // 8) % 360, 200, 255))
                p.setPen(Qt.NoPen)
                p.drawEllipse(pt, rad + round(12 * k), rad + round(12 * k))
            p.setPen(QPen(QColor("white"), 3))
            p.setBrush(QColor("#f5b100") if passed else QColor("#c4ccd8"))
            p.drawEllipse(pt, rad, rad)
            if last:
                ef = QFont(f)
                ef.setPointSize(max(12, round(26 * k)))
                p.setFont(ef)
                p.drawText(QRectF(pt.x() - 30, pt.y() - 22, 60, 44), Qt.AlignCenter, "🕋")
                p.setFont(f)
            p.setPen(QColor(theme.INK))
            up = i % 2 == 0
            tr = QRectF(pt.x() - 80 * k, pt.y() + ((-62 if up else 26) * k), 160 * k, 34 * k)
            p.drawText(tr, Qt.AlignCenter, name)

        # travellers
        tp = self._point(self.pos)
        bob = math.sin(self._t / 180) * 3
        ef = QFont()
        ef.setPointSize(max(12, round(30 * k)))
        p.setFont(ef)
        p.drawText(QRectF(tp.x() - 30 * k, tp.y() - 52 * k + bob, 60 * k, 50 * k), Qt.AlignCenter, "🐪" if self.pos > self.steps * 0.6 else "⛵")


class Confetti(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.parts: list[list[float]] = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)

    def burst(self) -> None:
        self.setGeometry(self.parent().rect())
        w = max(1, self.width())
        cols = ["#f5b100", "#2fb86e", "#ffffff", "#e5484d", "#2f6fed", "#8e4ec6"]
        self.parts = [[random.uniform(0, w), random.uniform(-400, 0), random.uniform(-1.5, 1.5), random.uniform(3, 7), random.randrange(len(cols)), random.uniform(0, 6.3)] for _ in range(220)]
        self._cols = [QColor(c) for c in cols]
        self.show()
        self.raise_()
        self.timer.start(30)

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def _step(self) -> None:
        h = self.height()
        for pt in self.parts:
            pt[0] += pt[2]
            pt[1] += pt[3]
            pt[5] += 0.15
            if pt[1] > h:
                pt[1] = random.uniform(-60, 0)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        for x, y, _vx, _vy, c, a in self.parts:
            p.setBrush(self._cols[c])
            p.drawRect(QRectF(x, y, 10, 5 + 5 * abs(math.sin(a))))


# ---------------------------------------------------------------------------
class PlateCard(Scaled, QFrame):
    def __init__(self, on_click: Callable[[int], None]):
        super().__init__()
        self.plate = 0
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(fs(56))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.num = QLabel()
        self.num.setFixedSize(36, 36)
        self.num.setAlignment(Qt.AlignCenter)
        self.word = QLabel()
        self.word.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.num)
        lay.addWidget(self.word, 1)

    def set_plate(self, plate: int, word: str, used: bool = False) -> None:
        # All plates look the same to the students: no number, no colour.
        self.plate = plate
        self.num.hide()
        self.word.setText(word)
        self._style(self.word, lambda: f"color: {'#b9ad8f' if used else '#3b2f12'}; font-size: {fs(34)}px; font-weight: 800;")
        bg, border = ("#f4efe2", "#e2d8bd") if used else ("#fff4d6", "#c9a227")
        self.setStyleSheet(f"PlateCard {{ background: {bg}; border-radius: 18px; border: 3px solid {border}; }}")

    def _rescale(self) -> None:
        self.setMinimumHeight(fs(56))

    def mousePressEvent(self, _e) -> None:  # noqa: N802
        self.on_click(self.plate)


class SocketBox(Scaled, QFrame):
    def __init__(self, index: int, on_click: Callable[[int], None]):
        super().__init__()
        self.index = index
        self.on_click = on_click
        self.setMinimumHeight(fs(64))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.lbl = QLabel(L(f"المقبس {ar(index + 1)}", f"Socket {index + 1}"))
        self.lbl.setAlignment(Qt.AlignCenter)
        self._style(self.lbl, lambda: f"color: {theme.MUTED}; font-size: {fs(15)}px; font-weight: 700;")
        self.word = QLabel()
        self.word.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl)
        lay.addWidget(self.word, 1)
        self.set_content(None, "", None)

    def set_content(self, plate: int | None, word: str, state: str | None) -> None:
        if plate:
            border = {"ok": theme.OK, "bad": theme.BAD}.get(state or "", "#c9a227")
            self.setStyleSheet(f"SocketBox {{ background: #fff4d6; border: 5px solid {border}; border-radius: 16px; }}")
            self.word.setText(word or "؟")
            self._style(self.word, lambda: f"color: #3b2f12; font-size: {fs(30)}px; font-weight: 800;")
        else:
            self.setStyleSheet("SocketBox { background: #ffffff; border: 3px dashed #b8c0cf; border-radius: 16px; }")
            self.word.setText("")
        self._style(self.lbl, lambda: f"color: {theme.MUTED}; font-size: {fs(15)}px; font-weight: 700;")

    def _rescale(self) -> None:
        self.setMinimumHeight(fs(64))

    def mousePressEvent(self, _e) -> None:  # noqa: N802
        self.on_click(self.index)


# ---------------------------------------------------------------------------
class JourneyView(Scaled, QWidget):
    def __init__(self, ctx, on_exit: Callable[[], None]):
        super().__init__()
        self.ctx = ctx
        self.on_exit = on_exit
        self.activity: JourneyActivity | None = None
        self.snap: dict[str, Any] = {}
        self.screen_board: list[int | None] = [None] * NUM_SOCKETS  # used only when no board is connected
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        self._build()
        ctx.bridge.on(DEVICE_STATUS, lambda _s: self._render_status())
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._exit)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=lambda: self.activity and self.activity.proceed())  # «next question»
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._render_timer)
        self._tick.start(250)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 14, 24, 14)
        root.setSpacing(10)
        top = QHBoxLayout()
        self.team = QLabel()
        self._style(self.team, lambda: f"font-size: {fs(24)}px; font-weight: 800;")
        self.progress = QLabel()
        self._style(self.progress, lambda: f"font-size: {fs(20)}px; color: {theme.MUTED}; font-weight: 700;")
        self.score = QLabel()
        self._style(self.score, lambda: f"background: {theme.BRAND_PURPLE}; color: white; border-radius: 16px; padding: 6px 16px; font-size: {fs(20)}px; font-weight: 800;")
        self.skip_btn = QPushButton(L("جملة أخرى ⏭", "Another sentence ⏭"))
        self.skip_btn.clicked.connect(lambda: self.activity and self.activity.next())
        self.end_btn = QPushButton(L("إنهاء", "End"))
        self.end_btn.setObjectName("Danger")
        self.end_btn.clicked.connect(self._exit)
        self.brand = QLabel()
        _pm = QPixmap(theme.asset("edubond_logo.png"))
        if not _pm.isNull():
            self._brand_pm = _pm
            self.brand.setPixmap(_pm.scaledToHeight(40, Qt.SmoothTransformation))
        top.addWidget(self.brand)
        top.addSpacing(12)
        top.addWidget(self.team)
        top.addSpacing(16)
        top.addWidget(self.progress)
        top.addStretch(1)
        top.addWidget(self.score)
        top.addWidget(self.skip_btn)
        top.addWidget(self.end_btn)
        root.addLayout(top)

        self.map = RouteMapWidget()  # no longer shown: the real LED map tracks the journey
        self.map.setParent(self)
        self.map.hide()
        # --- media area above the question: picture or video
        self.media_box = QStackedWidget()
        self.media_box.setMinimumHeight(60)
        self.media_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.q_image = QLabel()
        self.q_image.setAlignment(Qt.AlignCenter)
        self.q_image.setStyleSheet("background: white; border-radius: 22px;")
        self.media_box.addWidget(self.q_image)
        vid_page = QWidget()
        vl = QVBoxLayout(vid_page)
        vl.setContentsMargins(0, 0, 0, 0)
        self.video = None
        self.player = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self.video = QVideoWidget()
            self.player = QMediaPlayer(self)
            self._video_audio = QAudioOutput(self)
            self.player.setAudioOutput(self._video_audio)
            self.player.setVideoOutput(self.video)
            vl.addWidget(self.video, 1)
        except Exception:  # multimedia widgets missing: pictures still work
            vl.addWidget(QLabel(L("لا يمكن تشغيل الفيديو على هذا الجهاز", "Video playback is not available on this computer")))
        self.replay_btn = QPushButton(L("🔁 إعادة تشغيل الفيديو", "🔁 Replay video"))
        self.replay_btn.clicked.connect(self._replay_video)
        vl.addWidget(self.replay_btn, 0, Qt.AlignCenter)
        self.media_box.addWidget(vid_page)
        # page 2: shown when the question has no picture/video — the area stays in place
        ph = QWidget()
        ph.setObjectName("MediaPlaceholder")
        ph.setAttribute(Qt.WA_StyledBackground, True)
        ph.setStyleSheet(f"#MediaPlaceholder {{ background: white; border-radius: 22px; border: 3px dashed {theme.BRAND_TEAL}; }}")
        pl = QVBoxLayout(ph)
        self.ph_logo = QLabel()
        self.ph_logo.setAlignment(Qt.AlignCenter)
        self.ph_text = QLabel()
        self.ph_text.setAlignment(Qt.AlignCenter)
        self.ph_text.setStyleSheet(f"color: {theme.BRAND_PURPLE}; font-size: 22px; font-weight: 800;")
        pl.addStretch(1)
        pl.addWidget(self.ph_logo)
        pl.addWidget(self.ph_text)
        pl.addStretch(1)
        self.media_box.addWidget(ph)
        self._pixmap: QPixmap | None = None
        self._pixmap_for: str | None = None
        self._video_for: str | None = None
        root.addWidget(self.media_box, 3)

        self.pages = QStackedLayout()
        root.addLayout(self.pages, 4)

        # --- play page
        play = QWidget()
        pl = QVBoxLayout(play)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.instruction = QLabel()
        self.instruction.setAlignment(Qt.AlignCenter)
        self._style(self.instruction, lambda: f"font-size: {fs(34)}px; font-weight: 900;")
        pl.addWidget(self.instruction)
        # --- buttons mode: question + 4 answers (colours = physical buttons)
        self.choice_box = QWidget()
        cg = QGridLayout(self.choice_box)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(16)
        self.choice_cards: dict[str, OptionCard] = {}
        for i, k in enumerate("ABCD"):
            card = OptionCard(k, self._choice_clicked)
            self.choice_cards[k] = card
            cg.addWidget(card, i // 2, i % 2)
        pl.addWidget(self.choice_box, 1)
        # --- plates mode
        self.plates_box = QWidget()
        pb = QVBoxLayout(self.plates_box)
        pb.setContentsMargins(0, 0, 0, 0)
        self.plates_row = QHBoxLayout()
        self.plates_row.setSpacing(12)
        self.plate_cards = [PlateCard(self._plate_clicked) for _ in range(NUM_SOCKETS)]
        for c in self.plate_cards:
            self.plates_row.addWidget(c)
        pb.addLayout(self.plates_row)
        arrow = QLabel("⬇")
        arrow.setAlignment(Qt.AlignCenter)
        self._style(arrow, lambda: f"font-size: {fs(22)}px; color: {theme.MUTED};")
        pb.addWidget(arrow)
        self.sockets_row = QHBoxLayout()
        self.sockets_row.setSpacing(12)
        self.socket_boxes = [SocketBox(i, self._socket_clicked) for i in range(NUM_SOCKETS)]
        for b in self.socket_boxes:
            self.sockets_row.addWidget(b)
        pb.addLayout(self.sockets_row)
        pl.addWidget(self.plates_box)
        self.banner = QLabel()
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setWordWrap(True)
        self.banner.setMinimumHeight(40)
        pl.addWidget(self.banner)
        self.next_btn = QPushButton(L("السؤال التالي ⏭", "Next question ⏭"))
        self.next_btn.setObjectName("Primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self._style(self.next_btn, lambda: f"font-size: {fs(28)}px; font-weight: 900; padding: 12px 40px; border-radius: 18px; background: {theme.BRAND_PURPLE}; color: white;")
        self.next_btn.clicked.connect(lambda: self.activity and self.activity.proceed())
        self.next_btn.hide()
        pl.addWidget(self.next_btn, 0, Qt.AlignCenter)
        bottom = QHBoxLayout()
        self.board_dot = QLabel()
        self.map_dot = QLabel()
        self.timer_lbl = QLabel()
        self._style(self.timer_lbl, lambda: f"font-size: {fs(18)}px; font-weight: 700; color: {theme.MUTED};")
        bottom.addWidget(self.board_dot)
        bottom.addSpacing(16)
        bottom.addWidget(self.map_dot)
        bottom.addStretch(1)
        bottom.addWidget(self.timer_lbl)
        pl.addLayout(bottom)
        self.pages.addWidget(play)

        # --- arrival page
        done = QWidget()
        dl = QVBoxLayout(done)
        dl.addStretch(1)
        self.arr_title = QLabel(L("مبارك! وصلتم إلى مكة المكرمة 🎉", "Congratulations! You reached Makkah 🎉"))
        self.arr_title.setAlignment(Qt.AlignCenter)
        self._style(self.arr_title, lambda: f"font-size: {fs(54)}px; font-weight: 900; color: #1f7a45;")
        self.arr_dua = QLabel(DUA)
        self.arr_dua.setAlignment(Qt.AlignCenter)
        self._style(self.arr_dua, lambda: f"font-size: {fs(40)}px; font-weight: 700; color: #a87400;")
        self.arr_stats = QLabel()
        self.arr_stats.setAlignment(Qt.AlignCenter)
        self._style(self.arr_stats, lambda: f"font-size: {fs(26)}px; font-weight: 700;")
        btns = QHBoxLayout()
        again = QPushButton(L("🔊 إعادة الاحتفال", "🔊 Replay celebration"))
        self.again_btn = again
        again.clicked.connect(lambda: self._event_sound("win" if self.snap.get("state") == "arrived" else "lose"))
        back = QPushButton(L("العودة إلى لوحة المعلم", "Back to the teacher dashboard"))
        back.setObjectName("Primary")
        back.clicked.connect(self._exit)
        btns.addStretch(1)
        btns.addWidget(again)
        btns.addWidget(back)
        btns.addStretch(1)
        for w in (self.arr_title, self.arr_dua, self.arr_stats):
            dl.addWidget(w)
        dl.addSpacing(16)
        dl.addLayout(btns)
        dl.addStretch(1)
        self.pages.addWidget(done)
        self.confetti = Confetti(self)
        self.confetti.hide()

    # ----------------------------------------------------------------- binding
    def bind(self, activity: JourneyActivity) -> None:
        self.activity = activity
        self.screen_board = [None] * NUM_SOCKETS
        self.confetti.stop()
        self.ctx.media.stop()
        activity.add_listener(self._on_snapshot)
        self.snap = activity.snapshot()
        self.map.festival = False
        self.map.set_step(0, activity.steps, animate=False)
        self.render()

    def _on_snapshot(self, snap: dict[str, Any]) -> None:
        prev = self.snap
        self.snap = snap
        if snap["step"] != prev.get("step"):
            self.map.anim.setDuration(self.activity.settings.advance_ms if self.activity else 1800)
            self.map.set_step(snap["step"], snap["steps"])
        if snap["state"] == "feedback" and prev.get("state") != "feedback":
            res = snap["last_result"]
            ok = bool(res and res.is_correct)
            if not ok and snap["step"] == prev.get("step"):
                self.map.flash_fail()
            outcome = res.outcome.value if res else "timeout"
            if snap["step"] < snap["steps"] or not ok:  # on the final step the «win» sound plays instead
                self._event_sound("correct" if ok else ("timeout" if outcome == "timeout" else "wrong"))
            self.screen_board = [None] * NUM_SOCKETS
        if snap["state"] == "asking" and prev.get("question") is not snap.get("question"):
            self.screen_board = [None] * NUM_SOCKETS
            first = prev.get("state") in (None, "ready")
            used = self._event_sound("start" if first else "question")
            sp = self._speech()
            if used in ("none", "tone") and sp["enabled"] and sp["read_question"] and snap.get("question") is not None:
                q = snap["question"]
                text = q.text("ar")
                if snap.get("mode") == "buttons":
                    text += "، " + "، ".join(f"{letter(o.key, 'ar')}: {o.label('ar')}" for o in q.options)
                self.ctx.speaker.say(text, sp["rate"])
        if snap["state"] == "arrived" and prev.get("state") != "arrived":
            self.map.festival = True
            self.confetti.burst()
            if self._event_sound("win") == "speech":  # spoken congratulations, then the festive tune
                QTimer.singleShot(3000, lambda: self.ctx.media.play(self.ctx.sounds.path("festival")))
        if snap["state"] == "lost" and prev.get("state") != "lost":
            self._event_sound("lose")
        self.render()

    def _speech(self) -> dict[str, Any]:
        return speech_settings(self.ctx.repo.get_setting("journey_speech", {}))

    def _event_sound(self, event: str) -> str:
        """Imported / recorded file > spoken Arabic phrase > built-in tone (see «أصوات الأحداث»)."""
        return EventSounds(self.ctx).play(event)

    def _choice_clicked(self, key: str) -> None:
        a = self.activity
        if a and self.snap.get("state") == "asking" and self.snap.get("mode") == "buttons" and a.settings.allow_screen_answers:
            a.submit_from_ui(key, "screen")

    def _exit(self) -> None:
        self._stop_video()
        self.ctx.media.stop()
        self.ctx.speaker.stop()
        self.confetti.stop()
        self.ctx.sessions.stop()
        self.activity = None
        self.on_exit()

    # ------------------------------------------------- on-screen play (no board)
    def _board_online(self) -> bool:
        return self.ctx.devices.device_for("puzzle") is not None

    def _plate_clicked(self, plate: int) -> None:
        a = self.activity
        if not a or self._board_online() or self.snap.get("state") != "asking" or not a.settings.allow_screen_answers:
            return
        q: Question = self.snap["question"]
        n = len(q.correct)
        if plate in self.screen_board:
            return
        for i in range(n):
            if self.screen_board[i] is None:
                self.screen_board[i] = plate
                break
        self.render()
        if all(self.screen_board[:n]):
            a.submit_from_ui([str(p) for p in self.screen_board[:n]], "screen")

    def _socket_clicked(self, index: int) -> None:
        if not self._board_online() and self.snap.get("state") == "asking":
            self.screen_board[index] = None
            self.render()

    # ------------------------------------------------------------------ render
    def render(self) -> None:
        s = self.snap
        if not s:
            return
        self.team.setText("👥 " + (s.get("team_name") or L("الفريق", "Team")))
        names = station_names(s["steps"])
        here = names[min(s["step"], len(names) - 1)]
        left = s.get("questions_left")
        extra = L(f"   ·   الأسئلة المتبقية: {ar(left)}", f"   ·   Questions left: {left}") if left is not None else ""
        self.progress.setText(L(f"المحطة {ar(s['step'])} من {ar(s['steps'])} — {here}{extra}", f"Station {s['step']} of {s['steps']} — {here}{extra}"))
        self.score.setText(f"✔ {ar(s['correct_count'])}")
        if s["state"] in ("arrived", "lost", "stopped"):
            self.pages.setCurrentIndex(1)
            self.media_box.hide()
            self._stop_video()
            if s["state"] == "stopped":
                self.arr_title.setText(L("انتهت الرحلة", "The journey has ended"))
                self.arr_dua.setText("")
            elif s["state"] == "lost":
                self.arr_title.setText(L("انتهت الأسئلة قبل الوصول إلى مكة", "Questions ran out before reaching Makkah"))
                self.arr_dua.setText(L("لا بأس — حاولوا مرة أخرى، والرحلة تنتظركم 🌙", "Never mind — try again, the journey is waiting for you 🌙"))
            else:
                self.arr_title.setText(L("مبارك! وصلتم إلى مكة المكرمة 🎉", "Congratulations! You reached Makkah 🎉"))
                self.arr_dua.setText(DUA)
            self.again_btn.setText(L("🔊 إعادة الصوت", "🔊 Replay sound") if s["state"] == "lost" else L("🔊 إعادة الاحتفال", "🔊 Replay celebration"))
            self.again_btn.setVisible(s["state"] != "stopped")
            color = "#c0392b" if s["state"] == "lost" else "#1f7a45"
            self._style(self.arr_title, lambda: f"font-size: {fs(54)}px; font-weight: 900; color: {color};")
            self.arr_stats.setText(L(f"إجابات صحيحة: {ar(s['correct_count'])}   ·   محاولات: {ar(s['answered'])}", f"Correct answers: {s['correct_count']}   ·   Attempts: {s['answered']}"))
            self.skip_btn.setVisible(False)
            self.next_btn.hide()
            return
        self.pages.setCurrentIndex(0)
        self.skip_btn.setVisible(True)
        q: Question | None = s["question"]
        if q is None:
            return
        buttons_mode = s.get("mode") == "buttons"
        waiting = bool(s.get("waiting_next"))
        self.next_btn.setVisible(waiting)
        if waiting:
            retry = s["last_result"] is not None and not s["last_result"].is_correct and s.get("on_wrong") == "retry"
            self.next_btn.setText(L("حاولوا مرة أخرى 🔁", "Try again 🔁") if retry else L("السؤال التالي ⏭", "Next question ⏭"))
        self._render_image(q)
        self.skip_btn.setText(L("سؤال آخر ⏭", "Another question ⏭") if buttons_mode else L("جملة أخرى ⏭", "Another sentence ⏭"))
        self.choice_box.setVisible(buttons_mode)
        self.plates_box.setVisible(not buttons_mode)
        if buttons_mode:
            self._render_choice(s, q)
            self._render_banner(s, q)
            self._render_status()
            return
        self.instruction.setText(q.prompt.get("ar") or "رتّب الكلمات لتكوّن جملة صحيحة")
        self._style(self.instruction, lambda: f"font-size: {fs(34)}px; font-weight: 900;")
        words = {int(o.key): o.label("ar") for o in q.options}
        n = len(q.correct)
        board = s["board"] if self._board_online() else self.screen_board
        used = {p for p in board[:NUM_SOCKETS] if p}
        plates = display_order(q.code, sorted(words))
        for i, card in enumerate(self.plate_cards):
            if i < len(plates):
                card.set_plate(plates[i], words[plates[i]], used=plates[i] in used)
                card.show()
            else:
                card.hide()
        res = s["last_result"]
        feedback = s["state"] == "feedback"
        expected = [int(k) for k in q.correct]
        for i, box in enumerate(self.socket_boxes):
            box.setVisible(i < n)
            plate = board[i] if i < len(board) else None
            st = None
            if feedback and res is not None and i < len(s["last_placed"]):
                st = "ok" if s["last_placed"][i] == str(expected[i]) else "bad"
            box.set_content(plate, words.get(plate or 0, ""), st)
        self._render_banner(s, q)
        self._render_status()

    def _image_path(self, q: Question) -> str | None:
        if not q.image_path:
            return None
        p = Path(q.image_path)
        if not p.is_absolute():
            p = self.ctx.data_dir / "images" / q.image_path
        return str(p) if p.exists() else None

    def _render_image(self, q: Question) -> None:
        """The question's picture or video fills the area above the question."""
        path = self._image_path(q)
        self.media_box.show()  # the picture / video area is always at the top of the screen
        if not path:
            self._pixmap_for = None
            self._stop_video()
            self.media_box.setCurrentIndex(2)
            self._fit_placeholder()
            return
        if is_video(path):
            self.media_box.setCurrentIndex(1)
            if self._video_for != path and self.player is not None:
                from PySide6.QtCore import QUrl

                self._video_for = path
                self.player.setSource(QUrl.fromLocalFile(path))
                self.player.play()
            return
        self._stop_video()
        self.media_box.setCurrentIndex(0)
        if self._pixmap_for != path:
            self._pixmap = QPixmap(path)
            self._pixmap_for = path
        self._fit_image()

    def _fit_placeholder(self) -> None:
        """No picture/video for this question: show the EduBond logo and where the journey is."""
        pm = getattr(self, "_brand_pm", None)
        if pm is not None and not pm.isNull():
            h = max(40, min(int(self.media_box.height() * 0.55), 220))
            self.ph_logo.setPixmap(pm.scaledToHeight(h, Qt.SmoothTransformation))
        s = self.snap
        if s:
            names = station_names(s["steps"])
            here = names[min(s["step"], len(names) - 1)]
            self.ph_text.setText(L(f"📍 أنتم الآن في: {here}", f"📍 You are now in: {here}"))

    def _replay_video(self) -> None:
        if self.player is not None and self._video_for:
            self.player.setPosition(0)
            self.player.play()

    def _stop_video(self) -> None:
        if self.player is not None and self._video_for:
            self.player.stop()
        self._video_for = None

    def _fit_image(self) -> None:
        if self._pixmap is None or self._pixmap.isNull() or not self.media_box.isVisible() or self.media_box.currentIndex() != 0:
            return
        w, h = max(10, self.q_image.width() - 16), max(10, self.q_image.height() - 16)
        self.q_image.setPixmap(self._pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _render_choice(self, s: dict[str, Any], q: Question) -> None:
        self.instruction.setText(q.text("ar"))
        self._style(self.instruction, lambda: f"font-size: {fs(44)}px; font-weight: 900;")
        self.instruction.setWordWrap(True)
        feedback = s["state"] == "feedback"
        given = (s["last_placed"] or [""])[0] if feedback else ""
        correct = set(q.correct if isinstance(q.correct, list) else [])
        for k, card in self.choice_cards.items():
            opt = next((o for o in q.options if o.key == k), None)
            card.setVisible(opt is not None)
            if opt is None:
                continue
            card.set_content(letter(k, "ar"), opt.label("ar"))
            if not feedback:
                card.set_style("normal")
            elif k == given:
                card.set_style("correct" if k in correct else "wrong")
            elif k in correct:
                card.set_style("correct")
            else:
                card.set_style("dim")

    def _render_banner(self, s: dict[str, Any], q: Question) -> None:
        if s.get("mode") == "buttons":
            if s["state"] == "feedback" and s["last_result"] is not None:
                res = s["last_result"]
                names = station_names(s["steps"])
                here = names[min(s["step"], len(names) - 1)]
                if res.is_correct:
                    txt, col = L(f"أحسنتم! إجابة صحيحة ✔ — تقدّمتم إلى {here}", f"Well done! Correct ✔ — you moved on to {here}"), theme.OK
                else:
                    head = L("انتهى الوقت! ⏰", "Time is up! ⏰") if res.outcome.value == "timeout" else L("إجابة خاطئة ✘", "Wrong answer ✘")
                    ans = "، ".join(letter(k, "ar") for k in q.correct)
                    txt, col = L(f"{head} — الإجابة الصحيحة: {ans}", f"{head} — the correct answer is: {ans}"), theme.BAD
                    if s.get("last_step_back"):
                        txt += L(f"<div style='font-size: {fs(24)}px;color:{theme.MUTED}'>رجعتم خطوة إلى {here}</div>", f"<div style='font-size: {fs(24)}px;color:{theme.MUTED}'>You stepped back to {here}</div>")
                self.banner.setText(txt)
                self._style(self.banner, lambda: f"font-size: {fs(34)}px; font-weight: 900; color: {col};")
            else:
                self.banner.setText(L("اضغطوا على أحد الأزرار الأربعة للإجابة", "Press one of the four buttons to answer"))
                self._style(self.banner, lambda: f"font-size: {fs(22)}px; font-weight: 700; color: {theme.MUTED};")
            return
        if s["state"] == "feedback" and s["last_result"] is not None:
            res = s["last_result"]
            if res.is_correct:
                names = station_names(s["steps"])
                txt = L(f"أحسنتم! ترتيب صحيح ✔ — تقدّمتم إلى {names[min(s['step'], len(names) - 1)]}", f"Well done! Correct order ✔ — you moved on to {names[min(s['step'], len(names) - 1)]}")
                col = theme.OK
                if q.explanation.get("ar"):
                    txt += f"<div style='font-size: {fs(26)}px;color:{theme.INK}'>«{q.explanation['ar']}»</div>"
            elif res.outcome.value == "timeout":
                txt, col = L("انتهى الوقت! ⏰", "Time is up! ⏰"), theme.WARN
            else:
                k = res.detail.get("in_place", 0)
                retry = s.get("on_wrong") == "retry"
                txt = L("ترتيب غير صحيح ✘ — ", "Wrong order ✘ — ") + (L("حاولوا مرة أخرى", "try again") if retry else L("إلى الجملة التالية", "on to the next sentence"))
                txt += L(f"<div style='font-size: {fs(22)}px;color:{theme.MUTED}'>{ar(k)} من {ar(len(q.correct))} في المكان الصحيح</div>", f"<div style='font-size: {fs(22)}px;color:{theme.MUTED}'>{k} of {len(q.correct)} in the right place</div>")
                col = theme.BAD
            if s.get("waiting_next") and self._board_online():
                txt += L(f"<div style='font-size: {fs(22)}px;color:{theme.MUTED}'>أخرِجوا البطاقات من اللوحة، ثم اضغطوا الزر أدناه</div>", f"<div style='font-size: {fs(22)}px;color:{theme.MUTED}'>Take the cards out of the board, then press the button below</div>")
            self.banner.setText(txt)
            self._style(self.banner, lambda: f"font-size: {fs(34)}px; font-weight: 900; color: {col};")
        elif self._board_online() and s["board_state"] == "incomplete" and self.activity is not None:
            miss = "، ".join(ar(m) for m in getattr(self.activity, "missing", []))
            self.banner.setText(L(f"ضعوا كل البطاقات أولًا ✋ — الأماكن الفارغة: {miss}", f"Place all the cards first ✋ — empty places: {', '.join(str(m) for m in getattr(self.activity, 'missing', []))}"))
            self._style(self.banner, lambda: f"font-size: {fs(28)}px; font-weight: 800; color: {theme.WARN};")
        elif self._board_online() and s["board_state"] == "clear_required":
            self.banner.setText(L("أخرِجوا جميع البطاقات من اللوحة ثم ابدؤوا ✋", "Take all plates out of the board, then start ✋"))
            self._style(self.banner, lambda: f"font-size: {fs(28)}px; font-weight: 800; color: {theme.WARN};")
        else:
            hint = L("رتّبوا الكلمات في جملة مفيدة: ضعوا البطاقات في الأماكن (الأول من اليمين) ثم اضغطوا زر الإرسال ✅", "Arrange the words into a sentence: put the cards in the places (first on the right), then press SEND ✅")
            if not self._board_online():
                hint = L("اضغطوا على الكلمات بالترتيب الصحيح (اللوحة غير متصلة)", "Click the words in the right order (board not connected)")
            self.banner.setText(hint)
            self._style(self.banner, lambda: f"font-size: {fs(22)}px; font-weight: 700; color: {theme.MUTED};")

    def _render_status(self) -> None:
        buttons_mode = self.snap.get("mode") == "buttons"
        first = (self.activity.buttons_target() if self.activity else "map", L("الأزرار", "Buttons")) if buttons_mode else ("puzzle", L("لوحة البطاقات", "Plate board"))
        for role, lbl, name in ((first[0], self.board_dot, first[1]), ("map", self.map_dot, L("الخريطة", "Map"))):
            link = self.ctx.devices.device_for(role)
            c = theme.OK if link else theme.BAD
            lbl.setText(f"<span style='color:{c};font-size: {fs(16)}px'>●</span> {name}")

    def _render_timer(self) -> None:
        a = self.activity
        rem = a.remaining_s() if a else None
        self.timer_lbl.setText(L(f"⏱ {ar(int(rem + 0.99))} ث", f"⏱ {int(rem + 0.99)} s") if rem is not None else "")

    def on_rescaled(self) -> None:
        self.render()
        QTimer.singleShot(0, self._fit_image)
        QTimer.singleShot(0, self._fit_placeholder)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        apply_scale(self)
        QTimer.singleShot(0, self._fit_image)
        if self.confetti.isVisible():
            self.confetti.setGeometry(self.rect())
