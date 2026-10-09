"""Private durable import progress, scoped to an authenticated AI job owner."""
import hashlib
import json
from .jobs import active_job, ledger


def get(key, default=None):
    job=active_job.get()
    if not job or job.get('kind')!='import': return default
    return read(job['app'],job['id'],job['user_id'],key,default)


def read(app,job_id,user_id,key,default=None):
    with ledger(app) as con:
        row=con.execute('SELECT value FROM import_checkpoints WHERE job_id=? AND user_id=? AND key=?',
                        (job_id,user_id,key)).fetchone()
    return json.loads(row['value']) if row else default


def put(key,value):
    job=active_job.get()
    if not job or job.get('kind')!='import': return
    with ledger(job['app']) as con:
        con.execute('INSERT INTO import_checkpoints(job_id,user_id,key,value) VALUES(?,?,?,?) '
                    'ON CONFLICT(job_id,key) DO UPDATE SET value=excluded.value',
                    (job['id'],job['user_id'],key,json.dumps(value,ensure_ascii=False)))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def snapshot(app,job_id,user_id):
    questions=read(app,job_id,user_id,'questions',[])
    total=read(app,job_id,user_id,'total',len(questions))
    return dict(questions=questions,completed=len(questions),total=total,
                remaining=max(0,total-len(questions)),stage=read(app,job_id,user_id,'stage','尚未完成一批'))
