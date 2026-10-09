import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import g
from app import create_app
from storage import db
from personal_ai import jobs,import_checkpoints as checkpoints
from personal_ai.llm_provider import GroqLLM,OpenAICompatibleLLM,LLMError
from personal_ai.question_answering import infer_missing_answers


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'SECRET_KEY':'checkpoint-only',
                             'DATABASE':str(Path(self.directory.name)/'test.db'),'DB_READ_ONLY':False})
        self.app.instance_path=self.directory.name
        self.context=self.app.test_request_context('/imports')
        self.context.push()
        db().execute("INSERT INTO users(id,username,email,password_hash,is_email_verified) VALUES(1,'tester','test@example.com','unused',1)")
        db().commit()
        g.user={'id':1}
        with jobs.ledger(self.app) as con:
            con.execute("INSERT INTO jobs(id,user_id,kind,payload,status,created,updated) VALUES('old',1,'import','{}','running',?,?)",(time.time(),time.time()))
        self.token=jobs.active_job.set(dict(app=self.app,id='old',user_id=1,kind='import',deadline=time.monotonic()+600,max_calls=40,max_tokens=32000))

    def tearDown(self):
        jobs.active_job.reset(self.token)
        self.context.pop()
        self.directory.cleanup()

    def test_previous_daily_usage_does_not_block_new_or_resumed_job(self):
        jobs.update(self.app,'old',status='failed',calls=500,input_tokens=200000,output_tokens=10000)
        with patch.dict('os.environ',AI_DAILY_MAX_TOKENS='1',AI_DAILY_MAX_CALLS='1'):
            with patch.object(jobs._executor,'submit'):
                resumed=jobs.submit(self.app,1,'import',{'resume_from':'old'})
            token=jobs.active_job.set(dict(app=self.app,id=resumed,user_id=1,deadline=time.monotonic()+600,max_calls=40,max_tokens=32000))
            try:
                jobs.guard(1000)
                self.assertEqual(jobs.read(self.app,resumed,1)['calls'],1)
            finally:
                jobs.active_job.reset(token)
        self.assertEqual(jobs.read(self.app,'old',1)['input_tokens'],200000)

    def test_single_job_usage_is_unlimited_but_cancellation_remains(self):
        jobs.update(self.app,'old',calls=500,input_tokens=200000,output_tokens=50000)
        job=jobs.active_job.get()
        job['deadline']=time.monotonic()-1
        jobs.guard(1000000)
        self.assertEqual(jobs.read(self.app,'old',1)['calls'],501)
        jobs.update(self.app,'old',cancel=1)
        with self.assertRaisesRegex(RuntimeError,'取消'):
            jobs.guard()

    def test_failure_preserves_answers_and_resume_skips_completed(self):
        items=[dict(_question_no=i,content='題目',q_type='單選',answer_key='',option_A='甲',option_B='乙') for i in range(1,6)]
        class Solver:
            enabled=True
            provider='test'
            model='test'
            calls=0
            def complete_json(self,system,user):
                self.calls+=1
                if self.calls==2: raise RuntimeError('AI 工作已達總請求數或 token 額度')
                payload=json.loads(user.split('\n回傳 ')[0])
                return {'answers':[dict(number=x['number'],status='answered',answer='B',explanation='理由',context='') for x in payload]}
        model=Solver()
        with patch('personal_ai.question_answering.get_parser_llm',return_value=model):
            with self.assertRaisesRegex(RuntimeError,'token'):
                infer_missing_answers(items,[],Path('book.txt'),{})
        progress=checkpoints.snapshot(self.app,'old',1)
        self.assertEqual((progress['completed'],progress['remaining']),(4,1))
        model.calls=0
        with patch('personal_ai.question_answering.get_parser_llm',return_value=model):
            result=infer_missing_answers(items,[],Path('book.txt'),{})
        self.assertEqual(len(result),5)
        self.assertEqual(model.calls,1)
        self.assertEqual(checkpoints.snapshot(self.app,'old',2)['completed'],0)

    def test_cached_groq_response_never_calls_or_charges_again(self):
        model=GroqLLM('test-model','test-key')
        response={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],
                  'usage':{'prompt_tokens':10,'completion_tokens':2}}
        with patch.object(OpenAICompatibleLLM,'_request',return_value=response) as remote:
            self.assertEqual(model.complete_json('JSON','測試'),{'ok':True})
            self.assertEqual(model.complete_json('JSON','測試'),{'ok':True})
        self.assertEqual(remote.call_count,1)
        row=jobs.read(self.app,'old',1)
        self.assertEqual((row['calls'],row['input_tokens'],row['output_tokens']),(1,10,2))

    def test_resume_clones_private_checkpoint_not_daily_usage(self):
        checkpoints.put('questions',[{'content':'完成題','answer_key':'B'}])
        jobs.update(self.app,'old',status='failed',input_tokens=100,output_tokens=20)
        with patch.object(jobs._executor,'submit'):
            resumed=jobs.submit(self.app,1,'import',{'resume_from':'old'})
        self.assertEqual(checkpoints.snapshot(self.app,resumed,1)['completed'],1)
        self.assertEqual(jobs.read(self.app,'old',1)['input_tokens'],100)
        self.assertEqual(jobs.read(self.app,resumed,1)['input_tokens'],0)

    def test_restart_preserves_saved_results(self):
        checkpoints.put('questions',[{'content':'完成題','answer_key':'B'}])
        jobs.recover(self.app)
        self.assertEqual(jobs.read(self.app,'old',1)['status'],'failed')
        self.assertEqual(checkpoints.snapshot(self.app,'old',1)['completed'],1)

    def test_full_job_failure_keeps_source_and_resume_creates_preview(self):
        folder=Path(self.app.instance_path)/'job_uploads'
        folder.mkdir()
        source=folder/'fixture.txt'
        source.write_text('\n'.join(f'{i}. 題目\n(A)甲\n(B)乙' for i in range(1,6)),encoding='utf-8')
        db().execute("INSERT INTO subjects(id,subject_name,created_by) VALUES(1,'測試',1)")
        db().commit()
        payload=dict(path=str(source),filename='fixture.txt',form=[('subject_id','1'),('import_strategy','question_bank'),('parse_mode','auto')])
        jobs.update(self.app,'old',payload=json.dumps(payload))
        class Solver:
            enabled=True
            provider='test'
            model='test'
            calls=0
            def complete_json(self,s,u):
                self.calls+=1
                if self.calls==2: raise RuntimeError('AI 工作已達總請求數或 token 額度')
                data=json.loads(u.split('\n回傳 ')[0])
                return {'answers':[dict(number=x['number'],status='answered',answer='B',explanation='理由',context='') for x in data]}
        solver=Solver()
        with patch('personal_ai.question_answering.get_parser_llm',return_value=solver):
            jobs.run(self.app,'old',1)
        self.assertEqual(jobs.read(self.app,'old',1)['status'],'failed')
        self.assertTrue(source.is_file())
        self.assertEqual(checkpoints.snapshot(self.app,'old',1)['completed'],4)
        with patch.object(jobs._executor,'submit'):
            resumed=jobs.submit(self.app,1,'import',dict(payload,resume_from='old'))
        solver.calls=0
        with patch('personal_ai.question_answering.get_parser_llm',return_value=solver):
            jobs.run(self.app,resumed,1)
        completed=jobs.read(self.app,resumed,1)
        self.assertEqual(completed['status'],'completed',completed['error'])
        self.assertEqual(solver.calls,1)
        self.assertEqual(checkpoints.snapshot(self.app,resumed,1)['completed'],5)
        self.assertFalse(source.exists())
        self.assertEqual(db().execute('SELECT COUNT(*) FROM import_items').fetchone()[0],5)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM questions').fetchone()[0],0)

    def test_concept_import_accepts_43_questions(self):
        import io
        from werkzeug.datastructures import FileStorage,MultiDict
        from smartlife import process_import_file
        db().execute("INSERT INTO subjects(id,subject_name,created_by) VALUES(1,'測試',1)")
        db().commit()
        content='chapter_name,content,answer_key,q_type,option_A,option_B\n'+''.join(
            f'章節,第{i}題,A,單選,甲,乙\n' for i in range(43))
        upload=FileStorage(io.BytesIO(content.encode()),filename='fixture.csv')
        classifications=[dict(concept_id=None,concept_name='測試概念',skill='理解',cognitive_level='understand',difficulty=2,confidence=.8,reason='test',concept_description='') for _ in range(43)]
        with patch('personal_ai.concept_classifier.classify_question_batch',return_value=(classifications,'測試分類')) as classify:
            batch=process_import_file(self.app,MultiDict({'subject_id':'1','import_strategy':'concept'}),upload)
        self.assertEqual(len(classify.call_args.args[0]),43)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM import_items WHERE import_id=?',(batch,)).fetchone()[0],43)
        self.assertEqual(checkpoints.snapshot(self.app,'old',1)['completed'],43)

    def test_download_and_preview_owner_only(self):
        checkpoints.put('questions',[dict(content='完成題',answer_key='B',q_type='單選',explanation='AI 推定')])
        checkpoints.put('total',2)
        client=self.app.test_client()
        with client.session_transaction() as session: session['user_id']=1
        response=client.get('/ai/jobs/old/download')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['completed'],1)
        self.assertEqual(client.get('/ai/jobs/old/partial').status_code,200)
        self.assertEqual(client.get('/ai/jobs/old/download?format=csv').status_code,200)
        self.assertEqual(client.get('/ai/jobs/old').status_code,200)
        db().execute("INSERT INTO users(id,username,email,password_hash,is_email_verified) VALUES(2,'other','other@example.com','unused',1)")
        db().commit()
        with client.session_transaction() as session: session['user_id']=2
        self.assertEqual(client.get('/ai/jobs/old/download').status_code,404)
        self.assertEqual(client.get('/ai/jobs/old/partial').status_code,404)


if __name__=='__main__': unittest.main()
