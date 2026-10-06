"""TYE 模擬考、批閱、錯題簿與章節弱項分析模組。

設計原則：
- 路由由 app.py 統一註冊，避免組員互相修改主程式。
- 沿用既有 subjects / chapters / questions / quiz_sessions / quiz_answers / wrong_answers。
- 題目抽取在 Python 處理，避免依賴 SQLite RANDOM()，方便日後切換 MariaDB。
- 錯題 upsert 使用 select + insert/update，避免依賴 SQLite ON CONFLICT。
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from auth import login_required
from records import options
from storage import db

ALLOWED_MODES = ("練習", "模擬考", "錯題複習")
ALLOWED_TYPES = ("單選", "多選", "是非", "填空")
WEAKNESS_RECENT_LIMIT = 20
WEAKNESS_MIN_SAMPLE = 5


def _insert(table: str, data: dict):
    placeholders = ",".join("?" for _ in data)
    cursor = db().execute(
        f'INSERT INTO {table} ({",".join(data)}) VALUES ({placeholders})',
        tuple(data.values()),
    )
    return cursor.lastrowid


def _owned_subject(subject_id: int):
    row = db().execute(
        "SELECT * FROM subjects WHERE id=? AND created_by=?",
        (subject_id, g.user["id"]),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _owned_quiz(session_id: int):
    row = db().execute(
        "SELECT * FROM quiz_sessions WHERE id=? AND user_id=?",
        (session_id, g.user["id"]),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _chapters_for_user():
    return db().execute(
        """
        SELECT c.id, c.subject_id, c.chapter_name, c.order_no, s.subject_name
        FROM chapters c
        JOIN subjects s ON s.id=c.subject_id
        WHERE s.created_by=?
        ORDER BY s.subject_name, c.order_no, c.id
        """,
        (g.user["id"],),
    ).fetchall()


def _parse_id_list(values):
    ids = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError("章節設定格式錯誤。")
        if parsed not in ids:
            ids.append(parsed)
    return ids


def _normalize_answer(q_type: str, form_key: str):
    if q_type == "多選":
        return ",".join(sorted(set(request.form.getlist(form_key))))
    return request.form.get(form_key, "").strip()


def _question_snapshots(questions):
    """Build all question snapshots with one option query.

    The previous implementation queried options once per question (N+1).
    That is barely visible with local SQLite but becomes slow against a remote
    MariaDB over Tailscale.
    """
    if not questions:
        return []
    question_ids = [question["id"] for question in questions]
    placeholders = ",".join("?" for _ in question_ids)
    option_rows = db().execute(
        f"SELECT * FROM question_options WHERE question_id IN ({placeholders}) "
        "ORDER BY question_id, order_no, id",
        tuple(question_ids),
    ).fetchall()
    grouped = defaultdict(list)
    for row in option_rows:
        grouped[row["question_id"]].append(dict(row))

    snapshots = []
    for question in questions:
        snapshot = dict(question)
        snapshot["options"] = grouped.get(question["id"], [])
        snapshots.append(snapshot)
    return snapshots


def _candidate_questions(subject_id: int, chapter_ids: list[int], q_types: list[str], mode: str):
    sql = """
        SELECT q.*
        FROM questions q
        JOIN chapters c ON c.id=q.chapter_id
        JOIN subjects s ON s.id=c.subject_id
        WHERE c.subject_id=? AND s.created_by=?
    """
    params = [subject_id, g.user["id"]]

    # Fresh dynamic questions are historical snapshots, not a reusable fixed bank.
    # Exception: wrong-answer review intentionally needs the exact question again.
    if mode != "錯題複習":
        sql += " AND COALESCE(q.source,'manual') <> 'concept_dynamic'"

    if chapter_ids:
        sql += f" AND c.id IN ({','.join('?' for _ in chapter_ids)})"
        params.extend(chapter_ids)
    if q_types:
        sql += f" AND q.q_type IN ({','.join('?' for _ in q_types)})"
        params.extend(q_types)
    if mode == "錯題複習":
        sql += " AND q.id IN (SELECT question_id FROM wrong_answers WHERE user_id=? AND status='待複習')"
        params.append(g.user["id"])

    sql += " ORDER BY q.id"
    return list(db().execute(sql, tuple(params)).fetchall())


def _concept_source_count(subject_id: int, chapter_ids: list[int]) -> int:
    sql = """
        SELECT COUNT(*) AS n
        FROM source_question_items si
        WHERE si.user_id=? AND si.subject_id=?
    """
    params = [g.user["id"], subject_id]
    if chapter_ids:
        sql += f" AND si.chapter_id IN ({','.join('?' for _ in chapter_ids)})"
        params.extend(chapter_ids)
    row = db().execute(sql, tuple(params)).fetchone()
    return int(row["n"] if row else 0)


def _materialize_dynamic_questions(subject_id: int, chapter_ids: list[int], q_types: list[str], count: int):
    """Generate fresh Concept-based questions for one quiz and persist them only as history.

    These rows are tagged ``concept_dynamic`` and are never reused by the normal
    fixed-question sampler.  Persisting them gives grading/wrong-answer history a
    stable question_id while every new quiz still receives newly generated wording.
    """
    from personal_ai.services import generate_question_drafts
    from personal_ai.llm_provider import LLMError

    requested_types = q_types or list(ALLOWED_TYPES)
    created_questions = []
    remaining = count
    while remaining > 0:
        batch_size = min(10, remaining)
        try:
            draft_ids = generate_question_drafts(
                current_app.config, g.user["id"], subject_id, chapter_ids,
                batch_size, requested_types, 3,
                "本次模擬考：依 Concept/Skill 重新設計，不得只改數字或照抄來源題。",
            )
        except (LLMError, RuntimeError, ValueError) as exc:
            if created_questions:
                break
            raise ValueError(f"Concept 動態出題失敗：{exc}") from exc

        for draft_id in draft_ids:
            d = db().execute(
                "SELECT * FROM ai_question_drafts WHERE id=? AND user_id=?",
                (draft_id, g.user["id"]),
            ).fetchone()
            if not d:
                continue
            chapter_id = d["chapter_id"]
            if not chapter_id:
                if chapter_ids:
                    chapter_id = chapter_ids[0]
                else:
                    fallback = db().execute(
                        "SELECT id FROM chapters WHERE subject_id=? ORDER BY order_no,id LIMIT 1",
                        (subject_id,),
                    ).fetchone()
                    chapter_id = fallback["id"] if fallback else None
            if not chapter_id:
                raise ValueError("此科目尚無章節，無法建立動態考題。")

            qid = _insert("questions", {
                "chapter_id": chapter_id,
                "q_type": d["q_type"],
                "content": d["content"],
                "answer_key": d["answer_key"],
                "explanation": d["explanation"] or "",
                "difficulty": d["difficulty"] or 3,
                "source": "concept_dynamic",
            })
            opts = json.loads(d["options_json"] or "{}")
            for n, (label, text) in enumerate(opts.items(), 1):
                _insert("question_options", {
                    "question_id": qid, "option_label": label,
                    "option_text": text, "order_no": n,
                })
            _insert("question_metadata", {
                "question_id": qid,
                "source_type": "concept_dynamic",
                "generation_model": d["model_name"] or "",
                "evidence_chunk_ids": d["evidence_chunk_ids"] or "[]",
                "concepts_json": d["concepts_json"] or "[]",
                "skill": d["skill"] or "",
                "is_verified": 0,
            })
            try:
                concept_names = json.loads(d["concepts_json"] or "[]")
            except json.JSONDecodeError:
                concept_names = []
            for concept_name in concept_names:
                c = db().execute(
                    "SELECT id FROM concepts WHERE subject_id=? AND lower(name)=lower(?)",
                    (subject_id, str(concept_name)),
                ).fetchone()
                if c:
                    linked = db().execute(
                        "SELECT 1 FROM question_concepts WHERE question_id=? AND concept_id=?",
                        (qid, c["id"]),
                    ).fetchone()
                    if not linked:
                        db().execute(
                            "INSERT INTO question_concepts(question_id,concept_id,weight) VALUES (?,?,1)",
                            (qid, c["id"]),
                        )
            db().execute(
                "UPDATE ai_question_drafts SET status='quiz_generated',approved_question_id=? WHERE id=?",
                (qid, draft_id),
            )
            created_questions.append(db().execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone())
            if len(created_questions) >= count:
                break
        remaining = count - len(created_questions)
        if not draft_ids:
            break

    if len(created_questions) < count:
        raise ValueError(f"模型只產生 {len(created_questions)} 題可用題目，未達本次設定的 {count} 題，請重試或降低題數。")
    db().commit()
    return created_questions


def create_quiz(subject_id: int, count: int, mode: str, chapter_ids: list[int], q_types: list[str], random_order: bool, question_source: str = "auto", commit=True):
    """Create a quiz from Concept generation or, when unavailable, the legacy fixed bank."""
    _owned_subject(subject_id)
    if mode not in ALLOWED_MODES or not 1 <= count <= 100:
        raise ValueError("請選擇有效模式與 1–100 題；Concept 模式沒有固定題庫數量門檻。")
    if any(q_type not in ALLOWED_TYPES for q_type in q_types):
        raise ValueError("題型設定不正確。")
    if question_source not in ("auto", "bank_random"):
        raise ValueError("出題方式設定不正確。")
    if question_source == "bank_random":
        random_order = True

    if chapter_ids:
        rows = db().execute(
            f"""
            SELECT c.id
            FROM chapters c
            JOIN subjects s ON s.id=c.subject_id
            WHERE c.subject_id=? AND s.created_by=?
              AND c.id IN ({','.join('?' for _ in chapter_ids)})
            """,
            (subject_id, g.user["id"], *chapter_ids),
        ).fetchall()
        if {row["id"] for row in rows} != set(chapter_ids):
            raise ValueError("選取的章節不屬於目前科目，請重新設定。")

    # Wrong-answer review intentionally reuses the exact question the learner got wrong.
    # Normal practice/mock exams prefer Concept-based fresh generation whenever concept
    # source samples exist in the selected scope.
    if question_source == "auto" and mode != "錯題複習" and _concept_source_count(subject_id, chapter_ids) > 0:
        chosen = _materialize_dynamic_questions(subject_id, chapter_ids, q_types, count)
    else:
        candidates = _candidate_questions(subject_id, chapter_ids, q_types, mode)
        available = len(candidates)
        if available < count:
            label = "待複習錯題" if mode == "錯題複習" else "固定題庫題目"
            if mode == "錯題複習":
                raise ValueError(f"目前{label}只有 {available} 題；錯題複習會保留原題，因此不能憑空補題。")
            if question_source == "bank_random":
                raise ValueError(
                    f"選取範圍的固定題庫只有 {available} 題，無法抽出 {count} 題。"
                    "請降低題數、擴大範圍，或匯入固定題庫；普通隨機出題不會呼叫 AI 補題。"
                )
            raise ValueError(
                f"目前沒有可用的 Concept 來源樣本，且{label}只有 {available} 題。"
                "請先用概念型匯入建立 Concept，或使用傳統題庫匯入。"
            )
        chosen = random.sample(candidates, count) if random_order else candidates[:count]

    snapshots = _question_snapshots(chosen)

    # Reject malformed imported questions before creating the exam.  Single and
    # multiple choice questions must have at least two selectable options and
    # every answer label must exist in those options.
    malformed = []
    for snapshot in snapshots:
        if snapshot["q_type"] in ("單選", "多選"):
            labels = {str(option["option_label"]).strip() for option in snapshot["options"]}
            answers = {part.strip() for part in str(snapshot.get("answer_key", "")).split(",") if part.strip()}
            if len(labels) < 2 or not answers or not answers.issubset(labels):
                malformed.append(snapshot["id"])
    if malformed:
        raise ValueError("題庫資料不完整，請先修正題目 #" + ", #".join(map(str, malformed)) + " 的選項或答案。")

    session_id = _insert(
        "quiz_sessions",
        {
            "user_id": g.user["id"],
            "subject_id": subject_id,
            "mode": mode,
            "total_count": count,
        },
    )
    db().executemany(
        "INSERT INTO quiz_answers (session_id,question_id,question_snapshot) VALUES (?,?,?)",
        [
            (session_id, question["id"], json.dumps(snapshot, ensure_ascii=False))
            for question, snapshot in zip(chosen, snapshots)
        ],
    )
    if commit: db().commit()
    return session_id


def add_wrong_question(user_id: int, question_id: int):
    """可攜式錯題累計，不使用 SQLite ON CONFLICT。"""
    row = db().execute(
        "SELECT wrong_count FROM wrong_answers WHERE user_id=? AND question_id=?",
        (user_id, question_id),
    ).fetchone()
    if row:
        db().execute(
            """
            UPDATE wrong_answers
            SET wrong_count=?, last_wrong_at=CURRENT_TIMESTAMP, status='待複習'
            WHERE user_id=? AND question_id=?
            """,
            (row["wrong_count"] + 1, user_id, question_id),
        )
    else:
        db().execute(
            """
            INSERT INTO wrong_answers(user_id,question_id,wrong_count,last_wrong_at,status)
            VALUES (?,?,1,CURRENT_TIMESTAMP,'待複習')
            """,
            (user_id, question_id),
        )


def grade_quiz(session_id: int):
    """批閱一份考卷。重複交卷不重新計分或累加錯題。"""
    from storage import locked_sql
    from personal_ai.question_validation import correct as answer_correct
    db().execute('BEGIN IMMEDIATE')
    exam = db().execute(locked_sql('SELECT * FROM quiz_sessions WHERE id=? AND user_id=?'),(session_id,g.user['id'])).fetchone()
    if not exam:
        abort(404)
    if exam["finished_at"]:
        from personal_ai.coaching import apply_planner_quiz_result
        apply_planner_quiz_result(g.user['id'],session_id)
        return False

    answers = db().execute(
        "SELECT * FROM quiz_answers WHERE session_id=? ORDER BY id", (session_id,)
    ).fetchall()
    if not answers:
        raise ValueError("此考卷沒有題目，無法交卷。")

    prepared = []
    for row in answers:
        snapshot = json.loads(row["question_snapshot"])
        answer = _normalize_answer(snapshot["q_type"], f'answer_{row["id"]}')
        if len(answer) > 50:
            raise ValueError("答案不可超過 50 字。")
        prepared.append((row, snapshot, answer))

    correct = 0
    for row, snapshot, answer in prepared:
        if answer and snapshot['q_type'] in ('單選','多選'):
            labels={str(o['option_label']) for o in snapshot['options']}
            if not set(answer.split(',')).issubset(labels):
                raise ValueError('作答包含不存在的選項。')
        # Blank answers are valid submissions and receive zero credit.
        is_correct = bool(answer) and answer_correct(snapshot['q_type'],answer,snapshot.get('answer_key',''))
        correct += int(is_correct)
        db().execute(
            """
            UPDATE quiz_answers
            SET user_answer=?, is_correct=?, answered_at=CURRENT_TIMESTAMP
            WHERE id=? AND session_id=?
            """,
            (answer, int(is_correct), row["id"], session_id),
        )
        if not is_correct:
            add_wrong_question(g.user["id"], snapshot["id"])
        elif exam["mode"] == "錯題複習":
            db().execute(
                "UPDATE wrong_answers SET status='已克服' WHERE user_id=? AND question_id=?",
                (g.user["id"], snapshot["id"]),
            )

    db().execute(
        "UPDATE quiz_sessions SET correct_count=?, finished_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
        (correct, session_id, g.user["id"]),
    )

    # Planner-linked quizzes are scored gates. The learner cannot manually mark
    # them complete; this hook decides pass/fail from the submitted quiz score.
    try:
        from personal_ai.coaching import apply_planner_quiz_result
        outcome = apply_planner_quiz_result(g.user["id"], session_id, commit=False)
        if outcome:
            if outcome['passed']:
                flash(f"學習規劃驗收通過：{outcome['score']:.1f} 分（門檻 {outcome['required_score']:.0f} 分）。", "success")
            else:
                flash(f"本次尚未達標：{outcome['score']:.1f} 分（門檻 {outcome['required_score']:.0f} 分）。請補強後重新挑戰。", "error")
    except Exception as exc:
        db().rollback()
        raise ValueError("交卷與規劃更新未完成，資料已回復，請重新交卷。") from exc
    db().commit()
    return True


def get_wrong_book(user_id: int):
    rows = db().execute(
        """
        SELECT w.*, q.content, q.q_type, q.answer_key, q.explanation,
               c.chapter_name, s.subject_name
        FROM wrong_answers w
        JOIN questions q ON q.id=w.question_id
        JOIN chapters c ON c.id=q.chapter_id
        JOIN subjects s ON s.id=c.subject_id
        WHERE w.user_id=? AND s.created_by=?
        ORDER BY w.last_wrong_at DESC
        """,
        (user_id, user_id),
    ).fetchall()
    if not rows:
        return []

    # One query for all historical wrong answers instead of one query per row.
    question_ids = [row["question_id"] for row in rows]
    placeholders = ",".join("?" for _ in question_ids)
    history = db().execute(
        f"""
        SELECT a.question_id, a.user_answer, a.question_snapshot, a.answered_at, a.id
        FROM quiz_answers a
        JOIN quiz_sessions qs ON qs.id=a.session_id
        WHERE qs.user_id=? AND a.is_correct=0
          AND a.question_id IN ({placeholders})
        ORDER BY a.question_id, a.answered_at DESC, a.id DESC
        """,
        (user_id, *question_ids),
    ).fetchall()
    latest_by_question = {}
    for item in history:
        latest_by_question.setdefault(item["question_id"], item)

    output = []
    for row in rows:
        item = dict(row)
        latest = latest_by_question.get(row["question_id"])
        if latest:
            snapshot = json.loads(latest["question_snapshot"])
            item["last_wrong_answer"] = latest["user_answer"] or "未作答"
            item["snapshot_answer_key"] = snapshot.get("answer_key", row["answer_key"])
        else:
            item["last_wrong_answer"] = "—"
            item["snapshot_answer_key"] = row["answer_key"]
        output.append(item)
    return output


def calculate_chapter_stats(user_id: int, recent_limit: int = WEAKNESS_RECENT_LIMIT):
    """每章只採最近 N 次作答，回傳由弱到強的統計。"""
    rows = db().execute(
        """
        SELECT s.id AS subject_id, s.subject_name,
               c.id AS chapter_id, c.chapter_name,
               a.is_correct, a.answered_at, a.id AS answer_id
        FROM quiz_answers a
        JOIN quiz_sessions qs ON qs.id=a.session_id
        JOIN questions q ON q.id=a.question_id
        JOIN chapters c ON c.id=q.chapter_id
        JOIN subjects s ON s.id=c.subject_id
        WHERE qs.user_id=? AND qs.finished_at IS NOT NULL
          AND a.answered_at IS NOT NULL AND s.created_by=?
        ORDER BY c.id, a.answered_at DESC, a.id DESC
        """,
        (user_id, user_id),
    ).fetchall()

    grouped = defaultdict(list)
    metadata = {}
    for row in rows:
        key = row["chapter_id"]
        metadata[key] = (row["subject_name"], row["chapter_name"])
        if len(grouped[key]) < recent_limit:
            grouped[key].append(int(row["is_correct"] or 0))

    stats = []
    for chapter_id, values in grouped.items():
        total = len(values)
        correct = sum(values)
        wrong = total - correct
        accuracy = (correct / total * 100) if total else 0.0
        subject_name, chapter_name = metadata[chapter_id]
        stats.append(
            {
                "chapter_id": chapter_id,
                "subject_name": subject_name,
                "chapter_name": chapter_name,
                "n": total,
                "correct": correct,
                "wrong": wrong,
                "accuracy": accuracy,
                "insufficient": total < WEAKNESS_MIN_SAMPLE,
            }
        )
    stats.sort(key=lambda row: (row["accuracy"], row["n"], row["chapter_name"]))
    return stats


def register_tye_exam(app):
    """由 app.py 呼叫，註冊 TYE 負責的所有考試功能。"""

    @app.route("/quiz", methods=["GET", "POST"], endpoint="quiz_start")
    @login_required
    def quiz_start():
        error = None
        selected = {
            "subject_id": request.form.get("subject_id", ""),
            "mode": request.form.get("mode", "模擬考"),
            "count": request.form.get("count", "5"),
            "chapter_ids": request.form.getlist("chapter_ids"),
            "q_types": request.form.getlist("q_types"),
            "random_order": request.form.get("random_order", "1"),
            "question_source": request.form.get("question_source", "auto"),
        }
        if request.method=='GET' and request.args.get('subject_id',type=int):
            subject_id=request.args.get('subject_id',type=int)
            _owned_subject(subject_id)
            try:
                scope=_parse_id_list(request.args.getlist('chapter_ids'))
            except ValueError:
                abort(400)
            allowed={r['id'] for r in db().execute('SELECT id FROM chapters WHERE subject_id=?',(subject_id,))}
            if not set(scope)<=allowed:
                abort(404)
            selected['subject_id']=str(subject_id)
            selected['chapter_ids']=[str(cid) for cid in scope]
            if request.args.get('question_source')=='bank_random':
                selected['question_source']='bank_random'
        if request.method == "POST":
            try:
                subject_id = int(request.form.get("subject_id", "0"))
                count = int(request.form.get("count", "5"))
                chapter_ids = _parse_id_list(request.form.getlist("chapter_ids"))
                q_types = request.form.getlist("q_types")
                random_order = request.form.get("random_order", "1") == "1"
                from personal_ai.jobs import submit
                if selected['question_source']=='auto' and selected['mode']!='錯題複習' and _concept_source_count(subject_id,chapter_ids)>0:
                    job_id=submit(current_app._get_current_object(),g.user['id'],'quiz',dict(subject_id=subject_id,count=count,mode=selected['mode'],chapter_ids=chapter_ids,q_types=q_types,random_order=random_order,question_source='auto'))
                    return redirect(url_for('personal_ai.job_page',job_id=job_id))
                session_id=create_quiz(subject_id,count,selected['mode'],chapter_ids,q_types,random_order,question_source=selected['question_source'])
                return redirect(url_for("quiz_take", sid=session_id))
            except ValueError as exc:
                db().rollback()
                error = str(exc)

        sessions = db().execute(
            """
            SELECT qs.*, s.subject_name
            FROM quiz_sessions qs
            JOIN subjects s ON s.id=qs.subject_id
            WHERE qs.user_id=?
            ORDER BY qs.id DESC
            """,
            (g.user["id"],),
        ).fetchall()
        return render_template(
            "quiz_start.html",
            title="模擬考試",
            subjects=options(db(), "subjects", g.user["id"]),
            chapters=_chapters_for_user(),
            question_types=ALLOWED_TYPES,
            sessions=sessions,
            selected=selected,
            error=error,
        )

    @app.route("/quiz/<int:sid>", methods=["GET", "POST"], endpoint="quiz_take")
    @login_required
    def quiz_take(sid):
        exam = _owned_quiz(sid)
        if request.method == "POST":
            try:
                if not grade_quiz(sid):
                    flash("此考卷已經交卷，不會重複計分。", "info")
                return redirect(url_for("quiz_take", sid=sid))
            except ValueError as exc:
                db().rollback()
                flash(str(exc), "error")
                return redirect(url_for("quiz_take", sid=sid))

        exam = _owned_quiz(sid)
        items = []
        for row in db().execute(
            "SELECT * FROM quiz_answers WHERE session_id=? ORDER BY id", (sid,)
        ):
            snapshot = json.loads(row["question_snapshot"])
            if not exam["finished_at"]:
                snapshot.pop("answer_key", None)
                snapshot.pop("explanation", None)
            items.append((row, snapshot))
        planner_attempt = db().execute("""SELECT lca.*,lt.goal_id,lt.title task_title
            FROM learning_checkpoint_attempts lca JOIN learning_tasks lt ON lt.id=lca.task_id
            WHERE lca.session_id=? AND lt.user_id=?""",(sid,g.user['id'])).fetchone()
        from storage import MariaConnection
        # Use the database's own clock, avoiding browser/server timezone ambiguity.
        elapsed_expression = ("GREATEST(0,TIMESTAMPDIFF(SECOND,started_at,COALESCE(finished_at,CURRENT_TIMESTAMP)))"
                              if isinstance(db(), MariaConnection) else
                              "MAX(0,CAST((julianday(COALESCE(finished_at,CURRENT_TIMESTAMP))-julianday(started_at))*86400 AS INTEGER))")
        elapsed = db().execute(f'SELECT {elapsed_expression} AS seconds FROM quiz_sessions WHERE id=? AND user_id=?',
                               (sid,g.user['id'])).fetchone()
        return render_template(
            "quiz_take.html",
            title="考試結果" if exam["finished_at"] else "作答中",
            exam=exam,
            items=items,
            planner_attempt=planner_attempt,
            elapsed_seconds=int(elapsed['seconds'] or 0),
        )

    @app.get("/results", endpoint="results")
    @login_required
    def results():
        sessions = db().execute(
            """
            SELECT qs.*, s.subject_name
            FROM quiz_sessions qs
            JOIN subjects s ON s.id=qs.subject_id
            WHERE qs.user_id=? AND qs.finished_at IS NOT NULL
            ORDER BY qs.id DESC
            """,
            (g.user["id"],),
        ).fetchall()
        return render_template(
            "results.html",
            title="成績與錯題簿",
            wrong=get_wrong_book(g.user["id"]),
            sessions=sessions,
        )

    @app.get("/analysis", endpoint="analysis")
    @login_required
    def analysis():
        return render_template(
            "analysis.html",
            title="章節弱項分析",
            rows=calculate_chapter_stats(g.user["id"]),
            recent_limit=WEAKNESS_RECENT_LIMIT,
            minimum_sample=WEAKNESS_MIN_SAMPLE,
        )
