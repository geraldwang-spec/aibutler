# -*- coding: utf-8 -*-
"""body 模組所有的資料庫存取。

沿用既有資料表 body_metrics / exercises / workouts / workout_sets / daily_summary，不改 schema。
連線由 storage.db() 提供，依 .env 的 DB_TYPE 連 SQLite 或 MariaDB；
這裡的 SQL 都只用兩邊共通的語法（? 參數由 storage 自動轉成 MariaDB 的 %s）。
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

    def rate_limited(self, bucket, maximum, seconds):
        """沿用 rate_limits 資料表計數；超過次數回 True。SQLite 與 MariaDB 都能用（不用 BEGIN IMMEDIATE）。"""
        import time
        now = int(time.time())
        row = self.conn.execute('SELECT count, started_at FROM rate_limits WHERE bucket=?', (bucket,)).fetchone()
        if row and now - row['started_at'] < seconds:
            if row['count'] >= maximum:
                return True
            self.conn.execute('UPDATE rate_limits SET count=count+1 WHERE bucket=?', (bucket,))
        elif row:
            self.conn.execute('UPDATE rate_limits SET count=1, started_at=? WHERE bucket=?', (now, bucket))
        else:
            self.conn.execute('INSERT INTO rate_limits (bucket, count, started_at) VALUES (?, 1, ?)', (bucket, now))
        self.conn.commit()
        return False

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
        # 子查詢要有別名（MariaDB 規定），SQLite 也能用
        return self.conn.execute(
            'SELECT recent.record_date, recent.weight_kg FROM (SELECT record_date, weight_kg FROM body_metrics '
            'WHERE user_id=? AND record_date<=? ORDER BY record_date DESC LIMIT ?) AS recent ORDER BY recent.record_date',
            (self.user_id, until, limit)).fetchall()

    def upsert_metric(self, day, weight_kg, body_fat_pct):
        """同一天只有一筆：有就更新、沒有就新增。

        不用 SQLite 的 ON CONFLICT 或 MariaDB 的 ON DUPLICATE KEY，兩種資料庫都能用。
        """
        row = self.conn.execute('SELECT id FROM body_metrics WHERE user_id=? AND record_date=?',
                                (self.user_id, day)).fetchone()
        if row:
            self.conn.execute('UPDATE body_metrics SET weight_kg=?, body_fat_pct=? WHERE id=?',
                              (weight_kg, body_fat_pct, row['id']))
        else:
            self.conn.execute('INSERT INTO body_metrics (user_id,record_date,weight_kg,body_fat_pct) VALUES (?,?,?,?)',
                              (self.user_id, day, weight_kg, body_fat_pct))

    # ------------------------------------------------------------ 分析用（一次查出整段期間，不在迴圈裡逐筆查）
    def sets_between(self, start, end):
        """期間內每一組，附上日期、動作名稱與部位。"""
        return [dict(r) for r in self.conn.execute(
            'SELECT w.workout_date AS workout_date, w.id AS workout_id, s.exercise_id AS exercise_id, '
            'e.exercise_name AS exercise_name, e.muscle_group AS muscle_group, s.set_no AS set_no, '
            's.weight_kg AS weight_kg, s.reps AS reps '
            'FROM workout_sets s JOIN workouts w ON w.id=s.workout_id JOIN exercises e ON e.id=s.exercise_id '
            'WHERE w.user_id=? AND w.workout_date BETWEEN ? AND ? ORDER BY w.workout_date, w.id, s.id',
            (self.user_id, start, end))]

    def workouts_between(self, start, end):
        return [dict(r) for r in self.conn.execute(
            'SELECT id, workout_date, duration_min, ended_at FROM workouts '
            'WHERE user_id=? AND workout_date BETWEEN ? AND ? ORDER BY workout_date, id', (self.user_id, start, end))]

    def metrics_between(self, start, end):
        return [dict(r) for r in self.conn.execute(
            'SELECT record_date, weight_kg FROM body_metrics WHERE user_id=? AND record_date BETWEEN ? AND ? '
            'ORDER BY record_date', (self.user_id, start, end))]

    def last_trained_by_muscle(self, until):
        """每個部位最後一次訓練的日期（到 until 為止），{部位: 日期}。"""
        return {r['muscle_group']: r['last_date'] for r in self.conn.execute(
            'SELECT e.muscle_group AS muscle_group, MAX(w.workout_date) AS last_date '
            'FROM workout_sets s JOIN workouts w ON w.id=s.workout_id JOIN exercises e ON e.id=s.exercise_id '
            'WHERE w.user_id=? AND w.workout_date<=? GROUP BY e.muscle_group', (self.user_id, until)) if r['muscle_group']}

    # ------------------------------------------------------------ 個人資料與 AI 說明（ai_suggestions）
    def profile(self):
        row = self.conn.execute('SELECT goal_type, activity_level, workout_days_per_week, minutes_per_session '
                                'FROM user_profiles WHERE user_id=?', (self.user_id,)).fetchone()
        return dict(row) if row else {}

    def ai_suggestion(self, kind, sug_date):
        """取出某一期已產生的 AI 說明（type 例如 body_week，sug_date 是期間的第一天）。"""
        return self.conn.execute('SELECT id, content FROM ai_suggestions WHERE user_id=? AND type=? AND sug_date=? '
                                 'ORDER BY id DESC LIMIT 1', (self.user_id, kind, sug_date)).fetchone()

    def save_ai_suggestion(self, kind, sug_date, content):
        """同一期只保留一筆：有就更新、沒有就新增（兩種資料庫都能用的寫法）。"""
        row = self.ai_suggestion(kind, sug_date)
        if row:
            self.conn.execute('UPDATE ai_suggestions SET content=? WHERE id=?', (content, row['id']))
        else:
            self.conn.execute('INSERT INTO ai_suggestions (user_id, sug_date, type, content, accepted) VALUES (?,?,?,?,0)',
                              (self.user_id, sug_date, kind, content))

    # ------------------------------------------------------------ 教練文章（RAG）
    # 沿用既有的 materials → rag_documents → rag_chunks（＋rag_chunk_meta），不改資料表：
    #   materials.subject_id 留空、rag_documents.source_type = 'body'，跟其他模組的教材分開；
    #   materials.file_path 記錄做 embedding 用的模型（'embedding:<模型>'），body 不在硬碟存原始檔案。
    # 寫入用批次（executemany）＋最後一次 commit，經過 Tailscale 連遠端資料庫也只有少數幾次來回。
    SOURCE = 'body'

    def insert_document(self, title, file_type, embedding_model, chunks, vectors):
        """新增一篇文章與所有段落；回傳 material_id。由呼叫端 commit（失敗時 rollback，不會留下一半）。"""
        from .rag import VectorIndex
        self.conn.execute(
            'INSERT INTO materials (user_id, subject_id, title, file_path, file_type, page_count, parse_status) '
            'VALUES (?, NULL, ?, ?, ?, ?, ?)',
            (self.user_id, title, f'embedding:{embedding_model}', file_type, len(chunks), '完成'))
        material_id = self.conn.execute(
            'SELECT MAX(id) FROM materials WHERE user_id=? AND title=?', (self.user_id, title)).fetchone()[0]
        self.conn.execute('INSERT INTO rag_documents (source_type, material_id, title) VALUES (?,?,?)',
                          (self.SOURCE, material_id, title))
        doc_id = self.conn.execute('SELECT MAX(id) FROM rag_documents WHERE material_id=?', (material_id,)).fetchone()[0]
        self.conn.executemany(
            'INSERT INTO rag_chunks (doc_id, chunk_index, content, token_count, embedding) VALUES (?,?,?,?,?)',
            [(doc_id, c['index'], c['content'], len(c['content']), VectorIndex.to_blob(v)) for c, v in zip(chunks, vectors)])
        ids = [r[0] for r in self.conn.execute(
            'SELECT id FROM rag_chunks WHERE doc_id=? ORDER BY chunk_index', (doc_id,))]
        self.conn.executemany(
            'INSERT INTO rag_chunk_meta (chunk_id, source_locator, section_title) VALUES (?,?,?)',
            [(chunk_id, c.get('locator') or f"第 {c['index'] + 1} 段", c['section'] or None)
             for chunk_id, c in zip(ids, chunks)])
        return material_id

    def documents(self):
        """自己的教練文章列表（不含其他模組的教材）。"""
        return [dict(r) for r in self.conn.execute(
            'SELECT m.id AS id, m.title AS title, m.file_type AS file_type, m.page_count AS chunks, '
            'm.file_path AS file_path FROM materials m JOIN rag_documents d ON d.material_id=m.id '
            'WHERE m.user_id=? AND d.source_type=? ORDER BY m.id DESC', (self.user_id, self.SOURCE))]

    def document_count(self):
        return self.conn.execute(
            'SELECT COUNT(*) FROM materials m JOIN rag_documents d ON d.material_id=m.id '
            'WHERE m.user_id=? AND d.source_type=?', (self.user_id, self.SOURCE)).fetchone()[0]

    def delete_document(self, material_id):
        """刪除自己的一篇文章（段落、出處資訊、文件、教材都刪）；不是自己的或不是 body 的文章回 False。"""
        doc = self.conn.execute(
            'SELECT d.id FROM rag_documents d JOIN materials m ON m.id=d.material_id '
            'WHERE m.id=? AND m.user_id=? AND d.source_type=?', (material_id, self.user_id, self.SOURCE)).fetchone()
        if not doc:
            return False
        chunk_ids = [r[0] for r in self.conn.execute('SELECT id FROM rag_chunks WHERE doc_id=?', (doc[0],))]
        if chunk_ids:
            marks = ','.join('?' * len(chunk_ids))
            self.conn.execute(f'DELETE FROM rag_chunk_meta WHERE chunk_id IN ({marks})', chunk_ids)
        self.conn.execute('DELETE FROM rag_chunks WHERE doc_id=?', (doc[0],))
        self.conn.execute('DELETE FROM rag_documents WHERE id=?', (doc[0],))
        self.conn.execute('DELETE FROM materials WHERE id=? AND user_id=?', (material_id, self.user_id))
        return True

    def chunks_for_search(self):
        """自己所有教練文章的段落與向量（檢索用）；一定經過 materials.user_id 檢查。"""
        return [dict(r) for r in self.conn.execute(
            'SELECT c.id AS id, c.content AS content, c.embedding AS embedding, c.chunk_index AS chunk_index, '
            'm.id AS material_id, m.title AS title, m.file_path AS file_path, meta.section_title AS section, '
            'meta.source_locator AS locator '
            'FROM rag_chunks c JOIN rag_documents d ON d.id=c.doc_id JOIN materials m ON m.id=d.material_id '
            'LEFT JOIN rag_chunk_meta meta ON meta.chunk_id=c.id '
            'WHERE m.user_id=? AND d.source_type=?', (self.user_id, self.SOURCE))]

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

    def insert_exercise(self, name, muscle_group, equipment, is_cardio):
        """新增一個動作，回傳新動作的 id（用查詢取回，不依賴 lastrowid，各種資料庫都能用）。"""
        self.conn.execute('INSERT INTO exercises (exercise_name, muscle_group, equipment, is_cardio, created_by) '
                          'VALUES (?,?,?,?,?)', (name, muscle_group, equipment, 1 if is_cardio else 0, self.user_id))
        return self.conn.execute('SELECT MAX(id) FROM exercises WHERE created_by=? AND exercise_name=?',
                                 (self.user_id, name)).fetchone()[0]

    def insert_default_exercises(self, exercises):
        """動作庫是空的才一次寫入預設動作；已經有任何動作就什麼都不做。

        用單一 INSERT ... SELECT ... WHERE NOT EXISTS，同時開兩個分頁也不會重複寫入；
        預設動作用 UNION ALL 組成子查詢，SQLite 與 MariaDB 都能用。
        exercises: [(名稱, 部位, 器材, 是否有氧), ...]；回傳實際寫入的筆數。
        """
        if not exercises:
            return 0
        first = 'SELECT ? AS exercise_name, ? AS muscle_group, ? AS equipment, ? AS is_cardio'
        rows = ' UNION ALL '.join([first] + ['SELECT ?, ?, ?, ?'] * (len(exercises) - 1))
        params = [v for row in exercises for v in row]
        cursor = self.conn.execute(
            'INSERT INTO exercises (exercise_name, muscle_group, equipment, is_cardio, created_by) '
            f'SELECT d.exercise_name, d.muscle_group, d.equipment, d.is_cardio, ? FROM ({rows}) AS d '
            'WHERE NOT EXISTS (SELECT 1 FROM exercises WHERE created_by=?)',
            (self.user_id, *params, self.user_id))
        return cursor.rowcount

    def exercise_usage(self, since):
        """since 之後每個動作做過幾組，{exercise_id: 組數}；一句話輸入時用來排序候選動作。"""
        return {r['exercise_id']: r['n'] for r in self.conn.execute(
            'SELECT s.exercise_id AS exercise_id, COUNT(*) AS n FROM workout_sets s JOIN workouts w ON w.id=s.workout_id '
            'WHERE w.user_id=? AND w.workout_date>=? GROUP BY s.exercise_id', (self.user_id, since))}

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
