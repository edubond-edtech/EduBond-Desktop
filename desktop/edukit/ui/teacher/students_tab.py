"""👥 الطلاب والصفوف — مع الاستيراد والتصدير عبر Excel."""
from __future__ import annotations

from ..lang import L, direction

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import SchoolClass, Student
from ...data import excel_io


class _Form(QDialog):
    def __init__(self, parent, title: str, fields: list[tuple[str, QWidget]]):
        super().__init__(parent)
        self.setLayoutDirection(direction())
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        for label, w in fields:
            form.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L("حفظ", "Save"))
        bb.button(QDialogButtonBox.Cancel).setText(L("إلغاء", "Cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class StudentsTab(QWidget):
    @property
    def COLS(self) -> list[str]:  # noqa: N802
        return [L("الاسم", "Name"), L("تاريخ الميلاد", "Birth date"), L("رقم الهوية", "ID number"),
                L("السنة الدراسية", "School year"), L("الصف", "Class"), L("رقم الطالب", "Student no.")]

    def __init__(self, ctx, on_change=lambda: None):
        super().__init__()
        self.ctx = ctx
        self.on_change = on_change
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        lay = QHBoxLayout(self)
        split = QSplitter()
        lay.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel(L("<b>الصفوف</b>", "<b>Classes</b>")))
        self.classes = QListWidget()
        self.classes.currentRowChanged.connect(lambda _r: self.load_students())
        ll.addWidget(self.classes, 1)
        row = QHBoxLayout()
        for text, fn in ((L("＋ صف", "＋ Class"), self.add_class), (L("تعديل", "Edit"), self.edit_class), (L("حذف", "Delete"), self.delete_class)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        split.addWidget(left)

        self.right_tabs = QTabWidget()
        right = QWidget()
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("H1")
        self.search = QLineEdit()
        self.search.setPlaceholderText(L("🔎 بحث بالاسم أو رقم الهوية", "🔎 Search by name or ID number"))
        self.search.textChanged.connect(lambda _t: self.load_students())
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.search)
        rl.addLayout(top)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda _i: self.edit_student())
        rl.addWidget(self.table, 1)
        brow = QHBoxLayout()
        add = QPushButton(L("＋ طالب", "＋ Student"))
        add.setObjectName("Primary")
        add.clicked.connect(self.add_student)
        edit = QPushButton(L("تعديل", "Edit"))
        edit.clicked.connect(self.edit_student)
        dele = QPushButton(L("حذف", "Delete"))
        dele.setObjectName("Danger")
        dele.clicked.connect(self.delete_student)
        for b in (add, edit, dele):
            brow.addWidget(b)
        brow.addStretch(1)
        rl.addLayout(brow)
        xrow = QHBoxLayout()
        imp = QPushButton(L("📥 استيراد الطلاب من Excel", "📥 Import students from Excel"))
        imp.setObjectName("Primary")
        imp.clicked.connect(self.import_excel)
        tpl = QPushButton(L("📄 تنزيل قالب Excel", "📄 Download Excel template"))
        tpl.clicked.connect(self.save_template)
        exp = QPushButton(L("📤 تصدير الطلاب", "📤 Export students"))
        exp.clicked.connect(self.export_excel)
        for b in (imp, tpl, exp):
            xrow.addWidget(b)
        xrow.addStretch(1)
        rl.addLayout(xrow)
        hint = QLabel(L("أعمدة الملف: الاسم، تاريخ الميلاد، رقم الهوية، السنة الدراسية، الصف (ورقم الطالب اختياري). ", "File columns: name, birth date, ID number, school year, class (student no. optional). ")
                      + L("الطالب الموجود بنفس رقم الهوية تُحدَّث بياناته، والصف غير الموجود يُنشأ تلقائيًا.", "A student with the same ID number is updated; a missing class is created automatically."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        rl.addWidget(hint)
        self.right_tabs.addTab(right, L("الطلاب", "Students"))
        self.right_tabs.addTab(self._build_teams(), L("الفرق", "Teams"))
        split.addWidget(self.right_tabs)
        split.setSizes([260, 950])
        self.reload()

    # -------------------------------------------------------------------- teams
    def _build_teams(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.teams_title = QLabel()
        self.teams_title.setObjectName("H1")
        v.addWidget(self.teams_title)
        self.teams = QTableWidget(0, 3)
        self.teams.setHorizontalHeaderLabels([L("الفريق", "Team"), L("عدد الأعضاء", "Members"), L("الأعضاء", "Member names")])
        self.teams.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.teams.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.teams.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.teams.verticalHeader().setVisible(False)
        self.teams.doubleClicked.connect(lambda _i: self.edit_team())
        v.addWidget(self.teams, 1)
        row = QHBoxLayout()
        add = QPushButton(L("＋ فريق جديد", "＋ New team"))
        add.setObjectName("Primary")
        add.clicked.connect(self.add_team)
        ed = QPushButton(L("تعديل الفريق", "Edit team"))
        ed.clicked.connect(self.edit_team)
        de = QPushButton(L("حذف الفريق", "Delete team"))
        de.setObjectName("Danger")
        de.clicked.connect(self.delete_team)
        for b in (add, ed, de):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        note = QLabel(L("اختر صفًا من القائمة، ثم أنشئ فرقًا بتحديد أعضائها من طلاب الصف. تظهر نتائج الفريق في تقرير كل عضو.", "Choose a class in the list, then create teams by ticking members from the class. Team results appear in each member's report."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        v.addWidget(note)
        return w

    def load_teams(self) -> None:
        c = self.current_class()
        teams = self.ctx.repo.list_teams(c.id if c else None)
        self.teams_title.setText(L(f"{c.name if c else 'كل الصفوف'} — {len(teams)} فرق", f"{c.name if c else 'All classes'} — {len(teams)} teams"))
        self.teams.setRowCount(len(teams))
        for r, t in enumerate(teams):
            members = L("، ", ", ").join(m.name for m in t["members"])
            for col, val in enumerate((t["name"] if c else f"{t['name']} ({t['class_name']})", str(len(t["members"])), members)):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, t["id"])
                self.teams.setItem(r, col, it)

    def _team_dialog(self, class_id: int, name: str = "", members: set[int] | None = None) -> tuple[str, list[int]] | None:
        dlg = QDialog(self)
        dlg.setLayoutDirection(direction())
        dlg.setWindowTitle(L("الفريق", "Team"))
        dlg.setMinimumSize(420, 480)
        v = QVBoxLayout(dlg)
        f = QFormLayout()
        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText(L("مثال: فريق النور", "e.g. Team Nur"))
        f.addRow(L("اسم الفريق", "Team name"), name_edit)
        v.addLayout(f)
        v.addWidget(QLabel(L("اختر أعضاء الفريق من طلاب الصف:", "Tick the team members from the class:")))
        lst = QListWidget()
        for st in self.ctx.repo.list_students(class_id):
            it = QListWidgetItem(st.name)
            it.setData(Qt.UserRole, st.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if members and st.id in members else Qt.Unchecked)
            lst.addItem(it)
        v.addWidget(lst, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L("حفظ", "Save"))
        bb.button(QDialogButtonBox.Cancel).setText(L("إلغاء", "Cancel"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if not dlg.exec() or not name_edit.text().strip():
            return None
        chosen = [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]
        return name_edit.text().strip(), chosen

    def add_team(self) -> None:
        c = self.current_class()
        if c is None:
            QMessageBox.information(self, L("اختر صفًا", "Choose a class"), L("اختر صفًا من القائمة أولًا؛ الفريق يُنشأ داخل صف.", "Choose a class first; a team belongs to a class."))
            return
        res = self._team_dialog(c.id)
        if res:
            try:
                self.ctx.repo.add_team(c.id, res[0], res[1])
            except Exception as exc:
                QMessageBox.warning(self, L("تعذّر الحفظ", "Could not save"), L("يوجد فريق بهذا الاسم في الصف.", "This class already has a team with that name.") if "UNIQUE" in str(exc) else str(exc))
                return
            self.reload()

    def _selected_team(self) -> dict | None:
        r = self.teams.currentRow()
        return self.ctx.repo.get_team(self.teams.item(r, 0).data(Qt.UserRole)) if r >= 0 else None

    def edit_team(self) -> None:
        t = self._selected_team()
        if not t:
            return
        res = self._team_dialog(t["class_id"], t["name"], {m.id for m in t["members"]})
        if res:
            try:
                self.ctx.repo.update_team(t["id"], res[0], res[1])
            except Exception as exc:
                QMessageBox.warning(self, L("تعذّر الحفظ", "Could not save"), L("يوجد فريق بهذا الاسم في الصف.", "This class already has a team with that name.") if "UNIQUE" in str(exc) else str(exc))
                return
            self.reload()

    def delete_team(self) -> None:
        t = self._selected_team()
        if t and QMessageBox.question(self, L("حذف الفريق", "Delete team"), L(f"حذف الفريق «{t['name']}»؟ يبقى الطلاب ونتائجهم.", f"Delete team «{t['name']}»? Students and their results are kept.")) == QMessageBox.Yes:
            self.ctx.repo.delete_team(t["id"])
            self.reload()

    # ------------------------------------------------------------------ classes
    def current_class(self) -> SchoolClass | None:
        it = self.classes.currentItem()
        return it.data(Qt.UserRole) if it else None

    def reload(self, select_id: int | None = None) -> None:
        cur = select_id or (self.current_class().id if self.current_class() else None)
        self.classes.clear()
        all_item = QListWidgetItem(L("كل الطلاب", "All students"))
        all_item.setData(Qt.UserRole, None)
        self.classes.addItem(all_item)
        for c in self.ctx.repo.list_classes():
            it = QListWidgetItem(f"{c.name}" + (f"  ·  {c.grade}" if c.grade else ""))
            it.setData(Qt.UserRole, c)
            self.classes.addItem(it)
            if c.id == cur:
                self.classes.setCurrentItem(it)
        if self.classes.currentRow() < 0:
            self.classes.setCurrentRow(0)
        self.load_students()
        self.on_change()

    def load_students(self) -> None:
        if hasattr(self, "teams"):
            self.load_teams()
        c = self.current_class()
        names = {x.id: x.name for x in self.ctx.repo.list_classes()}
        students = self.ctx.repo.list_students(c.id if c else None)
        q = self.search.text().strip()
        if q:
            students = [s for s in students if q in s.name or q in s.national_id]
        self.title.setText(L(f"{c.name if c else 'كل الطلاب'} ({len(students)})", f"{c.name if c else 'All students'} ({len(students)})"))
        self.table.setRowCount(len(students))
        for r, s in enumerate(students):
            for col, v in enumerate((s.name, s.birth_date, s.national_id, s.school_year, names.get(s.class_id, "—"), s.student_no)):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, s)
                self.table.setItem(r, col, it)

    def _class_form(self, c: SchoolClass) -> bool:
        name, grade = QLineEdit(c.name), QLineEdit(c.grade)
        grade.setPlaceholderText(L("مثال: الرابع", "e.g. Grade 4"))
        if _Form(self, L("الصف", "Class"), [(L("اسم الصف", "Class name"), name), (L("المرحلة", "Grade"), grade)]).exec() and name.text().strip():
            c.name, c.grade = name.text().strip(), grade.text().strip()
            return True
        return False

    def add_class(self) -> None:
        c = SchoolClass("")
        if self._class_form(c):
            try:
                self.ctx.repo.add_class(c)
            except Exception:
                QMessageBox.warning(self, L("تعذّرت الإضافة", "Could not add"), L("يوجد صف بهذا الاسم.", "A class with this name already exists."))
                return
            self.reload(c.id)

    def edit_class(self) -> None:
        c = self.current_class()
        if c and self._class_form(c):
            self.ctx.repo.update_class(c)
            self.reload(c.id)

    def delete_class(self) -> None:
        c = self.current_class()
        if c and QMessageBox.question(self, L("حذف الصف", "Delete class"), L(f"حذف الصف «{c.name}»؟ يبقى طلابه في البرنامج بدون صف.", f"Delete class «{c.name}»? Its students stay, without a class.")) == QMessageBox.Yes:
            self.ctx.repo.delete_class(c.id)
            self.reload()

    # ----------------------------------------------------------------- students
    def _student_form(self, s: Student) -> bool:
        name, nid, year, sno = QLineEdit(s.name), QLineEdit(s.national_id), QLineEdit(s.school_year), QLineEdit(s.student_no)
        year.setPlaceholderText(L("مثال: 2026/2027", "e.g. 2026/2027"))
        has_birth = QCheckBox(L("معروف", "Known"))
        birth = QDateEdit()
        birth.setCalendarPopup(True)
        birth.setDisplayFormat("yyyy-MM-dd")
        d = QDate.fromString(s.birth_date, "yyyy-MM-dd") if s.birth_date else QDate(2016, 1, 1)
        birth.setDate(d)
        has_birth.setChecked(bool(s.birth_date))
        birth.setEnabled(bool(s.birth_date))
        has_birth.toggled.connect(birth.setEnabled)
        brow = QHBoxLayout()
        brow.addWidget(birth, 1)
        brow.addWidget(has_birth)
        bw = QWidget()
        bw.setLayout(brow)
        cls = QComboBox()
        cls.addItem(L("— بدون صف —", "— no class —"), None)
        for c in self.ctx.repo.list_classes():
            cls.addItem(c.name, c.id)
        cls.setCurrentIndex(max(0, cls.findData(s.class_id)))
        fields = [(L("الاسم", "Name"), name), (L("تاريخ الميلاد", "Birth date"), bw), (L("رقم الهوية", "ID number"), nid), (L("السنة الدراسية", "School year"), year), (L("الصف", "Class"), cls), (L("رقم الطالب", "Student no."), sno)]
        if _Form(self, L("الطالب", "Student"), fields).exec() and name.text().strip():
            s.name, s.national_id, s.school_year, s.student_no = name.text().strip(), nid.text().strip(), year.text().strip(), sno.text().strip()
            s.birth_date = birth.date().toString("yyyy-MM-dd") if has_birth.isChecked() else ""
            s.class_id = cls.currentData()
            return True
        return False

    def _selected(self) -> Student | None:
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 else None

    def _save(self, s: Student, new: bool) -> bool:
        try:
            (self.ctx.repo.add_student if new else self.ctx.repo.update_student)(s)
            return True
        except Exception as exc:
            QMessageBox.warning(self, L("تعذّر الحفظ", "Could not save"), L("يوجد طالب آخر بنفس رقم الهوية.", "Another student has the same ID number.") if "UNIQUE" in str(exc) else str(exc))
            return False

    def add_student(self) -> None:
        c = self.current_class()
        s = Student("", c.id if c else None)
        if self._student_form(s) and self._save(s, True):
            self.reload()

    def edit_student(self) -> None:
        s = self._selected()
        if s and self._student_form(s) and self._save(s, False):
            self.reload()

    def delete_student(self) -> None:
        s = self._selected()
        if s and QMessageBox.question(self, L("حذف الطالب", "Delete student"), L(f"حذف {s.name}؟ تبقى نتائجه السابقة في التقارير.", f"Delete {s.name}? Past results stay in the reports.")) == QMessageBox.Yes:
            self.ctx.repo.delete_student(s.id)
            self.reload()

    # -------------------------------------------------------------------- excel
    def import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, L("استيراد الطلاب من Excel", "Import students from Excel"), "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            rep = excel_io.import_students(self.ctx.repo, path)
        except Exception as exc:
            QMessageBox.warning(self, L("تعذّر الاستيراد", "Import failed"), L(f"تعذّر قراءة الملف: {exc}", f"Could not read the file: {exc}"))
            return
        self.reload()
        (QMessageBox.warning if rep.errors else QMessageBox.information)(self, L("نتيجة الاستيراد", "Import result"), rep.summary_ar())

    def save_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, L("حفظ قالب الطلاب", "Save students template"), L("قالب-الطلاب.xlsx", "students-template.xlsx"), "Excel (*.xlsx)")
        if path:
            excel_io.write_students_template(path)
            QMessageBox.information(self, L("تم", "Done"), L("حُفظ القالب. املأه في Excel ثم استورده.", "Template saved. Fill it in Excel, then import it."))

    def export_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, L("تصدير الطلاب", "Export students"), L("الطلاب.xlsx", "students.xlsx"), "Excel (*.xlsx)")
        if path:
            n = excel_io.export_students(self.ctx.repo, path)
            QMessageBox.information(self, L("تم", "Done"), L(f"صُدّر {n} طالبًا.", f"Exported {n} students."))
