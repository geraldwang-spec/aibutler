import json
import re
import tempfile
import unittest
from pathlib import Path

from personal_ai.question_importer import extract_by_rules, extract_questions
from personal_ai.question_layout import extract_layout, source_fragments
from personal_ai.llm_provider import LLMError


class LayoutModel:
    """Return source locations, never generated question wording."""
    max_input_bytes = 16000
    calls = 0
    field = 'content'

    def complete_json(self, system, user):
        self.calls += 1
        data = json.loads(user.split('\n回傳 ')[0])
        runs = []
        for key, text in data['fragments'].items():
            index = int(key)
            option = re.match(r'^([AB])\.', text)
            if option:
                self.field = option[1]
            elif text.startswith('答案：'):
                self.field = 'answer'
            elif text.startswith('解析：'):
                self.field = 'explanation'
            if runs and runs[-1]['field'] == self.field:
                runs[-1]['e'] = index
            else:
                runs.append(dict(s=index,e=index,field=self.field,new=self.calls==1 and index==0,type='單選'))
        return {'parts': runs}


class QuestionLayoutTests(unittest.TestCase):
    def test_numeric_options_are_not_question_numbers(self):
        from personal_ai.question_importer import _question_start
        self.assertIsNone(_question_start('(A)20 mL'))
        self.assertIsNone(_question_start('(B) 30 mL'))
        self.assertEqual(_question_start('( B ) 12. 題目'), 12)
        rows=self.rules('1. 容量多少？\n(A)20 mL\n(B)30 mL\n答案：B')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['option_A'], '20 mL')

    def test_docx_order_and_broken_pdf_text_detection(self):
        from docx import Document
        from personal_ai.parsers import parse_file, needs_ocr
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'order.docx'
            doc=Document()
            doc.add_paragraph('第一題')
            doc.add_table(rows=1,cols=1).cell(0,0).text='第一題選項'
            doc.add_paragraph('第二題')
            doc.save(path)
            self.assertEqual([s['text'] for s in parse_file(path)], ['第一題','第一題選項','第二題'])
        self.assertTrue(needs_ocr('(cid:1)(cid:2)(cid:3)'+'文字'*30))
        self.assertFalse(needs_ocr('正常的題目文字'*20))

    def rules(self, text):
        return extract_by_rules([{'text':text}], '測試')

    def test_fullwidth_parenthesized_and_multiline_explanation(self):
        rows = self.rules('題目１：下列何者正確？\n（Ａ）選項甲\n（Ｂ）選項乙\n【答案】Ｂ\n【解析】第一行\n第二行')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['answer_key'], 'B')
        self.assertEqual(rows[0]['option_A'], '選項甲')
        self.assertEqual(rows[0]['explanation'], '第一行\n第二行')

    def test_unnumbered_blocks(self):
        rows = self.rules('第一題內容\nA. 甲\nB. 乙\n答案：A\n\n第二題內容\nA. 丙\nB. 丁\n答案：B')
        self.assertEqual([r['answer_key'] for r in rows], ['A','B'])

    def test_passage_is_kept_for_each_group_question(self):
        rows = self.rules('(40-41)\nA long time ago, there was a king.\n40. 選擇第一題\n(A) yes\n(B) no\n答案：B\n41. 選擇第二題\n(A) yes\n(B) no\n答案：A')
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('there was a king' in r['content'] for r in rows))

    def test_long_source_is_copied_without_model_reproduction(self):
        content = '閱讀長文。' * 1400 + 'TAIL_SENTINEL'
        source = '1. '+content+'\nA. 甲\nB. 乙\n答案：B\n解析：原文解析'
        model = LayoutModel()
        rows = extract_layout(source, model, '長文')
        self.assertGreater(model.calls, 1)
        self.assertEqual(rows[0]['content'], content)
        self.assertEqual(rows[0]['answer_key'], 'B')
        self.assertEqual(''.join(source_fragments(source)), source)

    def test_incomplete_model_coverage_is_rejected(self):
        class Broken:
            def complete_json(self, *args):
                return {'parts':[dict(s=0,e=0,field='content',new=True)]}
        with self.assertRaises(LLMError):
            extract_layout('題目\nA. 甲\nB. 乙\n答案：B',Broken(),'測試')

    def test_partial_rules_are_not_silently_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'questions.txt'
            path.write_text('1. 題目\nA. 甲\nB. 乙\n答案：A\n2. 題目沒有答案\nA. 甲\nB. 乙',encoding='utf-8')
            rows, _ = extract_questions(path,'測試',{},mode='rules')
            self.assertEqual(rows, [])

    def test_long_question_validation_and_database_size_guard(self):
        from personal_ai.question_validation import validate
        row = dict(q_type='單選',content='長'*12000,answer_key='A',explanation='解析')
        validated, pairs = validate(row, {'A':'甲','B':'乙'})
        self.assertEqual(validated['content'], row['content'])
        with self.assertRaises(ValueError):
            validate(dict(row,content='😀'*16000), {'A':'甲','B':'乙'})

    def test_long_classification_sees_tail_and_preserves_original(self):
        from personal_ai.classification_context import prepare
        class Summarizer:
            enabled=True
            provider='test'
            fragments=[]
            def complete_json(self,system,user):
                self.fragments.append(user)
                return {'hint':'原文的知識點'}
        model=Summarizer()
        item=dict(content='長'*12000+'TAIL_SENTINEL',answer_key='A',option_A='甲',option_B='乙')
        context=prepare(item,model)
        self.assertIn('TAIL_SENTINEL',''.join(model.fragments))
        self.assertTrue(item['content'].endswith('TAIL_SENTINEL'))
        self.assertTrue(context['_long_classification_context'])

    def test_long_question_reaches_import_preview_storage(self):
        import io
        from flask import g
        from werkzeug.datastructures import FileStorage
        from app import create_app
        from storage import db
        from smartlife import process_import_file
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({'TESTING':True,'DATABASE':str(Path(directory)/'test.db'),
                              'SECRET_KEY':'layout-test','DB_READ_ONLY':False})
            app.instance_path = directory
            with app.test_request_context('/imports',method='POST'):
                db().execute("INSERT INTO users(id,username,email,password_hash) VALUES(1,'tester','tester@example.com','unused')")
                db().execute("INSERT INTO subjects(id,subject_name,created_by) VALUES(1,'測試',1)")
                db().commit()
                g.user = {'id':1}
                content='長文'*6000+'TAIL_SENTINEL'
                upload=FileStorage(stream=io.BytesIO(('1. '+content+'\n(A) 甲\n(B) 乙\n答案：B').encode('utf-8')),filename='long.txt')
                batch=process_import_file(app,{'subject_id':'1','import_strategy':'question_bank','parse_mode':'auto'},upload)
                row=db().execute('SELECT parsed_json FROM import_items WHERE import_id=?',(batch,)).fetchone()
                self.assertEqual(json.loads(row[0])['content'], content)


if __name__ == '__main__':
    unittest.main()
