# -*- coding: utf-8 -*-
"""body 模組自己的 LLM 呼叫（OpenAI 相容的 /chat/completions 與 /embeddings）。

OpenAI、Groq、Gemini（OpenAI 相容介面）、Ollama（/v1）、LM Studio 都支援這個格式，換供應商只要改 .env：
    BODY_LLM_BASE_URL          例如 https://api.openai.com/v1 或 http://127.0.0.1:11434/v1
    BODY_LLM_MODEL             對話模型名稱（以供應商後台的模型清單為準）
    BODY_LLM_API_KEY           雲端服務的金鑰；本機 Ollama 留空
    BODY_LLM_TIMEOUT           逾時秒數，預設 30
    BODY_LLM_JSON_MODE         是否要求只輸出 JSON（response_format），預設 true
    BODY_LLM_REASONING_EFFORT  （選填）推理型模型的思考程度，留空就不送
    BODY_EMBED_MODEL           （選填）embedding 模型名稱；留空就不能用 embed()
    BODY_EMBED_BASE_URL / BODY_EMBED_API_KEY  （選填）embedding 用不同的服務時才填，預設沿用 BODY_LLM_*

不同模型接受的參數不一樣（例如較新的推理型模型要用 max_completion_tokens、不接受自訂 temperature），
遇到「不支援這個參數」的錯誤時會自動改用對應的參數再試一次，並記住，之後就直接用正確的參數。

只用 Python 內建的 urllib，不需要安裝 SDK。金鑰只從環境變數讀取，不會出現在錯誤訊息或紀錄裡。
"""
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

EMBED_BATCH = 64          # 一次最多送幾段文字去做 embedding


class LlmError(Exception):
    """給使用者看的錯誤訊息（不含金鑰或伺服器細節）。"""


class _ParamRejected(Exception):
    """伺服器說某個參數不支援（內部用來自動調整參數）。"""

    def __init__(self, param):
        super().__init__(param)
        self.param = param


def _env(name, default=''):
    return os.getenv(name, default).strip()


def _env_bool(name, default=True):
    value = _env(name)
    return default if value == '' else value.lower() in ('1', 'true', 'yes', 'on')


def extract_json(text):
    """從模型回應取出 JSON 物件：去掉 <think> 推理區塊與 ```json 標記，取第一個 { 到最後一個 }。"""
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise LlmError('AI 回傳的內容不是 JSON')
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        raise LlmError('AI 回傳的 JSON 格式錯誤') from None


def _rejected_param(detail):
    """從 HTTP 400 的錯誤內容判斷是哪個參數不被接受；判斷不出來回 None。

    例如 OpenAI 較新的模型會回：Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead.
    """
    try:
        error = json.loads(detail).get('error') or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {'message': str(error)}
    param = error.get('param')
    message = str(error.get('message') or detail).lower()
    hint = any(word in message for word in ('unsupported', 'not supported', 'unrecognized', 'unknown', 'does not support'))
    for name in ('max_tokens', 'temperature', 'response_format', 'reasoning_effort'):
        if param == name or (hint and name in message):
            return name
    return None


class BodyLlmClient:
    def __init__(self, base_url, model, api_key='', timeout=30, max_tokens=800, json_mode=True,
                 reasoning_effort='', embed_model='', embed_base_url='', embed_api_key=''):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self.reasoning_effort = reasoning_effort
        self.embed_model = embed_model
        self.embed_base_url = (embed_base_url or base_url).rstrip('/')
        self.embed_api_key = embed_api_key if embed_base_url else (embed_api_key or api_key)
        # 依伺服器的回應自動調整（記住之後就不再試錯）
        self._tokens_param = 'max_tokens'
        self._send_temperature = True

    @classmethod
    def from_env(cls):
        """.env 沒有設定 BODY_LLM_BASE_URL 或 BODY_LLM_MODEL 時回傳 None（只用規則解析）。"""
        base_url, model = _env('BODY_LLM_BASE_URL'), _env('BODY_LLM_MODEL')
        if not base_url or not model:
            return None
        try:
            timeout = max(5, min(120, int(_env('BODY_LLM_TIMEOUT', '30') or 30)))
        except ValueError:
            timeout = 30
        return cls(base_url, model, _env('BODY_LLM_API_KEY'), timeout,
                   json_mode=_env_bool('BODY_LLM_JSON_MODE', True),
                   reasoning_effort=_env('BODY_LLM_REASONING_EFFORT'),
                   embed_model=_env('BODY_EMBED_MODEL'),
                   embed_base_url=_env('BODY_EMBED_BASE_URL'),
                   embed_api_key=_env('BODY_EMBED_API_KEY'))

    @property
    def can_embed(self):
        return bool(self.embed_model)

    # ------------------------------------------------------------------ HTTP
    def _request(self, url, api_key, payload):
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        request = urllib.request.Request(url, method='POST', headers=headers,
                                         data=json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:2000]
            if exc.code == 400:
                param = _rejected_param(detail)
                if param:
                    raise _ParamRejected(param) from None
            if exc.code in (401, 403):
                raise LlmError('AI 服務的金鑰無效或沒有權限') from None
            if exc.code == 404:
                raise LlmError('找不到指定的模型或網址，請檢查 .env 的設定') from None
            if exc.code == 429:
                raise LlmError('AI 服務使用太頻繁或額度已用完，請稍後再試') from None
            if exc.code == 413:
                raise LlmError('送給 AI 的內容太長') from None
            raise LlmError(f'AI 服務回應錯誤（HTTP {exc.code}）') from None
        except (socket.timeout, TimeoutError):
            raise LlmError(f'AI 服務超過 {self.timeout} 秒沒有回應') from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise LlmError(f'AI 服務超過 {self.timeout} 秒沒有回應') from None
            raise LlmError('無法連線到 AI 服務') from None
        except (ValueError, OSError):
            raise LlmError('AI 服務回應格式錯誤') from None

    # ------------------------------------------------------------------ 對話
    def _chat_payload(self, messages, max_tokens, json_mode):
        payload = dict(model=self.model, messages=messages)
        payload[self._tokens_param] = max_tokens
        if self._send_temperature:
            payload['temperature'] = 0
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
        if self.reasoning_effort:
            payload['reasoning_effort'] = self.reasoning_effort
        return payload

    def chat(self, messages, max_tokens=None, json_mode=None):
        """回傳 {text, input_tokens, output_tokens, latency_ms}；失敗丟 LlmError。"""
        json_mode = self.json_mode if json_mode is None else json_mode
        max_tokens = max_tokens or self.max_tokens
        started = time.monotonic()
        for _ in range(4):                       # 最多自動調整 3 次參數
            try:
                body = self._request(f'{self.base_url}/chat/completions', self.api_key,
                                     self._chat_payload(messages, max_tokens, json_mode))
                break
            except _ParamRejected as exc:
                if exc.param == 'max_tokens' and self._tokens_param == 'max_tokens':
                    self._tokens_param = 'max_completion_tokens'
                elif exc.param == 'temperature' and self._send_temperature:
                    self._send_temperature = False
                elif exc.param == 'response_format' and json_mode:
                    json_mode = False                # 不支援 JSON 模式 → 改用一般模式（提示詞已要求只輸出 JSON）
                elif exc.param == 'reasoning_effort' and self.reasoning_effort:
                    self.reasoning_effort = ''
                else:
                    raise LlmError('AI 服務不接受目前的參數設定（HTTP 400）') from None
        else:
            raise LlmError('AI 服務不接受目前的參數設定（HTTP 400）')

        try:
            choice = body['choices'][0]
            text = choice['message'].get('content') or ''
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LlmError('AI 服務回應格式錯誤') from None
        if not text.strip():
            if choice.get('finish_reason') == 'length':
                raise LlmError('AI 的回應被截斷（輸出長度上限太小）')
            raise LlmError('AI 回傳了空白內容')
        usage = body.get('usage') or {}
        return dict(text=text, input_tokens=int(usage.get('prompt_tokens') or 0),
                    output_tokens=int(usage.get('completion_tokens') or 0),
                    latency_ms=int((time.monotonic() - started) * 1000))

    def chat_json(self, messages, max_tokens=None):
        """要求只輸出 JSON；回傳 {data, input_tokens, output_tokens, latency_ms}。"""
        result = self.chat(messages, max_tokens)
        return dict(data=extract_json(result.pop('text')), **result)

    # ------------------------------------------------------------------ embedding（RAG 用）
    def embed(self, texts):
        """把多段文字轉成向量；回傳 {vectors: [[float, ...], ...], input_tokens, latency_ms, model}。

        向量的順序與輸入相同；同一個索引必須一直用同一個 embedding 模型（換模型要全部重算）。
        """
        if not self.can_embed:
            raise LlmError('尚未設定 embedding 模型（BODY_EMBED_MODEL）')
        texts = [str(t) for t in texts]
        if not texts:
            return dict(vectors=[], input_tokens=0, latency_ms=0, model=self.embed_model)
        started, vectors, tokens = time.monotonic(), [], 0
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i:i + EMBED_BATCH]
            try:
                body = self._request(f'{self.embed_base_url}/embeddings', self.embed_api_key,
                                     dict(model=self.embed_model, input=batch))
            except _ParamRejected:
                raise LlmError('embedding 服務不接受目前的參數設定（HTTP 400）') from None
            try:
                items = sorted(body['data'], key=lambda d: d.get('index', 0))
                got = [[float(x) for x in item['embedding']] for item in items]
            except (KeyError, TypeError, ValueError):
                raise LlmError('embedding 服務回應格式錯誤') from None
            if len(got) != len(batch):
                raise LlmError('embedding 服務回傳的數量不對')
            vectors += got
            tokens += int((body.get('usage') or {}).get('prompt_tokens') or 0)
        if len({len(v) for v in vectors}) != 1:
            raise LlmError('embedding 的維度不一致')
        return dict(vectors=vectors, input_tokens=tokens,
                    latency_ms=int((time.monotonic() - started) * 1000), model=self.embed_model)
