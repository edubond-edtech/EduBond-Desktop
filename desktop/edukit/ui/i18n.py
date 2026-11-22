"""Minimal bilingual (English / Arabic) string table for the student screen."""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "question_of": {"en": "Question {i} of {n}", "ar": "السؤال {i} من {n}"},
    "score": {"en": "Score", "ar": "النتيجة"},
    "correct": {"en": "Correct! Well done!", "ar": "إجابة صحيحة! أحسنت!"},
    "incorrect": {"en": "Not quite…", "ar": "ليست صحيحة…"},
    "partial": {"en": "Partly correct", "ar": "صحيحة جزئيًا"},
    "timeout": {"en": "Time is up!", "ar": "انتهى الوقت!"},
    "the_answer_is": {"en": "The answer is {a}", "ar": "الإجابة الصحيحة هي {a}"},
    "press_button": {"en": "Press a button to answer", "ar": "اضغط على زر للإجابة"},
    "finished": {"en": "Great job!", "ar": "عمل رائع!"},
    "final_score": {"en": "You scored {s} out of {m}", "ar": "حصلت على {s} من {m}"},
    "back": {"en": "Back to dashboard", "ar": "العودة إلى لوحة المعلم"},
    "next": {"en": "Next ▶", "ar": "التالي ◀"},
    "end": {"en": "End", "ar": "إنهاء"},
    "seconds": {"en": "{s}s", "ar": "{s} ث"},
    "guest": {"en": "Guest", "ar": "ضيف"},
    "stopped": {"en": "Session ended", "ar": "انتهت الجلسة"},
    "input_dev": {"en": "Buttons", "ar": "الأزرار"},
    "output_dev": {"en": "Lights", "ar": "الإضاءة"},
}

ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
LETTERS_AR = {"A": "أ", "B": "ب", "C": "ج", "D": "د", "E": "هـ", "F": "و"}


def tr(key: str, lang: str, **kw: object) -> str:
    s = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    out = s.format(**kw) if kw else s
    return out.translate(ARABIC_DIGITS) if lang == "ar" else out


def letter(key: str, lang: str) -> str:
    return LETTERS_AR.get(key, key) if lang == "ar" else key
