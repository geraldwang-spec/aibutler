import json
import unittest
from unittest.mock import patch

from admission.placement import CHECK_FAIL, EDGE, FAIL, PASS, check_year, classify, load_data, parse_scores, place
from tests import test_app

STANDARDS = {(115, s): {'頂標': 13, '前標': 11, '均標': 8, '後標': 5, '底標': 3}
             for s in ('國文', '英文', '數學A', '數學B', '社會', '自然')}
EMPTY_CHECKS = dict(check_chinese='', check_english='', check_math_a='', check_math_b='',
                    check_social='', check_science='', check_listening='')


def program(steps, **checks):
    return dict(EMPTY_CHECKS, year=115, **checks,
                steps=[{'label': label, 'subjects': subjects.split('+'), 'min_score': score}
                       for label, subjects, score in steps])


class PlacementLogicTests(unittest.TestCase):
    def test_steps_compare_subject_sums(self):
        p = program([('(英文+自然)', '英文+自然', 26), ('數學A', '數學A', 14)])
        self.assertEqual(check_year(p, {'英文': 14, '自然': 13, '數學A': 15}, '', STANDARDS)['status'], PASS)
        result = check_year(p, {'英文': 13, '自然': 13, '數學A': 15}, '', STANDARDS)
        self.assertEqual((result['status'], result['margin']), (EDGE, 0))
        result = check_year(p, {'英文': 13, '自然': 13, '數學A': 12}, '', STANDARDS)
        self.assertEqual((result['status'], result['margin']), (FAIL, -2))
        self.assertIn('數學A最低 14', result['reason'])
        self.assertEqual(result['weakest'], '數學A')
        # 沒有同級分超額篩選：等於最低級分就確定通過
        p['tie_break_extra'] = ''
        result = check_year(p, {'英文': 13, '自然': 13, '數學A': 15}, '', STANDARDS)
        self.assertEqual((result['status'], result['margin'], result['reason']), (PASS, 0, ''))

    def test_check_standard_and_missing_subject(self):
        p = program([('數學A', '數學A', 10)], check_english='頂標')
        self.assertEqual(check_year(p, {'英文': 12, '數學A': 15}, '', STANDARDS)['status'], CHECK_FAIL)
        self.assertEqual(check_year(p, {'數學A': 15}, '', STANDARDS)['status'], CHECK_FAIL)
        self.assertEqual(check_year(program([('國英數A', '國文+英文+數學A', 30)]), {'國文': 15, '英文': 15}, '', STANDARDS)['status'], FAIL)

    def test_listening_check(self):
        p = program([], check_listening='B')
        self.assertEqual(check_year(p, {'英文': 10}, 'A', STANDARDS)['status'], PASS)
        self.assertEqual(check_year(p, {'英文': 10}, 'C', STANDARDS)['status'], CHECK_FAIL)
        self.assertEqual(check_year(p, {'英文': 10}, '', STANDARDS)['status'], CHECK_FAIL)

    def test_classify_uses_latest_year_and_history(self):
        ok, edge = {'status': PASS, 'margin': 2}, {'status': EDGE, 'margin': 0}
        miss = lambda m: {'status': FAIL, 'margin': m}
        self.assertEqual(classify([ok, ok, ok]), '安全')
        self.assertEqual(classify([ok]), '適中')
        self.assertEqual(classify([ok, miss(-1), ok]), '適中')
        self.assertEqual(classify([edge, ok]), '適中')
        self.assertEqual(classify([miss(-2), miss(-5)]), '夢幻')
        self.assertEqual(classify([miss(-5), ok]), '夢幻')
        self.assertEqual(classify([miss(-5), miss(-6)]), '不建議')
        self.assertEqual(classify([{'status': CHECK_FAIL, 'margin': None}, ok]), '未達檢定')

    def test_parse_scores_validates_input(self):
        self.assertEqual(parse_scores({'國文': '12', '英文': '', '英聽': 'a'}), ({'國文': 12}, 'A', ''))
        for bad in ({}, {'國文': '16'}, {'國文': 'x'}, {'國文': '10', '英聽': 'D'}, {'國文': '10', 'gender': '其他'}):
            with self.assertRaises(ValueError):
                parse_scores(bad)

    def test_real_data_loads_and_places(self):
        standards, history, years = load_data()
        self.assertEqual(years[:3], [115, 114, 113])
        ntu_csie = history[('國立臺灣大學', '資訊工程學系', '無')][115]
        self.assertEqual([s['min_score'] for s in ntu_csie['steps']], [26, 15])
        top = place({s: 15 for s in ('國文', '英文', '數學A', '數學B', '社會', '自然')}, 'A')
        self.assertEqual(top['counts']['未達檢定'], 0)
        self.assertGreater(top['counts']['安全'], 200)
        self.assertFalse(any('希望組' in r['program'] or '招生' in r['program'] for r in top['rows']))
        self.assertTrue(any('希望組' in r['program'] for r in place({'國文': 15}, '', '', include_special=True)['rows']))
        female = place({'國文': 12, '英文': 12, '社會': 12, '數學B': 10}, '', '女')
        self.assertNotIn('男', {r['gender'] for r in female['rows']})


class PlacementPageTests(unittest.TestCase):
    # 只借用 AppTests 的建立帳號流程，不繼承（避免重跑它的測試）
    base = test_app.AppTests
    setUp, tearDown, post, register, login = base.setUp, base.tearDown, base.post, base.register, base.login

    def test_page_requires_login_and_renders_results(self):
        self.assertEqual(self.client.get('/admission').status_code, 302)
        self.register(); self.login()
        page = self.client.get('/admission', headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        self.assertIn('學測落點分析', page)
        page = self.client.get('/admission?英文=15&數學A=15&自然=15', headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        self.assertIn('國立臺灣大學 資訊工程學系', page)
        # 臺大植病 114 年改用「英文 ≥ 14」篩選：要顯示是哪一科差幾級分，以及歷年規則
        page = self.client.get('/admission?國文=13&英文=10&數學A=8&自然=13', headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        self.assertIn('英文差 4', page)
        self.assertIn('114 年：英文 ≥ 14 → 自然 ≥ 13', page)
        page = self.client.get('/admission?國文=99', headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        self.assertIn('0–15', page)

    def test_advice_request_submits_job_and_page_shows_result(self):
        self.register(); self.login()
        with patch('personal_ai.jobs.submit', return_value='job1') as submit:
            response = self.post('/admission/advice', {'英文': '13', '數學A': '12', 'unknown_field': 'x'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/ai/jobs/job1', response.location)
        self.assertEqual(submit.call_args.args[2:], ('admission_advice', {'英文': '13', '數學A': '12'}))
        advice = {'summary': '整體落點不錯', 'picks': [{'program': '國立成功大學 土木工程學系', 'why': '三年都過'}],
                  'improve': [], 'caution': ''}
        with patch('admission._advice', return_value=advice):
            page = self.client.get('/admission?英文=13&數學A=12&advice=job1',
                                   headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        self.assertIn('整體落點不錯', page)
        self.assertNotIn('請 AI 解讀', page)

    def test_advice_hidden_when_scores_changed(self):
        self.register(); self.login()
        job = {'kind': 'admission_advice', 'status': 'completed', 'payload': '{"英文": "13", "數學A": "12"}',
               'result': '{"advice": {"summary": "舊的解讀", "picks": [], "improve": [], "caution": ""}}'}
        get = lambda q: self.client.get('/admission?' + q, headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        with patch('personal_ai.jobs.read', return_value=job):
            self.assertIn('舊的解讀', get('英文=13&數學A=12&advice=job1'))
            self.assertNotIn('舊的解讀', get('英文=15&數學A=12&advice=job1'))
        with patch('personal_ai.jobs.read', return_value=dict(job, kind='chat')):
            self.assertNotIn('舊的解讀', get('英文=13&數學A=12&advice=job1'))

    def test_page_lists_covered_schools(self):
        self.register(); self.login()
        page = self.client.get('/admission', headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        self.assertIn('國立臺灣師範大學', page)
        self.assertIn('113、114、115 學年度', page)


class AdviceTests(unittest.TestCase):
    def test_advice_keeps_only_programs_from_summary(self):
        from admission.advice import generate_advice
        from app import create_app

        class FakeModel:
            def complete_json(self, system, user):
                self.user = user
                return {'summary': '說明', 'picks': [{'ref': 1, 'why': '穩'}, {'ref': 999, 'why': '編的'},
                                                    {'ref': '2', 'why': '型別不對'}],
                        'improve': [{'subject': '數學A', 'advice': '多練'}], 'caution': '僅供參考'}

        fake = FakeModel()
        app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'DATABASE': ':memory:'})
        with app.app_context(), patch('personal_ai.llm_provider.get_llm', return_value=fake):
            advice = generate_advice({'國文': '13', '英文': '13', '數學A': '12', '自然': '13'})
        self.assertEqual(len(advice['picks']), 1)
        self.assertIn('ref', fake.user)
        self.assertEqual(advice['improve'], [{'subject': '數學A', 'advice': '多練'}])


class InterestTests(unittest.TestCase):
    RECOMMENDATION = {'interest': '想寫程式做遊戲', 'summary': '適合資訊相關', 'explore': '',
                      'groups': [{'group': '資訊', 'why': '寫程式', 'career': '工程師'}]}

    def test_department_names_drop_groups(self):
        from admission.interest import department, departments
        self.assertEqual(department('經濟學系A組'), '經濟學系')
        self.assertEqual(department('醫學系(公費生)'), '醫學系')
        self.assertEqual(department('生物環境系統工程學系'), '生物環境系統工程學系')
        self.assertIn(('國立臺灣大學', '資訊工程學系', '無'), departments()['資訊工程學系'])
        self.assertFalse(any('招生' in name for name in departments()))

    def test_every_department_belongs_to_a_group(self):
        from admission.interest import UNGROUPED, departments, groups_of
        self.assertEqual([n for n in departments() if not groups_of(n) and not UNGROUPED.search(n)], [])
        # 名稱裡碰巧含有其他學群關鍵字的科系
        for name, expected in (('資訊管理學系', ['資訊', '管理']), ('財務工程學系', ['財經']),
                               ('獸醫學系', ['生物資源']), ('德國文化學系', ['外語', '文史哲']),
                               ('教育心理與諮商學系', ['社會與心理', '教育']), ('宗教學系', ['社會與心理', '文史哲']),
                               ('物理治療學系', ['醫藥衛生']), ('晶片設計學士學位學程', ['資訊', '工程'])):
            self.assertEqual(groups_of(name), expected, name)

    def test_interest_keeps_only_known_groups(self):
        from admission.interest import generate_interest
        from app import create_app

        class FakeModel:
            def complete_json(self, system, user):
                self.user = user
                return {'summary': '說明', 'explore': '多看課程地圖',
                        'groups': [{'group': '資訊學群', 'why': '寫程式', 'career': '工程師'},
                                   {'group': '遊戲學群', 'why': '編的'},
                                   {'group': '資訊', 'why': '重複'}, {'group': '藝術', 'why': '做遊戲美術'}]}

        fake = FakeModel()
        app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'DATABASE': ':memory:'})
        with app.app_context(), patch('personal_ai.llm_provider.get_llm', return_value=fake):
            result = generate_interest({'interest': '想寫程式做遊戲'})
            self.assertEqual([g['group'] for g in result['groups']], ['資訊', '藝術'])
            self.assertIn('資訊工程學系', fake.user)  # 學群附例子
            self.assertLess(len(fake.user.encode()), 3000)  # 不再送出整份科系清單
            with self.assertRaises(ValueError):
                generate_interest({'interest': '想'})

    def test_attach_schools_uses_placement_tiers(self):
        from admission.interest import attach_schools
        plain = attach_schools(self.RECOMMENDATION)['groups'][0]
        self.assertIn('資訊工程學系', [m['department'] for m in plain['majors']])
        self.assertTrue(all(s['tier'] is None for m in plain['majors'] for s in m['schools']))
        result = place({'國文': 10, '英文': 10, '數學A': 10, '自然': 10}, 'B')
        group = attach_schools(self.RECOMMENDATION, result)['groups'][0]
        tiers = [s['tier'] for m in group['majors'] for s in m['schools']]
        self.assertTrue(tiers and set(tiers) <= {'安全', '適中', '夢幻'})
        self.assertGreater(group['hidden'], 0)

    test_app_base = test_app.AppTests
    setUp, tearDown, post, register, login = (test_app_base.setUp, test_app_base.tearDown, test_app_base.post,
                                              test_app_base.register, test_app_base.login)

    def test_interest_request_and_page(self):
        self.register(); self.login()
        with patch('personal_ai.jobs.submit', return_value='job2') as submit:
            response = self.post('/admission/interest', {'interest': ' 想寫程式 ', '英文': '13'})
        self.assertIn('/ai/jobs/job2', response.location)
        self.assertEqual(submit.call_args.args[2:], ('admission_interest', {'英文': '13', 'interest': '想寫程式'}))
        job = {'kind': 'admission_interest', 'status': 'completed', 'payload': '{}',
               'result': json.dumps({'interest': self.RECOMMENDATION}, ensure_ascii=False)}
        get = lambda q: self.client.get('/admission?' + q, headers={'Sec-Fetch-Dest': 'iframe'}).get_data(as_text=True)
        with patch('personal_ai.jobs.read', return_value=job):
            page = get('interest=job2')
            self.assertIn('國立臺灣大學 資訊工程學系', page)
            self.assertNotIn('請至少輸入一科', page)
            # 臺大資工數學A最低 15 級分且有同分超額篩選：滿級分仍只是壓線
            self.assertIn('國立臺灣大學 資訊工程學系：適中', get('國文=15&英文=15&數學A=15&自然=15&英聽=A&interest=job2'))
        with patch('personal_ai.jobs.read', return_value=dict(job, kind='chat')):
            self.assertNotIn('興趣推薦學群', get('interest=job2'))


if __name__ == '__main__':
    unittest.main()
