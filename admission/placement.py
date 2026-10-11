"""學測個人申請第一階段落點比對。

資料：data/admission/*.csv（甄選會篩選結果，由 data/admission/source/build.py 產生）。
判斷全由程式依歷年資料計算，不交給 LLM；LLM 之後只負責解釋結果。

不同學年度的校系代碼可能對應不同科系，所以歷年比對一律用（校名, 校系名稱, 性別）。
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / 'data' / 'admission'

SUBJECTS = ('國文', '英文', '數學A', '數學B', '社會', '自然')
CHECK_COLUMNS = dict(zip(SUBJECTS, ('check_chinese', 'check_english', 'check_math_a',
                                    'check_math_b', 'check_social', 'check_science')))
STANDARD_COLUMNS = {'頂標': 'top', '前標': 'front', '均標': 'average', '後標': 'back', '底標': 'bottom'}
LISTENING_RANK = {'A': 4, 'B': 3, 'C': 2, 'F': 1}

# 經濟弱勢／特定身分才能報名的招生管道（如希望組、政星、旭日、向日葵、興翼、晨光、薪火、屯蒙、青年儲蓄帳戶組）
# 這類管道名稱都帶「招生」，一般校系名稱不會出現這兩個字
SPECIAL_TRACK_KEYWORDS = ('希望組', '招生', '屯蒙', '青年儲蓄帳戶')

PASS, EDGE, FAIL, CHECK_FAIL = 'pass', 'edge', 'fail', 'check_fail'
TIERS = ('安全', '適中', '夢幻', '不建議', '未達檢定')


def _read(name):
    with (DATA_DIR / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def load_data():
    standards = {}
    for row in _read('exam_standards.csv'):
        standards[(int(row['year']), row['subject'])] = {level: int(row[col]) for level, col in STANDARD_COLUMNS.items()}

    programs = {}
    for row in _read('sieve_programs.csv'):
        row['year'] = int(row['year'])
        row['steps'] = []
        programs[(row['year'], row['program_code'], row['gender'])] = row
    for step in _read('sieve_steps.csv'):
        key = (int(step['year']), step['program_code'], step['gender'])
        # 檔案內已依篩選順序排列
        programs[key]['steps'].append({'label': step['label'], 'subjects': step['subjects'].split('+'),
                                       'min_score': int(step['min_score'])})

    history = {}
    for program in programs.values():
        history.setdefault((program['school'], program['program'], program['gender']), {})[program['year']] = program
    years = sorted({p['year'] for p in programs.values()}, reverse=True)
    return standards, history, years


def parse_scores(form):
    """表單 -> {科目: 級分}；空白代表未考該科。"""
    scores = {}
    for subject in SUBJECTS:
        raw = str(form.get(subject, '') or '').strip()
        if not raw:
            continue
        if not raw.isdigit() or not 0 <= int(raw) <= 15:
            raise ValueError(f'{subject} 級分需為 0–15 的整數。')
        scores[subject] = int(raw)
    if not scores:
        raise ValueError('請至少輸入一科學測級分。')
    listening = str(form.get('英聽', '') or '').strip().upper()
    if listening and listening not in LISTENING_RANK:
        raise ValueError('英聽等級需為 A、B、C 或 F。')
    gender = str(form.get('gender', '') or '').strip()
    if gender not in ('', '男', '女'):
        raise ValueError('性別選項不正確。')
    return scores, listening, gender


def check_year(program, scores, listening, standards):
    """單一年度的結果：status、margin（最緊的篩選步驟高出最低級分多少）、未過原因。"""
    year = program['year']
    for subject, column in CHECK_COLUMNS.items():
        level = program[column]
        if not level:
            continue
        need = standards.get((year, subject), {}).get(level)
        if need is None:
            raise LookupError(f'缺少 {year} 學年度 {subject} 五標資料。')
        if scores.get(subject) is None or scores[subject] < need:
            return {'status': CHECK_FAIL, 'margin': None,
                    'reason': f'{subject}需達{level}（{need} 級分）'}
    if program['check_listening']:
        need = program['check_listening']
        if LISTENING_RANK.get(listening, 0) < LISTENING_RANK[need]:
            return {'status': CHECK_FAIL, 'margin': None, 'reason': f'英聽需達 {need} 級'}

    margin, weakest = None, None
    for step in program['steps']:
        if any(s not in scores for s in step['subjects']):
            return {'status': FAIL, 'margin': None, 'reason': f'未考{step["label"]}所需科目'}
        diff = sum(scores[s] for s in step['subjects']) - step['min_score']
        if margin is None or diff < margin:
            margin, weakest = diff, step
    if margin is None:  # 報名未超額，只看檢定
        return {'status': PASS, 'margin': None, 'reason': '', 'weakest': ''}
    # 沒有同級分超額篩選時，等於最低級分的人全數通過，不算壓線
    tie_break = program.get('tie_break_extra', 'Y') == 'Y'
    status = PASS if margin > 0 or margin == 0 and not tie_break else EDGE if margin == 0 else FAIL
    reason = '' if status == PASS else f'{weakest["label"]}最低 {weakest["min_score"]} 級分'
    return {'status': status, 'margin': margin, 'reason': reason, 'weakest': weakest['label']}


def classify(results):
    """以最新年度為準，配合歷年結果分級。results 依年度新到舊。"""
    latest = results[0]
    if latest['status'] == CHECK_FAIL:
        return '未達檢定'
    passed = [r['status'] in (PASS, EDGE) for r in results if r['status'] != CHECK_FAIL]
    if latest['status'] == PASS and all(passed) and len(results) >= 2:  # 只有一年資料不足以判斷安全
        return '安全'
    if latest['status'] in (PASS, EDGE):
        return '適中'
    if latest['margin'] is not None and latest['margin'] >= -2 or any(passed):
        return '夢幻'
    return '不建議'


def coverage():
    """頁面說明用：最新年度收錄的學校（依代碼排序）與所有學年度。"""
    _, history, years = load_data()
    schools = {}
    for by_year in history.values():
        if years[0] in by_year:
            program = by_year[years[0]]
            schools[program['school_code']] = program['school']
    return [schools[code] for code in sorted(schools)], years


def is_special_track(name):
    return any(keyword in name for keyword in SPECIAL_TRACK_KEYWORDS)


def place(scores, listening='', gender='', include_special=False):
    standards, history, years = load_data()
    latest_year = years[0]
    rows = []
    for (school, name, program_gender), by_year in history.items():
        if latest_year not in by_year:
            continue  # 今年已停招或改名，不列入
        if gender and program_gender not in ('無', gender):
            continue
        if not include_special and is_special_track(name):
            continue
        results = []
        for year in years:
            if year in by_year:
                result = check_year(by_year[year], scores, listening, standards)
                result['year'] = year
                result['steps'] = by_year[year]['steps']  # 每年的篩選規則可能不同
                results.append(result)
        current = by_year[latest_year]
        rows.append({'school': school, 'program': name, 'gender': program_gender,
                     'code': current['program_code'], 'quota': int(current['quota']),
                     'steps': current['steps'], 'tier': classify(results), 'results': results})
    order = {tier: i for i, tier in enumerate(TIERS)}
    rows.sort(key=lambda r: (order[r['tier']], -(r['results'][0]['margin'] or 0), r['code']))
    return {'year': latest_year, 'years': years, 'rows': rows,
            'counts': {tier: sum(r['tier'] == tier for r in rows) for tier in TIERS}}
