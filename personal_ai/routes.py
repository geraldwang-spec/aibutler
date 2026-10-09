from __future__ import annotations
import json, os, secrets, calendar as cal
from pathlib import Path
from flask import Blueprint,current_app,g,redirect,render_template,request,flash,url_for,abort,jsonify
from auth import login_required
from storage import db, backend
from .jobs import submit, read as read_job, update as update_job
from .parsers import parse_file,chunk_sections
from .services import generate_question_drafts
from .llm_provider import LLMError, get_llm, get_classifier_llm, get_generator_llm, get_reviewer_llm, get_course_llm, get_tutor_llm
from .embedding_provider import get_embedder, vector_literal
from .coaching import calculate_concept_weakness, answer_wrong_question, tutor_history, create_learning_goal_plan, replan_learning_goal, goal_progress, register_planner_quiz_attempt, planner_task_required_score
from .microcourse import create_micro_course, get_course, list_courses, answer_step, ask_course_tutor, complete_course

bp=Blueprint('personal_ai',__name__,template_folder='templates')

def _subjects(): return db().execute('SELECT * FROM subjects WHERE created_by=? ORDER BY subject_name',(g.user['id'],)).fetchall()
def _subject(sid):
    r=db().execute('SELECT * FROM subjects WHERE id=? AND created_by=?',(sid,g.user['id'])).fetchone()
    if not r: abort(404)
    return r

@bp.route('/knowledge',methods=['GET','POST'])
@login_required
def knowledge():
    error=None
    if request.method=='POST':
        path=None
        try:
            sid=int(request.form.get('subject_id','0')); _subject(sid)
            chapter_id=int(request.form.get('chapter_id','0') or 0) or None
            if chapter_id:
                ok=db().execute('SELECT 1 FROM chapters WHERE id=? AND subject_id=?',(chapter_id,sid)).fetchone()
                if not ok: raise ValueError('章節不屬於所選科目。')
            f=request.files.get('file')
            if not f or not f.filename: raise ValueError('請選擇教材檔案。')
            ext=Path(f.filename).suffix.lower()
            if ext not in {'.pdf','.docx','.xlsx','.xlsm','.txt','.md','.csv'}: raise ValueError('目前支援 PDF、DOCX、XLSX、TXT、MD、CSV。')
            root=Path(current_app.instance_path)/'personal_ai_uploads'/str(g.user['id']); root.mkdir(parents=True,exist_ok=True)
            safe=secrets.token_hex(8)+ext; path=root/safe; f.save(path)
            sections=parse_file(path); chunks=chunk_sections(sections)
            from .data_safety import safe_source, redact_text
            for chunk in chunks:
                chunk['text']=safe_source(chunk['text'])
                chunk['title']=redact_text(chunk['title'])
            chunks=[chunk for chunk in chunks if chunk['text'].strip()]
            if not chunks:
                raise ValueError('教材沒有可用的安全文字內容，請確認檔案不是空白或僅含敏感資料／系統指令。')
            vectors=None; embedding_model=None
            embedder=get_embedder(current_app.config)
            if backend()=='postgresql' and embedder.enabled and embedder.provider != 'cpu' and chunks:
                vectors=embedder.embed([c['text'] for c in chunks]); embedding_model=embedder.model
                if len(vectors)!=len(chunks): raise RuntimeError('Embedding 回傳數量與 chunks 不一致。')
            mid=db().execute('INSERT INTO materials(user_id,subject_id,title,file_path,file_type,page_count,parse_status) VALUES (?,?,?,?,?,?,?)',(g.user['id'],sid,Path(f.filename).name,str(path),ext.lstrip('.'),len(sections),'完成')).lastrowid
            did=db().execute('INSERT INTO rag_documents(source_type,material_id,title) VALUES (?,?,?)',('upload',mid,Path(f.filename).name)).lastrowid
            for i,c in enumerate(chunks):
                cid=db().execute('INSERT INTO rag_chunks(doc_id,chunk_index,content,token_count,chapter_id) VALUES (?,?,?,?,?)',(did,i,c['text'],len(c['text'])//2,chapter_id)).lastrowid
                if vectors is not None:
                    db().execute('UPDATE rag_chunks SET embedding=?::vector, embedding_model=? WHERE id=?',(vector_literal(vectors[i]),embedding_model,cid))
                db().execute('INSERT INTO rag_chunk_meta(chunk_id,source_locator,section_title) VALUES (?,?,?)',(cid,c['locator'],c['title']))
            db().commit(); mode='pgvector' if vectors is not None else '文字檢索 fallback'
            flash(f'教材已解析：{len(sections)} 個區段、{len(chunks)} 個 chunks；檢索模式：{mode}。','success')
            return redirect(url_for('personal_ai.knowledge'))
        except Exception as exc:
            db().rollback(); error=str(exc)
            if path: path.unlink(missing_ok=True)
    mats=db().execute('''SELECT m.*,s.subject_name,(SELECT count(*) FROM rag_documents rd JOIN rag_chunks rc ON rc.doc_id=rd.id WHERE rd.material_id=m.id) chunk_count FROM materials m JOIN subjects s ON s.id=m.subject_id WHERE m.user_id=? ORDER BY m.id DESC''',(g.user['id'],)).fetchall()
    chapters=db().execute('''SELECT c.* FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE s.created_by=? ORDER BY c.subject_id,c.order_no,c.id''',(g.user['id'],)).fetchall()
    return render_template('knowledge.html',title='教材知識庫',subjects=_subjects(),chapters=chapters,materials=mats,error=error)

@bp.route('/ai/questions',methods=['GET','POST'])
@login_required
def ai_questions():
    error=None
    if request.method=='POST':
        try:
            sid=int(request.form.get('subject_id','0')); _subject(sid)
            chapter_ids=[int(x) for x in request.form.getlist('chapter_ids') if x.isdigit()]
            count=max(1,min(20,int(request.form.get('count','5')))); difficulty=max(1,min(5,int(request.form.get('difficulty','3'))))
            qtypes=request.form.getlist('q_types') or ['單選']
            generation_mode=request.form.get('generation_mode','hybrid')
            if generation_mode not in ('hybrid','novel'):
                raise ValueError('出題策略設定不正確。')
            generation_config=dict(current_app.config,EXAM_GENERATION_MODE=generation_mode)
            job_id=submit(current_app._get_current_object(),g.user['id'],'questions',dict(generation_mode=generation_mode,arguments=dict(subject_id=sid,chapter_ids=chapter_ids,count=count,q_types=qtypes,difficulty=difficulty,focus=request.form.get('focus','').strip())))
            return redirect(url_for('personal_ai.job_page',job_id=job_id))
        except (ValueError,LLMError,RuntimeError) as exc: error=str(exc)
    subjects=_subjects(); chapters=db().execute('''SELECT c.* FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE s.created_by=? ORDER BY c.subject_id,c.order_no,c.id''',(g.user['id'],)).fetchall()
    drafts=db().execute('''SELECT d.*,s.subject_name,c.chapter_name FROM ai_question_drafts d JOIN subjects s ON s.id=d.subject_id LEFT JOIN chapters c ON c.id=d.chapter_id WHERE d.user_id=? AND d.status='draft' ORDER BY d.id DESC''',(g.user['id'],)).fetchall()
    drafts=[dict(d,options=json.loads(d['options_json'] or '{}')) for d in drafts]
    return render_template('ai_questions.html',title='RAG + LLM 動態出題',subjects=subjects,chapters=chapters,drafts=drafts,error=error,llm_enabled=str(current_app.config.get('GENERATOR_PROVIDER') or current_app.config.get('LLM_PROVIDER','disabled'))!='disabled')

@bp.post('/ai/questions/<int:draft_id>/approve')
@login_required
def approve_question(draft_id):
    from storage import locked_sql, StorageIntegrityError
    import sqlite3
    from .draft_review import prepare, apply
    action=request.form.get('action','approve')
    if action not in ('approve','reject','save'): abort(400)
    db().execute('BEGIN IMMEDIATE')
    d=db().execute(locked_sql('SELECT * FROM ai_question_drafts WHERE id=? AND user_id=?'),(draft_id,g.user['id'])).fetchone()
    if not d:
        db().rollback(); abort(404)
    try:
        if d['status']=='draft':
            apply(d,action,None if action=='reject' else prepare(d,request.form,g.user['id']))
            db().commit()
            flash({'save':'草稿已修正。','approve':'已加入正式題庫並建立概念關聯。','reject':'草稿已退回。'}[action],'success')
        else: db().rollback()
    except (ValueError,TypeError,sqlite3.IntegrityError,StorageIntegrityError) as exc:
        db().rollback(); flash(str(exc) if isinstance(exc,(ValueError,TypeError)) else '題庫資料有衝突，尚未寫入，請重新整理後再試。','error')
    return redirect(url_for('personal_ai.ai_questions'))


@bp.post('/ai/questions/batch')
@login_required
def bulk_questions():
    from .draft_batch import bulk_questions as review_batch
    return review_batch()


@bp.get('/ai/concepts')
@login_required
def concepts():
    subject_id=request.args.get('subject_id',type=int)
    subjects=_subjects()
    rows=[]
    samples=[]
    if subject_id:
        _subject(subject_id)
        from .concept_classifier import concept_summary
        rows=concept_summary(subject_id)
        samples=db().execute('SELECT sq.*,c.name AS concept_name FROM source_question_items sq '
            'JOIN concepts c ON c.id=sq.concept_id WHERE sq.user_id=? AND sq.subject_id=? '
            'ORDER BY sq.id DESC LIMIT 100',(g.user['id'],subject_id)).fetchall()
        samples=[dict(s,options=json.loads(s['options_json'] or '{}')) for s in samples]
    return render_template('concepts.html',title='Concept Bank',subjects=subjects,concepts=rows,samples=samples,subject_id=subject_id)


@bp.route('/ai/status', methods=['GET','POST'])
@login_required
def ai_status():
    from .exam_modules import installation_ready
    llm = get_llm(current_app.config)
    classifier = get_classifier_llm(current_app.config)
    generator = get_generator_llm(current_app.config)
    reviewer = get_reviewer_llm(current_app.config)
    course = get_course_llm(current_app.config)
    tutor = get_tutor_llm(current_app.config)
    embedder = get_embedder(current_app.config)
    llm_result = None
    embedding_result = None
    classifier_result = None
    generator_result = None
    reviewer_result = None
    course_result = None
    tutor_result = None
    if request.method == 'POST':
        action = request.form.get('action','')
        if action == 'test_llm':
            llm_result = llm.ping()
        elif action == 'test_classifier':
            classifier_result = classifier.ping()
        elif action == 'test_generator':
            generator_result = generator.ping()
        elif action == 'test_reviewer':
            reviewer_result = reviewer.ping()
        elif action == 'test_course':
            course_result = course.ping()
        elif action == 'test_tutor':
            tutor_result = tutor.ping()
        elif action == 'test_embedding':
            embedding_result = embedder.ping()
    return render_template(
        'ai_status.html',
        title='AI 模型與執行環境',
        app_mode=current_app.config.get('APP_MODE','dev'),
        db_type=current_app.config.get('DB_TYPE'),
        llm_provider=current_app.config.get('LLM_PROVIDER','disabled'),
        llm_model=current_app.config.get('LLM_MODEL','') or getattr(llm,'model',''),
        embedding_provider=current_app.config.get('EMBEDDING_PROVIDER','disabled'),
        embedding_model=current_app.config.get('EMBEDDING_MODEL','') or getattr(embedder,'model',''),
        classifier_provider=current_app.config.get('CLASSIFIER_PROVIDER','disabled'),
        classifier_model=current_app.config.get('CLASSIFIER_MODEL','') or getattr(classifier,'model',''),
        generator_provider=current_app.config.get('GENERATOR_PROVIDER','disabled'),
        generator_model=current_app.config.get('GENERATOR_MODEL','') or getattr(generator,'model',''),
        reviewer_provider=current_app.config.get('REVIEWER_PROVIDER','disabled'),
        reviewer_model=current_app.config.get('REVIEWER_MODEL','') or getattr(reviewer,'model',''),
        reviewer_fallback_model=current_app.config.get('REVIEWER_FALLBACK_MODEL',''),
        generator_fallback_model=current_app.config.get('GENERATOR_FALLBACK_MODEL',''),
        course_provider=current_app.config.get('COURSE_PROVIDER','disabled'),
        course_model=current_app.config.get('COURSE_MODEL','') or getattr(course,'model',''),
        course_fallback_model=current_app.config.get('COURSE_FALLBACK_MODEL',''),
        tutor_provider=current_app.config.get('TUTOR_PROVIDER','disabled'),
        tutor_model=current_app.config.get('TUTOR_MODEL','') or getattr(tutor,'model',''),
        tutor_fallback_model=current_app.config.get('TUTOR_FALLBACK_MODEL',''),
        groq_key_configured=bool(current_app.config.get('GROQ_API_KEY')),
        exam_modular_enabled=str(current_app.config.get('EXAM_MODULAR_AI','false')).lower()=='true',
        exam_cpu_models_ready=installation_ready(),
        voice_enabled=current_app.config.get('VOICE_ENABLED',False),
        stt_provider=current_app.config.get('STT_PROVIDER','faster_whisper'),
        stt_model=current_app.config.get('STT_MODEL','large-v3'),
        tts_provider=current_app.config.get('TTS_PROVIDER','kokoro'),
        tts_model=current_app.config.get('TTS_MODEL','hexgrad/Kokoro-82M'),
        llm_result=llm_result,
        classifier_result=classifier_result,
        generator_result=generator_result,
        reviewer_result=reviewer_result,
        course_result=course_result,
        tutor_result=tutor_result,
        embedding_result=embedding_result,
    )


@bp.route('/ai/tutor/<int:question_id>', methods=['GET','POST'])
@login_required
def wrong_tutor(question_id):
    error=None
    result=None
    try:
        if request.method=='POST':
            followup=(request.form.get('followup') or '').strip()
            if len(followup)>1500:
                raise ValueError('追問內容不可超過 1500 字。')
            job_id=submit(current_app._get_current_object(),g.user['id'],'wrong_tutor',dict(question_id=question_id,followup=followup))
            return redirect(url_for('personal_ai.job_page',job_id=job_id))
        else:
            from .coaching import wrong_question_context
            q = wrong_question_context(g.user['id'],question_id)
            if not q: abort(404)
            history = tutor_history(g.user['id'],question_id)
            result = dict(question=q,answer=history[-1]['content'] if history else '',chunks=[],mode='已儲存教學')
    except (ValueError,RuntimeError) as exc:
        error=str(exc)
    history=tutor_history(g.user['id'],question_id)
    question=result.get('question') if result else None
    return render_template('wrong_tutor.html',title='錯題 AI 教學',result=result,history=history,question=question,error=error)


@bp.get('/ai/weakness')
@login_required
def concept_weakness():
    subject_id=request.args.get('subject_id',type=int)
    if subject_id:
        _subject(subject_id)
    rows=calculate_concept_weakness(g.user['id'],subject_id)
    return render_template('concept_weakness.html',title='Concept 弱項分析',subjects=_subjects(),rows=rows,subject_id=subject_id,recent_limit=20,minimum_sample=3)


@bp.route('/ai/planner', methods=['GET','POST'])
@login_required
def adaptive_planner():
    from datetime import date
    error=None
    if request.method=='POST':
        try:
            sid=int(request.form.get('subject_id','0')); _subject(sid)
            goal_name=(request.form.get('goal_name') or '').strip()
            exam_date=date.fromisoformat(request.form.get('exam_date',''))
            chapter_ids=[int(x) for x in request.form.getlist('chapter_ids') if x.isdigit()]
            weekday=max(10,min(480,int(request.form.get('weekday_minutes','60'))))
            weekend=max(10,min(720,int(request.form.get('weekend_minutes','90'))))
            starting=(request.form.get('starting_level') or 'auto').strip()
            goal_id=create_learning_goal_plan(g.user['id'],sid,goal_name,exam_date,chapter_ids,weekday,weekend,starting)
            flash('學習目標已建立。系統已依考試日拆成階段、里程碑、Checkpoint 與考前緩衝。','success')
            return redirect(url_for('personal_ai.adaptive_planner',goal_id=goal_id))
        except (ValueError,TypeError) as exc:
            db().rollback(); error=str(exc)

    subjects=_subjects()
    chapters=db().execute("SELECT c.* FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE s.created_by=? ORDER BY c.subject_id,c.order_no,c.id",(g.user['id'],)).fetchall()
    goals=db().execute("""SELECT lg.*,s.subject_name FROM learning_goals lg
        JOIN subjects s ON s.id=lg.subject_id WHERE lg.user_id=? ORDER BY lg.status='active' DESC,lg.exam_date""",(g.user['id'],)).fetchall()
    goal_id=request.args.get('goal_id',type=int)
    if not goal_id and goals:
        goal_id=int(goals[0]['id'])
    current=None; phases=[]; milestones=[]; tasks=[]; progress={'total':0,'done':0,'percent':0}
    if goal_id:
        current=db().execute("""SELECT lg.*,s.subject_name FROM learning_goals lg JOIN subjects s ON s.id=lg.subject_id
            WHERE lg.id=? AND lg.user_id=?""",(goal_id,g.user['id'])).fetchone()
        if current:
            phases=db().execute("SELECT * FROM learning_phases WHERE goal_id=? ORDER BY phase_no",(goal_id,)).fetchall()
            milestones=db().execute("SELECT * FROM learning_milestones WHERE goal_id=? ORDER BY target_date,id",(goal_id,)).fetchall()
            raw_tasks=db().execute("""SELECT lt.*,lp.name phase_name FROM learning_tasks lt LEFT JOIN learning_phases lp ON lp.id=lt.phase_id
                WHERE lt.goal_id=? AND lt.user_id=? ORDER BY lt.task_date,lt.id""",(goal_id,g.user['id'])).fetchall()
            attempts=db().execute("""SELECT lca.* FROM learning_checkpoint_attempts lca
                JOIN learning_tasks lt ON lt.id=lca.task_id WHERE lt.goal_id=? AND lt.user_id=? ORDER BY lca.id DESC""",(goal_id,g.user['id'])).fetchall()
            latest={}
            for a in attempts:
                latest.setdefault(int(a['task_id']),dict(a))
            tasks=[]
            for row in raw_tasks:
                item=dict(row); item['attempt']=latest.get(int(row['id']))
                if int(item.get('question_count') or 0)>0:
                    item['required_score']=planner_task_required_score(item)
                tasks.append(item)
            progress=goal_progress(g.user['id'],goal_id)

    # Build a real month calendar. Month navigation never changes the learning plan.
    today_obj=date.today()
    month_arg=(request.args.get('month') or '').strip()
    try:
        if month_arg:
            year,month=map(int,month_arg.split('-',1)); month_anchor=date(year,month,1)
        else:
            month_anchor=date(today_obj.year,today_obj.month,1)
    except Exception:
        month_anchor=date(today_obj.year,today_obj.month,1)
    prev_anchor=(month_anchor.replace(day=1)-__import__('datetime').timedelta(days=1)).replace(day=1)
    next_anchor=(month_anchor.replace(day=28)+__import__('datetime').timedelta(days=4)).replace(day=1)
    by_date={}
    for t in tasks:
        by_date.setdefault(str(t['task_date'])[:10],[]).append(t)
    weeks=[]
    for week in cal.Calendar(firstweekday=0).monthdatescalendar(month_anchor.year,month_anchor.month):
        cells=[]
        for d in week:
            cells.append({'date':d.isoformat(),'day':d.day,'in_month':d.month==month_anchor.month,
                          'is_today':d==today_obj,'tasks':by_date.get(d.isoformat(),[])})
        weeks.append(cells)
    calendar_view={'label':f'{month_anchor.year} 年 {month_anchor.month} 月','month':month_anchor.strftime('%Y-%m'),
                   'prev':prev_anchor.strftime('%Y-%m'),'next':next_anchor.strftime('%Y-%m'),'weeks':weeks}
    return render_template('adaptive_planner.html',title='學習目標規劃',subjects=subjects,chapters=chapters,goals=goals,current=current,phases=phases,milestones=milestones,tasks=tasks,progress=progress,error=error,today=today_obj.isoformat(),calendar_view=calendar_view)


@bp.post('/ai/planner/task/<int:task_id>/checkpoint/start')
@login_required
def adaptive_plan_checkpoint_start(task_id):
    task=db().execute("""SELECT lt.*,lg.subject_id,lg.chapter_ids FROM learning_tasks lt
        JOIN learning_goals lg ON lg.id=lt.goal_id WHERE lt.id=? AND lt.user_id=?""",(task_id,g.user['id'])).fetchone()
    if not task: abort(404)
    if int(task['question_count'] or 0)<=0:
        flash('這一天是學習 / 複習安排，不是系統測驗；進度不會用手動勾選判定。','info')
        return redirect(url_for('personal_ai.adaptive_planner',goal_id=task['goal_id']))
    if task['status']=='done':
        flash('這個測驗已達標通過，不需要重複解鎖。','info')
        return redirect(url_for('personal_ai.adaptive_planner',goal_id=task['goal_id']))

    chapter_ids=[]
    if task['phase_id']:
        rows=db().execute("SELECT DISTINCT chapter_id FROM learning_phase_concepts WHERE phase_id=? AND chapter_id IS NOT NULL",(task['phase_id'],)).fetchall()
        chapter_ids=[int(r['chapter_id']) for r in rows]
    if not chapter_ids:
        try: chapter_ids=[int(x) for x in json.loads(task['chapter_ids'] or '[]')]
        except Exception: chapter_ids=[]
    if task['chapter_id'] and int(task['chapter_id']) not in chapter_ids:
        chapter_ids.append(int(task['chapter_id']))

    from TYE.exam_module import create_quiz
    try:
        job_id=submit(current_app._get_current_object(),g.user['id'],'quiz',dict(subject_id=int(task['subject_id']),count=int(task['question_count']),mode='模擬考',chapter_ids=chapter_ids,q_types=['單選','多選','是非','填空'],random_order=True,question_source='auto',planner_task_id=task_id))
        return redirect(url_for('personal_ai.job_page',job_id=job_id))
    except (ValueError,RuntimeError,LLMError) as exc:
        db().rollback(); flash(str(exc),'error')
        return redirect(url_for('personal_ai.adaptive_planner',goal_id=task['goal_id']))


@bp.post('/ai/planner/<int:goal_id>/replan')
@login_required
def adaptive_plan_replan(goal_id):
    try:
        replan_learning_goal(g.user['id'],goal_id)
        flash('已依目前作答結果與弱項重新安排尚未完成的學習任務；已完成紀錄不會被覆蓋。','success')
    except ValueError as exc:
        flash(str(exc),'error')
    return redirect(url_for('personal_ai.adaptive_planner',goal_id=goal_id))


@bp.route('/ai/micro-courses', methods=['GET','POST'])
@login_required
def micro_courses():
    error=None
    subject_id=request.args.get('subject_id',type=int)
    if request.method=='POST':
        try:
            concept_id=int(request.form.get('concept_id','0'))
            minutes=max(3,min(15,int(request.form.get('minutes','5'))))
            job_id=submit(current_app._get_current_object(),g.user['id'],'course',dict(concept_id=concept_id,minutes=minutes))
            return redirect(url_for('personal_ai.job_page',job_id=job_id))
        except (ValueError,TypeError,RuntimeError) as exc:
            db().rollback(); error=str(exc)
    subjects=_subjects()
    if subject_id:
        _subject(subject_id)
    weakness=calculate_concept_weakness(g.user['id'],subject_id)
    courses=list_courses(g.user['id'])
    return render_template('micro_courses.html',title='AI 弱項微課程',subjects=subjects,weakness=weakness,courses=courses,subject_id=subject_id,error=error)


@bp.route('/ai/micro-course/<int:course_id>', methods=['GET','POST'])
@login_required
def micro_course(course_id):
    error=None
    if request.method=='POST':
        try:
            action=request.form.get('action','')
            if action=='answer':
                step_id=int(request.form.get('step_id','0'))
                answer=(request.form.get('answer') or '').strip()
                if not answer:
                    raise ValueError('請先輸入你的回答。')
                correct,feedback=answer_step(g.user['id'],course_id,step_id,answer)
                flash(('答對了。' if correct else '回答已記錄。')+' '+feedback,'success' if correct else 'info')
            elif action=='ask':
                job_id=submit(current_app._get_current_object(),g.user['id'],'course_tutor',dict(course_id=course_id,question=request.form.get('question','')))
                return redirect(url_for('personal_ai.job_page',job_id=job_id))
            elif action=='complete':
                complete_course(g.user['id'],course_id)
                flash('這堂微課程已完成。接下來可回到模擬考，用全新題目確認是否真正掌握。','success')
            return redirect(url_for('personal_ai.micro_course',course_id=course_id))
        except (ValueError,TypeError,RuntimeError) as exc:
            db().rollback(); error=str(exc)
    course=get_course(g.user['id'],course_id)
    if not course:
        abort(404)
    return render_template('micro_course.html',title=course['title'],course=course,error=error,
                           voice_enabled=current_app.config.get('VOICE_ENABLED',False),
                           stt_model=current_app.config.get('STT_MODEL','large-v3'),
                           tts_model=current_app.config.get('TTS_MODEL','hexgrad/Kokoro-82M'))


@bp.get('/ai/jobs/<job_id>')
@login_required
def job_page(job_id):
    job=read_job(current_app,job_id,g.user['id'])
    if not job: abort(404)
    from .data_safety import redact_text
    job['error']=redact_text(job.get('error'))
    return render_template('ai_job.html',title='AI 工作',job=job,result=json.loads(job['result']) if job['result'] else None)

@bp.get('/ai/jobs/<job_id>/status')
@login_required
def job_status(job_id):
    job=read_job(current_app,job_id,g.user['id'])
    if not job: return jsonify(error='找不到這個工作，或您沒有存取權限。'),404
    payload={k:job[k] for k in ('status','calls','input_tokens','output_tokens','error')}
    payload['result']=json.loads(job['result']) if job['result'] else None
    from .data_safety import sanitize
    return jsonify(sanitize(payload))

@bp.post('/ai/jobs/<job_id>/cancel')
@login_required
def job_cancel(job_id):
    job=read_job(current_app,job_id,g.user['id'])
    if not job: abort(404)
    if job['status'] in ('queued','running'): update_job(current_app,job_id,cancel=1)
    return redirect(url_for('personal_ai.job_page',job_id=job_id))


@bp.get('/chat')
@login_required
def chat_index():
    chats=db().execute('SELECT * FROM chat_sessions WHERE user_id=? ORDER BY id DESC',(g.user['id'],)).fetchall()
    return render_template('chat.html',title='AI 對話',chats=chats,chat=None,messages=[],subjects=_subjects(),pending_job=None,chat_error=None)

@bp.post('/chat/new')
@login_required
def chat_new():
    from .chat import validate_question
    ajax=request.headers.get('X-Requested-With')=='XMLHttpRequest'
    cid=None
    try:
        question=validate_question(g.user['id'],request.form.get('question',''),request.form.get('subject_id',type=int))
        cid=db().execute('INSERT INTO chat_sessions(user_id,title) VALUES (?,?)',(g.user['id'],'新對話')).lastrowid
        db().commit()
        job_id=submit(current_app._get_current_object(),g.user['id'],'chat',dict(chat_id=cid,question=question,subject_id=request.form.get('subject_id',type=int)))
        if ajax:
            return jsonify(chat_id=cid,chat_url=url_for('personal_ai.chat_page',chat_id=cid),
                           status_url=url_for('personal_ai.job_status',job_id=job_id)),202
        return redirect(url_for('personal_ai.chat_page',chat_id=cid))
    except ValueError as exc:
        db().rollback()
        # No submitted job means the placeholder session has no content to keep.
        if cid:
            db().execute('DELETE FROM chat_sessions WHERE id=? AND user_id=?',(cid,g.user['id']))
            db().commit()
        if ajax: return jsonify(error=str(exc)),400
        flash(str(exc),'error')
        return redirect(url_for('personal_ai.chat_index'))

@bp.route('/chat/<int:chat_id>',methods=['GET','POST'])
@login_required
def chat_page(chat_id):
    chat=db().execute('SELECT * FROM chat_sessions WHERE id=? AND user_id=?',(chat_id,g.user['id'])).fetchone()
    if not chat: abort(404)
    if request.method=='POST':
        try:
            from .chat import validate_question
            question=validate_question(g.user['id'],request.form.get('question',''),request.form.get('subject_id',type=int))
            job_id=submit(current_app._get_current_object(),g.user['id'],'chat',dict(chat_id=chat_id,question=question,subject_id=request.form.get('subject_id',type=int)))
            if request.headers.get('X-Requested-With')=='XMLHttpRequest':
                return jsonify(chat_id=chat_id,chat_url=url_for('personal_ai.chat_page',chat_id=chat_id),
                               status_url=url_for('personal_ai.job_status',job_id=job_id)),202
            return redirect(url_for('personal_ai.chat_page',chat_id=chat_id))
        except ValueError as exc:
            if request.headers.get('X-Requested-With')=='XMLHttpRequest': return jsonify(error=str(exc)),400
            flash(str(exc),'error')
    chats=db().execute('SELECT * FROM chat_sessions WHERE user_id=? ORDER BY id DESC',(g.user['id'],)).fetchall()
    messages=db().execute('SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id',(chat_id,)).fetchall()
    from .jobs import latest_chat_job
    latest=latest_chat_job(current_app,g.user['id'],chat_id)
    pending=url_for('personal_ai.job_status',job_id=latest['id']) if latest and latest['status'] in ('queued','running') else None
    chat_error=latest['error'] if latest and latest['status'] in ('failed','cancelled') else None
    last_payload=json.loads(latest['payload']) if latest else {}
    return render_template('chat.html',title=chat['title'],chat=chat,chats=chats,messages=messages,subjects=_subjects(),pending_job=pending,chat_error=chat_error,
                           selected_subject_id=last_payload.get('subject_id'),retry_question=last_payload.get('question') if chat_error else None)


@bp.post('/ai/concepts/<int:concept_id>/change')
@login_required
def concept_change(concept_id):
    from .concept_admin import change
    try:
        change(g.user['id'],concept_id,request.form.get('action','rename'),request.form.get('name',''),request.form.get('target_id',type=int),request.form.get('description',''))
        flash('概念已更新，歷史題目快照保留。','success')
    except (ValueError,RuntimeError) as exc:
        db().rollback();flash(str(exc),'error')
    return redirect(url_for('personal_ai.concepts',subject_id=request.form.get('subject_id',type=int)))

@bp.post('/ai/concepts/source/<int:source_id>')
@login_required
def concept_source_move(source_id):
    from .concept_admin import move_source
    try:
        move_source(g.user['id'],source_id,request.form.get('name',''),request.form.get('skill',''));flash('來源歸類已調整。','success')
    except ValueError as exc:
        db().rollback();flash(str(exc),'error')
    return redirect(url_for('personal_ai.concepts',subject_id=request.form.get('subject_id',type=int)))

@bp.post('/ai/concepts/classify-fixed')
@login_required
def classify_fixed_start():
    try:
        sid=int(request.form.get('subject_id','0'));_subject(sid)
        job_id=submit(current_app._get_current_object(),g.user['id'],'classify_fixed',dict(subject_id=sid))
        return redirect(url_for('personal_ai.job_page',job_id=job_id))
    except ValueError as exc:
        flash(str(exc),'error');return redirect(url_for('personal_ai.concepts'))

@bp.post('/ai/planner/task/<int:task_id>/read')
@login_required
def planner_read(task_id):
    task=db().execute('SELECT * FROM learning_tasks WHERE id=? AND user_id=?',(task_id,g.user['id'])).fetchone()
    if not task:abort(404)
    if task['task_type'] in ('休息','運動建議'):
        if request.headers.get('X-Requested-With')=='XMLHttpRequest':
            return jsonify(error='休息與可選活動不需要記錄已閱讀。'),400
        return redirect(url_for('personal_ai.adaptive_planner',goal_id=task['goal_id']))
    if not task['question_count'] and task['status'] not in ('done','read'):
        db().execute("UPDATE learning_tasks SET status='read',completed_at=CURRENT_TIMESTAMP WHERE id=?",(task_id,));db().commit()
    if request.headers.get('X-Requested-With')=='XMLHttpRequest':
        if task['question_count']:
            return jsonify(error='測驗任務必須由系統評分驗收。'),400
        return jsonify(task_id=task_id,status='done' if task['status']=='done' else 'read',message='已記錄閱讀；正式進度由測驗驗收。')
    return redirect(url_for('personal_ai.adaptive_planner',goal_id=task['goal_id']))
