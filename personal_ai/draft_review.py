"""Draft review operations; the caller owns the transaction and row locks."""
import json
from storage import db
from .question_validation import validate


def prepare(draft, edits, user_id, allowed_chapters=None):
    data = {key: edits.get(key, draft[key]) for key in
            ('q_type', 'content', 'answer_key', 'explanation', 'difficulty')}
    options = json.loads(draft['options_json'] or '{}')
    options = {key: edits.get('option_' + key, options.get(key, '')) for key in 'ABCD'}
    data, pairs = validate(data, options)
    # An explicitly cleared chapter must not silently reuse the old chapter.
    chapter_id = int(edits.get('chapter_id', draft['chapter_id']) or 0)
    chapter_ok = ((chapter_id, draft['subject_id']) in allowed_chapters) if allowed_chapters is not None else db().execute(
        'SELECT 1 FROM chapters c JOIN subjects s ON s.id=c.subject_id '
        'WHERE c.id=? AND c.subject_id=? AND s.created_by=?',
        (chapter_id, draft['subject_id'], user_id)).fetchone()
    if not chapter_ok:
        raise ValueError('請指定此科目的章節。')
    return data, pairs, chapter_id


def apply(draft, action, prepared=None):
    if action == 'reject':
        db().execute("UPDATE ai_question_drafts SET status='rejected' WHERE id=?", (draft['id'],))
        return
    data, pairs, chapter_id = prepared
    db().execute('UPDATE ai_question_drafts SET chapter_id=?,q_type=?,content=?,answer_key=?,explanation=?,options_json=?,difficulty=? WHERE id=?',
                 (chapter_id, data['q_type'], data['content'], data['answer_key'], data['explanation'],
                  json.dumps(dict(pairs), ensure_ascii=False), data['difficulty'], draft['id']))
    if action == 'save':
        return
    qid = db().execute('INSERT INTO questions(chapter_id,q_type,content,answer_key,explanation,difficulty,source) VALUES (?,?,?,?,?,?,?)',
                       (chapter_id, data['q_type'], data['content'], data['answer_key'], data['explanation'],
                        data['difficulty'], 'rag_llm')).lastrowid
    for n, (label, text) in enumerate(pairs, 1):
        db().execute('INSERT INTO question_options(question_id,option_label,option_text,order_no) VALUES (?,?,?,?)',
                     (qid, label, text, n))
    db().execute('INSERT INTO question_metadata(question_id,source_type,generation_model,evidence_chunk_ids,concepts_json,skill,is_verified) VALUES (?,?,?,?,?,?,1)',
                 (qid, 'human_approved', draft['model_name'], draft['evidence_chunk_ids'], draft['concepts_json'], draft['skill']))
    seen = set()
    for name in json.loads(draft['concepts_json'] or '[]'):
        concept = db().execute('SELECT id FROM concepts WHERE subject_id=? AND lower(name)=lower(?)',
                               (draft['subject_id'], str(name))).fetchone()
        if concept and concept['id'] not in seen:
            seen.add(concept['id'])
            db().execute('INSERT INTO question_concepts(question_id,concept_id,weight) VALUES (?,?,1)', (qid, concept['id']))
    db().execute("UPDATE ai_question_drafts SET status='approved',approved_question_id=? WHERE id=?", (qid, draft['id']))
