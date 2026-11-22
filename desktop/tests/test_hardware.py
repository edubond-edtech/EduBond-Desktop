"""DeviceLink / DeviceManager / transports, driven by simulated controllers."""
import json
import threading
import time

from edukit.comms import protocol as P
from edukit.comms.serial_transport import SerialDiscovery, SerialTransport
from edukit.core.events import DEVICE_INPUT, DEVICE_STATUS
from edukit.hardware.link import DeviceLink
from edukit.hardware.manager import DeviceManager
from edukit.hardware.models import LinkState
from edukit.hardware.simulator import SimulatedInputDevice, SimulatedOutputDevice, SimTransport


def test_discovery_identifies_both_controllers(sim):
    mgr, inp, out, _ = sim
    st = {s.device_id: s for s in mgr.statuses()}
    assert st["INPUT_01"].state == LinkState.ONLINE and st["INPUT_01"].role == "input"
    assert st["OUTPUT_01"].state == LinkState.ONLINE and st["OUTPUT_01"].caps["leds"] == 30
    assert mgr.device_for("output").device_id == "OUTPUT_01"


def test_command_is_acknowledged(sim):
    mgr, _, out, _ = sim
    h = mgr.send("output", "play_effect", effect="correct", color="green", duration_ms=3000)
    assert h.status == "acked"
    sent = out.history[-1]
    assert sent["command"] == "play_effect" and sent["device_id"] == "OUTPUT_01" and sent["effect"] == "correct"


def test_unknown_command_is_nacked(sim):
    mgr, *_ = sim
    h = mgr.send("output", "make_coffee")
    assert h.status == "failed" and "unknown" in h.error


def test_retry_then_fail_when_device_hangs(sim, sched):
    mgr, _, out, _ = sim
    out.respond = False
    before = len(out.received)
    h = mgr.send("output", "play_effect", effect="solid")
    assert h.status == "pending"
    for _ in range(4):
        sched.advance(0.6)
        mgr.poll()
    assert h.status == "failed" and h.error == "no ack"
    assert len([m for m in out.received[before:] if m.get("id") == h.id]) == 3  # 1 send + 2 retries


def test_heartbeat_timeout_marks_device_lost_and_reconnects(sim, sched, bus):
    mgr, _, out, _ = sim
    states = []
    bus.subscribe(DEVICE_STATUS, lambda s: states.append((s.device_id, s.state)))
    out.respond = False
    for _ in range(80):
        sched.advance(0.1)
        mgr.poll()
    assert ("OUTPUT_01", LinkState.LOST) in states
    assert mgr.device_for("output") is None
    out.respond = True
    for _ in range(40):
        sched.advance(0.1)
        mgr.poll()
    assert mgr.device_for("output") is not None


def test_unplug_and_replug(sim, sched):
    mgr, inp, _, _ = sim
    inp.unplug()
    assert mgr.device_for("input") is None
    assert mgr.send("input", "arm", question_id="Q1", options=["A"]) is None  # safe, no exception
    inp.plug_in()
    sched.advance(3.1)
    mgr.poll()
    assert mgr.device_for("input") is not None


def test_events_are_acked_and_duplicates_dropped(sim, bus):
    mgr, inp, _, _ = sim
    events = []
    bus.subscribe(DEVICE_INPUT, events.append)
    mgr.send("input", "arm", question_id="Q001", options=["A", "B", "C", "D"])
    assert inp.press("C")
    assert not inp.unacked  # PC acknowledged
    # simulate a retransmission (e.g. ack lost on the wire): same seq must not be delivered twice
    inp.unacked[inp.seq] = {"type": "event", "device_id": "INPUT_01", "seq": inp.seq, "event": "answer_selected", "question_id": "Q001", "selected_answer": "C"}
    inp.retransmit_unacked()
    assert len(events) == 1
    e = events[0]
    assert (e.device_id, e.event, e.question_id, e.selected_answer) == ("INPUT_01", "answer_selected", "Q001", "C")
    assert mgr.device_for("input").duplicates_dropped == 1


def test_input_device_ignores_presses_when_not_armed_and_locks_after_answer(sim, sched, bus):
    mgr, inp, _, _ = sim
    events = []
    bus.subscribe(DEVICE_INPUT, events.append)
    assert not inp.press("A")  # not armed
    mgr.send("input", "arm", question_id="Q1", options=["A", "B"])
    assert not inp.press("D")  # not an allowed option
    assert inp.press("B")
    sched.advance(1)
    assert not inp.press("A")  # locked until re-armed
    assert len(events) == 1


def test_configurable_mapping(sim, bus):
    mgr, inp, _, _ = sim
    events = []
    bus.subscribe(DEVICE_INPUT, events.append)
    mgr.send("input", "configure", mapping={"0": "D", "1": "C", "2": "B", "3": "A"})
    mgr.send("input", "arm", question_id="Q1", options=["A", "B", "C", "D"])
    inp.press(0)
    assert events[0].selected_answer == "D"


def test_role_assignment_prefers_selected_device(sched, bus):
    from edukit.hardware.simulator import SimulationDiscovery

    o1, o2 = SimulatedOutputDevice("OUTPUT_01"), SimulatedOutputDevice("OUTPUT_02")
    mgr = DeviceManager(bus, [SimulationDiscovery([o1, o2])], clock=sched.now)
    mgr.scan()
    assert mgr.device_for("output").device_id == "OUTPUT_01"
    mgr.role_assignment["output"] = "OUTPUT_02"
    assert mgr.device_for("output").device_id == "OUTPUT_02"
    assert len(mgr.send_all("output", "stop")) == 2


def test_link_ignores_events_before_hello(sched):
    dev = SimulatedInputDevice("INPUT_09", clock=sched.now)
    t = SimTransport(dev)
    link = DeviceLink(t, clock=sched.now)
    got = []
    link.on_event = lambda l, m: got.append(m)
    link._on_message({"type": "event", "seq": 1, "event": "answer_selected"})
    assert got == []


# --------------------------------------------------------------------------
# SerialTransport against a fake serial port backed by a simulated ESP32.
class FakeSerial:
    """Mimics pyserial: bytes written are parsed as NDJSON and handed to a simulated device."""

    def __init__(self, device, *a, **kw):
        self.device = device
        self.rx = bytearray()
        self.cv = threading.Condition()
        self.closed = False
        self.decoder = P.LineDecoder()
        device.attach(self._emit, lambda reason: self.close())
        self._emit_raw(b"ets Jun  8 2016 00:22:57\r\nrst:0x1 (POWERON_RESET)\r\n")  # boot noise

    def _emit_raw(self, data):
        with self.cv:
            self.rx.extend(data)
            self.cv.notify_all()

    def _emit(self, msg):
        self._emit_raw(json.dumps(msg).encode() + b"\n")

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n):
        with self.cv:
            if not self.rx:
                self.cv.wait(0.05)
            if self.closed:
                raise OSError("device disconnected")
            out = bytes(self.rx[:n])
            del self.rx[:n]
            return out

    def write(self, data):
        if self.closed:
            raise OSError("closed")
        for m in self.decoder.feed(data):
            self.device.receive(m)
        return len(data)

    def close(self):
        with self.cv:
            self.closed = True
            self.cv.notify_all()


def _wait(pred, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_serial_transport_end_to_end_with_real_threads(bus):
    dev = SimulatedOutputDevice("OUTPUT_01")
    ports = [("/dev/cu.fake-esp32", "CP210x")]
    disc = SerialDiscovery(lister=lambda: ports)
    # inject the fake port into transports created by discovery
    orig = disc.discover

    def discover(busy):
        for t in orig(busy):
            t._factory = lambda *a, **kw: FakeSerial(dev)
            yield t

    disc.discover = discover
    mgr = DeviceManager(bus, [disc])
    mgr.scan()
    assert _wait(lambda: mgr.device_for("output") is not None)
    h = mgr.send("output", "play_effect", effect="incorrect")
    assert _wait(lambda: h.status == "acked")
    assert dev.effect.color == (255, 0, 0)
    link = mgr.device_for("output")
    dev.unplug()  # cable pulled -> reader thread hits an error
    assert _wait(lambda: link.state == LinkState.LOST)
    mgr.stop()


def test_serial_transport_open_failure_is_reported(bus):
    def boom(*a, **kw):
        raise OSError("Resource busy")

    t = SerialTransport("/dev/cu.nothing", serial_factory=boom)
    link = DeviceLink(t)
    try:
        link.start()
        raise AssertionError("expected TransportError")
    except IOError as exc:
        assert "Resource busy" in str(exc)
    assert link.state == LinkState.CLOSED


def test_rename_device_with_set_id(sim):
    mgr, inp, _, _ = sim
    h = mgr.send("INPUT_01", "set_id", new_id="INPUT_02")
    assert h.status == "acked"
    assert mgr.device_for("INPUT_02") is not None
    assert mgr.device_for("INPUT_01") is None
    assert {s.device_id for s in mgr.statuses()} == {"INPUT_02", "OUTPUT_01"}
    assert mgr.send("INPUT_02", "set_id", new_id="").status == "failed"  # nack
    mgr.scan()  # a rescan must not open a second link to the renamed device
    assert len(mgr.online_devices("input")) == 1


def test_real_device_preferred_over_simulator(sched, bus):
    from edukit.hardware.simulator import SimulationDiscovery

    sim_map = SimulatedOutputDevice("A_SIM")  # sorts first alphabetically
    real = SimulatedOutputDevice("Z_REAL")
    mgr = DeviceManager(bus, [SimulationDiscovery([sim_map])], clock=sched.now)
    mgr.scan()
    real_t = SimTransport(real)
    real_t.kind = "serial"  # pretend it arrived over USB
    from edukit.hardware.link import DeviceLink

    class Src:
        def discover(self, busy):
            return [real_t] if real_t.name not in busy else []

    mgr.add_source(Src())
    assert mgr.device_for("output").device_id == "Z_REAL"


def test_same_board_over_two_links_keeps_the_first(sched, bus):
    """USB + Bluetooth to the same ESP32 must not flap between the two links."""
    from edukit.hardware.link import DeviceLink  # noqa: F401
    from edukit.hardware.simulator import SimulationDiscovery

    dev = SimulatedOutputDevice("JOURNEY_01")
    mgr = DeviceManager(bus, [SimulationDiscovery([dev])], clock=sched.now)
    mgr.scan()
    first = mgr.device_for("JOURNEY_01")

    from edukit.comms.transport import Transport

    class BlePath(Transport):  # the same powered-up board seen over Bluetooth: same hello / boot_id
        kind = "ble"

        def __init__(self):
            super().__init__("ble:AA-BB")
            self._open = False

        def open(self):
            self._open = True
            self.on_message(dev.hello())

        def send(self, msg):
            if msg.get("id") is not None:
                self.on_message({"type": "ack", "id": msg["id"]})

        def close(self):
            self._open = False

        @property
        def is_open(self):
            return self._open

    class SecondLink:
        def discover(self, busy):
            return [] if "ble:AA-BB" in busy else [BlePath()]

    mgr.add_source(SecondLink())
    for _ in range(5):
        sched.advance(3.1)
        mgr.poll()
    assert mgr.device_for("JOURNEY_01") is first and first.online


def test_ble_discovery_connects_only_paired_boards():
    import asyncio
    import time as _t
    from types import SimpleNamespace

    from edukit.comms.ble_transport import NUS_SERVICE, BleDiscovery

    async def fake_scan(timeout, return_adv):
        dev = lambda a, n: (SimpleNamespace(address=a, name=n), SimpleNamespace(local_name=n, service_uuids=[NUS_SERVICE], rssi=-55))  # noqa: E731
        return {"AA": dev("AA", "EduKit-JOURNEY_01"), "BB": dev("BB", "EduKit-JOURNEY_02"),
                "CC": (SimpleNamespace(address="CC", name="Speaker"), SimpleNamespace(local_name="Speaker", service_uuids=[], rssi=-40))}

    d = BleDiscovery(scanner=fake_scan, interval=0, paired=["AA"])
    d.scan_now()
    end = _t.time() + 3
    while d.scanning and _t.time() < end:
        _t.sleep(0.02)
    found = d.found()
    assert [f["name"] for f in found] == ["EduKit-JOURNEY_01", "EduKit-JOURNEY_02"]  # not the speaker
    assert [f["paired"] for f in found] == [True, False] and found[0]["rssi"] == -55
    assert [t.name for t in d.discover(set())] == ["ble:AA"]  # only the paired board connects
    d.paired.add("BB")
    assert sorted(t.name for t in d.discover({"ble:AA"})) == ["ble:BB"]
    del asyncio
