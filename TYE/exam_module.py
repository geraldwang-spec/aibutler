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

from flask import abort, flash, g, redirect, render_template, request, url_for

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


def _question_snapshot(question):
    snapshot = dict(question)
    snapshot["options"] = [
        dict(row)
        for row in db().execute(
            "SELECT * FROM question_options WHERE question_id=? ORDER BY order_no, id",
            (question["id"],),
        ).fetchall()
    ]
    return snapshot


def _candidate_questions(subject_id: int, chapter_ids: list[int], q_types: list[str], mode: str):
    sql = """
        SELECT q.*
        FROM questions q
        JOIN chapters c ON c.id=q.chapter_id
        JOIN subjects s ON s.id=c.subject_id
        WHERE c.subject_id=? AND s.created_by=?
    """
    params = [subject_id, g.user["id"]]

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


def create_quiz(subject_id: int, count: int, mode: str, chapter_ids: list[int], q_types: list[str], random_order: bool):
    """依使用者設定建立固定題目快照；題目不足時拒絕建立。"""
    _owned_subject(subject_id)
    if mode not in ALLOWED_MODES or not 1 <= count <= 100:
        raise ValueError("請選擇有效模式與 1–100 題。")
    if any(q_type not in ALLOWED_TYPES for q_type in q_types):
        raise ValueError("題型設定不正確。")

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

    candidates = _candidate_questions(subject_id, chapter_ids, q_types, mode)
    available = len(candidates)
    if available < count:
        label = "待複習錯題" if mode == "錯題複習" else "符合條件的題目"
        raise ValueError(f"目前{label}只有 {available} 題，無法建立 {count} 題的模擬考。")

    chosen = random.sample(candidates, count) if random_order else candidates[:count]
    session_id = _insert(
        "quiz_sessions",
        {
            "user_id": g.user["id"],
            "subject_id": subject_id,
            "mode": mode,
            "total_count": count,
        },
    )
    for question in chosen:
        snapshot = _question_snapshot(question)
        _insert(
            "quiz_answers",
            {
                "session_id": session_id,
                "question_id": question["id"],
                "question_snapshot": json.dumps(snapshot, ensure_ascii=False),
            },
        )
    db().commit()
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
    exam = _owned_quiz(session_id)
    if exam["finished_at"]:
        return False

    answers = db().execute(
        "SELECT * FROM quiz_answers WHERE session_id=? ORDER BY id", (session_id,)
    ).fetchall()
    if not answers:
        raise ValueError("此考卷沒有題目，無法交卷。")

    prepared = []
    missing = 0
    for row in answers:
        snapshot = json.loads(row["question_snapshot"])
        answer = _normalize_answer(snapshot["q_type"], f'answer_{row["id"]}')
        if len(answer) > 50:
            raise ValueError("答案不可超過 50 字。")
        if not answer:
            missing += 1
        prepared.append((row, snapshot, answer))
    if missing:
        raise ValueError(f"尚有 {missing} 題未作答，請完成後再交卷。")

    correct = 0
    for row, snapshot, answer in prepared:
        is_correct = answer == str(snapshot.get("answer_key", "")).strip()
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

    output = []
    for row in rows:
        item = dict(row)
        latest = db().execute(
            """
            SELECT a.user_answer, a.question_snapshot
            FROM quiz_answers a
            JOIN quiz_sessions qs ON qs.id=a.session_id
            WHERE qs.user_id=? AND a.question_id=? AND a.is_correct=0
            ORDER BY a.answered_at DESC, a.id DESC
            LIMIT 1
            """,
            (user_id, row["question_id"]),
        ).fetchone()
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
            "count": request.form.get("count", "10"),
            "chapter_ids": request.form.getlist("chapter_ids"),
            "q_types": request.form.getlist("q_types"),
            "random_order": request.form.get("random_order", "1"),
        }
        if request.method == "POST":
            try:
                subject_id = int(request.form.get("subject_id", "0"))
                count = int(request.form.get("count", "10"))
                chapter_ids = _parse_id_list(request.form.getlist("chapter_ids"))
                q_types = request.form.getlist("q_types")
                random_order = request.form.get("random_order", "1") == "1"
                session_id = create_quiz(
                    subject_id,
                    count,
                    request.form.get("mode", "模擬考"),
                    chapter_ids,
                    q_types,
                    random_order,
                )
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
        return render_template(
            "quiz_take.html",
            title="考試結果" if exam["finished_at"] else "作答中",
            exam=exam,
            items=items,
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
