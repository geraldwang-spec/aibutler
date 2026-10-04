# -*- coding: utf-8 -*-
"""AI 分析說明：把 analysis.build_report() 的結果整理成給 LLM 的摘要，並檢查 LLM 的輸出。

原則：數字由程式計算，LLM 只負責「說明」。所以：
1. 交給 LLM 的只有程式算好的摘要（不給原始的每一組資料）。
2. LLM 在「摘要、優點、缺點」裡寫到的數字，必須能在摘要裡找到；找不到的那一句直接拿掉（不顯示編造的數字）。
3. 「建議」可以提出新的數字（例如「每週增加 2 組」），但只允許合理範圍內的小數字。

全部是純函式：不碰資料庫、不呼叫 LLM。
"""
import hashlib
import json
import re

MAX_ITEMS = 3                 # 優點／缺點／建議各最多幾項
MAX_TEXT = 120                # 每一項最多幾個字
SUGGESTION_MAX_NUMBER = 20    # 建議裡允許的新數字上限（組數、次數、天數這類）
_NUMBER = re.compile(r'\d+(?:\.\d+)?')


def llm_input(report, profile=None):
    """給 LLM 的摘要：只保留說明需要的欄位，數字都已經由程式算好。"""
    keep_progress = [dict(name=p['name'], muscle=p['muscle'], sets=p['sets'],
                          metric='估計1RM(kg)' if p['metric'] == 'e1rm' else '單組最多次數',
                          value=p['value'], previous=p['prev_value'], change_pct=p['change_pct'])
                     for p in report['progress'][:8]]
    return dict(
        period='週' if report['period'] == 'week' else '月',
        range=f"{report['start']}～{report['end']}",
        in_progress=report['in_progress'],
        this_period=report['summary'], previous_period=report['previous'],
        change_pct=report['change'],
        sets_by_muscle={m: v['sets'] for m, v in report['by_muscle'].items()},
        balance=report['balance'],
        days_since_trained=report['days_since'],
        progress=keep_progress,
        weight=report['weight'],
        rule_findings=[f['text'] for f in report['findings']],
        profile={k: v for k, v in (profile or {}).items() if v not in (None, '')},
    )


def input_hash(data):
    """摘要的雜湊值：資料沒變就沿用之前產生的 AI 說明，不重複呼叫。"""
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def _variants(value):
    """一個數字可能被寫成的樣子：68.4、68、68.40 → 都正規化成字串集合。"""
    out = set()
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return out
    for x in (number, round(number, 1), round(number)):
        out.add(f'{x:g}')
    return out


def allowed_numbers(data):
    """摘要裡出現過的所有數字（包含日期、名稱裡的數字），作為檢查的白名單。"""
    allowed = set()
    for token in _NUMBER.findall(json.dumps(data, ensure_ascii=False)):
        allowed |= _variants(token)
    # 千分位寫法（例如 1,600）在檢查前會先去掉逗號，所以不用另外處理
    return allowed


def numbers_in(text):
    return [f'{float(n):g}' for n in _NUMBER.findall((text or '').replace(',', ''))]


def check_output(raw, data):
    """整理並檢查 LLM 的 JSON 輸出。

    回傳 {summary, strengths, weaknesses, suggestions, removed}：
    removed 是被拿掉的句子數（裡面有摘要中找不到的數字，或格式不對）。
    """
    if not isinstance(raw, dict):
        raw = {}
    allowed = allowed_numbers(data)
    removed = 0

    def clean_list(value, facts):
        nonlocal removed
        items = value if isinstance(value, list) else []
        result = []
        for item in items:
            text = ' '.join(str(item).split())[:MAX_TEXT] if isinstance(item, (str, int, float)) else ''
            if not text:
                removed += 1
                continue
            numbers = numbers_in(text)
            if facts and any(n not in allowed for n in numbers):
                removed += 1                          # 有編造（或算錯）的數字 → 不顯示這一句
                continue
            if not facts and any(n not in allowed and float(n) > SUGGESTION_MAX_NUMBER for n in numbers):
                removed += 1                          # 建議裡不合理的大數字
                continue
            result.append(text)
        if len(result) > MAX_ITEMS:
            removed += len(result) - MAX_ITEMS
        return result[:MAX_ITEMS]

    summary = raw.get('summary')
    summary = ' '.join(str(summary).split())[:MAX_TEXT * 2] if isinstance(summary, str) else ''
    if summary and any(n not in allowed for n in numbers_in(summary)):
        summary, removed = '', removed + 1
    return dict(summary=summary,
                strengths=clean_list(raw.get('strengths'), facts=True),
                weaknesses=clean_list(raw.get('weaknesses'), facts=True),
                suggestions=clean_list(raw.get('suggestions'), facts=False),
                removed=removed)
