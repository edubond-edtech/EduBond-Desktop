"""DB v3: curriculum tree, student details, migration from an older database."""
import sqlite3

import pytest

from conftest import REPO_ROOT
from edukit.core.models import Option, Question, Student
from edukit.data.repository import Repository
from edukit.data.seed import seed_demo, seed_journey_mcq


def test_tree_and_paths():
    r = Repository(":memory:")
    lid = r.ensure_lesson("منهج ٢٠٢٦", "العلوم", "الوحدة الأولى: الماء", "الدرس ١: حالات الماء")
    assert r.ensure_lesson("منهج ٢٠٢٦", "العلوم", "الوحدة الأولى: الماء", "الدرس ١: حالات الماء") == lid  # idempotent
    r.ensure_lesson("منهج ٢٠٢٦", "العلوم", "الوحدة الأولى: الماء", "الدرس ٢")
    # same lesson name in another unit is allowed (old UNIQUE(name, subject, grade) is gone)
    r.ensure_lesson("منهج ٢٠٢٦", "العلوم", "الوحدة الثانية", "الدرس ٢")
    tree = r.curriculum_tree()
    sci = tree[0]["subjects"][0]
    assert tree[0]["name"] == "منهج ٢٠٢٦" and sci["name"] == "العلوم"
    assert [u["name"] for u in sci["units"]] == ["الوحدة الأولى: الماء", "الوحدة الثانية"]
    assert r.lesson_path(lid) == "منهج ٢٠٢٦ › العلوم › الوحدة الأولى: الماء › الدرس ١: حالات الماء"
    q = Question("Q1", {"ar": "؟"}, [Option("A", {"ar": "١"}), Option("B", {"ar": "٢"})], ["A"], bank_id=lid)
    r.add_question(q)
    uid = sci["units"][0]["id"]
    assert len(r.unit_questions(uid)) == 1
    r.delete_node("unit", uid)  # cascades to lessons and questions
    assert r.get_question(q.id) is None


def test_student_details_and_unique_id():
    r = Repository(":memory:")
    cid = r.get_or_create_class("الصف الرابع - أ", "الرابع")
    s = r.add_student(Student("أحمد علي", cid, "", None, "2016-03-01", "1234567890", "2026/2027"))
    got = r.find_student_by_national_id("1234567890")
    assert got.id == s.id and got.birth_date == "2016-03-01" and got.school_year == "2026/2027"
    with pytest.raises(sqlite3.IntegrityError):
        r.add_student(Student("آخر", cid, national_id="1234567890"))
    r.add_student(Student("بدون هوية 1", cid))
    r.add_student(Student("بدون هوية 2", cid))  # empty ids may repeat
    assert r.get_or_create_class("الصف الرابع - أ") == cid


def test_migrates_a_v2_database(tmp_path):
    """Build a real v2 database with data, open it with the new code, nothing is lost."""
    db = tmp_path / "old.sqlite3"
    schema_v2 = (REPO_ROOT / "desktop" / "edukit" / "data" / "schema.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(db)
    con.executescript(schema_v2)
    con.execute("INSERT INTO question_banks(name, subject, grade) VALUES('بنك قديم', 'الرياضيات', 'الثالث')")
    con.execute("INSERT INTO questions(bank_id, code, prompt_json, options_json, correct_json) VALUES(1, 'Q1', '{\"ar\":\"؟\"}', '[{\"key\":\"A\",\"text\":{\"ar\":\"x\"}},{\"key\":\"B\",\"text\":{\"ar\":\"y\"}}]', '[\"A\"]')")
    con.execute("INSERT INTO classes(name) VALUES('3A')")
    con.execute("INSERT INTO students(name, class_id) VALUES('سارة', 1)")
    con.execute("INSERT INTO sessions(activity_type, bank_id, team_name) VALUES('journey', 1, 'فريق')")
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()
    r = Repository(db)
    assert r._rows("PRAGMA user_version")[0][0] == 4
    assert r.list_students()[0].name == "سارة" and r.list_students()[0].national_id == ""
    bank = r.list_banks()[0]
    assert bank.name == "بنك قديم" and bank.unit_id is not None
    assert r.lesson_path(bank.id) == "المنهج العام › الرياضيات › عام › بنك قديم"
    assert len(r.list_questions(bank.id)) == 1
    assert r.list_sessions()[0]["bank_name"] == "بنك قديم"


def test_sample_lessons_are_placed_in_the_tree():
    r = Repository(":memory:")
    seed_demo(r, REPO_ROOT / "sample_data" / "questions.json")
    seed_journey_mcq(r, REPO_ROOT / "sample_data" / "journey_mcq_ar.json")
    r.assign_unplaced_lessons()
    paths = sorted(r.lesson_path(b.id) for b in r.list_banks())
    assert "المنهج التجريبي › اللغة العربية والتربية الإسلامية › رحلة إلى مكة › رحلة إلى مكة — أسئلة الاختيار" in paths
    assert all(paths)


def test_indonesian_grade1_arabic_set():
    from edukit.data.seed import seed_indonesia_g1

    r = Repository(":memory:")
    assert seed_indonesia_g1(r, REPO_ROOT / "sample_data" / "indonesia_g1_arabic.json")
    assert not seed_indonesia_g1(r, REPO_ROOT / "sample_data" / "indonesia_g1_arabic.json")  # once only
    tree = r.curriculum_tree()
    subj = tree[0]["subjects"][0]
    assert "الصف الأول" in subj["name"] and len(subj["units"]) == 6
    qs = [q for u in subj["units"] for q in r.unit_questions(u["id"])]
    assert len(qs) == 30 and all(q.qtype == "single_choice" and len(q.options) == 4 for q in qs)
    assert len({q.code for q in qs}) == 30


def test_upgrade_old_indonesian_set_to_arabic_only(tmp_path):
    import json
    import re

    from edukit.data.seed import seed_indonesia_g1, upgrade_indonesia_g1_arabic_only

    # simulate an installation that has the old (Arabic + Indonesian) set with a student answer
    new_file = REPO_ROOT / "sample_data" / "indonesia_g1_arabic.json"
    old = json.loads(new_file.read_text(encoding="utf-8"))
    old["curriculum"] = "المنهج الإندونيسي — Kurikulum MI/Ma'had"
    old["subject"] = "اللغة العربية — الصف الأول (Bahasa Arab Kelas 1)"
    for u in old["units"]:
        u["name"] += " (Indonesia)"
        u["lesson"] += " (Latihan)"
        for q in u["questions"]:
            q["prompt"]["ar"] = "Bahasa Arabnya … " + q["prompt"]["ar"]
    old_file = tmp_path / "old.json"
    old_file.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    r = Repository(":memory:")
    seed_indonesia_g1(r, old_file)
    q1 = next(q for b in r.list_banks() for q in r.list_questions(b.id) if q.code == "ID1-01")
    sid = r.start_session("journey", q1.bank_id, None, None, {}, "ble")
    r.add_response(sid, None, q1, "A", "correct", 1, 1, 800, "device", "JOURNEY_01")
    assert upgrade_indonesia_g1_arabic_only(r, new_file) == 30
    assert upgrade_indonesia_g1_arabic_only(r, new_file) == 0  # only once
    qs = [q for b in r.list_banks() for q in r.list_questions(b.id) if q.code.startswith("ID1-")]
    assert len(qs) == 30
    texts = [t for q in qs for t in [q.text("ar"), *[o.label("ar") for o in q.options]]]
    assert not any(re.search(r"[A-Za-z]", t) for t in texts)
    tree = r.curriculum_tree()
    names = [tree[0]["name"], tree[0]["subjects"][0]["name"]] + [u["name"] for u in tree[0]["subjects"][0]["units"]]
    assert not any(re.search(r"[A-Za-z]", n) for n in names) and tree[0]["name"] == "المنهج الإندونيسي"
    assert r.session_responses(sid)[0]["question_id"] == q1.id  # past answers stay linked
