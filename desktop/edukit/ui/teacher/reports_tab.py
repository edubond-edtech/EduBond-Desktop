"""📊 التقارير / Reports: a date range, and under every student all of their tests (individual, team, whole class)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...data import excel_io
from ..lang import L, direction, is_ar


class ReportsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        lay = QVBoxLayout(self)
        head = QLabel(L("📊 التقارير", "📊 Reports"))
        head.setObjectName("H1")
        lay.addWidget(head)

        f1 = QHBoxLayout()
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for d in (self.date_from, self.date_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
        today = QDate.currentDate()
        self.date_from.setDate(QDate(today.year(), today.month(), 1))
        self.date_to.setDate(today)
        self.period = QComboBox()
        for key, ar, en in (("month", "هذا الشهر", "This month"), ("week", "آخر ٧ أيام", "Last 7 days"), ("today", "اليوم", "Today"),
                            ("year", "هذه السنة", "This year"), ("all", "كل الفترات", "All time"), ("custom", "مخصّص", "Custom")):
            self.period.addItem(L(ar, en), key)
        self.period.currentIndexChanged.connect(self._period_changed)
        f1.addWidget(QLabel(L("الفترة:", "Period:")))
        f1.addWidget(self.period)
        f1.addWidget(QLabel(L("من", "From")))
        f1.addWidget(self.date_from)
        f1.addWidget(QLabel(L("إلى", "To")))
        f1.addWidget(self.date_to)
        f1.addSpacing(16)
        f1.addWidget(QLabel(L("الصف:", "Class:")))
        self.cls = QComboBox()
        self.cls.currentIndexChanged.connect(lambda _i: self._load_students())
        f1.addWidget(self.cls)
        f1.addWidget(QLabel(L("الطالب:", "Student:")))
        self.student = QComboBox()
        f1.addWidget(self.student, 1)
        show = QPushButton(L("عرض التقرير", "Show report"))
        show.setObjectName("Primary")
        show.clicked.connect(self.refresh)
        f1.addWidget(show)
        lay.addLayout(f1)

        self.summary = QLabel()
        self.summary.setStyleSheet("font-size: 16px; font-weight: 700;")
        lay.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([L("الطالب / الاختبار", "Student / test"), L("الدرس", "Lesson"), L("المشاركة", "Mode"),
                                   L("الصحيحة / المُجابة", "Correct / answered"), L("النسبة", "Percent"), L("الحالة", "Status")])
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setAlternatingRowColors(True)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        exp = QPushButton(L("📤 تصدير التقرير إلى Excel", "📤 Export report to Excel"))
        exp.clicked.connect(self.export_excel)
        expand = QPushButton(L("توسيع الكل", "Expand all"))
        expand.clicked.connect(self.tree.expandAll)
        collapse = QPushButton(L("طي الكل", "Collapse all"))
        collapse.clicked.connect(self.tree.collapseAll)
        for b in (exp, expand, collapse):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self._report: list[dict] = []
        self.reload_classes()

    # ---------------------------------------------------------------- filters
    def _period_changed(self) -> None:
        key = self.period.currentData()
        today = QDate.currentDate()
        rng = {"month": (QDate(today.year(), today.month(), 1), today), "week": (today.addDays(-6), today),
               "today": (today, today), "year": (QDate(today.year(), 1, 1), today), "all": (QDate(2000, 1, 1), today)}.get(key)
        custom = key == "custom"
        self.date_from.setEnabled(custom)
        self.date_to.setEnabled(custom)
        if rng:
            self.date_from.setDate(rng[0])
            self.date_to.setDate(rng[1])
        self.refresh()

    def reload_classes(self) -> None:
        cur = self.cls.currentData()
        self.cls.blockSignals(True)
        self.cls.clear()
        self.cls.addItem(L("كل الصفوف", "All classes"), None)
        for c in self.ctx.repo.list_classes():
            self.cls.addItem(c.name, c.id)
        self.cls.setCurrentIndex(max(0, self.cls.findData(cur)))
        self.cls.blockSignals(False)
        self._load_students()
        self._period_changed()

    def _load_students(self) -> None:
        cur = self.student.currentData()
        self.student.clear()
        self.student.addItem(L("كل الطلاب", "All students"), None)
        for s in self.ctx.repo.list_students(self.cls.currentData()):
            self.student.addItem(s.name, s.id)
        self.student.setCurrentIndex(max(0, self.student.findData(cur)))

    def _dates(self) -> tuple[str | None, str | None]:
        if self.period.currentData() == "all":
            return None, None
        return self.date_from.date().toString("yyyy-MM-dd"), self.date_to.date().toString("yyyy-MM-dd")

    # ----------------------------------------------------------------- report
    def refresh(self) -> None:
        d1, d2 = self._dates()
        report = self.ctx.repo.student_report(d1, d2, self.cls.currentData(), self.student.currentData())
        classes = {c.id: c.name for c in self.ctx.repo.list_classes()}
        for r in report:
            r["class_name"] = classes.get(r["student"].class_id, "")
        self._report = report
        mode_name = {"individual": L("فردي", "Individual"), "team": L("فريق", "Team"), "class": L("الصف كله", "Whole class")}
        self.tree.clear()
        tests = 0
        for r in report:
            st = r["student"]
            pct = f"{r['percent']:.0f}%" if r["percent"] is not None else "—"
            top = QTreeWidgetItem([f"👤 {st.name}", r["class_name"], L(f"{r['tests']} اختبار", f"{r['tests']} tests"),
                                   f"{r['correct']} / {r['answered']}", pct, ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for s in r["sessions"]:
                tests += 1
                spct = f"{s['percent']:.0f}%" if s["percent"] is not None else "—"
                who = mode_name.get(s["mode"], s["mode"]) + (f" — {s.get('team_label') or s.get('team_name')}" if s["mode"] == "team" else "")
                status = L("مكتمل", "Finished") if s.get("ended_at") else L("غير مكتمل", "Unfinished")
                QTreeWidgetItem(top, [f"🗓 {s['started_local']}", s["lesson_path"] or (s.get("lesson_name") or L("وحدة كاملة", "Whole unit")),
                                      who, f"{s['correct']} / {s['answered']}", spct, status])
        d1, d2 = self._dates()
        period = f"{d1} → {d2}" if d1 else L("كل الفترات", "all time")
        self.summary.setText(L(f"الفترة: {period}   ·   الطلاب: {len(report)}   ·   الاختبارات: {tests}",
                               f"Period: {period}   ·   Students: {len(report)}   ·   Tests: {tests}"))
        if len(report) <= 12:
            self.tree.expandAll()

    def export_excel(self) -> None:
        if not self._report:
            self.refresh()
        d1, d2 = self._dates()
        name = f"{L('تقرير-الطلاب', 'student-report')}-{datetime.now():%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, L("تصدير التقرير", "Export report"), name, "Excel (*.xlsx)")
        if path:
            n = excel_io.export_student_report(self._report, path, d1 or "", d2 or "", arabic=is_ar())
            QMessageBox.information(self, L("تم", "Done"), L(f"صُدّر تقرير {len(self._report)} طالبًا و{n} اختبارًا.",
                                                              f"Exported {len(self._report)} students and {n} tests."))

