import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_chat_rag
from storage import db


class ImportSubjectsTests(unittest.TestCase):
    setUp=test_chat_rag.ChatRagTests.setUp
    tearDown=test_chat_rag.ChatRagTests.tearDown

    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session['user_id']=1
            session['csrf_token']='test-csrf'
        return client

    def create(self,client,name,**extra):
        return client.post('/imports/subjects',data=dict(csrf_token='test-csrf',subject_name=name,**extra))

    def test_subject_creation_is_shared_with_management_and_import_selector(self):
        client=self.client()
        response=self.create(client,'  國中英文  ',created_by='2')
        self.assertEqual(response.status_code,201)
        subject=response.get_json()['subject']
        row=db().execute('SELECT * FROM subjects WHERE id=?',(subject['id'],)).fetchone()
        self.assertEqual(row['created_by'],1)
        self.assertEqual(row['subject_name'],'國中英文')
        self.assertIn('國中英文',client.get('/imports',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True))
        self.assertIn('國中英文',client.get('/records/subjects',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True))

    def test_duplicate_reuses_only_current_users_subject(self):
        client=self.client()
        first=self.create(client,'English').get_json()['subject']['id']
        second=self.create(client,' english ')
        self.assertEqual(second.status_code,200)
        self.assertFalse(second.get_json()['created'])
        self.assertEqual(second.get_json()['subject']['id'],first)
        self.assertEqual(self.create(client,'數學').get_json()['subject']['id'],1)
        self.assertEqual(db().execute('SELECT count(*) FROM subjects WHERE created_by=1').fetchone()[0],2)

    def test_invalid_names_do_not_create_records(self):
        client=self.client()
        for name in ('','   ','科'*81):
            response=self.create(client,name)
            self.assertEqual(response.status_code,400)
            self.assertFalse(response.get_json()['ok'])
        self.assertEqual(db().execute('SELECT count(*) FROM subjects').fetchone()[0],2)

    def test_auth_csrf_and_read_only_guards(self):
        anonymous=self.app.test_client()
        with anonymous.session_transaction() as session:
            session['csrf_token']='test-csrf'
        self.assertEqual(self.create(anonymous,'科目').status_code,302)
        client=self.client()
        self.assertEqual(client.post('/imports/subjects',data={'subject_name':'科目'}).status_code,400)
        self.app.config['DB_READ_ONLY']=True
        self.assertEqual(self.create(client,'科目').status_code,503)
        self.assertEqual(db().execute('SELECT count(*) FROM subjects').fetchone()[0],2)

    def test_new_subject_can_be_used_without_creating_questions_early(self):
        client=self.client()
        sid=self.create(client,'歷史').get_json()['subject']['id']
        with patch('personal_ai.jobs.submit',return_value='inline-test') as submit:
            response=client.post('/imports',data=dict(csrf_token='test-csrf',subject_id=str(sid),
                source_mode='text',text_format='txt',question_text='1. 是非 測試\n答案：是',
                default_chapter='第一章',parse_mode='rules',import_strategy='question_bank'))
        self.assertEqual(response.status_code,302)
        self.assertIn('inline-test',response.headers['Location'])
        payload=submit.call_args.args[3]
        self.assertEqual(dict(payload['form'])['subject_id'],str(sid))
        self.assertEqual(dict(payload['form'])['default_chapter'],'第一章')
        self.assertIn('答案：是',Path(payload['path']).read_text(encoding='utf-8'))
        self.assertEqual(db().execute('SELECT count(*) FROM questions').fetchone()[0],0)
        self.assertEqual(db().execute('SELECT count(*) FROM chapters').fetchone()[0],0)

    def test_inline_controls_dont_add_a_nested_form_or_required_name(self):
        html=self.client().get('/imports',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True)
        self.assertIn('建立並選取科目',html)
        self.assertIn('新章節名稱',html)
        self.assertIn('id="import-subject"',html)
        self.assertIn('data-url="/imports/subjects"',html)
        self.assertNotRegex(html,r'id="import-new-subject"[^>]*required')
        self.assertEqual(html.count('<form '),1)
