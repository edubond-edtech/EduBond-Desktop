"""Paths and app-wide configuration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "EduKit"


def data_dir() -> Path:
    override = os.environ.get("EDUKIT_HOME")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_root() -> Path:
    """Repository root in development, bundle dir when frozen with PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def sample_questions_file() -> Path:
    return resource_root() / "sample_data" / "questions.json"


def journey_questions_file() -> Path:
    return resource_root() / "sample_data" / "journey_arrange_ar.json"


def icon_file() -> Path:
    frozen = resource_root() / "icon.png"
    return frozen if frozen.exists() else resource_root() / "desktop" / "packaging" / "icon.png"


def journey_mcq_file() -> Path:
    return resource_root() / "sample_data" / "journey_mcq_ar.json"


def indonesia_g1_file() -> Path:
    return resource_root() / "sample_data" / "indonesia_g1_arabic.json"
