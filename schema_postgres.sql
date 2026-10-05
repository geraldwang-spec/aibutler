CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
 id BIGSERIAL PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, email VARCHAR(320) NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, is_email_verified SMALLINT NOT NULL DEFAULT 0,
 email_verified_at TIMESTAMP, password_changed_at TIMESTAMP, last_login_at TIMESTAMP,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS registration_codes (
 email VARCHAR(320) PRIMARY KEY, code_hash VARCHAR(128) NOT NULL, expires_at BIGINT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, sent_at BIGINT NOT NULL, state VARCHAR(32) NOT NULL,
 request_ip VARCHAR(64), used_at BIGINT
);
CREATE TABLE IF NOT EXISTS rate_limits (bucket VARCHAR(255) PRIMARY KEY, count INTEGER NOT NULL, started_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS reset_auth (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), reset_pwd_hash VARCHAR(255) UNIQUE,
 expires_at TIMESTAMP, used_at TIMESTAMP, request_ip VARCHAR(64), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_profiles (
 user_id BIGINT PRIMARY KEY REFERENCES users(id), gender VARCHAR(32), birth_date DATE, height_cm DOUBLE PRECISION,
 activity_level VARCHAR(64), goal_type VARCHAR(64), workout_days_per_week INTEGER, minutes_per_session INTEGER, onboarded_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS body_metrics (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), record_date DATE NOT NULL,
 weight_kg DOUBLE PRECISION NOT NULL, body_fat_pct DOUBLE PRECISION, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(user_id,record_date)
);
CREATE TABLE IF NOT EXISTS daily_summary (
 user_id BIGINT REFERENCES users(id), summary_date DATE, workout_volume DOUBLE PRECISION DEFAULT 0,
 trained_groups TEXT DEFAULT '[]', answered_count INTEGER DEFAULT 0, accuracy DOUBLE PRECISION DEFAULT 0,
 PRIMARY KEY(user_id,summary_date)
);
CREATE TABLE IF NOT EXISTS subjects (
 id BIGSERIAL PRIMARY KEY, subject_name VARCHAR(255) NOT NULL, created_by BIGINT REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chapters (
 id BIGSERIAL PRIMARY KEY, subject_id BIGINT NOT NULL REFERENCES subjects(id), chapter_name VARCHAR(255) NOT NULL,
 parent_chapter_id BIGINT REFERENCES chapters(id), order_no INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS questions (
 id BIGSERIAL PRIMARY KEY, chapter_id BIGINT NOT NULL REFERENCES chapters(id), q_type VARCHAR(32) NOT NULL,
 content TEXT NOT NULL, answer_key TEXT NOT NULL, explanation TEXT, difficulty INTEGER DEFAULT 1,
 source VARCHAR(255) DEFAULT 'manual', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS question_options (
 id BIGSERIAL PRIMARY KEY, question_id BIGINT NOT NULL REFERENCES questions(id), option_label VARCHAR(16) NOT NULL,
 option_text TEXT NOT NULL, order_no INTEGER DEFAULT 0, UNIQUE(question_id,option_label)
);
CREATE TABLE IF NOT EXISTS exam_imports (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), subject_id BIGINT REFERENCES subjects(id),
 file_name VARCHAR(255), file_path TEXT, file_type VARCHAR(32), status VARCHAR(64), total_rows INTEGER DEFAULT 0,
 imported_count INTEGER DEFAULT 0, error_log TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS import_items (
 id BIGSERIAL PRIMARY KEY, import_id BIGINT REFERENCES exam_imports(id), raw_content TEXT, parsed_json TEXT,
 chapter_id BIGINT REFERENCES chapters(id), question_id BIGINT REFERENCES questions(id), is_confirmed SMALLINT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), subject_id BIGINT REFERENCES subjects(id), mode VARCHAR(64),
 total_count INTEGER DEFAULT 0, correct_count INTEGER DEFAULT 0, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quiz_answers (
 id BIGSERIAL PRIMARY KEY, session_id BIGINT REFERENCES quiz_sessions(id), question_id BIGINT REFERENCES questions(id),
 user_answer TEXT, is_correct SMALLINT, time_spent_sec INTEGER, answered_at TIMESTAMP,
 question_snapshot TEXT NOT NULL, UNIQUE(session_id,question_id)
);
CREATE TABLE IF NOT EXISTS wrong_answers (
 user_id BIGINT REFERENCES users(id), question_id BIGINT REFERENCES questions(id), wrong_count INTEGER DEFAULT 1,
 last_wrong_at TIMESTAMP, status VARCHAR(32) DEFAULT '待複習', PRIMARY KEY(user_id,question_id)
);
CREATE TABLE IF NOT EXISTS summaries (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), chapter_id BIGINT REFERENCES chapters(id),
 summary_type VARCHAR(64), title VARCHAR(255), content TEXT, source_chunk_ids TEXT DEFAULT '[]', is_edited SMALLINT DEFAULT 1, mastery VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS exam_plans (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), subject_id BIGINT REFERENCES subjects(id), exam_date DATE,
 weekday_minutes INTEGER, weekend_minutes INTEGER, excluded_dates TEXT DEFAULT '[]', chapter_ids TEXT DEFAULT '[]',
 review_days INTEGER DEFAULT 3, generated_at TIMESTAMP, status VARCHAR(32)
);
CREATE TABLE IF NOT EXISTS study_plans (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), plan_date DATE, plan_type VARCHAR(64), title VARCHAR(255),
 chapter_id BIGINT REFERENCES chapters(id), target_value INTEGER, target_unit VARCHAR(64), status VARCHAR(32),
 done_ref_id BIGINT, exam_plan_id BIGINT REFERENCES exam_plans(id), source VARCHAR(64) DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS ix_study_date ON study_plans(user_id,plan_date);
CREATE TABLE IF NOT EXISTS exercises (
 id BIGSERIAL PRIMARY KEY, exercise_name VARCHAR(255), muscle_group VARCHAR(255), equipment VARCHAR(255),
 is_cardio SMALLINT DEFAULT 0, created_by BIGINT REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS workouts (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), workout_date DATE, started_at TIMESTAMP, ended_at TIMESTAMP,
 duration_min INTEGER DEFAULT 0, total_volume DOUBLE PRECISION DEFAULT 0, note TEXT
);
CREATE TABLE IF NOT EXISTS workout_sets (
 id BIGSERIAL PRIMARY KEY, workout_id BIGINT REFERENCES workouts(id), exercise_id BIGINT REFERENCES exercises(id), set_no INTEGER,
 weight_kg DOUBLE PRECISION, reps INTEGER, duration_sec INTEGER, distance_km DOUBLE PRECISION, rpe INTEGER
);
CREATE TABLE IF NOT EXISTS workout_templates (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), split_type VARCHAR(64), days_per_week INTEGER,
 minutes_per_session INTEGER, equipment_scope VARCHAR(255), is_active SMALLINT DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS template_items (
 id BIGSERIAL PRIMARY KEY, template_id BIGINT REFERENCES workout_templates(id), day_index INTEGER, muscle_group VARCHAR(255),
 exercise_id BIGINT REFERENCES exercises(id), order_no INTEGER, target_sets INTEGER, target_reps INTEGER,
 suggested_weight_kg DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS chat_sessions (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), title VARCHAR(255), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_messages (
 id BIGSERIAL PRIMARY KEY, chat_id BIGINT REFERENCES chat_sessions(id), role VARCHAR(32), content TEXT, intent VARCHAR(128),
 context_used TEXT DEFAULT '[]', token_usage INTEGER DEFAULT 0, latency_ms INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS materials (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), subject_id BIGINT REFERENCES subjects(id), title VARCHAR(255),
 file_path TEXT, file_type VARCHAR(64), page_count INTEGER, parse_status VARCHAR(64) DEFAULT '待處理'
);
CREATE TABLE IF NOT EXISTS rag_documents (
 id BIGSERIAL PRIMARY KEY, source_type VARCHAR(64), material_id BIGINT REFERENCES materials(id), title VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS rag_chunks (
 id BIGSERIAL PRIMARY KEY, doc_id BIGINT REFERENCES rag_documents(id), chunk_index INTEGER, content TEXT, token_count INTEGER,
 embedding vector, embedding_model VARCHAR(255), chapter_id BIGINT REFERENCES chapters(id)
);
CREATE TABLE IF NOT EXISTS generated_quizzes (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), prompt TEXT, source_chunk_ids TEXT, question_ids TEXT, reviewed SMALLINT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_suggestions (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id), sug_date DATE, type VARCHAR(64), content TEXT, accepted SMALLINT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rag_chunk_meta (
 chunk_id BIGINT PRIMARY KEY REFERENCES rag_chunks(id) ON DELETE CASCADE, source_locator VARCHAR(255), section_title VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS question_metadata (
 question_id BIGINT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
 source_type VARCHAR(64) DEFAULT 'manual', generation_model VARCHAR(255), evidence_chunk_ids TEXT,
 concepts_json TEXT, skill VARCHAR(64), is_verified SMALLINT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_question_drafts (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), subject_id BIGINT NOT NULL REFERENCES subjects(id),
 chapter_id BIGINT REFERENCES chapters(id), q_type VARCHAR(32) NOT NULL, content TEXT NOT NULL, options_json TEXT,
 answer_key TEXT NOT NULL, explanation TEXT, evidence_chunk_ids TEXT, concepts_json TEXT, skill VARCHAR(64), difficulty INTEGER DEFAULT 3,
 status VARCHAR(32) DEFAULT 'draft', model_name VARCHAR(255), approved_question_id BIGINT REFERENCES questions(id),
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS concepts (
 id BIGSERIAL PRIMARY KEY, subject_id BIGINT NOT NULL REFERENCES subjects(id), chapter_id BIGINT REFERENCES chapters(id),
 name VARCHAR(255) NOT NULL, description TEXT, importance INTEGER DEFAULT 3, UNIQUE(subject_id,name)
);
CREATE TABLE IF NOT EXISTS question_concepts (
 question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
 concept_id BIGINT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
 weight DOUBLE PRECISION DEFAULT 1, PRIMARY KEY(question_id,concept_id)
);

CREATE INDEX IF NOT EXISTS ix_subjects_created_by ON subjects(created_by);
CREATE INDEX IF NOT EXISTS ix_chapters_subject ON chapters(subject_id,order_no);
CREATE INDEX IF NOT EXISTS ix_questions_chapter_type ON questions(chapter_id,q_type);
CREATE INDEX IF NOT EXISTS ix_quiz_sessions_user_subject ON quiz_sessions(user_id,subject_id,finished_at);
CREATE INDEX IF NOT EXISTS ix_quiz_answers_session ON quiz_answers(session_id,id);
CREATE INDEX IF NOT EXISTS ix_quiz_answers_question_wrong ON quiz_answers(question_id,is_correct,answered_at);
CREATE INDEX IF NOT EXISTS ix_wrong_answers_user_status ON wrong_answers(user_id,status,last_wrong_at);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc_chapter ON rag_chunks(doc_id,chapter_id);
CREATE INDEX IF NOT EXISTS ix_aidraft_user_status ON ai_question_drafts(user_id,status,created_at);

CREATE TABLE IF NOT EXISTS source_question_items (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(id),
 subject_id BIGINT NOT NULL REFERENCES subjects(id),
 chapter_id BIGINT REFERENCES chapters(id),
 import_id BIGINT REFERENCES exam_imports(id),
 import_item_id BIGINT REFERENCES import_items(id),
 source_file TEXT,
 raw_question TEXT NOT NULL,
 q_type VARCHAR(32),
 answer_key TEXT,
 explanation TEXT,
 options_json TEXT,
 concept_id BIGINT NOT NULL REFERENCES concepts(id),
 skill VARCHAR(255),
 cognitive_level VARCHAR(32),
 difficulty INTEGER DEFAULT 2,
 classification_confidence DOUBLE PRECISION DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_source_questions_concept ON source_question_items(concept_id,chapter_id);
CREATE INDEX IF NOT EXISTS ix_source_questions_subject ON source_question_items(user_id,subject_id);


CREATE TABLE IF NOT EXISTS learning_goals (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), subject_id BIGINT NOT NULL REFERENCES subjects(id),
 goal_name TEXT NOT NULL, exam_date DATE NOT NULL, chapter_ids TEXT DEFAULT '[]', weekday_minutes INTEGER DEFAULT 60,
 weekend_minutes INTEGER DEFAULT 90, starting_level VARCHAR(32) DEFAULT 'auto', status VARCHAR(32) DEFAULT 'active',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_replanned_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS learning_phases (
 id BIGSERIAL PRIMARY KEY, goal_id BIGINT NOT NULL REFERENCES learning_goals(id), phase_no INTEGER NOT NULL, name TEXT NOT NULL,
 start_date DATE NOT NULL, end_date DATE NOT NULL, objective TEXT, target_mastery REAL DEFAULT 75, status VARCHAR(32) DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS learning_milestones (
 id BIGSERIAL PRIMARY KEY, goal_id BIGINT NOT NULL REFERENCES learning_goals(id), phase_id BIGINT REFERENCES learning_phases(id),
 title TEXT NOT NULL, target_date DATE NOT NULL, target_mastery REAL, checkpoint_question_count INTEGER DEFAULT 10,
 status VARCHAR(32) DEFAULT 'planned', achieved_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS learning_phase_concepts (
 id BIGSERIAL PRIMARY KEY, phase_id BIGINT NOT NULL REFERENCES learning_phases(id), concept_id BIGINT REFERENCES concepts(id),
 chapter_id BIGINT REFERENCES chapters(id), concept_name TEXT NOT NULL, priority_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS learning_tasks (
 id BIGSERIAL PRIMARY KEY, goal_id BIGINT NOT NULL REFERENCES learning_goals(id), user_id BIGINT NOT NULL REFERENCES users(id),
 phase_id BIGINT REFERENCES learning_phases(id), task_date DATE NOT NULL, task_type VARCHAR(64) NOT NULL, title TEXT NOT NULL,
 concept_id BIGINT REFERENCES concepts(id), chapter_id BIGINT REFERENCES chapters(id), target_minutes INTEGER DEFAULT 0,
 question_count INTEGER DEFAULT 0, status VARCHAR(32) DEFAULT 'planned', reason TEXT, completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_learning_tasks_goal_date ON learning_tasks(goal_id,user_id,task_date);

CREATE TABLE IF NOT EXISTS learning_checkpoint_attempts (
 id BIGSERIAL PRIMARY KEY,
 task_id BIGINT NOT NULL REFERENCES learning_tasks(id),
 milestone_id BIGINT REFERENCES learning_milestones(id),
 session_id BIGINT NOT NULL REFERENCES quiz_sessions(id),
 required_score REAL NOT NULL,
 score REAL,
 passed SMALLINT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 graded_at TIMESTAMP,
 UNIQUE(session_id)
);
CREATE INDEX IF NOT EXISTS ix_learning_checkpoint_task ON learning_checkpoint_attempts(task_id,id);


-- Adaptive AI Micro-Course: weakness + lecture RAG -> short interactive lesson.
CREATE TABLE IF NOT EXISTS micro_courses (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), subject_id BIGINT NOT NULL REFERENCES subjects(id),
 concept_id BIGINT NOT NULL REFERENCES concepts(id), title TEXT NOT NULL, objective TEXT, reason TEXT,
 estimated_minutes INTEGER DEFAULT 5, status VARCHAR(32) DEFAULT 'active', generation_model TEXT,
 evidence_chunk_ids TEXT DEFAULT '[]', weakness_snapshot TEXT DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 completed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS micro_course_steps (
 id BIGSERIAL PRIMARY KEY, course_id BIGINT NOT NULL REFERENCES micro_courses(id) ON DELETE CASCADE, step_no INTEGER NOT NULL,
 step_type VARCHAR(32) NOT NULL, title TEXT NOT NULL, content TEXT, question TEXT, answer_key TEXT, explanation TEXT,
 user_answer TEXT, is_correct SMALLINT, feedback TEXT, status VARCHAR(32) DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS micro_course_messages (
 id BIGSERIAL PRIMARY KEY, course_id BIGINT NOT NULL REFERENCES micro_courses(id) ON DELETE CASCADE, role VARCHAR(32) NOT NULL,
 content TEXT NOT NULL, context_chunk_ids TEXT DEFAULT '[]', model_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_micro_course_user ON micro_courses(user_id,subject_id,concept_id,created_at);
CREATE INDEX IF NOT EXISTS ix_micro_step_course ON micro_course_steps(course_id,step_no);
