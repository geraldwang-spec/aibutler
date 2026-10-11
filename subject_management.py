"""Subject folders and chapter organization, using the existing owned records."""
import json
import sqlite3

from flask import abort, flash, g, redirect, render_template, request, url_for

from auth import login_required
from records import CATALOG
from storage import db, locked_sql, StorageIntegrityError


def subject_owned(subject_id, lock=False):
    sql='SELECT * FROM subjects WHERE id=? AND created_by=?'
    row=db().execute(locked_sql(sql) if lock else sql,(subject_id,g.user['id'])).fetchone()
    if not row:
        abort(404)
    return row


def validate_chapter(data, record_id=None):
    subject_owned(data['subject_id'], lock=True)
    chapters={r['id']:dict(r) for r in db().execute('SELECT * FROM chapters WHERE subject_id=?',(data['subject_id'],))}
    parent=data.get('parent_chapter_id')
    seen={record_id} if record_id else set()
    while parent:
        if parent in seen:
            raise ValueError('上層章節不能選自己或自己的子章節。')
        if parent not in chapters:
            raise ValueError('上層章節必須屬於所選科目。跨科目移動時請先清空上層章節。')
        seen.add(parent)
        parent=chapters[parent]['parent_chapter_id']
    if any(r['id']!=record_id and r['chapter_name'].strip().casefold()==data['chapter_name'].casefold()
           and r['parent_chapter_id']==data.get('parent_chapter_id') for r in chapters.values()):
        raise ValueError('同一層已有同名章節，請改名或編輯現有章節。')
    if not record_id:
        return
    old=db().execute('SELECT * FROM chapters WHERE id=?',(record_id,)).fetchone()
    if old['subject_id']==data['subject_id']:
        return
    # Moving populated chapters would invalidate subject-specific concepts,
    # historical exams and planner scope. Never silently rewrite that history.
    if old['parent_chapter_id'] or db().execute('SELECT 1 FROM chapters WHERE parent_chapter_id=?',(record_id,)).fetchone():
        raise ValueError('請先解除上層與子章節關係，再移動科目。')
    for table in ('questions','summaries','import_items','study_plans','rag_chunks','ai_question_drafts',
                  'concepts','source_question_items','learning_phase_concepts','learning_tasks'):
        if db().execute(f'SELECT 1 FROM {table} WHERE chapter_id=? LIMIT 1',(record_id,)).fetchone():
            raise ValueError('此章節已有題目、教材或學習紀錄，請保留原科目；可新增章節收納新資料。')
    for table in ('exam_plans','learning_goals'):
        for row in db().execute(f'SELECT chapter_ids FROM {table} WHERE subject_id=?',(old['subject_id'],)):
            ids=json.loads(row['chapter_ids'] or '[]')
            if not ids or str(record_id) in {str(value) for value in ids}:
                raise ValueError('原科目已有涵蓋此章節的學習／考試計畫，暫不允許跨科目移動。')


def chapter_tree(rows):
    """Render all records even if legacy data contains an orphan or a cycle."""
    rows=[dict(r) for r in rows]
    by_id={r['id']:r for r in rows}
    children={}
    for row in rows:
        parent=row['parent_chapter_id'] if row['parent_chapter_id'] in by_id else None
        children.setdefault(parent,[]).append(row)
    result=[]
    seen=set()
    def walk(row, ancestors):
        if row['id'] in seen:
            return
        seen.add(row['id'])
        row['depth']=len(ancestors)
        row['ancestors']=' '.join(map(str,ancestors))
        row['child_count']=len(children.get(row['id'],[]))
        result.append(row)
        for child in children.get(row['id'],[]):
            walk(child,ancestors+[row['id']])
    for row in children.get(None,[]):
        walk(row,[])
    for row in rows:
        walk(row,[])
    return result


def render_subject_workspace(table, values, error, edit_id):
    subjects=db().execute('''SELECT s.*,
        (SELECT COUNT(*) FROM chapters c WHERE c.subject_id=s.id) AS chapter_count
        FROM subjects s WHERE s.created_by=? ORDER BY s.subject_name,s.id''',(g.user['id'],)).fetchall()
    # POST errors must keep the submitted edit id so saving again updates it.
    active_edit=request.form.get('id',type=int) if request.method=='POST' else edit_id
    sid=request.args.get('subject_id',type=int)
    if table=='chapters' and values:
        try:
            sid=int(values.get('subject_id') or sid or 0) or None
        except (ValueError,TypeError):
            pass
    elif table=='subjects' and active_edit:
        sid=active_edit
    if sid:
        selected=subject_owned(sid)
    else:
        selected=subjects[0] if subjects else None
        sid=selected['id'] if selected else None
    chapters=db().execute('''SELECT c.*,
        (SELECT COUNT(*) FROM questions q WHERE q.chapter_id=c.id AND COALESCE(q.source,'manual')<>'concept_dynamic') AS question_count,
        (SELECT COUNT(*) FROM source_question_items sc WHERE sc.chapter_id=c.id) AS source_count
        FROM chapters c WHERE c.subject_id=? ORDER BY c.order_no,c.id''',(sid,)).fetchall() if sid else []
    tree=chapter_tree(chapters)
    for chapter in tree:
        chapter['scope_ids']=[chapter['id']]+[row['id'] for row in tree if str(chapter['id']) in row['ancestors'].split()]
    chapter_values=values if table=='chapters' and values else {
        'subject_id':sid,'parent_chapter_id':request.args.get('parent_id',type=int),
        'order_no':min(999,max((r['order_no'] or 0 for r in chapters),default=0)+1)}
    return render_template('subject_workspace.html',title='科目與章節管理',error=error,
        subjects=subjects,selected_subject=selected,chapters=tree,
        subject_fields=CATALOG['subjects'][2],chapter_fields=CATALOG['chapters'][2],
        subject_values=values if table=='subjects' else {},chapter_values=chapter_values,
        subject_edit_id=active_edit if table=='subjects' else None,
        chapter_edit_id=active_edit if table=='chapters' else None,
        subject_form_open=table=='subjects' and (active_edit or error),
        chapter_form_open=(table=='chapters' and (active_edit or error)) or request.args.get('parent_id'),
        choices={'subject_id':[(r['id'],r['subject_name']) for r in subjects],
                 'parent_chapter_id':[(r['id'],'　'*min(r['depth'],5)+r['chapter_name']) for r in tree if table!='chapters' or r['id']!=active_edit]},
        question_total=sum(r['question_count'] for r in tree),source_total=sum(r['source_count'] for r in tree))


def register_subject_management(app):
    @app.post('/subjects/<int:subject_id>/organize')
    @login_required
    def organize_chapters(subject_id):
        subject_owned(subject_id,lock=True)
        try:
            action=request.form.get('action')
            if action=='bulk':
                text=request.form.get('chapter_names','')
                if len(text)>12000:
                    raise ValueError('一次最多貼上 12,000 字。')
                names=[name.strip() for name in text.splitlines() if name.strip()]
                if not 1<=len(names)<=100 or any(len(name)>120 for name in names):
                    raise ValueError('請每行填一個章節名稱，一次 1–100 個，每個最多 120 字。')
                parent=request.form.get('parent_chapter_id',type=int)
                if request.form.get('parent_chapter_id') and parent is None:
                    raise ValueError('請選擇有效的上層章節。')
                if parent and not db().execute('SELECT 1 FROM chapters WHERE id=? AND subject_id=?',(parent,subject_id)).fetchone():
                    raise ValueError('上層章節必須屬於目前科目。')
                existing=db().execute('SELECT chapter_name,order_no FROM chapters WHERE subject_id=? AND '+
                    ('parent_chapter_id=?' if parent else 'parent_chapter_id IS NULL'),
                    (subject_id,parent) if parent else (subject_id,)).fetchall()
                known={r['chapter_name'].strip().casefold() for r in existing}
                order=max((r['order_no'] or 0 for r in existing),default=0)
                added=0
                new_rows=[]
                for name in names:
                    if name.casefold() in known:
                        continue
                    order+=1
                    if order>999:
                        raise ValueError('排序已達上限，請先整理排序。')
                    new_rows.append((subject_id,parent,name,order))
                    known.add(name.casefold())
                    added+=1
                if new_rows:
                    db().execute('INSERT INTO chapters(subject_id,parent_chapter_id,chapter_name,order_no) VALUES '+
                                 ','.join('(?,?,?,?)' for row in new_rows),tuple(value for row in new_rows for value in row))
                message=f'已新增 {added} 個章節，略過 {len(names)-added} 個同層重複名稱。'
            elif action=='move':
                cid=request.form.get('chapter_id',type=int)
                current=db().execute('SELECT * FROM chapters WHERE id=? AND subject_id=?',(cid,subject_id)).fetchone()
                if not current:
                    abort(404)
                destination=request.form.get('destination_subject_id',type=int) or subject_id
                subject_owned(destination,lock=True)
                position=request.form.get('position')
                if position not in ('inside','before','after','root'):
                    abort(400)
                target_id=request.form.get('target_id',type=int)
                target=None
                if position!='root':
                    target=db().execute('SELECT * FROM chapters WHERE id=? AND subject_id=?',(target_id,destination)).fetchone()
                    if not target:
                        abort(404)
                    if target['id']==cid:
                        raise ValueError('請拖到其他章節或最上層。')
                parent=target['id'] if position=='inside' else (target['parent_chapter_id'] if target else None)
                data=dict(subject_id=destination,parent_chapter_id=parent,
                          chapter_name=current['chapter_name'],order_no=current['order_no'] or 0)
                validate_chapter(data,cid)
                siblings=[dict(r) for r in db().execute('SELECT id FROM chapters WHERE subject_id=? AND '+
                    ('parent_chapter_id=?' if parent else 'parent_chapter_id IS NULL')+' AND id<>? ORDER BY order_no,id',
                    (destination,parent,cid) if parent else (destination,cid))]
                if len(siblings)>=1000:
                    raise ValueError('同層章節過多，請先分成子章節。')
                index=len(siblings)
                if position in ('before','after'):
                    index=next(i for i,row in enumerate(siblings) if row['id']==target['id'])+(1 if position=='after' else 0)
                siblings.insert(index,{'id':cid})
                db().execute('UPDATE chapters SET subject_id=?,parent_chapter_id=? WHERE id=?',(destination,parent,cid))
                cases=' '.join('WHEN ? THEN ?' for row in siblings)
                params=tuple(value for order,row in enumerate(siblings) for value in (row['id'],order))
                db().execute('UPDATE chapters SET order_no=CASE id '+cases+' END WHERE subject_id=? AND id IN ('+
                             ','.join('?' for row in siblings)+')',params+(destination,)+tuple(row['id'] for row in siblings))
                subject_id=destination
                message='已依拖曳位置整理章節，章節內的資料與紀錄仍保留。'
            elif action in ('up','down'):
                cid=request.form.get('chapter_id',type=int)
                rows=[dict(r) for r in db().execute('SELECT * FROM chapters WHERE subject_id=? ORDER BY order_no,id',(subject_id,))]
                current=next((r for r in rows if r['id']==cid),None)
                if not current:
                    abort(404)
                siblings=[r for r in rows if r['parent_chapter_id']==current['parent_chapter_id']]
                if len(siblings)>1000:
                    raise ValueError('同層章節過多，請先分成子章節。')
                index=next(i for i,r in enumerate(siblings) if r['id']==cid)
                neighbor=index+(-1 if action=='up' else 1)
                if 0<=neighbor<len(siblings):
                    siblings[index],siblings[neighbor]=siblings[neighbor],siblings[index]
                cases=' '.join('WHEN ? THEN ?' for row in siblings)
                params=tuple(value for order,row in enumerate(siblings) for value in (row['id'],order))
                db().execute('UPDATE chapters SET order_no=CASE id '+cases+' END WHERE subject_id=? AND id IN ('+
                             ','.join('?' for row in siblings)+')',params+(subject_id,)+tuple(row['id'] for row in siblings))
                message='已更新同層章節順序。'
            else:
                abort(400)
            db().commit()
            flash(message,'success')
        except (ValueError,sqlite3.IntegrityError,StorageIntegrityError) as exc:
            db().rollback()
            flash(str(exc) if isinstance(exc,ValueError) else '章節關聯有誤，這次操作未儲存。','error')
        return redirect(url_for('records',table='subjects',subject_id=subject_id))
