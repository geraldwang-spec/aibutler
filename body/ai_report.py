# -*- coding: utf-8 -*-
"""AI 分析說明：把 TrainingAnalysis.build() 的結果整理成給 LLM 的摘要，並檢查 LLM 的輸出。

    ai = AiReport(report, profile)
    ai.data          給 LLM 的摘要（只有程式算好的數字）
    ai.hash          摘要的雜湊值：資料沒變就沿用存好的說明，不重複呼叫
    ai.check(raw)    整理並檢查 LLM 的 JSON 輸出

原則：數字由程式計算，LLM 只負責「說明」。所以：
1. 交給 LLM 的只有程式算好的摘要（不給原始的每一組資料）。
2. LLM 在「摘要、優點、缺點」裡寫到的數字，必須能在摘要裡找到；找不到的那一句直接拿掉（不顯示編造的數字）。
3. 「建議」可以提出新的數字（例如「每週增加 2 組」），但只允許合理範圍內的小數字。

全部是純計算：不碰資料庫、不呼叫 LLM。
"""
import hashlib
import json
import re


class AiReport:
    MAX_ITEMS = 3                 # 優點／缺點／建議各最多幾項
    MAX_TEXT = 120                # 每一項最多幾個字
    SUGGESTION_MAX_NUMBER = 20    # 建議裡允許的新數字上限（組數、次數、天數這類）
    _NUMBER = re.compile(r'\d+(?:\.\d+)?')

    def __init__(self, report, profile=None):
        self.report = report
        self.data = self.llm_input(report, profile)
        self._allowed = None

    # ------------------------------------------------------------------ 給 LLM 的摘要
    @staticmethod
    def llm_input(report, profile=None):
        """只保留說明需要的欄位，數字都已經由程式算好；個人資料空白的欄位不送。"""
        progress = [dict(name=p['name'], muscle=p['muscle'], sets=p['sets'],
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
            progress=progress,
            weight=report['weight'],
            rule_findings=[f['text'] for f in report['findings']],
            profile={k: v for k, v in (profile or {}).items() if v not in (None, '')},
        )

    @property
    def has_data(self):
        return self.report['summary']['sessions'] > 0

    @property
    def hash(self):
        return hashlib.sha256(json.dumps(self.data, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]

    # ------------------------------------------------------------------ 數字檢查
    @staticmethod
    def variants(value):
        """一個數字可能被寫成的樣子：68.4、68、68.40 → 都正規化成字串集合（不分正負號）。"""
        try:
            number = abs(float(value))
        except (TypeError, ValueError):
            return set()
        return {f'{x:g}' for x in (number, round(number, 1), round(number))}

    @classmethod
    def numbers_in(cls, text):
        """文字裡的數字（先去掉千分位逗號）。"""
        return [f'{float(n):g}' for n in cls._NUMBER.findall((text or '').replace(',', ''))]

    @property
    def allowed_numbers(self):
        """摘要裡出現過的所有數字（包含日期、名稱裡的數字），作為檢查的白名單。"""
        if self._allowed is None:
            self._allowed = set()
            for token in self._NUMBER.findall(json.dumps(self.data, ensure_ascii=False)):
                self._allowed |= self.variants(token)
        return self._allowed

    def _clean_list(self, value, facts):
        """回傳 (通過檢查的句子, 拿掉的句數)。facts=True 時數字必須在摘要裡。"""
        kept, removed = [], 0
        for item in value if isinstance(value, list) else []:
            text = ' '.join(str(item).split())[:self.MAX_TEXT] if isinstance(item, (str, int, float)) else ''
            numbers = self.numbers_in(text)
            if not text:
                removed += 1
            elif facts and any(n not in self.allowed_numbers for n in numbers):
                removed += 1                          # 有編造（或算錯）的數字 → 不顯示這一句
            elif not facts and any(n not in self.allowed_numbers and float(n) > self.SUGGESTION_MAX_NUMBER
                                   for n in numbers):
                removed += 1                          # 建議裡不合理的大數字
            else:
                kept.append(text)
        removed += max(0, len(kept) - self.MAX_ITEMS)
        return kept[:self.MAX_ITEMS], removed

    def check(self, raw):
        """整理並檢查 LLM 的 JSON 輸出。

        回傳 {summary, strengths, weaknesses, suggestions, removed}；
        removed 是被拿掉的句子數（裡面有摘要中找不到的數字，或格式不對）。
        """
        raw = raw if isinstance(raw, dict) else {}
        summary = raw.get('summary')
        summary = ' '.join(summary.split())[:self.MAX_TEXT * 2] if isinstance(summary, str) else ''
        removed = 0
        if summary and any(n not in self.allowed_numbers for n in self.numbers_in(summary)):
            summary, removed = '', 1
        result = dict(summary=summary)
        for name, facts in (('strengths', True), ('weaknesses', True), ('suggestions', False)):
            result[name], count = self._clean_list(raw.get(name), facts)
            removed += count
        result['removed'] = removed
        return result
