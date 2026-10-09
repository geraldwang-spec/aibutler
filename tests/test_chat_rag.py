import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app
from storage import db
from personal_ai.rag import retrieve
from personal_ai.chat import generate_reply
from personal_ai.exam_modules import ExamModuleError


class ChatRagTests(unittest.TestCase):
    def test_teaching_scope_is_not_a_math_question_special_case(self):
        from personal_ai.chat import GROUNDED_SCOPE
        self.assertIn('適用所有科目',GROUNDED_SCOPE)
        self.assertIn('先回答那部分',GROUNDED_SCOPE)
        self.assertNotIn('瓶數',GROUNDED_SCOPE)
        self.assertNotIn('字母為何變成數字',GROUNDED_SCOPE)

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'SECRET_KEY':'rag-test',
                             'DATABASE':str(Path(self.directory.name)/'test.db'),
                             'DB_READ_ONLY':False,'EMBEDDING_PROVIDER':'cpu'})
        self.app.instance_path=self.directory.name
        self.context=self.app.test_request_context('/chat')
        self.context.push()
        con=db()
        for i in (1,2):
            con.execute('INSERT INTO users(id,username,email,password_hash,is_email_verified) VALUES(?,?,?,?,1)',(i,f'user{i}',f'user{i}@example.com','unused'))
            con.execute('INSERT INTO subjects(id,subject_name,created_by) VALUES(?,?,?)',(i,'數學',i))
            con.execute("INSERT INTO materials(id,user_id,subject_id,title,parse_status) VALUES(?,?,?,'變數講義','完成')",(i,i,i))
            con.execute("INSERT INTO rag_documents(id,source_type,material_id,title) VALUES(?,'upload',?,'變數講義')",(i,i))
            con.execute('INSERT INTO rag_chunks(id,doc_id,chunk_index,content) VALUES(?,?,0,?)',(i,i,'一個可以任意決定或改變的數，稱為「變數」。x 是自變數，y 是應變數。' if i==1 else '其他使用者的私人教材'))
            con.execute("INSERT INTO rag_chunk_meta(chunk_id,source_locator,section_title) VALUES(?,'page:3','變數與函數')",(i,))
        con.execute("INSERT INTO chat_sessions(id,user_id,title) VALUES(1,1,'新對話')")
        con.commit()

    def tearDown(self):
        self.context.pop()
        self.directory.cleanup()

    def test_colloquial_math_retrieves_definition_and_stays_private(self):
        with patch('personal_ai.exam_modules.rank',side_effect=lambda q,c:[(i,1) for i in range(len(c))]):
            rows=retrieve(1,1,'為什麼英文字母會變成數字')
        self.assertEqual([r['id'] for r in rows],[1])
        self.assertIn('變數',rows[0]['content'])
        with self.assertRaisesRegex(ValueError,'不屬於'):
            retrieve(1,2,'變數')

    def test_cpu_failure_still_returns_scoped_lexical_evidence(self):
        with patch('personal_ai.exam_modules.rank',side_effect=ExamModuleError('not installed')):
            self.assertEqual(retrieve(1,1,'什麼是變數')[0]['id'],1)

    def test_chat_answer_has_real_evidence_and_source(self):
        class Tutor:
            def complete_json(self,system,user):
                payload=json.loads(user)
                assert '變數' in payload['evidence']
                return dict(answer='字母不是變成數字，而是用來表示變數。',supported=True,evidence_chunk_ids=[1],title='認識變數')
        with patch('personal_ai.exam_modules.rank',return_value=[(0,1)]),patch('personal_ai.chat.get_tutor_llm',return_value=Tutor()):
            response=generate_reply(1,1,'數學好難，英文字母怎麼變成數字',1)
        self.assertIn('教材來源：變數講義',response['answer'])
        self.assertIn('片段 1',response['answer'])

    def test_unrelated_question_does_not_call_unscoped_model(self):
        with patch('personal_ai.chat.get_tutor_llm') as model:
            response=generate_reply(1,1,'牛肉麵怎麼做',1)
        model.assert_not_called()
        self.assertIn('1 個教材片段',response['answer'])
        self.assertIn('沒有找到',response['answer'])

    def test_invalid_citation_is_not_shown_as_grounded_answer(self):
        class Tutor:
            def complete_json(self,s,u): return dict(answer='不可靠答案',supported=True,evidence_chunk_ids=[2])
        with patch('personal_ai.exam_modules.rank',return_value=[(0,1)]),patch('personal_ai.chat.get_tutor_llm',return_value=Tutor()):
            response=generate_reply(1,1,'什麼是變數',1)
        self.assertNotIn('不可靠答案',response['answer'])
        self.assertIn('沒有提供可核對的引用',response['answer'])
        self.assertIn('不是 AI 答案',response['answer'])

    def test_string_citations_are_normalized_before_grounding_review(self):
        from unittest.mock import Mock
        model=Mock()
        model.complete_json.return_value=dict(answer='變數是可變動的數。',supported=True,evidence_chunk_ids=['1'])
        with patch('personal_ai.exam_modules.rank',return_value=[(0,1)]),patch('personal_ai.chat.get_tutor_llm',return_value=model):
            response=generate_reply(1,1,'什麼是變數',1)
        self.assertIn('教材來源',response['answer'])
        self.assertEqual(model.complete_json.call_count,2)

    def test_bad_format_is_re_evaluated_once(self):
        from unittest.mock import Mock
        model=Mock()
        model.complete_json.side_effect=[dict(answer='draft',supported=True,evidence_chunk_ids=[]),
                                        dict(answer='變數是可變動的數。',supported=True,evidence_chunk_ids=[1]),
                                        dict(answer='變數是可變動的數。',supported=True,evidence_chunk_ids=[1])]
        with patch('personal_ai.exam_modules.rank',return_value=[(0,1)]),patch('personal_ai.chat.get_tutor_llm',return_value=model):
            response=generate_reply(1,1,'什麼是變數',1)
        self.assertIn('教材來源',response['answer'])
        self.assertEqual(model.complete_json.call_count,3)

    def test_grounding_review_removes_unsupported_draft(self):
        from unittest.mock import Mock
        model=Mock()
        model.complete_json.side_effect=[dict(answer='沒有教材依據的延伸內容',supported=True,evidence_chunk_ids=[1]),
                                        dict(answer='可以改變的數稱為變數。',supported=True,evidence_chunk_ids=[1])]
        with patch('personal_ai.exam_modules.rank',return_value=[(0,1)]),patch('personal_ai.chat.get_tutor_llm',return_value=model):
            response=generate_reply(1,1,'什麼是變數',1)
        self.assertNotIn('延伸內容',response['answer'])
        self.assertIn('稱為變數',response['answer'])
        review=json.loads(model.complete_json.call_args_list[1].args[1])
        self.assertIn('延伸內容',review['draft'])
        self.assertIn('教材片段 1',review['evidence'])

    def test_insufficient_evidence_is_not_reported_as_format_failure(self):
        from unittest.mock import Mock
        model=Mock()
        model.complete_json.return_value=dict(answer='不應展示',supported=False,evidence_chunk_ids=[])
        with patch('personal_ai.exam_modules.rank',return_value=[(0,1)]),patch('personal_ai.chat.get_tutor_llm',return_value=model):
            response=generate_reply(1,1,'什麼是變數',1)
        self.assertIn('片段不足',response['answer'])
        self.assertNotIn('不應展示',response['answer'])
        self.assertNotIn('沒有提供可核對',response['answer'])
        self.assertEqual(model.complete_json.call_count,2)

    def test_all_evidence_labels_survive_long_history(self):
        from personal_ai.chat import _grounded_payload,_citation_ids
        chunks=[dict(id=i,content='教材原文'*1000,material_title='講義',section_title='變數') for i in range(1,4)]
        payload=_grounded_payload('變數是什麼',chunks,[dict(role='assistant',content='舊對話'*5000)]*6)
        self.assertLessEqual(len(payload.encode('utf-8')),9000)
        data=json.loads(payload)
        for i in range(1,4): self.assertIn(f'[教材片段 {i}]',data['evidence'])
        self.assertIsNone(_citation_ids(dict(supported=1,evidence_chunk_ids=[1]),{1}))
        self.assertIsNone(_citation_ids(dict(supported=True,evidence_chunk_ids=[True]),{1}))

    def test_lecture_upload_and_chat_scope_link(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session['user_id']=1
            session['csrf_token']='test-csrf'
        response=client.post('/knowledge',data={'csrf_token':'test-csrf','subject_id':'1',
                                               'file':(io.BytesIO('新增講義：未知數用字母表示。'.encode()),'math.txt')})
        self.assertEqual(response.status_code,302)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM materials WHERE user_id=1').fetchone()[0],2)
        self.assertIn('subject_id=1',client.get('/knowledge',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True))
        chat=client.get('/chat?subject_id=1',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True)
        self.assertRegex(chat,r'value="1"\s+selected')
        self.assertEqual(client.get('/chat?subject_id=2',headers={'Sec-Fetch-Dest':'iframe'}).status_code,404)


if __name__=='__main__': unittest.main()
