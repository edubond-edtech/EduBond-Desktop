"""Game 1 «رحلة إلى مكة»: resistor plates -> puzzle board -> PC -> LED route map."""
import pytest

from conftest import REPO_ROOT
from edukit.activities.journey import JourneySettings, JourneyState
from edukit.core.events import DEVICE_INPUT
from edukit.core.models import Option, Question, QuestionBank
from edukit.core.session import SessionController
from edukit.data.repository import Repository
from edukit.data.seed import seed_journey
from edukit.evaluation.evaluator import evaluate
from edukit.feedback.engine import FeedbackEngine
from edukit.feedback.route import GOLD, RouteConfig, RouteRenderer
from edukit.hardware.manager import DeviceManager
from edukit.hardware.simulator import SimulatedMapDevice, SimulatedPuzzleBoard, SimulationDiscovery

SAMPLE = REPO_ROOT / "sample_data" / "journey_arrange_ar.json"


@pytest.fixture
def game(sched, bus):
    board = SimulatedPuzzleBoard("PUZZLE_01", clock=sched.now)
    mapd = SimulatedMapDevice("MAP_01")
    mgr = DeviceManager(bus, [SimulationDiscovery([board, mapd])], clock=sched.now)
    mgr.scan()
    repo = Repository(":memory:")
    seed_journey(repo, SAMPLE)
    ctl = SessionController(repo, mgr, FeedbackEngine(mgr, bus), bus, sched)
    bank = repo.list_banks()[0]
    return ctl, repo, mgr, board, mapd, bank


def start(ctl, bank, **kw):
    kw.setdefault("shuffle", False)
    kw.setdefault("on_wrong", "retry")  # plate-version behaviour
    kw.setdefault("step_back_on_wrong", False)
    kw.setdefault("manual_next_cards", False)  # these tests use the timed auto-advance
    act = ctl.start_journey(bank.id, None, None, JourneySettings(team_name="فريق النور", **kw))
    act.start()
    return act


def test_sample_bank_is_arabic_arrange(game):
    _, repo, *_, bank = game
    qs = repo.list_questions(bank.id)
    assert len(qs) == 10 and all(q.qtype == "arrange" for q in qs)
    q = qs[0]
    words = {o.key: o.text["ar"] for o in q.options}
    assert " ".join(words[k] for k in q.correct) == "سافر الحجاج من إندونيسيا إلى مكة"
    assert all(q.correct == [str(i + 1) for i in range(len(q.correct))] for q in qs)  # fixed firmware key


def test_arrange_evaluator():
    q = Question("X", {"ar": "؟"}, [Option(k, {"ar": k}) for k in "123"], ["2", "3", "1"], qtype="arrange")
    assert evaluate(q, ["2", "3", "1"]).is_correct
    r = evaluate(q, "2,1,3")
    assert not r.is_correct and r.detail["in_place"] == 1
    assert not evaluate(q, ["2", "3"]).is_correct  # incomplete


def test_correct_arrangement_moves_map_one_station(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    q = act.current
    assert board.armed and board.question_id == q.code and board.expected == q.correct
    arm = [m for m in board.received if m.get("command") == "arm"][-1]
    assert "expected" not in arm and arm["sockets"] == len(q.correct)  # key lives in the firmware
    assert mapd.history[0]["command"] == "configure" and mapd.history[0]["steps"] == 6
    assert mapd.history[-1] == {**mapd.history[-1], "command": "path_set", "step": 0}

    for s, plate in enumerate(q.correct[:-1]):
        board.insert(s, plate)
    assert act.state == JourneyState.ASKING and act.board[0] == int(q.correct[0])  # live board view
    board.insert(len(q.correct) - 1, q.correct[-1])
    assert not board.results  # nothing is judged until SEND
    board.submit()  # SEND button -> firmware verdict
    assert board.results[-1]["result"] == "win"
    assert act.state == JourneyState.FEEDBACK and act.step == 1
    adv = mapd.history[-1]
    assert adv["command"] == "path_advance" and adv["from"] == 0 and adv["to"] == 1
    rows = repo.session_responses(ctl.session_id)
    assert rows[0]["outcome"] == "correct" and rows[0]["answer"] == ",".join(q.correct) and rows[0]["device_id"] == "PUZZLE_01"


def test_wrong_arrangement_flashes_red_and_retries_same_sentence(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    q = act.current
    wrong = list(reversed(q.correct))
    board.place_all(wrong)
    assert board.results[-1]["result"] == "fail"
    assert act.step == 0 and act.last_result.outcome.value == "incorrect"
    assert mapd.history[-1]["command"] == "path_fail"
    sched.advance(4.0)
    assert act.state == JourneyState.ASKING and act.current.code == q.code and act.attempts == 1
    # students pull the plates out and re-insert them in a new order (board stays armed)
    board.clear()
    board.place_all(q.correct)
    assert act.step == 1 and act.attempts == 2


def test_send_during_feedback_is_ignored_then_resent(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    q = act.current
    board.place_all(list(reversed(q.correct)))
    assert act.state == JourneyState.FEEDBACK and not board.armed
    board.clear()
    board.place_all(q.correct)  # SEND pressed while the red feedback still shows: board is not armed
    assert act.step == 0 and len(board.results) == 1
    sched.advance(4.0)  # the PC re-arms the same sentence
    assert board.armed
    assert board.submit()  # pressing SEND again now counts
    assert act.step == 1


def test_cards_are_judged_only_when_send_is_pressed(game):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    board.place_all(act.current.correct, submit=False)
    assert act.state == JourneyState.ASKING and not board.results
    assert board.submit()
    assert act.step == 1


def test_send_with_missing_card_is_not_judged(game):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    board.place_all(act.current.correct[:-1])
    assert act.state == JourneyState.ASKING and not board.results and board.armed


def test_card_in_an_extra_socket_is_wrong(game):
    ctl, repo, mgr, board, mapd, bank = game
    short = next(q for q in repo.list_questions(bank.id) if len(q.correct) < 6)  # e.g. a 4-word sentence
    act = ctl.start_journey(bank.id, None, None, JourneySettings(shuffle=False, on_wrong="retry", manual_next_cards=False), questions=[short])
    act.start()
    n = len(short.correct)
    assert board.n == n
    board.insert(n, 6)  # a card where no word belongs
    board.place_all(short.correct)
    assert board.results[-1]["result"] == "fail" and board.results[-1]["extra_cards"]
    assert act.step == 0 and act.last_result.outcome.value == "incorrect"
    board.insert(n, None)  # take the extra card out and send again after the re-arm


def test_new_sentence_requires_clearing_the_board(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    board.place_all(act.current.correct)
    sched.advance(4.0)
    assert act.current.code == "Q102"
    assert act.board_state == "clear_required"
    board.place_all(act.current.correct)  # old plates still in -> must not count
    assert act.step == 1
    board.clear()
    assert act.board_state == "ready"
    board.place_all(act.current.correct)
    assert act.step == 2


def test_reaching_makkah_starts_festival_and_finishes_session(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank, steps_to_makkah=3)
    for _ in range(3):
        board.clear()
        board.place_all(act.current.correct)
        sched.advance(4.0)
    assert act.state == JourneyState.ARRIVED and act.step == 3
    assert mapd.history[-1]["command"] == "festival"
    assert not board.armed
    sess = repo.list_sessions()[0]
    assert sess["ended_at"] and sess["team_name"] == "فريق النور" and sess["activity_type"] == "journey"


def test_step_back_option_and_next_mode(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank, step_back_on_wrong=True, on_wrong="next")
    board.place_all(act.current.correct)
    sched.advance(4.0)
    board.clear()
    board.place_all(list(reversed(act.current.correct)))
    assert act.step == 0
    assert mapd.history[-1]["command"] == "path_back" and mapd.history[-1]["to"] == 0
    sched.advance(4.0)
    assert act.current.code == "Q103"  # moved on


def test_pc_overrides_wrong_firmware_verdict(game):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    board.expected = list(reversed(board.expected))  # board armed with a different order
    board.place_all(act.current.correct)
    assert board.results[-1]["result"] == "fail"
    assert act.step == 1 and act.firmware_mismatches == 1


def test_stale_result_and_wrong_role_ignored(game, bus):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    from edukit.hardware.models import InputEvent

    act.handle_input(InputEvent("PUZZLE_01", "puzzle", "puzzle_result", {"question_id": "Q999", "placed": [1], "result": "win"}))
    act.handle_input(InputEvent("INPUT_01", "input", "answer_selected", {"question_id": "Q101", "selected_answer": "A"}))
    assert act.step == 0 and act.ignored_events == 2


def test_runs_without_board_using_screen_entry(sched, bus):
    repo = Repository(":memory:")
    seed_journey(repo, SAMPLE)
    mgr = DeviceManager(bus, [], clock=sched.now)
    ctl = SessionController(repo, mgr, FeedbackEngine(mgr, bus), bus, sched)
    act = ctl.start_journey(repo.list_banks()[0].id, None, None, JourneySettings(shuffle=False))
    act.start()
    assert act.submit_from_ui(act.current.correct)
    assert act.step == 1


def test_puzzle_reconnect_rearms(game, sched):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    board.unplug()
    board.armed = False
    board.plug_in()
    sched.advance(3.1)
    mgr.poll()
    assert board.armed and board.question_id == act.current.code


def test_repository_validates_arrange_questions(game):
    _, repo, *_ = game
    b = repo.add_bank(QuestionBank("t"))
    ok = Question("A1", {"ar": "رتب"}, [Option("1", {"ar": "رب"}), Option("2", {"ar": "زدني"})], ["1", "2"], qtype="arrange", bank_id=b.id)
    repo.add_question(ok)
    with pytest.raises(ValueError):  # word 1 must be on plate 1
        repo.add_question(Question("A0", {"ar": "رتب"}, [Option("1", {"ar": "زدني"}), Option("2", {"ar": "رب"})], ["2", "1"], qtype="arrange", bank_id=b.id))
    with pytest.raises(ValueError):
        repo.add_question(Question("A2", {"ar": "رتب"}, [Option("2", {"ar": "x"}), Option("7", {"ar": "y"})], ["2", "7"], qtype="arrange", bank_id=b.id))
    with pytest.raises(ValueError):
        repo.add_question(Question("A3", {"ar": "رتب"}, [Option("1", {"ar": "x"}), Option("2", {"ar": "y"})], ["1"], qtype="arrange", bank_id=b.id))


def test_route_renderer_positions_and_festival():
    r = RouteRenderer(RouteConfig(num_leds=61, steps=6))
    assert [r.cfg.pos(k) for k in range(7)] == [0, 10, 20, 30, 40, 50, 60]
    r.cfg.brightness = 255
    r.path_set(2, 0)
    px = r.frame(0)
    assert px[10] == GOLD and px[30] != GOLD  # passed vs future station
    r.path_advance(2, 3, 0, 1000)
    r.frame(500)
    r.frame(1200)
    assert r.state.mode == "path" and r.state.step == 3
    r.festival(0, 2000)
    assert len(r.frame(100)) == 61
    r.cfg.waypoints = [0, 5, 9, 20, 33, 47, 60]
    assert r.cfg.pos(3) == 20


def test_firmware_key_and_resistors_match_pc():
    import re

    from edukit.hardware.plates import PLATE_RESISTORS, classify_mv, expected_mv

    src = (REPO_ROOT / "firmware" / "puzzle_controller" / "src" / "main.cpp").read_text()
    res = [int(x) for x in re.search(r"PLATE_RES_OHM\[NUM_PLATES\] = \{([^}]*)\}", src).group(1).split(",")]
    key = [int(x) for x in re.search(r"EXPECTED_PLATE\[NUM_SOCKETS\] = \{([^}]*)\}", src).group(1).split(",")]
    assert res == [PLATE_RESISTORS[p] for p in range(1, 7)]
    assert key == [1, 2, 3, 4, 5, 6]
    mvs = sorted(expected_mv(p) for p in range(1, 7))
    assert min(b - a for a, b in zip(mvs, mvs[1:])) >= 300  # well separated for the ESP32 ADC
    assert all(classify_mv(expected_mv(p) + 90) == p for p in range(1, 7))
    assert classify_mv(40) == 0 and classify_mv(3000) is None


def test_projector_never_shows_words_in_answer_order():
    pytest.importorskip("PySide6")
    from edukit.ui.journey_view import display_order

    for code in [f"Q{i:03d}" for i in range(200)]:
        for n in range(2, 7):
            order = display_order(code, list(range(1, n + 1)))
            assert sorted(order) == list(range(1, n + 1)) and order != sorted(order)


def test_incomplete_send_shows_missing_places(game):
    ctl, repo, mgr, board, mapd, bank = game
    act = start(ctl, bank)
    board.place_all(act.current.correct[:-1])
    assert act.board_state == "incomplete" and act.missing == [len(act.current.correct)]
    board.insert(len(act.current.correct) - 1, act.current.correct[-1])
    assert act.board_state == "ready"
    board.submit()
    assert act.step == 1


def test_card_sentence_waits_for_next_button(game, sched):
    ctl, repo, mgr, board, strip, bank = game
    act = start(ctl, bank, manual_next_cards=True, on_wrong="next")
    first = act.current.code
    board.place_all(board.expected)
    assert act.state == JourneyState.FEEDBACK and act.step == 1 and act.waiting_next
    sched.advance(60.0)  # no auto-advance: the class takes the cards out
    assert act.state == JourneyState.FEEDBACK and act.current.code == first
    assert act.snapshot()["waiting_next"]
    board.clear()
    assert act.proceed()
    assert act.state == JourneyState.ASKING and act.current.code != first and not act.waiting_next
    assert not act.proceed()  # only once per judgement


def test_next_button_retries_after_wrong_order(game, sched):
    ctl, repo, mgr, board, strip, bank = game
    act = start(ctl, bank, manual_next_cards=True, on_wrong="retry")
    first = act.current.code
    board.place_all(list(reversed(board.expected)))
    assert act.state == JourneyState.FEEDBACK and act.waiting_next
    sched.advance(30.0)
    assert act.state == JourneyState.FEEDBACK
    assert act.proceed()
    assert act.state == JourneyState.ASKING and act.current.code == first and board.armed
