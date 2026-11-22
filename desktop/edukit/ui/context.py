"""AppContext: builds and owns every service; shared by all UI pages."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import config
from ..activities.quiz import QuizSettings
from ..comms.serial_transport import SerialDiscovery
from ..core.events import DEVICE_INPUT, DEVICE_LOG, DEVICE_STATUS, FEEDBACK, EventBus
from ..core.session import SessionController
from ..data.repository import Repository
from ..data.seed import seed_demo, seed_indonesia_g1, seed_journey, seed_journey_mcq, upgrade_indonesia_g1_arabic_only
from ..feedback.engine import FeedbackEngine
from ..hardware.manager import DeviceManager
from ..hardware.models import DeviceStatus, LinkState
from ..hardware.simulator import (
    SimulatedInputDevice,
    SimulatedMapDevice,
    SimulatedOutputDevice,
    SimulatedPuzzleBoard,
    SimulationDiscovery,
)
from .qt_bridge import BusBridge, MainThreadDispatcher, QtScheduler
from .sounds import SoundPlayer

log = logging.getLogger(__name__)

DEFAULT_HW = {"simulation": False, "serial": False, "ble": True}  # Bluetooth by default; USB is for flashing


class AppContext(QObject):
    language_changed = Signal(str)
    hardware_mode_changed = Signal()

    def __init__(self, db_path: Path | None = None, data_dir: Path | None = None, hw_overrides: dict | None = None):
        super().__init__()
        self.data_dir = data_dir or config.data_dir()
        self.repo = Repository(db_path or self.data_dir / "edukit.sqlite3")
        seed_demo(self.repo, config.sample_questions_file())
        seed_journey_mcq(self.repo, config.journey_mcq_file())
        seed_journey(self.repo, config.journey_questions_file())
        if seed_indonesia_g1(self.repo, config.indonesia_g1_file()):
            self.repo.set_setting("indonesia_g1_arabic_only", True)  # fresh install already has the Arabic-only set
        upgrade_indonesia_g1_arabic_only(self.repo, config.indonesia_g1_file())
        self.repo.assign_unplaced_lessons()  # every lesson lives somewhere in the curriculum tree

        self.bus = EventBus()
        self.scheduler = QtScheduler()
        self.dispatcher = MainThreadDispatcher()
        self.bridge = BusBridge(self.bus, [DEVICE_STATUS, DEVICE_INPUT, DEVICE_LOG, FEEDBACK])

        self.sim_input = SimulatedInputDevice("SIM_INPUT")
        self.sim_output = SimulatedOutputDevice("SIM_OUTPUT", num_leds=30)
        self.sim_puzzle = SimulatedPuzzleBoard("SIM_PUZZLE")
        self.sim_map = SimulatedMapDevice("SIM_JOURNEY", num_leds=60, steps=6, buttons=4)  # map + 4 buttons on one ESP32
        self.sim_discovery = SimulationDiscovery([self.sim_input, self.sim_output, self.sim_puzzle, self.sim_map])
        self.serial_discovery = SerialDiscovery()
        from ..comms.ble_transport import BleDiscovery

        self.ble_discovery = BleDiscovery(paired=self._load_paired())
        self.devices = DeviceManager(self.bus, [])
        self.devices.role_assignment.update(self.repo.get_setting("role_assignment", {}) or {})

        self.feedback = FeedbackEngine(self.devices, self.bus, lambda: self.repo.get_setting("effect_profile", {}))
        self.sessions = SessionController(self.repo, self.devices, self.feedback, self.bus, self.scheduler, self.dispatcher.dispatch)
        self.sounds = SoundPlayer(self.data_dir / "sounds")
        from .audio import MediaPlayer

        self.media = MediaPlayer()
        from .speech import Speaker

        self.speaker = Speaker()
        self.sounds.enabled = bool(self.repo.get_setting("screen_sounds", True))
        self.bridge.on(FEEDBACK, lambda p: self.sounds.play(p[1].get("sound")))
        self.bridge.on(DEVICE_STATUS, self._remember_device)

        self.lang: str = self.repo.get_setting("lang", "en")
        hw = {**DEFAULT_HW, **(self.repo.get_setting("hardware", {}) or {}), **(hw_overrides or {})}
        self.set_simulation(hw["simulation"], persist=False)
        self.set_serial(hw["serial"], persist=False)
        self.set_ble(hw["ble"], persist=False)

    # ----------------------------------------------------------- hardware
    @property
    def simulation_enabled(self) -> bool:
        return self.sim_discovery in self.devices.sources

    @property
    def serial_enabled(self) -> bool:
        return self.serial_discovery in self.devices.sources

    def _hw_changed(self, persist: bool) -> None:
        if persist:
            self.repo.set_setting("hardware", {"simulation": self.simulation_enabled, "serial": self.serial_enabled, "ble": self.ble_enabled})
        # recorded with each session; "serial" is what counts for real-hardware validation
        self.sessions.hardware_mode = "+".join(m for m, on in (("simulation", self.simulation_enabled), ("serial", self.serial_enabled), ("ble", self.ble_enabled)) if on) or "none"
        self.hardware_mode_changed.emit()

    def set_simulation(self, on: bool, persist: bool = True) -> None:
        if on and not self.simulation_enabled:
            for d in self.sim_discovery.devices:
                d.plug_in()
            self.devices.add_source(self.sim_discovery)
        elif not on and self.simulation_enabled:
            self.devices.remove_source(self.sim_discovery)
            self.devices.disconnect_all("sim")
        self._hw_changed(persist)

    def _load_paired(self) -> list[str]:
        paired = self.repo.get_setting("paired_devices", None)
        if paired is None:  # first run of this version: keep boards that were already used over Bluetooth
            paired = [{"address": d["address"][4:], "name": d["device_id"]} for d in self.repo.list_devices()
                      if d["transport"] == "ble" and d["address"].startswith("ble:")]
            self.repo.set_setting("paired_devices", paired)
        return [p["address"] for p in paired]

    def paired_devices(self) -> list[dict]:
        return list(self.repo.get_setting("paired_devices", []) or [])

    def pair_device(self, address: str, name: str) -> None:
        paired = [p for p in self.paired_devices() if p["address"] != address] + [{"address": address, "name": name}]
        self.repo.set_setting("paired_devices", paired)
        self.ble_discovery.paired.add(address)
        self.devices.scan()

    def unpair_device(self, address: str) -> None:
        self.repo.set_setting("paired_devices", [p for p in self.paired_devices() if p["address"] != address])
        self.ble_discovery.paired.discard(address)
        for link in list(self.devices._links):
            if link.address == f"ble:{address}":
                link.close("unpaired by teacher")

    @property
    def ble_enabled(self) -> bool:
        return self.ble_discovery in self.devices.sources

    def set_ble(self, on: bool, persist: bool = True) -> None:
        if on and not self.ble_enabled:
            self.devices.add_source(self.ble_discovery)
        elif not on and self.ble_enabled:
            self.devices.remove_source(self.ble_discovery)
            self.devices.disconnect_all("ble")
        self._hw_changed(persist)

    def set_serial(self, on: bool, persist: bool = True) -> None:
        if on and not self.serial_enabled:
            self.devices.add_source(self.serial_discovery)
        elif not on and self.serial_enabled:
            self.devices.remove_source(self.serial_discovery)
            self.devices.disconnect_all("serial")
        self._hw_changed(persist)

    def _remember_device(self, st: DeviceStatus) -> None:
        if st.state == LinkState.ONLINE:
            self.repo.upsert_device(st.device_id, st.role, st.transport, st.address, st.fw)
            cfg = self.repo.device_config(st.device_id)
            if st.role == "map":
                cfg = {**(self.repo.get_setting("map_config", {}) or {}), **cfg}
            if cfg:  # re-apply teacher configuration (mapping, LED count...) after every reconnect
                self.devices.send(st.device_id, "configure", **cfg)

    def set_role_device(self, role: str, device_id: str | None) -> None:
        self.devices.role_assignment[role] = device_id
        self.repo.set_setting("role_assignment", self.devices.role_assignment)

    # ----------------------------------------------------------- settings
    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.repo.set_setting("lang", lang)
        self.language_changed.emit(lang)

    def quiz_settings(self) -> QuizSettings:
        return QuizSettings.from_dict(self.repo.get_setting("quiz_settings", {}))

    def save_quiz_settings(self, s: QuizSettings) -> None:
        self.repo.set_setting("quiz_settings", s.to_dict())

    def start(self) -> None:
        self.devices.start()

    def shutdown(self) -> None:
        self.sessions.stop()
        self.devices.stop()
        self.repo.close()
