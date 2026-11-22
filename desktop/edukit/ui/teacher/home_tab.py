"""Lesson launcher: pick bank, class, student and quiz settings."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...activities.base import ACTIVITY_TYPES
from ...activities.quiz import QuizSettings
from ...core.events import DEVICE_STATUS
from ..widgets import StatusDot


class HomeTab(QWidget):
    def __init__(self, ctx, on_start: Callable[[object, str], None]):
        super().__init__()
        self.ctx = ctx
        self.on_start = on_start
        self.setObjectName("Page")
        lay = QGridLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)

        head = QLabel("Start a lesson")
        head.setObjectName("H1")
        lay.addWidget(head, 0, 0, 1, 2)

        who = QGroupBox("Lesson")
        f = QFormLayout(who)
        self.activity = QComboBox()
        for tid, cls in ACTIVITY_TYPES.items():
            if tid == "mcq":  # games with their own launcher (e.g. the journey tab) are not listed here
                self.activity.addItem(cls.display_name["en"], tid)
        self.bank = QComboBox()
        self.cls = QComboBox()
        self.cls.currentIndexChanged.connect(lambda _i: self._load_students())
        self.student = QComboBox()
        f.addRow("Activity", self.activity)
        f.addRow("Question bank", self.bank)
        f.addRow("Class", self.cls)
        f.addRow("Student", self.student)
        lay.addWidget(who, 1, 0)

        st = QGroupBox("Quiz settings")
        sf = QFormLayout(st)
        s = ctx.quiz_settings()
        self.timers = QCheckBox("Use question timers")
        self.timers.setChecked(s.use_question_timers)
        self.auto = QCheckBox("Move to next question automatically")
        self.auto.setChecked(s.auto_advance)
        self.fb_secs = QDoubleSpinBox()
        self.fb_secs.setRange(0.5, 30)
        self.fb_secs.setSuffix(" s")
        self.fb_secs.setValue(s.feedback_seconds)
        self.shuffle = QCheckBox("Shuffle questions")
        self.shuffle.setChecked(s.shuffle)
        self.show_ans = QCheckBox("Show the correct answer after a mistake")
        self.show_ans.setChecked(s.show_correct_answer)
        self.screen = QCheckBox("Allow answering on screen / keyboard")
        self.screen.setChecked(s.allow_screen_answers)
        self.maxq = QSpinBox()
        self.maxq.setRange(0, 500)
        self.maxq.setSpecialValueText("All")
        self.maxq.setValue(s.max_questions)
        sf.addRow(self.timers)
        sf.addRow(self.auto)
        sf.addRow("Show feedback for", self.fb_secs)
        sf.addRow(self.shuffle)
        sf.addRow(self.show_ans)
        sf.addRow(self.screen)
        sf.addRow("Number of questions", self.maxq)
        lay.addWidget(st, 1, 1)

        disp = QGroupBox("Display")
        df = QFormLayout(disp)
        self.lang = QComboBox()
        self.lang.addItem("English", "en")
        self.lang.addItem("العربية", "ar")
        self.lang.setCurrentIndex(max(0, self.lang.findData(ctx.lang)))
        self.lang.currentIndexChanged.connect(lambda _i: ctx.set_language(self.lang.currentData()))
        ctx.language_changed.connect(lambda l: (self.lang.blockSignals(True), self.lang.setCurrentIndex(self.lang.findData(l)), self.lang.blockSignals(False)))
        self.sounds = QCheckBox("Play sounds on this computer")
        self.sounds.setChecked(ctx.sounds.enabled)
        self.sounds.toggled.connect(self._sounds)
        self.fullscreen = QCheckBox("Full screen student view")
        df.addRow("Student language", self.lang)
        df.addRow(self.sounds)
        df.addRow(self.fullscreen)
        lay.addWidget(disp, 2, 0)

        hw = QGroupBox("Hardware")
        hl = QVBoxLayout(hw)
        self.in_dot = StatusDot("Input controller")
        self.out_dot = StatusDot("Output controller")
        self.mode_lbl = QLabel()
        self.mode_lbl.setObjectName("Muted")
        self.mode_lbl.setWordWrap(True)
        hl.addWidget(self.in_dot)
        hl.addWidget(self.out_dot)
        hl.addWidget(self.mode_lbl)
        lay.addWidget(hw, 2, 1)

        go = QPushButton("▶  Start lesson")
        go.setObjectName("Primary")
        go.setMinimumHeight(48)
        go.clicked.connect(self.start)
        lay.addWidget(go, 3, 0, 1, 2)
        lay.setRowStretch(4, 1)

        ctx.bridge.on(DEVICE_STATUS, lambda _s: self.refresh_hw())
        ctx.hardware_mode_changed.connect(self.refresh_hw)
        self.reload()

    def _sounds(self, on: bool) -> None:
        self.ctx.sounds.enabled = on
        self.ctx.repo.set_setting("screen_sounds", on)

    def reload(self) -> None:
        cur_b, cur_c = self.bank.currentData(), self.cls.currentData()
        counts = self.ctx.repo.bank_question_counts()
        self.bank.clear()
        for b in self.ctx.repo.list_banks():
            self.bank.addItem(f"{b.name} ({b.subject}, {b.grade}) — {counts.get(b.id, 0)} questions", b.id)
        self.bank.setCurrentIndex(max(0, self.bank.findData(cur_b)))
        self.cls.blockSignals(True)
        self.cls.clear()
        self.cls.addItem("— no class —", None)
        for c in self.ctx.repo.list_classes():
            self.cls.addItem(c.name, c.id)
        idx = self.cls.findData(cur_c) if cur_c is not None else -1
        self.cls.setCurrentIndex(idx if idx >= 0 else (1 if self.cls.count() > 1 else 0))
        self.cls.blockSignals(False)
        self._load_students()
        self.refresh_hw()

    def _load_students(self) -> None:
        cur = self.student.currentData()
        self.student.clear()
        self.student.addItem("Guest (not recorded to a student)", None)
        cid = self.cls.currentData()
        for s in self.ctx.repo.list_students(cid) if cid is not None else self.ctx.repo.list_students():
            self.student.addItem(s.name, s.id)
        self.student.setCurrentIndex(max(0, self.student.findData(cur)))

    def refresh_hw(self) -> None:
        for role, dot in (("input", self.in_dot), ("output", self.out_dot)):
            link = self.ctx.devices.device_for(role)
            dot.set_state("online" if link else "lost", f"— {link.device_id} ({link.transport.kind})" if link else "— not connected")
        modes = [m for m, on in (("simulation", self.ctx.simulation_enabled), ("USB serial", self.ctx.serial_enabled)) if on]
        self.mode_lbl.setText("Active: " + (", ".join(modes) or "none") + ". Lessons still run without hardware (on-screen answers).")

    def settings(self) -> QuizSettings:
        return QuizSettings(
            feedback_seconds=self.fb_secs.value(),
            auto_advance=self.auto.isChecked(),
            shuffle=self.shuffle.isChecked(),
            use_question_timers=self.timers.isChecked(),
            allow_screen_answers=self.screen.isChecked(),
            show_correct_answer=self.show_ans.isChecked(),
            max_questions=self.maxq.value(),
        )

    def start(self) -> None:
        bank_id = self.bank.currentData()
        if bank_id is None:
            QMessageBox.information(self, "No question bank", "Create or import a question bank first.")
            return
        s = self.settings()
        self.ctx.save_quiz_settings(s)
        try:
            act = self.ctx.sessions.start_quiz(bank_id, self.student.currentData(), self.cls.currentData(), s)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot start", str(exc))
            return
        name = self.student.currentText() if self.student.currentData() is not None else ""
        self.on_start(act, name)
