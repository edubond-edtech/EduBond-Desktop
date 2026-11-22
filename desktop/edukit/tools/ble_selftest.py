"""Headless Bluetooth self-test:  EduKit --ble-selftest report.txt

Runs inside the EduKit app (which holds the macOS Bluetooth permission), finds an
EduKit board over BLE, talks to it with the normal protocol and writes a report.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..comms.ble_transport import BleDiscovery
from ..core.events import DEVICE_INPUT, DEVICE_LOG, EventBus
from ..hardware.manager import DeviceManager


def run_selftest(report: Path, wait_s: float = 30.0, press_s: float = 25.0) -> int:
    lines: list[str] = []

    def out(msg: str) -> None:
        lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    bus = EventBus()
    events: list = []
    bus.subscribe(DEVICE_INPUT, events.append)
    bus.subscribe(DEVICE_LOG, lambda e: out(f"log {e[0]} [{e[1]}] {e[2]}") if e[1] in ("info", "warn") else None)
    disc = BleDiscovery(scan_seconds=4, interval=5)
    mgr = DeviceManager(bus, [disc], rescan_interval=2.0)
    out("BLE self-test started; scanning for EduKit boards…")
    mgr.start(interval=0.05)
    link = None
    end = time.time() + wait_s
    while time.time() < end and link is None:
        link = next((l for l in mgr.online_devices() if l.transport.kind == "ble"), None)
        time.sleep(0.2)
    out(f"boards seen in scans: {disc.devices()}  scan error: {disc.last_error or 'none'}")
    if link is None:
        out("RESULT: FAIL — no EduKit board connected over Bluetooth")
        mgr.stop()
        return 1
    i = link.info
    out(f"connected over Bluetooth: {link.address} ({link.transport.label}) mtu={getattr(link.transport, '_mtu', '?')}")
    out(f"hello: device_id={i.device_id} role={i.role} fw={i.fw} caps={json.dumps(i.caps)}")

    def cmd(name: str, **kw) -> str:
        h = link.send_command(name, **kw)
        t = time.time() + 3
        while h.status == "pending" and time.time() < t:
            time.sleep(0.02)
        out(f"{name:13s} -> {h.status}{' (' + h.error + ')' if h.error else ''}")
        return h.status

    results = [cmd("ping"), cmd("configure", brightness=80), cmd("path_set", step=0)]
    time.sleep(0.8)
    results.append(cmd("path_advance", **{"from": 0, "to": 1, "duration_ms": 1500}))
    time.sleep(1.8)
    results.append(cmd("path_back", **{"from": 1, "to": 0, "duration_ms": 1500}))
    time.sleep(1.8)
    out(f"round-trip time: {link.rtt_ms:.1f} ms" if link.rtt_ms else "round-trip time: n/a")
    results.append(cmd("arm", question_id="BLE", options=["A", "B", "C", "D"], timeout_s=0))
    out(f">>> press any button or touch pad within {press_s:.0f} s")
    t = time.time() + press_s
    press = None
    while time.time() < t and press is None:
        press = next((e for e in events if e.event == "answer_selected"), None)
        time.sleep(0.05)
    out(f"button/touch over Bluetooth: {press.selected_answer} (channel {press.data.get('channel')})" if press else "button/touch: none pressed")
    if press:
        cmd("path_advance", **{"from": 0, "to": 1, "duration_ms": 900})
        time.sleep(1.2)
    cmd("disarm")
    cmd("path_set", step=0)
    ok = all(r == "acked" for r in results)
    out(f"RESULT: {'PASS' if ok else 'FAIL'} — commands {'all acknowledged' if ok else 'not all acknowledged'} over Bluetooth"
        + ("; button press received" if press else ""))
    mgr.stop()
    return 0 if ok else 1
