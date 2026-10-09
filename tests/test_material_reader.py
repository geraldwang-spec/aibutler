import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_chat_rag
from storage import db


class MaterialReaderTests(unittest.TestCase):
    setUp=test_chat_rag.ChatRagTests.setUp
    tearDown=test_chat_rag.ChatRagTests.tearDown

    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session['user_id']=1
            session['csrf_token']='test-csrf'
        return client

    def upload(self,client,text,name='reading.txt'):
        response=client.post('/knowledge',data={'csrf_token':'test-csrf','subject_id':'1',
            'file':(io.BytesIO(text.encode('utf-8')),name)})
        self.assertEqual(response.status_code,302)
        return db().execute('SELECT * FROM materials WHERE user_id=1 ORDER BY id DESC').fetchone()

    def test_upload_preserves_reading_copy_and_download(self):
        client=self.client()
        original='第一段：未知數用字母表示。\n\n第二段：<script>alert(1)</script>不要執行這段文字。'
        material=self.upload(client,original)
        path=Path(material['file_path'])
        self.assertEqual(path.read_text(encoding='utf-8'),original)
        snapshot=json.loads(path.with_suffix('.txt.reader.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot[0]['text'],original)
        reader=client.get(f'/knowledge/{material["id"]}',headers={'Sec-Fetch-Dest':'iframe'})
        html=reader.get_data(as_text=True)
        self.assertIn('解析文字',html)
        self.assertIn('\n\n第二段',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('no-store',reader.headers['Cache-Control'])
        with client.get(f'/knowledge/{material["id"]}/file') as response:
            self.assertEqual(response.data,original.encode())
            self.assertIn('attachment',response.headers['Content-Disposition'])
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        shelf=client.get('/knowledge',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True)
        self.assertIn('閱讀教材',shelf)

    def test_reader_and_file_do_not_expose_another_users_material(self):
        client=self.client()
        self.assertEqual(client.get('/knowledge/2',headers={'Sec-Fetch-Dest':'iframe'}).status_code,404)
        self.assertEqual(client.get('/knowledge/2/file').status_code,404)
        self.assertEqual(client.get('/knowledge/98765',headers={'Sec-Fetch-Dest':'iframe'}).status_code,404)

    def test_missing_original_still_shows_database_chunks_with_notice(self):
        client=self.client()
        response=client.get('/knowledge/1',headers={'Sec-Fetch-Dest':'iframe'})
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('本機找不到原始檔案',html)
        self.assertIn('資料庫知識片段',html)
        self.assertIn('自變數',html)
        self.assertNotIn('下載原檔</a>',html)
        self.assertEqual(client.get('/knowledge/1/file').status_code,404)

    def test_old_text_material_without_snapshot_remains_readable(self):
        client=self.client()
        material=self.upload(client,'第一段\n\n第二段')
        Path(material['file_path']).with_suffix('.txt.reader.json').unlink()
        html=client.get(f'/knowledge/{material["id"]}',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True)
        self.assertIn('解析文字',html)
        self.assertIn('第一段\n\n第二段',html)

    def test_file_outside_private_root_is_not_served(self):
        # Point a owned record at an existing project file. It must not be served.
        outside=Path(__file__).resolve()
        db().execute('UPDATE materials SET file_path=? WHERE id=1',(str(outside),))
        db().commit()
        client=self.client()
        self.assertEqual(client.get('/knowledge/1/file').status_code,404)
        self.assertIn('本機找不到原始檔案',client.get('/knowledge/1',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True))

    def test_pdf_uses_authenticated_inline_file_and_can_download(self):
        client=self.client()
        with patch('personal_ai.routes.parse_file',return_value=[dict(text='PDF 測試文字',locator='page:1',title='第1頁')]):
            material=self.upload(client,'%PDF-1.4\nfixture only','lecture.pdf')
        html=client.get(f'/knowledge/{material["id"]}',headers={'Sec-Fetch-Dest':'iframe'}).get_data(as_text=True)
        self.assertIn('PDF 原始教材',html)
        self.assertIn(f'/knowledge/{material["id"]}/file',html)
        with client.get(f'/knowledge/{material["id"]}/file') as response:
            self.assertEqual(response.mimetype,'application/pdf')
            self.assertIn('inline',response.headers['Content-Disposition'])
        with client.get(f'/knowledge/{material["id"]}/file?download=1') as response:
            self.assertIn('attachment',response.headers['Content-Disposition'])

    def test_upload_failure_cleans_up_original_and_reading_copy(self):
        client=self.client()
        with patch('personal_ai.routes.parse_file',return_value=[]):
            response=client.post('/knowledge',data={'csrf_token':'test-csrf','subject_id':'1',
                'file':(io.BytesIO(b'empty'),'empty.txt')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(list((Path(self.directory.name)/'personal_ai_uploads'/'1').iterdir()),[])

    def test_reading_requires_login(self):
        client=self.app.test_client()
        self.assertEqual(client.get('/knowledge/1',headers={'Sec-Fetch-Dest':'iframe'}).status_code,302)
        self.assertEqual(client.get('/knowledge/1/file').status_code,302)
