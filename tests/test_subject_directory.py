import re
import unittest
from tests import test_chat_rag
from storage import db


class SubjectDirectoryTests(unittest.TestCase):
    setUp=test_chat_rag.ChatRagTests.setUp
    tearDown=test_chat_rag.ChatRagTests.tearDown

    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session['user_id']=1
            session['csrf_token']='test-csrf'
        return client

    def seed(self):
        for cid,parent,name in [(1,None,'主章節'),(2,1,'子章節'),(3,2,'細節'),(4,None,'其他章節')]:
            db().execute('INSERT INTO chapters(id,subject_id,parent_chapter_id,chapter_name,order_no) VALUES(?,1,?,?,?)',(cid,parent,name,cid))
        db().commit()

    def page(self,path='/records/subjects?subject_id=1'):
        return self.client().get(path,headers={'Sec-Fetch-Dest':'iframe'})

    def test_directory_controls_and_breadcrumbs(self):
        self.seed()
        response=self.page()
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        for text in ('放在哪裡？','全部展開','收合子章節','主章節 / 子章節 / 細節','進階設定','匯入題目'):
            self.assertIn(text,html)
        self.assertIn('data-collapse-chapter="1"',html)
        self.assertIn('aria-controls="chapter-node-2 chapter-node-3 ',html)

    def test_editor_excludes_itself_and_descendants_as_parent(self):
        self.seed()
        html=self.page('/records/chapters?subject_id=1&edit=1').get_data(as_text=True)
        parent=re.search(r'<select id="parent_chapter_id".*?</select>',html,re.S).group()
        for cid in (1,2,3): self.assertNotIn(f'value="{cid}"',parent)
        self.assertIn('value="4"',parent)
        self.assertIn('name="id" value="1"',html)

    def test_new_chapter_form_opens_from_header_and_creates_in_current_subject(self):
        self.seed()
        html=self.page('/records/subjects?subject_id=1&new_chapter=1').get_data(as_text=True)
        self.assertRegex(html,r'<details id="chapter-edit-panel"\s+open')
        response=self.client().post('/records/chapters?subject_id=1',data=dict(csrf_token='test-csrf',
            subject_id='1',chapter_name='新章節',parent_chapter_id='1',order_no='5'))
        self.assertEqual(response.status_code,302)
        row=db().execute("SELECT * FROM chapters WHERE chapter_name='新章節'").fetchone()
        self.assertEqual(row['parent_chapter_id'],1)
        self.assertEqual(row['subject_id'],1)

    def test_edit_error_preserves_id_and_entered_name(self):
        self.seed()
        response=self.client().post('/records/chapters?subject_id=1',data=dict(csrf_token='test-csrf',id='1',
            subject_id='1',chapter_name='保留我的名稱',parent_chapter_id='2',order_no='1'))
        html=response.get_data(as_text=True)
        self.assertIn('上層章節不能選自己或自己的子章節',html)
        self.assertIn('name="id" value="1"',html)
        self.assertIn('value="保留我的名稱"',html)
        self.assertEqual(db().execute('SELECT chapter_name FROM chapters WHERE id=1').fetchone()[0],'主章節')

    def test_subject_import_link_preselects_correct_subject(self):
        html=self.page('/imports?subject_id=1').get_data(as_text=True)
        self.assertRegex(html,r'<option value="1"\s+selected')

    def test_empty_subject_has_clear_start_and_ownership_is_kept(self):
        self.assertIn('先建立第一個章節',self.page().get_data(as_text=True))
        self.assertEqual(self.page('/records/subjects?subject_id=2').status_code,404)
