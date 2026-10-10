# -*- coding: utf-8 -*-
"""訓練分析：把一段期間的訓練資料算成指標，並用規則產生「發現」。

    start, end, prev_start, prev_end = TrainingAnalysis.period_range('week', anchor)
    report = TrainingAnalysis(period, start, end, today, sets, prev_sets, workouts, prev_workouts,
                              metrics, last_trained).build()

全部是純計算：不碰資料庫、不呼叫 LLM、不碰 HTTP。
數字都在這裡算好；LLM 只拿 build() 的結果來寫說明，不自己算數字。

輸入資料的欄位（由 sql_process 查出來）：
    sets      [{workout_date, workout_id, exercise_id, exercise_name, muscle_group, set_no, weight_kg, reps}]
    workouts  [{id, workout_date, duration_min, ended_at}]
    metrics   [{record_date, weight_kg}]
    last_trained {部位: 'YYYY-MM-DD'}（查到 min(end, today) 為止）
    cardio    [{workout_date, workout_id, exercise_id, exercise_name, duration_sec, distance_km}]（選填；距離沒填是 None）

sets 只有重訓（sql_process 已排除 is_cardio 的動作），所以組數、訓練量、部位、推拉比例、1RM 都不含有氧；
有氧另外算總時間、距離與次數（report['cardio']）。距離是選填：總距離只加總有填的，並列出哪幾筆沒填。
只做有氧的那天仍算一次訓練。
"""
from collections import defaultdict
from datetime import date, timedelta


class TrainingAnalysis:
    MUSCLES = ('胸', '背', '腿', '肩', '手臂', '核心')     # 與 records.py「運動動作庫」的選項一致
    MAJOR_MUSCLES = ('胸', '背', '腿', '肩')
    WEEKLY_SETS_LOW = 10            # 常見建議：每個主要部位每週約 10 組以上（只當作提醒，不是硬性標準）
    NEGLECT_DAYS = 7                # 主要部位超過幾天沒練就提醒
    PROGRESS_GOOD_PCT = 2.5         # 估計 1RM 進步超過多少 % 算進步
    PROGRESS_DROP_PCT = -5.0        # 退步超過多少 % 提醒
    BALANCE_HIGH = 1.5              # 推／拉組數比例超過這個值（或低於倒數）就提醒
    PULL_WORDS = ('彎舉',)                              # 手臂裡算「拉」的動作
    PUSH_WORDS = ('下壓', '三頭', '窄握', '撐體')        # 手臂裡算「推」的動作

    def __init__(self, period, start, end, today, sets, prev_sets, workouts, prev_workouts, metrics, last_trained,
                 cardio=(), prev_cardio=()):
        self.period, self.start, self.end, self.today = period, start, end, today
        self.sets, self.prev_sets = sets, prev_sets
        self.cardio, self.prev_cardio = list(cardio), list(prev_cardio)
        self.workouts, self.prev_workouts = workouts, prev_workouts
        self.metrics, self.last_trained = metrics, last_trained

    # ------------------------------------------------------------------ 期間與基本公式
    @staticmethod
    def period_range(period, anchor):
        """period: 'week'（週一～週日）或 'month'（當月）。回傳 (本期開始, 本期結束, 上期開始, 上期結束)。"""
        if period == 'week':
            start = anchor - timedelta(days=anchor.weekday())
            end = start + timedelta(days=6)
            return start, end, start - timedelta(days=7), start - timedelta(days=1)
        start = anchor.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        prev_end = start - timedelta(days=1)
        return start, end, prev_end.replace(day=1), prev_end

    @staticmethod
    def estimated_1rm(weight_kg, reps):
        """Epley 公式估計 1RM：重量 ×（1 ＋ 次數 ÷ 30）。次數越多越不準，所以超過 12 下就不估。"""
        weight, reps = float(weight_kg or 0), int(reps or 0)
        if weight <= 0 or reps <= 0 or reps > 12:
            return 0.0
        return round(weight if reps == 1 else weight * (1 + reps / 30), 1)

    @staticmethod
    def volume(row):
        return float(row['weight_kg'] or 0) * int(row['reps'] or 0)

    @staticmethod
    def pct(now, before):
        return round((now - before) / before * 100, 1) if before else None

    # ------------------------------------------------------------------ 指標（可以給任何一段期間的資料）
    @classmethod
    def volume_by_muscle(cls, sets):
        """各部位的組數、訓練量（重量×次數）、做了幾種動作；依 MUSCLES 的順序。"""
        result = {m: dict(sets=0, volume=0.0, exercises=set()) for m in cls.MUSCLES}
        for row in sets:
            item = result.setdefault(row['muscle_group'] or '其他', dict(sets=0, volume=0.0, exercises=set()))
            item['sets'] += 1
            item['volume'] += cls.volume(row)
            item['exercises'].add(row['exercise_id'])
        return {m: dict(sets=v['sets'], volume=round(v['volume'], 1), exercises=len(v['exercises']))
                for m, v in result.items()}

    @classmethod
    def sessions_summary(cls, workouts, sets, cardio=()):
        """訓練次數、天數、總時長與平均時長（只算已結束且有時長的訓練）、總組數、總訓練量。

        sets 是重訓的組；cardio 只用來判斷「這次訓練有沒有紀錄」（只做有氧也算一次訓練）。
        """
        with_sets = {row['workout_id'] for row in sets} | {row['workout_id'] for row in cardio}
        done = [w for w in workouts if w['id'] in with_sets]
        timed = [int(w['duration_min'] or 0) for w in done if w['ended_at'] and (w['duration_min'] or 0) > 0]
        return dict(sessions=len(done), days=len({w['workout_date'] for w in done}),
                    total_minutes=sum(timed), avg_minutes=round(sum(timed) / len(timed)) if timed else None,
                    sets=len(sets), volume=round(sum(cls.volume(r) for r in sets), 1))

    @staticmethod
    def cardio_summary(rows):
        """有氧：做了幾次（不同的訓練）、總分鐘數（四捨五入）、總距離。

        距離是選填：km 只加總有填的那幾筆；no_km 列出沒填距離的紀錄（日期＋動作），
        畫面與 AI 說明都要註明，避免把「部分加總」看成全部的距離。
        """
        seconds = sum(int(r['duration_sec'] or 0) for r in rows)
        no_km = [dict(date=str(r['workout_date'])[:10], name=r['exercise_name']) for r in rows if not r.get('distance_km')]
        return dict(sessions=len({r['workout_id'] for r in rows}), minutes=round(seconds / 60), records=len(rows),
                    km=round(sum(float(r.get('distance_km') or 0) for r in rows), 1), no_km=no_km)

    @classmethod
    def arm_side(cls, name):
        if any(word in (name or '') for word in cls.PULL_WORDS):
            return 'pull'
        if any(word in (name or '') for word in cls.PUSH_WORDS):
            return 'push'
        return None

    @classmethod
    def balance(cls, sets):
        """推／拉、上半身／下半身的組數與比例（比例 = 推 ÷ 拉、上 ÷ 下；分母為 0 時是 None）。"""
        count = defaultdict(int)
        for row in sets:
            muscle = row['muscle_group']
            side = {'胸': 'push', '肩': 'push', '背': 'pull'}.get(muscle) or \
                (cls.arm_side(row['exercise_name']) if muscle == '手臂' else None)
            if side:
                count[side] += 1
            if muscle in ('胸', '背', '肩', '手臂'):
                count['upper'] += 1
            elif muscle == '腿':
                count['lower'] += 1

        def ratio(a, b):
            return round(count[a] / count[b], 2) if count[b] else None
        return dict(push=count['push'], pull=count['pull'], upper=count['upper'], lower=count['lower'],
                    push_pull=ratio('push', 'pull'), upper_lower=ratio('upper', 'lower'))

    @classmethod
    def _best(cls, rows):
        by_ex = {}
        for row in rows:
            ex = by_ex.setdefault(row['exercise_id'], dict(name=row['exercise_name'], muscle=row['muscle_group'],
                                                           e1rm=0.0, max_reps=0, max_weight=0.0, sets=0, volume=0.0))
            ex['e1rm'] = max(ex['e1rm'], cls.estimated_1rm(row['weight_kg'], row['reps']))
            ex['max_reps'] = max(ex['max_reps'], int(row['reps'] or 0))
            ex['max_weight'] = max(ex['max_weight'], float(row['weight_kg'] or 0))
            ex['sets'] += 1
            ex['volume'] += cls.volume(row)
        return by_ex

    @classmethod
    def progress_by_exercise(cls, sets, prev_sets):
        """每個動作本期與上期的表現：有負重的看估計 1RM，徒手的看單組最多次數。依本期訓練量排序。"""
        now, before = cls._best(sets), cls._best(prev_sets)
        result = []
        for ex_id, ex in now.items():
            prev = before.get(ex_id)
            weighted = ex['max_weight'] > 0
            value = ex['e1rm'] if weighted else ex['max_reps']
            prev_value = (prev['e1rm'] if weighted else prev['max_reps']) if prev else None
            result.append(dict(exercise_id=ex_id, name=ex['name'], muscle=ex['muscle'], sets=ex['sets'],
                               volume=round(ex['volume'], 1), metric='e1rm' if weighted else 'max_reps',
                               value=value, prev_value=prev_value or None,
                               change_pct=cls.pct(value, prev_value) if prev_value else None))
        return sorted(result, key=lambda x: (-x['volume'], -x['sets'], x['name']))

    @classmethod
    def days_since_trained(cls, last_trained, reference):
        """各部位距離上次訓練幾天（從沒練過是 None）。"""
        return {m: (reference - date.fromisoformat(str(last_trained[m])[:10])).days if last_trained.get(m) else None
                for m in cls.MUSCLES}

    @staticmethod
    def weight_trend(metrics):
        if not metrics:
            return None
        first, last = metrics[0], metrics[-1]
        return dict(start=float(first['weight_kg']), end=float(last['weight_kg']),
                    change=round(float(last['weight_kg']) - float(first['weight_kg']), 1),
                    records=len(metrics), start_date=str(first['record_date'])[:10], end_date=str(last['record_date'])[:10])

    # ------------------------------------------------------------------ 規則產生的「發現」
    @classmethod
    def findings(cls, report):
        """依指標產生簡短的發現（文字裡的數字都直接取自 report，不會有編造的數字）。

        每筆 {level: 'good'|'warn'|'info', text}；AI 說明時會把這些交給 LLM 改寫得更自然。
        """
        out = []
        summary, prev = report['summary'], report['previous']
        if summary['sessions'] == 0:
            return [dict(level='info', text='這段期間還沒有訓練紀錄。')]

        cardio = (report.get('cardio') or {}).get('summary') or {}
        if cardio.get('minutes'):
            missing = len(cardio.get('no_km') or [])
            if not cardio.get('km'):
                km = '（都沒有填距離）' if missing else ''
            elif missing:
                km = f"；有填距離的共 {cardio['km']:g} 公里（{cardio['records']} 筆中有 {missing} 筆沒填距離，未計入）"
            else:
                km = f"、{cardio['km']:g} 公里"
            out.append(dict(level='good', text=f"有氧 {cardio['sessions']} 次，共 {cardio['minutes']} 分鐘{km}。"))

        if prev['sessions']:
            diff = summary['sessions'] - prev['sessions']
            if diff > 0:
                out.append(dict(level='good', text=f"訓練次數 {summary['sessions']} 次，比上一期多 {diff} 次。"))
            elif diff < 0 and not report['in_progress']:
                out.append(dict(level='info', text=f"訓練次數 {summary['sessions']} 次，比上一期少 {-diff} 次。"))

        for item in report['progress']:
            if item['change_pct'] is None:
                continue
            unit = '估計 1RM' if item['metric'] == 'e1rm' else '單組最多次數'
            if item['change_pct'] >= cls.PROGRESS_GOOD_PCT:
                out.append(dict(level='good', text=f"{item['name']} {unit}從 {item['prev_value']:g} 提升到 "
                                                   f"{item['value']:g}（+{item['change_pct']:g}%）。"))
            elif item['change_pct'] <= cls.PROGRESS_DROP_PCT:
                out.append(dict(level='warn', text=f"{item['name']} {unit}從 {item['prev_value']:g} 降到 "
                                                   f"{item['value']:g}（{item['change_pct']:g}%），留意恢復與睡眠。"))

        bal = report['balance']
        push, pull = bal['push'], bal['pull']
        if push and pull and bal['push_pull'] is not None:
            if bal['push_pull'] >= cls.BALANCE_HIGH:
                out.append(dict(level='warn', text=f'推的動作做了 {push} 組，拉的只有 {pull} 組，'
                                                   '可以多安排划船、下拉等背部動作。'))
            elif bal['push_pull'] <= 1 / cls.BALANCE_HIGH:
                out.append(dict(level='warn', text=f'拉的動作做了 {pull} 組，推的只有 {push} 組，'
                                                   '可以多安排臥推、肩推等推的動作。'))
        elif push and not pull:
            out.append(dict(level='warn', text=f'推的動作做了 {push} 組，但沒有拉的動作（背部、彎舉），'
                                               '可以多安排划船、下拉等背部動作。'))
        elif pull and not push:
            out.append(dict(level='warn', text=f'拉的動作做了 {pull} 組，但沒有推的動作（胸、肩、三頭），'
                                               '可以多安排臥推、肩推等推的動作。'))

        never = [m for m in cls.MAJOR_MUSCLES if report['days_since'].get(m) is None]
        if never:
            out.append(dict(level='info', text=f"還沒有{'、'.join(never)}的訓練紀錄。"))
        for muscle in cls.MAJOR_MUSCLES:
            days = report['days_since'].get(muscle)
            sets_per_week = report['by_muscle'].get(muscle, {}).get('sets', 0) / report['weeks']
            if days is None:
                continue
            if days >= cls.NEGLECT_DAYS:
                out.append(dict(level='warn', text=f'{muscle}部已經 {days} 天沒練。'))
            elif 0 < sets_per_week < cls.WEEKLY_SETS_LOW and not report['in_progress']:
                out.append(dict(level='info', text=f'{muscle}部平均每週 {sets_per_week:.0f} 組，常見建議約每週 10 組以上。'))
        return out

    # ------------------------------------------------------------------ 組合
    def build(self):
        start, end, today = self.start, self.end, self.today
        in_progress = start <= today <= end
        last_day = min(end, today) if in_progress else end
        weeks = 1 if self.period == 'week' else max(1, round((last_day - start).days / 7 + 0.5))
        summary = self.sessions_summary(self.workouts, self.sets, self.cardio)
        prev = self.sessions_summary(self.prev_workouts, self.prev_sets, self.prev_cardio)
        cardio, prev_cardio = self.cardio_summary(self.cardio), self.cardio_summary(self.prev_cardio)
        report = dict(
            period=self.period, start=start.isoformat(), end=end.isoformat(), in_progress=in_progress, weeks=weeks,
            summary=summary, previous=prev,
            change={k: self.pct(summary[k], prev[k]) for k in ('sessions', 'sets', 'volume')},
            by_muscle=self.volume_by_muscle(self.sets), balance=self.balance(self.sets),
            progress=self.progress_by_exercise(self.sets, self.prev_sets),
            days_since=self.days_since_trained(self.last_trained, min(end, today)),   # 看過去的期間時，以期末為準
            weight=self.weight_trend(self.metrics),
            cardio=dict(summary=cardio, previous=prev_cardio, change_minutes=self.pct(cardio['minutes'], prev_cardio['minutes'])))
        report['findings'] = self.findings(report)
        return report
