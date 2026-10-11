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
from personal_ai.question_importer import extract_by_rules


class CheckpointTests(unittest.TestCase):
    def test_optional_image_ocr_failure_does_not_erase_native_drafts(self):
        from personal_ai.question_importer import extract_questions
        native=[{'text':'1. First?\nA. one\nB. two'}]
        with patch('personal_ai.question_importer.parse_file',side_effect=[native,RuntimeError('CPU image OCR failed')]):
            with self.assertRaisesRegex(RuntimeError,'CPU image OCR failed'):
                extract_questions(Path(self.directory.name)/'source.pdf','測試',{},'auto')
        progress=checkpoints.snapshot(self.app,'old',1)
        self.assertEqual(progress['parsed_count'],1)
        self.assertEqual(progress['parsed_questions'][0]['content'],'First?')

    def test_successful_local_repair_is_reused_on_resume(self):
        from personal_ai.import_routing import repair_local_questions
        sections=[{'text':'1. Good?\nA. one\nB. two\n答案：A\n2. Broken?\n3. Good?\nA. one\nB. two\n答案：B'}]
        local=extract_by_rules(sections,'測試',True)
        fixed=dict(local[1],q_type='單選',option_A='one',option_B='two',answer_key='')
        with patch('personal_ai.question_importer.extract_with_llm',return_value=[fixed]) as api:
            first=repair_local_questions(sections,local,'測試',{})
            second=repair_local_questions(sections,local,'測試',{})
        self.assertEqual(first,second)
        self.assertEqual(api.call_count,1)

    def test_local_drafts_remain_visible_if_ai_layout_is_rate_limited(self):
        from personal_ai.question_importer import extract_questions
        path=Path(self.directory.name)/'source.txt'
        path.write_text('1. First?\nA. one\nB. two\n2. Missing choices?',encoding='utf-8')
        with patch('personal_ai.question_importer.extract_with_llm',side_effect=LLMError('TPM',status_code=429)):
            with self.assertRaises(LLMError): extract_questions(path,'測試',{},'llm')
        progress=checkpoints.snapshot(self.app,'old',1)
        self.assertEqual(progress['parsed_count'],2)
        self.assertEqual(progress['total'],2)
        self.assertEqual(progress['completed'],0)
        self.assertEqual(progress['parsed_questions'][0]['content'],'First?')

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
        with patch('personal_ai.question_answering.get_parser_llm',return_value=solver),patch('personal_ai.question_importer.extract_with_llm',side_effect=lambda sections,chapter,config,**kw:extract_by_rules(sections,chapter,allow_missing_answers=True)):
            jobs.run(self.app,'old',1)
        self.assertEqual(jobs.read(self.app,'old',1)['status'],'failed')
        self.assertTrue(source.is_file())
        self.assertEqual(checkpoints.snapshot(self.app,'old',1)['completed'],4)
        with patch.object(jobs._executor,'submit'):
            resumed=jobs.submit(self.app,1,'import',dict(payload,resume_from='old'))
        solver.calls=0
        with patch('personal_ai.question_answering.get_parser_llm',return_value=solver),patch('personal_ai.question_importer.extract_with_llm',side_effect=lambda sections,chapter,config,**kw:extract_by_rules(sections,chapter,allow_missing_answers=True)):
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

    def test_insufficient_question_does_not_block_later_answers_and_resume(self):
        items=[dict(_question_no=i,content='題目',q_type='單選',answer_key='',option_A='甲',option_B='乙') for i in range(1,10)]
        class Solver:
            enabled=True
            provider='test'
            model='test'
            fail=True
            seen=[]
            def complete_json(self,s,u):
                payload=json.loads(u.split('\n回傳 ')[0])
                self.seen.extend(x['number'] for x in payload)
                return {'answers':[dict(number=x['number'],status='insufficient' if self.fail and x['number']==2 else 'answered',answer='' if self.fail and x['number']==2 else 'B',explanation='理由',context='') for x in payload]}
        solver=Solver()
        with patch('personal_ai.question_answering.get_parser_llm',return_value=solver):
            usable=infer_missing_answers(items,[],Path('book.txt'),{})
            self.assertEqual(len(usable),8)
            progress=checkpoints.snapshot(self.app,'old',1)
            self.assertEqual(progress['completed'],8)
            self.assertEqual(solver.seen,list(range(1,10)))
            self.assertEqual(progress['answer_failures'][0]['number'],2)
            solver.fail=False
            solver.seen=[]
            result=infer_missing_answers(items,[],Path('book.txt'),{})
        self.assertEqual(solver.seen,[2])
        self.assertEqual(len(result),9)
        self.assertEqual(checkpoints.snapshot(self.app,'old',1)['answer_failures'],[])

    def test_partial_answers_continue_to_classification_and_completed_preview(self):
        db().execute("INSERT INTO subjects(id,subject_name,created_by) VALUES(1,'測試',1)")
        db().commit()
        folder=Path(self.app.instance_path)/'job_uploads'
        folder.mkdir()
        source=folder/'partial.txt'
        source.write_text('測試文件',encoding='utf-8')
        items=[dict(_question_no=i,chapter_name='測試',content='題目',q_type='單選',answer_key='',option_A='甲',option_B='乙',difficulty=2) for i in range(1,6)]
        class Solver:
            enabled=True
            provider='test'
            model='test'
            def complete_json(self,s,u):
                payload=json.loads(u.split('\n回傳 ')[0])
                return {'answers':[dict(number=x['number'],status='insufficient' if x['number']==2 else 'answered',answer='' if x['number']==2 else 'B',explanation='理由',context='') for x in payload]}
        def extract(*args):
            return infer_missing_answers(items,[],Path('book.txt'),{}),'測試解析'
        def classify(rows,*args):
            self.assertEqual([x['_question_no'] for x in rows],[1,3,4,5])
            return [dict(concept_id=None,concept_name='概念',concept_description='',skill='理解',cognitive_level='understand',difficulty=2,confidence=.8,reason='test') for _ in rows],'測試分類'
        jobs.update(self.app,'old',payload=json.dumps(dict(path=str(source),filename='partial.txt',form=[('subject_id','1'),('import_strategy','concept')])))
        with patch('personal_ai.question_answering.get_parser_llm',return_value=Solver()),patch('personal_ai.question_importer.extract_questions',side_effect=extract),patch('personal_ai.concept_classifier.classify_question_batch',side_effect=classify) as classifier:
            jobs.run(self.app,'old',1)
        row=jobs.read(self.app,'old',1)
        self.assertEqual(row['status'],'completed',row['error'])
        classifier.assert_called_once()
        self.assertEqual(db().execute('SELECT COUNT(*) FROM import_items').fetchone()[0],4)
        progress=checkpoints.snapshot(self.app,'old',1)
        self.assertEqual((progress['completed'],progress['total'],progress['remaining']),(4,5,1))
        self.assertEqual(progress['answer_failures'][0]['number'],2)
        client=self.app.test_client()
        with client.session_transaction() as session: session['user_id']=1
        batch=db().execute('SELECT id FROM exam_imports').fetchone()[0]
        self.assertIn('待補資料題號：2',client.get(f'/imports/{batch}',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True))

    def test_insufficient_groq_response_is_not_reused_forever(self):
        model=GroqLLM('test-model','test-key')
        insufficient={'choices':[{'message':{'content':'{"answers":[{"number":2,"status":"insufficient","answer":""}]}'}}]}
        answered={'choices':[{'message':{'content':'{"answers":[{"number":2,"status":"answered","answer":"B"}]}'}}]}
        with patch.object(OpenAICompatibleLLM,'_request',side_effect=[insufficient,answered]) as remote:
            model.complete_json('JSON','retry')
            self.assertEqual(model.complete_json('JSON','retry')['answers'][0]['answer'],'B')
        self.assertEqual(remote.call_count,2)

    def test_partial_preview_retains_source_and_resume_reuses_answers_and_classifications(self):
        folder=Path(self.app.instance_path)/'job_uploads'
        folder.mkdir()
        source=folder/'partial-resume.txt'
        source.write_text('fixture',encoding='utf-8')
        db().execute("INSERT INTO subjects(id,subject_name,created_by) VALUES(1,'測試',1)")
        db().commit()
        items=[dict(_question_no=i,chapter_name='測試',content='題目'+str(i),q_type='單選',
                    answer_key='',option_A='甲',option_B='乙',difficulty=2) for i in range(1,6)]
        class Solver:
            enabled=True
            provider='test'
            model='text'
            incomplete=True
            seen=[]
            def complete_json(self,system,user):
                rows=json.loads(user.split('\n回傳 ')[0])
                self.seen.extend(row['number'] for row in rows)
                return {'answers':[dict(number=row['number'],status='insufficient' if self.incomplete and row['number']==2 else 'answered',
                    answer='' if self.incomplete and row['number']==2 else 'A',explanation='來源支持',context='') for row in rows]}
        solver=Solver()
        def extract(*args):
            return infer_missing_answers(items,[],Path('fixture.txt'),{}),'fixture'
        classified=[]
        def classify(rows,*args):
            classified.append([row['_question_no'] for row in rows])
            return [dict(concept_id=None,concept_name='概念',concept_description='',skill='理解',
                cognitive_level='understand',difficulty=2,confidence=.8,reason='fixture') for row in rows],'fixture'
        payload=dict(path=str(source),filename='partial-resume.txt',form=[('subject_id','1'),('import_strategy','concept')])
        jobs.update(self.app,'old',payload=json.dumps(payload))
        with patch('personal_ai.question_answering.get_parser_llm',return_value=solver),patch('personal_ai.question_importer.extract_questions',side_effect=extract),patch('personal_ai.concept_classifier.classify_question_batch',side_effect=classify):
            jobs.run(self.app,'old',1)
            self.assertEqual(jobs.read(self.app,'old',1)['status'],'completed')
            self.assertTrue(source.is_file())
            with patch.object(jobs._executor,'submit'):
                resumed=jobs.submit(self.app,1,'import',dict(payload,resume_from='old'))
            solver.incomplete=False
            solver.seen=[]
            jobs.run(self.app,resumed,1)
        self.assertEqual(jobs.read(self.app,resumed,1)['status'],'completed')
        self.assertEqual(solver.seen,[2])
        self.assertEqual(classified,[[1,3,4,5],[2]])
        self.assertEqual(checkpoints.snapshot(self.app,resumed,1)['remaining'],0)
        self.assertFalse(source.exists())

    def test_unresolved_reading_item_is_deferred_without_model_guess(self):
        good=dict(_question_no=1,content='完整題目',q_type='單選',answer_key='A',option_A='甲',option_B='乙')
        reading=dict(_question_no=2,content='閱讀子題',q_type='單選',answer_key='',option_A='甲',option_B='乙',_layout_needs_review='題組關聯尚未確認')
        class Model:
            enabled=True
            provider='test'
            model='test'
            def complete_json(self,s,u): raise AssertionError('不得猜未確認的閱讀題')
        with patch('personal_ai.question_answering.get_parser_llm',return_value=Model()):
            result=infer_missing_answers([good,reading],[],Path('book.txt'),{})
        self.assertEqual(result,[good])
        self.assertEqual(checkpoints.snapshot(self.app,'old',1)['answer_failures'][0]['number'],2)

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
