import io
import json
import smtplib
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from smartlife import create_app
from records import CATALOG


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name)/'test.db')
        self.app = create_app({'TESTING':True,'SECRET_KEY':'test-only-secret','DATABASE':self.path,
                               'SMTP_HOST':'','SMTP_PORT':'','SMTP_USERNAME':'','SMTP_PASSWORD':'','SMTP_FROM_EMAIL':''})
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def sql(self,query,params=()):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory=sqlite3.Row
            rows = [dict(row) for row in connection.execute(query,params).fetchall()]
            connection.commit()
            return rows

    def post(self,url,data=None,client=None):
        client=client or self.client
        client.get('/login')
        with client.session_transaction() as session:
            token=session['csrf_token']
        return client.post(url,data={'csrf_token':token,**(data or {})})

    def register(self,email='one@example.com',username='user!1',client=None):
        with patch('auth.send_code') as send:
            response=self.post('/send-verification',{'email':email},client)
            self.assertEqual(response.status_code,200,response.get_data(as_text=True))
            code=send.call_args.args[1]
        response=self.post('/register',{'email':email,'username':username,'password':'pass!123','code':code},client)
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        return code

    def login(self,username='user!1',client=None):
        response=self.post('/login',{'username':username,'password':'pass!123'},client)
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))

    def create_question(self):
        self.post('/records/subjects',{'subject_name':'資料庫'})
        sid=self.sql('SELECT id FROM subjects')[0]['id']
        self.post('/records/chapters',{'subject_id':sid,'chapter_name':'索引','order_no':1})
        cid=self.sql('SELECT id FROM chapters')[0]['id']
        response=self.post('/records/questions',{'chapter_id':cid,'q_type':'單選','content':'範例題目','answer_key':'A','explanation':'only-after-submit','difficulty':2,'option_A':'正確','option_B':'錯誤'})
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        return sid,cid

    def test_auth_persistence_and_csrf(self):
        self.assertEqual(self.client.get('/dashboard').status_code,302)
        self.assertEqual(self.client.post('/register').status_code,400)
        code=self.register()
        user=self.sql('SELECT * FROM users')[0]
        verification=self.sql('SELECT * FROM registration_codes')[0]
        self.assertNotEqual(user['password_hash'],'pass!123')
        self.assertNotEqual(verification['code_hash'],code)
        self.assertEqual(user['is_email_verified'],1)
        self.assertEqual(verification['state'],'used')
        self.assertEqual(self.post('/register',{'email':'one@example.com','username':'user!2','password':'pass!123','code':code}).status_code,400)
        self.assertEqual(self.post('/login',{'username':'user!1','password':'wrongpass'}).status_code,400)
        self.login()
        for table in CATALOG:
            self.assertEqual(self.client.get('/records/'+table).status_code,200,table)
        for path in ['/dashboard','/profile','/quiz','/results','/analysis','/materials','/imports','/workspace/sources']:
            self.assertIn(self.client.get(path).status_code,(200,302),path)
        other_app=create_app({'TESTING':True,'SECRET_KEY':'test-only-secret','DATABASE':self.path})
        other=other_app.test_client()
        self.login(client=other)
        self.assertEqual(other.get('/dashboard').status_code,200)
        self.assertEqual(self.client.get('/logout').status_code,405)
        self.post('/logout')
        self.assertEqual(self.client.get('/dashboard').status_code,302)

    def test_mail_failure_expiry_attempts_and_resend(self):
        response=self.post('/send-verification',{'email':'missing@example.com'})
        self.assertEqual(response.status_code,503)
        self.assertIn('尚未設定',response.json['message'])
        with patch('auth.send_code',side_effect=smtplib.SMTPException('private secret')):
            response=self.post('/send-verification',{'email':'failed@example.com'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private secret',response.json['message'])
        with patch('auth.send_code') as send:
            response=self.post('/send-verification',{'email':'new@example.com'})
            code=send.call_args.args[1]
        record=self.sql("SELECT * FROM registration_codes WHERE email='new@example.com'")[0]
        self.assertAlmostEqual(record['expires_at']-time.time(),1800,delta=5)
        self.assertEqual(self.post('/send-verification',{'email':'new@example.com'}).status_code,429)
        values={'username':'abcdef','password':'12345678','email':'new@example.com','code':'bad'}
        for _ in range(5):
            self.assertEqual(self.post('/register',values).status_code,400)
        self.assertEqual(self.post('/register',{**values,'code':code}).status_code,400)
        self.sql("UPDATE registration_codes SET sent_at=sent_at-61 WHERE email='new@example.com'")
        with patch('auth.send_code') as send:
            self.assertEqual(self.post('/send-verification',{'email':'new@example.com'}).status_code,200)
            code=send.call_args.args[1]
        self.sql("UPDATE registration_codes SET expires_at=0 WHERE email='new@example.com'")
        self.assertEqual(self.post('/register',{**values,'code':code}).status_code,400)
        self.assertEqual(self.sql('SELECT count(*) n FROM users')[0]['n'],0)

    def test_credential_rules_and_duplicate(self):
        with patch('auth.send_code') as send:
            self.post('/send-verification',{'email':'one@example.com'})
            code=send.call_args.args[1]
        data={'username':'short','password':'pass!123','email':'one@example.com','code':code}
        self.assertEqual(self.post('/register',data).status_code,400)
        self.assertEqual(self.post('/register',{**data,'username':'user01','password':'short'}).status_code,400)
        self.assertEqual(self.post('/register',{**data,'username':'中文帳號12'}).status_code,400)
        self.assertEqual(self.post('/register',{**data,'username':'user01'}).status_code,302)
        self.assertEqual(self.post('/send-verification',{'email':'ONE@example.com'}).status_code,409)

    def test_quiz_ownership_scoring_and_snapshots(self):
        self.register(); self.login()
        sid,cid=self.create_question()
        response=self.post('/quiz',{'subject_id':sid,'count':10,'mode':'模擬考'})
        location=response.location
        self.assertNotIn('only-after-submit',self.client.get(location).get_data(as_text=True))
        aid=self.sql('SELECT id FROM quiz_answers')[0]['id']
        self.post(location,{'answer_'+str(aid):'B'})
        result=self.client.get(location).get_data(as_text=True)
        self.assertIn('only-after-submit',result)
        self.assertEqual(self.sql('SELECT wrong_count FROM wrong_answers')[0]['wrong_count'],1)
        self.post(location,{'answer_'+str(aid):'B'})
        self.assertEqual(self.sql('SELECT wrong_count FROM wrong_answers')[0]['wrong_count'],1)
        self.assertEqual(self.sql('SELECT answered_count FROM daily_summary')[0]['answered_count'],1)
        other=self.app.test_client()
        self.register('two@example.com','user!2',other);self.login('user!2',other)
        self.assertEqual(other.get(location).status_code,404)
        self.assertEqual(other.get('/records/questions?edit=1').status_code,404)
        self.assertEqual(self.post('/records/chapters',{'subject_id':sid,'chapter_name':'attack','order_no':0},other).status_code,404)
        self.assertEqual(self.post('/records/subjects/1/delete',client=other).status_code,404)
        self.assertNotIn('範例題目',other.get('/records/questions').get_data(as_text=True))
        r=self.post('/quiz',{'subject_id':sid,'count':1,'mode':'錯題複習'})
        aid=self.sql('SELECT id FROM quiz_answers ORDER BY id DESC')[0]['id']
        self.post(r.location,{'answer_'+str(aid):'A'})
        self.assertEqual(self.sql('SELECT status FROM wrong_answers')[0]['status'],'已克服')

    def test_import_confirmation_and_xlsx(self):
        self.register();self.login()
        self.post('/records/subjects',{'subject_name':'匯入科目'})
        content='chapter_name,q_type,content,answer_key,explanation,difficulty,option_A,option_B\n第一章,單選,這是題目,A,正確解析,1,正確,錯誤\n'
        response=self.post('/imports',{'subject_id':1,'file':(io.BytesIO(content.encode()),'questions.csv')})
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        self.assertEqual(len(self.sql('SELECT * FROM questions')),0)
        self.assertIn('正確解析',self.client.get(response.location).get_data(as_text=True))
        self.post(response.location)
        self.post(response.location)
        self.assertEqual(len(self.sql('SELECT * FROM questions')),1)
        self.assertEqual(self.sql('SELECT is_confirmed FROM import_items')[0]['is_confirmed'],1)
        from openpyxl import Workbook
        book=Workbook(); book.active.append(content.splitlines()[0].split(','));book.active.append(content.splitlines()[1].split(','))
        stream=io.BytesIO();book.save(stream);stream.seek(0)
        response=self.post('/imports',{'subject_id':1,'file':(stream,'questions.xlsx')})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.post('/imports',{'subject_id':1,'file':(io.BytesIO(b'bad'),'bad.xlsx')}).status_code,200)

    def test_profile_workouts_plan_and_record_persistence(self):
        self.register();self.login()
        response=self.post('/profile',{'gender':'other','birth_date':'2000-01-01','height_cm':170,'activity_level':'中','goal_type':'維持','workout_days_per_week':3,'minutes_per_session':30,'initial_weight':65})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.sql('SELECT weight_kg FROM body_metrics')[0]['weight_kg'],65)
        response=self.post('/records/exercises',{'exercise_name':'深蹲','muscle_group':'腿','equipment':'槓鈴','is_cardio':'0'})
        self.assertEqual(response.status_code,302)
        response=self.post('/records/workouts',{'workout_date':'2026-09-16','started_at':'2026-09-16T10:00','ended_at':'2026-09-16T10:30','note':'test'})
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        response=self.post('/records/workout_sets',{'workout_id':1,'exercise_id':1,'set_no':1,'weight_kg':20,'reps':10})
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        self.assertEqual(self.sql('SELECT total_volume FROM workouts')[0]['total_volume'],200)
        self.assertEqual(self.sql('SELECT workout_volume FROM daily_summary')[0]['workout_volume'],200)
        self.post('/records/study_plans',{'plan_date':'2020-01-01','plan_type':'study','title':'old plan','target_value':30,'target_unit':'分鐘','status':'planned'})
        self.assertEqual(self.sql('SELECT status FROM study_plans')[0]['status'],'missed')
        response=self.post('/records/workout_sets',{'id':1,'workout_id':1,'exercise_id':1,'set_no':1,'weight_kg':25,'reps':10})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.sql('SELECT total_volume FROM workouts')[0]['total_volume'],250)
        self.post('/records/workout_sets/1/delete')
        self.assertEqual(self.sql('SELECT total_volume FROM workouts')[0]['total_volume'],0)

    def test_smtp_tls_transport(self):
        from auth import send_code
        self.app.config.update(SMTP_HOST='smtp.example.com',SMTP_PORT='587',SMTP_USERNAME='sender@example.com',SMTP_PASSWORD='test-key',SMTP_FROM_EMAIL='sender@example.com',SMTP_SECURITY='starttls')
        with self.app.app_context(), patch('auth.smtplib.SMTP') as transport:
            client=transport.return_value
            client.__enter__.return_value=client
            client.send_message.return_value={}
            send_code('recipient@example.com','012345')
            client.starttls.assert_called_once()
            client.login.assert_called_once_with('sender@example.com','test-key')
            message=client.send_message.call_args.args[0]
            self.assertEqual(message['To'],'recipient@example.com')
            self.assertIn('012345',message.get_content())
            self.assertIn('30',message.get_content())
            client.send_message.return_value={'recipient@example.com':(550,'refused')}
            with self.assertRaises(smtplib.SMTPException):
                send_code('recipient@example.com','012345')

    def test_resend_invalidates_old_code_and_login_throttle(self):
        with patch('auth.send_code'), patch('auth.secrets.randbelow',return_value=123456):
            self.post('/send-verification',{'email':'one@example.com'})
        self.sql('UPDATE registration_codes SET sent_at=sent_at-61')
        with patch('auth.send_code'), patch('auth.secrets.randbelow',return_value=654321):
            self.post('/send-verification',{'email':'one@example.com'})
        values={'username':'user!1','password':'pass!123','email':'one@example.com','code':'123456'}
        self.assertEqual(self.post('/register',values).status_code,400)
        self.assertEqual(self.post('/register',{**values,'code':'654321'}).status_code,302)
        for _ in range(10):
            self.post('/login',{'username':'user!1','password':'bad-password'})
        response=self.post('/login',{'username':'user!1','password':'pass!123'})
        self.assertIn('登入嘗試過多',response.get_data(as_text=True))

    def test_all_question_types(self):
        self.register();self.login()
        sid,cid=self.create_question()
        for kind,answer in [('多選','A,C'),('是非','是'),('填空','SQLite')]:
            response=self.post('/records/questions',{'chapter_id':cid,'q_type':kind,'content':kind+'題目','answer_key':answer,'difficulty':1,'option_A':'A選項','option_C':'C選項'})
            self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        exam=self.post('/quiz',{'subject_id':sid,'count':4,'mode':'練習'})
        answers={}
        for row in self.sql('SELECT * FROM quiz_answers'):
            q=json.loads(row['question_snapshot'])
            answers['answer_'+str(row['id'])]=q['answer_key'].split(',') if q['q_type']=='多選' else q['answer_key']
        self.post(exam.location,answers)
        self.assertEqual(self.sql('SELECT correct_count FROM quiz_sessions')[0]['correct_count'],4)


if __name__=='__main__':
    unittest.main()
