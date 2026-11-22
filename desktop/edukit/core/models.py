"""Domain models shared by the engine, database and UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

QTYPES = ("single_choice", "multi_choice", "true_false", "numeric", "arrange")
CHOICE_QTYPES = ("single_choice", "multi_choice", "true_false")


@dataclass
class Option:
    key: str  # "A", "B", ...
    text: dict[str, str]  # {"en": "...", "ar": "..."}

    def label(self, lang: str) -> str:
        return self.text.get(lang) or self.text.get("en") or next(iter(self.text.values()), "")


@dataclass
class Question:
    code: str
    prompt: dict[str, str]
    options: list[Option] = field(default_factory=list)
    correct: Any = field(default_factory=list)  # list[str] for choice types, {"value","tolerance"} for numeric
    qtype: str = "single_choice"
    time_limit_s: int = 30  # 0 = no limit
    points: int = 1
    image_path: str | None = None
    explanation: dict[str, str] = field(default_factory=dict)
    bank_id: int | None = None
    id: int | None = None

    def text(self, lang: str) -> str:
        return self.prompt.get(lang) or self.prompt.get("en") or ""

    @property
    def option_keys(self) -> list[str]:
        return [o.key for o in self.options]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "prompt": self.prompt,
            "options": [{"key": o.key, "text": o.text} for o in self.options],
            "correct": self.correct,
            "qtype": self.qtype,
            "time_limit_s": self.time_limit_s,
            "points": self.points,
            "image_path": self.image_path,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Question":
        return cls(
            code=d["code"],
            prompt=dict(d["prompt"]),
            options=[Option(o["key"], dict(o["text"])) for o in d.get("options", [])],
            correct=d.get("correct", []),
            qtype=d.get("qtype", "single_choice"),
            time_limit_s=int(d.get("time_limit_s", 30)),
            points=int(d.get("points", 1)),
            image_path=d.get("image_path"),
            explanation=dict(d.get("explanation") or {}),
            bank_id=d.get("bank_id"),
            id=d.get("id"),
        )


@dataclass
class Student:
    name: str
    class_id: int | None = None
    student_no: str = ""
    id: int | None = None
    birth_date: str = ""  # YYYY-MM-DD
    national_id: str = ""  # رقم الهوية (unique when set)
    school_year: str = ""  # e.g. 2026/2027


@dataclass
class SchoolClass:
    name: str
    grade: str = ""
    id: int | None = None


@dataclass
class QuestionBank:
    """A lesson (درس): the leaf of curriculum -> subject -> unit -> lesson; holds the questions."""

    name: str
    subject: str = ""
    grade: str = ""
    id: int | None = None
    unit_id: int | None = None
    position: int = 0


@dataclass
class Curriculum:
    name: str
    id: int | None = None


@dataclass
class Subject:
    name: str
    curriculum_id: int
    id: int | None = None


@dataclass
class Unit:
    name: str
    subject_id: int
    id: int | None = None
