# -*- coding: utf-8 -*-
"""body 模組的商業邏輯：輸入驗證、訓練規則、組出前端要的狀態 JSON。

這裡不直接寫 SQL（都交給 sql_process.BodySqlProcess），也不處理 HTTP（在 body_route.py）。
每個會寫入資料的方法都回傳 dict：{state, message?, rest?}，由路由包成 {ok: true, ...}。

規則摘要：
- 進行中的訓練：workouts.ended_at 為 NULL。
- 開始訓練前要先排好動作（exercise_ids 至少一個，而且都是自己動作庫裡的動作）。
  排好的清單是草稿，存在瀏覽器；做完第一組後才會寫進 workout_sets。
- 「完成一組」＝寫入一筆 workout_sets；「取消完成」＝刪除該筆並重新編號。
- 結束時如果一組都沒做，這次訓練直接取消。
- 打開頁面時，如果使用者的動作庫是空的，先寫入 DEFAULT_EXERCISES。
"""
import math
from datetime import date, datetime, time, timedelta

from .errors import ApiError
from .sql_process import BodySqlProcess

# 動作庫是空的時候預先放進去的常用動作：(名稱, 部位, 器材, 是否有氧)
# 參考 BurnFit 的分類方式（依部位，再依器材：槓鈴／啞鈴／機械／纜繩／徒手…）整理。
# 部位沿用 records.py「運動動作庫」的選項：胸、背、腿、肩、手臂、核心。
# 這個頁面以「重量 × 次數」記錄，所以只放重訓動作；棒式、跑步等記時間／距離的動作沒有放。
DEFAULT_EXERCISES = [
    # 胸
    ('槓鈴臥推', '胸', '槓鈴', 0),
    ('上斜槓鈴臥推', '胸', '槓鈴', 0),
    ('下斜槓鈴臥推', '胸', '槓鈴', 0),
    ('啞鈴臥推', '胸', '啞鈴', 0),
    ('上斜啞鈴臥推', '胸', '啞鈴', 0),
    ('啞鈴飛鳥', '胸', '啞鈴', 0),
    ('史密斯臥推', '胸', '史密斯機', 0),
    ('機械胸推', '胸', '機械', 0),
    ('蝴蝶機夾胸', '胸', '機械', 0),
    ('纜繩夾胸', '胸', '纜繩', 0),
    ('伏地挺身', '胸', '徒手', 0),
    ('雙槓撐體', '胸', '徒手', 0),
    # 背
    ('硬舉', '背', '槓鈴', 0),
    ('槓鈴划船', '背', '槓鈴', 0),
    ('T 槓划船', '背', '槓鈴', 0),
    ('單臂啞鈴划船', '背', '啞鈴', 0),
    ('滑輪下拉', '背', '纜繩', 0),
    ('坐姿划船', '背', '纜繩', 0),
    ('直臂下拉', '背', '纜繩', 0),
    ('機械划船', '背', '機械', 0),
    ('引體向上', '背', '徒手', 0),
    ('反手引體向上', '背', '徒手', 0),
    ('背部伸展', '背', '徒手', 0),
    # 腿
    ('槓鈴深蹲', '腿', '槓鈴', 0),
    ('前蹲舉', '腿', '槓鈴', 0),
    ('羅馬尼亞硬舉', '腿', '槓鈴', 0),
    ('槓鈴臀推', '腿', '槓鈴', 0),
    ('高腳杯深蹲', '腿', '啞鈴', 0),
    ('啞鈴弓步蹲', '腿', '啞鈴', 0),
    ('保加利亞分腿蹲', '腿', '啞鈴', 0),
    ('腿推舉', '腿', '機械', 0),
    ('哈克深蹲', '腿', '機械', 0),
    ('腿伸屈', '腿', '機械', 0),
    ('腿彎舉', '腿', '機械', 0),
    ('站姿提踵', '腿', '機械', 0),
    ('徒手深蹲', '腿', '徒手', 0),
    ('登階', '腿', '徒手', 0),
    # 肩
    ('槓鈴肩推', '肩', '槓鈴', 0),
    ('直立划船', '肩', '槓鈴', 0),
    ('啞鈴肩推', '肩', '啞鈴', 0),
    ('阿諾肩推', '肩', '啞鈴', 0),
    ('啞鈴側平舉', '肩', '啞鈴', 0),
    ('啞鈴前平舉', '肩', '啞鈴', 0),
    ('啞鈴反向飛鳥', '肩', '啞鈴', 0),
    ('啞鈴聳肩', '肩', '啞鈴', 0),
    ('機械肩推', '肩', '機械', 0),
    ('纜繩側平舉', '肩', '纜繩', 0),
    ('臉拉', '肩', '纜繩', 0),
    # 手臂
    ('槓鈴彎舉', '手臂', '槓鈴', 0),
    ('窄握臥推', '手臂', '槓鈴', 0),
    ('EZ 槓彎舉', '手臂', 'EZ 槓', 0),
    ('牧師椅彎舉', '手臂', 'EZ 槓', 0),
    ('仰臥三頭伸展', '手臂', 'EZ 槓', 0),
    ('啞鈴彎舉', '手臂', '啞鈴', 0),
    ('錘式彎舉', '手臂', '啞鈴', 0),
    ('啞鈴過頭三頭伸展', '手臂', '啞鈴', 0),
    ('纜繩彎舉', '手臂', '纜繩', 0),
    ('纜繩下壓', '手臂', '纜繩', 0),
    ('板凳撐體', '手臂', '徒手', 0),
    # 核心
    ('捲腹', '核心', '徒手', 0),
    ('仰臥抬腿', '核心', '徒手', 0),
    ('懸吊舉腿', '核心', '徒手', 0),
    ('俄羅斯轉體', '核心', '徒手', 0),
    ('健腹輪', '核心', '健腹輪', 0),
    ('纜繩捲腹', '核心', '纜繩', 0),
]

class Validator:
    """把前端送來的 JSON 值轉成正確型別；不合法就丟 ApiError。"""

    @staticmethod
    def day(value, default=None):
        try:
            return date.fromisoformat(value) if value else (default or date.today())
        except (TypeError, ValueError):
            return default or date.today()

    @staticmethod
    def number(data, name, label, low, high, required=True, integer=False):
        raw = data.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if required:
                raise ApiError('請填寫：' + label)
            return None
        if isinstance(raw, bool):
            raise ApiError(label + '格式不正確。')
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ApiError(label + '格式不正確。') from None
        if integer:
            if not math.isfinite(value) or value != int(value):
                raise ApiError(label + '須為整數。')
            value = int(value)
        if not math.isfinite(value) or not low <= value <= high:
            raise ApiError(f'{label}須介於 {low:g}–{high:g}。')
        return value

    @staticmethod
    def identifier(value, message='請選擇動作。'):
        if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
            raise ApiError(message)
        return int(value)

    @staticmethod
    def optional_identifier(value):
        """前端「目前正在看的動作」；不合法就當作沒有。"""
        return value if isinstance(value, int) and not isinstance(value, bool) else None


class BodyService:
    WEEKDAYS = '一二三四五六日'

    def __init__(self, sql: BodySqlProcess, today=None):
        self.sql = sql
        self.today = today or date.today()


    # ============================================================ 預設動作
    def ensure_default_exercises(self):
        """使用者的動作庫是空的時候，先寫入預設動作，「加入動作」才有東西可以選。回傳寫入筆數。"""
        added = self.sql.insert_default_exercises(DEFAULT_EXERCISES)
        if added:
            self.sql.commit()
        return added


    # ============================================================ 讀取：組出一天的狀態
    def state(self, day, wanted=None):
        """某一天的完整畫面資料（只放原始數值，格式化交給前端）。"""
        monday = day - timedelta(days=day.weekday())
        library = self._library(day)
        workout, current = self._workout(day, wanted, {e['id']: e for e in library})
        return dict(
            d=day.isoformat(), today=self.today.isoformat(), is_future=day > self.today,
            weekday=self.WEEKDAYS[day.weekday()],
            prev_week=(monday - timedelta(days=7)).isoformat(), next_week=(monday + timedelta(days=7)).isoformat(),
            week=self._week(day, monday), weight=self._weight(day),
            library=library, workout=workout, current=current)

    def _week(self, day, monday):
        dates = [monday + timedelta(days=i) for i in range(7)]
        start, end = dates[0].isoformat(), dates[-1].isoformat()
        trained = self.sql.trained_dates(start, end)
        groups = self.sql.muscle_groups_by_date(start, end)
        return [dict(d=x.isoformat(), weekday=self.WEEKDAYS[x.weekday()], day=x.day,
                     selected=x == day, today=x == self.today,
                     trained=x.isoformat() in trained, groups=groups.get(x.isoformat(), []))
                for x in dates]

    def _weight(self, day):
        d = day.isoformat()
        record = self.sql.metric_on(d)
        latest = self.sql.latest_metric(d)
        delta = None
        if latest:
            week_before = (date.fromisoformat(latest['record_date']) - timedelta(days=7)).isoformat()
            base = self.sql.latest_metric(week_before)
            if base:
                delta = round(latest['weight_kg'] - base['weight_kg'], 1)
        return dict(record=dict(record) if record else None, latest=dict(latest) if latest else None, delta=delta,
                    trend=[dict(d=r['record_date'], weight_kg=r['weight_kg']) for r in self.sql.recent_metrics(d)])

    def _library(self, day):
        """動作庫；每個動作附上最近一次的各組（last），讓前端排課時預填重量與次數。"""
        since = (day - timedelta(days=180)).isoformat()
        sessions = self.sql.latest_sessions_before(day.isoformat(), since)
        return [dict(id=r['id'], name=r['exercise_name'], muscle_group=r['muscle_group'], equipment=r['equipment'],
                     last=[dict(set_no=x['set_no'], weight_kg=x['weight_kg'], reps=x['reps']) for x in sessions.get(r['id'], [])])
                for r in self.sql.exercises()]

    @staticmethod
    def _pair(row):
        return dict(weight_kg=row['weight_kg'], reps=row['reps']) if row else None

    @staticmethod
    def _volume(sets):
        return sum((s['weight_kg'] or 0) * (s['reps'] or 0) for s in sets)

    def _workout(self, day, wanted, lib):
        row = self.sql.latest_workout_on(day.isoformat())
        if not row:
            return None, None
        sets = self.sql.sets_of(row['id'])
        order = self.sql.exercise_order(row['id'])
        if wanted in lib and wanted not in order:
            order.append(wanted)
        if wanted in order:
            current_id = wanted
        elif sets:
            current_id = max(sets, key=lambda s: s['id'])['exercise_id']
        else:
            current_id = None

        exercises, groups, current = [], [], None
        for ex_id in order:
            info = lib.get(ex_id, dict(id=ex_id, name=f'動作 #{ex_id}', muscle_group=None, equipment=None))
            mine = [s for s in sets if s['exercise_id'] == ex_id]
            if mine and info['muscle_group'] and info['muscle_group'] not in groups:
                groups.append(info['muscle_group'])
            exercises.append(dict({k: v for k, v in info.items() if k != 'last'}, done=len(mine), volume=self._volume(mine)))
            if ex_id == current_id:
                current = self._current(info, mine, row)

        workout = dict(id=row['id'], started_at=row['started_at'], ended_at=row['ended_at'],
                       in_progress=row['ended_at'] is None, duration_min=row['duration_min'] or 0,
                       volume=self._volume(sets), set_count=len(sets), groups=groups, exercises=exercises)
        return workout, current

    def _current(self, info, mine, workout_row):
        """目前正在記錄的動作：已完成的各組、上一次的成績、下一組預填值。"""
        prev = self.sql.previous_session_sets(info['id'], workout_row)
        best = max(prev.values(), key=lambda r: ((r['weight_kg'] or 0), (r['reps'] or 0)), default=None)
        next_no = (mine[-1]['set_no'] if mine else 0) + 1
        seed = mine[-1] if mine else prev.get(next_no)   # 下一組先填剛做的那組；第一組填上次同一組
        return dict(
            exercise_id=info['id'], name=info['name'], muscle_group=info['muscle_group'], equipment=info['equipment'],
            best=self._pair(best),
            sets=[dict(id=s['id'], set_no=s['set_no'], weight_kg=s['weight_kg'], reps=s['reps'], rpe=s['rpe'],
                       last=self._pair(prev.get(s['set_no']))) for s in mine],
            next=dict(set_no=next_no, last=self._pair(prev.get(next_no)),
                      weight_kg=seed['weight_kg'] if seed else None, reps=seed['reps'] if seed else None))

    # ============================================================ 寫入
    def _owned_workout(self, workout_id):
        row = self.sql.workout(workout_id)
        if not row:
            raise ApiError.not_found('找不到這次訓練。')
        return row

    def _owned_exercise(self, exercise_id):
        row = self.sql.exercise(exercise_id)
        if not row:
            raise ApiError.not_found('找不到這個動作。')
        return row

    def _result(self, day, wanted=None, **extra):
        return dict(state=self.state(day, wanted), **extra)

    def save_weight(self, data):
        day = Validator.day(data.get('d'), self.today)
        if day > self.today:
            raise ApiError('不能記錄未來日期的體重。')
        weight = Validator.number(data, 'weight_kg', '體重', 1, 600)
        fat = Validator.number(data, 'body_fat_pct', '體脂率', 0, 100, required=False)
        self.sql.upsert_metric(day.isoformat(), weight, fat)
        self.sql.commit()
        return self._result(day, Validator.optional_identifier(data.get('ex')), message='體重已儲存。')

    def start_workout(self, data):
        day = Validator.day(data.get('d'), self.today)
        if day > self.today:
            raise ApiError('不能在未來的日期開始訓練。')
        ids = data.get('exercise_ids')
        if not isinstance(ids, list) or not ids:
            raise ApiError('請先加入至少一個動作，再開始訓練。')
        exercise_ids = []
        for value in ids:
            exercise_id = self._owned_exercise(Validator.identifier(value, '動作格式不正確。'))['id']
            if exercise_id not in exercise_ids:
                exercise_ids.append(exercise_id)
        if not self.sql.running_workout_on(day.isoformat()):
            now = datetime.now()
            started = now if day == self.today else datetime.combine(day, now.time())
            self.sql.create_workout(day.isoformat(), started.strftime('%Y-%m-%dT%H:%M'))
            self.sql.commit()
        return self._result(day, exercise_ids[0])

    def end_workout(self, workout_id):
        workout = self._owned_workout(workout_id)
        day = date.fromisoformat(workout['workout_date'])
        if workout['ended_at']:
            return self._result(day)
        if not self.sql.workout_has_sets(workout_id):
            self.sql.delete_workout(workout_id)
            self.sql.commit()
            return self._result(day, message='這次訓練沒有任何組數，已取消。')
        start = datetime.fromisoformat(workout['started_at'])
        # 補登過去日期時，開始時間是「那天＋按下開始的時刻」，結束也用同樣方式，時長才會是真實經過時間
        end = min(datetime.combine(start.date(), datetime.now().time()), datetime.combine(start.date(), time(23, 59)))
        end = end.replace(second=0, microsecond=0)
        if end <= start:
            end = start + timedelta(minutes=1)
        self.sql.finish_workout(workout_id, end.strftime('%Y-%m-%dT%H:%M'), int((end - start).total_seconds() // 60))
        self.sql.refresh_stats()
        self.sql.commit()
        return self._result(day, message='訓練已結束並儲存。')

    def add_set(self, workout_id, data):
        workout = self._owned_workout(workout_id)
        exercise = self._owned_exercise(Validator.identifier(data.get('exercise_id')))
        weight = Validator.number(data, 'weight_kg', '重量', 0, 1000)
        reps = Validator.number(data, 'reps', '次數', 1, 10000, integer=True)
        rpe = Validator.number(data, 'rpe', 'RPE', 1, 10, required=False, integer=True)
        set_no = self.sql.next_set_no(workout_id, exercise['id'])
        self.sql.insert_set(workout_id, exercise['id'], set_no, weight, reps, rpe)
        self.sql.refresh_stats()
        self.sql.commit()
        return self._result(date.fromisoformat(workout['workout_date']), exercise['id'],
                            rest=workout['ended_at'] is None)

    def delete_set(self, set_id):
        row = self.sql.owned_set(set_id)
        if not row:
            raise ApiError.not_found('找不到這一組。')
        self.sql.delete_set_and_renumber(row)
        self.sql.refresh_stats()
        self.sql.commit()
        return self._result(date.fromisoformat(row['workout_date']), row['exercise_id'])
