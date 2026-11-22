"""Main window: teacher dashboard <-> student screen, plus the simulator dock."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QScrollArea, QStackedWidget, QTabWidget, QWidget

from PySide6.QtWidgets import QTabWidget as _Tabs

from .journey_view import JourneyView
from .simulator_panel import JourneySimPanel, SimulatorPanel
from .student_view import StudentView
from .teacher.devices_tab import DevicesTab
from .teacher.effects_tab import EffectsTab
from .teacher.home_tab import HomeTab
from .teacher.journey_tab import JourneyTab
from .teacher.curriculum_tab import CurriculumTab
from .teacher.reports_tab import ReportsTab
from .teacher.students_tab import StudentsTab


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        from .lang import L, direction

        self.setWindowTitle(L("إديوبوند — رحلة إلى مكة", "EduBond — Journey to Makkah"))
        self.setLayoutDirection(direction())
        self._fit_to_screen()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.tabs = QTabWidget()
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.setDocumentMode(True)
        self.home = HomeTab(ctx, self.start_lesson)
        self.journey = JourneyTab(ctx, self.start_journey)
        self.curriculum = CurriculumTab(ctx, on_change=lambda: self.journey.reload() if hasattr(self, "journey") else None)
        self.students = StudentsTab(ctx, on_change=lambda: (self.home.reload(), self.journey.reload()) if hasattr(self, "journey") else None)
        self.devices = DevicesTab(ctx)
        self.effects = EffectsTab(ctx)
        self.reports = ReportsTab(ctx)
        def scrolled(page: QWidget) -> QScrollArea:
            """Teacher pages scroll instead of forcing the window taller than the screen."""
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setWidget(page)
            area.page = page
            return area

        from .lang import L
        from .teacher.settings_tab import SettingsTab

        self.settings_tab = SettingsTab(ctx)
        pages = [
            (self.journey, L("🕋  رحلة إلى مكة", "🕋  Journey to Makkah")),
            (self.curriculum, L("📚  المنهج والأسئلة", "📚  Curriculum && questions")),
            (self.students, L("👥  الطلاب والصفوف والفرق", "👥  Students, classes && teams")),
            (self.reports, L("📊  التقارير", "📊  Reports")),
            (self.devices, L("🔌  الأجهزة", "🔌  Devices")),
            (self.settings_tab, L("⚙️  الإعدادات", "⚙️  Settings")),
        ]
        if ctx.repo.get_setting("dev_tools", False):
            pages += [(self.home, "🏠  Quiz demo"), (self.effects, "💡  Feedback effects")]
        for w, title in pages:
            self.tabs.addTab(scrolled(w), title)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.stack.addWidget(self._with_header(self.tabs))

        self.student = StudentView(ctx, self.end_lesson)
        self.stack.addWidget(self.student)
        self.journey_view = JourneyView(ctx, self.end_lesson)
        self.stack.addWidget(self.journey_view)
        ctx.language_changed.connect(lambda _l: self.student.refresh())

        self.sim_dock = QDockWidget(L("الأجهزة الافتراضية (محاكاة)", "Simulated hardware"), self)
        self.sim_dock.setObjectName("SimDock")
        sim_tabs = _Tabs()
        self.journey_sim = JourneySimPanel(ctx)
        sim_tabs.addTab(self.journey_sim, L("رحلة إلى مكة", "Journey"))
        sim_tabs.addTab(SimulatorPanel(ctx), "Quiz buttons")
        self.sim_dock.setWidget(sim_tabs)
        self.sim_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.sim_dock)
        self.sim_dock.setMinimumWidth(300)
        ctx.hardware_mode_changed.connect(self._sim_visibility)
        self._sim_visibility()

    def _sim_visibility(self) -> None:
        self.sim_dock.setVisible(self.ctx.simulation_enabled)

    def _with_header(self, tabs: QWidget) -> QWidget:
        """EduBond header (logo + product title) above the teacher tabs."""
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

        from .lang import L
        from .theme import asset

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QWidget()
        head.setObjectName("BrandHeader")
        head.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(head)
        h.setContentsMargins(16, 6, 16, 6)
        logo = QLabel()
        pm = QPixmap(asset("edubond_logo.png"))
        if not pm.isNull():
            logo.setPixmap(pm.scaledToHeight(46, Qt.SmoothTransformation))
        title = QLabel(L("رحلة إلى مكة — منصة التعلّم التفاعلي", "Journey to Makkah — interactive learning platform"))
        title.setObjectName("BrandTitle")
        sub = QLabel(L("إديوبوند · تعليم باللمس والأضواء", "EduBond · learning with touch and light"))
        sub.setObjectName("BrandSub")
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(title)
        texts.addWidget(sub)
        h.addWidget(logo)
        h.addSpacing(10)
        h.addLayout(texts)
        h.addStretch(1)
        v.addWidget(head)
        v.addWidget(tabs, 1)
        self.header = head
        return page

    def _fit_to_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        w = min(1400, int(avail.width() * 0.94))
        h = min(900, int(avail.height() * 0.92))
        self.setMinimumSize(min(900, avail.width() - 40), min(600, avail.height() - 40))
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2, avail.y() + (avail.height() - h) // 2)

    def _tab_changed(self, idx: int) -> None:
        w = getattr(self.tabs.widget(idx), "page", self.tabs.widget(idx))
        if w is self.home:
            self.home.reload()
        elif w is self.journey:
            self.journey.reload()
        elif w is self.reports:
            self.reports.reload_classes()

    def start_lesson(self, activity, student_name: str) -> None:
        self.student.bind(activity, student_name)
        self.stack.setCurrentWidget(self.student)
        if self.home.fullscreen.isChecked():
            self.showFullScreen()
        activity.start()
        self.student.setFocus()

    def _tab_index(self, page: QWidget) -> int:
        for i in range(self.tabs.count()):
            if getattr(self.tabs.widget(i), "page", None) is page:
                return i
        return 0

    def start_journey(self, activity) -> None:
        self.journey_view.bind(activity)
        self.stack.setCurrentWidget(self.journey_view)
        if self.journey.full.isChecked():
            self.showFullScreen()
        activity.start()
        self.journey_view.setFocus()

    def end_lesson(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.stack.setCurrentIndex(0)
        self.tabs.setCurrentIndex(self._tab_index(self.reports))
        self.reports.reload_classes()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.ctx.shutdown()
        super().closeEvent(e)
