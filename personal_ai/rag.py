from __future__ import annotations

import math
import re

from flask import current_app

from storage import backend, db
from .embedding_provider import EmbeddingError, get_embedder, vector_literal


def _terms(text):
    return [x.lower() for x in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{1,4}", text or "")]


def _lexical(user_id, subject_id, query, chapter_ids=None, limit=8):
    params = [user_id, subject_id]
    where = "m.user_id=? AND m.subject_id=?"
    if chapter_ids:
        marks = ",".join("?" for _ in chapter_ids)
        where += f" AND (rc.chapter_id IS NULL OR rc.chapter_id IN ({marks}))"
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
    for row in rows:
        terms = _terms(row["content"])
        tf = sum(1 for term in terms if term in q)
        score = tf / (math.sqrt(len(terms)) + 1) if q else 0
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [row for score, row in scored[:limit] if score > 0]
    return selected or [row for _, row in scored[:limit]]


def retrieve(user_id, subject_id, query, chapter_ids=None, limit=8):
    """Use pgvector cosine distance when possible; otherwise lexical fallback."""
    if backend() == "postgresql":
        embedder = get_embedder(current_app.config)
        if embedder.enabled:
            try:
                vec = vector_literal(embedder.embed_query(query))
                params = [user_id, subject_id]
                where = "m.user_id=? AND m.subject_id=? AND rc.embedding IS NOT NULL"
                if chapter_ids:
                    marks = ",".join("?" for _ in chapter_ids)
                    where += f" AND (rc.chapter_id IS NULL OR rc.chapter_id IN ({marks}))"
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
                    return rows
            except EmbeddingError:
                pass
    return _lexical(user_id, subject_id, query, chapter_ids, limit)
