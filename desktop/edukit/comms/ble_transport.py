"""Bluetooth Low Energy transport (Nordic UART Service) using ``bleak``.

The ESP32 firmware exposes the NUS service and carries exactly the same
newline-delimited JSON as USB serial, so DeviceLink / DeviceManager / every
activity work unchanged. Works offline on macOS (CoreBluetooth) and
Windows 10/11 (WinRT).

bleak is asyncio-based; all BLE work runs on one private event-loop thread and
the rest of EduKit stays synchronous.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable, Coroutine, Iterable

from .protocol import LineDecoder, Noise, encode
from .transport import DiscoverySource, Transport, TransportError

log = logging.getLogger(__name__)

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # PC -> device (write without response)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # device -> PC (notify)
NAME_PREFIX = "EduKit-"


class _BleLoop:
    """A single background asyncio loop shared by every BLE transport."""

    _instance: "_BleLoop | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="ble-loop", daemon=True)
        self.thread.start()

    @classmethod
    def get(cls) -> "_BleLoop":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def in_loop(self) -> bool:
        return threading.current_thread() is self.thread

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def run(self, coro: Coroutine[Any, Any, Any], timeout: float) -> Any:
        if self.in_loop():
            raise RuntimeError("blocking BLE call from the BLE thread")
        return self.submit(coro).result(timeout)


class BleTransport(Transport):
    kind = "ble"

    def __init__(self, device: Any, label: str = "", client_factory: Callable[..., Any] | None = None):
        address = getattr(device, "address", str(device))
        super().__init__(f"ble:{address}")
        self.device = device
        self.label = label or getattr(device, "name", "") or address
        self._factory = client_factory
        self._client: Any = None
        self._open = False
        self._decoder = LineDecoder()
        self._mtu = 23
        self._ble = _BleLoop.get()

    # ------------------------------------------------------------------ open
    def open(self) -> None:
        try:
            self._ble.run(self._connect(), timeout=25)
        except Exception as exc:
            self._open = False
            raise TransportError(f"BLE connect to {self.label} failed: {exc}") from exc

    async def _connect(self) -> None:
        factory = self._factory
        if factory is None:
            from bleak import BleakClient

            factory = BleakClient
        self._client = factory(self.device, disconnected_callback=self._on_disconnect)
        await self._client.connect(timeout=15)
        self._mtu = int(getattr(self._client, "mtu_size", 23) or 23)
        self._open = True
        await self._client.start_notify(NUS_TX, self._on_notify)

    # -------------------------------------------------------------- receiving
    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        for item in self._decoder.feed(bytes(data)):
            try:
                if isinstance(item, Noise):
                    self.on_noise(item.text)
                else:
                    self.on_message(item)
            except Exception:
                log.exception("BLE message handler failed")

    def _on_disconnect(self, _client: Any) -> None:
        if self._open:
            self._open = False
            self.on_closed("Bluetooth disconnected")

    # ---------------------------------------------------------------- sending
    def send(self, msg: dict[str, Any]) -> None:
        if not self._open or self._client is None:
            raise TransportError(f"{self.label} is not connected")
        data = encode(msg)
        if self._ble.in_loop():
            # e.g. acknowledging an event from inside a notification: never block the loop
            self._ble.loop.create_task(self._write(data))
            return
        try:
            self._ble.run(self._write(data), timeout=5)
        except Exception as exc:
            raise TransportError(f"BLE write to {self.label} failed: {exc}") from exc

    async def _write(self, data: bytes) -> None:
        chunk = max(20, self._mtu - 3)
        for off in range(0, len(data), chunk):
            await self._client.write_gatt_char(NUS_RX, data[off : off + chunk], response=False)

    def close(self) -> None:
        was_open, self._open = self._open, False
        if self._client is None:
            return
        try:
            if self._ble.in_loop():
                self._ble.loop.create_task(self._client.disconnect())
            elif was_open or getattr(self._client, "is_connected", False):
                self._ble.run(self._client.disconnect(), timeout=5)
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        return self._open


class BleDiscovery(DiscoverySource):
    """Scans for EduKit boards in the background; ``discover`` never blocks.

    Only *paired* boards (chosen by the teacher with «ربط») are connected automatically.
    ``scan_now()`` runs a search so the teacher can see every board in range.
    """

    def __init__(self, scan_seconds: float = 4.0, interval: float = 6.0, scanner: Callable[..., Any] | None = None,
                 paired: Iterable[str] = ()):
        self.scan_seconds = scan_seconds
        self.interval = interval
        self._scanner = scanner
        self._found: dict[str, tuple[Any, str, float, int | None]] = {}  # address -> (BLEDevice, name, seen_at, rssi)
        self._scanning = False
        self._last_scan = -1e9
        self._manual_until = 0.0
        self.last_error = ""
        self.paired: set[str] = set(paired)
        self._lock = threading.Lock()
        self._ble = _BleLoop.get()

    async def _scan(self) -> None:
        try:
            scan = self._scanner
            if scan is None:
                from bleak import BleakScanner

                scan = BleakScanner.discover
            found = await scan(timeout=self.scan_seconds, return_adv=True)
            now = time.monotonic()
            with self._lock:
                for address, (dev, adv) in found.items():
                    name = adv.local_name or dev.name or ""
                    uuids = [u.lower() for u in (adv.service_uuids or [])]
                    if NUS_SERVICE in uuids or name.startswith(NAME_PREFIX):
                        self._found[address] = (dev, name, now, getattr(adv, "rssi", None))
            self.last_error = ""
        except Exception as exc:  # Bluetooth off, permission denied, no adapter
            self.last_error = str(exc) or type(exc).__name__
            log.warning("BLE scan failed: %s", self.last_error)
        finally:
            self._scanning = False
            self._last_scan = time.monotonic()

    @property
    def scanning(self) -> bool:
        return self._scanning

    def scan_now(self, seconds: float = 6.0) -> None:
        """Teacher pressed «بحث»: search now and keep searching for a short while."""
        self._manual_until = time.monotonic() + seconds
        if not self._scanning:
            self._scanning = True
            self._ble.submit(self._scan())

    def devices(self) -> list[tuple[str, str]]:
        with self._lock:
            return [(addr, name) for addr, (_d, name, _t, _r) in self._found.items()]

    def found(self) -> list[dict[str, Any]]:
        """Every EduKit board seen recently: address, name, rssi, age_s, paired."""
        now = time.monotonic()
        with self._lock:
            items = list(self._found.items())
        return sorted(
            ({"address": a, "name": n, "rssi": r, "age_s": now - t, "paired": a in self.paired} for a, (_d, n, t, r) in items if now - t < 120),
            key=lambda d: d["name"],
        )

    def discover(self, busy: set[str]) -> Iterable[Transport]:
        now = time.monotonic()
        want = any(f"ble:{a}" not in busy for a in self.paired) or now < self._manual_until
        if want and not self._scanning and now - self._last_scan >= self.interval:
            self._scanning = True
            self._ble.submit(self._scan())
        with self._lock:
            items = list(self._found.items())
        out: list[Transport] = []
        for address, (dev, name, seen, _rssi) in items:
            if address not in self.paired or f"ble:{address}" in busy or now - seen > 60:
                continue
            out.append(BleTransport(dev, name))
        return out
