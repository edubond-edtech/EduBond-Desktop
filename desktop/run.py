#!/usr/bin/env python3
"""Start EduKit:  python run.py  [--simulate] [--no-serial] [--data-dir PATH]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from edukit.ui.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
