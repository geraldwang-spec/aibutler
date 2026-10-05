-- TYE / Personal AI extension tables only.
-- Do not place BODY-owned tables in this file.

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
