# -*- coding: utf-8 -*-
"""body 模組自己的 LLM 呼叫（OpenAI 相容的 /chat/completions）。

Groq、OpenAI、Ollama（/v1）、LM Studio 等都支援這個格式，換供應商只要改 .env：
    BODY_LLM_BASE_URL   例如 https://api.groq.com/openai/v1 或 http://127.0.0.1:11434/v1
    BODY_LLM_MODEL      模型名稱（以供應商後台的清單為準）
    BODY_LLM_API_KEY    雲端服務的金鑰；本機 Ollama 留空
    BODY_LLM_TIMEOUT    逾時秒數，預設 30
    BODY_LLM_JSON_MODE  是否要求只輸出 JSON（response_format），預設 true；供應商不支援時會自動改用一般模式

只用 Python 內建的 urllib，不需要安裝 SDK。金鑰只從環境變數讀取，不會出現在錯誤訊息或紀錄裡。
"""
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request


class LlmError(Exception):
    """給使用者看的錯誤訊息（不含金鑰或伺服器細節）。"""


def _env_bool(name, default=True):
    value = os.getenv(name)
    return default if value is None or value == '' else value.strip().lower() in ('1', 'true', 'yes', 'on')


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


class BodyLlmClient:
    def __init__(self, base_url, model, api_key='', timeout=30, max_tokens=800, json_mode=True):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.json_mode = json_mode

    @classmethod
    def from_env(cls):
        """.env 沒有設定 BODY_LLM_BASE_URL 或 BODY_LLM_MODEL 時回傳 None（只用規則解析）。"""
        base_url, model = os.getenv('BODY_LLM_BASE_URL', '').strip(), os.getenv('BODY_LLM_MODEL', '').strip()
        if not base_url or not model:
            return None
        try:
            timeout = max(5, min(120, int(os.getenv('BODY_LLM_TIMEOUT', '30'))))
        except ValueError:
            timeout = 30
        return cls(base_url, model, os.getenv('BODY_LLM_API_KEY', '').strip(), timeout,
                   json_mode=_env_bool('BODY_LLM_JSON_MODE', True))

    # ------------------------------------------------------------------ 呼叫
    def _post(self, payload):
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        request = urllib.request.Request(f'{self.base_url}/chat/completions', method='POST', headers=headers,
                                         data=json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode('utf-8'))

    def chat(self, messages, max_tokens=None, json_mode=None):
        """回傳 {text, input_tokens, output_tokens, latency_ms}；失敗丟 LlmError。"""
        json_mode = self.json_mode if json_mode is None else json_mode
        payload = dict(model=self.model, messages=messages, temperature=0, max_tokens=max_tokens or self.max_tokens)
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
        started = time.monotonic()
        try:
            body = self._post(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:500]
            if exc.code == 400 and json_mode and 'response_format' in detail:
                return self.chat(messages, max_tokens, json_mode=False)      # 不支援 JSON 模式 → 改用一般模式
            if exc.code in (401, 403):
                raise LlmError('AI 服務的金鑰無效或沒有權限') from None
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

        try:
            text = body['choices'][0]['message']['content'] or ''
        except (KeyError, IndexError, TypeError):
            raise LlmError('AI 服務回應格式錯誤') from None
        usage = body.get('usage') or {}
        return dict(text=text, input_tokens=int(usage.get('prompt_tokens') or 0),
                    output_tokens=int(usage.get('completion_tokens') or 0),
                    latency_ms=int((time.monotonic() - started) * 1000))

    def chat_json(self, messages, max_tokens=None):
        """要求只輸出 JSON；回傳 {data, input_tokens, output_tokens, latency_ms}。"""
        result = self.chat(messages, max_tokens)
        return dict(data=extract_json(result.pop('text')), **result)
