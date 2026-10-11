import json
from flask import g
from storage import db,locked_sql
from .question_validation import validate


def revise(batch,item_id,form):
    db().execute('BEGIN IMMEDIATE')
    record=db().execute(locked_sql('SELECT * FROM exam_imports WHERE id=? AND user_id=?'),(batch,g.user['id'])).fetchone()
    if not record or record['status']!='待確認': raise ValueError('只有待確認批次可修正。')
    row=db().execute('SELECT * FROM import_items WHERE id=? AND import_id=?',(item_id,batch)).fetchone()
    if not row: raise ValueError('找不到匯入題目。')
    if form.get('action')=='remove':
        count=db().execute('SELECT COUNT(*) FROM import_items WHERE import_id=?',(batch,)).fetchone()[0]
        if count<=1: raise ValueError('至少保留一題；不需要的批次可取消。')
        db().execute('DELETE FROM import_items WHERE id=?',(item_id,))
        db().execute('UPDATE exam_imports SET total_rows=total_rows-1 WHERE id=?',(batch,))
    else:
        item=json.loads(row['parsed_json'])
        for key in ('chapter_name','q_type','content','answer_key','explanation','difficulty'):
            item[key]=form.get(key,item.get(key,''))
        if not str(item['chapter_name']).strip() or len(item['chapter_name'])>120:
            raise ValueError('章節名稱需為 1–120 字。')
        options={k:form.get('option_'+k,item.get('option_'+k,'')) for k in 'ABCD'}
        item,pairs=validate(item,options)
        for k in 'ABCD': item['option_'+k]=dict(pairs).get(k,'')
        if item.get('_import_strategy')=='concept':
            name=(form.get('concept_name') or item.get('_concept_name') or '').strip()
            if not name or len(name)>255: raise ValueError('概念名稱需為 1–255 字。')
            co=db().execute('SELECT id FROM concepts WHERE subject_id=? AND name=?',(record['subject_id'],name)).fetchone()
            item.update(_concept_name=name,_concept_id=co['id'] if co else None,_skill=form.get('skill',item.get('_skill',''))[:255],_classification_reason='人工修正')
        db().execute('UPDATE import_items SET parsed_json=? WHERE id=?',(json.dumps(item,ensure_ascii=False),item_id))
    db().commit()
