import csv

import pytest

from conftest import REPO_ROOT
from edukit.core.models import Option, Question, QuestionBank, SchoolClass, Student
from edukit.data import reports
from edukit.data.repository import Repository
from edukit.data.seed import export_bank, import_bank, seed_demo


@pytest.fixture
def repo():
    r = Repository(":memory:")
    seed_demo(r, REPO_ROOT / "sample_data" / "questions.json")
    return r


def mkq(bank_id, **kw):
    d = dict(code="X1", prompt={"en": "2+2?", "ar": "٢+٢؟"}, options=[Option("A", {"en": "4"}), Option("B", {"en": "5"})], correct=["A"], bank_id=bank_id)
    d.update(kw)
    return Question(**d)


def test_seed_is_idempotent(repo):
    assert not seed_demo(repo, REPO_ROOT / "sample_data" / "questions.json")
    assert len(repo.list_banks()) == 1 and len(repo.list_students()) == 6


def test_question_crud_and_validation(repo):
    bank = repo.add_bank(QuestionBank("Bank 2", "Math", "Grade 1"))
    q = repo.add_question(mkq(bank.id))
    q.prompt["en"] = "Two plus two?"
    q.correct = ["B"]
    repo.update_question(q)
    got = repo.get_question(q.id)
    assert got.prompt["en"] == "Two plus two?" and got.correct == ["B"] and got.prompt["ar"] == "٢+٢؟"
    with pytest.raises(ValueError):
        repo.add_question(mkq(bank.id, code="X2", correct=["Z"]))
    with pytest.raises(ValueError):
        repo.add_question(mkq(bank.id, code="X3", options=[Option("A", {"en": "4"})]))
    with pytest.raises(ValueError):
        repo.add_question(mkq(bank.id, code="X4", correct=["A", "B"]))
    repo.delete_question(q.id)
    assert repo.list_questions(bank.id) == []
    assert repo.next_question_code(bank.id) == "Q001"


def test_deleting_bank_cascades(repo):
    bank = repo.list_banks()[0]
    repo.delete_bank(bank.id)
    assert repo.list_questions(bank.id) == []


def test_classes_and_students(repo):
    c = repo.add_class(SchoolClass("4B", "Grade 4"))
    s = repo.add_student(Student("Huda", c.id, "S100"))
    assert [x.name for x in repo.list_students(c.id)] == ["Huda"]
    repo.delete_class(c.id)
    assert repo.get_student(s.id).class_id is None  # ON DELETE SET NULL


def test_bank_export_import_roundtrip(repo, tmp_path):
    bank = repo.list_banks()[0]
    p = tmp_path / "bank.json"
    export_bank(repo, bank.id, p)
    other = Repository(":memory:")
    b2 = import_bank(other, p)
    assert [q.to_dict() for q in other.list_questions(b2.id)] == [q.to_dict() for q in repo.list_questions(bank.id)]


def test_reports(repo, tmp_path):
    bank = repo.list_banks()[0]
    st = repo.list_students()[0]
    sid = repo.start_session("mcq", bank.id, st.class_id, st.id, {}, "simulation")
    q = repo.list_questions(bank.id)[0]
    repo.add_response(sid, st.id, q, "C", "correct", 1, 1, 1200, "device", "INPUT_01")
    repo.finish_session(sid, 1, 1)
    n = reports.export_responses_csv(repo, tmp_path / "r.csv")
    assert n == 1
    rows = list(csv.DictReader(open(tmp_path / "r.csv", encoding="utf-8-sig")))
    assert rows[0]["student_name"] == st.name and rows[0]["outcome"] == "correct"
    assert reports.export_summary_csv(repo, tmp_path / "s.csv") == 6
    reports.export_html_report(repo, tmp_path / "r.html")
    assert st.name in (tmp_path / "r.html").read_text(encoding="utf-8")
