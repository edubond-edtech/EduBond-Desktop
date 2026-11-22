"""Drop-down lists (QComboBox) show their full Arabic text."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QWidget

from edukit.ui.combo_fix import install, popup_width

ITEMS = ["هذا الشهر", "آخر ٧ أيام", "اليوم", "هذه السنة", "كل الفترات", "مخصّص (من تاريخ إلى تاريخ)"]


def test_combo_and_popup_fit_longest_item(qtbot):
    install(QApplication.instance())
    w = QWidget()
    w.setLayoutDirection(Qt.RightToLeft)
    lay = QHBoxLayout(w)
    combo = QComboBox()
    combo.addItems(ITEMS)
    lay.addWidget(combo)
    lay.addStretch(1)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    fm = combo.fontMetrics()
    longest = max(fm.horizontalAdvance(t) for t in ITEMS)
    assert combo.sizeAdjustPolicy() == QComboBox.AdjustToContents
    assert combo.width() >= longest  # the closed box shows the whole current item
    combo.showPopup()
    popup = combo.view().window()
    qtbot.waitUntil(popup.isVisible, timeout=1000)
    assert popup.width() >= popup_width(combo) - 1 >= longest
    combo.hidePopup()
