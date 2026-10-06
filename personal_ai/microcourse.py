from __future__ import annotations

import json
import re
from flask import current_app

from storage import db
from .coaching import calculate_concept_weakness
from .llm_provider import LLMError, get_course_llm, get_tutor_llm, model_usage_label
from .rag import retrieve
from .prompt_budget import bounded_json
from .data_safety import safe_source, validate_user_text, redact_text
from .response_style import STYLE, scope_reply


def _concept_row(user_id: int, concept_id: int):
    row = db().execute(
        """
        SELECT co.*, ch.chapter_name, s.subject_name
        FROM concepts co
        JOIN subjects s ON s.id=co.subject_id
        LEFT JOIN chapters ch ON ch.id=co.chapter_id
        WHERE co.id=? AND s.created_by=?
        """,
        (concept_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def _weakness_for(user_id: int, subject_id: int, concept_id: int):
    for item in calculate_concept_weakness(user_id, subject_id):
        if int(item["concept_id"]) == int(concept_id):
            return item
    return {
        "concept_id": concept_id,
        "mastery": None,
        "priority": "尚未測驗",
        "n": 0,
        "skills": [],
    }


def _course_evidence(user_id: int, concept: dict, weakness: dict, limit: int = 8):
    skills = " ".join(s.get("name", "") for s in weakness.get("skills", [])[:4])
    query = " ".join(
        [concept.get("name", ""), concept.get("description") or "", skills]
    ).strip()
    chapters = [int(concept["chapter_id"])] if concept.get("chapter_id") else []
    rows = retrieve(user_id, int(concept["subject_id"]), query, chapters, limit=limit)
    return [dict(row) for row in rows]


def _normalize_steps(data: dict, concept_name: str):
    raw = data.get("steps") or []
    out = []
    allowed = {"teach", "example", "check", "summary", "reflection"}
    for idx, item in enumerate(raw[:10], 1):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("step_type") or "teach").lower()
        if kind not in allowed:
            kind = "teach"
        out.append(
            {
                "step_no": idx,
                "step_type": kind,
                "title": str(item.get("title") or f"步驟 {idx}").strip()[:180],
                "content": str(item.get("content") or "").strip(),
                "question": str(item.get("question") or "").strip(),
                "answer_key": str(
                    item.get("answer_key") or item.get("expected_answer") or ""
                ).strip(),
                "explanation": str(
                    item.get("explanation") or item.get("feedback") or ""
                ).strip(),
            }
        )
    if not out: raise ValueError("課程沒有有效步驟。")
    return out


def create_micro_course(user_id: int, concept_id: int, minutes: int = 5):
    concept = _concept_row(user_id, concept_id)
    if not concept:
        raise ValueError("找不到這個 Concept。")
    minutes = max(3, min(15, int(minutes or 5)))
    weakness = _weakness_for(user_id, int(concept["subject_id"]), concept_id)
    evidence = _course_evidence(user_id, concept, weakness)
    samples=db().execute('SELECT id,raw_question,explanation FROM source_question_items WHERE user_id=? AND concept_id=? AND subject_id=? ORDER BY id DESC LIMIT 4',
                         (user_id,concept_id,concept['subject_id'])).fetchall()
    sample_text='\n'.join(f"[source:{r['id']}] "+safe_source(r['raw_question'])+' '+safe_source(r['explanation']) for r in samples if safe_source(r['raw_question']))
    if not evidence and not sample_text:
        raise ValueError('沒有相關教材或來源樣本支持此課程，請先加入教材。')
    weakness['evidence_source_ids']=[r['id'] for r in samples if safe_source(r['raw_question'])] if not evidence else []
    evidence_text = "\n\n".join(
        f"[chunk:{e['id']}] {e.get('section_title') or e.get('material_title') or '教材'}\n{e.get('content','')}"
        for e in evidence
    )
    model = get_course_llm(current_app.config)
    mastery = weakness.get("mastery")
    reason = (
        f"目前掌握度 {mastery}%・{weakness.get('priority')}"
        if mastery is not None
        else "目前尚未有足夠測驗資料"
    )
    reason += (
        f"；已找到 {len(evidence)} 段相關教材"
        if evidence
        else "；目前未找到相關教材 chunk"
    )

    if not model.enabled or getattr(model, "provider", "") == "mock":
        lesson = {
            "title": f"{concept['name']}｜{minutes} 分鐘補強課",
            "objective": f"用短時間重新建立「{concept['name']}」的核心概念，並用互動檢查理解。",
            "steps": [
                {
                    "type": "teach",
                    "title": "先抓住核心",
                    "content": (
                        evidence[0]["content"][:650]
                        if evidence
                        else f"這是一堂針對「{concept['name']}」的 DEV 微課程。真模型啟用後會依你的教材與弱項重新生成內容。"
                    ),
                },
                {
                    "type": "example",
                    "title": "教材例子",
                    "content": (
                        evidence[1]["content"][:550]
                        if len(evidence) > 1
                        else "請把這個 Concept 想成一個可以被不同題目包裝，但核心判斷方式不變的能力。"
                    ),
                },
                {
                    "type": "check",
                    "title": "互動確認",
                    "content": "先不要背原題答案，確認自己能否描述核心規則。",
                    "question": f"請用自己的話說明「{concept['name']}」的核心判斷方式。",
                    "answer_key": concept["name"],
                    "explanation": "DEV 模式僅驗證互動流程；切換 Qwen 後會依教材產生具體且可驗證的問題。",
                },
                {
                    "type": "summary",
                    "title": "完成這堂補強",
                    "content": "完成後回到同 Concept 的動態小測，用全新題目確認是否真的理解。",
                },
            ],
        }
        model_name = "DEV Mock Course Builder"
    else:
        system = (
            "你是自適應學習課程設計師。只可依提供的教材 RAG 證據、Concept 與弱項資料設計短課程；"
            "不可補充教材未支持的專有事實。課程需 3~8 分鐘可完成，繁體中文，重點是重新教會弱項，不是摘要。"
            "至少包含 teach、example、check、summary 四種步驟。check 要有可判定的問題與答案。只回 JSON。"
        )
        payload = {
            "concept": concept,
            "weakness": weakness,
            "target_minutes": minutes,
            "evidence": evidence_text,
            "requirements": {
                "adapt_to_weakness": True,
                "use_short_sections": True,
                "include_interaction": True,
                "do_not_copy_source_question": True,
            },
        }
        if not evidence:
            payload['evidence']=sample_text
            if not payload['evidence']: raise ValueError('沒有教材或來源樣本支持此課程，請先加入教材。')
        lesson={'title':f"{concept['name']} 補強課",'objective':f"理解並應用 {concept['name']}",'steps':[]}
        try:
            for kind in ('teach','example','check','summary'):
                part=model.complete_json(system,bounded_json(payload)+
                    '\n本次只產生 '+kind+' 一個步驟，內容最多三句。check 必須為是非或簡短填空，答案不超過 20 字；多個可接受答案用 | 分隔。'+
                    '\n回傳 {"type":"'+kind+'","title":"...","content":"...","question":"check 才填","answer_key":"...","explanation":"..."}。')
                if not isinstance(part,dict) or not part.get('content'): raise ValueError('模型課程步驟不完整。')
                part['type']=kind
                if kind=='check' and (not part.get('question') or not part.get('answer_key')):
                    raise ValueError('互動題缺少問題或可判定答案。')
                lesson['steps'].append(part)
        except LLMError as exc:
            raise ValueError(str(exc)) from exc
        model_name = model_usage_label(model)

    steps = _normalize_steps(lesson, concept["name"])
    cur = db().execute(
        """
        INSERT INTO micro_courses
        (user_id,subject_id,concept_id,title,objective,reason,estimated_minutes,status,
         generation_model,evidence_chunk_ids,weakness_snapshot)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            user_id,
            concept["subject_id"],
            concept_id,
            str(lesson.get("title") or f"{concept['name']} 補強課")[:220],
            str(lesson.get("objective") or "")[:1200],
            reason,
            minutes,
            "active",
            model_name,
            json.dumps([int(e["id"]) for e in evidence]),
            json.dumps(weakness, ensure_ascii=False),
        ),
    )
    course_id = cur.lastrowid
    for step in steps:
        db().execute(
            """
            INSERT INTO micro_course_steps
            (course_id,step_no,step_type,title,content,question,answer_key,explanation,status)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                course_id,
                step["step_no"],
                step["step_type"],
                step["title"],
                step["content"],
                step["question"],
                step["answer_key"],
                step["explanation"],
                "planned",
            ),
        )
    db().commit()
    return course_id


def get_course(user_id: int, course_id: int):
    course = db().execute(
        """
        SELECT mc.*,co.name concept_name,s.subject_name,ch.chapter_name
        FROM micro_courses mc
        JOIN concepts co ON co.id=mc.concept_id
        JOIN subjects s ON s.id=mc.subject_id
        LEFT JOIN chapters ch ON ch.id=co.chapter_id
        WHERE mc.id=? AND mc.user_id=?
        """,
        (course_id, user_id),
    ).fetchone()
    if not course:
        return None
    data = dict(course)
    try:
        data["weakness"] = json.loads(data.get("weakness_snapshot") or "{}")
    except Exception:
        data["weakness"] = {}
    try:
        chunk_ids = json.loads(data.get("evidence_chunk_ids") or "[]")
    except Exception:
        chunk_ids = []
    data["steps"] = [
        dict(x)
        for x in db().execute(
            "SELECT * FROM micro_course_steps WHERE course_id=? ORDER BY step_no",
            (course_id,),
        ).fetchall()
    ]
    data["messages"] = [
        dict(x)
        for x in db().execute(
            "SELECT * FROM micro_course_messages WHERE course_id=? ORDER BY id",
            (course_id,),
        ).fetchall()
    ]
    data["evidence"] = []
    if chunk_ids:
        marks = ",".join("?" for _ in chunk_ids)
        data["evidence"] = [
            dict(x)
            for x in db().execute(
                f"""
                SELECT rc.id,rc.content,rm.section_title,m.title material_title
                FROM rag_chunks rc
                JOIN rag_documents rd ON rd.id=rc.doc_id
                JOIN materials m ON m.id=rd.material_id
                LEFT JOIN rag_chunk_meta rm ON rm.chunk_id=rc.id
                WHERE rc.id IN ({marks}) AND m.user_id=? AND m.subject_id=?
                """,
                (*chunk_ids,user_id,data['subject_id']),
            ).fetchall()
        ]
    for source in data['evidence']:
        source['content']=safe_source(source['content'])
        source['material_title']=redact_text(source['material_title'])
    data['evidence']=[source for source in data['evidence'] if source['content'].strip()]
    return data


def list_courses(user_id: int, limit: int = 40):
    return db().execute(
        """
        SELECT mc.*,co.name concept_name,s.subject_name
        FROM micro_courses mc
        JOIN concepts co ON co.id=mc.concept_id
        JOIN subjects s ON s.id=mc.subject_id
        WHERE mc.user_id=? ORDER BY mc.id DESC LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()


def _simple_correct(user_answer: str, answer_key: str):
    ua = re.sub(r"\s+", "", str(user_answer or "")).lower()
    ak = re.sub(r"\s+", "", str(answer_key or "")).lower()
    if not ak:
        return None
    return ua in [re.sub(r"\s+", "", x).lower() for x in ak.split("|")]


def answer_step(user_id: int, course_id: int, step_id: int, user_answer: str):
    course = get_course(user_id, course_id)
    if not course:
        raise ValueError("找不到這堂課。")
    step = next((s for s in course["steps"] if int(s["id"]) == int(step_id)), None)
    if not step:
        raise ValueError("找不到這個互動步驟。")
    correct = _simple_correct(user_answer, step.get("answer_key"))
    feedback = step.get("explanation") or (
        "回答已記錄。"
        if correct is None
        else ("答對了。" if correct else "這個回答還沒有命中核心答案，請再看一次上方重點。")
    )
    db().execute(
        "UPDATE micro_course_steps SET user_answer=?,is_correct=?,feedback=?,status=? WHERE id=?",
        (
            user_answer,
            None if correct is None else int(correct),
            feedback,
            "done",
            step_id,
        ),
    )
    db().commit()
    return correct, feedback


def ask_course_tutor(user_id: int, course_id: int, question: str):
    course = get_course(user_id, course_id)
    if not course:
        raise ValueError("找不到這堂課。")
    question = (question or "").strip()
    if not question:
        raise ValueError("請輸入問題。")
    if len(question) > 1500:
        raise ValueError("問題不可超過 1500 字。")
    validate_user_text(question)
    question=redact_text(question)
    from .rag import related
    supported=related(question,' '.join([course['concept_name'],course['objective'] or '']+
        [safe_source(e['content']) for e in course['evidence']]+
        [safe_source(step['content']) for step in course['steps']]))

    evidence = "\n\n".join(
        f"[chunk:{e['id']}] {e.get('section_title') or e.get('material_title')}\n{e['content']}"
        for e in course["evidence"]
    )
    history = "\n".join(
        f"{m['role']}: {m['content']}" for m in course["messages"][-8:]
    )
    model = get_tutor_llm(current_app.config)
    db().execute(
        "INSERT INTO micro_course_messages(course_id,role,content,context_chunk_ids,model_name) VALUES (?,?,?,?,?)",
        (course_id, "user", question, course.get("evidence_chunk_ids") or "[]", "user"),
    )

    if not supported:
        answer=scope_reply(question,context='這堂課和教材',in_chat=False)
        model_name='教材範圍檢查（未呼叫模型）'
    elif not model.enabled or getattr(model, "provider", "") == "mock":
        answer = (
            "DEV 模式：這裡已接好微課程互動 Tutor。啟用真 Qwen 後，會只依本課 Concept、課程內容與 RAG 教材回答你的追問。"
        )
        if course["evidence"]:
            answer += "\n\n目前可追溯教材：" + course["evidence"][0]["content"][:350]
        model_name = "DEV Mock Tutor"
    else:
        system = (
            "你是互動式 AI Tutor。只能依目前微課程、Concept、教材 RAG 證據回答。若證據不足要明說。"
            "用繁體中文、短句、蘇格拉底式引導；不要直接暴露未作答 Checkpoint 的答案。只回 JSON。" + STYLE
        )
        payload = bounded_json(
            {
                "course_title": course["title"],
                "concept": course["concept_name"],
                "objective": course["objective"],
                "lesson_steps": [
                    {"title": s["title"], "content": s["content"]}
                    for s in course["steps"]
                ],
                "evidence": evidence,
                "conversation": history,
                "question": question,
            },
        )
        try:
            data = model.complete_json(system, payload + '\n回傳 {"answer":"..."}')
            answer = str(data.get("answer") or "").strip()
            if not answer:
                raise LLMError("Tutor 回傳空白內容。")
        except LLMError as exc:
            raise ValueError(str(exc)) from exc
        model_name = model_usage_label(model)

    db().execute(
        "INSERT INTO micro_course_messages(course_id,role,content,context_chunk_ids,model_name) VALUES (?,?,?,?,?)",
        (
            course_id,
            "assistant",
            answer,
            course.get("evidence_chunk_ids") or "[]",
            model_name,
        ),
    )
    db().commit()
    return answer


def complete_course(user_id: int, course_id: int):
    course = get_course(user_id, course_id)
    if not course:
        raise ValueError("找不到這堂課。")
    checks = [s for s in course['steps'] if s.get('question')]
    if not checks or any(s['status'] != 'done' or s.get('is_correct') != 1 for s in checks):
        raise ValueError('請先完成並答對所有互動題，再完成課程。課程完成不代表已通過概念驗收。')
    db().execute(
        "UPDATE micro_courses SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
        (course_id, user_id),
    )
    db().commit()
