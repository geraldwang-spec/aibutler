# -*- coding: utf-8 -*-
"""建議課表：程式排出骨架與重量，LLM 只從候選動作中挑選並說明理由。

    plan = WorkoutPlan(day, profile, days_since, weekly_sets, library, usage, last_sessions, passages)
    plan.skeleton        程式排好的骨架：分化方式、今天練哪幾個部位、每個位置練什麼部位、組數與次數
    plan.prompt_data     送給 LLM 的內容（骨架＋每個位置的候選動作＋教練文章段落）
    plan.hash            骨架的雜湊值：資料沒變就沿用已存的課表
    plan.check(raw)      檢查 LLM 的選擇；不合格的位置改用程式的預設選擇
    plan.check(None)     沒有 LLM 時，全部用程式的預設選擇

分工（與 AiReport 相同的原則）：
- 程式決定：分化方式、今天輪到哪一天、幾個動作、每個動作練哪個部位、組數、次數、重量。
- LLM 決定：每個位置從「候選清單」挑哪個動作、一句理由、可引用教練文章 [編號]。
- LLM 選了清單外的動作、重複的動作、或理由裡有資料中沒有的數字 → 該位置改用程式的選擇或拿掉理由。

恢復與輪換（程式決定，LLM 只能在結果裡挑）：
- 距離上次不到 RECENT_DAYS 天（昨天、前天）做過的動作不排；胸背腿肩這段期間練過也不排，名額給其他部位。
- 今天沒有任何可以排的大肌群 → 建議休息（不呼叫 LLM）。
- 連續做超過 ROTATE_DAYS 天的動作 → 候選裡把「同部位、動作類型相同」的其他動作排到前面（可以換，但不強迫）。

全部是純計算：不碰資料庫、不呼叫 LLM、不碰 HTTP。
輸入資料的欄位：
    profile        {goal_type, workout_days_per_week, minutes_per_session}（可能是空的）
    days_since     {部位: 天數或 None}（TrainingAnalysis.days_since_trained）
    weekly_sets    {部位: 最近 7 天的組數}
    library        [{id, name, muscle_group, equipment, is_cardio}]
    usage          {exercise_id: 最近 90 天做過幾組}
    last_sessions  {exercise_id: [{set_no, weight_kg, reps}]}（最近一次訓練的各組）
    exercise_dates {exercise_id: ['YYYY-MM-DD', ...]}（做過這個動作的日期，判斷恢復與連續做多久）
"""
import hashlib
import json
from datetime import date

from .ai_report import AiReport
from .analysis import TrainingAnalysis


class WorkoutPlan:
    # 分化方式：(名稱, [(這一天的名稱, 部位, 手臂只放推或拉)])
    SPLITS = {
        'full': ('全身', [('全身', ('胸', '背', '腿', '肩'), None)]),
        'upper_lower': ('上下半身', [('上半身', ('胸', '背', '肩', '手臂'), None),
                                     ('下半身', ('腿', '核心'), None)]),
        'ppl': ('推拉腿', [('推', ('胸', '肩', '手臂'), 'push'),
                           ('拉', ('背', '手臂'), 'pull'),
                           ('腿', ('腿', '核心'), None)]),
    }
    MINOR = ('手臂', '核心')            # 小肌群每天最多 1 個動作
    REPS_BY_GOAL = {'增肌': 10, '減脂': 12, '體能': 12, '維持': 10}
    SETS_PER_EXERCISE = 3
    MINUTES_PER_EXERCISE = 12           # 一個動作 3 組＋休息約 12 分鐘
    MAX_CANDIDATES = 6                  # 每個位置給 LLM 幾個候選
    MAX_REASON = 60
    NEVER = 99                          # 沒練過的部位當作休息很久
    RECENT_DAYS = 3                     # 距離上次不到 3 天（昨天、前天）做過的動作／大肌群不排，約 72 小時恢復
    ROTATE_DAYS = 90                    # 連續做超過 90 天（約 3 個月）就建議換類似動作
    STREAK_GAP_DAYS = 28                # 兩次之間超過 28 天沒做，就算中斷，重新計算連續天數
    ACTIVE_DAYS = 30                    # 最近 30 天內沒做過的動作，不算「正在連續做」
    # 動作類型關鍵字：同部位、名稱裡有相同關鍵字的動作視為「類似動作」
    MOVEMENTS = ('臥推', '胸推', '飛鳥', '夾胸', '撐體', '伏地挺身', '划船', '下拉', '引體', '硬舉', '背部伸展',
                 '深蹲', '蹲', '臀推', '弓步', '腿推', '腿彎', '腿伸', '腿屈', '提踵', '登階', '肩推', '平舉',
                 '聳肩', '臉拉', '直立划船', '彎舉', '下壓', '三頭', '捲腹', '舉腿', '抬腿', '轉體')

    def __init__(self, day, profile, days_since, weekly_sets, library, usage, last_sessions, passages=None,
                 exercise_dates=None):
        self.day = day
        self.exercise_dates = {k: sorted({date.fromisoformat(str(d)[:10]) for d in v})
                               for k, v in (exercise_dates or {}).items()}
        self.profile = profile or {}
        self.days_since, self.weekly_sets = days_since, weekly_sets
        self.library = [e for e in library if not e.get('is_cardio')]   # 這個頁面只記重量×次數
        self.usage, self.last = usage, last_sessions
        self.passages = list(passages or [])
        self.skeleton = self._build()

    # ------------------------------------------------------------------ 骨架（程式決定）
    def split_key(self):
        days = int(self.profile.get('workout_days_per_week') or 3)
        return 'full' if days <= 3 else 'upper_lower' if days == 4 else 'ppl'

    def _rested(self, muscles):
        """這一天的部位裡，休息最少的那個休息了幾天（越大代表越該練）。"""
        majors = [m for m in muscles if m not in self.MINOR] or list(muscles)
        return min(self.NEVER if self.days_since.get(m) is None else self.days_since[m] for m in majors)

    def _deficit(self, muscle):
        """離每週建議組數還差多少；小肌群不算。"""
        if muscle in self.MINOR:
            return -1
        return TrainingAnalysis.WEEKLY_SETS_LOW - int(self.weekly_sets.get(muscle) or 0)

    def _build(self):
        key = self.split_key()
        split_name, days = self.SPLITS[key]
        # 輪到哪一天：休息最久的那一天（同分取前面的）
        day_name, muscles, arm_side = max(days, key=lambda d: self._rested(d[1]))
        # 三天內練過的大肌群不排（小肌群只排除動作，見 _candidates_for）
        skipped = [m for m in muscles if m not in self.MINOR and self._muscle_recent(m)]
        muscles = tuple(m for m in muscles if m not in skipped)
        minutes = int(self.profile.get('minutes_per_session') or 60)
        count = max(3, min(6, round(minutes / self.MINUTES_PER_EXERCISE)))
        reps = self.REPS_BY_GOAL.get(self.profile.get('goal_type'), 10)

        # 每個部位先放 1 個，多的位置給「離建議組數差最多」的大肌群
        available = [m for m in muscles if self._candidates_for(m, arm_side)]
        if not any(m not in self.MINOR for m in available):
            available = []                                  # 沒有大肌群可以練 → 建議休息，不只排手臂、核心
        order = sorted(available, key=lambda m: -self._deficit(m))
        slots_by_muscle = {m: 0 for m in order}
        for m in order[:count]:
            slots_by_muscle[m] = 1
        extra = count - sum(slots_by_muscle.values())
        majors = [m for m in order if m not in self.MINOR]
        i = 0
        while extra > 0 and majors:
            m = majors[i % len(majors)]
            if slots_by_muscle[m] < len(self._candidates_for(m, arm_side)):
                slots_by_muscle[m] += 1
                extra -= 1
            elif all(slots_by_muscle[x] >= len(self._candidates_for(x, arm_side)) for x in majors):
                break                                       # 候選動作不夠多，就少排幾個
            i += 1

        slots, n = [], 0
        for m in muscles:                                   # 依分化定義的順序排（大肌群在前）
            for _ in range(slots_by_muscle.get(m, 0)):
                n += 1
                slots.append(dict(slot=n, muscle=m, sets=self.SETS_PER_EXERCISE, reps=reps,
                                  why=self._why(m)))
        skipped_text = [f'{m}在 {self.days_since[m]} 天前練過，今天先讓它恢復' for m in skipped]
        return dict(date=self.day.isoformat(), split=key, split_name=split_name, day_name=day_name,
                    arm_side=arm_side, minutes=minutes, goal=self.profile.get('goal_type') or '', slots=slots,
                    skipped=skipped_text, rest=not slots,
                    rest_reason=(f'主要部位在 {self.RECENT_DAYS} 天內都練過，今天建議休息或做輕度活動。'
                                 if not slots else ''))

    def _muscle_recent(self, muscle):
        days = self.days_since.get(muscle)
        return days is not None and days < self.RECENT_DAYS

    def _why(self, muscle):
        """這個部位為什麼排進來（給 LLM 和畫面參考；數字都來自資料）。"""
        days = self.days_since.get(muscle)
        sets = int(self.weekly_sets.get(muscle) or 0)
        if days is None:
            return f'{muscle}還沒有訓練紀錄'
        text = f'{muscle}已 {days} 天沒練'
        if muscle not in self.MINOR and sets < TrainingAnalysis.WEEKLY_SETS_LOW:
            text += f'，最近 7 天 {sets} 組'
        return text

    # ------------------------------------------------------------------ 動作的恢復與輪換
    def days_since_done(self, exercise_id):
        dates = self.exercise_dates.get(exercise_id)
        return (self.day - dates[-1]).days if dates else None

    def is_recent(self, exercise):
        days = self.days_since_done(exercise['id'])
        return days is not None and days < self.RECENT_DAYS

    def streak_days(self, exercise_id):
        """這個動作「連續」做了幾天：從最近一次往回找，兩次間隔都不超過 STREAK_GAP_DAYS 就算連續。

        最近 ACTIVE_DAYS 天內沒做過就是 0（已經沒在做了）。
        """
        dates = self.exercise_dates.get(exercise_id) or []
        if not dates or (self.day - dates[-1]).days > self.ACTIVE_DAYS:
            return 0
        start = dates[-1]
        for d in reversed(dates[:-1]):
            if (start - d).days > self.STREAK_GAP_DAYS:
                break
            start = d
        return (self.day - start).days

    def is_long_running(self, exercise):
        return self.streak_days(exercise['id']) >= self.ROTATE_DAYS

    @classmethod
    def movement(cls, name):
        """動作名稱裡的動作類型關鍵字（取最長的那個，例如「直立划船」優先於「划船」）。"""
        found = [k for k in cls.MOVEMENTS if k in (name or '')]
        return max(found, key=len) if found else None

    @classmethod
    def similar(cls, a, b):
        if a['id'] == b['id'] or a['muscle_group'] != b['muscle_group']:
            return False
        ma, mb = cls.movement(a['name']), cls.movement(b['name'])
        return bool(ma and mb and (ma in mb or mb in ma))   # 「蹲」與「深蹲」也算類似

    def has_replacement(self, exercise):
        """連續做太久、而且動作庫裡有「沒有連續做太久」的類似動作可以換。沒有可換的就照常排。"""
        return self.is_long_running(exercise) and any(
            self.similar(exercise, e) and not self.is_long_running(e) and not self.is_recent(e) for e in self.library)

    def rotated_from(self, exercise):
        """這個動作是用來取代哪個「連續做太久」的動作；不是替換就回傳 None。"""
        if self.is_long_running(exercise):
            return None
        olds = [e for e in self.library if self.has_replacement(e) and self.similar(e, exercise)]
        return max(olds, key=lambda e: int(self.usage.get(e['id']) or 0)) if olds else None

    # ------------------------------------------------------------------ 候選動作與預設選擇
    def _candidates_for(self, muscle, arm_side):
        rows = [e for e in self.library if e['muscle_group'] == muscle and not self.is_recent(e)]
        if muscle == '手臂' and arm_side:
            rows = [e for e in rows if TrainingAnalysis.arm_side(e['name']) == arm_side]
        # 排序：替換「連續做太久」動作的類似動作 → 一般動作（常做的優先）→ 連續做太久的動作（仍可選）
        return sorted(rows, key=lambda e: (self.has_replacement(e), self.rotated_from(e) is None,
                                           -int(self.usage.get(e['id']) or 0)))

    def candidates(self, slot):
        return self._candidates_for(slot['muscle'], self.skeleton['arm_side'])[:self.MAX_CANDIDATES]

    def _default_pick(self, slot, taken, replaced=()):
        """程式的選擇：依候選順序；同一個舊動作已經被換過一次，就不再挑它的替代動作（避免整個部位都換掉）。"""
        free = [e for e in self.candidates(slot) if e['id'] not in taken]
        fresh = [e for e in free if not (self.rotated_from(e) and self.rotated_from(e)['id'] in replaced)]
        return (fresh or free or [None])[0]

    # ------------------------------------------------------------------ 重量（程式決定：雙重漸進）
    def sets_for(self, exercise, reps):
        """依最近一次的紀錄決定重量：上次最重的那幾組都做到目標次數 → 加重；否則維持。

        回傳 (各組 [{weight_kg, reps}], 依據說明)。沒有紀錄時重量留空，由使用者自己填。
        """
        n = self.SETS_PER_EXERCISE
        last = self.last.get(exercise['id']) or []
        if not last:
            return [dict(weight_kg=None, reps=reps)] * n, '沒有紀錄，請自己填重量'
        top = max(float(r['weight_kg'] or 0) for r in last)
        top_reps = [int(r['reps'] or 0) for r in last if float(r['weight_kg'] or 0) == top]
        done = '、'.join(str(x) for x in top_reps)
        if top == 0:                                         # 徒手：次數 +1
            best = max(top_reps)
            target = best + 1 if min(top_reps) >= reps else best
            return [dict(weight_kg=0, reps=target)] * n, f'上次徒手 {done} 下'
        if min(top_reps) >= reps:
            step = 2 if '啞鈴' in (exercise.get('equipment') or '') else 2.5
            weight = round((top + step) * 2) / 2              # 取到 0.5 kg
            return [dict(weight_kg=weight, reps=reps)] * n, f'上次 {top:g} kg 做到 {done} 下，加 {step:g} kg'
        return [dict(weight_kg=top, reps=reps)] * n, f'上次 {top:g} kg 做到 {done} 下，維持重量'

    # ------------------------------------------------------------------ 給 LLM 的內容
    @property
    def prompt_data(self):
        s = self.skeleton
        data = dict(
            date=s['date'], split=s['split_name'], today=s['day_name'], goal=s['goal'],
            slots=[dict(slot=x['slot'], muscle=x['muscle'], why=x['why'],
                        candidates=[self._candidate_info(e) for e in self.candidates(x)])
                   for x in s['slots']],
            rotate_after_days=self.ROTATE_DAYS)
        if self.passages:
            data['reference_passages'] = [dict(id=p['n'], title=p['title'], section=p.get('section') or '',
                                               text=p['text']) for p in self.passages]
        return data

    def _candidate_info(self, e):
        info = dict(name=e['name'], equipment=e.get('equipment') or '', recent_sets=int(self.usage.get(e['id']) or 0))
        if self.has_replacement(e):
            info['streak_days'] = self.streak_days(e['id'])     # 連續做超過 rotate_after_days 天，而且有類似動作可換
        old = self.rotated_from(e)
        if old:
            info['replaces'] = old['name']                     # 可以用來取代的那個動作
        return info

    @property
    def hash(self):
        """只看骨架與候選（不含教練文章）：有新的訓練紀錄、個人設定改變時才會變。"""
        base = dict(self.prompt_data)
        base.pop('reference_passages', None)
        return hashlib.sha256(json.dumps(base, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]

    # ------------------------------------------------------------------ 檢查 LLM 的選擇
    def _allowed_numbers(self):
        allowed = set()
        for token in AiReport._NUMBER.findall(json.dumps(self.prompt_data, ensure_ascii=False)):
            allowed |= AiReport.variants(token)
        return allowed

    def _clean_text(self, text, allowed, limit):
        """理由／總結：太長截斷；出處編號不存在、或有資料裡沒有的數字 → 整句不用。"""
        if not isinstance(text, str):
            return ''
        text = ' '.join(text.split())[:limit]
        cited = [int(n) for n in AiReport._CITATION.findall(text)]
        if any(n not in {p['n'] for p in self.passages} for n in cited):
            return ''
        plain = AiReport._CITATION.sub('', text)
        return text if all(n in allowed for n in AiReport.numbers_in(plain)) else ''

    def check(self, raw):
        """回傳 {skeleton, items, summary, sources, fallback}；fallback 是改用程式選擇的位置數。

        raw 是 None（沒有 LLM）時全部用程式的預設選擇。
        """
        raw = raw if isinstance(raw, dict) else {}
        if self.skeleton['rest']:
            return dict(skeleton=self.skeleton, items=[], summary='', sources=[], fallback=0)
        picks = {}
        for p in raw.get('picks') if isinstance(raw.get('picks'), list) else []:
            if isinstance(p, dict) and isinstance(p.get('slot'), int):
                picks.setdefault(p['slot'], p)              # 同一個位置只看第一個
        allowed = self._allowed_numbers()
        items, taken, fallback, replaced = [], set(), 0, set()
        for slot in self.skeleton['slots']:
            names = {e['name']: e for e in self.candidates(slot)}
            pick = picks.get(slot['slot'], {})
            exercise = names.get(pick.get('exercise'))
            reason, from_ai = '', bool(exercise and exercise['id'] not in taken)
            if from_ai:
                reason = self._clean_text(pick.get('reason'), allowed, self.MAX_REASON)
            else:
                exercise = self._default_pick(slot, taken, replaced)   # 清單外、重複、沒選 → 程式選
                fallback += 1 if raw else 0
            if exercise is None:
                continue
            taken.add(exercise['id'])
            sets, basis = self.sets_for(exercise, slot['reps'])
            old = self.rotated_from(exercise)
            if old and old['id'] in replaced:
                old = None                                   # 同一個舊動作只標示一次「取代」
            elif old:
                replaced.add(old['id'])
            items.append(dict(slot=slot['slot'], muscle=slot['muscle'], why=slot['why'],
                              exercise_id=exercise['id'], name=exercise['name'],
                              sets=sets, basis=basis, reason=reason, by_ai=from_ai,
                              rotated_from=dict(name=old['name'], days=self.streak_days(old['id'])) if old else None,
                              streak_days=self.streak_days(exercise['id']) if self.has_replacement(exercise) else None))
        summary = self._clean_text(raw.get('summary'), allowed, self.MAX_REASON * 2)
        texts = [summary] + [i['reason'] for i in items]
        cited = {int(n) for t in texts for n in AiReport._CITATION.findall(t)}
        sources = [dict(n=p['n'], chunk_id=p['chunk_id'], title=p['title'], section=p.get('section') or '',
                        locator=p.get('locator') or '', text=p['text'][:400], score=p.get('score'))
                   for p in self.passages if p['n'] in cited]
        return dict(skeleton=self.skeleton, items=items, summary=summary, sources=sources, fallback=fallback)
