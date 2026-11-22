"""Teacher tab for Game 1 «رحلة إلى مكة» (Arabic UI)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...activities.journey import JourneySettings
from ...core.events import DEVICE_STATUS
from ...core.models import Option, Question
from ..i18n import letter
from ..journey_view import ar, station_names
from ..lang import L, direction
from ..speech import speech_settings

DEFAULT_PROMPT = "رتّب الكلمات لتكوّن جملة صحيحة"


def _res_text(ohm: int) -> str:
    return L(f"{ohm / 1000:g} كيلو أوم", f"{ohm / 1000:g} kΩ")


class ArrangeQuestionDialog(QDialog):
    """Teacher types the sentence in the correct order; word k is written on plate k (fixed firmware key)."""

    def __init__(self, parent: QWidget, ctx, q: Question):
        super().__init__(parent)
        self.ctx, self.q = ctx, q
        self.setLayoutDirection(direction())
        self.setWindowTitle(L("تعديل جملة", "Edit sentence") if q.id else L("جملة جديدة", "New sentence"))
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit(q.code)
        self.prompt = QLineEdit(q.prompt.get("ar") or DEFAULT_PROMPT)
        self.sentence = QLineEdit()
        words_by_plate = {o.key: o.label("ar") for o in q.options}
        if q.correct:
            self.sentence.setText(" ".join(words_by_plate.get(k, "") for k in q.correct))
        self.sentence.setPlaceholderText(L("اكتب الجملة الصحيحة، مثال: سافر الحجاج من إندونيسيا إلى مكة", "Type the correct sentence, e.g. سافر الحجاج من إندونيسيا إلى مكة"))
        split = QPushButton(L("تقسيم إلى كلمات ⬇", "Split into words ⬇"))
        split.clicked.connect(self._split)
        srow = QHBoxLayout()
        srow.addWidget(self.sentence, 1)
        srow.addWidget(split)
        self.time = QSpinBox()
        self.time.setRange(0, 900)
        self.time.setSuffix(L(" ث", " s"))
        self.time.setSpecialValueText(L("بدون وقت", "No limit"))
        self.time.setValue(q.time_limit_s)
        self.points = QSpinBox()
        self.points.setRange(1, 100)
        self.points.setValue(q.points)
        form.addRow(L("الرمز", "Code"), self.code)
        form.addRow(L("التعليمات على الشاشة", "Instruction on screen"), self.prompt)
        form.addRow(L("الجملة الصحيحة", "Correct sentence"), srow)
        form.addRow(L("الوقت (عند تفعيل المؤقت)", "Time (when the timer is on)"), self.time)
        form.addRow(L("النقاط", "Points"), self.points)
        lay.addLayout(form)

        box = QGroupBox(L("الكلمات بالترتيب الصحيح — اكتب كل كلمة على البطاقة المقابلة لها", "Words in the correct order — write each word on its plate"))
        bl = QVBoxLayout(box)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([L("المقبس", "Socket"), L("الكلمة", "Word"), L("تُكتب على", "Write on")])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        bl.addWidget(self.table)
        note = QLabel(L("مفتاح الإجابة ثابت في برنامج اللوحة: المقبس ١ ينتظر البطاقة ١، والمقبس ٢ ينتظر البطاقة ٢ … ", "The answer key is fixed in the board firmware: socket 1 expects plate 1, socket 2 expects plate 2 … ")
                      + L("لذلك اكتب الكلمة الأولى على البطاقة ١، والثانية على البطاقة ٢ وهكذا (استعمل مفتاحك لمعرفة البطاقات). ", "so write the first word on plate 1, the second on plate 2, and so on (use your key to recognise the plates). ")
                      + L("البطاقات متشابهة للطلاب، والشاشة تعرض الكلمات بترتيب مخلوط. المقبس ١ هو أقصى اليمين.", "Plates look alike to students and the screen shows the words shuffled. Socket 1 is the right-most."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        bl.addWidget(note)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(L("حفظ", "Save"))
        bb.button(QDialogButtonBox.Cancel).setText(L("إلغاء", "Cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if q.correct:
            self._fill([words_by_plate.get(k, "") for k in q.correct])

    def _fill(self, words: list[str]) -> None:
        self.table.setRowCount(len(words))
        for r, word in enumerate(words):
            for c, v in ((0, ar(r + 1)), (1, word), (2, L(f"البطاقة {ar(r + 1)}", f"Plate {r + 1}"))):
                it = QTableWidgetItem(v)
                if c != 1:
                    it.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(r, c, it)

    def _split(self) -> None:
        words = self.sentence.text().split()
        if not 2 <= len(words) <= 6:
            QMessageBox.warning(self, L("عدد الكلمات", "Word count"), L("يجب أن تحتوي الجملة على ٢ إلى ٦ كلمات (عدد المقابس في اللوحة).", "The sentence must have 2 to 6 words (the number of sockets)."))
            return
        self._fill(words)

    def _save(self) -> None:
        if self.table.rowCount() == 0:
            self._split()
            if self.table.rowCount() == 0:
                return
        words = [self.table.item(r, 1).text().strip() for r in range(self.table.rowCount())]
        q = self.q
        q.qtype = "arrange"
        q.code = self.code.text().strip()
        q.prompt = {"ar": self.prompt.text().strip() or DEFAULT_PROMPT}
        q.options = [Option(str(i + 1), {"ar": w}) for i, w in enumerate(words)]
        q.correct = [str(i + 1) for i in range(len(words))]
        q.explanation = {"ar": " ".join(words)}
        q.time_limit_s = self.time.value()
        q.points = self.points.value()
        try:
            if q.id:
                self.ctx.repo.update_question(q)
            else:
                self.ctx.repo.add_question(q)
        except Exception as exc:
            msg = L("يوجد سؤال بنفس الرمز في هذا البنك.", "A question with this code already exists in this lesson.") if "UNIQUE" in str(exc) else str(exc)
            QMessageBox.warning(self, L("تعذّر الحفظ", "Could not save"), msg)
            return
        self.accept()


class ChoiceQuestionDialog(QDialog):
    """Arabic multiple-choice (أ ب ج د) or true/false (صح / خطأ) question, with an optional picture."""

    def __init__(self, parent: QWidget, ctx, q: Question):
        super().__init__(parent)
        self.ctx, self.q = ctx, q
        self.setLayoutDirection(direction())
        self.tf = q.qtype == "true_false"
        kind = L("صح أو خطأ", "True / false") if self.tf else L("اختيار من متعدد", "Multiple choice")
        self.setWindowTitle(L(f"{'تعديل' if q.id else 'سؤال جديد'} — {kind}", f"{'Edit' if q.id else 'New question'} — {kind}"))
        self.setMinimumWidth(600)
        form = QFormLayout(self)
        self.code = QLineEdit(q.code)
        self.text = QLineEdit(q.prompt.get("ar", ""))
        self.text.setPlaceholderText(L("اكتب السؤال، مثال: ما عاصمة إندونيسيا؟", "Type the question, e.g. ما عاصمة إندونيسيا؟"))
        form.addRow(L("الرمز", "Code"), self.code)
        form.addRow(L("السؤال", "Question"), self.text)
        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        self.group = QButtonGroup(self)
        self.opts: dict[str, QLineEdit] = {}
        colors = {"A": L("أحمر", "red"), "B": L("أزرق", "blue"), "C": L("أخضر", "green"), "D": L("أصفر", "yellow")}
        for k in ("AB" if self.tf else "ABCD"):
            row = QHBoxLayout()
            e = QLineEdit(next((o.label("ar") for o in q.options if o.key == k), ""))
            if self.tf:
                e.setText("صح" if k == "A" else "خطأ")
                e.setReadOnly(True)
            rb = QRadioButton(L("صحيحة", "Correct"))
            rb.setChecked(k in (q.correct or []))
            self.group.addButton(rb)
            rb.setProperty("key", k)
            row.addWidget(e, 1)
            row.addWidget(rb)
            self.opts[k] = e
            form.addRow(L(f"{letter(k, 'ar')}  (الزر {colors[k]})", f"{k}  ({colors[k]} button)"), row)
        self.time = QSpinBox()
        self.time.setRange(0, 600)
        self.time.setSuffix(L(" ث", " s"))
        self.time.setSpecialValueText(L("بدون وقت", "No limit"))
        self.time.setValue(q.time_limit_s)
        self.expl = QLineEdit(q.explanation.get("ar", ""))
        self.expl.setPlaceholderText(L("اختياري: شرح قصير يظهر بعد الإجابة", "Optional: short explanation shown after the answer"))
        form.addRow(L("الوقت (عند تفعيل المؤقت)", "Time (when the timer is on)"), self.time)
        form.addRow(L("الشرح", "Explanation"), self.expl)
        img_row = QHBoxLayout()
        self.image = QLineEdit(q.image_path or "")
        self.image.setPlaceholderText(L("صورة تظهر كبيرة مع السؤال (اختياري)", "Picture or video shown above the question (optional)"))
        self.image.setReadOnly(True)
        pick = QPushButton(L("اختيار صورة…", "Choose picture/video…"))
        pick.clicked.connect(self._pick_image)
        clr = QPushButton(L("بدون صورة", "None"))
        clr.clicked.connect(lambda: self.image.setText(""))
        img_row.addWidget(self.image, 1)
        img_row.addWidget(pick)
        img_row.addWidget(clr)
        form.addRow(L("الصورة", "Picture / video"), img_row)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(L("حفظ", "Save"))
        bb.button(QDialogButtonBox.Cancel).setText(L("إلغاء", "Cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _pick_image(self) -> None:
        import uuid

        path, _ = QFileDialog.getOpenFileName(self, L("اختيار صورة", "Choose a picture or video"), "", "Media (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.mp4 *.mov *.m4v *.avi *.mkv *.webm)")
        if path:
            dest_dir = self.ctx.data_dir / "images"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{uuid.uuid4().hex[:8]}_{Path(path).name}"
            shutil.copy2(path, dest)
            self.image.setText(dest.name)

    def _save(self) -> None:
        q = self.q
        checked = self.group.checkedButton()
        q.qtype = "true_false" if self.tf else "single_choice"
        q.image_path = self.image.text().strip() or None
        q.code = self.code.text().strip()
        q.prompt = {"ar": self.text.text().strip()}
        q.options = [Option(k, {"ar": e.text().strip()}) for k, e in self.opts.items() if e.text().strip()]
        q.correct = [checked.property("key")] if checked else []
        q.time_limit_s = self.time.value()
        q.explanation = {"ar": self.expl.text().strip()} if self.expl.text().strip() else {}
        try:
            if q.id:
                self.ctx.repo.update_question(q)
            else:
                self.ctx.repo.add_question(q)
        except Exception as exc:
            msg = L("يوجد سؤال بنفس الرمز في هذا البنك.", "A question with this code already exists in this lesson.") if "UNIQUE" in str(exc) else L("تأكد من كتابة السؤال وخيارين على الأقل وتحديد الإجابة الصحيحة.", "Write the question, at least two options and mark the correct answer.")
            QMessageBox.warning(self, L("تعذّر الحفظ", "Could not save"), msg)
            return
        self.accept()


class JourneyTab(QWidget):
    """🕋 Start the journey: competition type, lesson/unit, participants (student / team / class), rules, sounds."""

    def __init__(self, ctx, on_start: Callable[[object], None]):
        super().__init__()
        self.ctx = ctx
        self.on_start = on_start
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        outer = QVBoxLayout(self)
        head = QLabel(L("🕋 رحلة إلى مكة", "🕋 Journey to Makkah"))
        head.setObjectName("H1")
        outer.addWidget(head)
        tabs = QTabWidget()
        tabs.setElideMode(Qt.ElideNone)
        tabs.tabBar().setExpanding(False)
        outer.addWidget(tabs, 1)
        tabs.addTab(self._build_start(), L("بدء الرحلة", "Start"))
        tabs.addTab(self._build_sounds(), L("الأصوات", "Sounds"))
        self.tabs = tabs
        ctx.bridge.on(DEVICE_STATUS, lambda _s: self._refresh_status())
        self.reload()

    # ------------------------------------------------------------------ start
    def _build_start(self) -> QWidget:
        from .devices_tab import DEVICE_TYPES

        w = QWidget()
        g = QGridLayout(w)
        comp = QGroupBox(L("المسابقة", "Competition"))
        f = QFormLayout(comp)
        self.ctype = QComboBox()
        for key, ar_, en, ok in DEVICE_TYPES:
            self.ctype.addItem(L(ar_, en), key)
            if not ok:
                self.ctype.model().item(self.ctype.count() - 1).setEnabled(False)
        self.ctype.setCurrentIndex(max(0, self.ctype.findData(self.ctx.repo.get_setting("journey_ctype", "mcq"))))
        self.ctype.currentIndexChanged.connect(lambda _i: self.reload())
        self.bank = QComboBox()
        for combo in (self.ctype, self.bank):  # long lesson paths must not widen the page
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(22)
        f.addRow(L("نوع المسابقة", "Competition type"), self.ctype)
        f.addRow(L("الدرس أو الوحدة", "Lesson or unit"), self.bank)
        qnote = QLabel(L("الأسئلة تُدار من تبويب «📚 المنهج والأسئلة»، ونوع كل جهاز من تبويب «🔌 الأجهزة».",
                         "Questions are managed in «📚 Curriculum»; each device's type in «🔌 Devices»."))
        qnote.setObjectName("Muted")
        qnote.setWordWrap(True)
        f.addRow("", qnote)
        g.addWidget(comp, 0, 0)

        who = QGroupBox(L("المشاركون", "Participants"))
        pf = QFormLayout(who)
        self.cls = QComboBox()
        self.cls.currentIndexChanged.connect(lambda _i: self._load_people())
        self.mode = QComboBox()
        self.mode.addItem(L("فريق", "A team"), "team")
        self.mode.addItem(L("طالب واحد", "One student"), "student")
        self.mode.addItem(L("الصف كله", "The whole class"), "class")
        self.mode.currentIndexChanged.connect(lambda _i: (setattr(self, "_mode_chosen", True), self._load_people()))
        self.who_combo = QComboBox()
        self.who_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.who_combo.setMinimumContentsLength(18)
        self.who_combo.currentIndexChanged.connect(lambda _i: self._who_changed())
        self.members_lbl = QLabel()
        self.members_lbl.setObjectName("Muted")
        self.members_lbl.setWordWrap(True)
        self.team = QLineEdit()
        self.team.setPlaceholderText(L("الاسم الذي يظهر على الشاشة", "Name shown on screen"))
        pf.addRow(L("الصف", "Class"), self.cls)
        pf.addRow(L("المشاركة", "Who plays"), self.mode)
        pf.addRow("", self.who_combo)
        pf.addRow("", self.members_lbl)
        pf.addRow(L("الاسم على الشاشة", "Display name"), self.team)
        g.addWidget(who, 1, 0)

        st = QGroupBox(L("إعدادات اللعبة", "Game settings"))
        sf = QFormLayout(st)
        s = JourneySettings.from_dict(self.ctx.repo.get_setting("journey_settings_v2", {}))
        self.steps = QSpinBox()
        self.steps.setRange(1, 20)
        self.steps.setValue(s.steps_to_makkah)
        self.steps.valueChanged.connect(self._update_route_label)
        self.route_lbl = QLabel()
        self.route_lbl.setObjectName("Muted")
        self.route_lbl.setWordWrap(True)
        self.on_wrong = QComboBox()
        self.on_wrong.addItem(L("الانتقال إلى سؤال آخر", "Go to another question"), "next")
        self.on_wrong.addItem(L("إعادة نفس السؤال", "Repeat the same question"), "retry")
        self.on_wrong.setCurrentIndex(max(0, self.on_wrong.findData(s.on_wrong)))
        self.step_back = QCheckBox(L("الرجوع خطوة (بالأحمر) عند الخطأ", "Step back (red) on a wrong answer"))
        self.step_back.setChecked(s.step_back_on_wrong)
        self.fb = QDoubleSpinBox()
        self.fb.setRange(1, 30)
        self.fb.setSuffix(L(" ث", " s"))
        self.fb.setValue(s.feedback_seconds)
        self.timer = QCheckBox(L("تفعيل مؤقت لكل سؤال", "Timer for each question"))
        self.timer.setChecked(s.use_timer)
        self.shuffle = QCheckBox(L("خلط ترتيب الأسئلة", "Shuffle questions"))
        self.shuffle.setChecked(s.shuffle)
        self.screen = QCheckBox(L("السماح بالإجابة بالضغط على الشاشة أيضًا", "Also allow answering by clicking the screen"))
        self.screen.setChecked(s.allow_screen_answers)
        self.fest = QSpinBox()
        self.fest.setRange(5, 300)
        self.fest.setSuffix(L(" ث", " s"))
        self.fest.setValue(s.festival_seconds)
        self.maxq = QSpinBox()
        self.maxq.setRange(0, 200)
        self.maxq.setSpecialValueText(L("بلا حد (لا خسارة)", "No limit (no losing)"))
        self.maxq.setValue(s.max_questions)
        self.full = QCheckBox(L("ملء الشاشة على جهاز العرض", "Full screen on the projector"))
        sf.addRow(L("عدد الإجابات الصحيحة للوصول إلى مكة", "Correct answers to reach Makkah"), self.steps)
        sf.addRow("", self.route_lbl)
        sf.addRow(L("الحد الأقصى للأسئلة (للخسارة)", "Question limit (to lose)"), self.maxq)
        sf.addRow(L("عند الخطأ", "On a wrong answer"), self.on_wrong)
        sf.addRow(self.step_back)
        sf.addRow(L("مدة عرض النتيجة", "Show result for"), self.fb)
        sf.addRow(self.timer)
        sf.addRow(self.shuffle)
        sf.addRow(self.screen)
        sf.addRow(L("مدة الاحتفال على الخريطة", "Map festival length"), self.fest)
        sf.addRow(self.full)
        g.addWidget(st, 0, 1, 3, 1)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)

        hw = QGroupBox(L("الأجهزة", "Devices"))
        hl = QVBoxLayout(hw)
        self.map_lbl = QLabel()
        self.puzzle_lbl = QLabel()
        hl.addWidget(self.map_lbl)
        hl.addWidget(self.puzzle_lbl)
        g.addWidget(hw, 2, 0)

        go = QPushButton(L("🚀  ابدأ الرحلة إلى مكة", "🚀  Start the journey to Makkah"))
        go.setObjectName("Primary")
        go.setMinimumHeight(52)
        go.clicked.connect(self.start)
        g.addWidget(go, 3, 0, 1, 2)
        g.setRowStretch(4, 1)
        self._update_route_label()
        return w

    def _update_route_label(self) -> None:
        self.route_lbl.setText(L("المسار: ", "Route: ") + " ← ".join(station_names(self.steps.value())))

    # ------------------------------------------------------------ participants
    def _load_people(self) -> None:
        mode = self.mode.currentData()
        cid = self.cls.currentData()
        cur = self.who_combo.currentData()
        self.who_combo.blockSignals(True)
        self.who_combo.clear()
        if mode == "team":
            teams = self.ctx.repo.list_teams(cid) if cid is not None else self.ctx.repo.list_teams()
            for t in teams:
                self.who_combo.addItem(f"👥 {t['name']} ({len(t['members'])})", t["id"])
            if not teams:
                self.who_combo.addItem(L("— لا توجد فرق: أنشئها في «الطلاب والصفوف» —", "— no teams: create them in «Students & classes» —"), None)
        elif mode == "student":
            for s in self.ctx.repo.list_students(cid) if cid is not None else self.ctx.repo.list_students():
                self.who_combo.addItem(f"👤 {s.name}", s.id)
        self.who_combo.setVisible(mode != "class")
        self.who_combo.setCurrentIndex(max(0, self.who_combo.findData(cur)))
        self.who_combo.blockSignals(False)
        self._who_changed()

    def _who_changed(self) -> None:
        mode = self.mode.currentData()
        wid = self.who_combo.currentData()
        self.members_lbl.setText("")
        if mode == "team" and wid is not None:
            t = self.ctx.repo.get_team(wid)
            if t:
                self.members_lbl.setText(L("الأعضاء: ", "Members: ") + "، ".join(m.name for m in t["members"]))
                self.team.setText(t["name"])
        elif mode == "student" and wid is not None:
            self.team.setText(self.who_combo.currentText().replace("👤 ", ""))
        elif mode == "class":
            self.team.setText(self.cls.currentText() if self.cls.currentData() is not None else "")

    # ---------------------------------------------------------------- settings
    def settings(self) -> JourneySettings:
        return JourneySettings(
            steps_to_makkah=self.steps.value(),
            on_wrong=self.on_wrong.currentData(),
            step_back_on_wrong=self.step_back.isChecked(),
            feedback_seconds=self.fb.value(),
            shuffle=self.shuffle.isChecked(),
            use_timer=self.timer.isChecked(),
            allow_screen_answers=self.screen.isChecked(),
            festival_seconds=self.fest.value(),
            max_questions=self.maxq.value(),
            team_name=self.team.text().strip(),
        )

    def start(self) -> None:
        from .devices_tab import DEVICE_TYPES, TYPE_QTYPES

        ctype = self.ctype.currentData()
        if not next(ok for k, *_x, ok in DEVICE_TYPES if k == ctype):
            QMessageBox.information(self, L("قريبًا", "Coming soon"), L("هذا النوع من المسابقات غير متاح بعد.", "This competition type is not available yet."))
            return
        choice = self.bank.currentData()
        if choice is None:
            QMessageBox.information(self, L("لا توجد أسئلة", "No questions"),
                                    L("أضف أسئلة من هذا النوع لدرس في «📚 المنهج والأسئلة» أولًا.", "Add questions of this type to a lesson in «📚 Curriculum» first."))
            return
        kind, node_id = choice.split(":")[0], int(choice.split(":")[1])
        mode, wid, cid = self.mode.currentData(), self.who_combo.currentData(), self.cls.currentData()
        if mode == "team" and wid is None:
            QMessageBox.information(self, L("لا يوجد فريق", "No team"), L("أنشئ فريقًا من «👥 الطلاب والصفوف» أو اختر «طالب واحد» أو «الصف كله».",
                                                                         "Create a team in «👥 Students» or choose «One student» / «The whole class»."))
            return
        s = self.settings()
        self.ctx.repo.set_setting("journey_settings_v2", {k: v for k, v in s.to_dict().items() if k != "team_name"})
        self.ctx.repo.set_setting("journey_last_source", choice)
        self.ctx.repo.set_setting("journey_ctype", ctype)
        qtypes = TYPE_QTYPES[ctype]
        qs = self.ctx.repo.unit_questions(node_id) if kind == "unit" else self.ctx.repo.list_questions(node_id)
        qs = [q for q in qs if q.qtype in qtypes]
        student_id = wid if mode == "student" else None
        team_id = wid if mode == "team" else None
        try:
            act = self.ctx.sessions.start_journey(node_id if kind == "lesson" else None, student_id, cid, s, questions=qs, team_id=team_id)
        except ValueError as exc:
            QMessageBox.warning(self, L("تعذّر البدء", "Cannot start"), str(exc))
            return
        self.on_start(act)

    def reload(self) -> None:
        """Lesson / whole-unit picker for the chosen competition type, classes and participants."""
        from .devices_tab import TYPE_QTYPES

        ok = TYPE_QTYPES.get(self.ctype.currentData(), set())
        cur = self.bank.currentData() or self.ctx.repo.get_setting("journey_last_source", None)
        if isinstance(cur, list):
            cur = f"{cur[0]}:{cur[1]}"
        self.bank.blockSignals(True)
        self.bank.clear()
        default = None
        for c in self.ctx.repo.curriculum_tree():
            for sbj in c["subjects"]:
                for u in sbj["units"]:
                    playable = [l for l in u["lessons"] if l["count"] and set(l["types"]) & ok]
                    if not playable:
                        continue
                    if len(playable) > 1:
                        total = sum(l["count"] for l in playable)
                        self.bank.addItem(f"📂 {sbj['name']} › {u['name']} — {L('كل الدروس', 'all lessons')} ({total})", f"unit:{u['id']}")
                    for l in playable:
                        self.bank.addItem(f"📝 {sbj['name']} › {u['name']} › {l['name']} ({l['count']})", f"lesson:{l['id']}")
                        if default is None and "أسئلة الاختيار" in l["name"]:
                            default = f"lesson:{l['id']}"
        idx = self.bank.findData(cur) if cur else -1
        if idx < 0 and default:
            idx = self.bank.findData(default)
        self.bank.setCurrentIndex(max(0, idx))
        self.bank.blockSignals(False)
        cur_c = self.cls.currentData()
        self.cls.blockSignals(True)
        self.cls.clear()
        self.cls.addItem(L("— كل الصفوف —", "— all classes —"), None)
        for c in self.ctx.repo.list_classes():
            self.cls.addItem(c.name, c.id)
        idx = self.cls.findData(cur_c) if cur_c is not None else -1
        self.cls.setCurrentIndex(idx if idx >= 0 else (1 if self.cls.count() > 1 else 0))
        self.cls.blockSignals(False)
        # default: play as a team when the class has teams, otherwise as the whole class
        if not getattr(self, "_mode_chosen", False):
            has_teams = bool(self.ctx.repo.list_teams(self.cls.currentData()) if self.cls.currentData() is not None else self.ctx.repo.list_teams())
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData("team" if has_teams else "class"))
            self.mode.blockSignals(False)
        self._load_people()
        self._refresh_status()

    def _refresh_status(self) -> None:
        for role, lbl, name in (("map", self.map_lbl, L("الخريطة والأزرار", "Map and buttons")),
                                ("puzzle", self.puzzle_lbl, L("لوحة البطاقات (اختيارية)", "Plate board (optional)"))):
            link = self.ctx.devices.device_for(role)
            c = "#2fb86e" if link else "#e5484d"
            txt = (L("متصلة", "connected") + f" — {link.device_id} ({link.transport.kind})") if link else L("غير متصلة", "not connected")
            lbl.setText(f"<span style='color:{c};font-size:16px'>●</span> {name}: {txt}")

    # ------------------------------------------------------------------ sounds
    def _build_sounds(self) -> QWidget:
        from .event_audio_widget import EventAudioWidget

        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(EventAudioWidget(self.ctx))
        v.addWidget(self._build_speech())
        v.addStretch(1)
        return w

    def _build_speech(self) -> QWidget:
        sp = speech_settings(self.ctx.repo.get_setting("journey_speech", {}))
        box = QGroupBox(L("النطق بالعربية من الحاسوب (بدون إنترنت)", "Arabic speech from the computer (offline)"))
        f = QFormLayout(box)
        voice = self.ctx.speaker.voice_name
        status = QLabel(L(f"الصوت العربي في النظام: {voice}", f"System Arabic voice: {voice}") if self.ctx.speaker.available else
                        L("لا يوجد صوت عربي في النظام — ثبّته من إعدادات Windows ← الوقت واللغة ← الكلام، أو استورد أصواتًا أعلاه.",
                          "No Arabic voice in the system — install one in Windows Settings → Time & Language → Speech, or import sounds above."))
        status.setWordWrap(True)
        status.setStyleSheet(f"color: {'#1f9d55' if self.ctx.speaker.available else '#e5484d'}; font-weight: 700;")
        self.sp_enabled = QCheckBox(L("نطق عبارة بعد كل إجابة", "Speak a phrase after each answer"))
        self.sp_enabled.setChecked(sp["enabled"])
        self.sp_read = QCheckBox(L("قراءة السؤال والخيارات بصوت عالٍ", "Read the question and options aloud"))
        self.sp_read.setChecked(sp["read_question"])
        self.sp_correct = QLineEdit(" | ".join(sp["correct"]))
        self.sp_wrong = QLineEdit(" | ".join(sp["wrong"]))
        self.sp_arrival = QLineEdit(sp["arrival"])
        save = QPushButton(L("حفظ العبارات", "Save phrases"))
        save.clicked.connect(self._save_speech)
        t1 = QPushButton(L("▶ صحيحة", "▶ Correct"))
        t1.clicked.connect(lambda: self.ctx.speaker.say(self.sp_correct.text().split("|")[0].strip(), sp["rate"]))
        t2 = QPushButton(L("▶ خاطئة", "▶ Wrong"))
        t2.clicked.connect(lambda: self.ctx.speaker.say(self.sp_wrong.text().split("|")[0].strip(), sp["rate"]))
        row = QHBoxLayout()
        for x in (save, t1, t2):
            row.addWidget(x)
        row.addStretch(1)
        f.addRow(status)
        f.addRow(self.sp_enabled)
        f.addRow(self.sp_read)
        f.addRow(L("عند الإجابة الصحيحة (افصل بين العبارات بـ |)", "On a correct answer (separate phrases with |)"), self.sp_correct)
        f.addRow(L("عند الإجابة الخاطئة", "On a wrong answer"), self.sp_wrong)
        f.addRow(L("عند الوصول إلى مكة", "On reaching Makkah"), self.sp_arrival)
        f.addRow(row)
        return box

    def _save_speech(self) -> None:
        split = lambda t: [x.strip() for x in t.split("|") if x.strip()]  # noqa: E731
        self.ctx.repo.set_setting("journey_speech", {
            "enabled": self.sp_enabled.isChecked(),
            "read_question": self.sp_read.isChecked(),
            "correct": split(self.sp_correct.text()),
            "wrong": split(self.sp_wrong.text()),
            "arrival": self.sp_arrival.text().strip(),
        })
        QMessageBox.information(self, L("تم", "Done"), L("حُفظت إعدادات النطق.", "Speech settings saved."))
