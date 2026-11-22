"""صوت لكل حدث: استيراد ملف أو تسجيل بالميكروفون، مع تجربة وحذف."""
from __future__ import annotations

from ..lang import L, direction

import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from ..event_audio import EVENTS, EventSounds, Recorder, event_files, event_label, set_event_file, store_audio


class EventAudioWidget(QGroupBox):
    def __init__(self, ctx):
        super().__init__(L("أصوات الأحداث — استيراد ملف أو تسجيل بصوتك", "Event sounds — import a file or record your voice"))
        self.ctx = ctx
        self.setLayoutDirection(direction())
        self.sounds = EventSounds(ctx)
        self.recorder = Recorder()
        self.recording_event: str | None = None
        self._rec_started = 0.0
        g = QGridLayout(self)
        for c, h in enumerate([L("الحدث", "Event"), L("الصوت الحالي", "Current sound"), "", "", "", ""]):
            if h:
                lbl = QLabel(f"<b>{h}</b>")
                g.addWidget(lbl, 0, c)
        self.labels: dict[str, QLabel] = {}
        self.rec_buttons: dict[str, QPushButton] = {}
        for r, (key, label, _tone, _sp) in enumerate(EVENTS, start=1):
            g.addWidget(QLabel(event_label(key)), r, 0)
            cur = QLabel()
            cur.setObjectName("Muted")
            self.labels[key] = cur
            g.addWidget(cur, r, 1)
            imp = QPushButton(L("📂 استيراد", "📂 Import"))
            imp.clicked.connect(lambda _c=False, k=key: self.import_file(k))
            rec = QPushButton(L("⏺ تسجيل", "⏺ Record"))
            rec.clicked.connect(lambda _c=False, k=key: self.toggle_record(k))
            self.rec_buttons[key] = rec
            play = QPushButton(L("▶ تجربة", "▶ Play"))
            play.clicked.connect(lambda _c=False, k=key: self.sounds.play(k))
            clear = QPushButton(L("حذف", "Remove"))
            clear.clicked.connect(lambda _c=False, k=key: self.clear(k))
            for c, b in enumerate((imp, rec, play, clear), start=2):
                g.addWidget(b, r, c)
        stop = QPushButton(L("⏹ إيقاف أي صوت", "⏹ Stop all sound"))
        stop.clicked.connect(self._stop_all)
        g.addWidget(stop, len(EVENTS) + 1, 0)
        note = QLabel(L("بدون ملف يُنطق الحدث بالعربية (إن وُجد صوت عربي في النظام) ثم نغمة مدمجة. الملفات تُحفظ داخل البرنامج وتعمل دون إنترنت. ", "Without a file the event is spoken in Arabic (if the system has an Arabic voice), otherwise a built-in tone plays. Files are stored inside EduKit and work offline. ")
                      + L("الصيغ: MP3 · WAV · M4A. التسجيل يحتاج إذن الميكروفون في أول مرة.", "Formats: MP3 · WAV · M4A. Recording asks for microphone permission the first time."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        g.addWidget(note, len(EVENTS) + 2, 0, 1, 6)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_rec_label)
        self.refresh()

    def _stop_all(self) -> None:
        self.ctx.media.stop()
        self.ctx.speaker.stop()

    def refresh(self) -> None:
        files = event_files(self.ctx.repo)
        for key, lbl in self.labels.items():
            p = files.get(key)
            lbl.setText(f"🎵 {Path(p).name}" if p else L("مدمج (نطق / نغمة)", "Built-in (speech / tone)"))

    def import_file(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, L("اختيار ملف صوتي", "Choose an audio file"), "", "Audio (*.mp3 *.wav *.m4a *.aac *.ogg)")
        if path:
            set_event_file(self.ctx.repo, key, store_audio(self.ctx.data_dir, key, Path(path)))
            self.refresh()

    def clear(self, key: str) -> None:
        set_event_file(self.ctx.repo, key, "")
        self.refresh()

    def toggle_record(self, key: str) -> None:
        if self.recording_event == key:
            self._finish_recording()
            return
        if self.recording_event is not None:
            return  # one recording at a time

        def go(granted: bool) -> None:
            if not granted:
                QMessageBox.warning(self, L("الميكروفون", "Microphone"), L("لم يُسمح باستعمال الميكروفون. اسمح لـ EduKit من إعدادات النظام ← الخصوصية والأمان ← الميكروفون.", "Microphone access was not allowed. Allow EduKit in System Settings → Privacy & Security → Microphone."))
                return
            self._stop_all()
            dest = self.ctx.data_dir / "audio" / f"{key}_rec_{int(time.time())}.m4a"
            if not self.recorder.start(dest):
                QMessageBox.warning(self, L("التسجيل", "Recording"), L(f"تعذّر بدء التسجيل: {self.recorder.error}", f"Could not start recording: {self.recorder.error}"))
                return
            self.recording_event = key
            self._rec_started = time.time()
            self.rec_buttons[key].setText(L("⏹ إيقاف (0 ث)", "⏹ Stop (0 s)"))
            self._tick.start(250)

        self.recorder.permission(go)

    def _update_rec_label(self) -> None:
        if self.recording_event:
            self.rec_buttons[self.recording_event].setText(L(f"⏹ إيقاف ({int(time.time() - self._rec_started)} ث)", f"⏹ Stop ({int(time.time() - self._rec_started)} s)"))

    def _finish_recording(self) -> None:
        key = self.recording_event
        self.recording_event = None
        self._tick.stop()
        self.rec_buttons[key].setText(L("⏺ تسجيل", "⏺ Record"))
        path = self.recorder.stop()

        def done() -> None:
            if path and path.exists() and path.stat().st_size > 0:
                set_event_file(self.ctx.repo, key, str(path))
                self.refresh()
            else:
                QMessageBox.warning(self, L("التسجيل", "Recording"), L(f"لم يُحفظ التسجيل. {self.recorder.error}", f"The recording was not saved. {self.recorder.error}"))

        QTimer.singleShot(600, done)  # the encoder finishes writing the file asynchronously
