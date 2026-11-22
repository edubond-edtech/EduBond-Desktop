"""📚 المنهج والأسئلة: منهج ← مادة ← وحدة ← درس ← أسئلة، مع الاستيراد والتصدير عبر Excel."""
from __future__ import annotations

from ..lang import L, direction

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Question
from ...data import excel_io
from ..i18n import letter
from ..journey_view import ar
from .journey_tab import DEFAULT_PROMPT, ArrangeQuestionDialog, ChoiceQuestionDialog

class _Kinds(dict):
    def __getitem__(self, k: str) -> str:
        return {"curriculum": L("المنهج", "curriculum"), "subject": L("المادة", "subject"),
                "unit": L("الوحدة", "unit"), "lesson": L("الدرس", "lesson")}[k]


KIND_AR = _Kinds()
CHILD = {None: "curriculum", "curriculum": "subject", "subject": "unit", "unit": "lesson"}
ICON = {"curriculum": "📘", "subject": "📗", "unit": "📂", "lesson": "📝"}


class CurriculumTab(QWidget):
    def __init__(self, ctx, on_change=lambda: None):
        super().__init__()
        self.ctx = ctx
        self.on_change = on_change
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        lay = QVBoxLayout(self)
        head = QLabel(L("📚 المنهج والأسئلة", "📚 Curriculum & questions"))
        head.setObjectName("H1")
        lay.addWidget(head)
        split = QSplitter()
        lay.addWidget(split, 1)

        # ---------------- tree
        left = QWidget()
        ll = QVBoxLayout(left)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([L("الشجرة", "Tree"), L("الأسئلة", "Questions")])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setMinimumWidth(380)
        self.tree.currentItemChanged.connect(lambda *_: self.load_questions())
        ll.addWidget(self.tree, 1)
        g = QGridLayout()
        self.add_btn = QPushButton(L("＋ إضافة", "＋ Add"))
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self.add_child)
        add_root = QPushButton(L("＋ منهج جديد", "＋ New curriculum"))
        add_root.clicked.connect(lambda: self.add_child(root=True))
        ren = QPushButton(L("إعادة تسمية", "Rename"))
        ren.clicked.connect(self.rename)
        dele = QPushButton(L("حذف", "Delete"))
        dele.setObjectName("Danger")
        dele.clicked.connect(self.delete)
        for i, b in enumerate((self.add_btn, add_root, ren, dele)):
            g.addWidget(b, i // 2, i % 2)
        ll.addLayout(g)
        split.addWidget(left)

        # ---------------- questions
        right = QWidget()
        rl = QVBoxLayout(right)
        self.path_lbl = QLabel()
        self.path_lbl.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.path_lbl.setWordWrap(True)
        rl.addWidget(self.path_lbl)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([L("الرمز", "Code"), L("النوع", "Type"), L("السؤال", "Question"), L("الإجابة الصحيحة", "Correct answer"), L("صورة", "Media"), L("الوقت", "Time")])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda _i: self.edit_q())
        rl.addWidget(self.table, 1)
        qb = QHBoxLayout()
        for text, fn in ((L("＋ اختيار من متعدد", "＋ Multiple choice"), lambda: self.add_q("single_choice")), (L("＋ صح أو خطأ", "＋ True / false"), lambda: self.add_q("true_false")),
                         (L("＋ ترتيب كلمات", "＋ Word order"), lambda: self.add_q("arrange")), (L("تعديل", "Edit"), self.edit_q), (L("حذف السؤال", "Delete question"), self.delete_q)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text == L("حذف السؤال", "Delete question"):
                b.setObjectName("Danger")
            qb.addWidget(b)
        qb.addStretch(1)
        rl.addLayout(qb)
        xb = QHBoxLayout()
        imp = QPushButton(L("📥 استيراد أسئلة من Excel", "📥 Import questions from Excel"))
        imp.setObjectName("Primary")
        imp.clicked.connect(self.import_excel)
        tpl = QPushButton(L("📄 تنزيل قالب Excel", "📄 Download Excel template"))
        tpl.clicked.connect(self.save_template)
        exp = QPushButton(L("📤 تصدير أسئلة الدرس", "📤 Export lesson questions"))
        exp.clicked.connect(self.export_excel)
        for b in (imp, tpl, exp):
            xb.addWidget(b)
        xb.addStretch(1)
        rl.addLayout(xb)
        hint = QLabel(L("الاستيراد يضيف الأسئلة إلى الدرس المحدد. إذا ملأت أعمدة المادة والوحدة والدرس في الملف يُنشئها البرنامج تلقائيًا ", "Import adds questions to the selected lesson. If the file fills the subject, unit and lesson columns, EduKit creates them automatically ")
                      + L("(يمكن استيراد منهج كامل بملف واحد). الصور توضع بجانب ملف Excel أو في مجلد «صور».", "(a whole curriculum in one file). Put pictures/videos next to the Excel file or in a «صور» / «images» folder."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        rl.addWidget(hint)
        split.addWidget(right)
        split.setSizes([460, 820])
        self.reload()

    # ------------------------------------------------------------------ tree
    def _node(self) -> tuple[str | None, int | None]:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else (None, None)

    def reload(self, select: tuple[str, int] | None = None) -> None:
        select = select or self._node()
        self.tree.clear()
        target = None
        for c in self.ctx.repo.curriculum_tree():
            ci = self._item(self.tree, "curriculum", c["id"], c["name"], sum(l["count"] for s in c["subjects"] for u in s["units"] for l in u["lessons"]))
            target = target or (ci if select == ("curriculum", c["id"]) else None)
            for s in c["subjects"]:
                si = self._item(ci, "subject", s["id"], s["name"], sum(l["count"] for u in s["units"] for l in u["lessons"]))
                target = target or (si if select == ("subject", s["id"]) else None)
                for u in s["units"]:
                    ui = self._item(si, "unit", u["id"], u["name"], sum(l["count"] for l in u["lessons"]))
                    target = target or (ui if select == ("unit", u["id"]) else None)
                    for l in u["lessons"]:
                        li = self._item(ui, "lesson", l["id"], l["name"], l["count"])
                        target = target or (li if select == ("lesson", l["id"]) else None)
        self.tree.expandToDepth(2)
        if target:
            self.tree.setCurrentItem(target)
        self.load_questions()
        self.on_change()

    def _item(self, parent, kind: str, node_id: int, name: str, count: int) -> QTreeWidgetItem:  # noqa: ANN001
        it = QTreeWidgetItem(parent, [f"{ICON[kind]} {name}", ar(count)])
        it.setData(0, Qt.UserRole, (kind, node_id))
        return it

    def add_child(self, root: bool = False) -> None:
        kind, node_id = (None, None) if root else self._node()
        child = CHILD.get(kind)
        if child is None:
            QMessageBox.information(self, L("إضافة", "Add"), L("الدرس هو آخر مستوى. أضف أسئلة للدرس من الجهة الأخرى.", "A lesson is the last level. Add questions to it on the other side."))
            return
        name, ok = QInputDialog.getText(self, L(f"إضافة {KIND_AR[child]}", f"Add {KIND_AR[child]}"), L(f"اسم {KIND_AR[child]}:", f"{KIND_AR[child]} name:"))
        if not ok or not name.strip():
            return
        repo = self.ctx.repo
        try:
            if child == "curriculum":
                new = ("curriculum", repo.add_curriculum(name).id)
            elif child == "subject":
                new = ("subject", repo.add_subject(node_id, name).id)
            elif child == "unit":
                new = ("unit", repo.add_unit(node_id, name).id)
            else:
                new = ("lesson", repo.add_lesson(node_id, name).id)
        except Exception as exc:
            QMessageBox.warning(self, L("تعذّرت الإضافة", "Could not add"), L("الاسم مستعمل مسبقًا في هذا المستوى.", "That name is already used at this level.") if "UNIQUE" in str(exc) else str(exc))
            return
        self.reload(new)

    def rename(self) -> None:
        kind, node_id = self._node()
        if not kind:
            return
        old = self.tree.currentItem().text(0)[2:]
        name, ok = QInputDialog.getText(self, L("إعادة تسمية", "Rename"), L(f"الاسم الجديد لـ{KIND_AR[kind]}:", f"New name for the {KIND_AR[kind]}:"), text=old)
        if ok and name.strip():
            try:
                self.ctx.repo.rename_node(kind, node_id, name)
            except Exception as exc:
                QMessageBox.warning(self, L("تعذّرت إعادة التسمية", "Could not rename"), str(exc))
                return
            self.reload((kind, node_id))

    def delete(self) -> None:
        kind, node_id = self._node()
        if not kind:
            return
        name = self.tree.currentItem().text(0)
        if QMessageBox.question(self, L("حذف", "Delete"), L(f"حذف {KIND_AR[kind]} «{name}» وكل ما بداخله من وحدات ودروس وأسئلة؟\n(نتائج الطلاب السابقة تبقى محفوظة)", f"Delete the {KIND_AR[kind]} «{name}» and all its units, lessons and questions?\n(Past student results are kept)")) == QMessageBox.Yes:
            self.ctx.repo.delete_node(kind, node_id)
            self.reload()

    # ------------------------------------------------------------- questions
    def lesson_id(self) -> int | None:
        kind, node_id = self._node()
        return node_id if kind == "lesson" else None

    def load_questions(self) -> None:
        kind, node_id = self._node()
        self.table.setRowCount(0)
        if kind != "lesson":
            self.path_lbl.setText(L("اختر درسًا من الشجرة لعرض أسئلته", "Choose a lesson in the tree to see its questions") if kind else L("أنشئ منهجًا ثم مادة ثم وحدة ثم درسًا — أو استورد ملف Excel", "Create a curriculum, subject, unit and lesson — or import an Excel file"))
            return
        self.path_lbl.setText(self.ctx.repo.lesson_path(node_id))
        types = {"single_choice": L("اختيار من متعدد", "Multiple choice"), "true_false": L("صح أو خطأ", "True / false"), "arrange": L("ترتيب كلمات", "Word order"), "multi_choice": L("اختيار متعدد", "Multi-select"), "numeric": L("رقمي", "Numeric")}
        for q in self.ctx.repo.list_questions(node_id):
            words = {o.key: o.label("ar") for o in q.options}
            if q.qtype == "arrange":
                text, ans = q.text("ar"), " ".join(words.get(k, "") for k in q.correct)
            elif q.qtype == "true_false":
                text, ans = q.text("ar"), L("صح", "True") if q.correct == ["A"] else L("خطأ", "False")
            else:
                k0 = (q.correct or [""])[0]
                text, ans = q.text("ar"), f"{letter(k0, 'ar')} — {words.get(k0, '')}"
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, v in enumerate((q.code, types.get(q.qtype, q.qtype), text, ans, "🖼" if q.image_path else "", L(f"{ar(q.time_limit_s)} ث", f"{q.time_limit_s} s") if q.time_limit_s else "—")):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, q.id)
                self.table.setItem(r, c, it)

    def add_q(self, qtype: str) -> None:
        lid = self.lesson_id()
        if lid is None:
            QMessageBox.information(self, L("اختر درسًا", "Choose a lesson"), L("اختر درسًا من الشجرة أولًا.", "Choose a lesson in the tree first."))
            return
        q = Question(code=self.ctx.repo.next_question_code(lid), prompt={"ar": DEFAULT_PROMPT} if qtype == "arrange" else {},
                     qtype=qtype, bank_id=lid, time_limit_s=90 if qtype == "arrange" else 30)
        dlg = ArrangeQuestionDialog if qtype == "arrange" else ChoiceQuestionDialog
        if dlg(self, self.ctx, q).exec():
            self.reload()

    def _selected_q(self) -> Question | None:
        r = self.table.currentRow()
        return self.ctx.repo.get_question(self.table.item(r, 0).data(Qt.UserRole)) if r >= 0 else None

    def edit_q(self) -> None:
        q = self._selected_q()
        if q:
            dlg = ArrangeQuestionDialog if q.qtype == "arrange" else ChoiceQuestionDialog
            if dlg(self, self.ctx, q).exec():
                self.reload()

    def delete_q(self) -> None:
        q = self._selected_q()
        if q and QMessageBox.question(self, L("حذف", "Delete"), L("حذف السؤال المحدد؟", "Delete the selected question?")) == QMessageBox.Yes:
            self.ctx.repo.delete_question(q.id)
            self.reload()

    # ------------------------------------------------------------------ excel
    def import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, L("استيراد أسئلة من Excel", "Import questions from Excel"), "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            rep = excel_io.import_questions(self.ctx.repo, path, self.lesson_id(), self.ctx.data_dir / "images")
        except Exception as exc:
            QMessageBox.warning(self, L("تعذّر الاستيراد", "Import failed"), L(f"تعذّر قراءة الملف: {exc}", f"Could not read the file: {exc}"))
            return
        self.reload()
        (QMessageBox.warning if rep.errors else QMessageBox.information)(self, L("نتيجة الاستيراد", "Import result"), rep.summary_ar())

    def save_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, L("حفظ قالب الأسئلة", "Save questions template"), L("قالب-الأسئلة.xlsx", "questions-template.xlsx"), "Excel (*.xlsx)")
        if path:
            excel_io.write_questions_template(path)
            QMessageBox.information(self, L("تم", "Done"), L("حُفظ القالب. افتحه في Excel واقرأ ورقة «التعليمات».", "Template saved. Open it in Excel and read the «التعليمات» (instructions) sheet."))

    def export_excel(self) -> None:
        lid = self.lesson_id()
        if lid is None:
            QMessageBox.information(self, L("اختر درسًا", "Choose a lesson"), L("اختر درسًا من الشجرة أولًا.", "Choose a lesson in the tree first."))
            return
        name = self.tree.currentItem().text(0)[2:]
        path, _ = QFileDialog.getSaveFileName(self, L("تصدير أسئلة الدرس", "Export lesson questions"), f"{name}.xlsx", "Excel (*.xlsx)")
        if path:
            n = excel_io.export_questions(self.ctx.repo, lid, path)
            QMessageBox.information(self, L("تم", "Done"), L(f"صُدّر {ar(n)} سؤالًا.", f"Exported {n} questions."))
