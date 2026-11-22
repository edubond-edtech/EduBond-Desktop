"""USB serial transport (pyserial) for ESP32 controllers."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable

from .protocol import BAUD_RATE, LineDecoder, Noise, encode
from .transport import DiscoverySource, Transport, TransportError

log = logging.getLogger(__name__)

# USB-UART bridges commonly found on ESP32 dev boards.
KNOWN_USB_VIDS = {
    0x10C4: "Silicon Labs CP210x",
    0x1A86: "WCH CH340/CH9102",
    0x303A: "Espressif native USB",
    0x0403: "FTDI",
}
_IGNORED_NAME_HINTS = ("bluetooth", "debug-console", "wlan-debug", "airpods")


class SerialTransport(Transport):
    kind = "serial"

    def __init__(self, port: str, baudrate: int = BAUD_RATE, serial_factory: Callable[..., Any] | None = None):
        super().__init__(port)
        self.baudrate = baudrate
        self._factory = serial_factory
        self._ser = None
        self._decoder = LineDecoder()
        self._reader: threading.Thread | None = None
        self._running = False
        self._write_lock = threading.Lock()

    def open(self) -> None:
        factory = self._factory
        if factory is None:
            import serial  # imported lazily so the core works without pyserial in tests

            factory = serial.Serial
        try:
            self._ser = factory(self.name, self.baudrate, timeout=0.05, write_timeout=0.5)
        except Exception as exc:  # serial.SerialException, PermissionError, ...
            raise TransportError(f"cannot open {self.name}: {exc}") from exc
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name=f"serial-{self.name}", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        reason = "closed"
        try:
            while self._running:
                ser = self._ser
                if ser is None:
                    break
                waiting = getattr(ser, "in_waiting", 0) or 1
                data = ser.read(min(waiting, 4096))
                if not data:
                    continue
                for item in self._decoder.feed(data):
                    if isinstance(item, Noise):
                        self.on_noise(item.text)
                    else:
                        try:
                            self.on_message(item)
                        except Exception:  # never let a handler kill the reader
                            log.exception("message handler failed")
        except Exception as exc:
            reason = f"read error: {exc}"
        finally:
            was_running = self._running
            self._running = False
            self._close_port()
            if was_running:
                self.on_closed(reason)

    def send(self, msg: dict[str, Any]) -> None:
        data = encode(msg)
        with self._write_lock:
            if self._ser is None or not self._running:
                raise TransportError(f"{self.name} is not open")
            try:
                self._ser.write(data)
            except Exception as exc:
                raise TransportError(f"write failed on {self.name}: {exc}") from exc

    def close(self) -> None:
        self._running = False
        if self._reader and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.0)
        self._close_port()

    def _close_port(self) -> None:
        with self._write_lock:
            ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    @property
    def is_open(self) -> bool:
        return self._running and self._ser is not None


def list_candidate_ports(include_unknown: bool = True) -> list[tuple[str, str]]:
    """Return ``(device, description)`` of serial ports that may be ESP32 boards."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    result = []
    for p in list_ports.comports():
        name = (p.device or "").lower()
        if any(h in name for h in _IGNORED_NAME_HINTS):
            continue
        if name.startswith("/dev/tty.") :
            # On macOS prefer the /dev/cu.* callout device; tty.* blocks on open.
            continue
        if p.vid in KNOWN_USB_VIDS:
            result.append((p.device, KNOWN_USB_VIDS[p.vid]))
        elif include_unknown and p.vid is not None:
            result.append((p.device, p.description or "USB serial"))
    return result


class SerialDiscovery(DiscoverySource):
    def __init__(self, include_unknown: bool = True, lister: Callable[[], list[tuple[str, str]]] | None = None):
        self.include_unknown = include_unknown
        self._lister = lister or (lambda: list_candidate_ports(self.include_unknown))

    def discover(self, busy: set[str]) -> Iterable[Transport]:
        for device, _desc in self._lister():
            if device not in busy:
                yield SerialTransport(device)
