"""DeviceManager: discovery, identification, role routing and auto-reconnect.

Activities never talk to transports or links. They ask the manager to send a
command to a *role* ("input" / "output") or to a specific device id, and they
receive InputEvents from the EventBus. Swapping USB for BLE/Wi-Fi therefore
does not touch educational logic.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from ..comms.transport import DiscoverySource, TransportError
from ..core.events import DEVICE_INPUT, DEVICE_LOG, DEVICE_STATUS, EventBus
from .link import CommandHandle, DeviceLink
from .models import DeviceStatus, InputEvent, LinkState

log = logging.getLogger(__name__)


class DeviceManager:
    def __init__(
        self,
        bus: EventBus,
        sources: list[DiscoverySource] | None = None,
        clock: Callable[[], float] = time.monotonic,
        rescan_interval: float = 3.0,
        bad_port_cooldown: float = 30.0,
        link_kwargs: dict[str, Any] | None = None,
    ):
        self.bus = bus
        self.sources: list[DiscoverySource] = list(sources or [])
        self.clock = clock
        self.rescan_interval = rescan_interval
        self.bad_port_cooldown = bad_port_cooldown
        self.link_kwargs = link_kwargs or {}
        # Teacher-selected device per role; None = first online device with that role.
        self.role_assignment: dict[str, str | None] = {"input": None, "output": None, "puzzle": None, "map": None}

        self._lock = threading.RLock()
        self._links: list[DeviceLink] = []
        self._by_id: dict[str, DeviceLink] = {}
        self._known: dict[str, DeviceStatus] = {}
        self._cooldown: dict[str, float] = {}
        self._last_scan = -1e9
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------- discovery
    def add_source(self, src: DiscoverySource) -> None:
        with self._lock:
            self.sources.append(src)
        self.scan()

    def remove_source(self, src: DiscoverySource) -> None:
        with self._lock:
            if src in self.sources:
                self.sources.remove(src)

    def scan(self) -> int:
        """Open any newly available devices. Returns number of links started."""
        now = self.clock()
        with self._lock:
            self._last_scan = now
            busy = {l.address for l in self._links}
            busy |= {addr for addr, until in self._cooldown.items() if until > now}
            sources = list(self.sources)
        started = 0
        for src in sources:
            try:
                transports = list(src.discover(busy))
            except Exception:
                log.exception("discovery failed for %s", src)
                continue
            for t in transports:
                link = DeviceLink(t, clock=self.clock, **self.link_kwargs)
                link.on_state = self._on_link_state
                link.on_event = self._on_link_event
                link.on_log = self._on_link_log
                with self._lock:
                    self._links.append(link)
                try:
                    link.start()
                    started += 1
                except TransportError as exc:
                    with self._lock:
                        self._links.remove(link)
                        self._cooldown[t.name] = now + self.bad_port_cooldown / 3
                    self.bus.publish(DEVICE_LOG, (t.name, "debug", f"skip: {exc}"))
        return started

    # ---------------------------------------------------------------- polling
    def poll(self) -> None:
        with self._lock:
            links = list(self._links)
        for l in links:
            l.poll()
        with self._lock:
            for l in list(self._links):
                if l.state in (LinkState.CLOSED, LinkState.LOST):
                    self._links.remove(l)
                    if l.info is None:  # never identified -> not ours, back off
                        self._cooldown[l.address] = self.clock() + self.bad_port_cooldown
            due = self.clock() - self._last_scan >= self.rescan_interval
        if due:
            self.scan()

    def start(self, interval: float = 0.1) -> None:
        if self._running:
            return
        self._running = True

        def loop() -> None:
            while self._running:
                try:
                    self.poll()
                except Exception:
                    log.exception("device manager poll failed")
                time.sleep(interval)

        self.scan()
        self._thread = threading.Thread(target=loop, name="device-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        with self._lock:
            links = list(self._links)
        for l in links:
            l.close("shutdown")

    def disconnect_all(self, kind: str | None = None) -> None:
        with self._lock:
            links = [l for l in self._links if kind is None or l.transport.kind == kind]
        for l in links:
            l.close("disconnected by teacher")

    # -------------------------------------------------------------- callbacks
    def _status_of(self, link: DeviceLink) -> DeviceStatus:
        info = link.info
        return DeviceStatus(
            device_id=info.device_id if info else link.address,
            role=info.role if info else "?",
            state=link.state,
            transport=link.transport.kind,
            address=link.address,
            fw=info.fw if info else "?",
            caps=dict(info.caps) if info else {},
            last_seen=link.last_rx,
            rtt_ms=link.rtt_ms,
        )

    def _on_link_state(self, link: DeviceLink) -> None:
        if link.info is None:
            return  # not identified: not interesting for the UI
        dev_id = link.info.device_id
        stale: DeviceLink | None = None
        duplicate = False
        with self._lock:
            if link.state == LinkState.ONLINE:
                for other_id, l in list(self._by_id.items()):
                    if l is link and other_id != dev_id:  # device was renamed (set_id)
                        del self._by_id[other_id]
                        self._known.pop(other_id, None)
                old = self._by_id.get(dev_id)
                if old is not None and old is not link and old.online and old.info and old.info.boot_id == link.info.boot_id:
                    # same board reachable twice (e.g. USB cable + Bluetooth): keep the first link
                    duplicate = True
                    self._cooldown[link.address] = self.clock() + self.bad_port_cooldown * 2
                else:
                    if old is not None and old is not link:
                        stale = old
                    self._by_id[dev_id] = link
            elif self._by_id.get(dev_id) is link:
                del self._by_id[dev_id]
            status = self._status_of(link)
            self._known[dev_id] = status
        if duplicate:
            self.bus.publish(DEVICE_LOG, (dev_id, "info", f"already connected via {self._by_id[dev_id].transport.kind}; ignoring {link.transport.kind} link"))
            link.close("duplicate link")
            return
        if stale is not None:
            stale.close("superseded by new connection")
        self.bus.publish(DEVICE_STATUS, status)
        level = "info" if link.state == LinkState.ONLINE else "warn"
        reason = f" ({link.close_reason})" if link.state != LinkState.ONLINE and link.close_reason else ""
        self.bus.publish(DEVICE_LOG, (dev_id, level, f"{link.state.value} via {link.transport.kind} {link.address}{reason}"))

    def _on_link_event(self, link: DeviceLink, msg: dict[str, Any]) -> None:
        info = link.info
        assert info is not None
        data = {k: v for k, v in msg.items() if k not in ("type",)}
        self.bus.publish(DEVICE_INPUT, InputEvent(info.device_id, info.role, msg["event"], data, self.clock()))

    def _on_link_log(self, link: DeviceLink, level: str, text: str) -> None:
        self.bus.publish(DEVICE_LOG, (link.device_id or link.address, level, text))

    # ----------------------------------------------------------------- access
    def statuses(self) -> list[DeviceStatus]:
        with self._lock:
            out = dict(self._known)
            for dev_id, link in self._by_id.items():
                out[dev_id] = self._status_of(link)
        return sorted(out.values(), key=lambda s: (s.role, s.device_id))

    def online_devices(self, role: str | None = None) -> list[DeviceLink]:
        with self._lock:
            return [l for l in self._by_id.values() if l.online and (role is None or l.info and l.info.role == role)]

    def device_for(self, target: str) -> DeviceLink | None:
        """``target`` is a role name ("input"/"output") or a device id."""
        with self._lock:
            if target in self.role_assignment:
                pref = self.role_assignment[target]
                if pref:
                    l = self._by_id.get(pref)
                    return l if l and l.online else None
                # real hardware always wins over the simulator
                for l in sorted(self._by_id.values(), key=lambda x: (x.transport.kind == "sim", x.device_id or "")):
                    if l.online and l.info and l.info.role == target:
                        return l
                return None
            l = self._by_id.get(target)
            return l if l and l.online else None

    def is_available(self, target: str) -> bool:
        return self.device_for(target) is not None

    def send(self, target: str, command: str, **params: Any) -> CommandHandle | None:
        """Send safely: returns None (and logs) when no device is available."""
        link = self.device_for(target)
        if link is None:
            self.bus.publish(DEVICE_LOG, (target, "debug", f"no device for '{target}', skipped {command}"))
            return None
        return link.send_command(command, **params)

    def send_all(self, role: str, command: str, **params: Any) -> list[CommandHandle]:
        return [l.send_command(command, **params) for l in self.online_devices(role)]
