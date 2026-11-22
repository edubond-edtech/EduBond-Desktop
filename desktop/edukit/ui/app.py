"""Application entry point."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__, config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EduKit offline classroom platform")
    ap.add_argument("--data-dir", type=Path, help="folder for the database, sounds and images")
    ap.add_argument("--no-serial", action="store_true", help="do not scan USB serial ports this run")
    ap.add_argument("--serial", action="store_true", help="also scan USB serial ports this run")
    ap.add_argument("--no-ble", action="store_true", help="do not use Bluetooth this run")
    ap.add_argument("--ble-selftest", metavar="REPORT", help="connect to an EduKit board over Bluetooth, run checks, write REPORT, exit")
    ap.add_argument("--simulate", action="store_true", help="force simulation mode on this run")
    ap.add_argument("--debug", action="store_true")
    args, qt_args = ap.parse_known_args(argv)

    if sys.platform == "win32":  # own taskbar icon/group instead of python.exe's
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EduKit.Classroom")
        except Exception:
            pass
    if args.ble_selftest:
        from ..tools.ble_selftest import run_selftest

        return run_selftest(Path(args.ble_selftest))
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(__version__)
    if config.icon_file().exists():
        app.setWindowIcon(QIcon(str(config.icon_file())))
    f = QFont()
    if sys.platform == "win32":
        f.setFamilies(["Segoe UI", "Tahoma", "Arial"])
    elif sys.platform == "darwin":
        f.setFamilies([".AppleSystemUIFont", "Helvetica Neue", "Geeza Pro"])
    else:
        f.setFamilies(["Noto Sans", "Noto Sans Arabic", "DejaVu Sans"])
    app.setFont(f)

    from .context import AppContext
    from .main_window import MainWindow
    from .theme import STYLESHEET

    app.setStyleSheet(STYLESHEET)
    from .combo_fix import install as install_combo_fix

    install_combo_fix(app)  # drop-down lists show their full text
    data_dir = args.data_dir or config.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    overrides: dict = {}
    if args.simulate:
        overrides["simulation"] = True
    if args.no_ble:
        overrides["ble"] = False
    if args.serial:
        overrides["serial"] = True
    if args.no_serial:
        overrides["serial"] = False
    ctx = AppContext(data_dir=data_dir, hw_overrides=overrides)
    from .lang import direction, set_lang

    set_lang(ctx.repo.get_setting("ui_lang", "ar"))  # Arabic by default
    app.setLayoutDirection(direction())
    ctx.start()
    win = MainWindow(ctx)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
