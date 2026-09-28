# -*- coding: utf-8 -*-
"""體重與訓練：一頁完成體重、訓練與逐組紀錄（仿 Burnfit 操作）。

前後端以 JSON 溝通：
  GET  /body/                         頁面外殼（內嵌第一份狀態 JSON，免多一次請求）
  GET  /body/api/state?d=&ex=         取得某天的完整狀態
  POST /body/api/weight               {d, weight_kg, body_fat_pct?, ex?}
  POST /body/api/workouts             {d, exercise_ids}    開始訓練（須先加好動作）
  POST /body/api/workouts/<id>/end    {}                   結束並儲存
  POST /body/api/workouts/<id>/sets   {exercise_id, weight_kg, reps, rpe?}
  POST /body/api/sets/<id>/delete     {}                   取消完成
所有 POST 需帶 X-CSRF-Token 標頭；回應一律為
  成功 {ok: true, message?, rest?, state}
  失敗 {ok: false, error}（HTTP 400 / 401 / 404）

沿用既有資料表 body_metrics / exercises / workouts / workout_sets，不改 schema。
- 進行中的訓練：workouts.ended_at 為 NULL。
- 「完成一組」＝寫入一筆 workout_sets；「取消完成」＝刪除該筆並重新編號。
- 開始前要先排好「今天要做的動作」。清單是還沒記錄的草稿，存在瀏覽器（localStorage），
  開始時一起送到後端檢查；做完第一組後才會寫進 workout_sets。
"""
import math
from datetime import date, datetime, time, timedelta
from functools import wraps

from flask import Blueprint, g, jsonify, render_template, request

from auth import login_required
from storage import db

body = Blueprint('body', __name__, url_prefix='/body')

WEEKDAYS = '一二三四五六日'


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def api(view):
    """JSON API：未登入回 401、錯誤回 {ok:false,error}，不轉址到 HTML 頁面。"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return jsonify(ok=False, error='登入已逾時，請重新登入。'), 401
        try:
            return view(*args, **kwargs)
        except ApiError as exc:
            db().rollback()
            return jsonify(ok=False, error=exc.message), exc.status
    return wrapped


# ---------------------------------------------------------------- helpers

def _payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _day(value):
    try:
        return date.fromisoformat(value) if value else date.today()
    except (TypeError, ValueError):
        return date.today()


def _num(data, name, label, low, high, required=True, integer=False):
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


def _id(data, name):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise ApiError('請選擇動作。')
    return int(value)


def _wanted(data):
    """前端目前正在看的動作（讓重繪後停在同一個動作）。"""
    value = data.get('ex')
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _workout(workout_id):
    row = db().execute('SELECT * FROM workouts WHERE id=? AND user_id=?', (workout_id, g.user['id'])).fetchone()
    if not row:
        raise ApiError('找不到這次訓練。', 404)
    return row


def _exercise(exercise_id):
    row = db().execute('SELECT * FROM exercises WHERE id=? AND created_by=?', (exercise_id, g.user['id'])).fetchone()
    if not row:
        raise ApiError('找不到這個動作。', 404)
    return row


def _refresh():
    # 延遲匯入，避免與 smartlife.create_app 互相匯入
    from smartlife import refresh_stats
    refresh_stats(commit=False)


def _pair(row):
    return dict(weight_kg=row['weight_kg'], reps=row['reps']) if row else None


def _previous_session(exercise_id, workout):
    """同一動作「上一次」訓練的各組，{set_no: row}。"""
    prev = db().execute(
        'SELECT w.id FROM workouts w JOIN workout_sets s ON s.workout_id=w.id '
        'WHERE w.user_id=? AND s.exercise_id=? AND (w.workout_date<? OR (w.workout_date=? AND w.id<?)) '
        'ORDER BY w.workout_date DESC, w.id DESC LIMIT 1',
        (g.user['id'], exercise_id, workout['workout_date'], workout['workout_date'], workout['id'])).fetchone()
    if not prev:
        return {}
    rows = db().execute('SELECT * FROM workout_sets WHERE workout_id=? AND exercise_id=? ORDER BY set_no, id',
                        (prev['id'], exercise_id)).fetchall()
    return {r['set_no']: r for r in rows}


# ---------------------------------------------------------------- state

def _state(day, wanted=None):
    """某一天的完整畫面資料（只放原始數值，格式化交給前端）。"""
    uid = g.user['id']
    today = date.today()
    d = day.isoformat()

    # 週日曆條（週一開始）
    monday = day - timedelta(days=day.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]
    span = (week_dates[0].isoformat(), week_dates[-1].isoformat())
    trained = {r[0] for r in db().execute(
        'SELECT DISTINCT workout_date FROM workouts WHERE user_id=? AND workout_date BETWEEN ? AND ?', (uid, *span))}
    groups_by_day = {}
    for r in db().execute(
            'SELECT DISTINCT w.workout_date, e.muscle_group FROM workout_sets s JOIN workouts w ON w.id=s.workout_id '
            'JOIN exercises e ON e.id=s.exercise_id WHERE w.user_id=? AND w.workout_date BETWEEN ? AND ?', (uid, *span)):
        if r[1]:
            groups_by_day.setdefault(r[0], []).append(r[1])
    week = [dict(d=x.isoformat(), weekday=WEEKDAYS[x.weekday()], day=x.day, selected=x == day, today=x == today,
                 trained=x.isoformat() in trained, groups=groups_by_day.get(x.isoformat(), []))
            for x in week_dates]

    # 體重
    record = db().execute('SELECT weight_kg, body_fat_pct FROM body_metrics WHERE user_id=? AND record_date=?',
                          (uid, d)).fetchone()
    latest = db().execute('SELECT record_date, weight_kg FROM body_metrics WHERE user_id=? AND record_date<=? '
                          'ORDER BY record_date DESC LIMIT 1', (uid, d)).fetchone()
    delta = None
    if latest:
        base = db().execute('SELECT weight_kg FROM body_metrics WHERE user_id=? AND record_date<=? ORDER BY record_date DESC LIMIT 1',
                            (uid, (date.fromisoformat(latest['record_date']) - timedelta(days=7)).isoformat())).fetchone()
        if base:
            delta = round(latest['weight_kg'] - base['weight_kg'], 1)
    trend = [dict(d=r['record_date'], weight_kg=r['weight_kg']) for r in db().execute(
        'SELECT * FROM (SELECT record_date, weight_kg FROM body_metrics WHERE user_id=? AND record_date<=? '
        'ORDER BY record_date DESC LIMIT 7) ORDER BY record_date', (uid, d))]

    # 動作庫
    library = [dict(id=r['id'], name=r['exercise_name'], muscle_group=r['muscle_group'], equipment=r['equipment'])
               for r in db().execute('SELECT * FROM exercises WHERE created_by=? ORDER BY muscle_group, exercise_name', (uid,))]
    lib = {e['id']: e for e in library}

    # 訓練
    workout_row = db().execute('SELECT * FROM workouts WHERE user_id=? AND workout_date=? ORDER BY id DESC LIMIT 1',
                               (uid, d)).fetchone()
    workout, current = None, None
    if workout_row:
        sets = db().execute('SELECT * FROM workout_sets WHERE workout_id=? ORDER BY set_no, id', (workout_row['id'],)).fetchall()
        order = [r[0] for r in db().execute('SELECT exercise_id FROM workout_sets WHERE workout_id=? '
                                            'GROUP BY exercise_id ORDER BY min(id)', (workout_row['id'],))]
        if wanted in lib and wanted not in order:
            order.append(wanted)
        if wanted in order:
            current_id = wanted
        elif sets:
            current_id = max(sets, key=lambda s: s['id'])['exercise_id']
        else:
            current_id = None

        exercises, groups = [], []
        for ex_id in order:
            info = lib.get(ex_id, dict(id=ex_id, name=f'動作 #{ex_id}', muscle_group=None, equipment=None))
            mine = [s for s in sets if s['exercise_id'] == ex_id]
            if mine and info['muscle_group'] and info['muscle_group'] not in groups:
                groups.append(info['muscle_group'])
            exercises.append(dict(info, done=len(mine), volume=sum((s['weight_kg'] or 0) * (s['reps'] or 0) for s in mine)))
            if ex_id == current_id:
                prev = _previous_session(ex_id, workout_row)
                best = max(prev.values(), key=lambda r: ((r['weight_kg'] or 0), (r['reps'] or 0)), default=None)
                next_no = (mine[-1]['set_no'] if mine else 0) + 1
                seed = mine[-1] if mine else prev.get(next_no)
                current = dict(
                    exercise_id=ex_id, name=info['name'], muscle_group=info['muscle_group'], equipment=info['equipment'],
                    best=_pair(best),
                    sets=[dict(id=s['id'], set_no=s['set_no'], weight_kg=s['weight_kg'], reps=s['reps'], rpe=s['rpe'],
                               last=_pair(prev.get(s['set_no']))) for s in mine],
                    next=dict(set_no=next_no, last=_pair(prev.get(next_no)),
                              weight_kg=seed['weight_kg'] if seed else None, reps=seed['reps'] if seed else None))
        workout = dict(id=workout_row['id'], started_at=workout_row['started_at'], ended_at=workout_row['ended_at'],
                       in_progress=workout_row['ended_at'] is None, duration_min=workout_row['duration_min'] or 0,
                       volume=sum((s['weight_kg'] or 0) * (s['reps'] or 0) for s in sets),
                       set_count=len(sets), groups=groups, exercises=exercises)

    return dict(
        d=d, today=today.isoformat(), is_future=day > today, weekday=WEEKDAYS[day.weekday()],
        prev_week=(monday - timedelta(days=7)).isoformat(), next_week=(monday + timedelta(days=7)).isoformat(),
        week=week,
        weight=dict(record=dict(record) if record else None, latest=dict(latest) if latest else None,
                    delta=delta, trend=trend),
        library=library, workout=workout, current=current)


def _ok(day, wanted=None, **extra):
    return jsonify(ok=True, state=_state(day, wanted), **extra)


# ---------------------------------------------------------------- page

@body.get('/')
@login_required
def index():
    day = _day(request.args.get('d'))
    tab = 'weight' if request.args.get('tab') == 'weight' else 'train'
    return render_template('body/index.html', title='體重與訓練', tab=tab,
                           state=_state(day, request.args.get('ex', type=int)))


# ---------------------------------------------------------------- JSON API

@body.get('/api/state')
@api
def state():
    return _ok(_day(request.args.get('d')), request.args.get('ex', type=int))


@body.post('/api/weight')
@api
def save_weight():
    data = _payload()
    day = _day(data.get('d'))
    if day > date.today():
        raise ApiError('不能記錄未來日期的體重。')
    weight = _num(data, 'weight_kg', '體重', 1, 600)
    fat = _num(data, 'body_fat_pct', '體脂率', 0, 100, required=False)
    db().execute('INSERT INTO body_metrics (user_id,record_date,weight_kg,body_fat_pct) VALUES (?,?,?,?) '
                 'ON CONFLICT(user_id,record_date) DO UPDATE SET weight_kg=excluded.weight_kg, body_fat_pct=excluded.body_fat_pct',
                 (g.user['id'], day.isoformat(), weight, fat))
    db().commit()
    return _ok(day, _wanted(data), message='體重已儲存。')


@body.post('/api/workouts')
@api
def start_workout():
    """先加好動作才能開始：exercise_ids 至少一個，而且都要是自己動作庫裡的動作。"""
    data = _payload()
    day = _day(data.get('d'))
    if day > date.today():
        raise ApiError('不能在未來的日期開始訓練。')
    ids = data.get('exercise_ids')
    if not isinstance(ids, list) or not ids:
        raise ApiError('請先加入至少一個動作，再開始訓練。')
    exercise_ids = []
    for value in ids:
        if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
            raise ApiError('動作格式不正確。')
        exercise_id = _exercise(int(value))['id']
        if exercise_id not in exercise_ids:
            exercise_ids.append(exercise_id)
    running = db().execute('SELECT id FROM workouts WHERE user_id=? AND workout_date=? AND ended_at IS NULL',
                           (g.user['id'], day.isoformat())).fetchone()
    if not running:
        now = datetime.now()
        started = now if day == date.today() else datetime.combine(day, now.time())
        db().execute('INSERT INTO workouts (user_id,workout_date,started_at,duration_min,total_volume) VALUES (?,?,?,0,0)',
                     (g.user['id'], day.isoformat(), started.strftime('%Y-%m-%dT%H:%M')))
        db().commit()
    return _ok(day, exercise_ids[0])


@body.post('/api/workouts/<int:workout_id>/end')
@api
def end_workout(workout_id):
    workout = _workout(workout_id)
    day = date.fromisoformat(workout['workout_date'])
    if workout['ended_at']:
        return _ok(day)
    if not db().execute('SELECT 1 FROM workout_sets WHERE workout_id=?', (workout_id,)).fetchone():
        db().execute('DELETE FROM workouts WHERE id=?', (workout_id,))
        db().commit()
        return _ok(day, message='這次訓練沒有任何組數，已取消。')
    start = datetime.fromisoformat(workout['started_at'])
    # 補登過去日期時，開始時間是「那天＋按下開始的時刻」，結束也用同樣方式，時長才會是真實經過時間
    end = min(datetime.combine(start.date(), datetime.now().time()), datetime.combine(start.date(), time(23, 59)))
    end = end.replace(second=0, microsecond=0)
    if end <= start:
        end = start + timedelta(minutes=1)
    db().execute('UPDATE workouts SET ended_at=?, duration_min=? WHERE id=?',
                 (end.strftime('%Y-%m-%dT%H:%M'), int((end - start).total_seconds() // 60), workout_id))
    _refresh()
    db().commit()
    return _ok(day, message='訓練已結束並儲存。')


@body.post('/api/workouts/<int:workout_id>/sets')
@api
def add_set(workout_id):
    data = _payload()
    workout = _workout(workout_id)
    exercise = _exercise(_id(data, 'exercise_id'))
    weight = _num(data, 'weight_kg', '重量', 0, 1000)
    reps = _num(data, 'reps', '次數', 1, 10000, integer=True)
    rpe = _num(data, 'rpe', 'RPE', 1, 10, required=False, integer=True)
    set_no = db().execute('SELECT COALESCE(max(set_no),0)+1 FROM workout_sets WHERE workout_id=? AND exercise_id=?',
                          (workout_id, exercise['id'])).fetchone()[0]
    db().execute('INSERT INTO workout_sets (workout_id,exercise_id,set_no,weight_kg,reps,rpe) VALUES (?,?,?,?,?,?)',
                 (workout_id, exercise['id'], set_no, weight, reps, rpe))
    _refresh()
    db().commit()
    return _ok(date.fromisoformat(workout['workout_date']), exercise['id'], rest=workout['ended_at'] is None)


@body.post('/api/sets/<int:set_id>/delete')
@api
def delete_set(set_id):
    row = db().execute('SELECT s.*, w.workout_date FROM workout_sets s JOIN workouts w ON w.id=s.workout_id '
                       'WHERE s.id=? AND w.user_id=?', (set_id, g.user['id'])).fetchone()
    if not row:
        raise ApiError('找不到這一組。', 404)
    db().execute('DELETE FROM workout_sets WHERE id=?', (set_id,))
    db().execute('UPDATE workout_sets SET set_no=set_no-1 WHERE workout_id=? AND exercise_id=? AND set_no>?',
                 (row['workout_id'], row['exercise_id'], row['set_no']))
    _refresh()
    db().commit()
    return _ok(date.fromisoformat(row['workout_date']), row['exercise_id'])
