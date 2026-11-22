import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edukit.core.events import EventBus, ManualScheduler  # noqa: E402
from edukit.hardware.manager import DeviceManager  # noqa: E402
from edukit.hardware.simulator import SimulatedInputDevice, SimulatedOutputDevice, SimulationDiscovery  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sched():
    return ManualScheduler()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def sim(sched, bus):
    """Two simulated controllers connected through a real DeviceManager."""
    inp = SimulatedInputDevice("INPUT_01", clock=sched.now)
    out = SimulatedOutputDevice("OUTPUT_01")
    disc = SimulationDiscovery([inp, out])
    mgr = DeviceManager(bus, [disc], clock=sched.now)
    mgr.scan()
    return mgr, inp, out, disc
