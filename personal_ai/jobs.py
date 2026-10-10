"""Persistent, user-owned AI jobs. One bounded worker; no model call during boot."""
import contextvars
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from flask import g, url_for

active_job = contextvars.ContextVar('ai_job', default=None)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ai-job')
_chat_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chat-reply')
_lock = threading.Lock()


@contextmanager
def ledger(app):
    path=Path(app.instance_path)/'ai_jobs.sqlite'
    path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,user_id INTEGER,kind TEXT,payload TEXT,status TEXT,created REAL,updated REAL,cancel INTEGER DEFAULT 0,calls INTEGER DEFAULT 0,input_tokens INTEGER DEFAULT 0,output_tokens INTEGER DEFAULT 0,result TEXT,error TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS import_checkpoints (job_id TEXT,user_id INTEGER,key TEXT,value TEXT,PRIMARY KEY(job_id,key))')
    con.commit()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def read(app,job_id,user_id):
    with ledger(app) as con:
        row=con.execute('SELECT * FROM jobs WHERE id=? AND user_id=?',(job_id,user_id)).fetchone()
    return dict(row) if row else None


def update(app,job_id,**values):
    with ledger(app) as con:
        con.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+',updated=? WHERE id=?',(*values.values(),time.time(),job_id))


def submit(app,user_id,kind,payload):
    from storage import read_only
    from .data_safety import validate_user_text, redact_text
    def protect_fields(data):
        if not isinstance(data,dict): return data
        result=dict(data)
        for key,value in result.items():
            if key in ('question','followup','focus') and isinstance(value,str):
                validate_user_text(value)
                result[key]=redact_text(value)
            elif isinstance(value,dict): result[key]=protect_fields(value)
        return result
    payload=protect_fields(payload)
    if read_only(): raise ValueError('唯讀備援無法新增 AI 工作。')
    with _lock,ledger(app) as con:
        rows=con.execute("SELECT id FROM jobs WHERE user_id=? AND status IN ('queued','running')",(user_id,)).fetchall()
        if rows: raise ValueError('已有 AI 工作等待或執行中，請先完成或取消。')
        job_id=uuid.uuid4().hex
        now=time.time()
        con.execute('INSERT INTO jobs(id,user_id,kind,payload,status,created,updated) VALUES (?,?,?,?,?,?,?)',
                    (job_id,user_id,kind,json.dumps(payload,ensure_ascii=False),'queued',now,now))
        if payload.get('resume_from') and kind=='import':
            source=con.execute("SELECT id FROM jobs WHERE id=? AND user_id=? AND kind='import' AND status IN ('failed','cancelled')",(payload['resume_from'],user_id)).fetchone()
            if not source: raise ValueError('只能接續您自己的已中斷匯入工作。')
            con.execute('INSERT INTO import_checkpoints(job_id,user_id,key,value) '
                        'SELECT ?,user_id,key,value FROM import_checkpoints WHERE job_id=? AND user_id=?',
                        (job_id,payload['resume_from'],user_id))
    (_chat_executor if kind=='chat' else _executor).submit(run,app,job_id,user_id)
    return job_id


def latest_chat_job(app,user_id,chat_id):
    with ledger(app) as con:
        rows=con.execute("SELECT * FROM jobs WHERE user_id=? AND kind='chat' ORDER BY created DESC LIMIT 200",(user_id,)).fetchall()
    for row in rows:
        if json.loads(row['payload']).get('chat_id')==chat_id:
            return dict(row)
    return None


def guard(reserve=0):
    job=active_job.get()
    if not job: return
    row=read(job['app'],job['id'],job['user_id'])
    if row['cancel']: raise RuntimeError('工作已取消；已送出的單次 API 請求仍需等待結束。')
    update(job['app'],job['id'],calls=row['calls']+1)


def usage(data,model,elapsed):
    job=active_job.get()
    values=data.get('usage') or {}
    incoming=int(values.get('prompt_tokens') or 0); outgoing=int(values.get('completion_tokens') or 0)
    if job:
        row=read(job['app'],job['id'],job['user_id'])
        update(job['app'],job['id'],input_tokens=row['input_tokens']+incoming,output_tokens=row['output_tokens']+outgoing)
        app=job['app']; user=job['user_id']
    else:
        from flask import current_app, has_app_context
        if not has_app_context(): return
        app=current_app; user=getattr(g,'user',None)
        user=user['id'] if user else None
    path=Path(app.instance_path)/'ai_usage.jsonl'
    with _lock:
        with path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(time=time.time(),user_id=user,model=model,input_tokens=incoming,output_tokens=outgoing,seconds=round(elapsed,3),job_id=job['id'] if job else None))+'\n')


def run(app,job_id,user_id):
    from storage import db, read_only
    with app.app_context():
        row=read(app,job_id,user_id)
        # No application-imposed quota or total deadline; individual API requests
        # still have connection timeouts and bounded retries. Cancellation remains.
        token=active_job.set(dict(app=app,id=job_id,user_id=user_id,kind=row['kind']))
        try:
            if row['cancel']:
                update(app,job_id,status='cancelled'); return
            g.user=db().execute('SELECT * FROM users WHERE id=? AND is_email_verified=1',(user_id,)).fetchone()
            if not g.user or read_only(): raise ValueError('帳號不可用或目前為唯讀備援。')
            update(app,job_id,status='running')
            payload=json.loads(row['payload'])
            result=dispatch(app,user_id,row['kind'],payload)
            update(app,job_id,status='completed',result=json.dumps(result,ensure_ascii=False),error=None)
        except Exception as exc:
            if getattr(g,'db',None): g.db.rollback()
            pending=getattr(g,'import_pending_path',None)
            if pending: pending.unlink(missing_ok=True)
            latest=read(app,job_id,user_id)
            from .data_safety import redact_text
            import traceback
            update(app,job_id,status='cancelled' if latest['cancel'] else 'failed',error=redact_text(str(exc))[:1000])
            app.logger.error('AI job %s failed\n%s',job_id,redact_text(traceback.format_exc()))
        finally:
            active_job.reset(token)


def dispatch(app,user_id,kind,p):
    from storage import db
    if kind=='questions':
        from .services import generate_question_drafts
        ids=generate_question_drafts(dict(app.config,EXAM_GENERATION_MODE=p['generation_mode']),user_id,**p['arguments'])
        return dict(message=f'已產生 {len(ids)} 題草稿',url='/ai/questions')
    if kind=='quiz':
        from TYE.exam_module import create_quiz
        task_id=p.pop('planner_task_id',None)
        sid=create_quiz(**p,commit=not bool(task_id))
        if task_id:
            from .coaching import register_planner_quiz_attempt
            register_planner_quiz_attempt(user_id,task_id,sid)
        return dict(message='考卷已建立',url=f'/quiz/{sid}')
    if kind=='course':
        from .microcourse import create_micro_course
        cid=create_micro_course(user_id,**p)
        return dict(message='課程已建立',url=f'/ai/micro-course/{cid}')
    if kind=='wrong_tutor':
        from .coaching import answer_wrong_question
        answer_wrong_question(user_id,**p)
        return dict(message='教學已完成',url=f"/ai/tutor/{p['question_id']}")
    if kind=='course_tutor':
        from .microcourse import ask_course_tutor
        ask_course_tutor(user_id,**p)
        return dict(message='回答已完成',url=f"/ai/micro-course/{p['course_id']}")
    if kind=='import':
        from smartlife import process_import_file
        from werkzeug.datastructures import MultiDict,FileStorage
        path=Path(p['path'])
        from .import_checkpoints import get
        previous=get('final_batch_id')
        if previous:
            saved=db().execute('SELECT id FROM exam_imports WHERE id=? AND user_id=?',(previous,user_id)).fetchone()
            if saved:
                path.unlink(missing_ok=True)
                return dict(message='已有完整預覽，不重複建立',url=f'/imports/{previous}')
        with path.open('rb') as f:
            batch=process_import_file(app,MultiDict(p['form']),FileStorage(f,filename=p['filename']))
        path.unlink(missing_ok=True)
        missing=get('answer_failures',[])
        message=f'可用題目分析已完成（{len(missing)} 題待補資料），請確認' if missing else '解析已完成，請確認'
        return dict(message=message,url=f'/imports/{batch}')
    if kind=='classify_fixed':
        from .concept_admin import classify_fixed
        count=classify_fixed(user_id,p['subject_id'],app.config)
        return dict(message=f'已補標 {count} 題概念',url='/ai/concepts?subject_id='+str(p['subject_id']))
    if kind=='chat':
        from .chat import generate_reply
        reply=generate_reply(user_id,**p)
        return dict(message='回答已完成',url=f"/chat/{p['chat_id']}",**reply)
    raise ValueError('不支援的 AI 工作。')


def recover(app):
    # Never automatically repeat billed work after a process restart.
    with ledger(app) as con:
        con.execute("UPDATE jobs SET status='failed',error='服務重新啟動，工作中斷。請查看既有成果後重新提交。',updated=? WHERE status IN ('running','queued')",(time.time(),))
