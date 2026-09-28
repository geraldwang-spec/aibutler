# -*- coding: utf-8 -*-
"""body 模組所有的資料庫存取。

沿用既有資料表 body_metrics / exercises / workouts / workout_sets / daily_summary，不改 schema。
每個查詢都限定在建構時傳入的 user_id，避免讀寫到別人的資料。
這裡只做 SQL，不做驗證或商業規則（那些在 service.py）。
"""
from storage import db


class BodySqlProcess:
    def __init__(self, user_id, connection=None):
        self.user_id = user_id
        self.conn = connection if connection is not None else db()

    # ------------------------------------------------------------ 交易
    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def refresh_stats(self):
        """重算 daily_summary（沿用 smartlife 的共用函式）；由呼叫端決定何時 commit。"""
        # 延遲匯入，避免與 smartlife.create_app 互相匯入
        from smartlife import refresh_stats
        refresh_stats(commit=False)

    # ------------------------------------------------------------ 體重 body_metrics
    def metric_on(self, day):
        return self.conn.execute(
            'SELECT weight_kg, body_fat_pct FROM body_metrics WHERE user_id=? AND record_date=?',
            (self.user_id, day)).fetchone()

    def latest_metric(self, on_or_before):
        return self.conn.execute(
            'SELECT record_date, weight_kg FROM body_metrics WHERE user_id=? AND record_date<=? '
            'ORDER BY record_date DESC LIMIT 1', (self.user_id, on_or_before)).fetchone()

    def recent_metrics(self, until, limit=7):
        """最近 limit 筆（到 until 為止），依日期由舊到新。"""
        return self.conn.execute(
            'SELECT * FROM (SELECT record_date, weight_kg FROM body_metrics WHERE user_id=? AND record_date<=? '
            'ORDER BY record_date DESC LIMIT ?) ORDER BY record_date', (self.user_id, until, limit)).fetchall()

    def upsert_metric(self, day, weight_kg, body_fat_pct):
        self.conn.execute(
            'INSERT INTO body_metrics (user_id,record_date,weight_kg,body_fat_pct) VALUES (?,?,?,?) '
            'ON CONFLICT(user_id,record_date) DO UPDATE SET weight_kg=excluded.weight_kg, body_fat_pct=excluded.body_fat_pct',
            (self.user_id, day, weight_kg, body_fat_pct))

    # ------------------------------------------------------------ 動作庫 exercises

    # 動作庫的部位排序（與 records.py 的選項順序一致），其他部位排最後
    MUSCLE_ORDER = ('胸', '背', '腿', '肩', '手臂', '核心')

    def exercises(self):
        order = ' '.join(f"WHEN '{m}' THEN {i}" for i, m in enumerate(self.MUSCLE_ORDER))
        return self.conn.execute(
            f'SELECT * FROM exercises WHERE created_by=? ORDER BY CASE muscle_group {order} ELSE 99 END, muscle_group, id',
            (self.user_id,)).fetchall()

    def latest_sessions_before(self, day, since):
        """每個動作在 day 之前「最近一次」訓練的各組，回傳 {exercise_id: [row, ...]}。

        只看 since 之後的紀錄，避免資料多了以後整張表掃過一遍。
        """
        rows = self.conn.execute(
            'SELECT s.exercise_id, s.set_no, s.weight_kg, s.reps, w.id AS workout_id '
            'FROM workout_sets s JOIN workouts w ON w.id=s.workout_id '
            'WHERE w.user_id=? AND w.workout_date<? AND w.workout_date>=? '
            'ORDER BY w.workout_date DESC, w.id DESC, s.set_no, s.id', (self.user_id, day, since)).fetchall()
        chosen, sessions = {}, {}
        for r in rows:
            chosen.setdefault(r['exercise_id'], r['workout_id'])
            if chosen[r['exercise_id']] == r['workout_id']:
                sessions.setdefault(r['exercise_id'], []).append(r)
        return sessions

    def insert_default_exercises(self, exercises):
        """動作庫是空的才一次寫入預設動作；已經有任何動作就什麼都不做。

        用單一 INSERT ... SELECT ... WHERE NOT EXISTS，同時開兩個分頁也不會重複寫入。
        exercises: [(名稱, 部位, 器材, 是否有氧), ...]；回傳實際寫入的筆數。
        """
        if not exercises:
            return 0
        values = ','.join(['(?,?,?,?)'] * len(exercises))
        params = [v for row in exercises for v in row]
        cursor = self.conn.execute(
            f'WITH defaults(exercise_name, muscle_group, equipment, is_cardio) AS (VALUES {values}) '
            'INSERT INTO exercises (exercise_name, muscle_group, equipment, is_cardio, created_by) '
            'SELECT exercise_name, muscle_group, equipment, is_cardio, ? FROM defaults '
            'WHERE NOT EXISTS (SELECT 1 FROM exercises WHERE created_by=?)',
            (*params, self.user_id, self.user_id))
        return cursor.rowcount

    def exercise(self, exercise_id):
        return self.conn.execute(
            'SELECT * FROM exercises WHERE id=? AND created_by=?', (exercise_id, self.user_id)).fetchone()

    # ------------------------------------------------------------ 週曆
    def trained_dates(self, start, end):
        return {r[0] for r in self.conn.execute(
            'SELECT DISTINCT workout_date FROM workouts WHERE user_id=? AND workout_date BETWEEN ? AND ?',
            (self.user_id, start, end))}

    def muscle_groups_by_date(self, start, end):
        groups = {}
        for r in self.conn.execute(
                'SELECT DISTINCT w.workout_date, e.muscle_group FROM workout_sets s '
                'JOIN workouts w ON w.id=s.workout_id JOIN exercises e ON e.id=s.exercise_id '
                'WHERE w.user_id=? AND w.workout_date BETWEEN ? AND ?', (self.user_id, start, end)):
            if r[1]:
                groups.setdefault(r[0], []).append(r[1])
        return groups

    # ------------------------------------------------------------ 訓練 workouts
    def workout(self, workout_id):
        return self.conn.execute(
            'SELECT * FROM workouts WHERE id=? AND user_id=?', (workout_id, self.user_id)).fetchone()

    def latest_workout_on(self, day):
        return self.conn.execute(
            'SELECT * FROM workouts WHERE user_id=? AND workout_date=? ORDER BY id DESC LIMIT 1',
            (self.user_id, day)).fetchone()

    def running_workout_on(self, day):
        return self.conn.execute(
            'SELECT * FROM workouts WHERE user_id=? AND workout_date=? AND ended_at IS NULL',
            (self.user_id, day)).fetchone()

    def create_workout(self, day, started_at):
        cursor = self.conn.execute(
            'INSERT INTO workouts (user_id,workout_date,started_at,duration_min,total_volume) VALUES (?,?,?,0,0)',
            (self.user_id, day, started_at))
        return cursor.lastrowid

    def finish_workout(self, workout_id, ended_at, duration_min):
        self.conn.execute('UPDATE workouts SET ended_at=?, duration_min=? WHERE id=? AND user_id=?',
                          (ended_at, duration_min, workout_id, self.user_id))

    def delete_workout(self, workout_id):
        self.conn.execute('DELETE FROM workouts WHERE id=? AND user_id=?', (workout_id, self.user_id))

    def workout_has_sets(self, workout_id):
        return self.conn.execute('SELECT 1 FROM workout_sets WHERE workout_id=? LIMIT 1', (workout_id,)).fetchone() is not None

    # ------------------------------------------------------------ 組 workout_sets
    def sets_of(self, workout_id):
        return self.conn.execute(
            'SELECT * FROM workout_sets WHERE workout_id=? ORDER BY set_no, id', (workout_id,)).fetchall()

    def exercise_order(self, workout_id):
        """這次訓練出現過的動作，依第一次記錄的先後排序。"""
        return [r[0] for r in self.conn.execute(
            'SELECT exercise_id FROM workout_sets WHERE workout_id=? GROUP BY exercise_id ORDER BY min(id)', (workout_id,))]

    def next_set_no(self, workout_id, exercise_id):
        return self.conn.execute(
            'SELECT COALESCE(max(set_no),0)+1 FROM workout_sets WHERE workout_id=? AND exercise_id=?',
            (workout_id, exercise_id)).fetchone()[0]

    def insert_set(self, workout_id, exercise_id, set_no, weight_kg, reps, rpe):
        self.conn.execute(
            'INSERT INTO workout_sets (workout_id,exercise_id,set_no,weight_kg,reps,rpe) VALUES (?,?,?,?,?,?)',
            (workout_id, exercise_id, set_no, weight_kg, reps, rpe))

    def owned_set(self, set_id):
        """取得一組（含所屬訓練的日期），只限自己的資料。"""
        return self.conn.execute(
            'SELECT s.*, w.workout_date FROM workout_sets s JOIN workouts w ON w.id=s.workout_id '
            'WHERE s.id=? AND w.user_id=?', (set_id, self.user_id)).fetchone()

    def delete_set_and_renumber(self, row):
        """刪除一組，並把同動作後面的組號往前補。"""
        self.conn.execute('DELETE FROM workout_sets WHERE id=?', (row['id'],))
        self.conn.execute(
            'UPDATE workout_sets SET set_no=set_no-1 WHERE workout_id=? AND exercise_id=? AND set_no>?',
            (row['workout_id'], row['exercise_id'], row['set_no']))

    def previous_session_sets(self, exercise_id, workout):
        """同一動作「上一次」訓練的各組，回傳 {set_no: row}。"""
        prev = self.conn.execute(
            'SELECT w.id FROM workouts w JOIN workout_sets s ON s.workout_id=w.id '
            'WHERE w.user_id=? AND s.exercise_id=? AND (w.workout_date<? OR (w.workout_date=? AND w.id<?)) '
            'ORDER BY w.workout_date DESC, w.id DESC LIMIT 1',
            (self.user_id, exercise_id, workout['workout_date'], workout['workout_date'], workout['id'])).fetchone()
        if not prev:
            return {}
        rows = self.conn.execute(
            'SELECT * FROM workout_sets WHERE workout_id=? AND exercise_id=? ORDER BY set_no, id',
            (prev['id'], exercise_id)).fetchall()
        return {r['set_no']: r for r in rows}
