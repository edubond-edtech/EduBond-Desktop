"""Offline Arabic speech through the operating system's voices (macOS «Majed», Windows «Naayf/Hoda»).

Works without internet. If no Arabic voice is installed the caller falls back to
recorded audio files or tones.
"""
from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SPEECH: dict[str, Any] = {
    "enabled": True,
    "read_question": False,
    "rate": -0.1,  # -1..1 (slightly slower for children)
    "correct": ["أحسنت! إجابة صحيحة", "ممتاز! تقدّمنا خطوة نحو مكة", "بارك الله فيك! إجابة صحيحة"],
    "wrong": ["إجابة خاطئة، رجعنا خطوة إلى الوراء", "للأسف إجابة خاطئة، حاولوا في السؤال القادم"],
    "timeout": ["انتهى الوقت"],
    "arrival": "مبارك! وصلنا إلى مكة المكرمة",
    "start": "بسم الله، لنبدأ الرحلة إلى مكة المكرمة",
    "lose": "انتهت الأسئلة قبل الوصول إلى مكة، حاولوا مرة أخرى",
}


def speech_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    s = dict(DEFAULT_SPEECH)
    s.update({k: v for k, v in (raw or {}).items() if k in DEFAULT_SPEECH})
    return s


def pick_phrase(settings: dict[str, Any], key: str) -> str:
    v = settings.get(key)
    if isinstance(v, list):
        v = [x for x in v if str(x).strip()]
        return random.choice(v) if v else ""
    return str(v or "")


class Speaker:
    def __init__(self) -> None:
        self._tts = None
        self.voice_name = ""
        try:
            from PySide6.QtCore import QLocale
            from PySide6.QtTextToSpeech import QTextToSpeech

            tts = QTextToSpeech()
            for loc in tts.availableLocales():
                if loc.language() == QLocale.Arabic:
                    tts.setLocale(loc)
                    voices = tts.availableVoices()
                    if voices:
                        tts.setVoice(voices[0])
                        self.voice_name = voices[0].name()
                    self._tts = tts
                    break
            if self._tts is None:
                log.info("no Arabic text-to-speech voice installed")
        except Exception as exc:  # QtTextToSpeech missing
            log.warning("text-to-speech unavailable: %s", exc)

    @property
    def available(self) -> bool:
        return self._tts is not None

    def say(self, text: str, rate: float = 0.0) -> bool:
        if not self._tts or not text:
            return False
        self._tts.stop()
        self._tts.setRate(max(-1.0, min(1.0, rate)))
        self._tts.say(text)
        return True

    def stop(self) -> None:
        if self._tts:
            self._tts.stop()
