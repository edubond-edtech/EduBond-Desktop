"""Plays teacher-chosen audio files (nasheed, duaa, mp3/wav/m4a) offline through the PC speakers."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class MediaPlayer:
    def __init__(self) -> None:
        self._player = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._player = QMediaPlayer()
            self._out = QAudioOutput()
            self._out.setVolume(1.0)
            self._player.setAudioOutput(self._out)
        except Exception as exc:  # pragma: no cover - missing multimedia backend
            log.warning("media playback unavailable: %s", exc)

    def play(self, path: str | Path | None, volume: float = 1.0) -> bool:
        if self._player is None or not path or not Path(path).exists():
            return False
        from PySide6.QtCore import QUrl

        self._player.stop()
        self._out.setVolume(max(0.0, min(1.0, volume)))
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        return True

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
