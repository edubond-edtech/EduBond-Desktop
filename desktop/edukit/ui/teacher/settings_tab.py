"""⚙️ الإعدادات / Settings: interface language, developer tools, data folder."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ... import __version__
from ..lang import L, direction, lang, restart_app


class SettingsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        v = QVBoxLayout(self)
        head = QLabel(L("⚙️ الإعدادات", "⚙️ Settings"))
        head.setObjectName("H1")
        v.addWidget(head)

        g = QGroupBox(L("لغة الواجهة", "Interface language"))
        f = QFormLayout(g)
        self.lang = QComboBox()
        self.lang.addItem("العربية", "ar")
        self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(self.lang.findData(lang()))
        apply = QPushButton(L("تطبيق وإعادة التشغيل", "Apply and restart"))
        apply.setObjectName("Primary")
        apply.clicked.connect(self._apply_lang)
        row = QHBoxLayout()
        row.addWidget(self.lang)
        row.addWidget(apply)
        row.addStretch(1)
        f.addRow(L("اللغة", "Language"), row)
        note = QLabel(L("القوائم والأزرار تتغيّر إلى اللغة المختارة. محتوى الأسئلة يبقى كما كتبته.",
                        "Menus and buttons change to the chosen language. Question content stays as you wrote it."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        f.addRow(note)
        v.addWidget(g)

        d = QGroupBox(L("متقدّم", "Advanced"))
        df = QFormLayout(d)
        self.dev = QCheckBox(L("إظهار أدوات المطوّر (اختبار الأسئلة التجريبي، مؤثرات الأضواء)", "Show developer tools (demo quiz, light effects)"))
        self.dev.setChecked(bool(ctx.repo.get_setting("dev_tools", False)))
        self.dev.toggled.connect(self._toggle_dev)
        df.addRow(self.dev)
        folder = QPushButton(L("📂 فتح مجلد بيانات البرنامج", "📂 Open the data folder"))
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ctx.data_dir))))
        path = QLabel(str(ctx.data_dir))
        path.setObjectName("Muted")
        df.addRow(folder, path)
        df.addRow(QLabel(L(f"الإصدار {__version__}", f"Version {__version__}")))
        v.addWidget(d)
        v.addStretch(1)

    def _apply_lang(self) -> None:
        new = self.lang.currentData()
        if new == lang():
            return
        self.ctx.repo.set_setting("ui_lang", new)
        if QMessageBox.question(self, "EduKit", "إعادة تشغيل البرنامج الآن لتطبيق اللغة؟\nRestart EduKit now to apply the language?") == QMessageBox.Yes:
            restart_app()

    def _toggle_dev(self, on: bool) -> None:
        self.ctx.repo.set_setting("dev_tools", on)
        QMessageBox.information(self, "EduKit", L("سيظهر التغيير بعد إعادة تشغيل البرنامج.", "The change appears after restarting EduKit."))
