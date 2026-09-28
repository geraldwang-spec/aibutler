# -*- coding: utf-8 -*-
"""體重與訓練：對外的網址與 JSON API（只負責 HTTP，邏輯在 service.py，SQL 在 sql_process.py）。

  GET  /body/                         頁面外殼（內嵌第一份狀態 JSON；動作庫是空的會先寫入預設動作）
  GET  /body/api/state?d=&ex=         取得某天的完整狀態
  POST /body/api/weight               {d, weight_kg, body_fat_pct?, ex?}
  POST /body/api/workouts             {d, exercise_ids}    開始訓練（須先加好動作）
  POST /body/api/workouts/<id>/end    {}                   結束並儲存
  POST /body/api/workouts/<id>/sets   {exercise_id, weight_kg, reps, rpe?}
  POST /body/api/sets/<id>/delete     {}                   取消完成
所有 POST 需帶 X-CSRF-Token 標頭；回應一律為
  成功 {ok: true, message?, rest?, state}
  失敗 {ok: false, error}（HTTP 400 / 401 / 404）
"""
from functools import wraps

from flask import Blueprint, g, jsonify, render_template, request

from auth import login_required

from .errors import ApiError
from .service import BodyService, Validator
from .sql_process import BodySqlProcess

body = Blueprint('body', __name__, url_prefix='/body')


class BodyApi:
    """把 HTTP 請求轉給 BodyService，並把結果或錯誤包成 JSON。"""

    @staticmethod
    def service():
        # 同一個請求共用一個 service / 資料庫連線
        if 'body_service' not in g:
            g.body_service = BodyService(BodySqlProcess(g.user['id']))
        return g.body_service

    @staticmethod
    def payload():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def endpoint(view):
        """JSON API 用的裝飾器：未登入回 401、ApiError 回 {ok:false,error}，不轉址到 HTML 頁面。"""
        @wraps(view)
        def wrapped(*args, **kwargs):
            try:
                if g.user is None:
                    raise ApiError.unauthorized()
                return jsonify(ok=True, **view(*args, **kwargs))
            except ApiError as exc:
                if 'body_service' in g:
                    g.body_service.sql.rollback()
                return jsonify(ok=False, error=exc.message), exc.status
        return wrapped


api = BodyApi.endpoint


# ---------------------------------------------------------------- 頁面

@body.get('/')
@login_required
def index():
    tab = 'weight' if request.args.get('tab') == 'weight' else 'train'
    BodyApi.service().ensure_default_exercises()   # 動作庫是空的就先放入預設動作
    state = BodyApi.service().state(Validator.day(request.args.get('d')), request.args.get('ex', type=int))
    return render_template('body/index.html', title='體重與訓練', tab=tab, state=state)


# ---------------------------------------------------------------- JSON API

@body.get('/api/state')
@api
def state():
    service = BodyApi.service()
    return dict(state=service.state(Validator.day(request.args.get('d')), request.args.get('ex', type=int)))


@body.post('/api/weight')
@api
def save_weight():
    return BodyApi.service().save_weight(BodyApi.payload())


@body.post('/api/workouts')
@api
def start_workout():
    return BodyApi.service().start_workout(BodyApi.payload())


@body.post('/api/workouts/<int:workout_id>/end')
@api
def end_workout(workout_id):
    return BodyApi.service().end_workout(workout_id)


@body.post('/api/workouts/<int:workout_id>/sets')
@api
def add_set(workout_id):
    return BodyApi.service().add_set(workout_id, BodyApi.payload())


@body.post('/api/sets/<int:set_id>/delete')
@api
def delete_set(set_id):
    return BodyApi.service().delete_set(set_id)
