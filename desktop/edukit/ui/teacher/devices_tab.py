"""🔌 الأجهزة / Devices: search & pair, device (competition) type with its settings, links, status and log."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.events import DEVICE_INPUT, DEVICE_LOG, DEVICE_STATUS
from ...hardware.plates import PLATE_RESISTORS, expected_mv
from ..lang import L, direction
from .pairing_widget import PairingWidget

# competition / device types: (key, Arabic, English, available now)
DEVICE_TYPES = [
    ("mcq", "اختيار من متعدد (أزرار / لمس)", "Multiple choice (buttons / touch)", True),
    ("arrange", "ترتيب الكلمات (لوحة البطاقات)", "Word arrangement (plate board)", True),
    ("reading", "قراءة بالميكروفون (التعرّف على النطق) — قريبًا", "Reading aloud (speech recognition) — coming soon", False),
    ("writing", "كتابة بالقلم (كاميرا لقراءة الخط) — قريبًا", "Handwriting (camera reads the writing) — coming soon", False),
]
TYPE_QTYPES = {"mcq": {"single_choice", "true_false"}, "arrange": {"arrange"}, "reading": set(), "writing": set()}


def type_label(key: str) -> str:
    return next((L(a, e) for k, a, e, _ok in DEVICE_TYPES if k == key), key)


def device_types(repo) -> dict[str, str]:  # noqa: ANN001
    return dict(repo.get_setting("device_types", {}) or {})


class DevicesTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        self.setLayoutDirection(direction())
        lay = QVBoxLayout(self)
        self.pairing = PairingWidget(ctx)
        lay.addWidget(self.pairing)
        lay.addWidget(self._build_device_box())
        lay.addWidget(self._build_links())
        lay.addStretch(1)
        ctx.bridge.on(DEVICE_STATUS, lambda _s: self.refresh())
        ctx.bridge.on(DEVICE_LOG, self._log)
        ctx.bridge.on(DEVICE_INPUT, self._on_input)
        ctx.hardware_mode_changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2500)
        self.refresh()
        self._load_device()

    # ===================================================== device type + settings
    def _build_device_box(self) -> QGroupBox:
        box = QGroupBox(L("الجهاز المحدد: نوعه وإعداداته", "Selected device: type and settings"))
        v = QVBoxLayout(box)
        f = QFormLayout()
        self.dev_combo = QComboBox()
        self.dev_combo.currentIndexChanged.connect(lambda _i: self._load_device())
        self.type_combo = QComboBox()
        for key, ar, en, ok in DEVICE_TYPES:
            self.type_combo.addItem(L(ar, en), key)
            if not ok:
                self.type_combo.model().item(self.type_combo.count() - 1).setForeground(QColor("#9aa3b2"))
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        f.addRow(L("الجهاز", "Device"), self.dev_combo)
        f.addRow(L("نوع الجهاز / المسابقة", "Device / competition type"), self.type_combo)
        v.addLayout(f)
        self.type_note = QLabel()
        self.type_note.setWordWrap(True)
        v.addWidget(self.type_note)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._mcq_page())
        self.stack.addWidget(self._arrange_page())
        self.stack.addWidget(self._reading_page())
        self.stack.addWidget(self._writing_page())
        v.addWidget(self.stack)
        row = QHBoxLayout()
        save = QPushButton(L("💾 حفظ وإرسال الإعدادات إلى الجهاز", "💾 Save and send settings to the device"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save_device)
        row.addWidget(save)
        row.addStretch(1)
        v.addLayout(row)
        return box

    def _spin(self, lo: int, hi: int, val: int, suffix: str = "", special: str = "") -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        if suffix:
            s.setSuffix(suffix)
        if special:
            s.setSpecialValueText(special)
        return s

    def _mcq_page(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        f = QFormLayout()
        self.options = self._spin(2, 4, 4)
        self.input_type = QComboBox()
        for v, ar, en in (("both", "الأزرار واللمس معًا", "Buttons and touch"), ("buttons", "الأزرار فقط", "Buttons only"), ("touch", "اللمس فقط", "Touch only")):
            self.input_type.addItem(L(ar, en), v)
        self.touch_sens = self._spin(3, 90, 20, " %")
        self.leds = self._spin(2, 300, 60)
        self.mbright = self._spin(10, 255, 150)
        self.wps = QLineEdit()
        self.wps.setPlaceholderText(L("اختياري: رقم الضوء لكل محطة، مثال 0,9,20,31,40,51,59", "Optional: LED index of each station, e.g. 0,9,20,31,40,51,59"))
        self.wps.setLayoutDirection(Qt.LeftToRight)
        f.addRow(L("عدد الأزرار المستعملة", "Answer buttons used"), self.options)
        f.addRow(L("طريقة الإجابة", "Answer input"), self.input_type)
        f.addRow(L("حساسية اللمس", "Touch sensitivity"), self.touch_sens)
        f.addRow(L("عدد الأضواء في الشريط", "LEDs on the strip"), self.leds)
        f.addRow(L("السطوع الأقصى", "Max brightness"), self.mbright)
        f.addRow(L("أضواء المحطات", "Station LEDs"), self.wps)
        g.addLayout(f, 0, 0)
        t = QVBoxLayout()
        tl = QHBoxLayout()
        cal = QPushButton(L("معايرة اللمس", "Calibrate touch"))
        cal.clicked.connect(lambda: self.ctx.devices.send(self._target(), "calibrate"))
        rd = QPushButton(L("قراءة قيم اللمس", "Read touch values"))
        rd.clicked.connect(lambda: self.ctx.devices.send(self._target(), "read_touch"))
        tl.addWidget(cal)
        tl.addWidget(rd)
        t.addLayout(tl)
        self.touch_lbl = QLabel("—")
        self.touch_lbl.setObjectName("Muted")
        self.touch_lbl.setWordWrap(True)
        t.addWidget(self.touch_lbl)
        test = QHBoxLayout()
        self.test_step = self._spin(0, 20, 0)
        test.addWidget(QLabel(L("اختبار الأضواء:", "Test lights:")))
        test.addWidget(self.test_step)
        for ar, en, fn in (("المحطة", "Station", lambda: self.ctx.devices.send(self._target(), "path_set", step=self.test_step.value())),
                           ("تقدّم", "Forward", self._test_advance),
                           ("رجوع", "Back", self._test_back),
                           ("🎉 احتفال", "🎉 Festival", lambda: self.ctx.devices.send(self._target(), "festival", duration_ms=8000))):
            b = QPushButton(L(ar, en))
            b.clicked.connect(fn)
            test.addWidget(b)
        t.addLayout(test)
        t.addStretch(1)
        g.addLayout(t, 0, 1)
        return w

    def _arrange_page(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        f = QFormLayout()
        self.sockets = self._spin(2, 6, 6)
        self.tol = self._spin(40, 400, 140, " mV")
        self.settle = self._spin(50, 3000, 250, " ms")
        self.complete = self._spin(0, 5000, 600, " ms")
        f.addRow(L("عدد المقابس", "Sockets"), self.sockets)
        f.addRow(L("سماحية القراءة", "Reading tolerance"), self.tol)
        f.addRow(L("زمن استقرار البطاقة", "Plate settle time"), self.settle)
        f.addRow(L("انتظار قبل الحكم", "Wait before judging"), self.complete)
        g.addLayout(f, 0, 0)
        right = QVBoxLayout()
        right.addWidget(QLabel(L("مفتاح المعلم — ضع أي بطاقة لمعرفة رقمها:", "Teacher key — insert any plate to see its number:")))
        self.key_table = QTableWidget(1, 6)
        self.key_table.setHorizontalHeaderLabels([f"{L('مقبس', 'Socket')} {i + 1}" for i in range(6)])
        self.key_table.verticalHeader().setVisible(False)
        self.key_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.key_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.key_table.setFixedHeight(64)
        right.addWidget(self.key_table)
        res = " · ".join(f"{p}: {PLATE_RESISTORS[p] / 1000:g}k ({expected_mv(p) / 1000:.2f}V)" for p in range(1, 7))
        lbl = QLabel(L("مقاومات البطاقات: ", "Plate resistors: ") + res)
        lbl.setObjectName("Muted")
        lbl.setWordWrap(True)
        right.addWidget(lbl)
        g.addLayout(right, 0, 1)
        self._key_board: list[int | None] = [None] * 6
        return w

    def _soon_page(self, ar_note: str, en_note: str, rows: list[tuple[str, str, QWidget]]) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel("🕓 " + L(ar_note, en_note))
        note.setWordWrap(True)
        note.setStyleSheet("color: #a87400; font-weight: 700;")
        v.addWidget(note)
        f = QFormLayout()
        for ar, en, widget in rows:
            f.addRow(L(ar, en), widget)
        v.addLayout(f)
        return w

    def _reading_page(self) -> QWidget:
        self.read_lang = QComboBox()
        self.read_lang.addItem(L("العربية الفصحى", "Standard Arabic"), "ar")
        self.read_secs = self._spin(2, 60, 8, L(" ث", " s"))
        self.read_thresh = self._spin(30, 100, 80, " %")
        self.read_harakat = QCheckBox(L("التدقيق في الحركات", "Check vowel marks (harakat)"))
        return self._soon_page(
            "قريبًا: يقرأ الطالب الكلمة أو الجملة في الميكروفون، ويتعرّف البرنامج على النطق دون إنترنت ويقارنه بالنص الصحيح.",
            "Coming soon: the student reads the word or sentence into the microphone; EduKit recognises it offline and compares it with the correct text.",
            [("لغة التعرّف", "Recognition language", self.read_lang), ("أقصى مدة للقراءة", "Max reading time", self.read_secs),
             ("نسبة التطابق للقبول", "Match needed to accept", self.read_thresh), ("", "", self.read_harakat)])

    def _writing_page(self) -> QWidget:
        self.cam = self._spin(0, 5, 0)
        self.write_secs = self._spin(5, 300, 60, L(" ث", " s"))
        self.write_thresh = self._spin(30, 100, 75, " %")
        self.write_harakat = QCheckBox(L("التدقيق في الحركات والنقاط", "Check vowel marks and dots"))
        return self._soon_page(
            "قريبًا: يكتب الطالب على ورقة أو لوح، وتقرأ كاميرا ملحقة الخط وتقارنه بالكتابة العربية الصحيحة.",
            "Coming soon: the student writes on paper or a board; an attached camera reads the handwriting and compares it with the correct Arabic.",
            [("رقم الكاميرا", "Camera number", self.cam), ("وقت الكتابة", "Writing time", self.write_secs),
             ("نسبة التطابق للقبول", "Match needed to accept", self.write_thresh), ("", "", self.write_harakat)])

    # ------------------------------------------------------------- behaviour
    def _known_devices(self) -> list[tuple[str, str]]:
        """(device_id, label) for every device seen: online, paired or remembered."""
        seen: dict[str, str] = {}
        for st in self.ctx.devices.statuses():
            if st.transport == "sim" and not self.ctx.simulation_enabled:
                continue
            seen[st.device_id] = f"{st.device_id} ({st.transport})"
        for p in self.ctx.paired_devices():
            seen.setdefault(p["name"], f"{p['name']} (ble)")
        return sorted(seen.items())

    def _target(self) -> str:
        return self.dev_combo.currentData() or "map"

    def _type_changed(self) -> None:
        key = self.type_combo.currentData()
        idx = [k for k, *_r in DEVICE_TYPES].index(key)
        self.stack.setCurrentIndex(idx)
        ok = DEVICE_TYPES[idx][3]
        self.type_note.setText(("✅ " + L("متاح الآن.", "Available now.")) if ok else ("🕓 " + L("هذا النوع غير متاح بعد؛ يمكنك حفظ إعداداته من الآن.", "Not available yet; you can already save its settings.")))

    def _load_device(self) -> None:
        dev = self.dev_combo.currentData()
        if not dev:
            self.type_combo.setCurrentIndex(0)
            self._type_changed()
            return
        t = device_types(self.ctx.repo).get(dev, "mcq")
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(t)))
        self._type_changed()
        cfg = {**(self.ctx.repo.get_setting("map_config", {}) or {}), **self.ctx.repo.device_config(dev)}
        self.options.setValue(cfg.get("options", 4))
        self.input_type.setCurrentIndex(max(0, self.input_type.findData(cfg.get("input_type", "both"))))
        self.touch_sens.setValue(cfg.get("touch_sensitivity", 20))
        self.leds.setValue(cfg.get("num_leds", 60))
        self.mbright.setValue(cfg.get("brightness", 150))
        self.wps.setText(",".join(map(str, cfg.get("waypoints", []))))
        self.sockets.setValue(cfg.get("sockets", 6))
        self.tol.setValue(cfg.get("tolerance_mv", 140))
        self.settle.setValue(cfg.get("settle_ms", 250))
        self.complete.setValue(cfg.get("complete_ms", 600))
        self.read_secs.setValue(cfg.get("read_seconds", 8))
        self.read_thresh.setValue(cfg.get("read_threshold", 80))
        self.read_harakat.setChecked(cfg.get("read_harakat", False))
        self.cam.setValue(cfg.get("camera", 0))
        self.write_secs.setValue(cfg.get("write_seconds", 60))
        self.write_thresh.setValue(cfg.get("write_threshold", 75))
        self.write_harakat.setChecked(cfg.get("write_harakat", False))

    def _save_device(self) -> None:
        dev = self.dev_combo.currentData()
        if not dev:
            QMessageBox.information(self, L("لا يوجد جهاز", "No device"), L("ابحث عن جهاز واربطه أولًا.", "Search for a device and pair it first."))
            return
        kind = self.type_combo.currentData()
        types = device_types(self.ctx.repo)
        types[dev] = kind
        self.ctx.repo.set_setting("device_types", types)
        try:
            wps = [int(x) for x in self.wps.text().replace("،", ",").split(",") if x.strip()]
        except ValueError:
            QMessageBox.warning(self, L("خطأ", "Error"), L("أضواء المحطات يجب أن تكون أرقامًا مفصولة بفواصل.", "Station LEDs must be numbers separated by commas."))
            return
        send: dict = {}
        if kind == "mcq":
            send = {"num_leds": self.leds.value(), "waypoints": wps, "brightness": self.mbright.value(),
                    "input_type": self.input_type.currentData(), "touch_sensitivity": self.touch_sens.value()}
            local = {**send, "options": self.options.value()}
            self.ctx.repo.set_setting("map_config", send)
        elif kind == "arrange":
            send = {"tolerance_mv": self.tol.value(), "settle_ms": self.settle.value(), "complete_ms": self.complete.value()}
            local = {**send, "sockets": self.sockets.value()}
        elif kind == "reading":
            local = {"read_seconds": self.read_secs.value(), "read_threshold": self.read_thresh.value(), "read_harakat": self.read_harakat.isChecked()}
        else:
            local = {"camera": self.cam.value(), "write_seconds": self.write_secs.value(), "write_threshold": self.write_thresh.value(),
                     "write_harakat": self.write_harakat.isChecked()}
        role = "map" if kind == "mcq" else "puzzle" if kind == "arrange" else kind
        self.ctx.repo.set_device_config(dev, role, {**self.ctx.repo.device_config(dev), **local})
        h = self.ctx.devices.send(dev, "configure", **send) if send else None
        sent = L("وأُرسلت إلى الجهاز.", "and sent to the device.") if h else L("وستُرسل عند اتصال الجهاز.", "and will be sent when the device connects.")
        QMessageBox.information(self, L("تم", "Done"), L(f"حُفظ نوع الجهاز «{type_label(kind)}» وإعداداته ", f"Saved type «{type_label(kind)}» and its settings ") + sent)

    def _test_advance(self) -> None:
        s = self.test_step.value()
        self.ctx.devices.send(self._target(), "path_advance", **{"from": s, "to": s + 1, "duration_ms": 1800})
        self.test_step.setValue(s + 1)

    def _test_back(self) -> None:
        s = self.test_step.value()
        if s > 0:
            self.ctx.devices.send(self._target(), "path_back", **{"from": s, "to": s - 1, "duration_ms": 1800})
            self.test_step.setValue(s - 1)

    def _on_input(self, evt) -> None:  # noqa: ANN001
        if evt.event == "touch_readings":
            d = evt.data
            names = L("أبجد", "ABCD")
            parts = [f"{names[i]}: {v} ({L('الأساس', 'base')} {b})" + (" ✋" if (d.get("touched") or [False] * 4)[i] else "")
                     for i, (v, b) in enumerate(zip(d.get("values", []), d.get("baselines", [])))]
            self.touch_lbl.setText("  ·  ".join(parts))
        elif evt.role == "puzzle" and evt.event in ("plate_inserted", "plate_removed", "plate_unknown"):
            s = int(evt.data.get("socket", 0)) - 1
            if 0 <= s < 6:
                self._key_board[s] = int(evt.data.get("plate", 0)) if evt.event == "plate_inserted" else (-1 if evt.event == "plate_unknown" else None)
                for i, p in enumerate(self._key_board):
                    it = QTableWidgetItem("—" if p is None else ("؟" if p < 0 else f"{L('بطاقة', 'Plate')} {p}"))
                    it.setTextAlignment(Qt.AlignCenter)
                    self.key_table.setItem(0, i, it)

    # ============================================================ links + status
    def _build_links(self) -> QGroupBox:
        box = QGroupBox(L("طرق الاتصال والحالة", "Connections and status"))
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.ble_cb = QCheckBox(L("البلوتوث", "Bluetooth"))
        self.ble_cb.setChecked(self.ctx.ble_enabled)
        self.ble_cb.toggled.connect(self.ctx.set_ble)
        self.ser_cb = QCheckBox(L("كابل USB", "USB cable"))
        self.ser_cb.setChecked(self.ctx.serial_enabled)
        self.ser_cb.toggled.connect(self.ctx.set_serial)
        self.sim_cb = QCheckBox(L("المحاكاة (للتجربة بدون أجهزة)", "Simulation (test without hardware)"))
        self.sim_cb.setChecked(self.ctx.simulation_enabled)
        self.sim_cb.toggled.connect(self.ctx.set_simulation)
        for w in (self.ble_cb, self.ser_cb, self.sim_cb):
            row.addWidget(w)
        row.addStretch(1)
        v.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([L("الجهاز", "Device"), L("النوع", "Type"), L("الحالة", "State"), L("الاتصال", "Link"),
                                              L("الإصدار", "Firmware"), L("زمن الاستجابة", "Latency")])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setMinimumHeight(120)
        v.addWidget(self.table)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFixedHeight(130)
        self.log.setLayoutDirection(Qt.LeftToRight)
        v.addWidget(QLabel(L("سجل الاتصال", "Communication log")))
        v.addWidget(self.log)
        return box

    def _log(self, item) -> None:  # noqa: ANN001
        dev, level, text = item
        if level in ("debug", "noise"):
            return
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  [{level}] {dev}: {text}")

    def refresh(self) -> None:
        types = device_types(self.ctx.repo)
        statuses = [s for s in self.ctx.devices.statuses() if s.transport != "sim" or self.ctx.simulation_enabled]
        self.table.setRowCount(len(statuses))
        state_ar = {"online": L("متصل", "online"), "lost": L("منقطع", "lost"), "connecting": L("جارٍ الاتصال", "connecting"), "closed": L("مغلق", "closed")}
        for r, s in enumerate(statuses):
            vals = [s.device_id, type_label(types.get(s.device_id, "mcq")) if s.role in ("map", "input") else s.role,
                    state_ar.get(s.state.value, s.state.value), s.transport, s.fw, f"{s.rtt_ms:.0f} ms" if s.rtt_ms is not None else "—"]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 2:
                    it.setForeground(QColor({"online": "#2fb86e", "lost": "#e5484d"}.get(s.state.value, "#a9b0bf")))
                self.table.setItem(r, c, it)
        known = self._known_devices()
        if [self.dev_combo.itemData(i) for i in range(self.dev_combo.count())] != [k for k, _ in known]:
            cur = self.dev_combo.currentData()
            self.dev_combo.blockSignals(True)
            self.dev_combo.clear()
            for k, label in known:
                self.dev_combo.addItem(label, k)
            self.dev_combo.setCurrentIndex(max(0, self.dev_combo.findData(cur)))
            self.dev_combo.blockSignals(False)
            self._load_device()
        for cb, val in ((self.ble_cb, self.ctx.ble_enabled), (self.ser_cb, self.ctx.serial_enabled), (self.sim_cb, self.ctx.simulation_enabled)):
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
