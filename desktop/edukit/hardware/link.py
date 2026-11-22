"""DeviceLink: reliable session with one device over any Transport.

Responsibilities
  * identification handshake (identify -> hello)
  * command ids, acknowledgements, timeouts and retries
  * acknowledging device events and dropping duplicates (retransmissions)
  * heartbeat (ping) and loss detection
Callbacks are always invoked *outside* the internal lock to avoid deadlocks.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

from ..comms import protocol as P
from ..comms.transport import Transport, TransportError
from .models import DeviceInfo, LinkState

log = logging.getLogger(__name__)


class CommandHandle:
    def __init__(self, cmd_id: int, msg: dict[str, Any], now: float):
        self.id = cmd_id
        self.msg = msg
        self.command = msg.get("command")
        self.attempts = 1
        self.first_sent = now
        self.last_sent = now
        self.status = "pending"  # pending | acked | failed
        self.error: str | None = None
        self.reply: dict[str, Any] | None = None
        self._callbacks: list[Callable[[CommandHandle], None]] = []

    def on_done(self, fn: Callable[["CommandHandle"], None]) -> "CommandHandle":
        if self.status != "pending":
            fn(self)
        else:
            self._callbacks.append(fn)
        return self

    def _finish(self) -> list[Callable[[], None]]:
        cbs, self._callbacks = self._callbacks, []
        return [lambda f=f: f(self) for f in cbs]

    def __repr__(self) -> str:
        return f"<Cmd {self.id} {self.command} {self.status}>"


class DeviceLink:
    def __init__(
        self,
        transport: Transport,
        clock: Callable[[], float] = time.monotonic,
        ack_timeout: float = 0.5,
        max_attempts: int = 3,
        heartbeat_interval: float = 2.0,
        heartbeat_timeout: float = 6.5,
        hello_timeout: float = 5.0,
        identify_interval: float = 1.0,
    ):
        self.transport = transport
        self.clock = clock
        self.ack_timeout = ack_timeout
        self.max_attempts = max_attempts
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.hello_timeout = hello_timeout
        self.identify_interval = identify_interval

        self.state = LinkState.CLOSED
        self.info: DeviceInfo | None = None
        self.rtt_ms: float | None = None
        self.last_rx = 0.0
        self.duplicates_dropped = 0
        self.close_reason = ""

        self.on_state: Callable[[DeviceLink], None] = lambda link: None
        self.on_event: Callable[[DeviceLink, dict[str, Any]], None] = lambda link, msg: None
        self.on_log: Callable[[DeviceLink, str, str], None] = lambda link, level, text: None

        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self._pending: dict[int, CommandHandle] = {}
        self._seen: deque[tuple[str, int]] = deque(maxlen=256)
        self._seen_set: set[tuple[str, int]] = set()
        self._opened_at = 0.0
        self._last_identify = 0.0
        self._last_ping = 0.0

    # ------------------------------------------------------------------ props
    @property
    def address(self) -> str:
        return self.transport.name

    @property
    def device_id(self) -> str | None:
        return self.info.device_id if self.info else None

    @property
    def online(self) -> bool:
        return self.state == LinkState.ONLINE

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        t = self.transport
        t.on_message = self._on_message
        t.on_closed = self._on_transport_closed
        t.on_noise = lambda text: self.on_log(self, "noise", text)
        now = self.clock()
        with self._lock:
            self._opened_at = now
            self.last_rx = now
            self.state = LinkState.CONNECTING
        try:
            t.open()  # may raise TransportError; a device may already say hello during open
        except Exception:
            with self._lock:
                self.state = LinkState.CLOSED
            raise
        if self.state == LinkState.CONNECTING:
            self._send_identify()
            self.on_state(self)

    def close(self, reason: str = "closed by host") -> None:
        fire = self._shutdown(LinkState.CLOSED, reason)
        try:
            self.transport.close()
        except Exception:
            pass
        for f in fire:
            f()

    def _shutdown(self, new_state: LinkState, reason: str) -> list[Callable[[], None]]:
        fire: list[Callable[[], None]] = []
        with self._lock:
            if self.state in (LinkState.CLOSED, LinkState.LOST) and new_state != LinkState.CLOSED:
                return fire
            if self.state == new_state:
                return fire
            self.state = new_state
            self.close_reason = reason
            for h in self._pending.values():
                h.status, h.error = "failed", f"link {new_state.value}: {reason}"
                fire.extend(h._finish())
            self._pending.clear()
        fire.append(lambda: self.on_state(self))
        return fire

    # --------------------------------------------------------------- sending
    def _send_identify(self) -> None:
        self._last_identify = self.clock()
        self._write({"id": next(self._ids), "command": P.C_IDENTIFY})

    def send_command(self, command: str, **params: Any) -> CommandHandle:
        now = self.clock()
        with self._lock:
            cmd_id = next(self._ids)
            msg: dict[str, Any] = {"id": cmd_id, "command": command}
            if self.info:
                msg["device_id"] = self.info.device_id
            msg.update(params)
            h = CommandHandle(cmd_id, msg, now)
            if self.state != LinkState.ONLINE:
                h.status, h.error = "failed", f"device not online ({self.state.value})"
                return h
            self._pending[cmd_id] = h
        self._write(msg)
        return h

    def _write(self, msg: dict[str, Any]) -> bool:
        try:
            self.transport.send(msg)
            return True
        except TransportError as exc:
            log.warning("write failed on %s: %s", self.address, exc)
            for f in self._shutdown(LinkState.LOST, str(exc)):
                f()
            return False
        except P.ProtocolError as exc:
            log.error("refusing to send invalid message: %s", exc)
            return False

    # -------------------------------------------------------------- receiving
    def _on_message(self, raw: dict[str, Any]) -> None:
        try:
            msg = P.validate_inbound(raw)
        except P.ProtocolError as exc:
            self.on_log(self, "warn", f"invalid message ignored: {exc}: {raw}")
            return
        now = self.clock()
        fire: list[Callable[[], None]] = []
        reply: dict[str, Any] | None = None
        with self._lock:
            self.last_rx = now
            mtype = msg["type"]
            if mtype == P.T_HELLO:
                new_info = DeviceInfo(
                    device_id=msg["device_id"],
                    role=msg["role"],
                    fw=str(msg.get("fw", "?")),
                    proto=int(msg.get("proto", 1)),
                    boot_id=str(msg.get("boot_id", "")),
                    caps=dict(msg.get("caps") or {}),
                )
                if self.info and self.info.boot_id != new_info.boot_id:
                    note = f"{new_info.device_id} rebooted (boot_id {new_info.boot_id})"
                    fire.append(lambda note=note: self.on_log(self, "info", note))
                renamed = self.info is not None and self.info.device_id != new_info.device_id
                self.info = new_info
                if renamed and self.state == LinkState.ONLINE:
                    fire.append(lambda: self.on_state(self))
                if self.state != LinkState.ONLINE:
                    self.state = LinkState.ONLINE
                    self._last_ping = now
                    fire.append(lambda: self.on_state(self))
            elif mtype in (P.T_ACK, P.T_NACK):
                h = self._pending.pop(msg["id"], None)
                if h is not None:
                    h.reply = msg
                    if mtype == P.T_ACK:
                        h.status = "acked"
                        if h.command == P.C_PING:
                            self.rtt_ms = (now - h.last_sent) * 1000.0
                    else:
                        h.status, h.error = "failed", str(msg.get("error", "nack"))
                        fire.append(lambda h=h: self.on_log(self, "warn", f"command {h.command} rejected: {h.error}"))
                    fire.extend(h._finish())
            elif mtype == P.T_EVENT:
                if self.info is None:
                    # Not identified yet: don't ack, the device will retransmit after hello.
                    return
                reply = {"command": P.C_ACK, "seq": msg["seq"]}
                key = (self.info.boot_id, msg["seq"])
                if key in self._seen_set:
                    self.duplicates_dropped += 1
                else:
                    if len(self._seen) == self._seen.maxlen:
                        self._seen_set.discard(self._seen[0])
                    self._seen.append(key)
                    self._seen_set.add(key)
                    fire.append(lambda: self.on_event(self, msg))
            elif mtype == P.T_LOG:
                fire.append(lambda: self.on_log(self, str(msg.get("level", "info")), str(msg.get("msg", ""))))
        if reply is not None:
            self._write(reply)
        for f in fire:
            f()

    def _on_transport_closed(self, reason: str) -> None:
        for f in self._shutdown(LinkState.LOST, reason):
            f()

    # ------------------------------------------------------------ maintenance
    def poll(self) -> None:
        """Retries, heartbeats and timeouts. Call every ~50-200 ms."""
        now = self.clock()
        fire: list[Callable[[], None]] = []
        resend: list[dict[str, Any]] = []
        identify = False
        ping = False
        lost_reason = None
        with self._lock:
            if self.state == LinkState.CONNECTING:
                if now - self._opened_at > self.hello_timeout:
                    lost_reason = "no hello (not an EduKit device?)"
                elif now - self._last_identify >= self.identify_interval:
                    identify = True
            elif self.state == LinkState.ONLINE:
                for h in list(self._pending.values()):
                    if now - h.last_sent >= self.ack_timeout:
                        if h.attempts < self.max_attempts:
                            h.attempts += 1
                            h.last_sent = now
                            resend.append(h.msg)
                        else:
                            self._pending.pop(h.id, None)
                            h.status, h.error = "failed", "no ack"
                            fire.extend(h._finish())
                            fire.append(lambda h=h: self.on_log(self, "warn", f"no ack for {h.command} (id {h.id})"))
                if now - self.last_rx > self.heartbeat_timeout:
                    lost_reason = "heartbeat timeout"
                elif now - self._last_ping >= self.heartbeat_interval:
                    self._last_ping = now
                    ping = True
        for f in fire:
            f()
        if lost_reason:
            if self.state == LinkState.CONNECTING:
                self.close(lost_reason)
            else:
                for f in self._shutdown(LinkState.LOST, lost_reason):
                    f()
                try:
                    self.transport.close()
                except Exception:
                    pass
            return
        if identify:
            self._send_identify()
        for m in resend:
            self._write(m)
        if ping:
            self.send_command(P.C_PING)
