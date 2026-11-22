"""Game 1, two-board design: INPUT_01 = 4 touch pads only, MAP_01 = LED route strip only (GPIO 26)."""
import pytest

from conftest import REPO_ROOT
from edukit.activities.journey import JourneySettings, JourneyState
from edukit.core.session import SessionController
from edukit.data.repository import Repository
from edukit.data.seed import seed_journey_mcq
from edukit.feedback.engine import FeedbackEngine
from edukit.hardware.manager import DeviceManager
from edukit.hardware.simulator import SimulatedInputDevice, SimulatedMapDevice, SimulationDiscovery

MCQ = REPO_ROOT / "sample_data" / "journey_mcq_ar.json"


@pytest.fixture
def game(sched, bus):
    pads = SimulatedInputDevice("INPUT_01", channels=4, clock=sched.now)
    strip = SimulatedMapDevice("MAP_01", buttons=0, clock=sched.now)  # the LED board has no answer inputs
    mgr = DeviceManager(bus, [SimulationDiscovery([pads, strip])], clock=sched.now)
    mgr.scan()
    repo = Repository(":memory:")
    seed_journey_mcq(repo, MCQ)
    ctl = SessionController(repo, mgr, FeedbackEngine(mgr, bus), bus, sched)
    return ctl, repo, pads, strip, repo.list_banks()[0]


def start(ctl, bank, **kw):
    kw.setdefault("shuffle", False)
    act = ctl.start_journey(bank.id, None, None, JourneySettings(**kw))
    act.start()
    return act


def test_answers_armed_on_touch_board_not_led_board(game):
    ctl, repo, pads, strip, bank = game
    act = start(ctl, bank)
    assert act.buttons_target() == "input"
    assert pads.armed and pads.question_id == "J001" and pads.allowed == ["A", "B", "C", "D"]
    assert not any(c["command"] == "arm" for c in strip.history)


def test_touch_answer_moves_the_strip(game, sched):
    ctl, repo, pads, strip, bank = game
    act = start(ctl, bank)
    assert pads.press("A")  # correct
    assert act.step == 1 and act.state == JourneyState.FEEDBACK
    cmd = strip.history[-1]
    assert cmd["command"] == "path_advance" and (cmd["from"], cmd["to"]) == (0, 1)
    row = repo.session_responses(ctl.session_id)[0]
    assert (row["answer"], row["outcome"], row["device_id"]) == ("A", "correct", "INPUT_01")
    sched.advance(4.0)
    assert act.current.code == "J002" and pads.armed
    pads.press("A")  # wrong (J002 answer is B)
    assert act.step == 0 and strip.history[-1]["command"] == "path_back"
