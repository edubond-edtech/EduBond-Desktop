"""End-to-end classroom flow: simulated buttons -> PC evaluation -> LED feedback -> database."""
import pytest

from conftest import REPO_ROOT
from edukit.activities.quiz import QuizSettings, QuizState
from edukit.core.session import SessionController
from edukit.data.repository import Repository
from edukit.data.seed import seed_demo
from edukit.feedback.engine import FeedbackEngine


@pytest.fixture
def classroom(sim, sched, bus):
    mgr, inp, out, disc = sim
    repo = Repository(":memory:")
    seed_demo(repo, REPO_ROOT / "sample_data" / "questions.json")
    fb = FeedbackEngine(mgr, bus, lambda: repo.get_setting("effect_profile", {}))
    ctl = SessionController(repo, mgr, fb, bus, sched)
    bank = repo.list_banks()[0]
    student = repo.list_students()[0]
    return ctl, repo, mgr, inp, out, bank, student


def start(ctl, bank, student, **settings):
    act = ctl.start_quiz(bank.id, student.id, student.class_id, QuizSettings(**settings))
    act.start()
    return act


def test_ten_sample_questions_loaded(classroom):
    _, repo, *_, bank, _ = classroom
    qs = repo.list_questions(bank.id)
    assert len(qs) == 10 and qs[0].code == "Q001" and qs[0].correct == ["C"]
    assert qs[0].prompt["ar"]


def test_correct_answer_turns_strip_green_and_scores(classroom, sched):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student)
    assert act.state == QuizState.ASKING
    assert inp.armed and inp.question_id == "Q001"
    assert out.history[-1]["effect"] == "breathe" and out.history[-1]["color"] == "blue"  # waiting

    inp.press("C")  # 5 + 3 = 8
    assert act.state == QuizState.FEEDBACK
    assert act.score == 1
    fx = out.history[-1]
    assert fx["command"] == "play_effect" and fx["color"] == "green" and fx["duration_ms"] == 3000
    assert any(b["pattern"] == "correct" for b in out.buzzes)
    assert not inp.armed  # disarmed while showing feedback

    sched.advance(3.0)  # auto-advance after feedback_seconds
    assert act.state == QuizState.ASKING and act.current.code == "Q002"
    assert inp.question_id == "Q002"


def test_wrong_answer_turns_strip_red(classroom):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student)
    inp.press("A")
    assert act.score == 0 and out.history[-1]["color"] == "red"
    assert act.last_result.outcome.value == "incorrect"


def test_duplicate_and_stale_presses_are_ignored(classroom, sched):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student, auto_advance=False)
    inp.press("C")
    # device already locked; force a press through as if a second device/glitch sent it
    act.submit("A", source="device", device_id="INPUT_01")
    assert act.score == 1 and len(repo.session_responses(ctl.session_id)) == 1
    # stale event referencing the old question after moving on
    act.next()
    from edukit.hardware.models import InputEvent

    act.handle_input(InputEvent("INPUT_01", "input", "answer_selected", {"question_id": "Q001", "selected_answer": "C"}))
    assert act.current.code == "Q002" and act.state == QuizState.ASKING
    assert act.ignored_events >= 1


def test_timeout_records_and_shows_orange(classroom, sched):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student)
    sched.advance(20.0)  # Q001 has a 20 s limit
    assert act.last_result.outcome.value == "timeout"
    assert out.history[-1]["color"] == "orange"
    rows = repo.session_responses(ctl.session_id)
    assert rows[0]["outcome"] == "timeout" and rows[0]["answer"] is None


def test_full_quiz_records_everything_and_celebrates(classroom, sched):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student)
    answers = ["C", "A", "B", "B", "D", "A", "C", "D", "A", "A"]  # last one wrong
    for a in answers:
        sched.advance(0.5)
        assert inp.press(a)
        sched.advance(3.0)
    assert act.state == QuizState.FINISHED
    assert act.score == 9 and act.max_score == 10
    assert out.history[-1]["effect"] == "celebrate"
    sess = repo.list_sessions()[0]
    assert sess["ended_at"] and sess["total_score"] == 9 and sess["correct"] == 9 and sess["answered"] == 10
    perf = {p["student_name"]: p for p in repo.student_performance()}
    assert perf[student.name]["percent"] == 90.0
    rows = repo.session_responses(ctl.session_id)
    assert all(r["device_id"] == "INPUT_01" and r["source"] == "device" for r in rows)
    assert rows[0]["response_ms"] == 500


def test_quiz_runs_without_any_hardware(sched, bus):
    """Disconnected devices must never break the lesson: on-screen answers still work."""
    from edukit.hardware.manager import DeviceManager

    repo = Repository(":memory:")
    seed_demo(repo, REPO_ROOT / "sample_data" / "questions.json")
    mgr = DeviceManager(bus, [], clock=sched.now)
    ctl = SessionController(repo, mgr, FeedbackEngine(mgr, bus), bus, sched)
    act = ctl.start_quiz(repo.list_banks()[0].id, None, None, QuizSettings())
    act.start()
    assert act.submit_from_ui("C")
    assert act.score == 1


def test_input_reconnect_mid_question_rearms(classroom, sched):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student)
    inp.unplug()
    inp.armed = False  # a rebooted ESP32 loses its armed state
    inp.plug_in()
    sched.advance(3.1)
    mgr.poll()  # rescan -> reconnect -> status ONLINE -> activity re-arms
    assert inp.armed and inp.question_id == "Q001"
    inp.press("C")
    assert act.score == 1


def test_custom_effect_profile_is_used(classroom):
    ctl, repo, mgr, inp, out, bank, student = classroom
    repo.set_setting("effect_profile", {"correct": {"led": {"effect": "rainbow", "brightness": 50, "duration_ms": 1000}}})
    act = start(ctl, bank, student)
    inp.press("C")
    assert out.history[-1]["effect"] == "rainbow"


def test_manual_advance_and_stop(classroom):
    ctl, repo, mgr, inp, out, bank, student = classroom
    act = start(ctl, bank, student, auto_advance=False, max_questions=2)
    inp.press("C")
    act.next()
    assert act.current.code == "Q002"
    ctl.stop()
    assert act.state == QuizState.STOPPED
    assert out.history[-1]["effect"] == "off"
