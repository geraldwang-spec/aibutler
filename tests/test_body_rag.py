"""教練文章 RAG：切段、向量搜尋、出處檢查、API（用本機的假 embedding／LLM 伺服器，不呼叫真的 API）。"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from body.ai_report import AiReport
from body.rag import TextChunker, VectorIndex

ARTICLE = '''# 背部訓練原則
背部常被忽略。每週安排划船和下拉，可以平衡臥推等推的動作。建議背部每週 10 到 20 組。

# 恢復
睡眠不足會影響進步，每天睡 7 小時以上。蛋白質也要吃夠。

# 腿部
深蹲是腿部的主要動作，每週至少練一次腿。
'''


class ChunkerAndIndexTests(unittest.TestCase):
    def test_sections_and_sizes(self):
        chunks = TextChunker().split(ARTICLE)
        self.assertEqual([c['section'] for c in chunks], ['背部訓練原則', '恢復', '腿部'])
        self.assertEqual([c['index'] for c in chunks], [0, 1, 2])
        self.assertNotIn('睡眠', chunks[0]['content'])                     # 不跨標題

        long_text = '# 長文\n' + ''.join(f'第{i}句講背部划船的動作要點。' for i in range(120))
        chunks = TextChunker().split(long_text)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(c['content']) <= TextChunker.MAX_CHARS + TextChunker.OVERLAP_CHARS + 2 for c in chunks))
        self.assertEqual(chunks[1]['content'][:20], chunks[0]['content'][-TextChunker.OVERLAP_CHARS:][:20])   # 前後重疊
        self.assertEqual(TextChunker().split('  \n\n '), [])

    def test_vector_search(self):
        self.assertEqual(list(VectorIndex.from_blob(VectorIndex.to_blob([1, 2.5]))), [1.0, 2.5])
        rows = [dict(id=1, embedding=VectorIndex.to_blob([1, 0, 0])), dict(id=2, embedding=VectorIndex.to_blob([0.6, 0.8, 0])),
                dict(id=3, embedding=VectorIndex.to_blob([0, 0, 1])), dict(id=4, embedding=VectorIndex.to_blob([1, 0])),
                dict(id=5, embedding=None)]
        self.assertEqual([(r['id'], s) for r, s in VectorIndex.search([1, 0, 0], rows, k=3, min_score=0.5)], [(1, 1.0), (2, 0.6)])
        self.assertEqual(len(VectorIndex.search([1, 0, 0], rows, k=1, min_score=0)), 1)
        self.assertEqual(VectorIndex.search([0, 0, 0], rows), [])                   # 查詢是零向量
        self.assertEqual(VectorIndex.search([0, 1, 0], rows[:1]), [])               # 低於門檻 → 不回傳


class CitationTests(unittest.TestCase):
    def ai(self):
        from body.analysis import TrainingAnalysis
        start, end, *_ = TrainingAnalysis.period_range('week', date(2026, 10, 2))
        sets = [dict(workout_date='2026-09-29', workout_id=1, exercise_id=1, exercise_name='槓鈴臥推', muscle_group='胸',
                     set_no=1, weight_kg=60, reps=8)] * 6
        report = TrainingAnalysis('week', start, end, date(2026, 10, 12), sets, [], [dict(id=1, workout_date='2026-09-29',
                                  duration_min=50, ended_at='x')], [], [], {'胸': '2026-09-29'}).build()
        passages = [dict(n=1, chunk_id=11, title='教練文章', section='背部訓練原則', text='建議背部每週 10 到 20 組。', score=0.8),
                    dict(n=2, chunk_id=12, title='教練文章', section='恢復', text='每天睡 7 小時以上。', score=0.5)]
        return AiReport(report, None, passages)

    def test_citations(self):
        ai = self.ai()
        self.assertIn('reference_passages', ai.prompt_data)
        self.assertNotIn('reference_passages', ai.data)                         # 雜湊值不受文章影響
        result = ai.check({'summary': '本週練了 6 組胸。',
                           'weaknesses': ['背部還沒練，建議每週 10 到 20 組 [1]。', '多睡一點 [9]。'],
                           'suggestions': ['下週加入 3 組划船 [1]。'], 'strengths': []})
        self.assertEqual(result['weaknesses'], ['背部還沒練，建議每週 10 到 20 組 [1]。'])   # 20 來自文章；[9] 不存在 → 拿掉
        self.assertEqual(result['suggestions'], ['下週加入 3 組划船 [1]。'])
        self.assertEqual([s['n'] for s in result['sources']], [1])                # 只列出真的被引用的段落
        self.assertEqual(result['removed'], 1)
        plain = AiReport(ai.report).check({'summary': '本週練了 6 組 [1]。'})
        self.assertEqual(plain['summary'], '')                                    # 沒有文章卻引用 → 拿掉


class RagApiTests(unittest.TestCase):
    def setUp(self):
        from werkzeug.security import generate_password_hash
        from app import create_app
        from body import body_route
        from tests.test_body_parser import FakeLlmServer
        self.server = FakeLlmServer()
        self.server.embed_mode = 'keywords'
        self.directory = tempfile.TemporaryDirectory()
        config = Path(self.directory.name) / 'body.env'
        config.write_text(f'BODY_LLM_BASE_URL={self.server.url}\nBODY_LLM_MODEL=test-model\nBODY_EMBED_MODEL=test-embed\n',
                          encoding='utf-8')
        self.original = body_route.BodyApi.config_file
        body_route.BodyApi.config_file, body_route.BodyApi._llm_loaded = config, False
        self.path = str(Path(self.directory.name) / 'test.db')
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'DB_TYPE': 'sqlite', 'DATABASE': self.path,
                               'APP_MODE': 'test', 'SMTP_HOST': '', 'SMTP_PORT': '', 'SMTP_USERNAME': '',
                               'SMTP_PASSWORD': '', 'SMTP_FROM_EMAIL': ''})
        today = date.today().isoformat()
        with closing(sqlite3.connect(self.path)) as c:
            for name in ('tester01', 'other'):
                c.execute("INSERT INTO users(username,email,password_hash,is_email_verified,password_changed_at) "
                          "VALUES (?,?,?,1,CURRENT_TIMESTAMP)", (name, f'{name}@example.com', generate_password_hash('Testing!123')))
            c.execute("INSERT INTO exercises(exercise_name,muscle_group,equipment,created_by) VALUES ('槓鈴臥推','胸','槓鈴',1)")
            c.execute("INSERT INTO workouts(user_id,workout_date,started_at,ended_at,duration_min) VALUES (1,?,?,?,50)",
                      (today, today + 'T10:00', today + 'T10:50'))
            c.executemany("INSERT INTO workout_sets(workout_id,exercise_id,set_no,weight_kg,reps) VALUES (1,1,?,60,8)",
                          [(1,), (2,), (3,)])
            c.commit()
        self.client = self.login('tester01')

    def tearDown(self):
        from body import body_route
        body_route.BodyApi.config_file, body_route.BodyApi._llm_loaded = self.original, False
        self.server.close()
        self.directory.cleanup()

    def login(self, name):
        client = self.app.test_client()
        client.get('/login')
        client.post('/login', data={'csrf_token': self.token(client), 'username': name, 'password': 'Testing!123'})
        return client

    @staticmethod
    def token(client):
        client.get('/body/api/docs')
        with client.session_transaction() as s:
            return s['csrf_token']

    def upload(self, client, text, name='coach.md', title=''):
        import io
        response = client.post('/body/api/docs', data={'file': (io.BytesIO(text.encode('utf-8')), name), 'title': title},
                               headers={'X-CSRF-Token': self.token(client)}, content_type='multipart/form-data')
        return response.status_code, response.get_json()

    def test_upload_search_delete_and_ownership(self):
        status, data = self.upload(self.client, ARTICLE, title='教練的背部建議')
        self.assertEqual((status, data['uploaded']['chunks'], data['documents'][0]['usable']), (200, 3, True))
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rag_chunks').fetchone()[0], 3)
            self.assertEqual(c.execute("SELECT file_path, subject_id FROM materials").fetchone(), ('embedding:test-embed', None))
            self.assertEqual(c.execute('SELECT section_title FROM rag_chunk_meta ORDER BY chunk_id').fetchall()[0], ('背部訓練原則',))
        hits = self.client.get('/body/api/docs/search?q=背部划船').get_json()['hits']
        self.assertEqual(hits[0]['section'], '背部訓練原則')
        self.assertEqual(self.client.get('/body/api/docs/search?q=天氣很好').get_json()['hits'], [])   # 不相關 → 沒有結果
        # 別人看不到、刪不掉，也檢索不到
        other = self.login('other')
        self.assertEqual(other.get('/body/api/docs').get_json()['documents'], [])
        self.assertEqual(other.get('/body/api/docs/search?q=背部划船').get_json()['hits'], [])
        doc_id = data['documents'][0]['id']
        self.assertEqual(other.post(f'/body/api/docs/{doc_id}/delete', headers={'X-CSRF-Token': self.token(other)}).status_code, 404)
        # 本人刪除：段落與出處資訊一起刪
        data = self.client.post(f'/body/api/docs/{doc_id}/delete', headers={'X-CSRF-Token': self.token(self.client)}).get_json()
        self.assertEqual(data['documents'], [])
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual([c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                              for t in ('rag_chunks', 'rag_chunk_meta', 'rag_documents', 'materials')], [0, 0, 0, 0])

    def test_upload_validation(self):
        self.assertEqual(self.upload(self.client, 'x', name='coach.pdf')[0], 400)
        self.assertEqual(self.upload(self.client, '   ')[0], 400)
        self.assertIn('最多', self.upload(self.client, '字' * 20001)[1]['error'])
        import io
        response = self.client.post('/body/api/docs', data={'file': (io.BytesIO('中文'.encode('big5')), 'a.txt')},
                                    headers={'X-CSRF-Token': self.token(self.client)}, content_type='multipart/form-data')
        self.assertIn('UTF-8', response.get_json()['error'])
        import io as _io
        response = self.client.post('/body/api/docs', data={'file': (_io.BytesIO(b'abc'), 'a.txt')},
                                    content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)                              # 沒帶 CSRF

    def test_ai_explanation_uses_relevant_passages(self):
        self.upload(self.client, ARTICLE)
        self.server.reply = json.dumps({'summary': '本週練了 3 組胸。',
                                        'weaknesses': ['只有推的動作，背部還沒練 [1]。'],
                                        'suggestions': ['下週加入 2 組划船 [1]。', '多睡覺 [7]。'], 'strengths': []},
                                       ensure_ascii=False)
        data = self.client.post('/body/api/report/ai', json={'period': 'week'},
                                headers={'X-CSRF-Token': self.token(self.client)}).get_json()
        saved = data['ai']['saved']
        self.assertEqual(saved['suggestions'], ['下週加入 2 組划船 [1]。'])          # [7] 不存在 → 拿掉
        self.assertEqual(saved['sources'][0]['section'], '背部訓練原則')              # 用「沒有拉的動作」找到背部那段
        self.assertGreaterEqual(saved['passages'], 1)
        prompt = [r for r in self.server.requests if r['path'].endswith('/chat/completions')][-1]['body']['messages'][1]['content']
        self.assertIn('reference_passages', prompt)
        self.assertIn('划船', prompt)

    def test_without_embedding_config(self):
        from body import body_route
        config = Path(self.directory.name) / 'body.env'
        config.write_text(f'BODY_LLM_BASE_URL={self.server.url}\nBODY_LLM_MODEL=test-model\n', encoding='utf-8')
        body_route.BodyApi._llm_loaded = False
        self.assertFalse(self.client.get('/body/api/docs').get_json()['enabled'])
        self.assertIn('BODY_EMBED_MODEL', self.upload(self.client, ARTICLE)[1]['error'])


if __name__ == '__main__':
    unittest.main()
