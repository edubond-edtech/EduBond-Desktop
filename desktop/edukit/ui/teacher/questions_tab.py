"""Question banks and question editor."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QHeaderView,
)

from ...core.models import Option, Question, QuestionBank
from ...data.seed import export_bank, import_bank

KEYS = "ABCDEF"


class QuestionDialog(QDialog):
    def __init__(self, parent: QWidget, ctx, q: Question):
        super().__init__(parent)
        self.ctx, self.q = ctx, q
        self.setWindowTitle("Edit question" if q.id else "New question")
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit(q.code)
        self.qtype = QComboBox()
        for t, label in (("single_choice", "Single choice"), ("true_false", "True / False"), ("multi_choice", "Multiple correct (partial credit)")):
            self.qtype.addItem(label, t)
        self.qtype.setCurrentIndex(max(0, self.qtype.findData(q.qtype)))
        self.prompt_en = QLineEdit(q.prompt.get("en", ""))
        self.prompt_ar = QLineEdit(q.prompt.get("ar", ""))
        self.prompt_ar.setLayoutDirection(Qt.RightToLeft)
        self.time = QSpinBox()
        self.time.setRange(0, 600)
        self.time.setSuffix(" s")
        self.time.setSpecialValueText("No limit")
        self.time.setValue(q.time_limit_s)
        self.points = QSpinBox()
        self.points.setRange(1, 100)
        self.points.setValue(q.points)
        img_row = QHBoxLayout()
        self.image = QLineEdit(q.image_path or "")
        pick = QPushButton("Choose…")
        pick.clicked.connect(self._pick_image)
        img_row.addWidget(self.image)
        img_row.addWidget(pick)
        self.expl_en = QLineEdit(q.explanation.get("en", ""))
        self.expl_ar = QLineEdit(q.explanation.get("ar", ""))
        self.expl_ar.setLayoutDirection(Qt.RightToLeft)
        form.addRow("Code (sent to devices)", self.code)
        form.addRow("Type", self.qtype)
        form.addRow("Question (English)", self.prompt_en)
        form.addRow("السؤال (عربي)", self.prompt_ar)
        form.addRow("Timer", self.time)
        form.addRow("Points", self.points)
        form.addRow("Image", img_row)
        form.addRow("Explanation (EN)", self.expl_en)
        form.addRow("الشرح (عربي)", self.expl_ar)
        lay.addLayout(form)

        box = QGroupBox("Answer options — tick the correct answer(s)")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("Key"), 0, 0)
        grid.addWidget(QLabel("English"), 0, 1)
        grid.addWidget(QLabel("عربي"), 0, 2)
        grid.addWidget(QLabel("Correct"), 0, 3)
        self.opt_rows: list[tuple[QLineEdit, QLineEdit, QCheckBox]] = []
        correct = set(q.correct if isinstance(q.correct, list) else [])
        for i, k in enumerate(KEYS):
            opt = next((o for o in q.options if o.key == k), None)
            en = QLineEdit(opt.text.get("en", "") if opt else "")
            ar = QLineEdit(opt.text.get("ar", "") if opt else "")
            ar.setLayoutDirection(Qt.RightToLeft)
            cb = QCheckBox()
            cb.setChecked(k in correct)
            cb.toggled.connect(lambda on, cb=cb: self._exclusive(cb, on))
            grid.addWidget(QLabel(f"<b>{k}</b>"), i + 1, 0)
            grid.addWidget(en, i + 1, 1)
            grid.addWidget(ar, i + 1, 2)
            grid.addWidget(cb, i + 1, 3)
            self.opt_rows.append((en, ar, cb))
        note = QLabel("Physical controllers in the prototype have 4 buttons (A–D). Options E–F are for future 6-button kits / on-screen answers.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        grid.addWidget(note, len(KEYS) + 1, 0, 1, 4)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _exclusive(self, cb: QCheckBox, on: bool) -> None:
        if on and self.qtype.currentData() != "multi_choice":
            for _, _, other in self.opt_rows:
                if other is not cb:
                    other.setChecked(False)

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.gif *.bmp)")
        if path:
            dest_dir = self.ctx.data_dir / "images"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / Path(path).name
            if Path(path).resolve() != dest.resolve():
                shutil.copy2(path, dest)
            self.image.setText(dest.name)  # stored relative to the data folder -> portable

    def _save(self) -> None:
        q = self.q
        q.code = self.code.text().strip()
        q.qtype = self.qtype.currentData()
        q.prompt = {k: v for k, v in (("en", self.prompt_en.text().strip()), ("ar", self.prompt_ar.text().strip())) if v}
        q.options, q.correct = [], []
        for k, (en, ar, cb) in zip(KEYS, self.opt_rows):
            text = {lang: w.text().strip() for lang, w in (("en", en), ("ar", ar)) if w.text().strip()}
            if text:
                q.options.append(Option(k, text))
                if cb.isChecked():
                    q.correct.append(k)
        q.time_limit_s = self.time.value()
        q.points = self.points.value()
        q.image_path = self.image.text().strip() or None
        q.explanation = {k: v for k, v in (("en", self.expl_en.text().strip()), ("ar", self.expl_ar.text().strip())) if v}
        try:
            if q.id:
                self.ctx.repo.update_question(q)
            else:
                self.ctx.repo.add_question(q)
        except Exception as exc:  # validation or UNIQUE(bank, code)
            msg = "A question with this code already exists in the bank." if "UNIQUE" in str(exc) else str(exc)
            QMessageBox.warning(self, "Cannot save question", msg)
            return
        self.accept()


class BankDialog(QDialog):
    def __init__(self, parent: QWidget, bank: QuestionBank):
        super().__init__(parent)
        self.bank = bank
        self.setWindowTitle("Question bank")
        form = QFormLayout(self)
        self.name = QLineEdit(bank.name)
        self.subject = QLineEdit(bank.subject)
        self.grade = QLineEdit(bank.grade)
        form.addRow("Name", self.name)
        form.addRow("Subject", self.subject)
        form.addRow("Grade", self.grade)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _ok(self) -> None:
        if not self.name.text().strip():
            return
        self.bank.name, self.bank.subject, self.bank.grade = self.name.text().strip(), self.subject.text().strip(), self.grade.text().strip()
        self.accept()


class QuestionsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        lay = QHBoxLayout(self)
        split = QSplitter()
        lay.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Question banks</b> (by subject & grade)"))
        self.banks = QListWidget()
        self.banks.currentRowChanged.connect(lambda _r: self.load_questions())
        ll.addWidget(self.banks, 1)
        row = QGridLayout()
        for i, (text, fn) in enumerate((("New bank", self.add_bank), ("Edit", self.edit_bank), ("Delete", self.delete_bank), ("Import…", self.import_bank), ("Export…", self.export_bank))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b, i // 3, i % 3)
        ll.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.title = QLabel()
        self.title.setObjectName("H1")
        rl.addWidget(self.title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Code", "Question (EN)", "السؤال", "Options", "Correct", "Timer"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda _i: self.edit_question())
        rl.addWidget(self.table, 1)
        brow = QHBoxLayout()
        add = QPushButton("＋ Add question")
        add.setObjectName("Primary")
        add.clicked.connect(self.add_question)
        edit = QPushButton("Edit")
        edit.clicked.connect(self.edit_question)
        dele = QPushButton("Delete")
        dele.setObjectName("Danger")
        dele.clicked.connect(self.delete_question)
        brow.addWidget(add)
        brow.addWidget(edit)
        brow.addWidget(dele)
        brow.addStretch(1)
        rl.addLayout(brow)
        split.addWidget(right)
        split.setSizes([300, 900])
        self.reload()

    # ----------------------------------------------------------------- banks
    def current_bank(self) -> QuestionBank | None:
        it = self.banks.currentItem()
        return it.data(Qt.UserRole) if it else None

    def reload(self, select_id: int | None = None) -> None:
        cur = select_id or (self.current_bank().id if self.current_bank() else None)
        counts = self.ctx.repo.bank_question_counts()
        self.banks.clear()
        for b in self.ctx.repo.list_banks():
            it = QListWidgetItem(f"{b.name}\n{b.subject} · {b.grade} · {counts.get(b.id, 0)} questions")
            it.setData(Qt.UserRole, b)
            self.banks.addItem(it)
            if b.id == cur:
                self.banks.setCurrentItem(it)
        if self.banks.currentRow() < 0 and self.banks.count():
            self.banks.setCurrentRow(0)
        self.load_questions()

    def add_bank(self) -> None:
        b = QuestionBank("New bank")
        if BankDialog(self, b).exec():
            try:
                self.ctx.repo.add_bank(b)
            except Exception as exc:
                QMessageBox.warning(self, "Cannot create bank", str(exc))
                return
            self.reload(b.id)

    def edit_bank(self) -> None:
        b = self.current_bank()
        if b and BankDialog(self, b).exec():
            self.ctx.repo.update_bank(b)
            self.reload(b.id)

    def delete_bank(self) -> None:
        b = self.current_bank()
        if b and QMessageBox.question(self, "Delete bank", f"Delete '{b.name}' and all its questions?\nPast results are kept.") == QMessageBox.Yes:
            self.ctx.repo.delete_bank(b.id)
            self.reload()

    def import_bank(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import question bank", "", "EduKit bank (*.json)")
        if path:
            try:
                b = import_bank(self.ctx.repo, path)
            except Exception as exc:
                QMessageBox.warning(self, "Import failed", str(exc))
                return
            self.reload(b.id)

    def export_bank(self) -> None:
        b = self.current_bank()
        if not b:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export question bank", f"{b.name}.json", "EduKit bank (*.json)")
        if path:
            export_bank(self.ctx.repo, b.id, path)

    # ------------------------------------------------------------- questions
    def load_questions(self) -> None:
        b = self.current_bank()
        self.title.setText(b.name if b else "No bank selected")
        self.table.setRowCount(0)
        if not b:
            return
        for q in self.ctx.repo.list_questions(b.id):
            r = self.table.rowCount()
            self.table.insertRow(r)
            correct = ", ".join(q.correct) if isinstance(q.correct, list) else str(q.correct)
            prompt_ar = q.prompt.get("ar", "")
            if q.qtype == "arrange":
                words = {o.key: o.label("ar") for o in q.options}
                prompt_ar = " ".join(words.get(k, "?") for k in q.correct)
                correct = "plates " + correct
            vals = [q.code, q.prompt.get("en", ""), prompt_ar, str(len(q.options)), correct, f"{q.time_limit_s}s" if q.time_limit_s else "—"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, q.id)
                self.table.setItem(r, c, it)

    def _selected_qid(self) -> int | None:
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 else None

    def add_question(self) -> None:
        b = self.current_bank()
        if not b:
            QMessageBox.information(self, "No bank", "Create a question bank first.")
            return
        q = Question(code=self.ctx.repo.next_question_code(b.id), prompt={}, bank_id=b.id, time_limit_s=30)
        if QuestionDialog(self, self.ctx, q).exec():
            self.reload()

    def edit_question(self) -> None:
        qid = self._selected_qid()
        q = self.ctx.repo.get_question(qid) if qid else None
        if q and q.qtype == "arrange":
            from .journey_tab import ArrangeQuestionDialog

            if ArrangeQuestionDialog(self, self.ctx, q).exec():
                self.reload()
        elif q and QuestionDialog(self, self.ctx, q).exec():
            self.reload()

    def delete_question(self) -> None:
        qid = self._selected_qid()
        if qid and QMessageBox.question(self, "Delete question", "Delete the selected question?") == QMessageBox.Yes:
            self.ctx.repo.delete_question(qid)
            self.reload()

