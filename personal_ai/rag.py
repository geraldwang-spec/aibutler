from __future__ import annotations

import math
import re

from flask import current_app

from storage import backend, db
from .embedding_provider import EmbeddingError, get_embedder, vector_literal
from .data_safety import safe_source, redact_text, validate_user_text

def related(query, text):
    return bool(set(_terms(query)) & set(_terms(text)))


def _terms(text):
    # Overlapping Chinese terms avoid depending on an arbitrary four-character boundary.
    stop = {'請問', '幫我', '可以', '什麼', '甚麼', '如何', '為何', '今天', '這個', '那個',
            '解釋', '說明', '一下', '告訴', '我想', '知道', 'the', 'is', 'a', 'an', 'of', 'to', 'and'}
    terms = []
    for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text or ""):
        if re.fullmatch(r'[\u4e00-\u9fff]+', token):
            terms.extend(token[index:index+2] for index in range(len(token)-1))
        else:
            terms.append(token.lower())
    return [term for term in terms if term not in stop]


def _lexical(user_id, subject_id, query, chapter_ids=None, limit=8, require_relevance=False):
    params = [user_id, subject_id]
    where = "m.user_id=? AND m.subject_id=?"
    if chapter_ids:
        marks = ",".join("?" for _ in chapter_ids)
        where += f" AND rc.chapter_id IN ({marks})"
        params += list(chapter_ids)
    rows = db().execute(
        f"""SELECT rc.id,rc.content,rc.chapter_id,rm.source_locator,rm.section_title,m.title material_title
        FROM rag_chunks rc
        JOIN rag_documents rd ON rd.id=rc.doc_id
        JOIN materials m ON m.id=rd.material_id
        LEFT JOIN rag_chunk_meta rm ON rm.chunk_id=rc.id
        WHERE {where}""",
        tuple(params),
    ).fetchall()
    q = set(_terms(query))
    scored = []
    for raw in rows:
        row = dict(raw)
        row['content'] = safe_source(row['content'])
        if not row['content'].strip():
            continue
        for key in ('material_title','section_title','source_locator'):
            row[key] = redact_text(row.get(key))
        terms = _terms(row["content"])
        tf = sum(1 for term in terms if term in q)
        score = tf / (math.sqrt(len(terms)) + 1) if q else 0
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [row for score, row in scored[:limit] if score > 0]
    return selected if require_relevance else (selected or [row for _, row in scored[:limit]])


def retrieve(user_id, subject_id, query, chapter_ids=None, limit=8, require_relevance=True):
    """Use pgvector cosine distance when possible; otherwise lexical fallback."""
    validate_user_text(query)
    query=redact_text(query)
    if not db().execute('SELECT 1 FROM subjects WHERE id=? AND created_by=?',(subject_id,user_id)).fetchone():
        raise ValueError('科目不屬於此帳號。')
    if chapter_ids:
        chapter_ids=list(dict.fromkeys(int(cid) for cid in chapter_ids))
        marks=','.join('?' for _ in chapter_ids)
        owned=db().execute(f'SELECT id FROM chapters WHERE subject_id=? AND id IN ({marks})',(subject_id,*chapter_ids)).fetchall()
        if {row['id'] for row in owned} != set(chapter_ids):
            raise ValueError('章節不屬於所選科目。')
    limit=max(1,min(24,int(limit)))
    if not require_relevance:
        if query.strip():
            raise ValueError('有指定問題時不可略過教材相關性檢查。')
        return _lexical(user_id,subject_id,'',chapter_ids,limit,False)
    if str(current_app.config.get('EMBEDDING_PROVIDER', '')).lower() == 'cpu':
        from .exam_modules import rank
        candidates = [dict(row) for row in _lexical(user_id,subject_id,query,chapter_ids,max(limit,24),require_relevance)]
        if not candidates:
            return []
        order = rank(query,[row['content'] for row in candidates])
        return [candidates[i] for i,_ in order[:limit]]
    if backend() == "postgresql":
        embedder = get_embedder(current_app.config)
        if embedder.enabled:
            try:
                vec = vector_literal(embedder.embed_query(query))
                params = [user_id, subject_id]
                where = "m.user_id=? AND m.subject_id=? AND rc.embedding IS NOT NULL"
                if chapter_ids:
                    marks = ",".join("?" for _ in chapter_ids)
                    where += f" AND rc.chapter_id IN ({marks})"
                    params += list(chapter_ids)
                sql = f"""SELECT rc.id,rc.content,rc.chapter_id,rm.source_locator,rm.section_title,
                           m.title material_title,1-(rc.embedding <=> ?::vector) AS vector_score
                    FROM rag_chunks rc
                    JOIN rag_documents rd ON rd.id=rc.doc_id
                    JOIN materials m ON m.id=rd.material_id
                    LEFT JOIN rag_chunk_meta rm ON rm.chunk_id=rc.id
                    WHERE {where}
                    ORDER BY rc.embedding <=> ?::vector
                    LIMIT ?"""
                rows = db().execute(sql, tuple([vec] + params + [vec, limit])).fetchall()
                if rows:
                    if require_relevance:
                        relevant = {row['id']: row for row in _lexical(user_id,subject_id,query,chapter_ids,limit=24,require_relevance=True)}
                        return [relevant[row['id']] for row in rows if row['id'] in relevant]
                    return rows
            except EmbeddingError:
                pass
    return _lexical(user_id, subject_id, query, chapter_ids, limit,require_relevance)
