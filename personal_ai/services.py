from __future__ import annotations
import json
from difflib import SequenceMatcher
from storage import db
from .rag import retrieve
from .llm_provider import get_generator_llm, get_reviewer_llm, model_usage_label, LLMError

ALLOWED={'單選','多選','是非','填空'}


def _concept_context(user_id, subject_id, chapter_ids, limit=20):
    params=[user_id,subject_id]
    chapter_sql=''
    if chapter_ids:
        chapter_sql=' AND c.chapter_id IN ('+','.join('?' for _ in chapter_ids)+')'
        params.extend(chapter_ids)
    concepts=db().execute('''SELECT c.id,c.name,c.description,c.chapter_id,ch.chapter_name,
        COUNT(si.id) source_count
        FROM concepts c
        LEFT JOIN chapters ch ON ch.id=c.chapter_id
        LEFT JOIN source_question_items si ON si.concept_id=c.id AND si.user_id=?
        WHERE c.subject_id=?'''+chapter_sql+'''
        GROUP BY c.id,c.name,c.description,c.chapter_id,ch.chapter_name
        ORDER BY source_count DESC,c.name LIMIT ?''',(*params,limit)).fetchall()
    # sqlite3.Row supports row["field"] but not dict-style .get().
    # Normalize DB rows at the service boundary so the rest of the AI pipeline
    # behaves identically on SQLite (DEV) and PostgreSQL/self-host mode.
    concepts=[dict(row) for row in concepts]
    if not concepts:
        return [],[]
    ids=[int(c['id']) for c in concepts]
    marks=','.join('?' for _ in ids)
    samples=db().execute(f'''SELECT concept_id,raw_question,q_type,answer_key,skill,cognitive_level,difficulty
        FROM source_question_items
        WHERE user_id=? AND concept_id IN ({marks})
        ORDER BY id DESC LIMIT 80''',(user_id,*ids)).fetchall()
    samples=[dict(row) for row in samples]
    return concepts,samples


def _validate_generated(item):
    qt=str(item.get('q_type','')).strip()
    content=str(item.get('content','')).strip()
    ans=str(item.get('answer_key','')).strip()
    opts=item.get('options') or {}
    if qt not in ALLOWED or not content or not ans:
        return None
    if qt in ('單選','多選'):
        labels=set(opts.keys())
        answers={x.strip() for x in ans.replace('，',',').split(',') if x.strip()}
        if len(labels)<2 or not answers.issubset(labels):
            return None
    return qt,content,ans,opts


def _review_question(reviewer, item, evidence_text, concept_text):
    if not reviewer.enabled or getattr(reviewer,'provider','')=='mock':
        return {'approved': True, 'reason': 'DEV/Mock reviewer：略過真實模型審題。'}
    system=(
        '你是考題審題模型。只根據提供的 Concept、來源樣本與教材證據，檢查題目是否：'
        '1) 有唯一或明確答案；2) 答案與解析一致；3) 沒有超出範圍；'
        '4) 不是只把來源題目換數字或換字；5) 題目可正常作答。只回 JSON。'
    )
    user=json.dumps({'question':item,'concept_context':concept_text,'evidence':evidence_text[:12000]},ensure_ascii=False)
    user += '\n回傳：{"approved":true,"reason":"...","corrected_question":null}。如需修正，可在 corrected_question 回傳完整題目物件。'
    try:
        data=reviewer.complete_json(system,user)
        return data if isinstance(data,dict) else {'approved':False,'reason':'Reviewer 回傳格式錯誤'}
    except Exception as exc:
        return {'approved':False,'reason':f'Reviewer 失敗：{exc}'}


def generate_question_drafts(config,user_id,subject_id,chapter_ids,count,q_types,difficulty,focus=''):
    # 兩種來源都可驅動出題：Concept Bank（由匯入題目歸類而來）+ 教材 RAG。
    concepts,samples=_concept_context(user_id,subject_id,chapter_ids,limit=max(12,count*2))
    query=focus or ' '.join(q_types)+' 核心概念 重要觀念 應用'
    chunks=retrieve(user_id,subject_id,query,chapter_ids,limit=max(6,count))
    if not concepts and not chunks:
        raise ValueError('選取範圍沒有 Concept 或教材內容。請先匯入題庫做概念歸類，或上傳教材。')

    recent=db().execute('''SELECT q.content FROM questions q JOIN chapters c ON c.id=q.chapter_id JOIN subjects s ON s.id=c.subject_id
                           WHERE s.id=? ORDER BY q.id DESC LIMIT 80''',(subject_id,)).fetchall()
    recent_text='\n'.join('- '+r['content'][:220] for r in recent)
    evidence='\n\n'.join(f"[chunk:{c['id']}] {c['section_title'] or c['material_title']}\n{c['content']}" for c in chunks)
    concept_map={int(c['id']):c for c in concepts}
    sample_groups={cid:[] for cid in concept_map}
    for sample in samples:
        sample_groups.setdefault(int(sample['concept_id']),[]).append(sample)
    concept_lines=[]
    for c in concepts:
        cid=int(c['id'])
        concept_lines.append(f"[concept:{cid}] {c['name']} | chapter={c['chapter_name'] or ''} | {c['description'] or ''} | source_examples={c['source_count']}")
        for ex in sample_groups.get(cid,[])[:3]:
            concept_lines.append(f"  - SOURCE EXAMPLE（只供理解考點，禁止改數字照抄）: {ex['raw_question'][:420]} | skill={ex['skill'] or ''} | level={ex['cognitive_level'] or ''}")
    concept_text='\n'.join(concept_lines)

    generator=get_generator_llm(config)
    reviewer=get_reviewer_llm(config)
    if not generator.enabled:
        raise LLMError('Generator LLM 尚未設定。請設定 GENERATOR_PROVIDER / GENERATOR_MODEL。')
    system=(
        '你是 Concept-based Adaptive Assessment 考題設計模型。你的目標不是重述來源題，而是根據 Concept/Skill '
        '重新設計全新題目，降低使用者背題與過度擬合。\n'
        '規則：\n'
        '1. 優先從提供的 Concept Bank 選擇考點；來源題只用來理解考什麼，不可照抄、只換數字或只換人物。\n'
        '2. 同一 Concept 可用不同情境、數值、資料結構或推理方向，能力層次盡量混合 understand/apply/analyze。\n'
        '3. 若有教材 evidence，答案必須能由 evidence 支持；若只有來源題樣本，必須保持該 Concept 的標準知識邏輯。\n'
        '4. 避免與近期既有題目近似。\n'
        '5. 每題回傳 concept_id、concept_name、skill、cognitive_level、答案與解析。\n'
        '6. 只回 JSON，不要 Markdown。'
    )
    # Small Groq output quotas cannot fit a multi-question JSON response.
    primary = getattr(generator, 'primary', generator)
    batch_size = 1 if getattr(primary, 'provider', '') == 'groq' else count
    user=(f'請產生 {batch_size} 題，題型限定 {q_types}，難度 {difficulty}/5。\n'
          f'使用者指定重點：{focus or "無"}\n\n'
          f'Concept Bank / 來源題樣本：\n{concept_text or "無"}\n\n'
          f'教材 RAG：\n{evidence or "無"}\n\n'
          f'近期正式題目（避免近似）：\n{recent_text or "無"}\n\n'
          'JSON 格式：{"questions":[{"concept_id":1,"concept_name":"...","q_type":"單選",'
          '"content":"...","options":{"A":"...","B":"...","C":"...","D":"..."},'
          '"answer_key":"B","explanation":"...","evidence_chunk_ids":[1],"skill":"...","cognitive_level":"apply"}]}')
    qs=[]
    for offset in range(0, count, batch_size):
        batch_user = user
        if batch_size == 1:
            previous = '\n'.join(str(q.get('content', '')) for q in qs if isinstance(q, dict))
            batch_user += (f'\n本次是第 {offset + 1}/{count} 題。題幹、選項與解析請精簡，解析最多兩句。'
                           f'\n本輪已產生題目（請避免重複）：\n{previous or "無"}')
        data=generator.complete_json(system,batch_user)
        batch=data.get('questions',[]) if isinstance(data,dict) else []
        if not isinstance(batch,list) or not batch:
            raise LLMError('Generator 沒有產生可用題目。')
        qs.extend(batch[:batch_size])
    if not qs:
        raise LLMError('Generator 沒有產生可用題目。')

    created=[]
    existing=[r['content'] for r in recent]
    source_texts=[s['raw_question'] for s in samples]
    for item in qs[:count*2]:
        if len(created)>=count:
            break
        valid=_validate_generated(item)
        if not valid:
            continue
        qt,content,ans,opts=valid
        # Real generators are screened for near-duplicates.  DEV Mock intentionally
        # uses templated wording, so skip this semantic-looking string gate there;
        # otherwise frontend/backend tests would incorrectly collapse to one item.
        if getattr(generator, 'provider', '') != 'mock' and any(
            SequenceMatcher(None,content,old).ratio()>=0.84 for old in existing+source_texts
        ):
            continue
        review=_review_question(reviewer,item,evidence,concept_text)
        if not review.get('approved'):
            corrected=review.get('corrected_question')
            if isinstance(corrected,dict):
                v=_validate_generated(corrected)
                if not v:
                    continue
                item=corrected
                qt,content,ans,opts=v
            else:
                continue
        ev=item.get('evidence_chunk_ids') or []
        concept_id=item.get('concept_id')
        try:
            concept_id=int(concept_id) if concept_id else None
        except (TypeError,ValueError):
            concept_id=None
        if concept_id not in concept_map:
            concept_id=None
        concept_name=str(item.get('concept_name') or (concept_map.get(concept_id,{}).get('name') if concept_id else '') or '').strip()
        concept_names=[concept_name] if concept_name else []
        chapter_id=(concept_map.get(concept_id,{}).get('chapter_id') if concept_id else None) or (chapter_ids[0] if len(chapter_ids)==1 else None)
        cur=db().execute('''INSERT INTO ai_question_drafts(user_id,subject_id,chapter_id,q_type,content,options_json,answer_key,explanation,evidence_chunk_ids,concepts_json,skill,difficulty,status,model_name)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            user_id,subject_id,chapter_id,qt,content,json.dumps(opts,ensure_ascii=False),ans,
            str(item.get('explanation','')).strip(),json.dumps(ev),json.dumps(concept_names,ensure_ascii=False),
            str(item.get('skill','')).strip(),difficulty,'draft',model_usage_label(generator)))
        created.append(cur.lastrowid)
        existing.append(content)
    db().commit()
    if not created:
        raise LLMError('生成結果全部因格式、重複度或審題規則被拒絕，請調整範圍或重試。')
    return created
