"""Report exports (CSV opens in Excel/Numbers; HTML prints to PDF from any browser)."""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path

from .repository import Repository

RESPONSE_COLUMNS = ["session_id", "session_started", "class_name", "student_name", "bank_name", "question_code", "answer", "outcome", "score", "max_score", "response_ms", "source", "device_id", "created_at"]
SUMMARY_COLUMNS = ["class_name", "student_name", "sessions", "answered", "correct", "partial", "incorrect", "timeouts", "score", "max_score", "percent", "avg_response_ms"]


def export_responses_csv(repo: Repository, path: str | Path) -> int:
    n = 0
    # utf-8-sig so Excel shows Arabic names correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=RESPONSE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in repo.all_responses():
            w.writerow(row)
            n += 1
    return n


def export_summary_csv(repo: Repository, path: str | Path, class_id: int | None = None) -> int:
    rows = repo.student_performance(class_id)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            if r["avg_response_ms"] is not None:
                r["avg_response_ms"] = int(r["avg_response_ms"])
            w.writerow(r)
    return len(rows)


def export_html_report(repo: Repository, path: str | Path, class_id: int | None = None) -> None:
    perf = repo.student_performance(class_id)
    sessions = repo.list_sessions(50)
    e = html.escape

    def pct(r: dict) -> str:
        return "–" if r["percent"] is None else f"{r['percent']:.0f}%"

    perf_rows = "".join(
        f"<tr><td>{e(r['class_name'] or '')}</td><td>{e(r['student_name'])}</td><td>{r['sessions']}</td><td>{r['answered']}</td>"
        f"<td>{r['correct'] or 0}</td><td>{r['incorrect'] or 0}</td><td>{r['timeouts'] or 0}</td>"
        f"<td><div class=bar><span style='width:{r['percent'] or 0}%'></span></div> {pct(r)}</td></tr>"
        for r in perf
    )
    sess_rows = "".join(
        f"<tr><td>{s['id']}</td><td>{e(s['started_at'] or '')}</td><td>{e(s['student_name'] or 'Guest')}</td><td>{e(s['bank_name'] or '')}</td>"
        f"<td>{s['correct']}/{s['answered']}</td><td>{s['total_score']:g}/{s['max_score']:g}</td><td>{e(s['hardware_mode'])}</td></tr>"
        for s in sessions
    )
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>EduKit report</title>
<style>body{{font-family:-apple-system,Segoe UI,Tahoma,sans-serif;margin:32px;color:#1d2433}}
h1{{margin:0 0 4px}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}
th,td{{border-bottom:1px solid #e3e7ef;padding:8px;text-align:start}}th{{background:#f4f6fb}}
.bar{{display:inline-block;width:120px;height:10px;background:#eceff5;border-radius:5px;vertical-align:middle}}
.bar span{{display:block;height:100%;background:#7B3E98;border-radius:5px}}.muted{{color:#6b7385}}</style></head>
<body><h1>EduKit — Class performance report</h1><div class=muted>Generated {datetime.now():%Y-%m-%d %H:%M}</div>
<h2>Students</h2><table><tr><th>Class</th><th>Student</th><th>Sessions</th><th>Answered</th><th>Correct</th><th>Wrong</th><th>Timeouts</th><th>Score</th></tr>{perf_rows}</table>
<h2>Recent sessions</h2><table><tr><th>#</th><th>Started</th><th>Student</th><th>Bank</th><th>Correct</th><th>Score</th><th>Hardware</th></tr>{sess_rows}</table>
<script type="application/json" id="data">{e(json.dumps(perf, default=str))}</script></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
