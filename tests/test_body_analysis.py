"""訓練分析：純函式測試（手寫資料）＋ API 測試。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from body import analysis


def row(day, workout_id, ex_id, name, muscle, weight, reps):
    return dict(workout_date=day, workout_id=workout_id, exercise_id=ex_id, exercise_name=name,
                muscle_group=muscle, set_no=1, weight_kg=weight, reps=reps)


class PureFunctionTests(unittest.TestCase):
    def test_period_range(self):
        self.assertEqual(analysis.period_range('week', date(2026, 10, 2)),
                         (date(2026, 9, 28), date(2026, 10, 4), date(2026, 9, 21), date(2026, 9, 27)))
        self.assertEqual(analysis.period_range('month', date(2026, 3, 15)),
                         (date(2026, 3, 1), date(2026, 3, 31), date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(analysis.period_range('month', date(2026, 12, 31))[1], date(2026, 12, 31))

    def test_estimated_1rm(self):
        self.assertEqual(analysis.estimated_1rm(100, 1), 100)
        self.assertEqual(analysis.estimated_1rm(60, 10), 80.0)
        self.assertEqual(analysis.estimated_1rm(0, 10), 0)          # 徒手
        self.assertEqual(analysis.estimated_1rm(40, 20), 0)         # 次數太多不估

    def test_volume_balance_and_progress(self):
        sets = [row('2026-09-29', 1, 1, '槓鈴臥推', '胸', 62.5, 8)] * 6 + \
               [row('2026-09-29', 1, 2, '纜繩下壓', '手臂', 25, 12)] * 3 + \
               [row('2026-10-01', 2, 3, '引體向上', '背', 0, 10)] * 3
        prev = [row('2026-09-22', 9, 1, '槓鈴臥推', '胸', 60, 8)] * 3 + [row('2026-09-23', 8, 3, '引體向上', '背', 0, 8)]
        by_muscle = analysis.volume_by_muscle(sets)
        self.assertEqual(by_muscle['胸'], dict(sets=6, volume=3000.0, exercises=1))
        self.assertEqual(by_muscle['腿']['sets'], 0)
        self.assertEqual(analysis.balance(sets), dict(push=9, pull=3, upper=12, lower=0, push_pull=3.0, upper_lower=None))
        progress = {p['name']: p for p in analysis.progress_by_exercise(sets, prev)}
        self.assertEqual((progress['槓鈴臥推']['value'], progress['槓鈴臥推']['prev_value'], progress['槓鈴臥推']['change_pct']),
                         (79.2, 76.0, 4.2))
        self.assertEqual((progress['引體向上']['metric'], progress['引體向上']['value'], progress['引體向上']['change_pct']),
                         ('max_reps', 10, 25.0))

    def test_findings_use_only_report_numbers(self):
        today = date(2026, 10, 12)
        start, end, ps, pe = analysis.period_range('week', date(2026, 10, 2))
        sets = [row('2026-09-29', 1, 1, '槓鈴臥推', '胸', 62.5, 8)] * 6 + [row('2026-10-01', 2, 3, '引體向上', '背', 0, 10)] * 2
        prev = [row('2026-09-22', 9, 1, '槓鈴臥推', '胸', 60, 8)] * 3
        workouts = [dict(id=1, workout_date='2026-09-29', duration_min=50, ended_at='x'),
                    dict(id=2, workout_date='2026-10-01', duration_min=40, ended_at='x')]
        report = analysis.build_report('week', start, end, today, sets, prev, workouts,
                                       [dict(id=9, workout_date='2026-09-22', duration_min=45, ended_at='x')],
                                       [dict(record_date='2026-09-28', weight_kg=69.0), dict(record_date='2026-10-04', weight_kg=68.4)],
                                       {'胸': '2026-09-29', '背': '2026-10-01'})
        self.assertEqual(report['summary'], dict(sessions=2, days=2, total_minutes=90, avg_minutes=45, sets=8, volume=3000.0))
        self.assertEqual(report['change']['sessions'], 100.0)
        self.assertEqual(report['weight']['change'], -0.6)
        self.assertEqual(report['days_since']['胸'], 5)               # 以期末 10/4 為準
        texts = ' '.join(f['text'] for f in report['findings'])
        self.assertIn('訓練次數 2 次，比上一期多 1 次', texts)
        self.assertIn('槓鈴臥推 估計 1RM從 76 提升到 79.2（+4.2%）', texts)
        self.assertIn('推的組數（6）是拉的（2）3 倍', texts)
        self.assertIn('還沒有腿、肩的訓練紀錄', texts)

    def test_empty_period(self):
        start, end, *_ = analysis.period_range('week', date(2026, 10, 2))
        report = analysis.build_report('week', start, end, date(2026, 10, 2), [], [], [], [], [], {})
        self.assertEqual(report['findings'], [dict(level='info', text='這段期間還沒有訓練紀錄。')])
        self.assertIsNone(report['weight'])


class ReportApiTests(unittest.TestCase):
    def setUp(self):
        from werkzeug.security import generate_password_hash
        from app import create_app
        self.directory = tempfile.TemporaryDirectory()
        path = str(Path(self.directory.name) / 'test.db')
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'DB_TYPE': 'sqlite', 'DATABASE': path,
                               'SMTP_HOST': '', 'SMTP_PORT': '', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '', 'SMTP_FROM_EMAIL': ''})
        today = date.today()
        with closing(sqlite3.connect(path)) as c:
            c.execute("INSERT INTO users(username,email,password_hash,is_email_verified,password_changed_at) "
                      "VALUES ('tester01','t@example.com',?,1,CURRENT_TIMESTAMP)", (generate_password_hash('Testing!123'),))
            c.execute("INSERT INTO users(username,email,password_hash,is_email_verified,password_changed_at) "
                      "VALUES ('other','o@example.com','x',1,CURRENT_TIMESTAMP)")
            c.execute("INSERT INTO exercises(exercise_name,muscle_group,equipment,created_by) VALUES ('槓鈴臥推','胸','槓鈴',1),('別人的','背','x',2)")
            c.execute("INSERT INTO workouts(user_id,workout_date,started_at,ended_at,duration_min) VALUES (1,?,?,?,50)",
                      (today.isoformat(), today.isoformat() + 'T10:00', today.isoformat() + 'T10:50'))
            c.execute("INSERT INTO workouts(user_id,workout_date,started_at,ended_at,duration_min) VALUES (2,?,?,?,30)",
                      (today.isoformat(), today.isoformat() + 'T10:00', today.isoformat() + 'T10:30'))
            c.executemany("INSERT INTO workout_sets(workout_id,exercise_id,set_no,weight_kg,reps) VALUES (?,?,?,?,?)",
                          [(1, 1, 1, 60, 10), (1, 1, 2, 60, 8), (2, 2, 1, 100, 5)])
            c.commit()
        self.client = self.app.test_client()
        self.client.get('/login')
        with self.client.session_transaction() as s:
            token = s['csrf_token']
        self.client.post('/login', data={'csrf_token': token, 'username': 'tester01', 'password': 'Testing!123'})

    def tearDown(self):
        self.directory.cleanup()

    def test_report_only_counts_own_data(self):
        data = self.client.get('/body/api/report?period=week').get_json()
        self.assertTrue(data['ok'])
        report = data['report']
        self.assertEqual((report['summary']['sets'], report['summary']['volume']), (2, 1080.0))
        self.assertEqual(report['by_muscle']['背']['sets'], 0)               # 別人的資料不會算進來
        self.assertEqual(report['progress'][0]['name'], '槓鈴臥推')
        self.assertEqual(self.client.get('/body/api/report?period=month').get_json()['report']['summary']['sets'], 2)

    def test_bad_period(self):
        self.assertEqual(self.client.get('/body/api/report?period=year').status_code, 400)


if __name__ == '__main__':
    unittest.main()
