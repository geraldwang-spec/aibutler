import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_ai.import_routing import plan_repairs,repair_local_questions
from personal_ai.question_importer import extract_by_rules,extract_questions
from personal_ai.question_answering import compact_answer_payload,infer_missing_answers
from personal_ai.llm_provider import LLMError


class ImportRoutingTests(unittest.TestCase):
    def test_classifier_shared_material_is_not_repeated(self):
        from personal_ai.concept_classifier import _compact_questions
        shared='共用文章原文。'*30
        items=[dict(content=shared+'\n\n問題'+str(i),_shared_text=shared,q_type='單選') for i in (1,2)]
        payload=_compact_questions(items)
        self.assertEqual(payload[0]['passage'],shared)
        self.assertNotIn('passage',payload[1])
        self.assertEqual(payload[0]['passage_id'],payload[1]['passage_id'])
        self.assertEqual(payload[1]['question'],'問題2')

    def test_partial_image_repair_receives_only_target_page_and_no_answers(self):
        import pymupdf
        from personal_ai.import_routing import extract_unit_with_vision
        class Vision:
            images=[]
            def complete_json_with_images(self,system,user,images):
                self.images=images
                self.assertion='不得推定答案' in system
                return {'questions':[dict(number=2,q_type='單選',content='Which figure?',options={'A':'one','B':'two'},answer_key='A')]}
        model=Vision()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.pdf'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40,60),'1. unrelated')
                doc.new_page().insert_text((40,60),'2. Which figure?')
                doc.save(path)
            with patch('personal_ai.llm_provider.get_vision_llm',return_value=model):
                result=extract_unit_with_vision(dict(numbers=[2],text='2. Which figure?'),path,'測試',{})
        self.assertEqual(len(model.images),1)
        self.assertTrue(model.assertion)
        self.assertEqual(result[0]['answer_key'],'')

    def test_one_bad_question_does_not_send_good_questions(self):
        text='1. Good first?\nA. one\nB. two\n答案：A\n2. Broken?\n3. Good last?\nA. three\nB. four\n答案：B'
        sections=[{'text':text}]
        local=extract_by_rules(sections,'測試',True)
        units,numbers=plan_repairs(sections,local)
        self.assertEqual(numbers,{1,2,3})
        self.assertEqual([u['numbers'] for u in units],[[2]])
        def repair(section,*args,**kwargs):
            self.assertIn('2. Broken?',section[0]['text'])
            self.assertNotIn('Good',section[0]['text'])
            return [dict(local[1],q_type='單選',option_A='one',option_B='two',answer_key='A')]
        with patch('personal_ai.question_importer.extract_with_llm',side_effect=repair) as model:
            result=repair_local_questions(sections,local,'測試',{})
        self.assertEqual(model.call_count,1)
        self.assertEqual(result[0],local[0])
        self.assertEqual(result[2],local[2])

    def test_one_bad_reading_question_repairs_only_its_group(self):
        text='1. Independent?\nA. one\nB. two\n答案：A\n請閱讀下文，回答2〜3題：共享文章說明。\n2. Broken?\n3. Article question?\nA. one\nB. two\n答案：B\n請閱讀下文，回答4〜5題：另一篇文章。\n4. Other?\nA. one\nB. two\n答案：A\n5. Other last?\nA. one\nB. two\n答案：A'
        sections=[{'text':text}]
        local=extract_by_rules(sections,'測試',True)
        units,_=plan_repairs(sections,local)
        self.assertEqual([u['numbers'] for u in units],[[2,3]])
        self.assertIn('共享文章',units[0]['text'])
        self.assertNotIn('Independent',units[0]['text'])
        self.assertNotIn('另一篇',units[0]['text'])

    def test_failed_repair_marks_only_target_and_preserves_good_answers(self):
        sections=[{'text':'1. Good?\nA. one\nB. two\n答案：A\n2. Broken?\n3. Good?\nA. one\nB. two\n答案：B'}]
        local=extract_by_rules(sections,'測試',True)
        with patch('personal_ai.question_importer.extract_with_llm',return_value=[local[0]]):
            result=repair_local_questions(sections,local,'測試',{})
        self.assertEqual([x['answer_key'] for x in result],['A','','B'])
        self.assertIn('_layout_needs_review',result[1])
        self.assertNotIn('_layout_needs_review',result[0])

    def test_complete_auto_import_does_not_call_layout_or_answer_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'good.txt'
            path.write_text('1. Good?\nA. one\nB. two\n答案：A',encoding='utf-8')
            with patch('personal_ai.question_importer.extract_with_llm') as layout,patch('personal_ai.question_answering.infer_missing_answers') as answer:
                rows,_=extract_questions(path,'測試',{},'auto')
            self.assertEqual(len(rows),1)
            layout.assert_not_called()
            answer.assert_not_called()

    def test_shared_passage_is_transmitted_once_without_source_loss(self):
        material='請閱讀下文，回答2〜3題：'+('共享文章原文。'*100)
        batch=[dict(_question_no=i,q_type='單選',content=material+'\n\n問題'+str(i),
                    _shared_text=material,option_A='甲',option_B='乙') for i in (2,3)]
        payload=compact_answer_payload(batch)
        self.assertEqual(payload[0]['passage'],material)
        self.assertNotIn('passage',payload[1])
        self.assertEqual(payload[0]['passage_id'],payload[1]['passage_id'])
        self.assertEqual([r['content'] for r in payload],['問題2','問題3'])
        self.assertLess(len(json.dumps(payload,ensure_ascii=False)),len(json.dumps(batch,ensure_ascii=False))/2)

    def test_pure_text_pdf_answer_does_not_send_images(self):
        import pymupdf
        class Text:
            enabled=True
            provider='test'
            model='text'
            def complete_json(self,system,user):
                payload=json.loads(user.split('\n回傳 ')[0])
                return {'answers':[dict(number=r['number'],status='answered',answer='B',explanation='原文支持',context='') for r in payload]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plain.pdf'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40,60),'1. Pure text?\n(A) one\n(B) two')
                doc.save(path)
            rows=extract_by_rules([{'text':'1. Pure text?\n(A) one\n(B) two'}],'測試',True)
            with patch('personal_ai.question_answering.get_parser_llm',return_value=Text()),patch('personal_ai.question_answering.get_vision_llm') as vision:
                result=infer_missing_answers(rows,[],path,{})
                vision.return_value.complete_json_with_images.assert_not_called()
            self.assertEqual(result[0]['answer_key'],'B')

    def test_visual_reference_uses_only_current_page_for_nonreading_question(self):
        import pymupdf
        class Vision:
            enabled=True
            provider='test'
            model='vision'
            images=[]
            def complete_json_with_images(self,system,user,images):
                self.images=images
                self.assertion='附圖來源頁碼（依順序）：2' in user
                return {'answers':[dict(number=2,status='answered',answer='A',explanation='圖片支持',context='')]}
        model=Vision()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'visual.pdf'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40,60),'1. Unrelated page.')
                doc.new_page().insert_text((40,60),'2. Which figure?\n(A) one\n(B) two')
                doc.save(path)
            rows=extract_by_rules([{'text':'2. Which figure?\n(A) one\n(B) two'}],'測試',True)
            with patch('personal_ai.question_answering.get_parser_llm',return_value=model),patch('personal_ai.question_answering.get_vision_llm',return_value=model):
                result=infer_missing_answers(rows,[],path,{})
        self.assertEqual(result[0]['answer_key'],'A')
        self.assertEqual(len(model.images),1)
        self.assertTrue(model.assertion)


if __name__=='__main__': unittest.main()
