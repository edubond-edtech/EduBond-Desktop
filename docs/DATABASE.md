# Local database

SQLite 3, a single file (`edukit.sqlite3` in the data folder), WAL mode, foreign keys on. The authoritative schema is [`desktop/edukit/data/schema.sql`](../desktop/edukit/data/schema.sql). The schema version is kept in `PRAGMA user_version`, and migrations run automatically at start-up in `Repository.migrate()` (currently 3: v2 added `sessions.team_name`; v3 added student birth date / national ID / school year and the curriculum tables `curricula → subjects → units`, with each question bank now a **lesson** under a unit).

```
classes 1───* students
   │                │
   │                └──────────────┐
question_banks 1───* questions     │
   │                    │          │
   └───* sessions *─────┼──────────┘   (session: one lesson run; bank, class, student)
            │           │
            └───* responses *┘          (one row per question answered / timed out)

devices   (last seen controllers + per-device config JSON: mapping, LED count, …)
settings  (key → JSON: language, quiz settings, effect profile, role assignment, hardware mode)
```

| Table | Purpose / notable columns |
|---|---|
| `classes` | `name` (unique), `grade` |
| `students` | `name`, `student_no`, `class_id` → classes (SET NULL on delete) |
| `question_banks` | `name`, `subject`, `grade` — unique together |
| `questions` | `code` (e.g. `Q001`, unique per bank, sent to devices as `question_id`), `qtype` (`single_choice`, `true_false`, `multi_choice`, `numeric`, `arrange`; for `arrange`, option *k* is the word on plate *k* and `correct` is always `["1",…,"n"]`), `prompt_json` `{"en","ar"}`, `options_json` `[{"key","text":{"en","ar"}}]`, `correct_json` (`["C"]` or `{"value":8,"tolerance":0}`), `time_limit_s`, `points`, `image_path` (relative to `data/images`), `explanation_json`, `position` |
| `sessions` | `activity_type` (`mcq`, `journey`), `team_name`, `bank_id`, `class_id`, `student_id`, `settings_json`, `hardware_mode` (`simulation`, `serial`, `simulation+serial`), `started_at`, `ended_at` (NULL = aborted), `total_score`, `max_score` |
| `responses` | `question_code` (kept even if the question is deleted later), `answer`, `outcome` (`correct`, `incorrect`, `partial`, `timeout`), `score`, `max_score`, `response_ms`, `source` (`device`, `screen`, `keyboard`, `skipped`), `device_id` |
| `devices` | `device_id`, `role`, `transport`, `address`, `fw`, `last_seen`, `config_json` |
| `settings` | `key`, `value_json` |

Deleting a bank cascades to its questions. Results keep `question_code`, and `question_id` becomes NULL. Deleting a student keeps their responses with `student_id = NULL`.

## Question bank exchange format

Banks can be imported and exported from the Questions tab as JSON. See [`sample_data/questions.json`](../sample_data/questions.json):

```json
{"format": "edukit-question-bank", "version": 1,
 "bank": {"name": "...", "subject": "...", "grade": "..."},
 "questions": [{"code": "Q001", "qtype": "single_choice", "time_limit_s": 20, "points": 1,
                "prompt": {"en": "What is 5 + 3?", "ar": "كم يساوي ٥ + ٣؟"},
                "options": [{"key": "A", "text": {"en": "6", "ar": "٦"}}, ...],
                "correct": ["C"], "explanation": {"en": "...", "ar": "..."}}]}
```

## Backups

Copy `edukit.sqlite3` (together with the `-wal` and `-shm` files if present) while the app is closed. Reports export to CSV (UTF-8 with BOM, so Excel shows Arabic correctly) and printable HTML.
