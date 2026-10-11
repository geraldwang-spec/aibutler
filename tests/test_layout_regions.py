import unittest
from personal_ai.layout_regions import visual_region,question_crops
from personal_ai.parsers import exam_sections,image_text_kind,image_text_fields,parse_file
from personal_ai.source_content import material_only,clean_visual_stem
from personal_ai.question_importer import extract_by_rules
from personal_ai.import_routing import plan_repairs


class LayoutRegionTests(unittest.TestCase):
    def test_same_line_image_uses_font_band_at_every_scale(self):
        for scale in (.25,.5,1,2,4):
            def box(values): return [x*scale for x in values]
            questions=[dict(number=1,bbox=box([40,100,300,115])),dict(number=2,bbox=box([40,200,300,215]))]
            self.assertEqual(visual_region([],questions,box([70,199,280,250]),400*scale)['range'],(2,2))
    def test_single_column_is_not_split_by_page_midpoint(self):
        questions=[dict(number=1,bbox=[220,100,520,115])]
        self.assertEqual(visual_region([],questions,[20,120,180,200],600)['range'],(1,1))
    def test_crop_follows_question_region_and_full_reading_scope(self):
        questions=[dict(number=1,bbox=[40,100,300,115]),dict(number=2,bbox=[40,200,300,215])]
        crop=question_crops([],questions,{1},400,600)[0]
        self.assertLess(crop[1],100)
        self.assertLess(crop[3],200)
        anchors=[dict(question_from=2,question_to=2,bbox=[40,130,300,145])]
        self.assertLess(question_crops(anchors,questions,{2},400,600)[0][1],130)
    def test_header_does_not_inherit_other_column(self):
        questions=[dict(number=1,bbox=[40,120,300,135]),dict(number=2,bbox=[360,130,580,145])]
        result=visual_region([],questions,[20,30,580,90],600,(1,2))
        self.assertIsNone(result['range'])
        self.assertEqual(result['status'],'unresolved')
    def test_spanning_multiple_questions_requires_review(self):
        questions=[dict(number=1,bbox=[40,100,300,115]),dict(number=2,bbox=[40,200,300,215])]
        result=visual_region([],questions,[60,120,280,250],400)
        self.assertIsNone(result['range'])
        self.assertEqual(result['candidates'],[1,2])
    def test_explicit_scope_allows_shared_table(self):
        questions=[dict(number=2,bbox=[40,100,300,115]),dict(number=3,bbox=[40,200,300,215])]
        anchors=[dict(question_from=2,question_to=3,bbox=[40,70,300,85])]
        self.assertEqual(visual_region(anchors,questions,[60,120,280,250],400)['range'],(2,3))
    def test_unresolved_region_requests_only_local_review(self):
        sections=[dict(text='1. Good?\nA. one\nB. two\n2. Good?\nA. one\nB. two',image_context=[dict(status='unresolved',candidates=[2],range=None,text='unassigned image')])]
        items=extract_by_rules(sections,'test',True)
        self.assertEqual([u['numbers'] for u in plan_repairs(sections,items)[0]],[[2]])
        self.assertNotIn('unassigned image',items[1]['content'])
    def test_ocr_choices_are_not_material(self):
        self.assertEqual(image_text_kind('(A)根據資料一\n(B)依照資料二\nC我發現資料\n(D)我覺得'),'choices')
    def test_mixed_ocr_fields_preserve_material_without_choices(self):
        text='共同資料：原文必須保留。\n(A)甲\n(B)乙\n(C)丙\n(D)丁'
        fields=image_text_fields(text)
        self.assertEqual([f['field'] for f in fields],['material','A','B','C','D'])
        self.assertEqual(fields[0]['text'],'共同資料：原文必須保留。')
        self.assertEqual(image_text_fields('(A)甲\n(B)乙\n(A)另一題')[0]['field'],'unresolved')
    def test_native_formula_numbers_do_not_become_questions(self):
        import tempfile
        from pathlib import Path
        import pymupdf
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'formula.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page()
                for x,y,text in [(40,80,'1. Which formula?'),(110,100,'('),(115,115,'1)'),
                                 (40,150,'(A) one'),(40,170,'(B) two'),(40,200,'2. Another formula?'),
                                 (40,220,'(A) three'),(40,240,'(B) four')]: page.insert_text((x,y),text)
                doc.save(path)
            sections=parse_file(path)
            self.assertIn('1)',sections[0]['text'])
            rows=extract_by_rules(sections,'test',True)
        self.assertEqual([r['_question_no'] for r in rows],[1,2])
        self.assertIn('1)',rows[0]['content'])
    def test_visual_repair_preserves_complete_shared_source(self):
        from personal_ai.import_routing import repair_local_questions
        from unittest.mock import patch
        from pathlib import Path
        passage='請閱讀下文，回答1〜2題：完整文章第一句。重要但非第一題相關的第二句。'
        sections=[dict(locator='page:1',has_images=True,text=passage+'\n1. Missing?\n2. Good?\nA. one\nB. two')]
        items=extract_by_rules(sections,'test',True)
        def visual(unit,*args):
            return [dict(_question_no=n,q_type='單選',content='部分文章\n提問',_question_stem='提問',option_A='one',option_B='two') for n in unit['numbers']]
        with patch('personal_ai.import_routing.extract_unit_with_vision',side_effect=visual):
            result=repair_local_questions(sections,items,'test',{},Path('sample.pdf'))
        for row in result:
            self.assertIn('重要但非第一題相關的第二句',row['content'])
            self.assertNotIn('部分文章',row['content'])
    def test_visual_material_repair_cannot_rewrite_native_options(self):
        from personal_ai.import_routing import repair_local_questions
        from unittest.mock import patch
        from pathlib import Path
        sections=[dict(locator='page:1',has_images=True,text='1. Which statement?\nA. not always\nB. always',
                       image_context=[dict(status='unresolved',candidates=[1],range=None,text='')])]
        items=extract_by_rules(sections,'test',True)
        replacement=dict(_question_no=1,q_type='單選',content='image material\nWhich statement?',
                         _question_stem='Which statement?',_source_material='image material',option_A='always',option_B='never')
        with patch('personal_ai.import_routing.extract_unit_with_vision',return_value=[replacement]):
            result=repair_local_questions(sections,items,'test',{},Path('sample.pdf'))
        self.assertEqual(result[0]['option_A'],'not always')
        self.assertEqual(result[0]['option_B'],'always')
    def test_answer_context_cannot_repeat_question_and_options(self):
        question='根據上述兩份資料，下列何者最恰當？'
        context='【資料一】原文甲。\n【資料二】原文乙。\n'+question+'\nA. 甲\nB. 乙'
        self.assertEqual(material_only(context,dict(content=question)),'【資料一】原文甲。\n【資料二】原文乙。')
        self.assertEqual(clean_visual_stem(question+'\nA. 甲\nB. 乙',{'A':'甲','B':'乙'}),question)
    def test_cover_filter_is_not_fixed_to_first_page(self):
        cover=dict(text='注意事項\n請攜帶准考證\n考試開始後作答\n1. 使用鉛筆\n2. 勿折答案卡')
        exam=dict(text='1. 注意事項中哪一项正确？\nA. 使用准考證\nB. 考試開始後作答')
        self.assertEqual(exam_sections([exam,cover]),[exam])
        self.assertEqual(extract_by_rules([cover,exam],'test',True)[0]['_question_no'],1)


if __name__=='__main__': unittest.main()
