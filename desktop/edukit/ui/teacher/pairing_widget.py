"""البحث عن أجهزة EduKit القريبة عبر البلوتوث والربط بزر."""
from __future__ import annotations

from ..lang import L, direction

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


def _signal(rssi: int | None) -> str:
    if rssi is None:
        return "—"
    bars = 4 if rssi > -60 else 3 if rssi > -70 else 2 if rssi > -80 else 1
    return "▮" * bars + "▯" * (4 - bars) + f"  ({rssi})"


class PairingWidget(QGroupBox):
    def __init__(self, ctx):
        super().__init__(L("الأجهزة عبر البلوتوث — بحث وربط", "Bluetooth devices — search and pair"))
        self.ctx = ctx
        self.setLayoutDirection(direction())
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_btn = QPushButton(L("🔍 بحث عن الأجهزة", "🔍 Search for devices"))
        self.search_btn.setObjectName("Primary")
        self.search_btn.clicked.connect(self.search)
        self.pair_btn = QPushButton(L("🔗 ربط", "🔗 Pair"))
        self.pair_btn.clicked.connect(self.pair)
        self.unpair_btn = QPushButton(L("إلغاء الربط", "Unpair"))
        self.unpair_btn.setObjectName("Danger")
        self.unpair_btn.clicked.connect(self.unpair)
        for b in (self.search_btn, self.pair_btn, self.unpair_btn):
            top.addWidget(b)
        top.addStretch(1)
        lay.addLayout(top)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([L("الجهاز", "Device"), L("قوة الإشارة", "Signal"), L("الحالة", "Status"), L("العنوان", "Address")])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setMinimumHeight(130)
        self.table.doubleClicked.connect(lambda _i: self.pair())
        lay.addWidget(self.table)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    def _rows(self) -> list[dict]:
        """Boards found by the last search, plus paired boards that are not in range right now."""
        found = {d["address"]: d for d in self.ctx.ble_discovery.found()}
        for p in self.ctx.paired_devices():
            found.setdefault(p["address"], {"address": p["address"], "name": p["name"], "rssi": None, "age_s": None, "paired": True})
        return sorted(found.values(), key=lambda d: (not d["paired"], d["name"]))

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 and self.table.item(r, 0) else None

    def search(self) -> None:
        if not self.ctx.ble_enabled:
            self.ctx.set_ble(True)
        self.ctx.ble_discovery.scan_now(8)
        self.status.setText(L("جارٍ البحث عن أجهزة EduKit القريبة… تأكد أن الجهاز موصول بالكهرباء.", "Searching for nearby EduKit devices… make sure the device is powered."))

    def pair(self) -> None:
        d = self._selected()
        if not d:
            self.status.setText(L("اختر جهازًا من القائمة ثم اضغط «ربط».", "Choose a device from the list, then press «Pair»."))
            return
        self.ctx.pair_device(d["address"], d["name"].replace("EduKit-", ""))
        self.status.setText(L(f"تم ربط {d['name']} — جارٍ الاتصال…", f"Paired {d['name']} — connecting…"))
        self.refresh()

    def unpair(self) -> None:
        d = self._selected()
        if d and d["paired"]:
            self.ctx.unpair_device(d["address"])
            self.status.setText(L(f"أُلغي ربط {d['name']}.", f"Unpaired {d['name']}."))
            self.refresh()

    def refresh(self) -> None:
        if not self.isVisible():
            return
        online = {l.address: l for l in self.ctx.devices.online_devices() if l.transport.kind == "ble"}
        rows = self._rows()
        keep = self._selected()
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            link = online.get(f"ble:{d['address']}")
            if link:
                state, color = L(f"✅ متصل ({link.device_id})", f"✅ Connected ({link.device_id})"), "#1f9d55"
            elif d["paired"]:
                state, color = (L("🔗 مربوط — خارج النطاق أو مطفأ", "🔗 Paired — out of range or off") if d["age_s"] is None else L("🔗 مربوط — جارٍ الاتصال…", "🔗 Paired — connecting…")), "#a87400"
            else:
                state, color = L("غير مربوط", "Not paired"), "#6b7385"
            vals = [d["name"] or "EduKit", _signal(d["rssi"]), state, d["address"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, d)
                if c == 2:
                    it.setForeground(QColor(color))
                self.table.setItem(r, c, it)
            if keep and keep["address"] == d["address"]:
                self.table.selectRow(r)
        disc = self.ctx.ble_discovery
        if disc.last_error:
            self.status.setText(L(f"مشكلة في البلوتوث: {disc.last_error} — شغّل البلوتوث واسمح لـ EduKit من إعدادات الخصوصية.", f"Bluetooth problem: {disc.last_error} — turn Bluetooth on and allow EduKit in Privacy settings."))
        elif disc.scanning:
            self.search_btn.setText(L("⏳ جارٍ البحث…", "⏳ Searching…"))
        else:
            self.search_btn.setText(L("🔍 بحث عن الأجهزة", "🔍 Search for devices"))
            if not rows:
                self.status.setText(L("لا توجد أجهزة بعد. اضغط «بحث عن الأجهزة».", "No devices yet. Press «Search for devices»."))
