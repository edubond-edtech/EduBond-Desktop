"""SQLite repository: all persistence goes through this class."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

from ..core.models import Curriculum, Option, Question, QuestionBank, SchoolClass, Student, Subject, Unit

SCHEMA_VERSION = 4
_SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


class Repository:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL" if self.path != ":memory:" else "PRAGMA journal_mode = MEMORY")
        self.migrate()

    # ------------------------------------------------------------ plumbing
    def migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                self._db.executescript(_SCHEMA)
                version = 2  # schema.sql already contains every column
            if version < 2:
                self._db.execute("ALTER TABLE sessions ADD COLUMN team_name TEXT NOT NULL DEFAULT ''")
            if version < 3:
                self._migrate_v3()
            if version < 4:
                self._db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS teams (
                        id INTEGER PRIMARY KEY,
                        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        UNIQUE (class_id, name));
                    CREATE TABLE IF NOT EXISTS team_members (
                        team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                        PRIMARY KEY (team_id, student_id));
                    ALTER TABLE sessions ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL;
                    """
                )
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.commit()

    def _migrate_v3(self) -> None:
        """Student details + curriculum -> subject -> unit -> lesson (lessons are the old question banks)."""
        db = self._db
        db.commit()
        db.execute("PRAGMA foreign_keys = OFF")
        db.executescript(
            """
            ALTER TABLE students ADD COLUMN birth_date TEXT NOT NULL DEFAULT '';
            ALTER TABLE students ADD COLUMN national_id TEXT NOT NULL DEFAULT '';
            ALTER TABLE students ADD COLUMN school_year TEXT NOT NULL DEFAULT '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_students_nid ON students(national_id) WHERE national_id <> '';
            CREATE TABLE IF NOT EXISTS curricula (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY,
                curriculum_id INTEGER NOT NULL REFERENCES curricula(id) ON DELETE CASCADE,
                name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, UNIQUE (curriculum_id, name));
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, UNIQUE (subject_id, name));
            CREATE TABLE question_banks_v3 (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '', grade TEXT NOT NULL DEFAULT '',
                unit_id INTEGER REFERENCES units(id) ON DELETE CASCADE,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')));
            INSERT INTO question_banks_v3(id, name, subject, grade, created_at)
                SELECT id, name, subject, grade, created_at FROM question_banks;
            DROP TABLE question_banks;
            ALTER TABLE question_banks_v3 RENAME TO question_banks;
            CREATE INDEX IF NOT EXISTS idx_banks_unit ON question_banks(unit_id, position);
            """
        )
        db.execute("PRAGMA foreign_keys = ON")
        self.assign_unplaced_lessons()

    # --------------------------------------------------------- curriculum tree
    def assign_unplaced_lessons(self, curriculum: str = "المنهج العام") -> int:
        """Put lessons without a unit into <curriculum> › <their subject> › «عام»."""
        rows = self._rows("SELECT id, subject FROM question_banks WHERE unit_id IS NULL")
        for r in rows:
            subject = (r["subject"] or "").strip() or "عام"
            unit_id = self.ensure_unit(curriculum, subject, "عام")
            self._exec("UPDATE question_banks SET unit_id=? WHERE id=?", (unit_id, r["id"]))
        return len(rows)

    def _get_or_create(self, table: str, parent_col: str | None, parent_id: int | None, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("الاسم مطلوب / name is required")
        if parent_col:
            rows = self._rows(f"SELECT id FROM {table} WHERE {parent_col}=? AND name=?", (parent_id, name))
        else:
            rows = self._rows(f"SELECT id FROM {table} WHERE name=?", (name,))
        if rows:
            return rows[0][0]
        if parent_col:
            pos = self._rows(f"SELECT COALESCE(MAX(position), 0) + 1 FROM {table} WHERE {parent_col}=?", (parent_id,))[0][0]
            return self._exec(f"INSERT INTO {table}(name, {parent_col}, position) VALUES(?, ?, ?)", (name, parent_id, pos)).lastrowid
        return self._exec(f"INSERT INTO {table}(name) VALUES(?)", (name,)).lastrowid

    def ensure_unit(self, curriculum: str, subject: str, unit: str) -> int:
        cid = self._get_or_create("curricula", None, None, curriculum)
        sid = self._get_or_create("subjects", "curriculum_id", cid, subject)
        return self._get_or_create("units", "subject_id", sid, unit)

    def ensure_lesson(self, curriculum: str, subject: str, unit: str, lesson: str) -> int:
        uid = self.ensure_unit(curriculum, subject, unit)
        rows = self._rows("SELECT id FROM question_banks WHERE unit_id=? AND name=?", (uid, lesson.strip()))
        if rows:
            return rows[0][0]
        return self.add_lesson(uid, lesson).id  # type: ignore[return-value]

    def add_curriculum(self, name: str) -> Curriculum:
        return Curriculum(name.strip(), self._exec("INSERT INTO curricula(name) VALUES(?)", (name.strip(),)).lastrowid)

    def add_subject(self, curriculum_id: int, name: str) -> Subject:
        return Subject(name.strip(), curriculum_id, self._get_or_create("subjects", "curriculum_id", curriculum_id, name))

    def add_unit(self, subject_id: int, name: str) -> Unit:
        return Unit(name.strip(), subject_id, self._get_or_create("units", "subject_id", subject_id, name))

    def add_lesson(self, unit_id: int, name: str) -> QuestionBank:
        subj = self._rows("SELECT s.name FROM units u JOIN subjects s ON s.id = u.subject_id WHERE u.id=?", (unit_id,))
        pos = self._rows("SELECT COALESCE(MAX(position), 0) + 1 FROM question_banks WHERE unit_id=?", (unit_id,))[0][0]
        b = QuestionBank(name.strip(), subj[0][0] if subj else "", "", None, unit_id, pos)
        b.id = self._exec("INSERT INTO question_banks(name, subject, grade, unit_id, position) VALUES(?, ?, ?, ?, ?)",
                          (b.name, b.subject, b.grade, unit_id, pos)).lastrowid
        return b

    def rename_node(self, kind: str, node_id: int, name: str) -> None:
        table = {"curriculum": "curricula", "subject": "subjects", "unit": "units", "lesson": "question_banks"}[kind]
        if not name.strip():
            raise ValueError("الاسم مطلوب")
        self._exec(f"UPDATE {table} SET name=? WHERE id=?", (name.strip(), node_id))

    def delete_node(self, kind: str, node_id: int) -> None:
        table = {"curriculum": "curricula", "subject": "subjects", "unit": "units", "lesson": "question_banks"}[kind]
        self._exec(f"DELETE FROM {table} WHERE id=?", (node_id,))

    def curriculum_tree(self) -> list[dict[str, Any]]:
        """[{id,name,subjects:[{id,name,units:[{id,name,lessons:[{id,name,count,types}]}]}]}]"""
        counts = self.bank_question_counts()
        types = self.bank_types()
        tree = []
        for c in self._rows("SELECT id, name FROM curricula ORDER BY name"):
            subjects = []
            for s_ in self._rows("SELECT id, name FROM subjects WHERE curriculum_id=? ORDER BY position, name", (c["id"],)):
                units = []
                for u in self._rows("SELECT id, name FROM units WHERE subject_id=? ORDER BY position, name", (s_["id"],)):
                    lessons = [
                        {"id": l["id"], "name": l["name"], "count": counts.get(l["id"], 0), "types": sorted(types.get(l["id"], set()))}
                        for l in self._rows("SELECT id, name FROM question_banks WHERE unit_id=? ORDER BY position, name", (u["id"],))
                    ]
                    units.append({"id": u["id"], "name": u["name"], "lessons": lessons})
                subjects.append({"id": s_["id"], "name": s_["name"], "units": units})
            tree.append({"id": c["id"], "name": c["name"], "subjects": subjects})
        return tree

    def lesson_path(self, bank_id: int) -> str:
        r = self._rows(
            """SELECT c.name, s.name, u.name, b.name FROM question_banks b
               JOIN units u ON u.id = b.unit_id JOIN subjects s ON s.id = u.subject_id JOIN curricula c ON c.id = s.curriculum_id
               WHERE b.id=?""", (bank_id,))
        return " › ".join(r[0]) if r else ""

    def unit_questions(self, unit_id: int) -> list[Question]:
        out: list[Question] = []
        for b in self._rows("SELECT id FROM question_banks WHERE unit_id=? ORDER BY position, name", (unit_id,)):
            out += self.list_questions(b["id"])
        return out

    def _exec(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _rows(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    closed = False

    def close(self) -> None:
        with self._lock:
            self.closed = True
            self._db.close()

    # ------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._rows("SELECT value_json FROM settings WHERE key=?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO settings(key, value_json) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # -------------------------------------------------------------- classes
    def add_class(self, c: SchoolClass) -> SchoolClass:
        c.id = self._exec("INSERT INTO classes(name, grade) VALUES(?, ?)", (c.name, c.grade)).lastrowid
        return c

    def update_class(self, c: SchoolClass) -> None:
        self._exec("UPDATE classes SET name=?, grade=? WHERE id=?", (c.name, c.grade, c.id))

    def delete_class(self, class_id: int) -> None:
        self._exec("DELETE FROM classes WHERE id=?", (class_id,))

    def list_classes(self) -> list[SchoolClass]:
        return [SchoolClass(r["name"], r["grade"], r["id"]) for r in self._rows("SELECT * FROM classes ORDER BY name")]

    # ------------------------------------------------------------- students
    def add_student(self, s: Student) -> Student:
        s.id = self._exec(
            "INSERT INTO students(name, student_no, class_id, birth_date, national_id, school_year) VALUES(?, ?, ?, ?, ?, ?)",
            (s.name, s.student_no, s.class_id, s.birth_date, s.national_id.strip(), s.school_year),
        ).lastrowid
        return s

    def update_student(self, s: Student) -> None:
        self._exec(
            "UPDATE students SET name=?, student_no=?, class_id=?, birth_date=?, national_id=?, school_year=? WHERE id=?",
            (s.name, s.student_no, s.class_id, s.birth_date, s.national_id.strip(), s.school_year, s.id),
        )

    def find_student_by_national_id(self, national_id: str) -> Student | None:
        if not national_id.strip():
            return None
        rows = self._rows("SELECT * FROM students WHERE national_id=?", (national_id.strip(),))
        return self._row_to_student(rows[0]) if rows else None

    def get_or_create_class(self, name: str, grade: str = "") -> int:
        rows = self._rows("SELECT id FROM classes WHERE name=?", (name.strip(),))
        if rows:
            return rows[0][0]
        return self.add_class(SchoolClass(name.strip(), grade)).id  # type: ignore[return-value]

    @staticmethod
    def _row_to_student(r: sqlite3.Row) -> Student:
        return Student(r["name"], r["class_id"], r["student_no"], r["id"], r["birth_date"], r["national_id"], r["school_year"])

    def delete_student(self, student_id: int) -> None:
        self._exec("DELETE FROM students WHERE id=?", (student_id,))

    def list_students(self, class_id: int | None = None) -> list[Student]:
        if class_id is None:
            rows = self._rows("SELECT * FROM students ORDER BY name")
        else:
            rows = self._rows("SELECT * FROM students WHERE class_id=? ORDER BY name", (class_id,))
        return [self._row_to_student(r) for r in rows]

    def get_student(self, student_id: int) -> Student | None:
        rows = self._rows("SELECT * FROM students WHERE id=?", (student_id,))
        return self._row_to_student(rows[0]) if rows else None

    # ---------------------------------------------------------------- banks
    def add_bank(self, b: QuestionBank) -> QuestionBank:
        b.id = self._exec(
            "INSERT INTO question_banks(name, subject, grade, unit_id, position) VALUES(?, ?, ?, ?, ?)",
            (b.name, b.subject, b.grade, b.unit_id, b.position),
        ).lastrowid
        return b

    def update_bank(self, b: QuestionBank) -> None:
        self._exec("UPDATE question_banks SET name=?, subject=?, grade=? WHERE id=?", (b.name, b.subject, b.grade, b.id))

    def delete_bank(self, bank_id: int) -> None:
        self._exec("DELETE FROM question_banks WHERE id=?", (bank_id,))

    def list_banks(self) -> list[QuestionBank]:
        return [QuestionBank(r["name"], r["subject"], r["grade"], r["id"], r["unit_id"], r["position"]) for r in self._rows("SELECT * FROM question_banks ORDER BY subject, grade, name")]

    def bank_types(self) -> dict[int, set[str]]:
        out: dict[int, set[str]] = {}
        for r in self._rows("SELECT bank_id, qtype FROM questions GROUP BY bank_id, qtype"):
            out.setdefault(r[0], set()).add(r[1])
        return out

    def bank_question_counts(self) -> dict[int, int]:
        return {r[0]: r[1] for r in self._rows("SELECT bank_id, COUNT(*) FROM questions GROUP BY bank_id")}

    # ------------------------------------------------------------ questions
    @staticmethod
    def _q_params(q: Question) -> dict[str, Any]:
        if not q.code.strip():
            raise ValueError("question code is required")
        if not any(v.strip() for v in q.prompt.values()):
            raise ValueError("question text is required")
        if q.qtype == "arrange":
            keys = [o.key for o in q.options]
            if not 2 <= len(keys) <= 6:
                raise ValueError("ترتيب الكلمات يحتاج من 2 إلى 6 كلمات / arrange needs 2-6 words")
            if any(k not in "123456" or len(k) != 1 for k in keys) or len(set(keys)) != len(keys):
                raise ValueError("أرقام البطاقات يجب أن تكون مختلفة من 1 إلى 6 / plate numbers must be unique 1-6")
            if not all(o.label("ar").strip() for o in q.options):
                raise ValueError("كل بطاقة تحتاج كلمة / every plate needs a word")
            correct = [str(c) for c in (q.correct or [])]
            fixed = [str(i + 1) for i in range(len(keys))]
            if correct != fixed or sorted(keys) != fixed:
                # The board firmware has a fixed key: socket k expects plate k, so word k must be on plate k.
                raise ValueError("الكلمة رقم ك يجب أن تكون على البطاقة رقم ك / word k must be on plate k (fixed firmware key)")
        elif q.qtype in ("single_choice", "multi_choice", "true_false"):
            keys = {o.key for o in q.options}
            if len(q.options) < 2:
                raise ValueError("at least two options are required")
            correct = q.correct if isinstance(q.correct, list) else [q.correct]
            if not correct or not set(correct) <= keys:
                raise ValueError("the correct answer must be one of the options")
            if q.qtype != "multi_choice" and len(correct) != 1:
                raise ValueError("single choice questions need exactly one correct answer")
        return {
            "bank_id": q.bank_id,
            "code": q.code.strip(),
            "qtype": q.qtype,
            "prompt_json": json.dumps(q.prompt, ensure_ascii=False),
            "options_json": json.dumps([{"key": o.key, "text": o.text} for o in q.options], ensure_ascii=False),
            "correct_json": json.dumps(q.correct, ensure_ascii=False),
            "time_limit_s": int(q.time_limit_s),
            "points": int(q.points),
            "image_path": q.image_path,
            "explanation_json": json.dumps(q.explanation, ensure_ascii=False),
        }

    def add_question(self, q: Question) -> Question:
        p = self._q_params(q)
        pos = self._rows("SELECT COALESCE(MAX(position), 0) + 1 FROM questions WHERE bank_id=?", (q.bank_id,))[0][0]
        p["position"] = pos
        q.id = self._exec(
            "INSERT INTO questions(bank_id, code, qtype, prompt_json, options_json, correct_json, time_limit_s, points, image_path, explanation_json, position) "
            "VALUES(:bank_id, :code, :qtype, :prompt_json, :options_json, :correct_json, :time_limit_s, :points, :image_path, :explanation_json, :position)",
            p,
        ).lastrowid
        return q

    def update_question(self, q: Question) -> None:
        p = self._q_params(q)
        p["id"] = q.id
        self._exec(
            "UPDATE questions SET bank_id=:bank_id, code=:code, qtype=:qtype, prompt_json=:prompt_json, options_json=:options_json, "
            "correct_json=:correct_json, time_limit_s=:time_limit_s, points=:points, image_path=:image_path, "
            "explanation_json=:explanation_json, updated_at=datetime('now') WHERE id=:id",
            p,
        )

    def delete_question(self, question_id: int) -> None:
        self._exec("DELETE FROM questions WHERE id=?", (question_id,))

    @staticmethod
    def _row_to_question(r: sqlite3.Row) -> Question:
        return Question(
            code=r["code"],
            prompt=json.loads(r["prompt_json"]),
            options=[Option(o["key"], o["text"]) for o in json.loads(r["options_json"])],
            correct=json.loads(r["correct_json"]),
            qtype=r["qtype"],
            time_limit_s=r["time_limit_s"],
            points=r["points"],
            image_path=r["image_path"],
            explanation=json.loads(r["explanation_json"] or "{}"),
            bank_id=r["bank_id"],
            id=r["id"],
        )

    def list_questions(self, bank_id: int) -> list[Question]:
        return [self._row_to_question(r) for r in self._rows("SELECT * FROM questions WHERE bank_id=? ORDER BY position, id", (bank_id,))]

    def get_question(self, question_id: int) -> Question | None:
        rows = self._rows("SELECT * FROM questions WHERE id=?", (question_id,))
        return self._row_to_question(rows[0]) if rows else None

    def next_question_code(self, bank_id: int) -> str:
        n = self._rows("SELECT COUNT(*) FROM questions WHERE bank_id=?", (bank_id,))[0][0] + 1
        existing = {q.code for q in self.list_questions(bank_id)}
        while f"Q{n:03d}" in existing:
            n += 1
        return f"Q{n:03d}"

    # ---------------------------------------------------------------- teams
    def add_team(self, class_id: int, name: str, member_ids: list[int]) -> int:
        if not name.strip():
            raise ValueError("اسم الفريق مطلوب / team name is required")
        tid = self._exec("INSERT INTO teams(class_id, name) VALUES(?, ?)", (class_id, name.strip())).lastrowid
        self.set_team_members(tid, member_ids)
        return tid

    def update_team(self, team_id: int, name: str, member_ids: list[int]) -> None:
        self._exec("UPDATE teams SET name=? WHERE id=?", (name.strip(), team_id))
        self.set_team_members(team_id, member_ids)

    def set_team_members(self, team_id: int, member_ids: list[int]) -> None:
        with self._lock:
            self._db.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
            self._db.executemany("INSERT OR IGNORE INTO team_members(team_id, student_id) VALUES(?, ?)", [(team_id, m) for m in member_ids])
            self._db.commit()

    def delete_team(self, team_id: int) -> None:
        self._exec("DELETE FROM teams WHERE id=?", (team_id,))

    def list_teams(self, class_id: int | None = None) -> list[dict[str, Any]]:
        where, params = ("WHERE t.class_id=?", (class_id,)) if class_id is not None else ("", ())
        teams = [dict(r) for r in self._rows(f"SELECT t.*, c.name AS class_name FROM teams t JOIN classes c ON c.id=t.class_id {where} ORDER BY c.name, t.name", params)]
        for t in teams:
            t["members"] = [self._row_to_student(r) for r in self._rows(
                "SELECT s.* FROM team_members m JOIN students s ON s.id=m.student_id WHERE m.team_id=? ORDER BY s.name", (t["id"],))]
        return teams

    def get_team(self, team_id: int) -> dict[str, Any] | None:
        return next((t for t in self.list_teams() if t["id"] == team_id), None)

    # --------------------------------------------------------- per-student report
    def student_report(self, date_from: str | None = None, date_to: str | None = None, class_id: int | None = None,
                       student_id: int | None = None) -> list[dict[str, Any]]:
        """Every student with all their tests in the period (individual, as a team member, or whole-class).

        Dates are local calendar days 'YYYY-MM-DD' (inclusive)."""
        students = self.list_students(class_id)
        if student_id is not None:
            students = [s for s in students if s.id == student_id]
        cond, params = [], []
        if date_from:
            cond.append("date(s.started_at, 'localtime') >= ?")
            params.append(date_from)
        if date_to:
            cond.append("date(s.started_at, 'localtime') <= ?")
            params.append(date_to)
        where = ("AND " + " AND ".join(cond)) if cond else ""
        sessions = [dict(r) for r in self._rows(
            f"""SELECT s.*, t.name AS team_label, b.name AS lesson_name,
                       (SELECT COUNT(*) FROM responses r WHERE r.session_id=s.id) AS answered,
                       (SELECT COUNT(*) FROM responses r WHERE r.session_id=s.id AND r.outcome='correct') AS correct,
                       datetime(s.started_at, 'localtime') AS started_local
                FROM sessions s LEFT JOIN teams t ON t.id=s.team_id LEFT JOIN question_banks b ON b.id=s.bank_id
                WHERE 1=1 {where} ORDER BY s.started_at""", tuple(params))]
        members: dict[int, set[int]] = {}
        for r in self._rows("SELECT team_id, student_id FROM team_members"):
            members.setdefault(r[1], set()).add(r[0])
        paths: dict[int, str] = {}
        out = []
        for st in students:
            mine = []
            for se in sessions:
                if se["student_id"] == st.id:
                    mode = "individual"
                elif se["team_id"] is not None and se["team_id"] in members.get(st.id, set()):
                    mode = "team"
                elif se["student_id"] is None and se["team_id"] is None and se["class_id"] is not None and se["class_id"] == st.class_id:
                    mode = "class"
                else:
                    continue
                if se["bank_id"] and se["bank_id"] not in paths:
                    paths[se["bank_id"]] = self.lesson_path(se["bank_id"]) or (se["lesson_name"] or "")
                mine.append({**se, "mode": mode, "lesson_path": paths.get(se["bank_id"], "") if se["bank_id"] else "",
                             "percent": round(100.0 * se["correct"] / se["answered"], 1) if se["answered"] else None})
            answered = sum(m["answered"] for m in mine)
            correct = sum(m["correct"] for m in mine)
            out.append({"student": st, "sessions": mine, "tests": len(mine), "answered": answered, "correct": correct,
                        "percent": round(100.0 * correct / answered, 1) if answered else None})
        return out

    # ------------------------------------------------------------- sessions
    def start_session(self, activity_type: str, bank_id: int | None, class_id: int | None, student_id: int | None, settings: dict[str, Any], hardware_mode: str, team_name: str = "", team_id: int | None = None) -> int:
        return self._exec(
            "INSERT INTO sessions(activity_type, bank_id, class_id, student_id, settings_json, hardware_mode, team_name, team_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (activity_type, bank_id, class_id, student_id, json.dumps(settings, ensure_ascii=False), hardware_mode, team_name, team_id),
        ).lastrowid

    def finish_session(self, session_id: int, total: float, max_score: float) -> None:
        self._exec("UPDATE sessions SET ended_at=datetime('now'), total_score=?, max_score=? WHERE id=?", (total, max_score, session_id))

    def add_response(self, session_id: int, student_id: int | None, question: Question, answer: Any, outcome: str, score: float, max_score: float, response_ms: int | None, source: str, device_id: str | None) -> int:
        if isinstance(answer, (list, tuple)):
            answer = ",".join(map(str, answer))
        return self._exec(
            "INSERT INTO responses(session_id, student_id, question_id, question_code, answer, outcome, score, max_score, response_ms, source, device_id) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, student_id, question.id, question.code, None if answer is None else str(answer), outcome, score, max_score, response_ms, source, device_id),
        ).lastrowid

    def list_sessions(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._rows(
            """SELECT s.*, st.name AS student_name, c.name AS class_name, b.name AS bank_name,
                      (SELECT COUNT(*) FROM responses r WHERE r.session_id = s.id) AS answered,
                      (SELECT COUNT(*) FROM responses r WHERE r.session_id = s.id AND r.outcome='correct') AS correct
               FROM sessions s
               LEFT JOIN students st ON st.id = s.student_id
               LEFT JOIN classes c ON c.id = s.class_id
               LEFT JOIN question_banks b ON b.id = s.bank_id
               ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def session_responses(self, session_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows("SELECT * FROM responses WHERE session_id=? ORDER BY id", (session_id,))]

    def all_responses(self) -> Iterator[dict[str, Any]]:
        for r in self._rows(
            """SELECT r.*, st.name AS student_name, c.name AS class_name, b.name AS bank_name, s.started_at AS session_started
               FROM responses r JOIN sessions s ON s.id = r.session_id
               LEFT JOIN students st ON st.id = r.student_id
               LEFT JOIN classes c ON c.id = s.class_id
               LEFT JOIN question_banks b ON b.id = s.bank_id ORDER BY r.id"""
        ):
            yield dict(r)

    def student_performance(self, class_id: int | None = None) -> list[dict[str, Any]]:
        where = "WHERE st.class_id = ?" if class_id is not None else ""
        params: tuple = (class_id,) if class_id is not None else ()
        rows = self._rows(
            f"""SELECT st.id AS student_id, st.name AS student_name, c.name AS class_name,
                       COUNT(r.id) AS answered,
                       SUM(CASE WHEN r.outcome='correct' THEN 1 ELSE 0 END) AS correct,
                       SUM(CASE WHEN r.outcome='partial' THEN 1 ELSE 0 END) AS partial,
                       SUM(CASE WHEN r.outcome='incorrect' THEN 1 ELSE 0 END) AS incorrect,
                       SUM(CASE WHEN r.outcome='timeout' THEN 1 ELSE 0 END) AS timeouts,
                       COALESCE(SUM(r.score), 0) AS score, COALESCE(SUM(r.max_score), 0) AS max_score,
                       AVG(r.response_ms) AS avg_response_ms,
                       COUNT(DISTINCT r.session_id) AS sessions
                FROM students st
                LEFT JOIN classes c ON c.id = st.class_id
                LEFT JOIN responses r ON r.student_id = st.id
                {where}
                GROUP BY st.id ORDER BY c.name, st.name""",
            params,
        )
        out = []
        for r in rows:
            d = dict(r)
            d["percent"] = round(100.0 * d["score"] / d["max_score"], 1) if d["max_score"] else None
            out.append(d)
        return out

    def question_stats(self, bank_id: int) -> list[dict[str, Any]]:
        rows = self._rows(
            """SELECT q.code, q.prompt_json, COUNT(r.id) AS answered,
                      SUM(CASE WHEN r.outcome='correct' THEN 1 ELSE 0 END) AS correct
               FROM questions q LEFT JOIN responses r ON r.question_id = q.id
               WHERE q.bank_id=? GROUP BY q.id ORDER BY q.position""",
            (bank_id,),
        )
        return [dict(r) for r in rows]

    # -------------------------------------------------------------- devices
    def upsert_device(self, device_id: str, role: str, transport: str, address: str, fw: str) -> None:
        self._exec(
            """INSERT INTO devices(device_id, role, transport, address, fw, last_seen) VALUES(?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(device_id) DO UPDATE SET role=excluded.role, transport=excluded.transport, address=excluded.address,
               fw=excluded.fw, last_seen=excluded.last_seen""",
            (device_id, role, transport, address, fw),
        )

    def device_config(self, device_id: str) -> dict[str, Any]:
        rows = self._rows("SELECT config_json FROM devices WHERE device_id=?", (device_id,))
        return json.loads(rows[0][0]) if rows else {}

    def set_device_config(self, device_id: str, role: str, config: dict[str, Any]) -> None:
        self._exec(
            """INSERT INTO devices(device_id, role, transport, config_json) VALUES(?, ?, '', ?)
               ON CONFLICT(device_id) DO UPDATE SET config_json=excluded.config_json""",
            (device_id, role, json.dumps(config)),
        )

    def list_devices(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows("SELECT * FROM devices ORDER BY role, device_id")]
