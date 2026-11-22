"""Interface language: Arabic by default, English on request.

Every menu, button and label is written as ``L("عربي", "English")``.
Question content is never translated: it is shown exactly as the teacher wrote it.
"""
from __future__ import annotations

_LANG = "ar"


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = "en" if lang == "en" else "ar"


def lang() -> str:
    return _LANG


def is_ar() -> bool:
    return _LANG == "ar"


def L(ar: str, en: str) -> str:  # noqa: N802 - short on purpose, used everywhere
    return en if _LANG == "en" else ar


def direction():  # noqa: ANN201
    from PySide6.QtCore import Qt

    return Qt.RightToLeft if _LANG == "ar" else Qt.LeftToRight


def restart_app() -> None:
    """Relaunch EduKit (used after changing the interface language)."""
    import sys

    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication

    if getattr(sys, "frozen", False):
        QProcess.startDetached(sys.executable, sys.argv[1:])
    else:
        QProcess.startDetached(sys.executable, sys.argv)
    QApplication.quit()
