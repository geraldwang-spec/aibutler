import json
import re
import unittest

from personal_ai.question_ranges import reading_ranges
from personal_ai.question_layout import extract_layout
from personal_ai.parsers import pdf_reading_anchors


class QuestionRangeTests(unittest.TestCase):
    def test_wrapped_answer_boxes_keep_question_numbers(self):
        from personal_ai.question_importer import extract_by_rules,_question_start
        text='(\n)1. First?\n(A)one(B)two\n(\n)2. Second?\n(A)one(B)two'
        rows=extract_by_rules([{'text':text}],'測試',allow_missing_answers=True)
        self.assertEqual([x['_question_no'] for x in rows],[1,2])
        self.assertEqual(rows[0]['content'],'First?')
        self.assertEqual(rows[0]['option_B'],'two')
        self.assertIsNone(_question_start(')abc'))

    def test_pdf_column_positions_not_last_heading_on_page(self):
        import pymupdf
        with pymupdf.open() as doc:
            page=doc.new_page(width=600,height=800)
            page.insert_text((40,500),'Read a poem and answer questions 2-3.',fontsize=9)
            page.insert_text((330,100),'Read a story and answer questions 4-6.',fontsize=9)
            anchors=pdf_reading_anchors(page)
            self.assertEqual([(a['question_from'],a['question_to']) for a in anchors],[(2,3),(4,6)])
            before_left_image=[a for a in anchors if a['order']<=(0,550)]
            self.assertEqual(before_left_image[-1]['question_from'],2)

    def test_unicode_and_wrapped_instructions(self):
        for separator in ('〜','～','–','—','−','至','到','-'):
            anchors=reading_ranges(f'請閱讀以下短文，\n並回答\n１２ {separator} １４ 題：')
            self.assertEqual([(a['question_from'],a['question_to']) for a in anchors],[(12,14)])

    def test_english_and_non_reading_ranges(self):
        anchors=reading_ranges('Read the passage and answer questions 7 through 9.\n'
                               '一、單題（1〜23 題）\n二、題組（24〜42 題）\n產量增加5〜7倍')
        self.assertEqual([(a['question_from'],a['question_to']) for a in anchors],[(7,9)])

    def test_source_instruction_outranks_missing_model_scope(self):
        class Model:
            max_input_bytes=16000
            field='content'
            def complete_json(self,system,user):
                payload=json.JSONDecoder().raw_decode(user)[0]
                if 'questions' in payload:
                    raise AssertionError('Explicit source range must not need semantic guessing')
                runs=[]
                for key,text in payload['fragments'].items():
                    new=False
                    field=self.field
                    if '請閱讀' in text or '並回答' in text:
                        field='ignore'  # Model accidentally discards the heading.
                    elif text.startswith('共用文章'):
                        self.field=field='passage'; new=True
                    elif re.match(r'^\d+\.',text):
                        self.field=field='content'; new=True
                    elif re.match(r'^[AB]\.',text): self.field=field=text[0]
                    elif text.startswith('答案：'): self.field=field='answer'
                    runs.append(dict(s=int(key),e=int(key),field=field,new=new,type='單選',
                                     question_from=None,question_to=None))
                return {'parts':runs}
        rows=extract_layout('請閱讀以下資料，並回答12〜13題：\n共用文章提供背景。\n'
                            '12. 問題一？\nA. 甲\nB. 乙\n答案：A\n'
                            '13. 問題二？\nA. 甲\nB. 乙\n答案：B',Model(),'測試')
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertIn('共用文章',row['content'])
            self.assertEqual(row['_passage_range'],[12,13])


if __name__=='__main__':
    unittest.main()
