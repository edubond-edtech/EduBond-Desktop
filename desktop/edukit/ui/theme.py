"""Colours and the application stylesheet."""
from __future__ import annotations

# Option colours match the physical arcade buttons in the BOM (A red, B blue, C green, D yellow).
OPTION_COLORS = {
    "A": ("#e5484d", "#ffffff"),
    "B": ("#2f6fed", "#ffffff"),
    "C": ("#2fb86e", "#ffffff"),
    "D": ("#f5b100", "#1d2433"),
    "E": ("#8e4ec6", "#ffffff"),
    "F": ("#12a594", "#ffffff"),
}
OK = "#2fb86e"
BAD = "#e5484d"
WARN = "#f5a524"
INK = "#2a2140"
MUTED = "#6b6680"
BG = "#f7f4fb"  # soft lavender, from the EduBond purple
CARD = "#ffffff"
# EduBond brand identity (EduBond_Reference.md)
BRAND_PURPLE = "#7B3E98"
BRAND_YELLOW = "#FFCA3A"
BRAND_TEAL = "#26B6A8"
ACCENT = BRAND_PURPLE

STYLESHEET = f"""
QMainWindow, QWidget#Page {{ background: {BG}; }}
QWidget {{ color: {INK}; font-size: 14px; }}
QTabWidget::pane {{ border: 0; background: {BG}; }}
QTabBar::tab {{ padding: 10px 18px; margin-right: 2px; background: transparent; color: {MUTED}; border: 0; font-weight: 600; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 3px solid {ACCENT}; }}
QGroupBox {{ background: {CARD}; border: 1px solid #e3e7ef; border-radius: 12px; margin-top: 18px; padding: 14px 12px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 4px; color: {MUTED}; }}
QPushButton {{ background: {CARD}; border: 1px solid #d5dbe7; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #a9b0bf; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: 0; font-weight: 700; padding: 10px 22px; }}
QPushButton#Primary:hover {{ background: #67307f; }}
QPushButton#Brand {{ background: {BRAND_TEAL}; color: white; border: 0; font-weight: 700; padding: 8px 18px; }}
QWidget#BrandHeader {{ background: white; border-bottom: 3px solid {BRAND_YELLOW}; }}
QLabel#BrandTitle {{ color: {BRAND_PURPLE}; font-size: 20px; font-weight: 900; }}
QLabel#BrandSub {{ color: {BRAND_TEAL}; font-size: 13px; font-weight: 700; }}
QGroupBox::title {{ color: {BRAND_TEAL}; }}
QPushButton#Danger {{ color: {BAD}; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: white; border: 1px solid #d5dbe7; border-radius: 6px; padding: 5px; }}
QTableWidget, QListWidget, QTreeWidget {{ background: white; border: 1px solid #e3e7ef; border-radius: 8px; gridline-color: #eef1f6; }}
QHeaderView::section {{ background: #f7f8fc; border: 0; border-bottom: 1px solid #e3e7ef; padding: 6px; font-weight: 600; color: {MUTED}; }}
QDockWidget::title {{ padding: 8px; background: #e9ecf5; font-weight: 700; }}
QLabel#H1 {{ font-size: 24px; font-weight: 800; color: {BRAND_PURPLE}; }}
QLabel#Muted {{ color: {MUTED}; }}
"""


# ---- responsive sizing: game/student screens scale everything with the window
_SCALE = 1.0


def set_scale(k: float) -> None:
    global _SCALE
    _SCALE = max(0.5, min(1.4, k))


def scale() -> float:
    return _SCALE


def fs(n: float) -> int:
    """Scaled size in px for fonts, radii and boxes."""
    return max(8, round(n * _SCALE))


def scale_for(width: int, height: int, design_w: int = 1500, design_h: int = 920) -> float:
    return min(width / design_w, height / design_h)


class Scaled:
    """Mixin: remembers each widget's stylesheet recipe so it can be re-applied at a new scale."""

    def _style(self, widget, recipe) -> None:  # noqa: ANN001
        if not hasattr(self, "_styles"):
            self._styles = {}
        self._styles[widget] = recipe
        widget.setStyleSheet(recipe())

    def _rescale(self) -> None:
        """Override to resize fixed boxes (badges, minimum heights)."""

    def _restyle(self) -> None:
        self._rescale()
        for widget, recipe in list(getattr(self, "_styles", {}).items()):
            try:
                widget.setStyleSheet(recipe())
            except RuntimeError:  # widget already deleted
                self._styles.pop(widget, None)


def apply_scale(view) -> None:  # noqa: ANN001
    """Called from a full-screen view's resizeEvent: rescale it and all its Scaled children."""
    from PySide6.QtWidgets import QWidget

    k = scale_for(view.width(), view.height())
    if abs(k - getattr(view, "_last_scale", 0)) < 0.03:
        return
    view._last_scale = k
    set_scale(k)
    for child in view.findChildren(QWidget):
        if isinstance(child, Scaled):
            child._restyle()
    view._restyle()
    view.on_rescaled()


def asset(name: str) -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parent / "assets" / name)
