"""Student screen: large bilingual question, colour-coded answer cards, timer, score, feedback."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..activities.quiz import QuizActivity
from ..core.events import DEVICE_STATUS
from ..core.models import Question
from ..hardware.models import DeviceStatus
from . import theme
from .theme import Scaled, apply_scale, fs
from .i18n import letter, tr
from .widgets import StatusDot


class OptionCard(Scaled, QFrame):
    def __init__(self, key: str, on_click: Callable[[str], None]):
        super().__init__()
        self.key = key
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(fs(70))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 14, 22, 14)
        lay.setSpacing(18)
        self.badge = QLabel()
        self.badge.setFixedSize(fs(72), fs(72))
        self.badge.setAlignment(Qt.AlignCenter)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self._style(self.text, lambda: f"font-size: {fs(34)}px; font-weight: 700;")
        self.mark = QLabel()
        self.mark.setFixedWidth(fs(60))
        self.mark.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.mark)
        self.set_style("normal")

    def _rescale(self) -> None:
        self.setMinimumHeight(fs(70))
        self.badge.setFixedSize(fs(72), fs(72))
        self.mark.setFixedWidth(fs(60))
        lay = self.layout()
        lay.setContentsMargins(fs(22), fs(10), fs(22), fs(10))
        lay.setSpacing(fs(18))

    def set_content(self, label: str, text: str) -> None:
        self.badge.setText(label)
        self.text.setText(text)

    def set_style(self, mode: str) -> None:
        bg, fg = theme.OPTION_COLORS.get(self.key, ("#888", "#fff"))
        border, card, mark, op = "#e3e7ef", "white", "", 1.0
        if mode == "correct":
            border, card, mark = theme.OK, "#e6f7ee", "✔"
        elif mode == "wrong":
            border, card, mark = theme.BAD, "#fde8e8", "✘"
        elif mode == "dim":
            op = 0.45
        self.setStyleSheet(f"OptionCard {{ background: {card}; border: 4px solid {border}; border-radius: 22px; }}")
        self._style(self.badge, lambda: f"background: {bg}; color: {fg}; border-radius: {fs(72) // 2}px; font-size: {fs(34)}px; font-weight: 800;")
        self._style(self.mark, lambda: f"font-size: {fs(44)}px; font-weight: 900; color: {theme.OK if mode == 'correct' else theme.BAD};")
        self.mark.setText(mark)
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(op)
        self.setGraphicsEffect(eff if op < 1 else None)

    def mousePressEvent(self, _e) -> None:  # noqa: N802
        self.on_click(self.key)


class StudentView(Scaled, QWidget):
    def __init__(self, ctx, on_exit: Callable[[], None]):
        super().__init__()
        self.ctx = ctx
        self.on_exit = on_exit
        self.activity: QuizActivity | None = None
        self.student_name = ""
        self.snap: dict[str, Any] = {}
        self.setObjectName("Page")
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)
        ctx.bridge.on(DEVICE_STATUS, lambda _s: self._update_devices())
        for i, k in enumerate("ABCD"):
            for seq in (k, str(i + 1)):
                QShortcut(QKeySequence(seq), self, activated=lambda k=k: self._answer(k, "keyboard"))
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._exit)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self._next)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(14)

        top = QHBoxLayout()
        self.who = QLabel()
        self._style(self.who, lambda: f"font-size: {fs(20)}px; font-weight: 700;")
        self.progress_lbl = QLabel()
        self._style(self.progress_lbl, lambda: f"font-size: {fs(18)}px; color: {theme.MUTED}; font-weight: 600;")
        self.score_lbl = QLabel()
        self._style(self.score_lbl, lambda: f"background: {theme.ACCENT}; color: white; border-radius: 16px; padding: 6px 16px; font-size: {fs(20)}px; font-weight: 800;")
        self.lang_btn = QPushButton("عربي / EN")
        self.lang_btn.clicked.connect(lambda: self.ctx.set_language("en" if self.ctx.lang == "ar" else "ar"))
        self.end_btn = QPushButton()
        self.end_btn.setObjectName("Danger")
        self.end_btn.clicked.connect(self._exit)
        top.addWidget(self.who)
        top.addSpacing(16)
        top.addWidget(self.progress_lbl)
        top.addStretch(1)
        top.addWidget(self.score_lbl)
        top.addSpacing(10)
        top.addWidget(self.lang_btn)
        top.addWidget(self.end_btn)
        root.addLayout(top)

        self.steps = QProgressBar()
        self.steps.setTextVisible(False)
        self.steps.setFixedHeight(8)
        self.steps.setStyleSheet(f"QProgressBar {{ background: #e3e7ef; border: 0; border-radius: 4px; }} QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 4px; }}")
        root.addWidget(self.steps)

        self.pages = QStackedLayout()
        root.addLayout(self.pages, 1)

        # --- question page
        qpage = QWidget()
        ql = QVBoxLayout(qpage)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(16)
        card = QFrame()
        card.setStyleSheet("QFrame { background: white; border-radius: 26px; }")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(30, 22, 30, 22)
        self.q_text = QLabel()
        self.q_text.setWordWrap(True)
        self.q_text.setAlignment(Qt.AlignCenter)
        self._style(self.q_text, lambda: f"font-size: {fs(52)}px; font-weight: 800;")
        self.q_image = QLabel()
        self.q_image.setAlignment(Qt.AlignCenter)
        self.timer_bar = QProgressBar()
        self.timer_bar.setTextVisible(False)
        self.timer_bar.setFixedHeight(14)
        self.timer_lbl = QLabel()
        self.timer_lbl.setAlignment(Qt.AlignCenter)
        self._style(self.timer_lbl, lambda: f"font-size: {fs(18)}px; color: {theme.MUTED}; font-weight: 700;")
        cl.addWidget(self.q_text)
        cl.addWidget(self.q_image)
        cl.addWidget(self.timer_bar)
        cl.addWidget(self.timer_lbl)
        ql.addWidget(card, 2)

        self.banner = QLabel()
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setMinimumHeight(40)
        self.banner_fx = QGraphicsOpacityEffect(self.banner)
        self.banner.setGraphicsEffect(self.banner_fx)
        self.banner_anim = QPropertyAnimation(self.banner_fx, b"opacity", self)
        self.banner_anim.setDuration(450)
        self.banner_anim.setEasingCurve(QEasingCurve.OutBack)
        ql.addWidget(self.banner)

        grid = QGridLayout()
        grid.setSpacing(18)
        self.cards: dict[str, OptionCard] = {}
        for i, k in enumerate("ABCD"):
            c = OptionCard(k, lambda key: self._answer(key, "screen"))
            self.cards[k] = c
            grid.addWidget(c, i // 2, i % 2)
        ql.addLayout(grid, 3)

        bottom = QHBoxLayout()
        self.in_dot = StatusDot()
        self.out_dot = StatusDot()
        self.next_btn = QPushButton()
        self.next_btn.setObjectName("Primary")
        self.next_btn.clicked.connect(self._next)
        bottom.addWidget(self.in_dot)
        bottom.addSpacing(16)
        bottom.addWidget(self.out_dot)
        bottom.addStretch(1)
        bottom.addWidget(self.next_btn)
        ql.addLayout(bottom)
        self.pages.addWidget(qpage)

        # --- finished page
        done = QWidget()
        dl = QVBoxLayout(done)
        dl.addStretch(1)
        self.done_title = QLabel()
        self.done_title.setAlignment(Qt.AlignCenter)
        self._style(self.done_title, lambda: f"font-size: {fs(64)}px; font-weight: 900;")
        self.done_stars = QLabel()
        self.done_stars.setAlignment(Qt.AlignCenter)
        self._style(self.done_stars, lambda: f"font-size: {fs(72)}px; color: #f5b100;")
        self.done_score = QLabel()
        self.done_score.setAlignment(Qt.AlignCenter)
        self._style(self.done_score, lambda: f"font-size: {fs(34)}px; font-weight: 700;")
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("Primary")
        self.back_btn.clicked.connect(self._exit)
        for w in (self.done_title, self.done_stars, self.done_score):
            dl.addWidget(w)
        dl.addSpacing(24)
        dl.addWidget(self.back_btn, 0, Qt.AlignCenter)
        dl.addStretch(1)
        self.pages.addWidget(done)

    # ------------------------------------------------------------- binding
    def bind(self, activity: QuizActivity, student_name: str) -> None:
        self.activity = activity
        self.student_name = student_name
        activity.add_listener(self._on_snapshot)
        self.snap = activity.snapshot()
        self.refresh()

    def _on_snapshot(self, snap: dict[str, Any]) -> None:
        prev_state = self.snap.get("state")
        self.snap = snap
        self.refresh()
        if snap["state"] == "feedback" and prev_state != "feedback":
            self.banner_fx.setOpacity(0)
            self.banner_anim.stop()
            self.banner_anim.setStartValue(0.0)
            self.banner_anim.setEndValue(1.0)
            self.banner_anim.start()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        apply_scale(self)

    def on_rescaled(self) -> None:
        self.refresh()

    def _answer(self, key: str, source: str) -> None:
        if self.activity and self.isVisible():
            self.activity.submit_from_ui(key, source)

    def _next(self) -> None:
        if self.activity and self.snap.get("state") in ("feedback", "asking"):
            self.activity.next()

    def _exit(self) -> None:
        self.ctx.sessions.stop()
        self.activity = None
        self.on_exit()

    # ------------------------------------------------------------- render
    def refresh(self) -> None:
        lang = self.ctx.lang
        self.setLayoutDirection(Qt.RightToLeft if lang == "ar" else Qt.LeftToRight)
        self.end_btn.setText(tr("end", lang))
        self.next_btn.setText(tr("next", lang))
        self.back_btn.setText(tr("back", lang))
        self.in_dot._text = tr("input_dev", lang)
        self.out_dot._text = tr("output_dev", lang)
        self._update_devices()
        s = self.snap
        if not s:
            return
        self.who.setText("👤 " + (self.student_name or tr("guest", lang)))
        n, i = s["total"], s["index"]
        self.steps.setMaximum(max(1, n))
        self.steps.setValue(i + (1 if s["state"] in ("feedback", "finished") else 0))
        self.progress_lbl.setText(tr("question_of", lang, i=min(i + 1, n), n=n))
        self.score_lbl.setText(f"⭐ {s['score']:g}")
        if s["state"] in ("finished", "stopped"):
            self._render_finished(s, lang)
            return
        self.pages.setCurrentIndex(0)
        q: Question | None = s["question"]
        if q is None:
            return
        self.q_text.setText(q.text(lang))
        self._render_image(q)
        for k, card in self.cards.items():
            opt = next((o for o in q.options if o.key == k), None)
            card.setVisible(opt is not None)
            if opt is not None:
                card.set_content(letter(k, lang), opt.label(lang))
        self.next_btn.setVisible(s["state"] == "feedback" and not self.activity.settings.auto_advance if self.activity else False)
        if s["state"] == "asking":
            for c in self.cards.values():
                c.set_style("normal")
            self.banner.setText(tr("press_button", lang))
            self._style(self.banner, lambda: f"font-size: {fs(22)}px; color: {theme.MUTED}; font-weight: 600;")
            self.banner_fx.setOpacity(1)
        elif s["state"] == "feedback":
            self._render_feedback(s, q, lang)
        self._tick()

    def _render_image(self, q: Question) -> None:
        path = q.image_path
        if path and not Path(path).is_absolute():
            path = str(self.ctx.data_dir / "images" / path)
        if path and Path(path).exists():
            pm = QPixmap(path)
            self.q_image.setPixmap(pm.scaledToHeight(min(260, pm.height()), Qt.SmoothTransformation))
            self.q_image.show()
        else:
            self.q_image.clear()
            self.q_image.hide()

    def _render_feedback(self, s: dict[str, Any], q: Question, lang: str) -> None:
        res = s["last_result"]
        outcome = res.outcome.value if res else "timeout"
        given = str(s.get("last_answer") or "").upper()
        correct = set(q.correct if isinstance(q.correct, list) else [])
        show = self.activity.settings.show_correct_answer if self.activity else True
        for k, card in self.cards.items():
            if k == given:
                card.set_style("correct" if k in correct else "wrong")
            elif k in correct and show:
                card.set_style("correct")
            else:
                card.set_style("dim")
        color = {"correct": theme.OK, "incorrect": theme.BAD, "partial": theme.WARN, "timeout": theme.WARN}[outcome]
        text = tr(outcome, lang)
        if outcome != "correct" and show and correct:
            ans = ", ".join(letter(k, lang) for k in sorted(correct))
            text += "  —  " + tr("the_answer_is", lang, a=ans)
        expl = q.explanation.get(lang) or q.explanation.get("en")
        if expl:
            text += f"<div style='font-size: {fs(20)}px;color:{theme.MUTED};font-weight:600'>{expl}</div>"
        self.banner.setText(text)
        self._style(self.banner, lambda: f"font-size: {fs(34)}px; font-weight: 900; color: {color};")

    def _render_finished(self, s: dict[str, Any], lang: str) -> None:
        self.pages.setCurrentIndex(1)
        possible = s["possible_score"] or 1
        frac = s["score"] / possible
        stars = 3 if frac >= 0.9 else 2 if frac >= 0.6 else 1 if frac > 0 else 0
        self.done_title.setText(tr("finished", lang) if s["state"] == "finished" else tr("stopped", lang))
        self.done_stars.setText("★" * stars + "☆" * (3 - stars))
        self.done_score.setText(tr("final_score", lang, s=f"{s['score']:g}", m=f"{possible:g}"))

    def _tick(self) -> None:
        if not self.activity or self.snap.get("state") != "asking":
            self.timer_bar.setVisible(False)
            self.timer_lbl.setText("")
            return
        rem = self.activity.remaining_s()
        limit = self.snap.get("time_limit_s") or 0
        if rem is None or not limit:
            self.timer_bar.setVisible(False)
            self.timer_lbl.setText("")
            return
        self.timer_bar.setVisible(True)
        self.timer_bar.setMaximum(int(limit * 10))
        self.timer_bar.setValue(int(rem * 10))
        col = theme.OK if rem > limit * 0.5 else theme.WARN if rem > limit * 0.2 else theme.BAD
        self.timer_bar.setStyleSheet(f"QProgressBar {{ background: #eceff5; border: 0; border-radius: 7px; }} QProgressBar::chunk {{ background: {col}; border-radius: 7px; }}")
        self.timer_lbl.setText("⏱ " + tr("seconds", self.ctx.lang, s=int(rem + 0.99)))

    def _update_devices(self) -> None:
        def st(role: str) -> tuple[str, str]:
            link = self.ctx.devices.device_for(role)
            return ("online", link.device_id or "") if link else ("lost", "")

        self.in_dot.set_state(*st("input"))
        self.out_dot.set_state(*st("output"))

    def on_status(self, _s: DeviceStatus) -> None:
        self._update_devices()
