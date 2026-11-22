-- EduKit local database schema (SQLite). Version tracked via PRAGMA user_version (2).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    grade       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    student_no  TEXT NOT NULL DEFAULT '',
    class_id    INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);

CREATE TABLE IF NOT EXISTS question_banks (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT '',
    grade       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (name, subject, grade)
);

CREATE TABLE IF NOT EXISTS questions (
    id               INTEGER PRIMARY KEY,
    bank_id          INTEGER NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
    code             TEXT NOT NULL,                       -- e.g. Q001; sent to devices as question_id
    qtype            TEXT NOT NULL DEFAULT 'single_choice',
    prompt_json      TEXT NOT NULL,                       -- {"en": "...", "ar": "..."}
    options_json     TEXT NOT NULL DEFAULT '[]',          -- [{"key":"A","text":{"en":..,"ar":..}}]
    correct_json     TEXT NOT NULL,                       -- ["C"] or {"value": 8, "tolerance": 0}
    time_limit_s     INTEGER NOT NULL DEFAULT 30,
    points           INTEGER NOT NULL DEFAULT 1,
    image_path       TEXT,
    explanation_json TEXT NOT NULL DEFAULT '{}',
    position         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (bank_id, code)
);
CREATE INDEX IF NOT EXISTS idx_questions_bank ON questions(bank_id, position);

CREATE TABLE IF NOT EXISTS sessions (
    id             INTEGER PRIMARY KEY,
    activity_type  TEXT NOT NULL,                         -- "mcq", later "race", "sensor", ...
    bank_id        INTEGER REFERENCES question_banks(id) ON DELETE SET NULL,
    class_id       INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    student_id     INTEGER REFERENCES students(id) ON DELETE SET NULL,
    settings_json  TEXT NOT NULL DEFAULT '{}',
    hardware_mode  TEXT NOT NULL DEFAULT 'simulation',    -- simulation | serial
    team_name      TEXT NOT NULL DEFAULT '',              -- journey game: team / group name
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at       TEXT,
    total_score    REAL NOT NULL DEFAULT 0,
    max_score      REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS responses (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    student_id     INTEGER REFERENCES students(id) ON DELETE SET NULL,
    question_id    INTEGER REFERENCES questions(id) ON DELETE SET NULL,
    question_code  TEXT NOT NULL,
    answer         TEXT,                                   -- "C", "A,C", "8", NULL on timeout
    outcome        TEXT NOT NULL CHECK (outcome IN ('correct','incorrect','partial','timeout')),
    score          REAL NOT NULL DEFAULT 0,
    max_score      REAL NOT NULL DEFAULT 0,
    response_ms    INTEGER,
    source         TEXT NOT NULL DEFAULT 'device',         -- device | screen | keyboard
    device_id      TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_responses_session ON responses(session_id);
CREATE INDEX IF NOT EXISTS idx_responses_student ON responses(student_id);

CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,
    role        TEXT NOT NULL,
    transport   TEXT NOT NULL,
    address     TEXT NOT NULL DEFAULT '',
    fw          TEXT NOT NULL DEFAULT '',
    last_seen   TEXT,
    config_json TEXT NOT NULL DEFAULT '{}'                 -- e.g. answer mapping, LED count
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL
);
