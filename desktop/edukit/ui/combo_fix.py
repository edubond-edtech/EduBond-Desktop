"""Drop-down lists show their full text.

Qt sizes a combo box and its pop-up list from the box's current width. With
Arabic text, right-to-left layout and the app stylesheet, that clipped both the
box («هذا» instead of «هذا الشهر») and the list items. One application-wide
event filter fixes every QComboBox in the app:
  * the box grows to its longest item (AdjustToContents), and
  * the pop-up list is at least as wide as its longest item.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QStyle

_EXTRA = 48  # check mark + padding + scroll bar


def popup_width(combo: QComboBox) -> int:
    view = combo.view()
    fm = view.fontMetrics()
    widest = max((fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
    icon = combo.iconSize().width() + 6 if any(not combo.itemIcon(i).isNull() for i in range(combo.count())) else 0
    sb = combo.style().pixelMetric(QStyle.PM_ScrollBarExtent)
    return max(combo.width(), widest + icon + sb + _EXTRA)


class ComboFix(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        et = event.type()
        if et == QEvent.Polish and isinstance(obj, QComboBox):
            if not obj.isEditable():
                obj.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        elif et == QEvent.Show and isinstance(obj.parent(), QComboBox) and obj.isWindow():
            combo: QComboBox = obj.parent()  # the pop-up container is a child window of its combo
            w = popup_width(combo)
            combo.view().setMinimumWidth(w - 4)
            if obj.width() < w:
                obj.setMinimumWidth(w)
                obj.resize(w, obj.height())
                if combo.layoutDirection() == Qt.RightToLeft:  # keep the list's right edge under the box
                    right = combo.mapToGlobal(combo.rect().topRight()).x()
                    obj.move(right - w + 1, obj.y())
        return False


_fix: ComboFix | None = None


def install(app: QApplication) -> None:
    global _fix
    if _fix is None:
        _fix = ComboFix(app)
        app.installEventFilter(_fix)
