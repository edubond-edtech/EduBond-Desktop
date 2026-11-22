"""Game 1, buttons design: ONE ESP32 (JOURNEY_01) = LED route map + 4 answer buttons."""
import pytest

from conftest import REPO_ROOT
from edukit.activities.journey import JourneySettings, JourneyState
from edukit.core.session import SessionController
from edukit.data.repository import Repository
from edukit.data.seed import seed_journey_mcq
from edukit.feedback.engine import FeedbackEngine
from edukit.feedback.route import FAIL, RouteConfig, RouteRenderer
from edukit.hardware.manager import DeviceManager
from edukit.hardware.simulator import SimulatedInputDevice, SimulatedMapDevice, SimulationDiscovery

MCQ = REPO_ROOT / "sample_data" / "journey_mcq_ar.json"


@pytest.fixture
def game(sched, bus):
    board = SimulatedMapDevice("JOURNEY_01", buttons=4, clock=sched.now)
    mgr = DeviceManager(bus, [SimulationDiscovery([board])], clock=sched.now)
    mgr.scan()
    repo = Repository(":memory:")
    seed_journey_mcq(repo, MCQ)
    ctl = SessionController(repo, mgr, FeedbackEngine(mgr, bus), bus, sched)
    return ctl, repo, mgr, board, repo.list_banks()[0]


def start(ctl, bank, **kw):
    kw.setdefault("shuffle", False)
    act = ctl.start_journey(bank.id, None, None, JourneySettings(team_name="فريق الهدى", **kw))
    act.start()
    return act


def test_sample_bank_is_arabic_choice(game):
    _, repo, _, _, bank = game
    qs = repo.list_questions(bank.id)
    assert len(qs) == 10 and all(q.qtype == "single_choice" and q.prompt.get("ar") and len(q.options) == 4 for q in qs)
    assert all("en" not in q.prompt for q in qs)


def test_buttons_armed_on_the_map_board(game):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank)
    assert act.buttons_target() == "map"
    assert board.armed and board.question_id == "J001" and board.allowed == ["A", "B", "C", "D"]
    assert board.button_leds == [True] * 4


def test_correct_answer_moves_one_green_step(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank)
    assert board.press("A")  # جاكرتا
    assert act.step == 1 and act.state == JourneyState.FEEDBACK
    cmd = board.history[-1]
    assert cmd["command"] == "path_advance" and (cmd["from"], cmd["to"]) == (0, 1)
    assert not board.armed  # one press per question
    row = repo.session_responses(ctl.session_id)[0]
    assert (row["answer"], row["outcome"], row["device_id"]) == ("A", "correct", "JOURNEY_01")
    sched.advance(4.0)
    assert act.current.code == "J002" and board.armed


def test_wrong_answer_steps_back_red(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank)
    board.press("A")
    sched.advance(4.0)
    board.press("A")  # J002 answer is B
    assert act.step == 0 and act.last_step_back
    cmd = board.history[-1]
    assert cmd["command"] == "path_back" and (cmd["from"], cmd["to"]) == (1, 0)
    sched.advance(4.0)
    assert act.current.code == "J003"  # default: next question


def test_wrong_at_start_flashes_red_without_moving(game):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank)
    board.press("D")
    assert act.step == 0 and board.history[-1]["command"] == "path_fail"


def test_double_press_and_stale_press_ignored(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank)
    board.press("A")
    from edukit.hardware.models import InputEvent

    act.handle_input(InputEvent("JOURNEY_01", "map", "answer_selected", {"question_id": "J001", "selected_answer": "B"}))
    assert act.step == 1 and len(repo.session_responses(ctl.session_id)) == 1
    sched.advance(4.0)
    act.handle_input(InputEvent("JOURNEY_01", "map", "answer_selected", {"question_id": "J001", "selected_answer": "A"}))
    assert act.state == JourneyState.ASKING and act.ignored_events >= 2


def test_reach_makkah_with_buttons(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank, steps_to_makkah=3)
    answers = {q.code: q.correct[0] for q in repo.list_questions(bank.id)}
    for _ in range(3):
        board.press(answers[act.current.code])
        sched.advance(4.0)
    assert act.state == JourneyState.ARRIVED and board.history[-1]["command"] == "festival" and not board.armed


def test_screen_answer_and_separate_quiz_box(sched, bus):
    """No buttons on the map -> a separate 4-button box (INPUT_01) is used; screen clicks work too."""
    mapd = SimulatedMapDevice("MAP_01")
    box = SimulatedInputDevice("INPUT_01", clock=sched.now)
    mgr = DeviceManager(bus, [SimulationDiscovery([mapd, box])], clock=sched.now)
    mgr.scan()
    repo = Repository(":memory:")
    seed_journey_mcq(repo, MCQ)
    ctl = SessionController(repo, mgr, FeedbackEngine(mgr, bus), bus, sched)
    act = start(ctl, repo.list_banks()[0])
    assert act.buttons_target() == "input" and box.armed
    box.press("A")
    assert act.step == 1
    sched.advance(4.0)
    assert act.submit_from_ui("B") and act.step == 2


def test_board_restart_rearms_buttons(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank)
    board.unplug()
    board.armed = False
    board.plug_in()
    sched.advance(3.1)
    mgr.poll()
    assert board.armed and board.question_id == act.current.code


def test_route_back_animation_is_red():
    r = RouteRenderer(RouteConfig(num_leds=61, steps=6, brightness=255))
    r.path_back(2, 1, 0, 1000)
    px = r.frame(0)
    assert px[15] == FAIL  # lost segment between station 1 (led 10) and 2 (led 20) blinks red
    r.frame(1100)
    assert r.state.mode == "path" and r.state.step == 1


def test_speech_phrase_selection():
    pytest.importorskip("PySide6")
    from edukit.ui.speech import pick_phrase, speech_settings

    s = speech_settings({"correct": ["أحسنت"], "bogus": 1})
    assert pick_phrase(s, "correct") == "أحسنت" and "bogus" not in s
    assert pick_phrase(s, "arrival").startswith("مبارك")


def test_touch_configuration_and_readings(game, bus):
    ctl, repo, mgr, board, bank = game
    from edukit.core.events import DEVICE_INPUT

    got = []
    bus.subscribe(DEVICE_INPUT, got.append)
    assert mgr.send("map", "configure", input_type="touch", touch_sensitivity=25).status == "acked"
    assert mgr.send("map", "calibrate").status == "acked"
    assert mgr.send("map", "read_touch").status == "acked"
    r = [e for e in got if e.event == "touch_readings"][-1]
    assert r.data["input_type"] == "touch" and r.data["sensitivity"] == 25 and len(r.data["values"]) == 4
    act = start(ctl, bank)
    act.handle_input(r)  # diagnostics never count as an answer
    assert act.state == JourneyState.ASKING and act.step == 0


def test_lose_when_question_limit_is_used_up(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank, steps_to_makkah=6, max_questions=3)
    assert act.snapshot()["questions_left"] == 3
    board.press("A")          # J001 correct -> step 1
    sched.advance(4.0)
    board.press("A")          # J002 wrong -> back to 0
    sched.advance(4.0)
    board.press("A")          # J003 wrong (answer C) -> limit reached
    assert act.state == JourneyState.FEEDBACK
    sched.advance(4.0)
    assert act.state == JourneyState.LOST and not board.armed
    assert board.history[-1]["command"] == "path_fail"
    assert repo.list_sessions()[0]["ended_at"]


def test_win_on_the_last_allowed_question_is_a_win(game, sched):
    ctl, repo, mgr, board, bank = game
    act = start(ctl, bank, steps_to_makkah=1, max_questions=1)
    board.press("A")
    sched.advance(4.0)
    assert act.state == JourneyState.ARRIVED
