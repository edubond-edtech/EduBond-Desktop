"""Import/export of question banks and first-run demo data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.models import Question, QuestionBank, SchoolClass, Student
from .repository import Repository

DEMO_STUDENTS = ["Ahmed", "Fatima", "Omar", "Layla", "Yusuf", "Maryam"]


DEMO_CURRICULUM = ("المنهج التجريبي", "اللغة العربية والتربية الإسلامية", "رحلة إلى مكة")


def import_bank(repo: Repository, data: dict[str, Any] | str | Path, unit_id: int | None = None) -> QuestionBank:
    if not isinstance(data, dict):
        data = json.loads(Path(data).read_text(encoding="utf-8"))
    if data.get("format") != "edukit-question-bank":
        raise ValueError("not an EduKit question bank file")
    b = data["bank"]
    bank = repo.add_bank(QuestionBank(b["name"], b.get("subject", ""), b.get("grade", ""), unit_id=unit_id))
    for qd in data["questions"]:
        q = Question.from_dict(qd)
        q.bank_id = bank.id
        repo.add_question(q)
    return bank


def export_bank(repo: Repository, bank_id: int, path: str | Path) -> None:
    bank = next(b for b in repo.list_banks() if b.id == bank_id)
    data = {
        "format": "edukit-question-bank",
        "version": 1,
        "bank": {"name": bank.name, "subject": bank.subject, "grade": bank.grade},
        "questions": [q.to_dict() for q in repo.list_questions(bank_id)],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def seed_demo(repo: Repository, sample_file: Path) -> bool:
    """Populate an empty database with the demo bank, a class and students."""
    if repo.get_setting("seeded"):
        return False
    if sample_file.exists():
        import_bank(repo, sample_file)
    cls = repo.add_class(SchoolClass("Class 3A", "Grade 3"))
    for i, name in enumerate(DEMO_STUDENTS, 1):
        repo.add_student(Student(name, cls.id, f"S{i:03d}"))
    repo.set_setting("seeded", True)
    return True


def seed_journey(repo: Repository, sample_file: Path) -> bool:
    """Add the Arabic word-arrangement bank for the journey game (once)."""
    if repo.get_setting("seeded_journey") or not sample_file.exists():
        return False
    import_bank(repo, sample_file, repo.ensure_unit(*DEMO_CURRICULUM))
    repo.set_setting("seeded_journey", True)
    return True


def seed_journey_mcq(repo: Repository, sample_file: Path) -> bool:
    """Add the Arabic multiple-choice bank for the journey game (buttons version), once."""
    if repo.get_setting("seeded_journey_mcq") or not sample_file.exists():
        return False
    import_bank(repo, sample_file, repo.ensure_unit(*DEMO_CURRICULUM))
    repo.set_setting("seeded_journey_mcq", True)
    return True


def import_curriculum(repo: Repository, path: Path) -> int:
    """Load an «edukit-curriculum» JSON file: curriculum → subject → units → one lesson each with questions."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != "edukit-curriculum":
        raise ValueError("not an EduKit curriculum file")
    n = 0
    for unit in data["units"]:
        lesson_id = repo.ensure_lesson(data["curriculum"], data["subject"], unit["name"], unit["lesson"])
        for qd in unit["questions"]:
            q = Question.from_dict(qd)
            q.bank_id = lesson_id
            repo.add_question(q)
            n += 1
    return n


def seed_indonesia_g1(repo: Repository, sample_file: Path) -> bool:
    """30 multiple-choice questions: Indonesian curriculum, grade 1 Arabic (initial set)."""
    if repo.get_setting("seeded_indonesia_g1") or not sample_file.exists():
        return False
    import_curriculum(repo, sample_file)
    repo.set_setting("seeded_indonesia_g1", True)
    return True


def upgrade_indonesia_g1_arabic_only(repo: Repository, sample_file: Path) -> int:
    """One-time update of an already-installed Indonesian grade-1 set to the Arabic-only version.

    Questions are updated in place by code (ID1-01…ID1-30), so past results stay linked;
    curriculum, subject, unit and lesson names lose their Indonesian parts. Returns questions updated."""
    if repo.get_setting("indonesia_g1_arabic_only") or not sample_file.exists():
        return 0
    data = json.loads(Path(sample_file).read_text(encoding="utf-8"))
    updated = 0
    renamed_top = False
    for unit in data["units"]:
        unit_renamed = False
        for qd in unit["questions"]:
            rows = repo._rows("SELECT id, bank_id FROM questions WHERE code=?", (qd["code"],))
            if not rows:
                continue
            new = Question.from_dict(qd)
            new.id, new.bank_id = rows[0]["id"], rows[0]["bank_id"]
            old = repo.get_question(new.id)
            new.image_path = old.image_path if old else None  # keep a picture/video the teacher added
            repo.update_question(new)
            updated += 1
            if not unit_renamed:
                path = repo._rows(
                    """SELECT b.id AS lesson, u.id AS unit, s.id AS subject, c.id AS curriculum FROM question_banks b
                       JOIN units u ON u.id=b.unit_id JOIN subjects s ON s.id=u.subject_id JOIN curricula c ON c.id=s.curriculum_id
                       WHERE b.id=?""", (new.bank_id,))
                if path:
                    p = path[0]
                    for kind, node, name in (("unit", p["unit"], unit["name"]), ("lesson", p["lesson"], unit["lesson"])):
                        try:
                            repo.rename_node(kind, node, name)
                        except Exception:
                            pass  # a name clash: keep the old name rather than fail
                    if not renamed_top:
                        for kind, node, name in (("subject", p["subject"], data["subject"]), ("curriculum", p["curriculum"], data["curriculum"])):
                            try:
                                repo.rename_node(kind, node, name)
                            except Exception:
                                pass
                        renamed_top = True
                unit_renamed = True
    repo.set_setting("indonesia_g1_arabic_only", True)
    return updated
