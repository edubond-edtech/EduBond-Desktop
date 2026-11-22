"""Excel import/export of students and questions."""
import pytest

openpyxl = pytest.importorskip("openpyxl")

from edukit.core.models import Student  # noqa: E402
from edukit.data import excel_io as X  # noqa: E402
from edukit.data.repository import Repository  # noqa: E402


def make_xlsx(path, headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_students_template_imports_its_own_examples(tmp_path):
    r = Repository(":memory:")
    X.write_students_template(tmp_path / "t.xlsx")
    rep = X.import_students(r, tmp_path / "t.xlsx")
    assert (rep.added, rep.errors) == (2, [])
    s = r.find_student_by_national_id("1098765432")
    assert s.name == "فاطمة حسن" and s.birth_date == "2016-09-14" and s.school_year == "2026/2027"
    assert [c.name for c in r.list_classes()] == ["الصف الرابع - أ"]


def test_students_update_by_id_and_report_errors(tmp_path):
    from datetime import datetime

    r = Repository(":memory:")
    r.add_student(Student("قديم", national_id="555"))
    p = make_xlsx(tmp_path / "s.xlsx", ["اسم الطالب", "تاريخ الميلاد", "رقم الهوية", "العام الدراسي", "الفصل"], [
        ["اسم جديد", datetime(2015, 1, 2), "٥٥٥", "2026/2027", "5B"],   # Arabic digits -> same student, updated
        ["", "2015-01-01", "1", "", ""],                                 # no name
        ["خالد", "31/02/2015", "2", "", ""],                              # impossible date
        ["ليلى", "", "", "", "5B"],
    ])
    rep = X.import_students(r, p)
    assert (rep.added, rep.updated) == (1, 1)
    assert [row for row, _ in rep.errors] == [3, 4]
    assert r.find_student_by_national_id("555").name == "اسم جديد"
    assert r.find_student_by_national_id("555").birth_date == "2015-01-02"
    assert "الصف 4" in rep.summary_ar()


def test_parse_date_forms():
    assert X.parse_date("2016-3-1") == "2016-03-01"
    assert X.parse_date("01/03/2016") == "2016-03-01"
    assert X.parse_date("٠١/٠٣/٢٠١٦") == "2016-03-01"
    with pytest.raises(ValueError):
        X.parse_date("next year")


def test_questions_template_roundtrip(tmp_path):
    r = Repository(":memory:")
    lesson = r.ensure_lesson("م", "العربية", "الوحدة ١", "الدرس ١")
    X.write_questions_template(tmp_path / "q.xlsx")
    rep = X.import_questions(r, tmp_path / "q.xlsx", lesson, tmp_path / "imgs")
    assert rep.added == 4 and rep.errors == []
    assert len(rep.warnings) == 1  # jakarta.jpg is not next to the file
    qs = r.list_questions(lesson)
    assert [q.qtype for q in qs] == ["single_choice", "true_false", "arrange"]
    assert qs[0].correct == ["A"] and qs[1].correct == ["A"] and qs[1].option_keys == ["A", "B"]
    assert [o.label("ar") for o in qs[2].options] == "سافر الحجاج من إندونيسيا إلى مكة".split()
    # the 4th example row names its own lesson -> created in the tree
    sci = [b for b in r.list_banks() if b.name == "حالات الماء"][0]
    assert r.lesson_path(sci.id) == "منهج 2026 › العلوم › الوحدة الأولى: الماء › حالات الماء"
    assert r.list_questions(sci.id)[0].correct == ["B"]
    # export -> import into another lesson gives the same questions
    X.export_questions(r, lesson, tmp_path / "out.xlsx")
    other = r.ensure_lesson("م", "العربية", "الوحدة ١", "نسخة")
    X.import_questions(r, tmp_path / "out.xlsx", other, tmp_path / "imgs")
    strip = lambda q: (q.qtype, q.prompt, [(o.key, o.text) for o in q.options], q.correct)  # noqa: E731
    assert [strip(q) for q in r.list_questions(other)] == [strip(q) for q in qs]


def test_question_rows_validation_and_images(tmp_path):
    r = Repository(":memory:")
    lesson = r.ensure_lesson("م", "م", "و", "د")
    (tmp_path / "صور").mkdir()
    from PIL import Image  # pillow is a dev dependency

    Image.new("RGB", (8, 8), "red").save(tmp_path / "صور" / "kaaba.png")
    p = make_xlsx(tmp_path / "q.xlsx", ["النوع", "السؤال", "أ", "ب", "ج", "د", "الإجابة", "الصورة"], [
        ["اختيار", "أين الكعبة؟", "المدينة", "مكة", "", "", "مكة", "kaaba.png"],  # answer given as option text
        ["صح وخطأ", "الماء يغلي عند ١٠٠ درجة", "", "", "", "", "نعم", ""],
        ["اختيار", "سؤال بخيار واحد", "فقط", "", "", "", "أ", ""],
        ["لغز", "؟", "", "", "", "", "", ""],
        ["اختيار", "كم يساوي ٥ + ٣؟", "٦", "٨", "", "", "د", ""],
        ["ترتيب", "", "", "", "", "", "كلمة", ""],
    ])
    rep = X.import_questions(r, p, lesson, tmp_path / "imgs")
    assert rep.added == 2 and [row for row, _ in rep.errors] == [4, 5, 6, 7]
    q = r.list_questions(lesson)[0]
    assert q.correct == ["B"] and q.image_path and (tmp_path / "imgs" / q.image_path).exists()
    assert r.list_questions(lesson)[1].correct == ["A"]


def test_students_export(tmp_path):
    r = Repository(":memory:")
    cid = r.get_or_create_class("4A")
    r.add_student(Student("سارة", cid, "S9", None, "2016-05-05", "0012", "2026/2027"))
    assert X.export_students(r, tmp_path / "e.xlsx") == 1
    r2 = Repository(":memory:")
    X.import_students(r2, tmp_path / "e.xlsx")
    assert r2.find_student_by_national_id("0012").student_no == "S9"  # leading zeros kept
