import json
from storage import db,locked_sql


def change(user_id,concept_id,action,name='',target_id=None,description=''):
    db().execute('BEGIN IMMEDIATE')
    concept=db().execute(locked_sql('SELECT co.* FROM concepts co JOIN subjects s ON s.id=co.subject_id WHERE co.id=? AND s.created_by=?'),(concept_id,user_id)).fetchone()
    if not concept: raise ValueError('找不到概念。')
    if action=='merge':
        target=db().execute('SELECT * FROM concepts WHERE id=? AND subject_id=?',(target_id,concept['subject_id'])).fetchone()
        if not target or int(target['id'])==int(concept_id): raise ValueError('請選擇同科目的另一概念。')
        db().execute('INSERT INTO question_concepts(question_id,concept_id,weight) SELECT qc.question_id,?,qc.weight FROM question_concepts qc WHERE qc.concept_id=? AND NOT EXISTS(SELECT 1 FROM question_concepts tq WHERE tq.question_id=qc.question_id AND tq.concept_id=?)',(target_id,concept_id,target_id))
        for table in ('source_question_items','micro_courses','learning_tasks','learning_phase_concepts'):
            db().execute(f'UPDATE {table} SET concept_id=? WHERE concept_id=?',(target_id,concept_id))
        db().execute('DELETE FROM question_concepts WHERE concept_id=?',(concept_id,))
        db().execute('DELETE FROM concepts WHERE id=?',(concept_id,))
        new_name=target['name']
    else:
        name=name.strip()
        if not name or len(name)>255 or len(description)>1200: raise ValueError('概念名稱需為 1–255 字，說明最多 1200 字。')
        if db().execute('SELECT 1 FROM concepts WHERE subject_id=? AND name=? AND id<>?',(concept['subject_id'],name,concept_id)).fetchone():
            raise ValueError('名稱已存在，請使用合併。')
        db().execute('UPDATE concepts SET name=?,description=? WHERE id=?',(name,description,concept_id))
        new_name=name;target_id=concept_id
    for row in db().execute("SELECT d.id,d.concepts_json FROM ai_question_drafts d WHERE d.subject_id=? AND d.status='draft'",(concept['subject_id'],)):
        names=json.loads(row['concepts_json'] or '[]')
        if concept['name'] in names:
            names=[new_name if n==concept['name'] else n for n in names]
            db().execute('UPDATE ai_question_drafts SET concepts_json=? WHERE id=?',(json.dumps(names,ensure_ascii=False),row['id']))
    rows=db().execute("SELECT ii.id,ii.parsed_json FROM import_items ii JOIN exam_imports ei ON ei.id=ii.import_id WHERE ei.subject_id=? AND ei.user_id=? AND ei.status='待確認'",(concept['subject_id'],user_id)).fetchall()
    for row in rows:
        item=json.loads(row['parsed_json'])
        if item.get('_concept_id')==concept_id:
            item.update(_concept_id=target_id,_concept_name=new_name)
            db().execute('UPDATE import_items SET parsed_json=? WHERE id=?',(json.dumps(item,ensure_ascii=False),row['id']))
    db().execute('INSERT INTO concept_change_log(user_id,subject_id,old_name,new_name,action) VALUES (?,?,?,?,?)',(user_id,concept['subject_id'],concept['name'],new_name,action))
    db().commit()


def move_source(user_id,source_id,name,skill):
    row=db().execute('SELECT * FROM source_question_items WHERE id=? AND user_id=?',(source_id,user_id)).fetchone()
    if not row: raise ValueError('來源不存在。')
    name=name.strip()
    if not name or len(name)>255: raise ValueError('概念名稱需為 1–255 字。')
    co=db().execute('SELECT id FROM concepts WHERE subject_id=? AND name=?',(row['subject_id'],name)).fetchone()
    cid=co['id'] if co else db().execute('INSERT INTO concepts(subject_id,chapter_id,name,importance) VALUES (?,?,?,3)',(row['subject_id'],row['chapter_id'],name)).lastrowid
    db().execute('UPDATE source_question_items SET concept_id=?,skill=? WHERE id=?',(cid,skill[:255],source_id))
    db().execute('INSERT INTO concept_change_log(user_id,subject_id,old_name,new_name,action) VALUES (?,?,?,?,?)',(user_id,row['subject_id'],str(row['concept_id']),name,'move_source'))
    db().commit()


def classify_fixed(user_id,subject_id,config):
    if not db().execute('SELECT 1 FROM subjects WHERE id=? AND created_by=?',(subject_id,user_id)).fetchone(): raise ValueError('科目不存在。')
    rows=db().execute('SELECT q.*,ch.chapter_name FROM questions q JOIN chapters ch ON ch.id=q.chapter_id WHERE ch.subject_id=? AND NOT EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) ORDER BY q.id',(subject_id,)).fetchall()
    items=[dict(row) for row in rows]
    if not items: raise ValueError('沒有需要補標的題目。')
    for item in items:
        for op in db().execute('SELECT * FROM question_options WHERE question_id=?',(item['id'],)):
            item['option_'+op['option_label']]=op['option_text']
    from .concept_classifier import classify_question_batch
    classified,_=classify_question_batch(items,subject_id,config)
    for item,proposal in zip(items,classified):
        name=proposal['concept_name']
        co=db().execute('SELECT id FROM concepts WHERE subject_id=? AND name=?',(subject_id,name)).fetchone()
        cid=co['id'] if co else db().execute('INSERT INTO concepts(subject_id,chapter_id,name,importance) VALUES (?,?,?,3)',(subject_id,item['chapter_id'],name)).lastrowid
        if not db().execute('SELECT 1 FROM question_concepts WHERE question_id=? AND concept_id=?',(item['id'],cid)).fetchone():
            db().execute('INSERT INTO question_concepts(question_id,concept_id,weight) VALUES (?,?,1)',(item['id'],cid))
    db().commit()
    return len(items)
