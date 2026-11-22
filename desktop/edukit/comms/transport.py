"""Transport abstraction.

A Transport moves protocol messages (dicts) between the PC and one device.
USB serial and in-process simulation are implemented today; BLE (e.g. via
``bleak`` + Nordic UART Service) and Wi-Fi (WebSocket/UDP) only need a new
Transport + DiscoverySource -- DeviceLink, DeviceManager and every activity
stay unchanged.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable

MessageHandler = Callable[[dict[str, Any]], None]
CloseHandler = Callable[[str], None]
NoiseHandler = Callable[[str], None]


class TransportError(IOError):
    pass


class Transport(ABC):
    kind: str = "abstract"

    def __init__(self, name: str):
        self.name = name  # unique address, e.g. "/dev/cu.usbserial-0001" or "sim:INPUT_01"
        self.on_message: MessageHandler = lambda m: None
        self.on_closed: CloseHandler = lambda reason: None
        self.on_noise: NoiseHandler = lambda text: None

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send(self, msg: dict[str, Any]) -> None:
        """Send one message. Raises TransportError if the link is down."""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


class DiscoverySource(ABC):
    """Finds devices reachable over one transport technology."""

    @abstractmethod
    def discover(self, busy: set[str]) -> Iterable[Transport]:
        """Return unopened transports for candidate devices whose name is not in ``busy``."""
