"""Teams inside classes and the per-student report over a date range."""
from datetime import date, timedelta

import pytest

from edukit.core.models import Option, Question, Student
from edukit.data.repository import Repository


@pytest.fixture
def school():
    r = Repository(":memory:")
    c4 = r.get_or_create_class("4A")
    c5 = r.get_or_create_class("5B")
    a = r.add_student(Student("Ahmad", c4))
    b = r.add_student(Student("Budi", c4))
    c = r.add_student(Student("Citra", c4))
    d = r.add_student(Student("Dewi", c5))
    lesson = r.ensure_lesson("M", "Arabic", "U1", "L1")
    q = r.add_question(Question("Q1", {"ar": "?"}, [Option("A", {"ar": "1"}), Option("B", {"ar": "2"})], ["A"], bank_id=lesson))
    return r, (c4, c5), (a, b, c, d), lesson, q


def play(r, lesson, q, outcomes, **kw):
    sid = r.start_session("journey", lesson, kw.get("class_id"), kw.get("student_id"), {}, "ble", kw.get("team_name", ""), kw.get("team_id"))
    for o in outcomes:
        r.add_response(sid, kw.get("student_id"), q, "A", o, 1 if o == "correct" else 0, 1, 900, "device", "JOURNEY_01")
    r.finish_session(sid, outcomes.count("correct"), len(outcomes))
    return sid


def test_teams_crud(school):
    r, (c4, c5), (a, b, c, d), *_ = school
    tid = r.add_team(c4, "فريق النور", [a.id, b.id])
    t = r.get_team(tid)
    assert t["name"] == "فريق النور" and [m.name for m in t["members"]] == ["Ahmad", "Budi"] and t["class_name"] == "4A"
    r.update_team(tid, "النور", [b.id, c.id])
    assert [m.name for m in r.get_team(tid)["members"]] == ["Budi", "Citra"]
    with pytest.raises(ValueError):
        r.add_team(c4, " ", [])
    r.delete_student(c.id)
    assert [m.name for m in r.get_team(tid)["members"]] == ["Budi"]
    r.delete_class(c5)  # cascades teams of that class
    r.add_team(c4, "B", [])
    assert [t["name"] for t in r.list_teams(c4)] == ["B", "النور"]


def test_student_report_individual_team_and_class(school):
    r, (c4, c5), (a, b, c, d), lesson, q = school
    tid = r.add_team(c4, "T1", [a.id, b.id])
    play(r, lesson, q, ["correct", "incorrect"], student_id=a.id, class_id=c4)             # Ahmad alone
    play(r, lesson, q, ["correct", "correct", "correct"], team_id=tid, class_id=c4, team_name="T1")  # Ahmad + Budi
    play(r, lesson, q, ["incorrect"], class_id=c4)                                            # whole class 4A
    play(r, lesson, q, ["correct"], student_id=d.id, class_id=c5)                             # Dewi only
    rep = {x["student"].name: x for x in r.student_report()}
    assert rep["Ahmad"]["tests"] == 3 and [s["mode"] for s in rep["Ahmad"]["sessions"]] == ["individual", "team", "class"]
    assert rep["Budi"]["tests"] == 2 and rep["Citra"]["tests"] == 1 and rep["Dewi"]["tests"] == 1
    assert rep["Ahmad"]["correct"] == 4 and rep["Ahmad"]["answered"] == 6 and rep["Ahmad"]["percent"] == 66.7
    assert rep["Ahmad"]["sessions"][0]["lesson_path"] == "M › Arabic › U1 › L1"
    assert [x["student"].name for x in r.student_report(class_id=c5)] == ["Dewi"]
    assert len(r.student_report(student_id=b.id)) == 1


def test_student_report_date_range(school):
    r, (c4, _), (a, *_rest), lesson, q = school
    old = play(r, lesson, q, ["correct"], student_id=a.id)
    r._exec("UPDATE sessions SET started_at = datetime('now', '-40 days') WHERE id=?", (old,))
    play(r, lesson, q, ["correct"], student_id=a.id)
    today = date.today()
    recent = r.student_report(date_from=(today - timedelta(days=7)).isoformat(), date_to=today.isoformat(), student_id=a.id)[0]
    assert recent["tests"] == 1
    everything = r.student_report(student_id=a.id)[0]
    assert everything["tests"] == 2
    past = r.student_report(date_to=(today - timedelta(days=30)).isoformat(), student_id=a.id)[0]
    assert past["tests"] == 1
