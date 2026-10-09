# -*- coding: utf-8 -*-
"""體重與訓練：對外的網址與 JSON API（只負責 HTTP，邏輯在 service.py，SQL 在 sql_process.py）。

  GET  /body/                         頁面外殼（內嵌第一份狀態 JSON；動作庫是空的會先寫入預設動作）
  GET  /body/api/state?d=&ex=         取得某天的完整狀態
  GET  /body/api/report?period=week|month&d=   訓練分析（只讀）
  POST /body/api/parse                {text}               一句話輸入 → 草稿（不寫資料庫）
  POST /body/api/exercises            {name, muscle_group, equipment, is_cardio, d}   新增動作
  POST /body/api/weight               {d, weight_kg, body_fat_pct?, ex?}
  POST /body/api/workouts             {d, exercise_ids}    開始訓練（須先加好動作）
  POST /body/api/workouts/<id>/end    {}                   結束並儲存
  POST /body/api/workouts/<id>/sets   {exercise_id, weight_kg, reps, rpe?}
  POST /body/api/sets/<id>/delete     {}                   取消完成
所有 POST 需帶 X-CSRF-Token 標頭；回應一律為
  成功 {ok: true, message?, rest?, state}
  失敗 {ok: false, error}（HTTP 400 / 401 / 404）
"""
import json
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, render_template, request, abort

from auth import login_required

from .errors import ApiError
from .llm_client import BodyLlmClient
from .service import BodyService, Validator
from .sql_process import BodySqlProcess

body = Blueprint('body', __name__, url_prefix='/body')


@body.app_template_global()
def exercise_media(name):
    from .exercise_media import media_for
    return media_for(name)


@body.get('/exercises/<int:exercise_id>/demo')
@login_required
def exercise_demo(exercise_id):
    from storage import db
    row = db().execute('SELECT * FROM exercises WHERE id=? AND created_by=?',
                       (exercise_id, g.user['id'])).fetchone()
    if row is None:
        abort(404)
    return render_template('body/exercise_demo.html', title=row['exercise_name'] + ' · 動作示範',
                           exercise=row, media=exercise_media(row['exercise_name']))


class BodyApi:
    """把 HTTP 請求轉給 BodyService，並把結果或錯誤包成 JSON。"""

    config_file = Path(__file__).with_name('body.env')   # body 自己的設定檔（不讀專案 .env）
    _llm = None            # 依設定檔建立一次（改設定後要重新啟動）
    _llm_loaded = False

    @classmethod
    def llm_parse(cls):
        """回傳給 BodyService 用的 LLM 函式；body/body.env 沒設定 BODY_LLM_* 就回 None（只用規則解析）。"""
        if not cls._llm_loaded:
            cls._llm, cls._llm_loaded = BodyLlmClient.from_file(cls.config_file), True
        client = cls._llm
        if client is None:
            return None

        def parse(messages):
            result = client.chat_json(messages)
            usage = dict(model=client.model, input_tokens=result['input_tokens'],
                         output_tokens=result['output_tokens'], latency_ms=result['latency_ms'])
            BodyApi.log_usage(usage)
            return result['data'], usage
        return parse

    @staticmethod
    def log_usage(usage):
        """把每次 AI 呼叫的用量與延遲寫到 instance/body_llm_usage.jsonl（成本控制與報告素材）。

        只記錄數字，不記錄使用者輸入的內容；instance/ 已排除 Git。寫檔失敗不影響功能。
        """
        line = dict(time=datetime.now().isoformat(timespec='seconds'), user=g.user['id'], feature='parse', **usage)
        try:
            path = Path(current_app.instance_path) / 'body_llm_usage.jsonl'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as file:
                file.write(json.dumps(line, ensure_ascii=False) + '\n')
        except OSError:
            current_app.logger.warning('body llm usage log failed')

    @staticmethod
    def service():
        # 同一個請求共用一個 service / 資料庫連線
        if 'body_service' not in g:
            g.body_service = BodyService(BodySqlProcess(g.user['id']), llm_parse=BodyApi.llm_parse())
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
    tab = request.args.get('tab') if request.args.get('tab') in ('weight', 'analysis') else 'train'
    BodyApi.service().ensure_default_exercises()   # 動作庫是空的就先放入預設動作
    state = BodyApi.service().state(Validator.day(request.args.get('d')), request.args.get('ex', type=int))
    return render_template('body/index.html', title='體重與訓練', tab=tab, state=state)


# ---------------------------------------------------------------- JSON API

@body.get('/api/state')
@api
def state():
    service = BodyApi.service()
    return dict(state=service.state(Validator.day(request.args.get('d')), request.args.get('ex', type=int)))


@body.get('/api/report')
@api
def report():
    """訓練分析（週／月）：只讀資料，不寫入。"""
    period = request.args.get('period', 'week')
    return dict(report=BodyApi.service().report(period, Validator.day(request.args.get('d'))))


@body.post('/api/parse')
@api
def parse_text():
    """一句話輸入：只回傳草稿，不寫資料庫。"""
    return BodyApi.service().parse_text(BodyApi.payload())


@body.post('/api/exercises')
@api
def create_exercise():
    """新增動作（使用者在確認表單填好部位、器材、是否有氧後送出）。回傳新動作與最新狀態。"""
    data = BodyApi.payload()
    service = BodyApi.service()
    result = service.create_exercise(data)
    return dict(result, state=service.state(Validator.day(data.get('d')), result['exercise']['id']))


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
