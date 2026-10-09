from __future__ import annotations

import json
import math
import re
from collections import defaultdict

from storage import db
from .embedding_provider import get_embedder
from .llm_provider import LLMError, get_classifier_llm, model_usage_label


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a)) or 1.0
    nb = math.sqrt(sum(float(x) * float(x) for x in b)) or 1.0
    return dot / (na * nb)


def _question_text(item):
    opts = ' '.join(str(item.get('option_' + k, '') or '') for k in 'ABCD')
    return f"{item.get('content','')} {opts} {item.get('explanation','')}".strip()


def _heuristic(item):
    text = _question_text(item).lower()
    rules = [
        (('range(', '串列', 'list('), '迴圈與串列', '索引、長度與迴圈判讀'),
        (('type(', 'int', '字串', '變數', '型別'), '變數與型別', '辨識資料型別'),
        (('if ', '條件判斷', '比較運算'), '條件判斷', '判讀條件結果'),
        (('二元一次', '聯立方程'), '二元一次聯立方程式', '求解與建模'),
        (('primary key', '主索引鍵', '主鍵'), '主索引鍵與資料唯一性', '辨識主索引鍵用途'),
        (('foreign key', '外部索引鍵', '外鍵'), '外部索引鍵與參照完整性', '建立資料表關聯'),
        (('group by', 'having'), 'SQL 聚合與 HAVING', '聚合後條件篩選'),
        (('inner join', 'left join', 'right join', 'cross join', ' join '), 'SQL JOIN 與資料表關聯', '判讀 JOIN 行為'),
        (('rollback', 'commit', 'transaction', '交易'), '資料庫交易控制', 'COMMIT 與 ROLLBACK'),
        (('index', '索引'), '資料庫索引與查詢效能', '索引效能判讀'),
        (('order by', '排序'), 'SQL 排序與結果順序', 'ORDER BY 與結果順序'),
        (('create table', 'drop table', 'ddl'), '資料定義語言 DDL', '資料表結構操作'),
        (('normal form', '正規化', '1nf', '2nf', '3nf'), '資料庫正規化', '正規形式判讀'),
    ]
    for keys, name, skill in rules:
        if any(k in text for k in keys):
            return name, skill
    # Stable, human-readable fallback rather than one concept per whole question.
    words = re.findall(r'[A-Za-z][A-Za-z0-9_+-]*|[\u4e00-\u9fff]{2,8}', str(item.get('content','')))
    name = ' / '.join(words[:2]) if words else '待人工命名概念'
    return name[:80], '概念理解'


def _existing(subject_id):
    rows = db().execute(
        'SELECT id,name,description,chapter_id FROM concepts WHERE subject_id=? ORDER BY name',
        (subject_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _embedding_candidates(items, concepts, config, top_k=6):
    if not concepts:
        return {i: [] for i in range(len(items))}
    embedder = get_embedder(config)
    if not embedder.enabled:
        return {i: list(concepts[:top_k]) for i in range(len(items))}
    qtexts = [_question_text(x) for x in items]
    ctexts = [f"{c['name']} {c['description'] or ''}" for c in concepts]
    try:
        vectors = embedder.embed(qtexts + ctexts)
        qv = vectors[:len(qtexts)]
        cv = vectors[len(qtexts):]
        result = {}
        for i, vec in enumerate(qv):
            scored = sorted(((_cosine(vec, cv[j]), concepts[j]) for j in range(len(concepts))), key=lambda x: x[0], reverse=True)
            result[i] = [dict(row, similarity=round(score, 4)) for score, row in scored[:top_k]]
        return result
    except Exception:
        return {i: list(concepts[:top_k]) for i in range(len(items))}


def _normalize_classification(raw, item, existing_ids):
    concept_name = str(raw.get('concept_name') or '').strip()[:255]
    if not concept_name:
        concept_name, fallback_skill = _heuristic(item)
    else:
        fallback_skill = '概念理解'
    eid = raw.get('existing_concept_id')
    try:
        eid = int(eid) if eid not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        eid = None
    if eid not in existing_ids:
        eid = None
    confidence = raw.get('confidence', 0.5)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        'concept_id': eid,
        'concept_name': concept_name,
        'concept_description': str(raw.get('concept_description') or '').strip()[:1200],
        'skill': str(raw.get('skill') or fallback_skill).strip()[:255],
        'cognitive_level': str(raw.get('cognitive_level') or 'understand').strip().lower()[:32],
        'difficulty': max(1, min(5, int(raw.get('difficulty') or item.get('difficulty') or 2))),
        'confidence': confidence,
        'reason': str(raw.get('reason') or '').strip()[:1000],
    }


def classify_question_batch(items, subject_id, config):
    """Classify imported questions into semantic concepts.

    Uses embeddings to shortlist existing concepts, then a dedicated classifier LLM
    to decide whether each question belongs to an existing concept or a new one.
    Questions in the same batch are explicitly asked to share canonical names when
    they test the same underlying knowledge.
    """
    concepts = _existing(subject_id)
    existing_ids = {int(c['id']) for c in concepts}
    from .classification_context import prepare, mark_review
    context_model = get_classifier_llm(config)
    items = [prepare(item, context_model) for item in items]
    from .exam_modules import enabled, classify, specialist_heads
    if enabled(config):
        final = get_classifier_llm(config)
        if not final.enabled:
            raise LLMError('分工模式需要最終 LLM，請設定 CLASSIFIER_PROVIDER。')
        output = []
        # Keep each final response within the Groq output cap.
        for start in range(0, len(items), 2):
            batch = items[start:start+2]
            proposals = [classify(item, concepts, _heuristic(item)[0]) for item in batch]
            for item,proposal in zip(batch,proposals):
                proposal['specialist_heads']=specialist_heads(item,subject_id)
            payload = [dict(index=i, question=item.get('content',''),
                            answer=item.get('answer_key'), chapter=item.get('chapter_name'),
                            proposal=proposal) for i,(item,proposal) in enumerate(zip(batch,proposals))]
            data = final.complete_json(
                '你是考題分類的最終裁決者。CPU 分數未校準，不代表正確率。檢查候選概念，'
                '低信心時用簡短穩定的概念名稱。只能選提供的 concept id 或 null。'
                '每題回傳 index、existing_concept_id、concept_name、skill、cognitive_level、confidence。只回 JSON。',
                json.dumps(payload,ensure_ascii=False)+'\n格式：{"classifications":[{"index":0,"concept_name":"...","existing_concept_id":null,"skill":"...","cognitive_level":"understand","confidence":0.5}]}')
            mapped = {r.get('index'):r for r in data.get('classifications',[]) if isinstance(r,dict)} if isinstance(data,dict) else {}
            for i,(item,proposal) in enumerate(zip(batch,proposals)):
                if i not in mapped:
                    raise LLMError('最終分類裁決未回傳全部題目，請減少匯入題數後重試。')
                raw = mapped[i]
                raw['reason'] = proposal['reason'] + (' 低信心，已交 LLM 裁決。' if proposal['needs_review'] else ' 已交 LLM 最終確認。')
                normalized = _normalize_classification(raw,item,existing_ids)
                output.append(mark_review(normalized) if item.get('_long_classification_context') else normalized)
        return output, 'CPU E5 + MiniLM NLI → ' + model_usage_label(final)
    classifier = get_classifier_llm(config)
    primary=getattr(classifier,'primary',classifier)
    batch_size = 1 if any(len(_question_text(item).encode('utf-8')) > 3000 for item in items) else 2
    if getattr(primary,'provider','')=='groq' and len(items)>batch_size:
        output=[]
        label=model_usage_label(classifier)
        for start in range(0,len(items),batch_size):
            batch,label=classify_question_batch(items[start:start+batch_size],subject_id,config)
            output.extend(batch)
        return output,label
    candidates = _embedding_candidates(items, concepts, config)

    # Mock/disabled mode still gives a useful deterministic front-end test.
    if not classifier.enabled or getattr(classifier, 'provider', '') == 'mock':
        by_name = {str(c['name']).casefold(): c for c in concepts}
        out = []
        for item in items:
            name, skill = _heuristic(item)
            c = by_name.get(name.casefold())
            out.append({
                'concept_id': int(c['id']) if c else None,
                'concept_name': c['name'] if c else name,
                'concept_description': c['description'] if c else '',
                'skill': skill,
                'cognitive_level': 'understand',
                'difficulty': int(item.get('difficulty') or 2),
                'confidence': 0.65 if c else 0.55,
                'reason': 'DEV/heuristic 概念歸類；正式模式會由 Classifier LLM 判斷。',
            })
        return out, 'DEV 概念分類器'

    payload = []
    for i, item in enumerate(items):
        payload.append({
            'index': i,
            'q_type': item.get('q_type'),
            'question': item.get('content'),
            'options': {k: item.get('option_' + k, '') for k in 'ABCD' if item.get('option_' + k)},
            'answer': item.get('answer_key'),
            'chapter': item.get('chapter_name'),
            'candidate_existing_concepts': [
                {'id': c['id'], 'name': c['name'], 'description': (c.get('description') or '')[:180], 'similarity': c.get('similarity')}
                for c in candidates.get(i, [])
            ],
        })

    system = '''你是「學習概念分類器」，不是出題模型。你的任務是判斷每一題真正測量的知識概念與技能。\n
重要規則：\n
1. 題目敘述、數字、人物或情境不同，但核心解法相同，必須歸為同一 Concept。\n
2. 同一批題目若本質相同，concept_name 必須完全一致。\n
3. 優先選擇 candidate_existing_concepts 中語意相同的既有 Concept，只有真的不同才建立新名稱。\n
4. 不要用整句題目當 Concept 名稱。Concept 應是穩定知識點，例如「二元一次聯立方程式」「SQL JOIN 與資料表關聯」。\n
5. skill 描述更細的能力，例如「文字題建模」「消去法」「判讀 INNER JOIN」。\n
6. cognitive_level 只能是 remember / understand / apply / analyze。\n
7. 只回 JSON。'''
    user = '請分類以下題目：\n' + json.dumps(payload, ensure_ascii=False) + '''\n\n回傳格式：
{"classifications":[{"index":0,"existing_concept_id":null,"concept_name":"...","concept_description":"...","skill":"...","cognitive_level":"apply","difficulty":2,"confidence":0.92,"reason":"..."}]}'''
    data = classifier.complete_json(system, user)
    rows = data.get('classifications', []) if isinstance(data, dict) else []
    mapped = {}
    for raw in rows:
        try:
            idx = int(raw.get('index'))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(items):
            mapped[idx] = _normalize_classification(raw, items[idx], existing_ids)

    out = []
    for i, item in enumerate(items):
        if i in mapped:
            out.append(mapped[i])
        else:
            name, skill = _heuristic(item)
            out.append({
                'concept_id': None, 'concept_name': name, 'concept_description': '', 'skill': skill,
                'cognitive_level': 'understand', 'difficulty': int(item.get('difficulty') or 2),
                'confidence': 0.35, 'reason': 'Classifier 未回傳此題，使用 fallback。'
            })
    for item, classification in zip(items, out):
        if item.get('_long_classification_context'):
            mark_review(classification)
    return out, f"{model_usage_label(classifier)} 概念分類"


def attach_classifications(items, classifications, strategy='concept'):
    result = []
    for item, c in zip(items, classifications):
        row = dict(item)
        row['_import_strategy'] = strategy
        row['_concept_id'] = c.get('concept_id')
        row['_concept_name'] = c.get('concept_name')
        row['_concept_description'] = c.get('concept_description')
        row['_skill'] = c.get('skill')
        row['_cognitive_level'] = c.get('cognitive_level')
        row['_concept_confidence'] = c.get('confidence')
        row['_classification_reason'] = c.get('reason')
        result.append(row)
    return result


def concept_summary(subject_id):
    base = db().execute('''SELECT c.id,c.name,c.description,c.chapter_id,ch.chapter_name,
        COUNT(si.id) source_count,
        COUNT(DISTINCT CASE WHEN si.skill IS NOT NULL AND si.skill<>'' THEN si.skill END) skill_count
        FROM concepts c
        LEFT JOIN chapters ch ON ch.id=c.chapter_id
        LEFT JOIN source_question_items si ON si.concept_id=c.id
        WHERE c.subject_id=?
        GROUP BY c.id,c.name,c.description,c.chapter_id,ch.chapter_name
        ORDER BY source_count DESC,c.name''',(subject_id,)).fetchall()
    rows = [dict(r) for r in base]
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    marks = ','.join('?' for _ in ids)
    src = db().execute(
        f"SELECT concept_id,q_type FROM source_question_items WHERE concept_id IN ({marks})",
        tuple(ids),
    ).fetchall()
    type_map = defaultdict(set)
    for item in src:
        if item['q_type']:
            type_map[int(item['concept_id'])].add(str(item['q_type']))
    for row in rows:
        row['q_types'] = ', '.join(sorted(type_map.get(int(row['id']), set()))) or '—'
    return rows
