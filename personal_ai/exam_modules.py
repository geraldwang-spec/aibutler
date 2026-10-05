"""CPU specialists for exams, isolated from the app's Python and BODY module."""
import atexit
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_process = None
_responses = None
_lock = threading.Lock()


class ExamModuleError(RuntimeError):
    pass


def enabled(config):
    return str(config.get('EXAM_MODULAR_AI', os.getenv('EXAM_MODULAR_AI', 'false'))).lower() == 'true'


def stop_worker():
    global _process
    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
    _process = None


atexit.register(stop_worker)


def _read(process, responses):
    for line in process.stdout:
        responses.put(line)
    responses.put(None)


def cpu(op, **payload):
    global _process, _responses
    if not _lock.acquire(timeout=60):
        raise ExamModuleError('CPU 判斷模組忙碌，請稍後再試。')
    try:
        if not _process or _process.poll() is not None:
            python = Path(os.getenv('EXAM_CPU_PYTHON') or (ROOT / '.venv-exam-ai' / ('Scripts/python.exe' if os.name=='nt' else 'bin/python')))
            if not python.is_file():
                raise ExamModuleError('尚未安裝考題 CPU 執行環境，請執行 tools/setup_exam_ai.ps1。')
            env = dict(os.environ, PYTHONUTF8='1', TOKENIZERS_PARALLELISM='false')
            _process = subprocess.Popen([str(python), str(ROOT / 'tools' / 'exam_cpu_worker.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            _responses = queue.Queue()
            threading.Thread(target=_read, args=(_process, _responses), daemon=True).start()
        _process.stdin.write(json.dumps(dict(op=op, **payload), ensure_ascii=False) + '\n')
        _process.stdin.flush()
        try:
            line = _responses.get(timeout=60)
        except queue.Empty:
            stop_worker()
            raise ExamModuleError('CPU 判斷超過 60 秒，已停止此 CPU 工作。請減少單批題數。') from None
        if line is None:
            stop_worker()
            raise ExamModuleError('CPU 判斷模組意外結束，請確認模型已完整下載。')
        data = json.loads(line)
        if not data['ok']:
            raise ExamModuleError('CPU 模組：' + data.get('error', '未知錯誤'))
        return data['result']
    except (OSError, ValueError) as exc:
        stop_worker()
        raise ExamModuleError('CPU 模組無法執行：' + str(exc)) from exc
    finally:
        _lock.release()


def rank(text, candidates):
    if not candidates:
        return []
    # Score overlapping windows so the end of a long chapter remains searchable.
    windows = [(index, c[start:start+180]) for index,c in enumerate(candidates)
               for start in range(0,max(1,len(c)),140)]
    queries = [text[start:start+180] for start in range(0,max(1,len(text)),140)]
    vectors = cpu('embed', texts=['query: '+q for q in queries] + ['passage: '+w for _,w in windows])
    scores = [-1.0] * len(candidates)
    for (index,_),vector in zip(windows,vectors[len(queries):]):
        scores[index] = max(scores[index],max(sum(a*b for a,b in zip(query,vector)) for query in vectors[:len(queries)]))
    return sorted(enumerate(scores), key=lambda row: row[1], reverse=True)


def classify(item, concepts, fallback):
    labels = list(dict.fromkeys([c['name'] for c in concepts] + [fallback,
        '變數與型別','條件判斷','迴圈與串列','函式與參數','例外處理',
        'SQL 查詢與篩選','SQL JOIN 與資料表關聯','SQL 排序與結果順序',
        '主索引鍵與資料唯一性','外部索引鍵與參照完整性','資料庫交易控制']))
    text = str(item.get('content', '')) + ' ' + str(item.get('explanation', ''))
    top = rank(text, labels)[:3]
    judgments = cpu('nli', pairs=[(text[:1500], '這道題目主要考查' + labels[index] + '。') for index,_ in top])
    ordered = sorted(zip(top, judgments), key=lambda row: row[1].get('entailment', 0), reverse=True)
    (index, similarity), judgment = ordered[0]
    score = judgment.get('entailment', 0)
    second = ordered[1][1].get('entailment', 0) if len(ordered) > 1 else 0
    name = labels[index]
    existing = next((c for c in concepts if c['name'] == name), None)
    return dict(concept_name=name, existing_concept_id=existing['id'] if existing else None,
                raw_score=round(score, 3), margin=round(score-second, 3), similarity=round(similarity, 3),
                needs_review=score < .8 or score-second < .15,
                reason='CPU E5 候選檢索 + MiniLM NLI 初篩；分數未經本校題庫校準。')


def specialist_heads(item,subject_id):
    if not (ROOT/'models'/'exam'/'trained'/'manifest.json').is_file():
        return {'status':'未訓練；人工標註資料不足，使用 CPU NLI 候選與 LLM 最終裁決'}
    return cpu('heads',text=str(item.get('content',''))[:4000],subject_id=subject_id)


def assess(items, evidence):
    reports = []
    texts=[str(item.get('content','')) for item in items]
    vectors=cpu('embed',texts=['passage: '+text[:2000] for text in texts]) if texts else []
    for item in items:
        options = item.get('options') or {}
        issues = []
        if not isinstance(options, dict):
            issues.append('選項格式錯誤')
            options = {}
        normalized = [str(v).strip().casefold() for v in options.values()]
        if len(set(normalized)) != len(normalized):
            issues.append('選項文字重複')
        if any(not value for value in normalized):
            issues.append('有空白選項')
        if item.get('q_type') in ('單選','多選'):
            answers = str(item.get('answer_key','')).replace('，',',').split(',')
            if not all(a.strip() in options for a in answers):
                issues.append('答案未對應選項')
        report = dict(issues=issues, evidence_status='未取得教材；需人工確認')
        index=len(reports)
        similarities=[(j,sum(a*b for a,b in zip(vectors[index],v))) for j,v in enumerate(vectors) if j != index]
        report['similar_questions']=[dict(index=j,raw_similarity=round(s,3)) for j,s in similarities if s>.9]
        report['expert_check']=item.get('_expert','未做科目執行驗證；需 LLM／人工審核')
        if evidence:
            answer = ', '.join(str(options.get(k.strip(), k)) for k in str(item.get('answer_key','')).split(','))
            hypothesis = str(item.get('content','')) + ' 正確答案是：' + answer
            premises=[evidence[start:start+160] for start in range(0,len(evidence),120)]
            judgments=cpu('nli', pairs=[(premise,hypothesis[:180]) for premise in premises])
            scores=max(judgments,key=lambda result:result.get('entailment',0))
            report.update(evidence_scores=scores, evidence_status='語意支持初篩，不能取代答案驗證')
        reports.append(report)
    return reports
