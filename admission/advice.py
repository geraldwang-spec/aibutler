"""把落點結果交給 LLM 解讀。

LLM 只負責說明與建議：它拿到的是程式算好的落點摘要，不能自行判斷能不能上，
回答中引用的校系編號也會逐一檢查必須來自摘要。
"""
from __future__ import annotations

import json
from collections import Counter

from flask import current_app

from .placement import parse_scores, place

SHOWN = {'安全': 5, '適中': 8, '夢幻': 8}


def _brief(row, ref):
    latest = row['results'][0]
    return {'ref': ref, '校系': f"{row['school']} {row['program']}", '分級': row['tier'],
            '今年差距': latest['margin'], '卡關': latest['reason'] or None,
            '歷年': {str(r['year']): r['margin'] if r['status'] != 'check_fail' else '未達檢定' for r in row['results']}}


def build_summary(form):
    scores, listening, gender = parse_scores(form)
    result = place(scores, listening, gender, include_special=form.get('special') == '1')
    picked = []
    for tier, limit in SHOWN.items():
        picked += [row for row in result['rows'] if row['tier'] == tier][:limit]
    # 夢幻校系最常卡在哪一個篩選項目，是「下一步加強哪科」最直接的依據
    bottlenecks = Counter(row['results'][0]['reason'].split('最低')[0]
                          for row in result['rows'] if row['tier'] == '夢幻' and row['results'][0]['reason'])
    summary = {'學年度': result['year'], '級分': scores, '英聽': listening or '未考',
               '各分級校系數': result['counts'],
               '夢幻校系常卡的篩選項目': dict(bottlenecks.most_common(5)),
               '校系': [_brief(row, i + 1) for i, row in enumerate(picked)]}
    return summary


def generate_advice(form):
    from personal_ai.llm_provider import get_llm
    from personal_ai.prompt_budget import bounded_json
    from personal_ai.response_style import STYLE

    summary = build_summary(form)
    refs = {item['ref']: item['校系'] for item in summary['校系']}
    model = get_llm(current_app.config)
    data = model.complete_json(
        '你是台灣大學申請入學的升學顧問。資料是程式依甄選會歷年「個人申請第一階段篩選結果」算出的落點，'
        '「今年差距」是最緊的篩選項目高出（正）或低於（負）最低通過級分的級分數。'
        '只能根據這份資料說明，不可自行判斷能否錄取、不可補充資料外的錄取分數、名額或校系資訊，'
        '也不可評論第二階段書審面試的結果。引用校系時只能用資料中的 ref 編號。' + STYLE +
        '回答要具體、簡短。只回有效 JSON：' + json.dumps({
            'summary': '整體落點說明，150 字內',
            'picks': [{'ref': 1, 'why': '推薦理由，40 字內'}],
            'improve': [{'subject': '科目或科目組合', 'advice': '加強建議，40 字內'}],
            'caution': '提醒，60 字內'}, ensure_ascii=False) +
        ' picks 最多 4 個、improve 最多 3 個。',
        bounded_json(summary))
    if not isinstance(data, dict) or not isinstance(data.get('summary'), str) or not data['summary'].strip():
        raise ValueError('模型回傳的解讀格式不正確，請再試一次。')

    picks = []
    for pick in data.get('picks') or []:
        # 只保留真的出現在摘要裡的校系，避免模型自己編出校系
        if isinstance(pick, dict) and type(pick.get('ref')) is int and pick['ref'] in refs and isinstance(pick.get('why'), str):
            picks.append({'program': refs[pick['ref']], 'why': pick['why'].strip()[:120]})
    improve = [{'subject': str(item['subject'])[:30], 'advice': str(item['advice'])[:120]}
               for item in data.get('improve') or []
               if isinstance(item, dict) and item.get('subject') and isinstance(item.get('advice'), str)]
    caution = data.get('caution') if isinstance(data.get('caution'), str) else ''
    return {'summary': data['summary'].strip()[:600], 'picks': picks[:4], 'improve': improve[:3],
            'caution': caution.strip()[:200]}
