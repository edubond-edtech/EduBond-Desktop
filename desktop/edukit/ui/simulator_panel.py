"""Virtual hardware: four illuminated buttons + an animated WS2812B strip."""
from __future__ import annotations

from .lang import L, direction

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .widgets import LedStripWidget, RoundButton


class SimulatorPanel(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        inp, out = ctx.sim_input, ctx.sim_output
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 10)

        g1 = QGroupBox(f"Input controller · {inp.device_id}")
        l1 = QVBoxLayout(g1)
        row = QHBoxLayout()
        self.buttons: list[RoundButton] = []
        for ch in range(inp.channels):
            label = inp.mapping.get(ch, "?")
            b = RoundButton(label, theme.OPTION_COLORS.get(label, ("#888", ""))[0], lambda ch=ch: self._press(ch))
            self.buttons.append(b)
            row.addWidget(b)
        l1.addLayout(row)
        self.in_state = QLabel()
        self.in_state.setObjectName("Muted")
        self.in_state.setWordWrap(True)
        l1.addWidget(self.in_state)
        self.in_plug = QCheckBox("USB cable connected")
        self.in_plug.setChecked(True)
        self.in_plug.toggled.connect(lambda on: inp.plug_in() if on else inp.unplug())
        l1.addWidget(self.in_plug)
        lay.addWidget(g1)

        g2 = QGroupBox(f"Output controller · {out.device_id}")
        l2 = QVBoxLayout(g2)
        self.strip = LedStripWidget(out.frame)
        l2.addWidget(self.strip)
        self.out_state = QLabel()
        self.out_state.setObjectName("Muted")
        self.out_state.setWordWrap(True)
        l2.addWidget(self.out_state)
        self.out_plug = QCheckBox("USB cable connected")
        self.out_plug.setChecked(True)
        self.out_plug.toggled.connect(lambda on: out.plug_in() if on else out.unplug())
        l2.addWidget(self.out_plug)
        lay.addWidget(g2)
        hint = QLabel("Tip: keys A–D or 1–4 and clicking the answer cards also work.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(150)

    def _press(self, ch: int) -> None:
        self.ctx.sim_input.press(ch)
        self.refresh()

    def refresh(self) -> None:
        inp, out = self.ctx.sim_input, self.ctx.sim_output
        for i, b in enumerate(self.buttons):
            b.label = inp.mapping.get(i, "?")
            b.set_lit(inp.plugged_in and i < len(inp.button_leds) and inp.button_leds[i])
        if not inp.plugged_in:
            self.in_state.setText("Unplugged")
        else:
            self.in_state.setText(f"Armed for {inp.question_id} · options {','.join(inp.allowed)}" if inp.armed else "Idle (not armed) · mode: " + inp.mode)
        e = out.effect
        last = out.history[-1] if out.history else {}
        buzz = f" · 🔊 {out.buzzes[-1].get('pattern')}" if out.buzzes else ""
        self.out_state.setText("Unplugged" if not out.plugged_in else f"Effect: {last.get('effect', e.base)} ({e.base}) · brightness {e.brightness}{buzz}")
        if self.in_plug.isChecked() != inp.plugged_in:
            self.in_plug.blockSignals(True)
            self.in_plug.setChecked(inp.plugged_in)
            self.in_plug.blockSignals(False)
        self.setEnabled(self.ctx.simulation_enabled)


class JourneySimPanel(QWidget):
    """Simulated word-plate board and LED route map (Game 1)."""

    def __init__(self, ctx):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QComboBox, QGridLayout, QPushButton

        from ..hardware.plates import PLATE_COLORS

        super().__init__()
        self.ctx = ctx
        self.setLayoutDirection(direction())
        board, mapd = ctx.sim_puzzle, ctx.sim_map
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 10)

        g1 = QGroupBox(L(f"لوحة البطاقات (اختيارية) · {board.device_id}", f"Plate board (optional) · {board.device_id}"))
        l1 = QVBoxLayout(g1)
        grid = QGridLayout()
        self.combos: list[QComboBox] = []
        for i in range(board.num_sockets):
            lbl = QLabel(L(f"مقبس {i + 1}", f"Socket {i + 1}"))
            cb = QComboBox()
            cb.addItem(L("— فارغ —", "— empty —"), None)
            for p in range(1, 7):
                cb.addItem(L(f"بطاقة {p}", f"Plate {p}"), p)
                cb.setItemData(p, QColor(PLATE_COLORS[p]), Qt.DecorationRole)
            cb.activated.connect(lambda _idx, i=i, cb=cb: self._plug(i, cb.currentData()))
            self.combos.append(cb)
            grid.addWidget(lbl, i // 2, (i % 2) * 2)
            grid.addWidget(cb, i // 2, (i % 2) * 2 + 1)
        l1.addLayout(grid)
        row = QHBoxLayout()
        for text, fn in ((L("✔ ترتيب صحيح", "✔ Correct order"), self._correct), (L("✘ ترتيب خاطئ", "✘ Wrong order"), self._wrong), (L("إخراج الكل", "Remove all"), board.clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        l1.addLayout(row)
        self.board_state = QLabel()
        self.board_state.setObjectName("Muted")
        self.board_state.setWordWrap(True)
        l1.addWidget(self.board_state)
        self.board_plug = QCheckBox(L("كابل USB موصول", "USB cable connected"))
        self.board_plug.setChecked(True)
        self.board_plug.toggled.connect(lambda on: board.plug_in() if on else board.unplug())
        l1.addWidget(self.board_plug)
        lay.addWidget(g1)

        g2 = QGroupBox(L(f"الخريطة + الأزرار · {mapd.device_id}", f"Map + buttons · {mapd.device_id}"))
        l2 = QVBoxLayout(g2)
        self.strip = LedStripWidget(lambda: list(reversed(mapd.frame())))  # LED 0 (Indonesia) drawn on the right
        self.strip.setMinimumHeight(30)
        l2.addWidget(self.strip)
        ends = QHBoxLayout()
        ends.addWidget(QLabel(L("إندونيسيا", "Indonesia")))
        ends.addStretch(1)
        ends.addWidget(QLabel(L("مكة 🕋", "Makkah 🕋")))
        l2.addLayout(ends)
        brow = QHBoxLayout()
        self.jbuttons: list[RoundButton] = []
        from .i18n import letter

        for ch in range(mapd.buttons):
            key = mapd.mapping.get(ch, "?")
            rb = RoundButton(letter(key, "ar"), theme.OPTION_COLORS.get(key, ("#888", ""))[0], lambda ch=ch: self._jpress(ch))
            self.jbuttons.append(rb)
            brow.addWidget(rb)
        l2.addLayout(brow)
        self.map_state = QLabel()
        self.map_state.setObjectName("Muted")
        self.map_state.setWordWrap(True)
        l2.addWidget(self.map_state)
        self.map_plug = QCheckBox(L("كابل USB موصول", "USB cable connected"))
        self.map_plug.setChecked(True)
        self.map_plug.toggled.connect(lambda on: mapd.plug_in() if on else mapd.unplug())
        l2.addWidget(self.map_plug)
        lay.insertWidget(0, g2)  # the combined map+buttons board is the main device
        lay.addStretch(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(200)

    def _jpress(self, ch: int) -> None:
        self.ctx.sim_map.press(ch)
        self.refresh()

    def _plug(self, socket: int, plate) -> None:  # noqa: ANN001
        self.ctx.sim_puzzle.insert(socket, plate)
        self.refresh()

    def _expected(self) -> list[str]:
        return list(self.ctx.sim_puzzle.expected)

    def _correct(self) -> None:
        b = self.ctx.sim_puzzle
        b.clear()
        b.place_all(self._expected())

    def _wrong(self) -> None:
        exp = self._expected()
        if len(exp) < 2:
            return
        wrong = exp[1:] + exp[:1]
        b = self.ctx.sim_puzzle
        b.clear()
        b.place_all(wrong)

    def refresh(self) -> None:
        b, m = self.ctx.sim_puzzle, self.ctx.sim_map
        for i, cb in enumerate(self.combos):
            want = int(b.sockets[i]) if b.sockets[i] else None
            if cb.currentData() != want:
                cb.setCurrentIndex(max(0, cb.findData(want)))
        if not b.plugged_in:
            self.board_state.setText(L("مفصولة", "Unplugged"))
        elif b.armed:
            st = L("أخرجوا البطاقات أولًا", "remove plates first") if b.need_clear else L("جاهزة", "ready")
            self.board_state.setText(L(f"السؤال {b.question_id} · الترتيب المتوقع {','.join(b.expected)} · {st}", f"Question {b.question_id} · expected order {','.join(b.expected)} · {st}"))
        else:
            self.board_state.setText(L("غير مفعّلة", "Not armed"))
        r = m.renderer.state
        for i, rb in enumerate(self.jbuttons):
            rb.set_lit(m.plugged_in and i < len(m.button_leds) and m.button_leds[i])
        arm = L(f" · الأزرار مفعّلة للسؤال {m.question_id}", f" · buttons armed for {m.question_id}") if m.armed else L(" · الأزرار غير مفعّلة", " · buttons not armed")
        self.map_state.setText(L("مفصولة", "Unplugged") if not m.plugged_in else L(f"الوضع: {r.mode} · المحطة {r.to_step}{arm}", f"Mode: {r.mode} · station {r.to_step}{arm}"))
        self.setEnabled(self.ctx.simulation_enabled)
