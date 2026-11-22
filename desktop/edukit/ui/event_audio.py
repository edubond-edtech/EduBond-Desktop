"""Sound for game events: imported file or microphone recording > spoken Arabic phrase > built-in tone."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

# (key, Arabic label, built-in tone, speech key)
EVENTS: list[tuple[str, str, str | None, str | None]] = [
    ("start", "بداية اللعبة", "tick", "start"),
    ("question", "عرض سؤال جديد", None, None),
    ("correct", "إجابة صحيحة", "correct", "correct"),
    ("wrong", "إجابة خاطئة", "incorrect", "wrong"),
    ("timeout", "انتهاء الوقت", "timeout", "timeout"),
    ("win", "الفوز — الوصول إلى مكة", "festival", "arrival"),
    ("lose", "الخسارة — انتهت الأسئلة", "incorrect", "lose"),
]
EVENT_EN = {"start": "Game start", "question": "New question", "correct": "Correct answer", "wrong": "Wrong answer",
            "timeout": "Time is up", "win": "Win — reached Makkah", "lose": "Lose — questions used up"}


def event_label(key: str) -> str:
    from .lang import L

    return L(next(lbl for k, lbl, _t, _s in EVENTS if k == key), EVENT_EN[key])


def event_files(repo: Any) -> dict[str, str]:
    """Teacher's audio per event; migrates the older «journey_audio» setting once."""
    files = repo.get_setting("event_audio", None)
    if files is None:
        old = repo.get_setting("journey_audio", {}) or {}
        files = {"correct": old.get("correct", ""), "wrong": old.get("incorrect", ""), "win": old.get("festival", "")}
        repo.set_setting("event_audio", files)
    return {k: v for k, v in files.items() if v}


def set_event_file(repo: Any, event: str, path: str) -> None:
    files = dict(repo.get_setting("event_audio", {}) or {})
    files[event] = path
    repo.set_setting("event_audio", files)


def store_audio(data_dir: Path, event: str, src: Path) -> str:
    """Copy an imported file into the app's audio folder (works offline, survives moving the original)."""
    dest_dir = data_dir / "audio"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{event}_{int(time.time())}{src.suffix.lower()}"
    shutil.copy2(src, dest)
    return str(dest)


class EventSounds:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    def play(self, event: str, after: Callable[[], None] | None = None) -> str:
        """Play the sound for ``event``. Returns what was used: file / speech / tone / none."""
        from .speech import pick_phrase, speech_settings

        path = event_files(self.ctx.repo).get(event)
        if path and self.ctx.media.play(path):
            return "file"
        tone, speech_key = next(((t, sk) for k, _l, t, sk in EVENTS if k == event), (None, None))
        sp = speech_settings(self.ctx.repo.get_setting("journey_speech", {}))
        if speech_key and sp["enabled"] and self.ctx.speaker.say(pick_phrase(sp, speech_key), sp["rate"]):
            if event == "correct":
                self.ctx.sounds.play("correct")
            return "speech"
        if event == "win":  # a long festive tune for arrival
            self.ctx.media.play(self.ctx.sounds.path("festival"))
            return "tone"
        if tone:
            self.ctx.sounds.play(tone)
            return "tone"
        return "none"


class Recorder:
    """Microphone recording to .m4a with Qt Multimedia (asks for microphone permission on macOS)."""

    def __init__(self) -> None:
        self._rec = None
        self.path: Path | None = None
        self.error = ""

    def permission(self, on_result: Callable[[bool], None]) -> None:
        try:
            from PySide6.QtCore import QMicrophonePermission, Qt
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            perm = QMicrophonePermission()
            status = app.checkPermission(perm)
            if status == Qt.PermissionStatus.Granted:
                on_result(True)
            elif status == Qt.PermissionStatus.Denied:
                on_result(False)
            else:
                app.requestPermission(perm, lambda p: on_result(app.checkPermission(p) == Qt.PermissionStatus.Granted))
        except Exception as exc:  # older Qt: just try
            log.info("permission API unavailable: %s", exc)
            on_result(True)

    def start(self, path: Path) -> bool:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioInput, QMediaCaptureSession, QMediaFormat, QMediaRecorder

            path.parent.mkdir(parents=True, exist_ok=True)
            self._session = QMediaCaptureSession()
            self._input = QAudioInput()
            self._session.setAudioInput(self._input)
            self._rec = QMediaRecorder()
            self._session.setRecorder(self._rec)
            fmt = QMediaFormat()
            fmt.setFileFormat(QMediaFormat.FileFormat.Mpeg4Audio)
            fmt.setAudioCodec(QMediaFormat.AudioCodec.AAC)
            self._rec.setMediaFormat(fmt)
            self._rec.setQuality(QMediaRecorder.Quality.HighQuality)
            self._rec.setOutputLocation(QUrl.fromLocalFile(str(path)))
            self._rec.errorOccurred.connect(lambda _e, msg: setattr(self, "error", msg))
            self.path = path
            self.error = ""
            self._rec.record()
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def stop(self) -> Path | None:
        if self._rec is None:
            return None
        self._rec.stop()
        loc = self._rec.actualLocation().toLocalFile() or (str(self.path) if self.path else "")
        self._rec = None
        return Path(loc) if loc else None

    @property
    def recording(self) -> bool:
        return self._rec is not None
