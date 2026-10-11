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

個人資料（user_profiles）：
- 必填 REQUIRED_PROFILE（目標、一週天數、每次分鐘），缺少時 service 不產生課表，請使用者先填。
- 完全沒有訓練紀錄（first_time）時只依個人資料排課：器材挑容易上手的、活動量低的人每個動作少 1 組。
- 沒做過的動作的起始重量，依序：
  1. reference_weight：從做過的類似動作（沒有就同部位動作）換算：
     新動作 1RM ＝ 參考動作估計 1RM ÷ 參考器材比例 × 新動作係數 ÷ 參考動作係數 × 新器材比例
  2. starting_weight：沒有可換算的紀錄時，依體重、性別、年齡、活動量、目標次數估算
  兩者都會換成目標次數的重量後再往下抓（START_SAFETY）；
  缺性別或體重就不估；未滿 18 歲不估（建議在指導下開始）。性別、體重、生日只在程式裡計算，不送給 LLM。

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
import math
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
    # 產生課表前必須填好的個人資料欄位（欄位名稱 → 畫面上的名稱，與 records.PROFILE_FIELDS 一致）
    REQUIRED_PROFILE = {'goal_type': '運動目標', 'workout_days_per_week': '一週可運動天數',
                        'minutes_per_session': '每次運動分鐘'}
    # 第一次排課（沒有任何紀錄）時的器材優先順序：數字越小越優先；沒列出的（槓鈴、EZ 槓…）排最後
    # 理由：機械、纜繩動作軌跡固定、容易學，也比較容易自己抓重量
    FIRST_TIME_EQUIPMENT = {'機械': 0, '纜繩': 0, '啞鈴': 1, '史密斯機': 1, '徒手': 2}
    FIRST_TIME_RIR = '2～3'             # 第一次做：選還能再多做 2～3 下的重量（RIR, reps in reserve）

    # ---- 第一次排課的起始重量估算（粗估的起始值，不是實測標準；寧可偏輕，做完第一次就改用實際紀錄）
    # 估計 1RM ＝ 體重 × 係數（依動作類型、性別）× 活動量係數；工作重量 ＝ 1RM ÷（1 ＋ 次數 ÷ 30）× START_SAFETY
    # 係數以「槓鈴版本」為準，依序比對動作名稱（前面的優先）：(關鍵字, 男, 女)
    START_RATIOS = (
        (('直臂', '直立划船'), 0.3, 0.2),     # 要放在「划船、下拉」前面，避免被當成比較重的複合動作
        (('腿推',), 1.5, 1.0),
        (('硬舉', '臀推'), 0.9, 0.65),
        (('深蹲', '蹲', '弓步', '登階'), 0.75, 0.5),
        (('聳肩', '提踵'), 0.6, 0.4),
        (('臥推', '胸推'), 0.6, 0.35),
        (('划船', '下拉'), 0.6, 0.4),
        (('肩推',), 0.4, 0.25),
        (('平舉', '臉拉', '飛鳥', '夾胸'), 0.15, 0.1),
        (('彎舉', '下壓', '三頭', '腿伸', '腿屈', '腿彎', '捲腹'), 0.25, 0.15),
    )
    ACTIVITY_FACTOR = {'低': 0.8, '中': 0.9, '高': 1.0}
    MIN_ESTIMATE_AGE = 18               # 未滿 18 歲不估起始重量
    AGE_FACTORS = ((60, 0.8), (50, 0.9), (40, 0.95))   # (幾歲以上, 係數)，由大到小比對；其他年齡 1.0
    START_SAFETY = 0.8                  # 「往下抓一點」：估出來的重量再打 8 折
    DUMBBELL_PER_HAND = 0.4             # 兩支啞鈴約為槓鈴重量的 8 成，每手約 4 成
    # 器材取整：(每一級 kg, 最小 kg)；一律無條件捨去
    WEIGHT_STEP = {'槓鈴': (2.5, 20), 'EZ 槓': (2.5, 10), '史密斯機': (2.5, 10), '啞鈴': (1, 2),
                   '機械': (2.5, 5), '纜繩': (2.5, 5)}
    NO_LOAD = ('徒手', '健腹輪')        # 不用估重量的器材

    # ---- 依上次的 RPE 調整（只看上次最重那幾組裡有填 RPE 的；都沒填就照原本的雙重漸進）
    RPE_EASY = 8                        # 次數達標且 RPE ≤ 8：還有餘力 → 加重
    RPE_FAILURE = 10                    # 次數沒達標且 RPE 10（已力竭）→ 降重
    DELOAD = 0.95                       # 降重幅度：上次重量 × 0.95
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
                 exercise_dates=None, body=None):
        self.day = day
        self.body = body or {}          # {gender: '男'|'女', weight_kg, birth_date}：只用來估起始重量，不送給 LLM
        self.exercise_dates = {k: sorted({date.fromisoformat(str(d)[:10]) for d in v})
                               for k, v in (exercise_dates or {}).items()}
        self.profile = profile or {}
        self.days_since, self.weekly_sets = days_since, weekly_sets
        self.library = [e for e in library if not e.get('is_cardio')]   # 這個頁面只記重量×次數
        self.usage, self.last = usage, last_sessions
        self.passages = list(passages or [])
        # 完全沒有訓練紀錄：只能依個人資料排課
        self.first_time = not (self.usage or self.last or self.exercise_dates
                               or any(v is not None for v in (days_since or {}).values())
                               or any(int(v or 0) for v in (weekly_sets or {}).values()))
        self.skeleton = self._build()

    @classmethod
    def missing_profile(cls, profile):
        """產生課表前還沒填的個人資料欄位（畫面上的名稱）；一週 0 天也算沒填。"""
        profile = profile or {}
        return [label for key, label in cls.REQUIRED_PROFILE.items()
                if profile.get(key) in (None, '') or (key != 'goal_type' and int(profile.get(key) or 0) <= 0)]

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
        # 第一次排課、日常活動量低 → 每個動作少 1 組，先熟悉動作
        low = self.first_time and self.profile.get('activity_level') == '低'
        self.sets_per_exercise = self.SETS_PER_EXERCISE - 1 if low else self.SETS_PER_EXERCISE

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
                slots.append(dict(slot=n, muscle=m, sets=self.sets_per_exercise, reps=reps,
                                  why=self._why(m)))
        skipped_text = [f'{m}在 {self.days_since[m]} 天前練過，今天先讓它恢復' for m in skipped]
        return dict(date=self.day.isoformat(), split=key, split_name=split_name, day_name=day_name,
                    arm_side=arm_side, minutes=minutes, goal=self.profile.get('goal_type') or '', slots=slots,
                    skipped=skipped_text, rest=not slots, first_time=self.first_time,
                    profile_text=self._profile_text(),
                    rest_reason=(f'主要部位在 {self.RECENT_DAYS} 天內都練過，今天建議休息或做輕度活動。'
                                 if not slots else ''))

    def _profile_text(self):
        """畫面上「依據哪些個人資料排課」的說明（數字都來自 user_profiles）。"""
        p = self.profile
        parts = [f"目標：{p['goal_type']}" if p.get('goal_type') else '',
                 f"一週 {p['workout_days_per_week']} 天" if p.get('workout_days_per_week') else '',
                 f"每次 {p['minutes_per_session']} 分鐘" if p.get('minutes_per_session') else '',
                 f"活動量：{p['activity_level']}" if p.get('activity_level') else '']
        return '・'.join(x for x in parts if x)

    def _muscle_recent(self, muscle):
        days = self.days_since.get(muscle)
        return days is not None and days < self.RECENT_DAYS

    def _why(self, muscle):
        """這個部位為什麼排進來（給 LLM 和畫面參考；數字都來自資料）。"""
        days = self.days_since.get(muscle)
        sets = int(self.weekly_sets.get(muscle) or 0)
        if self.first_time:
            return f"依目標「{self.profile.get('goal_type') or '一般'}」排入{muscle}"
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
        if self.first_time:                               # 沒有紀錄：容易上手的器材優先，同分依動作庫順序
            return sorted(rows, key=lambda e: self.FIRST_TIME_EQUIPMENT.get(e.get('equipment'), 9))
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
        """依最近一次的紀錄決定重量（雙重漸進＋RPE）：

            次數達標、RPE ≤ 8 或沒填 → 加重　　次數達標、RPE 9～10 → 維持
            次數沒達標、RPE ≤ 9 或沒填 → 維持　次數沒達標、RPE 10 → 降約 5%
        RPE 只看上次最重那幾組裡有填的最大值。回傳 (各組 [{weight_kg, reps}], 依據說明)。
        沒做過的動作：reference_weight() 從類似動作換算；沒有參考紀錄才用 starting_weight() 依個人資料估算
        （缺資料就留空，由使用者自己填）。
        """
        n = getattr(self, 'sets_per_exercise', self.SETS_PER_EXERCISE)
        last = self.last.get(exercise['id']) or []
        if not last:                                         # 沒做過的動作：先從類似動作換算，沒有才依個人資料估
            weight, basis = self.reference_weight(exercise, reps) or self.starting_weight(exercise, reps)
            return [dict(weight_kg=weight, reps=reps)] * n, basis
        top = max(float(r['weight_kg'] or 0) for r in last)
        top_rows = [r for r in last if float(r['weight_kg'] or 0) == top]
        top_reps = [int(r['reps'] or 0) for r in top_rows]
        done = '、'.join(str(x) for x in top_reps)
        rpe = self.top_rpe(top_rows)                         # None：上次沒填 RPE
        rpe_text = f'，RPE 最高 {rpe}' if rpe is not None else ''
        reached = min(top_reps) >= reps
        if top == 0:                                         # 徒手：調整次數
            best = max(top_reps)
            if reached and (rpe is None or rpe <= self.RPE_EASY):
                return [dict(weight_kg=0, reps=best + 1)] * n, f'上次徒手 {done} 下{rpe_text}，次數 +1'
            why = '已接近力竭，維持次數' if reached else '維持次數'
            return [dict(weight_kg=0, reps=best)] * n, f'上次徒手 {done} 下{rpe_text}，{why}'
        if reached and (rpe is None or rpe <= self.RPE_EASY):
            step = 2 if '啞鈴' in (exercise.get('equipment') or '') else 2.5
            weight = round((top + step) * 2) / 2              # 取到 0.5 kg
            return [dict(weight_kg=weight, reps=reps)] * n, \
                f'上次 {top:g} kg 做到 {done} 下{rpe_text}，加 {step:g} kg'
        if reached:                                          # 次數達標但 RPE 9～10：先在同重量做得更輕鬆
            return [dict(weight_kg=top, reps=reps)] * n, \
                f'上次 {top:g} kg 做到 {done} 下{rpe_text}，已接近力竭，維持重量'
        if rpe is not None and rpe >= self.RPE_FAILURE:      # 力竭了次數還不夠 → 降重
            weight = math.floor(top * self.DELOAD * 2) / 2   # 取到 0.5 kg，無條件捨去
            return [dict(weight_kg=weight, reps=reps)] * n, \
                f'上次 {top:g} kg 只做到 {done} 下{rpe_text}，降約 {round((1 - self.DELOAD) * 100)}% 到 {weight:g} kg'
        return [dict(weight_kg=top, reps=reps)] * n, f'上次 {top:g} kg 做到 {done} 下{rpe_text}，維持重量'

    @staticmethod
    def top_rpe(rows):
        """上次最重那幾組裡有填的 RPE 取最大值；都沒填就是 None。"""
        # rows 可能是 sqlite3.Row（沒有 .get()）或 dict（測試用，可能沒有 rpe 這個 key）
        values = [int(r['rpe']) for r in rows if 'rpe' in r.keys() and r['rpe'] not in (None, '')]
        return max(values) if values else None

    @property
    def age(self):
        """課表日期當天的足歲；生日沒填或格式不對就是 None。"""
        try:
            born = date.fromisoformat(str(self.body.get('birth_date') or '')[:10])
        except ValueError:
            return None
        return self.day.year - born.year - ((self.day.month, self.day.day) < (born.month, born.day))

    def age_factor(self):
        age = self.age
        return next((f for at_least, f in self.AGE_FACTORS if age is not None and age >= at_least), 1.0)

    def ratio_for(self, name):
        """動作係數（START_RATIOS）；性別沒填時用男性欄（換算只用比例，影響不大）。"""
        female = self.body.get('gender') == '女'
        return next(((f if female else m) for words, m, f in self.START_RATIOS if any(w in name for w in words)), None)

    @staticmethod
    def weight_unit(exercise):
        """畫面上重量前面的說明：高腳杯是雙手拿一顆啞鈴，其他啞鈴動作是每手的重量。"""
        if (exercise.get('equipment') or '') != '啞鈴':
            return ''
        return '一顆啞鈴' if '高腳杯' in exercise['name'] else '每手'

    def equipment_factor(self, equipment):
        """器材比例：啞鈴每手約為槓鈴的 0.4，其他器材視為 1。"""
        return self.DUMBBELL_PER_HAND if equipment == '啞鈴' else 1.0

    def _to_weight(self, one_rm, reps, equipment):
        """槓鈴等效 1RM → 目標次數的工作重量（往下抓、乘器材比例、依器材取整）。回傳 (kg, 是否低於器材最小重量)。"""
        work = one_rm / (1 + reps / 30) * self.START_SAFETY * self.equipment_factor(equipment)
        step, minimum = self.WEIGHT_STEP.get(equipment, (2.5, 2.5))
        raw = math.floor(work / step) * step
        return max(minimum, raw), raw < minimum

    def reference_weight(self, exercise, reps):
        """從做過的類似動作換算起始重量：回傳 (kg, 依據說明)；沒有可用的參考紀錄就回傳 None。

        參考動作：同部位、做過、有係數、上次有負重且次數 ≤ 12（Epley 才準）。
        優先「類似動作」（同動作類型），其次同部位其他動作；同條件下選最常做的。
        """
        equipment = exercise.get('equipment') or ''
        age = self.age
        if equipment in self.NO_LOAD or (age is not None and age < self.MIN_ESTIMATE_AGE):
            return None                                       # 徒手、未滿 18 歲照 starting_weight 的規則
        ratio_new = self.ratio_for(exercise['name'])
        if ratio_new is None:
            return None
        refs = []
        for e in self.library:
            rows = self.last.get(e['id'])
            if e['id'] == exercise['id'] or not rows or e['muscle_group'] != exercise['muscle_group']:
                continue
            ratio_ref = self.ratio_for(e['name'])
            best = max(rows, key=lambda r: TrainingAnalysis.estimated_1rm(r['weight_kg'], r['reps']))
            one_rm = TrainingAnalysis.estimated_1rm(best['weight_kg'], best['reps'])
            if ratio_ref is None or one_rm <= 0:
                continue
            refs.append(((not self.similar(e, exercise), -int(self.usage.get(e['id']) or 0)), e, best, one_rm, ratio_ref))
        if not refs:
            return None
        _, ref, best, one_rm, ratio_ref = min(refs, key=lambda x: x[0])
        barbell_1rm = one_rm / self.equipment_factor(ref.get('equipment') or '') * ratio_new / ratio_ref
        weight, below = self._to_weight(barbell_1rm, reps, equipment)
        unit = self.weight_unit(exercise)
        ref_unit = f'{self.weight_unit(ref)} ' if self.weight_unit(ref) else ''
        basis = (f"第一次做：依「{ref['name']}」上次 {ref_unit}{float(best['weight_kg']):g} kg × {int(best['reps'])} 下"
                 f"（估計 1RM {one_rm:g} kg）換算，已往下抓 {round((1 - self.START_SAFETY) * 100)}%，"
                 f"建議{unit} {weight:g} kg 起；太輕或太重就調整")
        if below:
            basis += f"（換算值低於器材最小重量 {self.WEIGHT_STEP.get(equipment, (2.5, 2.5))[1]:g} kg）"
        return weight, basis

    def starting_weight(self, exercise, reps):
        """沒做過的動作的起始重量：回傳 (kg 或 None, 依據說明)。啞鈴是每手的重量。

        缺性別或體重、或動作沒有對應的係數 → None（重量自填），不硬猜。
        """
        equipment = exercise.get('equipment') or ''
        hint = f'還留 {self.FIRST_TIME_RIR} 下餘力'
        if equipment in self.NO_LOAD:
            return 0, f'第一次做：徒手動作，目標 {reps} 下，做不到就先做到{hint}的次數'
        age = self.age
        if age is not None and age < self.MIN_ESTIMATE_AGE:
            return None, (f'第一次做：未滿 {self.MIN_ESTIMATE_AGE} 歲，建議在教練或師長指導下，'
                          f'從能輕鬆做 {reps} 下的重量開始（重量請自己填）')
        gender, body_weight = self.body.get('gender'), float(self.body.get('weight_kg') or 0)
        if gender not in ('男', '女') or body_weight <= 0:
            return None, f'第一次做：選能做 {reps} 下、{hint}的重量（填寫性別與體重後可以估算起始重量）'
        ratio = next(((m if gender == '男' else f) for words, m, f in self.START_RATIOS
                      if any(w in exercise['name'] for w in words)), None)
        step, minimum = self.WEIGHT_STEP.get(equipment, (2.5, 2.5))
        if ratio is None:
            return None, f'第一次做：選能做 {reps} 下、{hint}的重量'
        level = self.profile.get('activity_level')
        one_rm = body_weight * ratio * self.ACTIVITY_FACTOR.get(level, 0.9) * self.age_factor()
        work = one_rm / (1 + reps / 30) * self.START_SAFETY
        if equipment == '啞鈴':
            work *= self.DUMBBELL_PER_HAND
        weight = max(minimum, math.floor(work / step) * step)
        unit = self.weight_unit(exercise)
        basis = (f"第一次做：依體重 {body_weight:g} kg、{gender}、{f'{age} 歲' if age is not None else '年齡未填'}、"
                 f"活動量{level or '未填'}、目標 {reps} 下估算，"
                 f"已往下抓 {round((1 - self.START_SAFETY) * 100)}%，建議{unit} {weight:g} kg 起；太輕或太重就調整")
        if weight == minimum and math.floor(work / step) * step < minimum:
            basis += f'（估算值低於器材最小重量 {minimum:g} kg）'
        return weight, basis

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
        if self.first_time:
            data['first_time'] = True                       # 沒有任何訓練紀錄
            data['activity_level'] = self.profile.get('activity_level') or ''
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
        if any(not self.last.get(e['id']) for x in self.skeleton['slots'] for e in self.candidates(x)):
            # 候選裡有沒做過的動作：體重、性別、年齡改變時起始重量會變（只進雜湊，不送給 LLM；放年齡不放生日）
            base['body'] = dict(gender=self.body.get('gender'), weight_kg=self.body.get('weight_kg'), age=self.age)
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
