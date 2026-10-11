"""依興趣或想從事的職業推薦學群與科系。

LLM 只負責從 18 學群中挑出相關的並說明理由（免費版輸出上限 800 tokens，
直接從數百個科系挑選時推理量太大，會在輸出 JSON 前就用完）；
學群包含哪些科系、哪些學校有開、能否通過篩選，都由程式依規則與落點資料計算。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from flask import current_app

from .placement import TIERS, is_special_track, load_data

MAX_INTEREST = 300
MAX_GROUPS = 3
# 先比對「學系」，避免「生物環境系統工程學系」被截成「生物環境系」
DEPARTMENT_PATTERNS = (r'^(.+?學系)', r'^(.+?學位學程)', r'^(.+?學程)', r'^(.+?學士班)', r'^(.+?系)')

# 18 學群：(學群, 科系名稱符合的關鍵字, 排除的關鍵字)。一個科系可屬於多個學群（如資管 = 資訊 + 管理）。
GROUP_RULES = (
    ('資訊', r'資訊工程|資訊科學|人工智慧|資料科學|大數據|資訊管理|資訊安全|智慧運算|智慧計算|數位媒體|醫療資訊|醫學資訊'
             r'|資訊電機|電機資訊|資訊經營|統計資訊|經營資訊|工業與資訊|資訊傳播|晶片設計|智慧創意|智慧媒體', None),
    ('工程', r'工程|工學院|機械|機電|電機|半導體|光電|材料|航太|航空|造船|船舶|商船|輪機|自動控制|通訊|動力|能源|精密系統'
             r'|紡織|纖維|晶片', r'財務工程'),
    ('數理化', r'數學|物理學系|應用物理|光電物理|電子物理|化學系|化學學系|應用化學|統計|理學院|原子科學|精算', r'農業化學|文化學系|管理學院'),
    ('醫藥衛生', r'醫學系|牙醫|中醫|藥學|護理|物理治療|職能治療|呼吸治療|醫學檢驗|醫學生物技術|放射|營養|公共衛生|口腔衛生'
                 r'|醫學影像|運動醫學|醫務管理|中國藥學|藥用|化粧品|香粧品|健康|醫學科學', r'獸醫'),
    ('生命科學', r'生命科學|生物科技|生化科技|微生物|生物醫學|生醫|生物技術|海洋生物', None),
    ('生物資源', r'農藝|園藝|森林|植物病理|昆蟲|動物科學|畜產|獸醫|農業|農企業|水產|漁業|土壤|水土保持|食品|生物環境系統'
                 r'|生物產業|生物機電', None),
    ('地球與環境', r'地球科學|地質|大氣|地理|環境|永續|生態|太空科學|海洋工程|河海|水利|水資源|測量', None),
    ('建築與設計', r'建築|設計|景觀|都市計|室內|地景|織品服裝', r'晶片設計|精密系統設計|未來設計'),
    ('藝術', r'戲劇|藝術', None),
    ('社會與心理', r'心理|社會學|社會工作|社會福利|社會科學|兒童|家庭|人類學|民族學|宗教|諮商|輔導|勞動|人力資源|社區', None),
    ('大眾傳播', r'傳播|新聞|廣告|圖書資訊|圖書館', None),
    ('外語', r'外國語文|外語|英國語文|英文學|英美|英語|歐洲語文|歐美語文|日本語|德國文化|德語|法國語文|西班牙|義大利|斯拉夫'
             r'|土耳其|阿拉伯|韓國語文|東南亞語文|國際溝通', r'全英語'),
    ('文史哲', r'中國文學|國文|台灣文學|臺灣語文|歷史|哲學|華語文|文學院|人文|宗教|天主教|客家語文|東亞', None),
    ('教育', r'教育|幼兒|教學|學習科學|學習科技', r'宗教'),
    ('法政', r'法律|法政|政治|公共行政|行政管理|外交|國際關係|地政|土地|政府|公民', None),
    ('管理', r'管理|企業|行銷|商務|商學|工商|經營|航運|運輸|物流|交通', r'諮商'),
    ('財經', r'經濟|財務|金融|財政|財稅|會計|保險|精算|貿易|國際企業', None),
    ('遊憩與運動', r'運動|體育|觀光|餐旅|遊憩', None),
)
GROUPS = tuple(name for name, _, _ in GROUP_RULES)
# 不分系／跨領域學士班不屬於特定學群
UNGROUPED = re.compile(r'不分系|跨領域|創新國際學院')


def department(name):
    """校系名稱去掉分組與身分別：'經濟學系A組' / '醫學系(公費生)' -> 'XX學系'。"""
    for pattern in DEPARTMENT_PATTERNS:
        match = re.match(pattern, name)
        if match:
            return match.group(1)
    return name


@lru_cache(maxsize=1)
def departments():
    """最新年度的 {科系: [(校名, 校系名稱, 性別), ...]}，不含特定身分管道。"""
    _, history, years = load_data()
    result = {}
    for (school, name, gender), by_year in history.items():
        if years[0] in by_year and not is_special_track(name):
            result.setdefault(department(name), []).append((school, name, gender))
    return result


def groups_of(name):
    return [group for group, include, exclude in GROUP_RULES
            if re.search(include, name) and not (exclude and re.search(exclude, name))]


@lru_cache(maxsize=1)
def group_departments():
    """{學群: [科系, ...]}，科系依開設校數多到少排序。"""
    result = {group: [] for group in GROUPS}
    for name, schools in sorted(departments().items(), key=lambda item: (-len(item[1]), item[0])):
        for group in groups_of(name):
            result[group].append(name)
    return result


def parse_interest(form):
    interest = str(form.get('interest', '') or '').strip()
    if len(interest) < 2:
        raise ValueError('請描述你的興趣或想從事的職業。')
    if len(interest) > MAX_INTEREST:
        raise ValueError(f'興趣描述請在 {MAX_INTEREST} 字以內。')
    return interest


def generate_interest(form):
    from personal_ai.llm_provider import get_llm
    from personal_ai.response_style import STYLE

    interest = parse_interest(form)
    # 每個學群附幾個開設最多的科系當例子，幫模型理解學群範圍；整份清單維持在幾百 tokens
    groups = {group: '、'.join(names[:4]) for group, names in group_departments().items()}
    model = get_llm(current_app.config)
    data = model.complete_json(
        '你是台灣大學申請入學的升學顧問。依學生描述的興趣或想從事的職業，從「學群」中挑出最相關的學群。'
        '學群名稱必須照抄清單的鍵名。只說明學群學什麼、和興趣或職業的關聯，'
        '不可評論錄取機會、分數或學校排名。' + STYLE +
        '回答要具體、簡短。只回有效 JSON：' + json.dumps({
            'summary': '整體說明興趣適合的方向，80 字內',
            'groups': [{'group': '學群名稱', 'why': '和興趣的關聯，30 字內', 'career': '常見出路，20 字內'}],
            'explore': '建議再了解或確認的事，50 字內'}, ensure_ascii=False) +
        f' groups 依相關程度排序，最多 {MAX_GROUPS} 個。',
        json.dumps({'興趣或職業': interest, '學群': groups}, ensure_ascii=False))
    if not isinstance(data, dict) or not isinstance(data.get('summary'), str) or not data['summary'].strip():
        raise ValueError('模型回傳的推薦格式不正確，請再試一次。')

    picked = []
    for item in data.get('groups') or []:
        # 只保留真的存在的學群，避免模型自己編
        if not isinstance(item, dict) or not isinstance(item.get('group'), str):
            continue
        name = item['group'].strip().removesuffix('學群')
        if name in GROUPS and name not in {g['group'] for g in picked}:
            picked.append({'group': name, 'why': str(item.get('why') or '').strip()[:120],
                           'career': str(item.get('career') or '').strip()[:100]})
    if not picked:
        raise ValueError('找不到符合描述的學群，請換個說法或描述得更具體一些。')
    explore = data.get('explore') if isinstance(data.get('explore'), str) else ''
    return {'interest': interest, 'summary': data['summary'].strip()[:500],
            'groups': picked[:MAX_GROUPS], 'explore': explore.strip()[:200]}


def attach_schools(recommendation, result=None):
    """把推薦學群展開成科系與各校校系。

    有落點結果時附上分級，只列出安全／適中／夢幻的校系，科系依最好的分級排序；
    其餘科系只計數，避免學群底下幾十個科系把頁面塞滿。
    """
    rows = {(r['school'], r['program'], r['gender']): r for r in result['rows']} if result else {}
    order = {tier: i for i, tier in enumerate(TIERS)}
    reachable = {'安全', '適中', '夢幻'}
    groups = []
    for group in recommendation.get('groups', []):
        majors, hidden = [], 0
        for name in group_departments().get(group['group'], []):
            schools = []
            for key in departments()[name]:
                row = rows.get(key)
                if result and (not row or row['tier'] not in reachable):
                    continue  # 被性別等條件排除，或目前落點不建議
                schools.append({'school': key[0], 'program': key[1], 'gender': key[2],
                                'tier': row['tier'] if row else None})
            if not schools:
                hidden += 1
                continue
            if result:
                schools.sort(key=lambda s: order[s['tier']])
            majors.append({'department': name, 'schools': schools})
        if result:
            majors.sort(key=lambda m: order[m['schools'][0]['tier']])  # sort 穩定：同分級維持開設校數排序
        groups.append(dict(group, majors=majors, hidden=hidden))
    return dict(recommendation, groups=groups)
