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
import json
import math
import re
from datetime import date, datetime, time, timedelta

from modules.document_parser import DocumentParseError, DocumentParser

from .ai_report import AiReport
from .analysis import TrainingAnalysis
from .errors import ApiError
from .llm_client import LlmError
from .prompts import Prompts
from .rag import TextChunker, VectorIndex
from .sql_process import BodySqlProcess
from .text_parser import ExerciseGuesser, WorkoutTextParser
from .workout_plan import WorkoutPlan

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
    ('槌式胸推', '胸', '機械', 0),
    ('獨立式上斜胸推機', '胸', '機械', 0),
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
    ('單臂坐姿滑輪划船','背', '纜繩', 0),
    ('低位划船機','背', '機械', 0),
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
    ('單腿腿屈伸', '腿', '機械', 0),
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
    ('肩推機', '肩', '機械', 0),
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

# 每個使用者每小時最多呼叫幾次 AI 解析（規則解析不受限制）
LLM_PARSE_PER_HOUR = 30
# 每個使用者每小時最多產生幾次 AI 分析說明（同一期資料沒變時直接用存好的，不算次數）
LLM_REPORT_PER_HOUR = 10
# 每個使用者每小時最多產生幾次 AI 建議課表（沒設定 AI 時用程式選擇，不算次數）
LLM_PLAN_PER_HOUR = 10


class DocumentRules:
    """教練文章（RAG）的限制：控制 embedding 費用與檢索品質。"""
    FILE_TYPES = ('txt', 'md', 'pdf', 'docx', 'xlsx', 'csv')   # 轉換由共用的 modules.document_parser 負責
    MAX_BYTES = 5 * 1024 * 1024   # 檔案大小上限，與 smartlife.py 的 MAX_CONTENT_LENGTH 相同
    MAX_CHARS = 20000          # 一篇最多幾個字
    MAX_DOCUMENTS = 10         # 每人最多幾篇
    MAX_CHUNKS = 80            # 一篇最多切成幾段
    UPLOADS_PER_HOUR = 20
    REPORT_PASSAGES = 4        # AI 說明最多參考幾段
    QUERIES = 3                # 從分析結果最多產生幾個查詢


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

    def __init__(self, sql: BodySqlProcess, today=None, llm_parse=None, llm_report=None, embedder=None, embed_model=''):
        """llm_parse(messages) -> dict 或 (dict, 用量)：規則解析不了時呼叫的 LLM（回傳解析後的 JSON）。

        沒有傳入就只用規則解析；測試時可以傳入回傳固定 JSON 的假函式，不用真的呼叫 API。
        """
        self.sql = sql
        self.today = today or date.today()
        self.llm_parse = llm_parse
        self.llm_report = llm_report          # llm_report(messages) -> (dict, 用量)：週／月分析的 AI 說明
        self.embedder = embedder              # embedder(texts) -> [[float, ...], ...]：教練文章的 embedding
        self.embed_model = embed_model        # 目前的 embedding 模型；換模型後舊文章要重新上傳


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

    # ============================================================ 一句話輸入（只產生草稿，不寫資料庫）
    def parse_text(self, data):
        """把一句話解析成草稿：先用規則；規則有看不懂、而且含數字的片段，才交給 LLM。

        回傳 {items, unparsed, source}；items 只是草稿，前端填進預計組數，使用者逐組按 ✓ 才寫入。
        """
        text = data.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ApiError('請輸入今天的訓練內容。')
        if len(text) > WorkoutTextParser.MAX_TEXT:
            raise ApiError(f'內容太長，請在 {WorkoutTextParser.MAX_TEXT} 字以內。')
        library = [dict(id=r['id'], name=r['exercise_name']) for r in self.sql.exercises()]
        if not library:
            raise ApiError('動作庫是空的，請先新增動作。')
        usage = self.sql.exercise_usage((self.today - timedelta(days=90)).isoformat())

        parser = WorkoutTextParser(library, usage)
        result, source, note = parser.parse(text), 'rule', None
        # 需要 LLM 的情況：有含數字但看不懂的片段（unclear），或動作名稱完全對不到（可能是別名，例如 bench）
        unclear = any(re.search(r'\d', seg) for seg in result['unparsed'])
        needs_llm = unclear or any(item['exercise_id'] is None and not item['candidates'] for item in result['items'])
        llm_usage = None
        if needs_llm and self.llm_parse:
            if self.sql.rate_limited(f'body-llm:{self.sql.user_id}', LLM_PARSE_PER_HOUR, 3600):
                note = f'AI 解析每小時最多 {LLM_PARSE_PER_HOUR} 次，已達上限；只顯示規則解析的結果。'
            else:
                try:
                    raw = self.llm_parse(Prompts.parse_messages(text, [e['name'] for e in library]))
                    if isinstance(raw, tuple):                  # (資料, 用量)
                        raw, llm_usage = raw
                    drafted = parser.validate_llm_draft(raw)
                    if drafted['items']:
                        result, source = drafted, 'llm'
                    else:
                        note = 'AI 也沒有解析出訓練內容，請改用「動作 重量 組數 次數」的寫法。'
                except LlmError as exc:                         # LLM 失敗不影響規則解析的結果
                    note = f'AI 解析暫時無法使用（{exc}），只顯示規則解析的結果。'
                except Exception:
                    note = 'AI 解析暫時無法使用，只顯示規則解析的結果。'
        elif unclear:      # 只是動作庫沒有的名稱時不提示（畫面會詢問是否新增動作）
            note = '有部分內容需要 AI 解析，目前尚未啟用；請改用「動作 重量 組數 次數」的寫法。'

        names = {e['id']: e['name'] for e in library}
        for item in result['items']:
            if item['exercise_id'] is None:
                item['suggest'] = ExerciseGuesser.guess(item['input_text'])   # 新增動作時的預填值
            item['name'] = names.get(item['exercise_id'])
            item['candidates'] = [dict(id=c, name=names[c]) for c in item['candidates'] if c in names]
        return dict(items=result['items'], unparsed=result['unparsed'], source=source, note=note, usage=llm_usage)

    # ============================================================ 訓練分析（數字全部由程式計算）
    def report(self, period, anchor):
        """週／月分析：本期與上期比較、各部位組數、推拉比例、各動作進步、多久沒練、體重變化，以及規則產生的發現。"""
        if period not in ('week', 'month'):
            raise ApiError('period 只能是 week 或 month。')
        start, end, prev_start, prev_end = TrainingAnalysis.period_range(period, anchor)
        s, e, ps, pe = (x.isoformat() for x in (start, end, prev_start, prev_end))
        reference = min(end, self.today).isoformat()
        return TrainingAnalysis(
            period, start, end, self.today,
            sets=self.sql.sets_between(s, e), prev_sets=self.sql.sets_between(ps, pe),
            workouts=self.sql.workouts_between(s, e), prev_workouts=self.sql.workouts_between(ps, pe),
            metrics=self.sql.metrics_between(s, e), last_trained=self.sql.last_trained_by_muscle(reference)).build()

    # ============================================================ AI 分析說明（數字由程式算，LLM 只負責說明）
    def _ai_report(self, period, anchor, with_passages=False):
        report, profile = self.report(period, anchor), self.sql.profile()
        passages = self._report_passages(report, profile) if with_passages else None
        return AiReport(report, profile, passages)

    def _report_passages(self, report, profile):
        """用這期分析的重點當查詢，從自己的教練文章找出相關段落；沒有文章、沒設定或出錯就回空清單。"""
        if self.embedder is None:
            return []
        queries = [f['text'] for f in report['findings'] if f['level'] in ('warn', 'info')][:DocumentRules.QUERIES]
        if profile.get('goal_type'):
            queries.append(f"{profile['goal_type']} 的訓練建議")
        return self._passages(queries)

    def _passages(self, queries):
        """用幾個查詢從自己的教練文章找段落，合併後取分數最高的幾段；沒有文章或出錯就回空清單。"""
        rows = self._searchable_chunks()
        if self.embedder is None or not queries or not rows:
            return []
        try:
            vectors = self.embedder(queries)
        except LlmError:
            return []
        best = {}
        for vector in vectors:
            for row, score in VectorIndex.search(vector, rows, k=2):
                if score > best.get(row['id'], (None, -1))[1]:
                    best[row['id']] = (row, score)
        ranked = sorted(best.values(), key=lambda x: -x[1])[:DocumentRules.REPORT_PASSAGES]
        return [dict(n=i + 1, chunk_id=row['id'], title=row['title'], section=row.get('section') or '',
                     locator=row.get('locator') or '', text=row['content'], score=score)
                for i, (row, score) in enumerate(ranked)]

    def _searchable_chunks(self):
        """只用「目前的 embedding 模型」做的段落（換模型後的舊向量不能互相比較）。"""
        tag = f'embedding:{self.embed_model}'
        return [r for r in self.sql.chunks_for_search() if r['file_path'] == tag]

    def ai_explanation(self, period, anchor):
        """讀取這一期已產生的 AI 說明；資料有變動時標示 stale（不會自動重新呼叫 LLM）。"""
        ai = self._ai_report(period, anchor)
        row = self.sql.ai_suggestion(f'body_{period}', ai.report['start'])
        saved = None
        if row:
            try:
                saved = json.loads(row['content'])
            except (TypeError, ValueError):
                saved = None
        if saved:
            saved['stale'] = saved.get('input_hash') != ai.hash
        return dict(enabled=self.llm_report is not None, saved=saved, has_data=ai.has_data)

    def generate_ai_explanation(self, period, anchor):
        """呼叫 LLM 產生（或重新產生）這一期的說明，檢查數字後存進 ai_suggestions。"""
        if self.llm_report is None:
            raise ApiError('尚未設定 AI（body/body.env），目前只能看程式算出的分析。')
        ai = self._ai_report(period, anchor, with_passages=True)
        if not ai.has_data:
            raise ApiError('這段期間沒有訓練紀錄，沒有可以分析的內容。')
        if self.sql.rate_limited(f'body-llm-report:{self.sql.user_id}', LLM_REPORT_PER_HOUR, 3600):
            raise ApiError(f'AI 分析每小時最多 {LLM_REPORT_PER_HOUR} 次，請稍後再試。')
        try:
            raw = self.llm_report(Prompts.report_messages(ai.prompt_data))
        except LlmError as exc:
            raise ApiError(f'AI 分析暫時無法使用（{exc}）。') from None
        raw, usage = raw if isinstance(raw, tuple) else (raw, None)
        result = ai.check(raw)
        if not (result['summary'] or result['strengths'] or result['weaknesses'] or result['suggestions']):
            raise ApiError('AI 回傳的內容沒有通過檢查，請稍後再試。')
        saved = dict(result, input_hash=ai.hash, period=period, start=ai.report['start'], end=ai.report['end'],
                     generated_at=datetime.now().isoformat(timespec='seconds'),
                     model=(usage or {}).get('model'), usage=usage, passages=len(ai.passages))
        self.sql.save_ai_suggestion(f'body_{period}', ai.report['start'], json.dumps(saved, ensure_ascii=False))
        self.sql.commit()
        saved['stale'] = False
        return dict(enabled=True, saved=saved, has_data=True)

    # ============================================================ 建議課表（程式排骨架與重量，LLM 挑動作與說明）
    def _plan(self, day, with_passages=False):
        d = day.isoformat()
        week_ago = (day - timedelta(days=7)).isoformat()
        yesterday = (day - timedelta(days=1)).isoformat()
        weekly = TrainingAnalysis.volume_by_muscle(self.sql.sets_between(week_ago, yesterday))
        library = [dict(id=r['id'], name=r['exercise_name'], muscle_group=r['muscle_group'],
                        equipment=r['equipment'], is_cardio=r['is_cardio']) for r in self.sql.exercises()]
        plan = WorkoutPlan(
            day, self.sql.profile(),
            days_since=TrainingAnalysis.days_since_trained(self.sql.last_trained_by_muscle(yesterday), day),
            weekly_sets={m: v['sets'] for m, v in weekly.items()},
            library=library,
            usage=self.sql.exercise_usage((day - timedelta(days=90)).isoformat()),
            last_sessions=self.sql.latest_sessions_before(d, (day - timedelta(days=180)).isoformat()),
            exercise_dates=self.sql.exercise_dates((day - timedelta(days=365)).isoformat(), d),
            body=self._body(d))
        if with_passages:
            queries = [x['why'] for x in plan.skeleton['slots']][:DocumentRules.QUERIES]
            if plan.skeleton['goal']:
                queries.append(f"{plan.skeleton['goal']} 的訓練建議")
            plan.passages = self._passages(queries)
        return plan

    def _body(self, day):
        """估起始重量用的性別、生日與最近一次體重（到 day 為止）。"""
        metric = self.sql.latest_metric(day)
        return dict(self.sql.gender_and_birth(), weight_kg=metric['weight_kg'] if metric else None)

    def suggested_plan(self, day):
        """讀取這一天已產生的建議課表；資料有變動時標示 stale（不會自動重新產生）。"""
        plan = self._plan(day)
        row = self.sql.ai_suggestion('body_plan', day.isoformat())
        saved = None
        if row:
            try:
                saved = json.loads(row['content'])
            except (TypeError, ValueError):
                saved = None
        if saved:
            saved['stale'] = saved.get('input_hash') != plan.hash
        return dict(enabled=self.llm_report is not None, saved=saved)

    def generate_plan(self, day):
        """產生（或重新產生）這一天的建議課表，存進 ai_suggestions（type=body_plan）。

        有設定 AI：LLM 從候選挑動作，檢查後不合格的位置改用程式選擇。
        沒有設定 AI：全部用程式選擇（常做的動作優先），功能仍可使用。
        課表只是草稿：「套用到今天」只填進前端的預計組數，使用者逐組按 ✓ 才寫入 workout_sets。
        """
        if day < self.today:
            raise ApiError('只能替今天或之後的日期建議課表。')
        # 分化方式、動作數、次數都依個人資料決定，沒填就不排（後端檢查，不依賴前端）
        missing = WorkoutPlan.missing_profile(self.sql.profile())
        if missing:
            raise ApiError(f"請先到「個人資料與目標」填寫：{'、'.join(missing)}，才能依你的目標排課。",
                           need='profile', missing=missing)
        use_ai = self.llm_report is not None
        plan = self._plan(day, with_passages=use_ai)
        if not plan.library:
            raise ApiError('動作庫裡沒有可以安排的重訓動作，請先新增動作。')
        raw, usage, note = None, None, None
        if use_ai and not plan.skeleton['rest']:          # 建議休息時不用呼叫 LLM
            if self.sql.rate_limited(f'body-llm-plan:{self.sql.user_id}', LLM_PLAN_PER_HOUR, 3600):
                raise ApiError(f'AI 建議課表每小時最多 {LLM_PLAN_PER_HOUR} 次，請稍後再試。')
            try:
                raw = self.llm_report(Prompts.plan_messages(plan.prompt_data))
                raw, usage = raw if isinstance(raw, tuple) else (raw, None)
            except LlmError as exc:                        # AI 失敗時仍給程式選擇的課表
                raw, note = None, f'AI 暫時無法使用（{exc}），以下是程式依紀錄選擇的動作。'
        result = plan.check(raw)
        saved = dict(result, input_hash=plan.hash, source='llm' if raw is not None else 'rule', note=note,
                     generated_at=datetime.now().isoformat(timespec='seconds'),
                     model=(usage or {}).get('model'), usage=usage)
        self.sql.save_ai_suggestion('body_plan', day.isoformat(), json.dumps(saved, ensure_ascii=False))
        self.sql.commit()
        saved['stale'] = False
        return dict(enabled=use_ai, saved=saved)

    # ============================================================ 教練文章（RAG）
    def documents(self):
        """自己的教練文章；usable=False 代表是用別的 embedding 模型做的，要重新上傳才能檢索。"""
        tag = f'embedding:{self.embed_model}'
        docs = [dict(id=d['id'], title=d['title'], file_type=d['file_type'], chunks=d['chunks'],
                     model=(d['file_path'] or '').replace('embedding:', '', 1), usable=d['file_path'] == tag)
                for d in self.sql.documents()]
        return dict(enabled=self.embedder is not None, documents=docs, limits=dict(
            max_chars=DocumentRules.MAX_CHARS, max_documents=DocumentRules.MAX_DOCUMENTS, max_bytes=DocumentRules.MAX_BYTES,
            file_types=list(DocumentRules.FILE_TYPES)))

    def upload_document(self, filename, raw, title=''):
        """上傳文章：轉成文字（modules.document_parser）→ 切段 → embedding → 一次寫入資料庫（原始檔案不存）。"""
        if self.embedder is None:
            raise ApiError('尚未設定 embedding（body/body.env 的 BODY_EMBED_MODEL），不能上傳文章。')
        name = str(filename or '').strip()
        ext = DocumentParser.extension(name)
        if ext not in DocumentRules.FILE_TYPES:
            raise ApiError(f"只能上傳 {'、'.join('.' + e for e in DocumentRules.FILE_TYPES)} 檔案。")
        try:
            sections = DocumentParser.parse(name, raw)
        except DocumentParseError as exc:
            raise ApiError(str(exc)) from None
        total = sum(len(s['text']) for s in sections)
        if total > DocumentRules.MAX_CHARS:
            raise ApiError(f'文章太長（{total:,} 字），一篇最多 {DocumentRules.MAX_CHARS:,} 字，請分成幾篇上傳。')
        if self.sql.document_count() >= DocumentRules.MAX_DOCUMENTS:
            raise ApiError(f'最多上傳 {DocumentRules.MAX_DOCUMENTS} 篇，請先刪除不需要的文章。')
        title = ' '.join(str(title or '').split())[:120] or name.rsplit('.', 1)[0][:120] or '教練文章'
        chunks = TextChunker().split_sections(sections)
        if not chunks:
            raise ApiError('文章裡沒有可以使用的內容。')
        if len(chunks) > DocumentRules.MAX_CHUNKS:
            raise ApiError(f'文章切成 {len(chunks)} 段，超過上限 {DocumentRules.MAX_CHUNKS} 段，請分成幾篇上傳。')
        if self.sql.rate_limited(f'body-doc:{self.sql.user_id}', DocumentRules.UPLOADS_PER_HOUR, 3600):
            raise ApiError(f'每小時最多上傳 {DocumentRules.UPLOADS_PER_HOUR} 次，請稍後再試。')
        try:
            vectors = self.embedder([c['content'] for c in chunks])
        except LlmError as exc:
            raise ApiError(f'產生 embedding 失敗（{exc}）。') from None
        if len(vectors) != len(chunks):
            raise ApiError('embedding 回傳的數量不對。')
        try:
            material_id = self.sql.insert_document(title, ext, self.embed_model, chunks, vectors)
            self.sql.commit()
        except Exception:
            self.sql.rollback()
            raise ApiError('儲存文章時發生錯誤，請再試一次。') from None
        return dict(self.documents(), uploaded=dict(id=material_id, title=title, chunks=len(chunks)))

    def delete_document(self, material_id):
        if not self.sql.delete_document(material_id):
            raise ApiError.not_found('找不到這篇文章。')
        self.sql.commit()
        return self.documents()

    def search_documents(self, query, k=None, min_score=None):
        """直接查詢教練文章（給評估與除錯用）：回傳超過門檻的段落與分數。"""
        if self.embedder is None:
            raise ApiError('尚未設定 embedding（BODY_EMBED_MODEL）。')
        query = ' '.join(str(query or '').split())[:300]
        if not query:
            raise ApiError('請輸入查詢內容。')
        rows = self._searchable_chunks()
        if not rows:
            return dict(query=query, hits=[], min_score=min_score or VectorIndex.DEFAULT_MIN_SCORE)
        try:
            vector = self.embedder([query])[0]
        except LlmError as exc:
            raise ApiError(f'產生 embedding 失敗（{exc}）。') from None
        hits = VectorIndex.search(vector, rows, k=k, min_score=min_score)
        return dict(query=query, min_score=VectorIndex.DEFAULT_MIN_SCORE if min_score is None else min_score,
                    hits=[dict(chunk_id=r['id'], title=r['title'], section=r.get('section') or '',
                               locator=r.get('locator') or '', text=r['content'], score=score) for r, score in hits])

    # ============================================================ 新增動作（一句話輸入遇到動作庫沒有的動作）
    def create_exercise(self, data):
        """新增動作；規則與「運動動作庫」頁面相同（名稱 80 字、部位 6 選 1、器材 50 字、是否有氧）。

        名稱已經存在（不分大小寫與空白）就直接回傳既有的動作，不重複新增。
        """
        name = ' '.join(str(data.get('name') or '').split())
        equipment = ' '.join(str(data.get('equipment') or '').split())
        muscle = data.get('muscle_group')
        if not name:
            raise ApiError('請輸入動作名稱。')
        if len(name) > 80:
            raise ApiError('動作名稱最多 80 字。')
        if muscle not in ExerciseGuesser.MUSCLES:
            raise ApiError('請選擇部位。')
        if not equipment:
            raise ApiError('請輸入使用的器材。')
        if len(equipment) > 50:
            raise ApiError('器材最多 50 字。')
        is_cardio = data.get('is_cardio')
        if not isinstance(is_cardio, bool):
            is_cardio = str(is_cardio).strip().lower() in ('1', 'true', 'yes')
        key = ''.join(name.split()).lower()
        for row in self.sql.exercises():
            if ''.join(row['exercise_name'].split()).lower() == key:
                return dict(exercise=dict(id=row['id'], name=row['exercise_name']), existed=True)
        exercise_id = self.sql.insert_exercise(name, muscle, equipment, is_cardio)
        self.sql.commit()
        return dict(exercise=dict(id=exercise_id, name=name), existed=False)

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
