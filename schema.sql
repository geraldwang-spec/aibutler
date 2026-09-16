PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, is_email_verified INTEGER NOT NULL DEFAULT 0,
 email_verified_at TEXT, password_changed_at TEXT, last_login_at TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS registration_codes (
 email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at INTEGER NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, sent_at INTEGER NOT NULL, state TEXT NOT NULL,
 request_ip TEXT, used_at INTEGER
);
CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, started_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reset_auth (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), reset_pwd_hash TEXT UNIQUE,
 expires_at TEXT, used_at TEXT, request_ip TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_profiles (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), gender TEXT, birth_date TEXT, height_cm REAL,
 activity_level TEXT, goal_type TEXT, workout_days_per_week INTEGER, minutes_per_session INTEGER, onboarded_at TEXT
);
CREATE TABLE IF NOT EXISTS body_metrics (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), record_date TEXT NOT NULL,
 weight_kg REAL NOT NULL, body_fat_pct REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,record_date)
);
CREATE TABLE IF NOT EXISTS daily_summary (
 user_id INTEGER REFERENCES users(id), summary_date TEXT, workout_volume REAL DEFAULT 0,
 trained_groups TEXT DEFAULT '[]', answered_count INTEGER DEFAULT 0, accuracy REAL DEFAULT 0,
 PRIMARY KEY(user_id,summary_date)
);
CREATE TABLE IF NOT EXISTS subjects (
 id INTEGER PRIMARY KEY, subject_name TEXT NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chapters (
 id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES subjects(id), chapter_name TEXT NOT NULL,
 parent_chapter_id INTEGER REFERENCES chapters(id), order_no INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS questions (
 id INTEGER PRIMARY KEY, chapter_id INTEGER NOT NULL REFERENCES chapters(id), q_type TEXT NOT NULL,
 content TEXT NOT NULL, answer_key TEXT NOT NULL, explanation TEXT, difficulty INTEGER DEFAULT 1,
 source TEXT DEFAULT 'manual', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS question_options (
 id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES questions(id), option_label TEXT NOT NULL,
 option_text TEXT NOT NULL, order_no INTEGER DEFAULT 0, UNIQUE(question_id,option_label)
);
CREATE TABLE IF NOT EXISTS exam_imports (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), subject_id INTEGER REFERENCES subjects(id),
 file_name TEXT, file_path TEXT, file_type TEXT, status TEXT, total_rows INTEGER DEFAULT 0,
 imported_count INTEGER DEFAULT 0, error_log TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS import_items (
 id INTEGER PRIMARY KEY, import_id INTEGER REFERENCES exam_imports(id), raw_content TEXT, parsed_json TEXT,
 chapter_id INTEGER REFERENCES chapters(id), question_id INTEGER REFERENCES questions(id), is_confirmed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), subject_id INTEGER REFERENCES subjects(id), mode TEXT,
 total_count INTEGER DEFAULT 0, correct_count INTEGER DEFAULT 0, started_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS quiz_answers (
 id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES quiz_sessions(id), question_id INTEGER REFERENCES questions(id),
 user_answer TEXT, is_correct INTEGER, time_spent_sec INTEGER, answered_at TEXT,
 question_snapshot TEXT NOT NULL, UNIQUE(session_id, question_id)
);
CREATE TABLE IF NOT EXISTS wrong_answers (
 user_id INTEGER REFERENCES users(id), question_id INTEGER REFERENCES questions(id), wrong_count INTEGER DEFAULT 1,
 last_wrong_at TEXT, status TEXT DEFAULT '待複習', PRIMARY KEY(user_id,question_id)
);
CREATE TABLE IF NOT EXISTS summaries (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), chapter_id INTEGER REFERENCES chapters(id),
 summary_type TEXT, title TEXT, content TEXT, source_chunk_ids TEXT DEFAULT '[]', is_edited INTEGER DEFAULT 1, mastery TEXT
);
CREATE TABLE IF NOT EXISTS exam_plans (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), subject_id INTEGER REFERENCES subjects(id), exam_date TEXT,
 weekday_minutes INTEGER, weekend_minutes INTEGER, excluded_dates TEXT DEFAULT '[]', chapter_ids TEXT DEFAULT '[]',
 review_days INTEGER DEFAULT 3, generated_at TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS study_plans (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), plan_date TEXT, plan_type TEXT, title TEXT,
 chapter_id INTEGER REFERENCES chapters(id), target_value INTEGER, target_unit TEXT, status TEXT,
 done_ref_id INTEGER, exam_plan_id INTEGER REFERENCES exam_plans(id), source TEXT DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS ix_study_date ON study_plans(user_id,plan_date);
CREATE TABLE IF NOT EXISTS exercises (
 id INTEGER PRIMARY KEY, exercise_name TEXT, muscle_group TEXT, equipment TEXT, is_cardio INTEGER DEFAULT 0, created_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS workouts (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), workout_date TEXT, started_at TEXT, ended_at TEXT,
 duration_min INTEGER DEFAULT 0, total_volume REAL DEFAULT 0, note TEXT
);
CREATE TABLE IF NOT EXISTS workout_sets (
 id INTEGER PRIMARY KEY, workout_id INTEGER REFERENCES workouts(id), exercise_id INTEGER REFERENCES exercises(id), set_no INTEGER,
 weight_kg REAL, reps INTEGER, duration_sec INTEGER, distance_km REAL, rpe INTEGER
);
CREATE TABLE IF NOT EXISTS workout_templates (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), split_type TEXT, days_per_week INTEGER,
 minutes_per_session INTEGER, equipment_scope TEXT, is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS template_items (
 id INTEGER PRIMARY KEY, template_id INTEGER REFERENCES workout_templates(id), day_index INTEGER, muscle_group TEXT,
 exercise_id INTEGER REFERENCES exercises(id), order_no INTEGER, target_sets INTEGER, target_reps INTEGER, suggested_weight_kg REAL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), title TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_messages (
 id INTEGER PRIMARY KEY, chat_id INTEGER REFERENCES chat_sessions(id), role TEXT, content TEXT, intent TEXT,
 context_used TEXT DEFAULT '[]', token_usage INTEGER DEFAULT 0, latency_ms INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS materials (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), subject_id INTEGER REFERENCES subjects(id), title TEXT,
 file_path TEXT, file_type TEXT, page_count INTEGER, parse_status TEXT DEFAULT '待處理'
);
CREATE TABLE IF NOT EXISTS rag_documents (
 id INTEGER PRIMARY KEY, source_type TEXT, material_id INTEGER REFERENCES materials(id), title TEXT
);
CREATE TABLE IF NOT EXISTS rag_chunks (
 id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES rag_documents(id), chunk_index INTEGER, content TEXT, token_count INTEGER,
 embedding BLOB, chapter_id INTEGER REFERENCES chapters(id)
);
CREATE TABLE IF NOT EXISTS generated_quizzes (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), prompt TEXT, source_chunk_ids TEXT, question_ids TEXT, reviewed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_suggestions (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), sug_date TEXT, type TEXT, content TEXT, accepted INTEGER DEFAULT 0
);
