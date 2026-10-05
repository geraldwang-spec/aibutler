SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS users (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 username VARCHAR(80) NOT NULL UNIQUE,
 email VARCHAR(320) NOT NULL UNIQUE,
 password_hash TEXT NOT NULL,
 is_email_verified TINYINT(1) NOT NULL DEFAULT 0,
 email_verified_at DATETIME NULL,
 password_changed_at DATETIME NULL,
 last_login_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS registration_codes (
 email VARCHAR(320) PRIMARY KEY,
 code_hash VARCHAR(128) NOT NULL,
 expires_at BIGINT NOT NULL,
 attempts INT NOT NULL DEFAULT 0,
 sent_at BIGINT NOT NULL,
 state VARCHAR(32) NOT NULL,
 request_ip VARCHAR(64),
 used_at BIGINT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rate_limits (
 bucket VARCHAR(255) PRIMARY KEY,
 count INT NOT NULL,
 started_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reset_auth (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL,
 reset_pwd_hash VARCHAR(255) UNIQUE,
 expires_at DATETIME NULL,
 used_at DATETIME NULL,
 request_ip VARCHAR(64),
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_reset_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_profiles (
 user_id INT PRIMARY KEY,
 gender VARCHAR(32), birth_date DATE, height_cm DOUBLE,
 activity_level VARCHAR(64), goal_type VARCHAR(64), workout_days_per_week INT,
 minutes_per_session INT, onboarded_at DATETIME NULL,
 CONSTRAINT fk_profile_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS body_metrics (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL, record_date DATE NOT NULL,
 weight_kg DOUBLE NOT NULL, body_fat_pct DOUBLE,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_body_user_date (user_id,record_date),
 CONSTRAINT fk_body_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS daily_summary (
 user_id INT NOT NULL, summary_date DATE NOT NULL, workout_volume DOUBLE DEFAULT 0,
 trained_groups TEXT, answered_count INT DEFAULT 0, accuracy DOUBLE DEFAULT 0,
 PRIMARY KEY(user_id,summary_date),
 CONSTRAINT fk_daily_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS subjects (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 subject_name VARCHAR(255) NOT NULL,
 created_by INT NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_subject_user FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chapters (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 subject_id INT NOT NULL,
 chapter_name VARCHAR(255) NOT NULL,
 parent_chapter_id INT NULL,
 order_no INT DEFAULT 0,
 CONSTRAINT fk_chapter_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
 CONSTRAINT fk_chapter_parent FOREIGN KEY (parent_chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS questions (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 chapter_id INT NOT NULL,
 q_type VARCHAR(32) NOT NULL,
 content TEXT NOT NULL,
 answer_key TEXT NOT NULL,
 explanation TEXT,
 difficulty INT DEFAULT 1,
 source VARCHAR(255) DEFAULT 'manual',
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_question_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS question_options (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 question_id INT NOT NULL,
 option_label VARCHAR(16) NOT NULL,
 option_text TEXT NOT NULL,
 order_no INT DEFAULT 0,
 UNIQUE KEY uq_question_label (question_id,option_label),
 CONSTRAINT fk_option_question FOREIGN KEY (question_id) REFERENCES questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exam_imports (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, subject_id INT NULL,
 file_name VARCHAR(255), file_path TEXT, file_type VARCHAR(32), status VARCHAR(64),
 total_rows INT DEFAULT 0, imported_count INT DEFAULT 0, error_log TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_import_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_import_subject FOREIGN KEY (subject_id) REFERENCES subjects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS import_items (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 import_id INT NULL, raw_content LONGTEXT, parsed_json LONGTEXT,
 chapter_id INT NULL, question_id INT NULL, is_confirmed TINYINT(1) DEFAULT 0,
 CONSTRAINT fk_item_import FOREIGN KEY (import_id) REFERENCES exam_imports(id),
 CONSTRAINT fk_item_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id),
 CONSTRAINT fk_item_question FOREIGN KEY (question_id) REFERENCES questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_sessions (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, subject_id INT NULL, mode VARCHAR(64),
 total_count INT DEFAULT 0, correct_count INT DEFAULT 0,
 started_at DATETIME DEFAULT CURRENT_TIMESTAMP, finished_at DATETIME NULL,
 CONSTRAINT fk_quiz_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_quiz_subject FOREIGN KEY (subject_id) REFERENCES subjects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS quiz_answers (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 session_id INT NULL, question_id INT NULL,
 user_answer TEXT, is_correct TINYINT(1), time_spent_sec INT, answered_at DATETIME NULL,
 question_snapshot LONGTEXT NOT NULL,
 UNIQUE KEY uq_quiz_question (session_id,question_id),
 CONSTRAINT fk_answer_session FOREIGN KEY (session_id) REFERENCES quiz_sessions(id),
 CONSTRAINT fk_answer_question FOREIGN KEY (question_id) REFERENCES questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wrong_answers (
 user_id INT NOT NULL, question_id INT NOT NULL, wrong_count INT DEFAULT 1,
 last_wrong_at DATETIME NULL, status VARCHAR(32) DEFAULT '待複習',
 PRIMARY KEY(user_id,question_id),
 CONSTRAINT fk_wrong_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_wrong_question FOREIGN KEY (question_id) REFERENCES questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS summaries (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, chapter_id INT NULL, summary_type VARCHAR(64), title VARCHAR(255),
 content LONGTEXT, source_chunk_ids LONGTEXT, is_edited TINYINT(1) DEFAULT 1, mastery VARCHAR(64),
 CONSTRAINT fk_summary_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_summary_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exam_plans (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, subject_id INT NULL, exam_date DATE,
 weekday_minutes INT, weekend_minutes INT, excluded_dates LONGTEXT, chapter_ids LONGTEXT,
 review_days INT DEFAULT 3, generated_at DATETIME NULL, status VARCHAR(32),
 CONSTRAINT fk_examplan_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_examplan_subject FOREIGN KEY (subject_id) REFERENCES subjects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS study_plans (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, plan_date DATE, plan_type VARCHAR(64), title VARCHAR(255),
 chapter_id INT NULL, target_value INT, target_unit VARCHAR(64), status VARCHAR(32),
 done_ref_id INT, exam_plan_id INT NULL, source VARCHAR(64) DEFAULT 'manual',
 CONSTRAINT fk_study_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_study_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id),
 CONSTRAINT fk_study_examplan FOREIGN KEY (exam_plan_id) REFERENCES exam_plans(id),
 INDEX ix_study_date (user_id,plan_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exercises (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 exercise_name VARCHAR(255), muscle_group VARCHAR(255), equipment VARCHAR(255),
 is_cardio TINYINT(1) DEFAULT 0, created_by INT NULL,
 CONSTRAINT fk_exercise_user FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workouts (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, workout_date DATE, started_at DATETIME NULL, ended_at DATETIME NULL,
 duration_min INT DEFAULT 0, total_volume DOUBLE DEFAULT 0, note TEXT,
 CONSTRAINT fk_workout_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workout_sets (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 workout_id INT NULL, exercise_id INT NULL, set_no INT,
 weight_kg DOUBLE, reps INT, duration_sec INT, distance_km DOUBLE, rpe INT,
 CONSTRAINT fk_set_workout FOREIGN KEY (workout_id) REFERENCES workouts(id),
 CONSTRAINT fk_set_exercise FOREIGN KEY (exercise_id) REFERENCES exercises(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workout_templates (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, split_type VARCHAR(64), days_per_week INT, minutes_per_session INT,
 equipment_scope VARCHAR(255), is_active TINYINT(1) DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_template_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS template_items (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 template_id INT NULL, day_index INT, muscle_group VARCHAR(255), exercise_id INT NULL,
 order_no INT, target_sets INT, target_reps INT, suggested_weight_kg DOUBLE,
 CONSTRAINT fk_template_item_template FOREIGN KEY (template_id) REFERENCES workout_templates(id),
 CONSTRAINT fk_template_item_exercise FOREIGN KEY (exercise_id) REFERENCES exercises(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_sessions (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, title VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_chat_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_messages (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 chat_id INT NULL, role VARCHAR(32), content LONGTEXT, intent VARCHAR(128),
 context_used LONGTEXT, token_usage INT DEFAULT 0, latency_ms INT DEFAULT 0,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_message_chat FOREIGN KEY (chat_id) REFERENCES chat_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS materials (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, subject_id INT NULL, title VARCHAR(255), file_path TEXT,
 file_type VARCHAR(64), page_count INT, parse_status VARCHAR(64) DEFAULT '待處理',
 CONSTRAINT fk_material_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_material_subject FOREIGN KEY (subject_id) REFERENCES subjects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_documents (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 source_type VARCHAR(64), material_id INT NULL, title VARCHAR(255),
 CONSTRAINT fk_ragdoc_material FOREIGN KEY (material_id) REFERENCES materials(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_chunks (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 doc_id INT NULL, chunk_index INT, content LONGTEXT, token_count INT,
 embedding LONGBLOB, embedding_model VARCHAR(255) NULL, chapter_id INT NULL,
 CONSTRAINT fk_chunk_doc FOREIGN KEY (doc_id) REFERENCES rag_documents(id),
 CONSTRAINT fk_chunk_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS generated_quizzes (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, prompt LONGTEXT, source_chunk_ids LONGTEXT, question_ids LONGTEXT,
 reviewed TINYINT(1) DEFAULT 0,
 CONSTRAINT fk_generated_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_suggestions (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NULL, sug_date DATE, type VARCHAR(64), content LONGTEXT,
 accepted TINYINT(1) DEFAULT 0,
 CONSTRAINT fk_suggestion_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ===== Integrated Personal AI / RAG / adaptive planner tables =====
CREATE TABLE IF NOT EXISTS rag_chunk_meta (
 chunk_id INT PRIMARY KEY, source_locator TEXT, section_title TEXT,
 CONSTRAINT fk_ragmeta_chunk FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS question_metadata (
 question_id INT PRIMARY KEY, source_type VARCHAR(64) DEFAULT 'manual', generation_model VARCHAR(255),
 evidence_chunk_ids LONGTEXT, concepts_json LONGTEXT, skill VARCHAR(255), is_verified TINYINT(1) DEFAULT 0,
 CONSTRAINT fk_qmeta_question FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_question_drafts (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, subject_id INT NOT NULL, chapter_id INT NULL,
 q_type VARCHAR(32) NOT NULL, content LONGTEXT NOT NULL, options_json LONGTEXT, answer_key TEXT NOT NULL, explanation LONGTEXT,
 evidence_chunk_ids LONGTEXT, concepts_json LONGTEXT, skill VARCHAR(255), difficulty INT DEFAULT 3, status VARCHAR(32) DEFAULT 'draft',
 model_name VARCHAR(255), approved_question_id INT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 INDEX ix_aidraft_user_status (user_id,status,created_at),
 CONSTRAINT fk_aidraft_user FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_aidraft_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
 CONSTRAINT fk_aidraft_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id),
 CONSTRAINT fk_aidraft_approved FOREIGN KEY (approved_question_id) REFERENCES questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS concepts (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, subject_id INT NOT NULL, chapter_id INT NULL, name VARCHAR(255) NOT NULL,
 description LONGTEXT, importance INT DEFAULT 3, UNIQUE KEY uq_concept_subject_name(subject_id,name),
 CONSTRAINT fk_concept_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
 CONSTRAINT fk_concept_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS question_concepts (
 question_id INT NOT NULL, concept_id INT NOT NULL, weight DOUBLE DEFAULT 1, PRIMARY KEY(question_id,concept_id),
 CONSTRAINT fk_qconcept_question FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE,
 CONSTRAINT fk_qconcept_concept FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS source_question_items (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, subject_id INT NOT NULL, chapter_id INT NULL, import_id INT NULL, import_item_id INT NULL,
 source_file TEXT, raw_question LONGTEXT NOT NULL, q_type VARCHAR(32), answer_key TEXT, explanation LONGTEXT, options_json LONGTEXT,
 concept_id INT NOT NULL, skill VARCHAR(255), cognitive_level VARCHAR(255), difficulty INT DEFAULT 2, classification_confidence DOUBLE DEFAULT 0,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX ix_source_questions_concept(concept_id,chapter_id), INDEX ix_source_questions_subject(user_id,subject_id),
 CONSTRAINT fk_sourceq_user FOREIGN KEY(user_id) REFERENCES users(id), CONSTRAINT fk_sourceq_subject FOREIGN KEY(subject_id) REFERENCES subjects(id),
 CONSTRAINT fk_sourceq_chapter FOREIGN KEY(chapter_id) REFERENCES chapters(id), CONSTRAINT fk_sourceq_import FOREIGN KEY(import_id) REFERENCES exam_imports(id),
 CONSTRAINT fk_sourceq_item FOREIGN KEY(import_item_id) REFERENCES import_items(id), CONSTRAINT fk_sourceq_concept FOREIGN KEY(concept_id) REFERENCES concepts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS learning_goals (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, subject_id INT NOT NULL, goal_name VARCHAR(255) NOT NULL, exam_date DATE NOT NULL,
 chapter_ids LONGTEXT, weekday_minutes INT DEFAULT 60, weekend_minutes INT DEFAULT 90, starting_level VARCHAR(64) DEFAULT 'auto', status VARCHAR(32) DEFAULT 'active',
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP, last_replanned_at DATETIME NULL,
 CONSTRAINT fk_lgoal_user FOREIGN KEY(user_id) REFERENCES users(id), CONSTRAINT fk_lgoal_subject FOREIGN KEY(subject_id) REFERENCES subjects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS learning_phases (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, goal_id INT NOT NULL, phase_no INT NOT NULL, name VARCHAR(255) NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL,
 objective LONGTEXT, target_mastery DOUBLE DEFAULT 75, status VARCHAR(32) DEFAULT 'planned', CONSTRAINT fk_lphase_goal FOREIGN KEY(goal_id) REFERENCES learning_goals(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS learning_milestones (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, goal_id INT NOT NULL, phase_id INT NULL, title VARCHAR(255) NOT NULL, target_date DATE NOT NULL,
 target_mastery DOUBLE, checkpoint_question_count INT DEFAULT 10, status VARCHAR(32) DEFAULT 'planned', achieved_at DATETIME NULL,
 CONSTRAINT fk_lmile_goal FOREIGN KEY(goal_id) REFERENCES learning_goals(id), CONSTRAINT fk_lmile_phase FOREIGN KEY(phase_id) REFERENCES learning_phases(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS learning_phase_concepts (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, phase_id INT NOT NULL, concept_id INT NULL, chapter_id INT NULL, concept_name VARCHAR(255) NOT NULL, priority_order INT DEFAULT 0,
 CONSTRAINT fk_lpc_phase FOREIGN KEY(phase_id) REFERENCES learning_phases(id), CONSTRAINT fk_lpc_concept FOREIGN KEY(concept_id) REFERENCES concepts(id), CONSTRAINT fk_lpc_chapter FOREIGN KEY(chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS learning_tasks (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, goal_id INT NOT NULL, user_id INT NOT NULL, phase_id INT NULL, task_date DATE NOT NULL, task_type VARCHAR(64) NOT NULL,
 title VARCHAR(255) NOT NULL, concept_id INT NULL, chapter_id INT NULL, target_minutes INT DEFAULT 0, question_count INT DEFAULT 0, status VARCHAR(32) DEFAULT 'planned',
 reason LONGTEXT, completed_at DATETIME NULL, INDEX ix_learning_tasks_goal_date(goal_id,user_id,task_date),
 CONSTRAINT fk_ltask_goal FOREIGN KEY(goal_id) REFERENCES learning_goals(id), CONSTRAINT fk_ltask_user FOREIGN KEY(user_id) REFERENCES users(id),
 CONSTRAINT fk_ltask_phase FOREIGN KEY(phase_id) REFERENCES learning_phases(id), CONSTRAINT fk_ltask_concept FOREIGN KEY(concept_id) REFERENCES concepts(id), CONSTRAINT fk_ltask_chapter FOREIGN KEY(chapter_id) REFERENCES chapters(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS learning_checkpoint_attempts (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, task_id INT NOT NULL, milestone_id INT NULL, session_id INT NOT NULL UNIQUE, required_score DOUBLE NOT NULL, score DOUBLE, passed TINYINT(1),
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP, graded_at DATETIME NULL, INDEX ix_learning_checkpoint_task(task_id,id),
 CONSTRAINT fk_lca_task FOREIGN KEY(task_id) REFERENCES learning_tasks(id), CONSTRAINT fk_lca_mile FOREIGN KEY(milestone_id) REFERENCES learning_milestones(id), CONSTRAINT fk_lca_session FOREIGN KEY(session_id) REFERENCES quiz_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS micro_courses (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, subject_id INT NOT NULL, concept_id INT NOT NULL, title VARCHAR(255) NOT NULL, objective LONGTEXT, reason LONGTEXT,
 estimated_minutes INT DEFAULT 5, status VARCHAR(32) DEFAULT 'active', generation_model VARCHAR(255), evidence_chunk_ids LONGTEXT, weakness_snapshot LONGTEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_at DATETIME NULL, INDEX ix_micro_course_user(user_id,subject_id,concept_id,created_at),
 CONSTRAINT fk_mcourse_user FOREIGN KEY(user_id) REFERENCES users(id), CONSTRAINT fk_mcourse_subject FOREIGN KEY(subject_id) REFERENCES subjects(id), CONSTRAINT fk_mcourse_concept FOREIGN KEY(concept_id) REFERENCES concepts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS micro_course_steps (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, course_id INT NOT NULL, step_no INT NOT NULL, step_type VARCHAR(64) NOT NULL, title VARCHAR(255) NOT NULL, content LONGTEXT, question LONGTEXT,
 answer_key TEXT, explanation LONGTEXT, user_answer LONGTEXT, is_correct TINYINT(1), feedback LONGTEXT, status VARCHAR(32) DEFAULT 'planned', INDEX ix_micro_step_course(course_id,step_no),
 CONSTRAINT fk_mcstep_course FOREIGN KEY(course_id) REFERENCES micro_courses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS micro_course_messages (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, course_id INT NOT NULL, role VARCHAR(32) NOT NULL, content LONGTEXT NOT NULL, context_chunk_ids LONGTEXT, model_name VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_mcmsg_course FOREIGN KEY(course_id) REFERENCES micro_courses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS concept_change_log (id INT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,subject_id INT NOT NULL,old_name VARCHAR(255),new_name VARCHAR(255),action VARCHAR(40),created_at DATETIME DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
