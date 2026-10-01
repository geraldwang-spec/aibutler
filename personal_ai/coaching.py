from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

from flask import current_app

from storage import db
from .llm_provider import model_usage_label, get_llm, LLMError
from .rag import retrieve

RECENT_CONCEPT_LIMIT = 20
MIN_CONCEPT_SAMPLE = 3


def calculate_concept_weakness(user_id: int, subject_id: int | None = None, recent_limit: int = RECENT_CONCEPT_LIMIT):
    """Recent-weighted mastery by Concept.

    The newest answer has weight 1.0 and older answers decay gradually.  This is
    intentionally algorithmic; the LLM may explain the result later, but it does
    not decide whether the learner is weak or strong.
    """
    sql = """
        SELECT co.id concept_id, co.name concept_name, co.chapter_id,
               ch.chapter_name, s.id subject_id, s.subject_name,
               qa.is_correct, qa.answered_at, qa.id answer_id,
               qm.skill
        FROM quiz_answers qa
        JOIN quiz_sessions qs ON qs.id=qa.session_id
        JOIN questions q ON q.id=qa.question_id
        JOIN question_concepts qc ON qc.question_id=q.id
        JOIN concepts co ON co.id=qc.concept_id
        JOIN subjects s ON s.id=co.subject_id
        LEFT JOIN chapters ch ON ch.id=co.chapter_id
        LEFT JOIN question_metadata qm ON qm.question_id=q.id
        WHERE qs.user_id=? AND qs.finished_at IS NOT NULL AND s.created_by=?
    """
    params = [user_id, user_id]
    if subject_id:
        sql += " AND s.id=?"
        params.append(subject_id)
    sql += " ORDER BY co.id, qa.answered_at DESC, qa.id DESC"
    rows = db().execute(sql, tuple(params)).fetchall()

    grouped: dict[int, list] = defaultdict(list)
    meta = {}
    skill_groups: dict[tuple[int, str], list] = defaultdict(list)
    for row in rows:
        cid = int(row["concept_id"])
        meta[cid] = dict(row)
        if len(grouped[cid]) < recent_limit:
            grouped[cid].append(int(row["is_correct"] or 0))
        skill = (row["skill"] or "").strip()
        if skill and len(skill_groups[(cid, skill)]) < recent_limit:
            skill_groups[(cid, skill)].append(int(row["is_correct"] or 0))

    # Also expose concepts that have source examples but no completed answers yet.
    unseen_sql = """
        SELECT DISTINCT co.id concept_id, co.name concept_name, co.chapter_id,
               ch.chapter_name, s.id subject_id, s.subject_name
        FROM concepts co
        JOIN subjects s ON s.id=co.subject_id
        LEFT JOIN chapters ch ON ch.id=co.chapter_id
        JOIN source_question_items si ON si.concept_id=co.id AND si.user_id=?
        WHERE s.created_by=?
    """
    unseen_params = [user_id, user_id]
    if subject_id:
        unseen_sql += " AND s.id=?"
        unseen_params.append(subject_id)
    for row in db().execute(unseen_sql, tuple(unseen_params)).fetchall():
        cid = int(row["concept_id"])
        meta.setdefault(cid, dict(row))
        grouped.setdefault(cid, [])

    out = []
    for cid, m in meta.items():
        values = grouped.get(cid, [])
        if values:
            weights = [0.88 ** i for i in range(len(values))]
            weighted = sum(v * w for v, w in zip(values, weights)) / sum(weights) * 100
            raw = sum(values) / len(values) * 100
        else:
            weighted = None
            raw = None
        sample = len(values)
        if weighted is None:
            priority = "尚未測驗"
            score_for_sort = 45.0
        elif sample < MIN_CONCEPT_SAMPLE:
            priority = "資料不足"
            score_for_sort = weighted
        elif weighted < 60:
            priority = "優先補強"
            score_for_sort = weighted
        elif weighted < 80:
            priority = "持續練習"
            score_for_sort = weighted
        else:
            priority = "穩定掌握"
            score_for_sort = weighted

        skills = []
        for (concept_id, skill), sv in skill_groups.items():
            if concept_id != cid:
                continue
            sw = [0.88 ** i for i in range(len(sv))]
            sscore = sum(v * w for v, w in zip(sv, sw)) / sum(sw) * 100
            skills.append({"name": skill, "accuracy": round(sscore, 1), "n": len(sv)})
        skills.sort(key=lambda x: (x["accuracy"], -x["n"], x["name"]))

        out.append({
            "concept_id": cid,
            "concept_name": m["concept_name"],
            "chapter_id": m.get("chapter_id"),
            "chapter_name": m.get("chapter_name") or "未指定章節",
            "subject_id": int(m["subject_id"]),
            "subject_name": m["subject_name"],
            "n": sample,
            "raw_accuracy": None if raw is None else round(raw, 1),
            "mastery": None if weighted is None else round(weighted, 1),
            "priority": priority,
            "skills": skills[:5],
            "_sort": score_for_sort,
        })
    out.sort(key=lambda x: (x["_sort"], x["n"], x["concept_name"]))
    return out


def wrong_question_context(user_id: int, question_id: int):
    row = db().execute(
        """
        SELECT w.*, q.content, q.q_type, q.answer_key, q.explanation, q.chapter_id,
               c.chapter_name, s.id subject_id, s.subject_name,
               qm.skill, qm.concepts_json
        FROM wrong_answers w
        JOIN questions q ON q.id=w.question_id
        JOIN chapters c ON c.id=q.chapter_id
        JOIN subjects s ON s.id=c.subject_id
        LEFT JOIN question_metadata qm ON qm.question_id=q.id
        WHERE w.user_id=? AND q.id=? AND s.created_by=?
        """,
        (user_id, question_id, user_id),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    latest = db().execute(
        """
        SELECT qa.user_answer,qa.question_snapshot,qa.answered_at
        FROM quiz_answers qa JOIN quiz_sessions qs ON qs.id=qa.session_id
        WHERE qs.user_id=? AND qa.question_id=? AND qa.is_correct=0
        ORDER BY qa.answered_at DESC,qa.id DESC LIMIT 1
        """,
        (user_id, question_id),
    ).fetchone()
    item["last_wrong_answer"] = latest["user_answer"] if latest else ""
    if latest:
        try:
            snap = json.loads(latest["question_snapshot"] or "{}")
            item["options"] = snap.get("options", [])
        except json.JSONDecodeError:
            item["options"] = []
    else:
        item["options"] = []
    concepts = db().execute(
        """SELECT co.id,co.name FROM question_concepts qc JOIN concepts co ON co.id=qc.concept_id
             WHERE qc.question_id=? ORDER BY qc.weight DESC,co.name""",
        (question_id,),
    ).fetchall()
    item["concepts"] = [dict(c) for c in concepts]
    return item


def _ensure_tutor_thread(user_id: int, question_id: int):
    row = db().execute(
        "SELECT id FROM tutor_threads WHERE user_id=? AND question_id=? ORDER BY id DESC LIMIT 1",
        (user_id, question_id),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = db().execute(
        "INSERT INTO tutor_threads(user_id,question_id) VALUES (?,?)", (user_id, question_id)
    )
    db().commit()
    return cur.lastrowid


def _save_tutor_message(thread_id: int, role: str, content: str, chunk_ids=None):
    db().execute(
        "INSERT INTO tutor_messages(thread_id,role,content,context_chunk_ids) VALUES (?,?,?,?)",
        (thread_id, role, content, json.dumps(chunk_ids or [])),
    )
    db().commit()


def tutor_history(user_id: int, question_id: int):
    row = db().execute(
        "SELECT id FROM tutor_threads WHERE user_id=? AND question_id=? ORDER BY id DESC LIMIT 1",
        (user_id, question_id),
    ).fetchone()
    if not row:
        return []
    return [dict(x) for x in db().execute(
        "SELECT * FROM tutor_messages WHERE thread_id=? ORDER BY id", (row["id"],)
    ).fetchall()]


def answer_wrong_question(user_id: int, question_id: int, followup: str = ""):
    q = wrong_question_context(user_id, question_id)
    if not q:
        raise ValueError("找不到這筆錯題。")
    concept_names = [c["name"] for c in q["concepts"]]
    query = " ".join(concept_names + [q.get("skill") or "", q["content"], followup]).strip()
    chunks = retrieve(user_id, q["subject_id"], query, [q["chapter_id"]], limit=6)
    chunk_ids = [int(c["id"]) for c in chunks]
    evidence = "\n\n".join(
        f"[chunk:{c['id']}] {c['section_title'] or c['material_title']}\n{c['content']}" for c in chunks
    )
    thread_id = _ensure_tutor_thread(user_id, question_id)
    if followup:
        _save_tutor_message(thread_id, "user", followup, chunk_ids)

    llm = get_llm(current_app.config)
    # DEV mode stays useful without pretending a model performed reasoning.
    if not llm.enabled or getattr(llm, "provider", "") == "mock":
        pieces = []
        if q.get("explanation"):
            pieces.append("題庫解析：" + q["explanation"])
        pieces.append(f"你的答案：{q.get('last_wrong_answer') or '未記錄'}；正確答案：{q['answer_key']}。")
        if chunks:
            pieces.append("教材相關內容：" + " / ".join((c["content"][:220].replace("\n", " ")) for c in chunks[:2]))
        if followup:
            pieces.append("DEV 模式尚未啟用真 LLM，因此追問只顯示可追溯教材內容；切換 Ollama 後會依這些 chunks 回答。")
        else:
            pieces.append("建議先重新說明這題的關鍵條件，再用同一 Concept 做一題不同情境的練習。")
        answer = "\n\n".join(pieces)
        mode = "DEV 來源式解說"
    else:
        history = tutor_history(user_id, question_id)[-8:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
        system = (
            "你是錯題教學助理。只能依題目、正確答案、題庫解析與提供的教材 RAG 證據回答。"
            "若證據不足，明確說教材中沒有足夠依據，不可自行補充未提供的事實。"
            "用繁體中文，先指出錯誤關鍵，再分步說明；追問也必須維持相同證據限制。只回 JSON。"
        )
        user = json.dumps({
            "question": q["content"],
            "question_type": q["q_type"],
            "user_answer": q.get("last_wrong_answer"),
            "correct_answer": q["answer_key"],
            "question_explanation": q.get("explanation"),
            "concepts": concept_names,
            "skill": q.get("skill"),
            "evidence": evidence,
            "conversation": history_text,
            "followup": followup,
        }, ensure_ascii=False)
        user += '\n回傳 {"answer":"..."}。'
        try:
            data = llm.complete_json(system, user)
            answer = str(data.get("answer") or "").strip()
            if not answer:
                raise LLMError("Tutor 回傳空白內容。")
            mode = model_usage_label(llm)
        except LLMError as exc:
            raise ValueError(str(exc)) from exc

    _save_tutor_message(thread_id, "assistant", answer, chunk_ids)
    return {"answer": answer, "chunks": [dict(c) for c in chunks], "mode": mode, "question": q}


def _planner_concepts(user_id: int, subject_id: int, chapter_ids: list[int]):
    """Return ordered Concepts with current mastery metadata for the goal planner."""
    weakness = calculate_concept_weakness(user_id, subject_id)
    if chapter_ids:
        weakness = [w for w in weakness if w.get("chapter_id") in chapter_ids]
    if weakness:
        return weakness

    # A goal can still be created before any quiz history exists.
    sql = """
        SELECT co.id concept_id, co.name concept_name, co.chapter_id,
               ch.chapter_name
        FROM concepts co
        LEFT JOIN chapters ch ON ch.id=co.chapter_id
        WHERE co.subject_id=?
    """
    params = [subject_id]
    if chapter_ids:
        sql += " AND co.chapter_id IN (" + ",".join("?" for _ in chapter_ids) + ")"
        params.extend(chapter_ids)
    sql += " ORDER BY COALESCE(ch.order_no,0), co.id"
    rows = db().execute(sql, tuple(params)).fetchall()
    if rows:
        return [{
            "concept_id": int(r["concept_id"]),
            "concept_name": r["concept_name"],
            "chapter_id": r["chapter_id"],
            "chapter_name": r["chapter_name"],
            "mastery": None,
            "priority": "尚未測驗",
            "_sort": 50.0,
        } for r in rows]

    # Last fallback: use chapter names as planning units until Concepts are imported.
    sql = "SELECT id chapter_id, chapter_name FROM chapters WHERE subject_id=?"
    params = [subject_id]
    if chapter_ids:
        sql += " AND id IN (" + ",".join("?" for _ in chapter_ids) + ")"
        params.extend(chapter_ids)
    sql += " ORDER BY order_no,id"
    rows = db().execute(sql, tuple(params)).fetchall()
    return [{
        "concept_id": None,
        "concept_name": r["chapter_name"],
        "chapter_id": r["chapter_id"],
        "chapter_name": r["chapter_name"],
        "mastery": None,
        "priority": "尚未建立 Concept",
        "_sort": 45.0,
    } for r in rows]


def _phase_blueprint(total_days: int):
    """Build high-level learning phases. The final phase is always protected review/buffer time."""
    if total_days <= 6:
        return [("短期衝刺與緩衝", 1.0, 75, "核心弱項、Checkpoint 與考前整理") ]
    if total_days <= 13:
        return [
            ("核心學習", .60, 70, "完成最重要的核心範圍"),
            ("考前衝刺與緩衝", .40, 78, "Checkpoint、弱項補強與模擬"),
        ]
    if total_days <= 21:
        return [
            ("核心學習", .45, 70, "完成核心範圍並通過基礎 Checkpoint"),
            ("整合練習", .30, 78, "能將多個 Concept 綜合應用"),
            ("考前衝刺與緩衝", .25, 82, "完成弱項補強與至少一次完整模擬"),
        ]
    if total_days <= 60:
        return [
            ("基礎建立", .25, 70, "建立主要 Concept 的基本理解"),
            ("核心能力", .30, 75, "完成核心範圍並能獨立解題"),
            ("整合應用", .25, 80, "跨章節綜合應用與除錯"),
            ("模擬與緩衝", .20, 85, "弱項補強、完整模擬與考前緩衝"),
        ]
    return [
        ("基礎建立", .20, 70, "完成基礎 Concept，建立必要先備知識"),
        ("核心能力", .25, 75, "核心範圍達到可獨立解題程度"),
        ("進階與應用", .20, 78, "能處理應用、情境與除錯題"),
        ("整合實戰", .20, 82, "跨 Concept 綜合解題並穩定達標"),
        ("模擬考與緩衝", .15, 85, "保留補進度、弱項重練與完整模擬時間"),
    ]


def _allocate_phase_dates(start: date, exam_date: date, blueprint):
    total = (exam_date - start).days
    remaining = total
    cursor = start
    result = []
    for idx, item in enumerate(blueprint):
        name, ratio, mastery, objective = item
        if idx == len(blueprint)-1:
            days = remaining
        else:
            days = max(2, round(total * ratio))
            # keep at least two days for every future phase
            max_days = remaining - 2 * (len(blueprint)-idx-1)
            days = min(days, max_days)
        end = cursor + timedelta(days=max(0, days-1))
        result.append((idx+1, name, cursor, end, mastery, objective))
        cursor = end + timedelta(days=1)
        remaining = (exam_date - cursor).days
    # Never schedule learning work on exam day itself.
    if result:
        seq,name,st,_,mastery,obj=result[-1]
        result[-1]=(seq,name,st,exam_date-timedelta(days=1),mastery,obj)
    return result


def create_learning_goal_plan(user_id: int, subject_id: int, goal_name: str, exam_date: date,
                              chapter_ids: list[int], weekday_minutes: int, weekend_minutes: int,
                              starting_level: str = "auto"):
    goal_name=(goal_name or "").strip()
    if not goal_name:
        raise ValueError("請輸入學習目標，例如：TQC Python 證照。")
    today=date.today()
    if exam_date <= today:
        raise ValueError("考試日期必須晚於今天。")
    total_days=(exam_date-today).days
    if total_days > 730:
        raise ValueError("目前一次最多規劃兩年內的目標。")
    weekday_minutes=max(10,min(480,int(weekday_minutes)))
    weekend_minutes=max(10,min(720,int(weekend_minutes)))

    subject=db().execute("SELECT * FROM subjects WHERE id=? AND created_by=?",(subject_id,user_id)).fetchone()
    if not subject:
        raise ValueError("科目不存在。")
    if chapter_ids:
        marks=','.join('?' for _ in chapter_ids)
        valid=db().execute(f"SELECT id FROM chapters WHERE subject_id=? AND id IN ({marks})",(subject_id,*chapter_ids)).fetchall()
        if {int(r['id']) for r in valid} != set(chapter_ids):
            raise ValueError("章節範圍不正確。")

    concepts=_planner_concepts(user_id,subject_id,chapter_ids)
    if not concepts:
        raise ValueError("這個科目目前沒有章節或 Concept，請先建立學習範圍。")

    cur=db().execute("""INSERT INTO learning_goals
        (user_id,subject_id,goal_name,exam_date,chapter_ids,weekday_minutes,weekend_minutes,starting_level,status,created_at,last_replanned_at)
        VALUES (?,?,?,?,?,?,?,?,? ,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
        (user_id,subject_id,goal_name,exam_date.isoformat(),json.dumps(chapter_ids),weekday_minutes,weekend_minutes,starting_level,'active'))
    goal_id=cur.lastrowid

    phases=_allocate_phase_dates(today,exam_date,_phase_blueprint(total_days))
    phase_ids=[]
    for seq,name,st,en,target_mastery,objective in phases:
        pcur=db().execute("""INSERT INTO learning_phases
            (goal_id,phase_no,name,start_date,end_date,objective,target_mastery,status)
            VALUES (?,?,?,?,?,?,?,'planned')""",
            (goal_id,seq,name,st.isoformat(),en.isoformat(),objective,target_mastery))
        phase_ids.append((pcur.lastrowid,seq,name,st,en,target_mastery,objective))
        db().execute("""INSERT INTO learning_milestones
            (goal_id,phase_id,title,target_date,target_mastery,checkpoint_question_count,status)
            VALUES (?,?,?,?,?,?,'planned')""",
            (goal_id,pcur.lastrowid,f"{name} Checkpoint",en.isoformat(),target_mastery,10 if seq < len(phases) else 20))

    # Assign concepts to the non-final phases. Weak / unseen concepts appear earlier and recur later.
    learning_phases=phase_ids[:-1] if len(phase_ids)>1 else phase_ids
    concepts=sorted(concepts,key=lambda x: x.get('_sort',50),reverse=True)
    for idx,c in enumerate(concepts):
        p=learning_phases[idx % len(learning_phases)]
        db().execute("""INSERT INTO learning_phase_concepts
            (phase_id,concept_id,chapter_id,concept_name,priority_order)
            VALUES (?,?,?,?,?)""",
            (p[0],c.get('concept_id'),c.get('chapter_id'),c.get('concept_name'),idx+1))

    _rebuild_goal_tasks(goal_id,user_id,concepts,phase_ids,weekday_minutes,weekend_minutes,keep_done=False)
    db().commit()
    return goal_id


def _rebuild_goal_tasks(goal_id: int, user_id: int, concepts, phase_ids, weekday_minutes: int, weekend_minutes: int, keep_done=True):
    """Rebuild calendar tasks while preserving every task that already has an assessment attempt.

    Reading/review tasks are guidance only. Progress is earned by system quizzes,
    never by manually clicking a task complete button.
    """
    preserve_dates=set()
    if keep_done:
        preserved=db().execute("""
            SELECT DISTINCT lt.task_date
            FROM learning_tasks lt
            LEFT JOIN learning_checkpoint_attempts lca ON lca.task_id=lt.id
            WHERE lt.goal_id=? AND lt.user_id=?
              AND (lt.status='done' OR lca.id IS NOT NULL)
        """,(goal_id,user_id)).fetchall()
        preserve_dates={str(r['task_date'])[:10] for r in preserved}
        db().execute("""
            DELETE FROM learning_tasks
            WHERE goal_id=? AND user_id=? AND status<>'done'
              AND id NOT IN (SELECT task_id FROM learning_checkpoint_attempts)
        """,(goal_id,user_id))
    else:
        db().execute("DELETE FROM learning_tasks WHERE goal_id=? AND user_id=?",(goal_id,user_id))

    if not concepts:
        return
    concept_idx=0
    for phase_id,seq,phase_name,st,en,target_mastery,objective in phase_ids:
        d=st
        day_index=0
        while d<=en:
            ds=d.isoformat()
            if ds in preserve_dates:
                d += timedelta(days=1); day_index += 1; continue
            minutes=weekend_minutes if d.weekday()>=5 else weekday_minutes
            is_final=(seq==phase_ids[-1][1])
            is_phase_end=(d==en)

            if is_phase_end:
                # Every phase ends with a real scored gate. The learner cannot click past it.
                task_type='Checkpoint'
                title=f"{phase_name} · 階段驗收"
                qcount=20 if is_final else 10
                concept=None
                reason=f"系統驗收：需達 {int(target_mastery)}% 才算通過此階段"
            elif is_final:
                # Protected final period: weak-area review + scored mock exams; no new core material.
                if day_index % 3 == 2:
                    task_type='模擬考'; title='考前完整範圍模擬考'; qcount=10
                    concept=None
                    reason=f"考前模擬：建議達 {int(target_mastery)}%"
                else:
                    concept=concepts[concept_idx % len(concepts)]; concept_idx += 1
                    task_type='弱項補強'; title=f"考前弱項回顧：{concept['concept_name']}"; qcount=0
                    reason='考前保留期：依弱項補強，不安排新的核心內容'
            else:
                concept=concepts[concept_idx % len(concepts)]; concept_idx += 1
                # A short system quiz roughly every week provides evidence for replanning.
                if day_index > 0 and day_index % 7 == 5:
                    task_type='小測'; title=f"本週小考：{phase_name}"; qcount=5
                    concept=None
                    reason='系統小考：由成績判定是否達標，結果會回饋弱項分析'
                elif day_index % 4 == 3:
                    task_type='間隔複習'; title=f"間隔複習：{concept['concept_name']}"; qcount=0
                    reason='依遺忘間隔安排複習；不以手動勾選作為通過依據'
                else:
                    task_type='學習'; title=f"學習：{concept['concept_name']}"; qcount=0
                    reason='依里程碑與目前弱項安排；真正進度由後續小考 / Checkpoint 判定'

            db().execute("""INSERT INTO learning_tasks
                (goal_id,user_id,phase_id,task_date,task_type,title,concept_id,chapter_id,target_minutes,question_count,status,reason)
                VALUES (?,?,?,?,?,?,?,?,?,?, 'planned',?)""",
                (goal_id,user_id,phase_id,ds,task_type,title,
                 None if concept is None else concept.get('concept_id'),
                 None if concept is None else concept.get('chapter_id'),
                 minutes,qcount,reason))
            d += timedelta(days=1); day_index += 1


def replan_learning_goal(user_id: int, goal_id: int):
    goal=db().execute("SELECT * FROM learning_goals WHERE id=? AND user_id=?",(goal_id,user_id)).fetchone()
    if not goal:
        raise ValueError("找不到學習目標。")
    exam_date=date.fromisoformat(str(goal['exam_date'])[:10])
    if exam_date <= date.today():
        raise ValueError("考試日期已到或已過，無法重新規劃。")
    chapter_ids=json.loads(goal['chapter_ids'] or '[]')
    concepts=_planner_concepts(user_id,int(goal['subject_id']),chapter_ids)
    phases=db().execute("SELECT * FROM learning_phases WHERE goal_id=? ORDER BY phase_no",(goal_id,)).fetchall()
    phase_ids=[]
    for p in phases:
        st=max(date.today(),date.fromisoformat(str(p['start_date'])[:10]))
        en=date.fromisoformat(str(p['end_date'])[:10])
        if en < date.today():
            continue
        phase_ids.append((int(p['id']),int(p['phase_no']),p['name'],st,en,float(p['target_mastery'] or 0),p['objective']))
    _rebuild_goal_tasks(goal_id,user_id,concepts,phase_ids,int(goal['weekday_minutes']),int(goal['weekend_minutes']),keep_done=True)
    db().execute("UPDATE learning_goals SET last_replanned_at=CURRENT_TIMESTAMP WHERE id=?",(goal_id,))
    db().commit()


def goal_progress(user_id: int, goal_id: int):
    """Progress is assessment-based: passed checkpoints, not clicked daily tasks."""
    row=db().execute("""
        SELECT COUNT(*) total,
               SUM(CASE WHEN status='achieved' THEN 1 ELSE 0 END) passed
        FROM learning_milestones WHERE goal_id=?
    """,(goal_id,)).fetchone()
    total=int(row['total'] or 0); passed=int(row['passed'] or 0)
    quiz=db().execute("""
        SELECT COUNT(*) total,
               SUM(CASE WHEN lt.status='done' THEN 1 ELSE 0 END) passed
        FROM learning_tasks lt
        WHERE lt.goal_id=? AND lt.user_id=? AND lt.question_count>0
    """,(goal_id,user_id)).fetchone()
    quiz_total=int(quiz['total'] or 0); quiz_passed=int(quiz['passed'] or 0)
    return {
        'total': total,
        'passed': passed,
        'done': passed,
        'percent': round(passed*100/total) if total else 0,
        'quiz_total': quiz_total,
        'quiz_passed': quiz_passed,
    }


def planner_task_required_score(task_row) -> float:
    """Return the automatic passing threshold for a planner assessment task."""
    task=dict(task_row)
    if task.get('phase_id'):
        phase=db().execute("SELECT target_mastery FROM learning_phases WHERE id=?",(task['phase_id'],)).fetchone()
        phase_target=float(phase['target_mastery'] or 75) if phase else 75.0
    else:
        phase_target=75.0
    if task.get('task_type')=='小測':
        return min(70.0, phase_target)
    return phase_target


def register_planner_quiz_attempt(user_id: int, task_id: int, session_id: int):
    task=db().execute("SELECT * FROM learning_tasks WHERE id=? AND user_id=?",(task_id,user_id)).fetchone()
    if not task:
        raise ValueError("找不到學習任務。")
    if int(task['question_count'] or 0) <= 0:
        raise ValueError("這一天是學習 / 複習任務，不是系統測驗。")
    milestone=None
    if task['task_type']=='Checkpoint' and task['phase_id']:
        milestone=db().execute("""
            SELECT * FROM learning_milestones
            WHERE goal_id=? AND phase_id=? ORDER BY target_date DESC,id DESC LIMIT 1
        """,(task['goal_id'],task['phase_id'])).fetchone()
    required=planner_task_required_score(task)
    cur=db().execute("""INSERT INTO learning_checkpoint_attempts
        (task_id,milestone_id,session_id,required_score,created_at)
        VALUES (?,?,?,?,CURRENT_TIMESTAMP)""",
        (task_id,milestone['id'] if milestone else None,session_id,required))
    db().commit()
    return cur.lastrowid


def apply_planner_quiz_result(user_id: int, session_id: int):
    """Apply a finished quiz score to its planner task and milestone.

    Returns None for ordinary quizzes. A failed gate stays failed and can be retried;
    a passing Checkpoint is the only way a phase/milestone becomes achieved.
    """
    attempt=db().execute("""
        SELECT lca.*,lt.goal_id,lt.phase_id,lt.task_type,lt.title,lt.user_id
        FROM learning_checkpoint_attempts lca
        JOIN learning_tasks lt ON lt.id=lca.task_id
        WHERE lca.session_id=? AND lt.user_id=?
    """,(session_id,user_id)).fetchone()
    if not attempt:
        return None
    if attempt['graded_at']:
        return {
            'task_id': attempt['task_id'], 'score': attempt['score'],
            'required_score': attempt['required_score'], 'passed': bool(attempt['passed']),
            'goal_id': attempt['goal_id'], 'task_type': attempt['task_type'], 'title': attempt['title']
        }
    quiz=db().execute("SELECT total_count,correct_count,finished_at FROM quiz_sessions WHERE id=? AND user_id=?",(session_id,user_id)).fetchone()
    if not quiz or not quiz['finished_at']:
        return None
    total=int(quiz['total_count'] or 0); correct=int(quiz['correct_count'] or 0)
    score=round(correct*100/total,1) if total else 0.0
    required=float(attempt['required_score'] or 0)
    passed=score >= required
    db().execute("""UPDATE learning_checkpoint_attempts
        SET score=?,passed=?,graded_at=CURRENT_TIMESTAMP WHERE id=?""",
        (score,1 if passed else 0,attempt['id']))
    db().execute("""UPDATE learning_tasks
        SET status=?,completed_at=CASE WHEN ?='done' THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE id=?""",('done' if passed else 'failed','done' if passed else 'failed',attempt['task_id']))

    if attempt['milestone_id']:
        if passed:
            db().execute("UPDATE learning_milestones SET status='achieved',achieved_at=CURRENT_TIMESTAMP WHERE id=?",(attempt['milestone_id'],))
            if attempt['phase_id']:
                db().execute("UPDATE learning_phases SET status='passed' WHERE id=?",(attempt['phase_id'],))
        else:
            db().execute("UPDATE learning_milestones SET status='needs_review',achieved_at=NULL WHERE id=?",(attempt['milestone_id'],))
            if attempt['phase_id']:
                db().execute("UPDATE learning_phases SET status='needs_review' WHERE id=?",(attempt['phase_id'],))

    remaining=db().execute("SELECT COUNT(*) n FROM learning_milestones WHERE goal_id=? AND status<>'achieved'",(attempt['goal_id'],)).fetchone()
    if remaining and int(remaining['n'] or 0)==0:
        db().execute("UPDATE learning_goals SET status='ready' WHERE id=?",(attempt['goal_id'],))
    db().commit()
    return {
        'task_id': attempt['task_id'], 'score': score, 'required_score': required,
        'passed': passed, 'goal_id': attempt['goal_id'], 'task_type': attempt['task_type'], 'title': attempt['title']
    }
