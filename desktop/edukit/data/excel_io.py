"""Excel (.xlsx) import/export for students and questions — Arabic templates, row-by-row validation."""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..core.models import Option, Question, Student
from .repository import Repository

# --------------------------------------------------------------------------- common
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


@dataclass
class ImportReport:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)  # (excel row number, message)
    warnings: list[tuple[int, str]] = field(default_factory=list)

    def summary_ar(self) -> str:
        parts = [f"أُضيف: {self.added}", f"حُدّث: {self.updated}"]
        if self.skipped:
            parts.append(f"تُخطّي: {self.skipped}")
        text = " · ".join(parts)
        if self.errors:
            text += "\n\nأخطاء:\n" + "\n".join(f"الصف {r}: {m}" for r, m in self.errors[:30])
            if len(self.errors) > 30:
                text += f"\n… و{len(self.errors) - 30} أخطاء أخرى"
        if self.warnings:
            text += "\n\nتنبيهات:\n" + "\n".join(f"الصف {r}: {m}" for r, m in self.warnings[:20])
        return text


def _clean(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _norm_header(h: Any) -> str:
    return re.sub(r"\s+", " ", _clean(h)).replace("ـ", "").lower()


def _read_rows(path: str | Path, aliases: dict[str, list[str]], sheet: str | None = None) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    """Return [(row_number, {field: value})] using flexible Arabic/English header names."""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    lookup = {}
    for fld, names in aliases.items():
        for n in names:
            lookup[_norm_header(n)] = fld
    header = [lookup.get(_norm_header(h)) for h in rows[0]]
    found = [h for h in header if h]
    out = []
    for i, row in enumerate(rows[1:], start=2):
        if row is None or all(c is None or _clean(c) == "" for c in row):
            continue
        rec = {fld: row[j] for j, fld in enumerate(header) if fld and j < len(row)}
        out.append((i, rec))
    return out, found


def _style_sheet(ws, headers: list[str], widths: list[int]) -> None:  # noqa: ANN001
    from openpyxl.styles import Alignment, Font, PatternFill

    ws.sheet_view.rightToLeft = True
    ws.append(headers)
    for col, w in enumerate(widths, start=1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7B3E98")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"


# --------------------------------------------------------------------------- students
STUDENT_HEADERS = ["الاسم", "تاريخ الميلاد", "رقم الهوية", "السنة الدراسية", "الصف", "رقم الطالب"]
STUDENT_ALIASES = {
    "name": ["الاسم", "اسم الطالب", "الاسم الكامل", "name", "student name"],
    "birth_date": ["تاريخ الميلاد", "الميلاد", "birth date", "birthdate", "date of birth", "dob"],
    "national_id": ["رقم الهوية", "الهوية", "رقم الهوية الوطنية", "السجل المدني", "national id", "id number", "id"],
    "school_year": ["السنة الدراسية", "العام الدراسي", "school year", "academic year", "year"],
    "class_name": ["الصف", "الفصل", "الشعبة", "class", "grade", "section"],
    "student_no": ["رقم الطالب", "الرقم", "student no", "student number"],
}


def parse_date(v: Any) -> str:
    """Return YYYY-MM-DD; accepts Excel dates, 2016-03-01, 01/03/2016, 1-3-2016 (day first). Raises ValueError."""
    if v is None or _clean(v) == "":
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = _clean(v).translate(AR_DIGITS).replace("\\", "/")
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
        if not m:
            raise ValueError(f"تاريخ غير مفهوم: «{s}» (استعمل مثلًا 2016-03-01 أو 01/03/2016)")
        d, mo, y = map(int, m.groups())
    return date(y, mo, d).isoformat()  # validates the day/month


def write_students_template(path: str | Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "الطلاب"
    _style_sheet(ws, STUDENT_HEADERS, [28, 16, 18, 16, 20, 12])
    ws.append(["أحمد محمد علي", "2016-03-01", "1023456789", "2026/2027", "الصف الرابع - أ", "S001"])
    ws.append(["فاطمة حسن", "14/09/2016", "1098765432", "2026/2027", "الصف الرابع - أ", "S002"])
    for row in ws.iter_rows(min_row=2, max_row=200, min_col=3, max_col=3):
        for c in row:
            c.number_format = "@"  # keep leading zeros of ID numbers
    info = wb.create_sheet("التعليمات")
    info.sheet_view.rightToLeft = True
    info.column_dimensions["A"].width = 100
    for line in [
        "تعليمات استيراد الطلاب",
        "• الاسم: مطلوب.",
        "• تاريخ الميلاد: بصيغة 2016-03-01 أو 01/03/2016 (اليوم أولًا) أو خلية تاريخ في Excel.",
        "• رقم الهوية: إذا وُجد طالب بنفس رقم الهوية تُحدَّث بياناته بدل إضافته مرة ثانية.",
        "• السنة الدراسية: مثل 2026/2027.",
        "• الصف: إذا لم يكن الصف موجودًا في البرنامج يُنشأ تلقائيًا.",
        "• رقم الطالب: اختياري.",
        "احذف صفوف الأمثلة ثم أضف طلابك ابتداءً من الصف الثاني.",
    ]:
        info.append([line])
    wb.save(path)


def import_students(repo: Repository, path: str | Path) -> ImportReport:
    rep = ImportReport()
    rows, found = _read_rows(path, STUDENT_ALIASES)
    if "name" not in found:
        rep.errors.append((1, "لم يُعثر على عمود «الاسم» في الصف الأول"))
        return rep
    for rownum, r in rows:
        name = _clean(r.get("name"))
        if not name:
            rep.errors.append((rownum, "الاسم فارغ"))
            continue
        try:
            birth = parse_date(r.get("birth_date"))
        except ValueError as exc:
            rep.errors.append((rownum, str(exc)))
            continue
        nid = _clean(r.get("national_id")).translate(AR_DIGITS).replace(" ", "")
        class_name = _clean(r.get("class_name"))
        class_id = repo.get_or_create_class(class_name) if class_name else None
        year = _clean(r.get("school_year"))
        sno = _clean(r.get("student_no"))
        existing = repo.find_student_by_national_id(nid) if nid else None
        if existing is not None:
            existing.name, existing.birth_date, existing.school_year = name, birth or existing.birth_date, year or existing.school_year
            existing.class_id = class_id if class_id is not None else existing.class_id
            existing.student_no = sno or existing.student_no
            repo.update_student(existing)
            rep.updated += 1
        else:
            repo.add_student(Student(name, class_id, sno, None, birth, nid, year))
            rep.added += 1
    return rep


def export_students(repo: Repository, path: str | Path) -> int:
    from openpyxl import Workbook

    names = {c.id: c.name for c in repo.list_classes()}
    wb = Workbook()
    ws = wb.active
    ws.title = "الطلاب"
    _style_sheet(ws, STUDENT_HEADERS, [28, 16, 18, 16, 20, 12])
    students = repo.list_students()
    for s in students:
        ws.append([s.name, s.birth_date, s.national_id, s.school_year, names.get(s.class_id, ""), s.student_no])
    wb.save(path)
    return len(students)


# --------------------------------------------------------------------------- questions
QUESTION_HEADERS = ["المنهج", "المادة", "الوحدة", "الدرس", "النوع", "السؤال", "الخيار أ", "الخيار ب", "الخيار ج", "الخيار د",
                    "الإجابة الصحيحة", "الصورة أو الفيديو", "الوقت (ثانية)", "النقاط", "الشرح"]
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
QUESTION_ALIASES = {
    "curriculum": ["المنهج", "curriculum"],
    "subject": ["المادة", "subject"],
    "unit": ["الوحدة", "unit"],
    "lesson": ["الدرس", "lesson"],
    "type": ["النوع", "نوع السؤال", "type"],
    "text": ["السؤال", "نص السؤال", "question"],
    "A": ["الخيار أ", "أ", "الخيار 1", "option a", "a"],
    "B": ["الخيار ب", "ب", "الخيار 2", "option b", "b"],
    "C": ["الخيار ج", "ج", "الخيار 3", "option c", "c"],
    "D": ["الخيار د", "د", "الخيار 4", "option d", "d"],
    "answer": ["الإجابة الصحيحة", "الاجابة الصحيحة", "الإجابة", "الجواب", "answer", "correct"],
    "image": ["الصورة أو الفيديو", "الصورة", "صورة", "الفيديو", "فيديو", "الوسائط", "image", "picture", "video", "media"],
    "time": ["الوقت (ثانية)", "الوقت", "time", "seconds"],
    "points": ["النقاط", "الدرجة", "points"],
    "explanation": ["الشرح", "التوضيح", "explanation"],
}
TYPE_ALIASES = {
    "single_choice": ["اختيار من متعدد", "اختيار", "متعدد", "mcq", "choice", "single_choice", "multiple choice"],
    "true_false": ["صح أو خطأ", "صح او خطأ", "صح وخطأ", "صح/خطأ", "صواب وخطأ", "true_false", "true/false", "tf"],
    "arrange": ["ترتيب كلمات", "ترتيب الكلمات", "ترتيب", "arrange", "order"],
}
TYPE_LABELS_AR = {"single_choice": "اختيار من متعدد", "true_false": "صح أو خطأ", "arrange": "ترتيب كلمات"}
LETTERS = {"أ": "A", "ا": "A", "ب": "B", "ج": "C", "د": "D", "a": "A", "b": "B", "c": "C", "d": "D", "1": "A", "2": "B", "3": "C", "4": "D"}
TRUE_WORDS = {"صح", "صحيح", "صواب", "نعم", "true", "t", "yes", "1", "✓", "✔"}
FALSE_WORDS = {"خطأ", "خطا", "خاطئ", "غلط", "لا", "false", "f", "no", "0", "✗", "✘"}


def _qtype(v: Any) -> str | None:
    t = _norm_header(v)
    for qtype, names in TYPE_ALIASES.items():
        if t in {_norm_header(n) for n in names}:
            return qtype
    return None


def build_question(r: dict[str, Any], code: str) -> Question:
    """Turn one spreadsheet row into a Question (raises ValueError with an Arabic message)."""
    qtype = _qtype(r.get("type") or "اختيار من متعدد")
    if qtype is None:
        raise ValueError(f"نوع غير معروف: «{_clean(r.get('type'))}» (المسموح: اختيار من متعدد، صح أو خطأ، ترتيب كلمات)")
    text = _clean(r.get("text"))
    answer = _clean(r.get("answer"))
    t = _clean(r.get("time"))
    points = _clean(r.get("points"))
    q = Question(code=code, prompt={"ar": text}, qtype=qtype,
                 time_limit_s=int(float(t)) if t else 30, points=int(float(points)) if points else 1)
    if _clean(r.get("explanation")):
        q.explanation = {"ar": _clean(r.get("explanation"))}
    if qtype == "single_choice":
        if not text:
            raise ValueError("نص السؤال فارغ")
        q.options = [Option(k, {"ar": _clean(r.get(k))}) for k in "ABCD" if _clean(r.get(k))]
        if len(q.options) < 2:
            raise ValueError("سؤال الاختيار يحتاج خيارين على الأقل")
        key = LETTERS.get(answer.lower(), answer.upper() if answer.upper() in "ABCD" and answer else None)
        if key is None:  # the answer may be written as the option text itself
            key = next((o.key for o in q.options if o.label("ar") == answer), None)
        if key is None or key not in q.option_keys:
            raise ValueError(f"الإجابة الصحيحة «{answer}» ليست أحد الخيارات (اكتب أ أو ب أو ج أو د)")
        q.correct = [key]
    elif qtype == "true_false":
        if not text:
            raise ValueError("نص السؤال فارغ")
        q.options = [Option("A", {"ar": "صح"}), Option("B", {"ar": "خطأ"})]
        a = answer.lower()
        if a in TRUE_WORDS or LETTERS.get(a) == "A":
            q.correct = ["A"]
        elif a in FALSE_WORDS or LETTERS.get(a) == "B":
            q.correct = ["B"]
        else:
            raise ValueError(f"إجابة صح أو خطأ غير مفهومة: «{answer}» (اكتب صح أو خطأ)")
    else:  # arrange: the answer column holds the sentence in the correct order
        words = answer.split() if answer else []
        if not 2 <= len(words) <= 6:
            raise ValueError("ترتيب الكلمات: اكتب الجملة الصحيحة (٢ إلى ٦ كلمات) في عمود «الإجابة الصحيحة»")
        q.prompt = {"ar": text or "رتّب الكلمات لتكوّن جملة صحيحة"}
        q.options = [Option(str(i + 1), {"ar": w}) for i, w in enumerate(words)]
        q.correct = [str(i + 1) for i in range(len(words))]
        q.explanation = q.explanation or {"ar": answer}
    return q


def _resolve_image(name: str, excel_path: Path, images_dir: Path) -> str | None:
    if not name:
        return None
    candidates = [Path(name)] if Path(name).is_absolute() else [
        excel_path.parent / name, excel_path.parent / "صور" / name, excel_path.parent / "images" / name]
    for folder in ("فيديو", "videos", "وسائط", "media"):
        candidates.append(excel_path.parent / folder / name)
    src = next((c for c in candidates if c.is_file()), None)
    if src is None or src.suffix.lower() not in MEDIA_EXT:
        return None
    images_dir.mkdir(parents=True, exist_ok=True)
    dest = images_dir / f"{uuid.uuid4().hex[:8]}_{src.name}"
    shutil.copy2(src, dest)
    return dest.name


def import_questions(repo: Repository, path: str | Path, lesson_id: int | None, images_dir: Path) -> ImportReport:
    """Rows go to ``lesson_id``, or — when المادة/الوحدة/الدرس are filled — to that lesson (created if needed)."""
    path = Path(path)
    rep = ImportReport()
    rows, found = _read_rows(path, QUESTION_ALIASES)
    if "text" not in found and "answer" not in found:
        rep.errors.append((1, "لم يُعثر على أعمدة «السؤال» و«الإجابة الصحيحة» في الصف الأول"))
        return rep
    for rownum, r in rows:
        target = lesson_id
        if _clean(r.get("subject")) and _clean(r.get("unit")) and _clean(r.get("lesson")):
            target = repo.ensure_lesson(_clean(r.get("curriculum")) or "المنهج العام", _clean(r.get("subject")),
                                        _clean(r.get("unit")), _clean(r.get("lesson")))
        if target is None:
            rep.errors.append((rownum, "اختر درسًا قبل الاستيراد أو املأ أعمدة المادة والوحدة والدرس"))
            continue
        try:
            q = build_question(r, repo.next_question_code(target))
        except ValueError as exc:
            rep.errors.append((rownum, str(exc)))
            continue
        img = _clean(r.get("image"))
        if img:
            q.image_path = _resolve_image(img, path, images_dir)
            if q.image_path is None:
                rep.warnings.append((rownum, f"الملف «{img}» غير موجود بجانب ملف Excel أو ليس صورة/فيديو؛ استُورد السؤال بدونه"))
        q.bank_id = target
        try:
            repo.add_question(q)
            rep.added += 1
        except Exception as exc:  # validation from the repository
            rep.errors.append((rownum, str(exc)))
    return rep


def write_questions_template(path: str | Path) -> None:
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "الأسئلة"
    _style_sheet(ws, QUESTION_HEADERS, [14, 14, 18, 18, 18, 40, 16, 16, 16, 16, 30, 18, 12, 9, 30])
    ex = [
        ["", "", "", "", "اختيار من متعدد", "ما عاصمة إندونيسيا؟", "جاكرتا", "كوالالمبور", "القاهرة", "الرياض", "أ", "jakarta.jpg", 30, 1, "عاصمة إندونيسيا هي جاكرتا"],
        ["", "", "", "", "صح أو خطأ", "الكعبة المشرفة في مكة المكرمة", "", "", "", "", "صح", "", 20, 1, ""],
        ["", "", "", "", "ترتيب كلمات", "رتّب الكلمات لتكوّن جملة صحيحة", "", "", "", "", "سافر الحجاج من إندونيسيا إلى مكة", "", 90, 1, ""],
        ["منهج 2026", "العلوم", "الوحدة الأولى: الماء", "حالات الماء", "اختيار من متعدد", "يتجمد الماء عند …", "100 °س", "0 °س", "50 °س", "", "ب", "", 30, 1, ""],
    ]
    for row in ex:
        ws.append(row)
    dv = DataValidation(type="list", formula1='"اختيار من متعدد,صح أو خطأ,ترتيب كلمات"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("E2:E1000")
    info = wb.create_sheet("التعليمات")
    info.sheet_view.rightToLeft = True
    info.column_dimensions["A"].width = 110
    for line in [
        "تعليمات استيراد الأسئلة",
        "• المنهج / المادة / الوحدة / الدرس: اختيارية. اتركها فارغة ليُستورد السؤال إلى الدرس المحدد في البرنامج،",
        "  أو املأها لينشئ البرنامج المادة والوحدة والدرس تلقائيًا (يمكن استيراد منهج كامل بملف واحد).",
        "• النوع: اختيار من متعدد · صح أو خطأ · ترتيب كلمات.",
        "• اختيار من متعدد: اكتب الخيارات في أ، ب، ج، د (خياران على الأقل)، والإجابة الصحيحة حرفًا: أ أو ب أو ج أو د.",
        "• صح أو خطأ: اترك الخيارات فارغة، والإجابة الصحيحة: صح أو خطأ.",
        "• ترتيب كلمات: اكتب الجملة الصحيحة كاملة (٢ إلى ٦ كلمات) في عمود «الإجابة الصحيحة»؛ الكلمة الأولى على البطاقة ١ وهكذا.",
        "• الصورة أو الفيديو: اسم الملف (مثل jakarta.jpg أو lesson1.mp4) موضوع بجانب ملف Excel أو في مجلد «صور» أو «فيديو» بجانبه.",
        "  تظهر الصورة أو يعمل الفيديو في أعلى الشاشة فوق السؤال. الصيغ: PNG · JPG · GIF · WEBP · MP4 · MOV · M4V · WEBM.",
        "• الوقت (ثانية) والنقاط والشرح: اختيارية (الافتراضي ٣٠ ثانية ونقطة واحدة).",
        "احذف صفوف الأمثلة ثم أضف أسئلتك ابتداءً من الصف الثاني.",
    ]:
        info.append([line])
    wb.save(path)


def export_questions(repo: Repository, lesson_id: int, path: str | Path) -> int:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "الأسئلة"
    _style_sheet(ws, QUESTION_HEADERS, [14, 14, 18, 18, 18, 40, 16, 16, 16, 16, 30, 18, 12, 9, 30])
    rev = {"A": "أ", "B": "ب", "C": "ج", "D": "د"}
    qs = repo.list_questions(lesson_id)
    for q in qs:
        words = {o.key: o.label("ar") for o in q.options}
        if q.qtype == "arrange":
            opts, ans = ["", "", "", ""], " ".join(words.get(k, "") for k in q.correct)
        elif q.qtype == "true_false":
            opts, ans = ["", "", "", ""], "صح" if q.correct == ["A"] else "خطأ"
        else:
            opts, ans = [words.get(k, "") for k in "ABCD"], rev.get((q.correct or [""])[0], "")
        ws.append(["", "", "", "", TYPE_LABELS_AR.get(q.qtype, q.qtype), q.text("ar"), *opts, ans, q.image_path or "",
                   q.time_limit_s, q.points, q.explanation.get("ar", "")])
    wb.save(path)
    return len(qs)


# --------------------------------------------------------------------------- student report
def export_student_report(report: list[dict[str, Any]], path: str | Path, date_from: str = "", date_to: str = "", arabic: bool = True) -> int:
    """Workbook with a summary sheet (one row per student) and a details sheet (every test under each student)."""
    from openpyxl import Workbook

    t = (lambda a, e: a) if arabic else (lambda a, e: e)  # noqa: E731
    mode_name = {"individual": t("فردي", "Individual"), "team": t("فريق", "Team"), "class": t("الصف كله", "Whole class")}
    wb = Workbook()
    ws = wb.active
    ws.title = t("ملخص الطلاب", "Summary")
    ws.sheet_view.rightToLeft = arabic
    period = f"{date_from or '…'} → {date_to or '…'}"
    ws.append([t("تقرير الطلاب", "Student report"), period])
    _style_sheet_after(ws, [t("الطالب", "Student"), t("رقم الهوية", "ID number"), t("الصف", "Class"), t("عدد الاختبارات", "Tests"),
                            t("الأسئلة المُجابة", "Answered"), t("الصحيحة", "Correct"), t("النسبة %", "Percent %")], [28, 16, 16, 14, 16, 12, 12])
    for r in report:
        st = r["student"]
        ws.append([st.name, st.national_id, r.get("class_name", ""), r["tests"], r["answered"], r["correct"], r["percent"] if r["percent"] is not None else ""])
    d = wb.create_sheet(t("التفاصيل", "Details"))
    d.sheet_view.rightToLeft = arabic
    _style_sheet_after(d, [t("الطالب", "Student"), t("التاريخ", "Date"), t("الدرس", "Lesson"), t("المشاركة", "Mode"), t("الفريق", "Team"),
                           t("المُجابة", "Answered"), t("الصحيحة", "Correct"), t("النسبة %", "Percent %"), t("الحالة", "Status")], [26, 20, 50, 12, 18, 12, 12, 12, 14])
    n = 0
    for r in report:
        for s in r["sessions"]:
            status = t("مكتمل", "Finished") if s.get("ended_at") else t("غير مكتمل", "Unfinished")
            d.append([r["student"].name, s["started_local"], s["lesson_path"] or s.get("lesson_name") or "", mode_name.get(s["mode"], s["mode"]),
                      s.get("team_label") or s.get("team_name") or "", s["answered"], s["correct"], s["percent"] if s["percent"] is not None else "",
                      status])
            n += 1
    wb.save(path)
    return n


def _style_sheet_after(ws, headers: list[str], widths: list[int]) -> None:  # noqa: ANN001
    """Like _style_sheet but appends the header row after any title rows already in the sheet."""
    from openpyxl.styles import Alignment, Font, PatternFill

    ws.append(headers)
    row = ws.max_row
    for col, w in enumerate(widths, start=1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7B3E98")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = w
