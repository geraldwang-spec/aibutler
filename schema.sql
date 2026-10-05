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

CREATE TABLE IF NOT EXISTS rag_chunk_meta (chunk_id INTEGER PRIMARY KEY,source_locator TEXT,section_title TEXT,FOREIGN KEY(chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS question_metadata (question_id INTEGER PRIMARY KEY,source_type TEXT DEFAULT 'manual',generation_model TEXT,evidence_chunk_ids TEXT,concepts_json TEXT,skill TEXT,is_verified INTEGER DEFAULT 0,FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS ai_question_drafts (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,subject_id INTEGER NOT NULL,chapter_id INTEGER,q_type TEXT NOT NULL,content TEXT NOT NULL,options_json TEXT,answer_key TEXT NOT NULL,explanation TEXT,evidence_chunk_ids TEXT,concepts_json TEXT,skill TEXT,difficulty INTEGER DEFAULT 3,status TEXT DEFAULT 'draft',model_name TEXT,approved_question_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id),FOREIGN KEY(subject_id) REFERENCES subjects(id),FOREIGN KEY(chapter_id) REFERENCES chapters(id),FOREIGN KEY(approved_question_id) REFERENCES questions(id));
CREATE INDEX IF NOT EXISTS ix_aidraft_user_status ON ai_question_drafts(user_id,status,created_at);
CREATE TABLE IF NOT EXISTS concepts (id INTEGER PRIMARY KEY AUTOINCREMENT,subject_id INTEGER NOT NULL,chapter_id INTEGER,name TEXT NOT NULL,description TEXT,importance INTEGER DEFAULT 3,UNIQUE(subject_id,name),FOREIGN KEY(subject_id) REFERENCES subjects(id),FOREIGN KEY(chapter_id) REFERENCES chapters(id));
CREATE TABLE IF NOT EXISTS question_concepts (question_id INTEGER NOT NULL,concept_id INTEGER NOT NULL,weight REAL DEFAULT 1,PRIMARY KEY(question_id,concept_id),FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE,FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE CASCADE);

-- Concept-based import: imported questions are source examples, not necessarily exam-pool questions.
CREATE TABLE IF NOT EXISTS source_question_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 subject_id INTEGER NOT NULL REFERENCES subjects(id),
 chapter_id INTEGER REFERENCES chapters(id),
 import_id INTEGER REFERENCES exam_imports(id),
 import_item_id INTEGER REFERENCES import_items(id),
 source_file TEXT,
 raw_question TEXT NOT NULL,
 q_type TEXT,
 answer_key TEXT,
 explanation TEXT,
 options_json TEXT,
 concept_id INTEGER NOT NULL REFERENCES concepts(id),
 skill TEXT,
 cognitive_level TEXT,
 difficulty INTEGER DEFAULT 2,
 classification_confidence REAL DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_source_questions_concept ON source_question_items(concept_id,chapter_id);
CREATE INDEX IF NOT EXISTS ix_source_questions_subject ON source_question_items(user_id,subject_id);


CREATE TABLE IF NOT EXISTS learning_goals (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), subject_id INTEGER NOT NULL REFERENCES subjects(id),
 goal_name TEXT NOT NULL, exam_date TEXT NOT NULL, chapter_ids TEXT DEFAULT '[]', weekday_minutes INTEGER DEFAULT 60,
 weekend_minutes INTEGER DEFAULT 90, starting_level TEXT DEFAULT 'auto', status TEXT DEFAULT 'active',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_replanned_at TEXT
);
CREATE TABLE IF NOT EXISTS learning_phases (
 id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL REFERENCES learning_goals(id), phase_no INTEGER NOT NULL, name TEXT NOT NULL,
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, objective TEXT, target_mastery REAL DEFAULT 75, status TEXT DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS learning_milestones (
 id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL REFERENCES learning_goals(id), phase_id INTEGER REFERENCES learning_phases(id),
 title TEXT NOT NULL, target_date TEXT NOT NULL, target_mastery REAL, checkpoint_question_count INTEGER DEFAULT 10,
 status TEXT DEFAULT 'planned', achieved_at TEXT
);
CREATE TABLE IF NOT EXISTS learning_phase_concepts (
 id INTEGER PRIMARY KEY, phase_id INTEGER NOT NULL REFERENCES learning_phases(id), concept_id INTEGER REFERENCES concepts(id),
 chapter_id INTEGER REFERENCES chapters(id), concept_name TEXT NOT NULL, priority_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS learning_tasks (
 id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL REFERENCES learning_goals(id), user_id INTEGER NOT NULL REFERENCES users(id),
 phase_id INTEGER REFERENCES learning_phases(id), task_date TEXT NOT NULL, task_type TEXT NOT NULL, title TEXT NOT NULL,
 concept_id INTEGER REFERENCES concepts(id), chapter_id INTEGER REFERENCES chapters(id), target_minutes INTEGER DEFAULT 0,
 question_count INTEGER DEFAULT 0, status TEXT DEFAULT 'planned', reason TEXT, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_learning_tasks_goal_date ON learning_tasks(goal_id,user_id,task_date);

CREATE TABLE IF NOT EXISTS learning_checkpoint_attempts (
 id INTEGER PRIMARY KEY,
 task_id INTEGER NOT NULL REFERENCES learning_tasks(id),
 milestone_id INTEGER REFERENCES learning_milestones(id),
 session_id INTEGER NOT NULL REFERENCES quiz_sessions(id),
 required_score REAL NOT NULL,
 score REAL,
 passed INTEGER,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 graded_at TEXT,
 UNIQUE(session_id)
);
CREATE INDEX IF NOT EXISTS ix_learning_checkpoint_task ON learning_checkpoint_attempts(task_id,id);


-- Adaptive AI Micro-Course: weakness + lecture RAG -> short interactive lesson.
CREATE TABLE IF NOT EXISTS micro_courses (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), subject_id INTEGER NOT NULL REFERENCES subjects(id),
 concept_id INTEGER NOT NULL REFERENCES concepts(id), title TEXT NOT NULL, objective TEXT, reason TEXT,
 estimated_minutes INTEGER DEFAULT 5, status TEXT DEFAULT 'active', generation_model TEXT,
 evidence_chunk_ids TEXT DEFAULT '[]', weakness_snapshot TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 completed_at TEXT
);
CREATE TABLE IF NOT EXISTS micro_course_steps (
 id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES micro_courses(id) ON DELETE CASCADE, step_no INTEGER NOT NULL,
 step_type TEXT NOT NULL, title TEXT NOT NULL, content TEXT, question TEXT, answer_key TEXT, explanation TEXT,
 user_answer TEXT, is_correct INTEGER, feedback TEXT, status TEXT DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS micro_course_messages (
 id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES micro_courses(id) ON DELETE CASCADE, role TEXT NOT NULL,
 content TEXT NOT NULL, context_chunk_ids TEXT DEFAULT '[]', model_name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_micro_course_user ON micro_courses(user_id,subject_id,concept_id,created_at);
CREATE INDEX IF NOT EXISTS ix_micro_step_course ON micro_course_steps(course_id,step_no);

CREATE TABLE IF NOT EXISTS concept_change_log (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,subject_id INTEGER NOT NULL,old_name TEXT,new_name TEXT,action TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
