# -*- coding: utf-8 -*-
"""一句話輸入訓練：把「臥推 60 公斤 5 組 8 下，引體向上 3 組 10 下」轉成結構化草稿。

分兩層：
1. parse_rules()：用規則解析常見寫法（不用 LLM、不耗額度、可離線）。
2. validate_llm_draft()：規則解析不了的句子交給 LLM 後，用同一套規則檢查 LLM 的輸出。

這裡只做純計算：不碰資料庫、不呼叫 LLM、不碰 HTTP，方便單獨測試。
結果只是「草稿」，由前端填進預計組數，使用者確認並逐組按 ✓ 後才會寫入資料庫。
"""
import re
from difflib import SequenceMatcher

LB_TO_KG = 0.45359237
MAX_TEXT = 300          # 輸入長度上限
MAX_ITEMS = 20          # 最多幾個動作
MAX_SETS = 20           # 每個動作最多幾組
WEIGHT_RANGE = (0, 500)       # 解析時超過就標示「不合理」，使用者可自行修改
REPS_RANGE = (1, 100)

# ------------------------------------------------------------------ 中文數字
_CN_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '兩': 2, '两': 2, '三': 3, '四': 4,
              '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
_CN_NUM = '[零〇一二兩两三四五六七八九十百]+'
_UNITS = r'(?:公斤|kg|磅|lbs?|組|组|下|次|reps?)'


def _cn_to_int(text):
    """一百二十 → 120、十二 → 12、六十 → 60、兩 → 2；不支援就回 None。"""
    total, num = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch == '十':
            total += (num or 1) * 10
            num = 0
        elif ch == '百':
            total += (num or 1) * 100
            num = 0
        else:
            return None
    return total + num


def _normalize(text):
    """全形轉半形、中文數字（後面接單位時）轉阿拉伯數字、統一符號。"""
    text = text.translate(str.maketrans('０１２３４５６７８９．ｘＸ＊，；：', '0123456789.xx*,;:'))
    text = re.sub(f'({_CN_NUM})\\s*(?={_UNITS})',
                  lambda m: str(_cn_to_int(m.group(1))) if _cn_to_int(m.group(1)) is not None else m.group(1),
                  text, flags=re.I)
    return text


# ------------------------------------------------------------------ 規則
_NUM = r'(\d+(?:\.\d+)?)'
_RE_WEIGHT = re.compile(_NUM + r'\s*(公斤|kg|磅|lbs?)', re.I)
_RE_SETS_X_REPS = re.compile(r'(\d+)\s*[x×*]\s*(\d+)', re.I)            # 5x8：5 組 × 8 下
_RE_SETS = re.compile(r'(\d+)\s*[組组]')
_RE_REPS = re.compile(r'(\d+)\s*(?:下|次|reps?)', re.I)
_RE_FIRST_NUM = re.compile(r'\d')
_SPLIT = re.compile(r'[,;。\n、]|然後|還有|接著')
_FILLER = re.compile(r'^(?:今天|早上|晚上|下午|我|有|做了?|練了?|再|又|先|共|總共|另外|最後)+')


def _segments(text):
    return [s.strip() for s in _SPLIT.split(text) if s and s.strip()]


def _parse_segment(seg):
    """解析一段文字 → (動作名稱, [組...], 錯誤訊息)；完全看不懂就回 None。"""
    first = _RE_FIRST_NUM.search(seg)
    name = _FILLER.sub('', (seg[:first.start()] if first else seg)).strip(' :-')
    if not first:
        return None
    body = seg[first.start():]

    weight, unit = 0.0, 'kg'
    m = _RE_WEIGHT.search(body)
    if m:
        weight, unit = float(m.group(1)), m.group(2).lower()
        body = body[:m.start()] + ' ' + body[m.end():]

    sets = reps = None
    m = _RE_SETS_X_REPS.search(body)
    if m:
        sets, reps = int(m.group(1)), int(m.group(2))
        body = body[:m.start()] + ' ' + body[m.end():]
    else:
        ms, mr = _RE_SETS.search(body), _RE_REPS.search(body)
        if mr:
            reps = int(mr.group(1))
            sets = int(ms.group(1)) if ms else 1
            for found in sorted(filter(None, (ms, mr)), key=lambda x: -x.start()):
                body = body[:found.start()] + ' ' + body[found.end():]
    if reps is None:
        return None
    if re.search(r'\d', body):          # 還有沒用到的數字 → 寫法不確定，交給 LLM 或使用者，不要猜
        return None

    if unit in ('磅', 'lb', 'lbs'):
        weight = round(weight * LB_TO_KG, 1)            # 換算由程式負責
    weight = round(weight, 2)

    error = None
    if not WEIGHT_RANGE[0] <= weight <= WEIGHT_RANGE[1]:
        error = f'重量 {weight:g} kg 不合理'
    elif not REPS_RANGE[0] <= reps <= REPS_RANGE[1]:
        error = f'次數 {reps} 不合理'
    elif not 1 <= sets <= MAX_SETS:
        error = f'組數 {sets} 不合理（最多 {MAX_SETS} 組）'
    return name, [dict(weight_kg=weight, reps=reps) for _ in range(min(sets, MAX_SETS))], error


# ------------------------------------------------------------------ 動作名稱比對
def _key(text):
    return re.sub(r'\s+', '', text or '').lower()


def match_exercise(name, library, usage=None):
    """名稱 → (exercise_id 或 None, 候選 [id, ...])。

    library: [{'id', 'name'}, ...]；usage: {exercise_id: 最近使用次數}，用來排序候選。
    """
    usage = usage or {}
    key = _key(name)
    if not key:
        return None, []
    by_key = {_key(e['name']): e for e in library}
    if key in by_key:                                   # 完全相同
        return by_key[key]['id'], []

    contained = [e for e in library if _key(e['name']) in key]          # 「槓鈴臥推做了」含有「槓鈴臥推」
    if contained:
        best = max(contained, key=lambda e: len(_key(e['name'])))
        return best['id'], []

    def rank(e):
        return (-usage.get(e['id'], 0), -SequenceMatcher(None, key, _key(e['name'])).ratio(), len(e['name']))

    partial = [e for e in library if key in _key(e['name'])]            # 「臥推」→ 槓鈴臥推、啞鈴臥推…
    if len(partial) == 1:
        return partial[0]['id'], []
    if partial:
        return None, [e['id'] for e in sorted(partial, key=rank)[:3]]

    similar = [e for e in library if SequenceMatcher(None, key, _key(e['name'])).ratio() >= 0.5]
    return None, [e['id'] for e in sorted(similar, key=rank)[:3]]


# ------------------------------------------------------------------ 對外函式
def parse_rules(text, library, usage=None):
    """用規則解析整句話。

    回傳 {items: [{input_text, exercise_id, candidates, sets, error}], unparsed: [文字, ...]}。
    沒寫動作名稱的片段（例如金字塔組「110 公斤 3 下」）接續上一個動作。
    """
    items, unparsed = [], []
    for seg in _segments(_normalize(text[:MAX_TEXT])):
        result = _parse_segment(seg)
        if result is None:
            unparsed.append(seg)
            continue
        name, sets, error = result
        if not name and items:                          # 接續上一個動作
            items[-1]['sets'].extend(sets)
            items[-1]['sets'] = items[-1]['sets'][:MAX_SETS]
            items[-1]['error'] = items[-1]['error'] or error
            continue
        if not name:
            unparsed.append(seg)
            continue
        exercise_id, candidates = match_exercise(name, library, usage)
        items.append(dict(input_text=name[:50], exercise_id=exercise_id, candidates=candidates,
                          sets=sets, error=error))
        if len(items) >= MAX_ITEMS:
            break
    return dict(items=items, unparsed=unparsed)


def validate_llm_draft(raw, library, usage=None):
    """檢查 LLM 回傳的草稿（格式見 prompts.PARSE_SYSTEM_PROMPT），不合格的部分丟掉或標記錯誤。

    原則：不信任 LLM。動作只能是動作庫裡的；數值重新檢查；磅轉公斤與展開組數由程式負責。
    """
    if not isinstance(raw, dict):
        return dict(items=[], unparsed=['（無法解析）'])
    by_name = {_key(e['name']): e['id'] for e in library}
    items = []
    for item in (raw.get('items') or [])[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        input_text = str(item.get('input_text') or item.get('exercise_name') or '')[:50]
        exercise_id = by_name.get(_key(item.get('exercise_name')))
        candidates = [by_name[_key(c)] for c in (item.get('candidates') or []) if isinstance(c, str) and _key(c) in by_name][:3]
        if exercise_id is None and not candidates:      # LLM 給的名字不在動作庫 → 用規則再比對一次
            exercise_id, candidates = match_exercise(input_text, library, usage)
        sets, error = [], None
        for grp in (item.get('groups') or [])[:MAX_SETS]:
            try:
                weight = float(grp.get('weight') or 0)
                reps = int(grp.get('reps'))
                count = int(grp.get('count') or 1)
            except (TypeError, ValueError, AttributeError):
                error = '數值格式不正確'
                continue
            if str(grp.get('unit', 'kg')).lower() in ('lb', 'lbs', '磅'):
                weight = round(weight * LB_TO_KG, 1)
            if not WEIGHT_RANGE[0] <= weight <= WEIGHT_RANGE[1] or not REPS_RANGE[0] <= reps <= REPS_RANGE[1] \
                    or not 1 <= count <= MAX_SETS:
                error = '數值不合理，請檢查'
                continue
            sets += [dict(weight_kg=round(weight, 2), reps=reps)] * count
        if sets or error:
            items.append(dict(input_text=input_text, exercise_id=exercise_id, candidates=candidates,
                              sets=sets[:MAX_SETS], error=error))
    unparsed = raw.get('unparsed')
    unparsed = [str(unparsed)[:200]] if isinstance(unparsed, str) and unparsed.strip() else \
        [str(u)[:200] for u in unparsed] if isinstance(unparsed, list) else []
    return dict(items=items, unparsed=unparsed)
