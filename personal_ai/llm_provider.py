from __future__ import annotations

import json
import os
import re
import time
import threading
import urllib.error
import urllib.request

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
_OLLAMA_GATE = threading.Lock()


class LLMError(RuntimeError):
    pass


class BaseLLM:
    enabled = False
    provider = "disabled"
    model = ""

    def complete_json(self, system: str, user: str):
        raise LLMError("LLM 尚未設定。請確認 Provider、Model 與 API Key。")

    def complete_json_with_images(self, system: str, user: str, images):
        raise LLMError("目前模型 Provider 不支援圖片輸入。")

    def ping(self):
        return {"ok": False, "message": "LLM 尚未設定。", "provider": self.provider, "model": self.model}


class MockLLM(BaseLLM):
    """僅保留給單元測試/離線 UI smoke test；正式設定不再使用 mock。"""

    enabled = True
    provider = "mock"
    model = "mock-test-only"

    def complete_json(self, system: str, user: str):
        match = re.search(r"請產生\s*(\d+)\s*題", user)
        count = max(1, min(20, int(match.group(1)) if match else 3))
        return {
            "questions": [
                {
                    "q_type": "單選",
                    "content": f"[TEST ONLY #{i + 1}] mock provider 不應出現在正式驗收。",
                    "options": {"A": "A", "B": "B"},
                    "answer_key": "A",
                    "explanation": "test only",
                    "evidence_chunk_ids": [],
                    "skill": "test",
                    "cognitive_level": "remember",
                }
                for i in range(count)
            ]
        }

    def ping(self):
        return {"ok": True, "message": "Mock 僅供測試；正式版不應使用。", "provider": self.provider, "model": self.model}


class OpenAICompatibleLLM(BaseLLM):
    enabled = True
    provider = "openai_compatible"

    def __init__(self, base_url, model, api_key="", timeout=120):
        self.base_url = str(base_url).rstrip("/")
        self.model = str(model).strip()
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout

    def _request(self, messages, temperature=0.2):
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                **self._request_options(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/chat/completions", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        # Groq's edge protection rejects urllib's default Python-urllib agent (1010).
        req.add_header("User-Agent", "AI-Butler/1.0")
        req.add_header("Accept", "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1200]
            except Exception:
                pass
            suffix = f"：{detail}" if detail else ""
            raise LLMError(f"LLM API HTTP {exc.code}{suffix}") from exc
        except Exception as exc:
            raise LLMError(f"LLM API 呼叫失敗：{exc}") from exc

    def _request_options(self):
        return {}

    @staticmethod
    def _parse_json_text(text: str):
        text = str(text or "").strip()
        # Qwen/reasoning models may expose a think block before final JSON.
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        raise LLMError("LLM 未回傳有效 JSON。請重試或改用較強模型。")

    def complete_json(self, system, user):
        data = self._request(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.35,
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError("LLM 回傳格式不符合 OpenAI-compatible API。") from exc
        if data["choices"][0].get("finish_reason") == "length":
            raise LLMError("模型輸出達到 token 上限，JSON 未完成。請縮短題目或解析內容。")
        return self._parse_json_text(text)

    def ping(self):
        try:
            data = self._request(
                [
                    {"role": "system", "content": '只回 JSON：{"status":"OK"}。'},
                    {"role": "user", "content": "連線測試"},
                ],
                temperature=0,
            )
            _ = data["choices"][0]["message"]["content"]
            return {"ok": True, "message": "LLM API 連線成功。", "provider": self.provider, "model": self.model}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "provider": self.provider, "model": self.model}


class OllamaLLM(OpenAICompatibleLLM):
    provider = "ollama"

    def __init__(self, base_url, model, api_key="", timeout=60):
        super().__init__(base_url, model, api_key, timeout=timeout)

    def _native_chat(self, messages, temperature=0.2, images=None, num_predict=4096):
        deadline=time.monotonic()+(self.timeout or 60)
        if not _OLLAMA_GATE.acquire(timeout=self.timeout or 60):
            raise LLMError('本機模型忙碌超過 60 秒，請稍後再試。')
        try:
            if time.monotonic() >= deadline:
                raise LLMError('本機模型等待超過 60 秒，尚未開始生成。')
            return self._native_chat_impl(messages,temperature,images,num_predict,deadline)
        finally:
            _OLLAMA_GATE.release()

    def _native_chat_impl(self, messages, temperature=0.2, images=None, num_predict=4096, deadline=None):
        """Call Ollama native /api/chat with thinking explicitly disabled."""
        root = self.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        native_messages = [dict(m) for m in messages]
        if images:
            for m in reversed(native_messages):
                if m.get("role") == "user":
                    m["images"] = list(images)
                    break
        payload = json.dumps({
            "model": self.model,
            "messages": native_messages,
            "stream": True,
            "think": False,
            "options": {"temperature": temperature, "num_predict": int(num_predict)},
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(root + "/api/chat", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        deadline=deadline or time.monotonic()+(self.timeout or 60)
        try:
            with urllib.request.urlopen(req, timeout=max(.1,deadline-time.monotonic())) as response:
                pieces=[]
                data={}
                for line in response:
                    remaining=deadline-time.monotonic()
                    if remaining <= 0:
                        raise LLMError('本機模型生成超過 60 秒，已關閉串流，不再執行後續模型任務。')
                    try:
                        response.fp.raw._sock.settimeout(remaining)
                    except AttributeError:
                        pass
                    if not line.strip():
                        continue
                    data=json.loads(line.decode('utf-8'))
                    if data.get('error'):
                        raise LLMError('Ollama：'+str(data['error']))
                    pieces.append((data.get('message') or {}).get('content') or '')
                    if data.get('done'):
                        break
                if not data.get('done'):
                    raise LLMError('本機模型串流中斷，尚未完成回應。')
                data['message']={'content':''.join(pieces)}
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1200]
            except Exception:
                pass
            suffix = f"：{detail}" if detail else ""
            raise LLMError(f"Ollama API HTTP {exc.code}{suffix}") from exc
        except Exception as exc:
            raise LLMError(f"Ollama API 呼叫失敗：{exc}") from exc
        content = ((data.get("message") or {}).get("content") or "")
        return {"choices": [{"message": {"role": "assistant", "content": content},
                             "finish_reason":"length" if data.get('done_reason')=='length' else 'stop'}], "_ollama": data}

    def _request(self, messages, temperature=0.2):
        return self._native_chat(messages, temperature=temperature, num_predict=4096)

    def complete_json_with_images(self, system, user, images):
        data = self._native_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.15, images=images, num_predict=4096,
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError("Ollama Vision 回傳格式錯誤。") from exc
        return self._parse_json_text(text)


class GroqLLM(OpenAICompatibleLLM):
    provider = "groq"

    def __init__(self, model, api_key="", base_url=GROQ_BASE_URL, timeout=60):
        super().__init__(base_url, model, api_key, timeout=timeout)
        self.max_output_tokens = max(128, min(800, int(os.getenv('GROQ_MAX_OUTPUT_TOKENS', '800'))))
        self.max_input_bytes = max(2000, min(24000, int(os.getenv('GROQ_MAX_INPUT_BYTES', '16000'))))

    def _request_options(self):
        # A per-request cap; this does not replace Groq's per-minute quota.
        options = {"max_completion_tokens": self.max_output_tokens}
        if self.model.startswith('openai/gpt-oss-'):
            options.update(reasoning_effort='low', include_reasoning=False,
                           response_format={'type': 'json_object'})
        if self.model == "qwen/qwen3.8-27b":
            options["reasoning_effort"] = "none"
        return options

    def _request(self, messages, temperature=0.2):
        # UTF-8 bytes are a conservative bound, not an exact tokenizer count.
        size = len(json.dumps(messages, ensure_ascii=False).encode('utf-8'))
        if size > self.max_input_bytes:
            raise LLMError(f'送入模型的內容超過 {self.max_input_bytes} bytes 上限，請縮短內容或分批匯入。尚未呼叫 API。')
        if __package__:
            from .jobs import guard, usage
            guard(size+self.max_output_tokens+512)
        else:
            usage=lambda *args:None
        started=time.monotonic()
        try:
            data=super()._request(messages, temperature)
            try:
                usage(data,self.model,time.monotonic()-started)
            except OSError:
                pass
            return data
        except LLMError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 429:
                raise LLMError('Groq 額度不足或單次內容超過限制，請減少內容或稍後重試。已停止後續呼叫。') from exc
            raise

    def complete_json(self, system, user):
        if not self.api_key:
            raise LLMError("Groq 尚未設定 API Key。請在 .env 填入 GROQ_API_KEY。")
        return super().complete_json(system, user)

    def ping(self):
        if not self.api_key:
            return {
                "ok": False,
                "message": "Groq API Key 未設定；將由本機 fallback 接手（若有設定）。",
                "provider": self.provider,
                "model": self.model,
            }
        return super().ping()


class FallbackLLM(BaseLLM):
    """Primary model fails -> retry once with fallback model.

    Typical production path in this project:
      Groq high-capability model -> local Ollama qwen3.5:4b.
    """

    enabled = True

    def __init__(self, primary: BaseLLM, fallback: BaseLLM):
        self.primary = primary
        self.fallback = fallback
        self.provider = f"{getattr(primary, 'provider', 'primary')}→{getattr(fallback, 'provider', 'fallback')}"
        self.model = f"{getattr(primary, 'model', '')} | fallback:{getattr(fallback, 'model', '')}"
        self.last_used = None

    def complete_json(self, system: str, user: str):
        try:
            result = self.primary.complete_json(system, user)
            self.last_used = {"provider": self.primary.provider, "model": self.primary.model, "fallback": False}
            return result
        except Exception as primary_exc:
            if not getattr(self.fallback, "enabled", False):
                raise
            try:
                result = self.fallback.complete_json(system, user)
                self.last_used = {
                    "provider": self.fallback.provider,
                    "model": self.fallback.model,
                    "fallback": True,
                    "primary_error": str(primary_exc),
                }
                return result
            except Exception as fallback_exc:
                raise LLMError(
                    f"Primary 與 fallback 都失敗。Primary={primary_exc}；Fallback={fallback_exc}"
                ) from fallback_exc

    def ping(self):
        primary_result = self.primary.ping()
        fallback_result = self.fallback.ping()
        return {
            "ok": bool(primary_result.get("ok") or fallback_result.get("ok")),
            "message": (
                f"Primary: {primary_result.get('message')} | "
                f"Fallback: {fallback_result.get('message')}"
            ),
            "provider": self.provider,
            "model": self.model,
            "primary": primary_result,
            "fallback": fallback_result,
        }


def _provider_instance(provider, base, model, key=""):
    provider = str(provider or "disabled").lower().strip()
    model = str(model or "").strip()
    if provider == "mock":
        return MockLLM()
    if not model:
        return BaseLLM()
    if provider == "ollama":
        return OllamaLLM(base or OLLAMA_BASE_URL, model, key)
    if provider == "groq":
        return GroqLLM(model=model, api_key=key, base_url=base or GROQ_BASE_URL)
    if provider in ("openai_compatible", "api"):
        return OpenAICompatibleLLM(base or OLLAMA_BASE_URL, model, key)
    return BaseLLM()


def _api_key_for(config, prefix: str, provider: str, fallback_prefix: str | None = None):
    value = config.get(f"{prefix}_API_KEY")
    if not value and fallback_prefix:
        value = config.get(f"{fallback_prefix}_API_KEY")
    if not value:
        value = config.get("LLM_API_KEY")
    if not value and str(provider).lower() == "groq":
        value = config.get("GROQ_API_KEY")
    return value or ""


def get_llm(config):
    provider = str(config.get("LLM_PROVIDER", "groq")).lower()
    model = str(config.get("LLM_MODEL") or "openai/gpt-oss-20b").strip()
    base = config.get("LLM_BASE_URL") or (GROQ_BASE_URL if provider == "groq" else OLLAMA_BASE_URL)
    key = _api_key_for(config, "LLM", provider)
    return _provider_instance(provider, base, model, key)


def get_classifier_llm(config):
    provider = str(config.get("CLASSIFIER_PROVIDER") or "groq").lower()
    model = str(config.get("CLASSIFIER_MODEL") or "openai/gpt-oss-20b").strip()
    base = config.get("CLASSIFIER_BASE_URL") or (GROQ_BASE_URL if provider == "groq" else OLLAMA_BASE_URL)
    key = _api_key_for(config, "CLASSIFIER", provider, "LLM")
    primary = _provider_instance(provider, base, model, key)

    fb_provider = str(config.get("CLASSIFIER_FALLBACK_PROVIDER") or "").lower()
    fb_model = str(config.get("CLASSIFIER_FALLBACK_MODEL") or "").strip()
    if fb_provider and fb_model:
        fb_base = config.get("CLASSIFIER_FALLBACK_BASE_URL") or (GROQ_BASE_URL if fb_provider == "groq" else OLLAMA_BASE_URL)
        fb_key = config.get("CLASSIFIER_FALLBACK_API_KEY") or (config.get("GROQ_API_KEY") if fb_provider == "groq" else "")
        return FallbackLLM(primary, _provider_instance(fb_provider, fb_base, fb_model, fb_key))
    return primary


def _get_role_llm(config, prefix: str, fallback_prefix: str = "LLM"):
    provider = str(
        config.get(f"{prefix}_PROVIDER")
        or config.get(f"{fallback_prefix}_PROVIDER")
        or config.get("LLM_PROVIDER", "groq")
    ).lower()
    model = str(
        config.get(f"{prefix}_MODEL")
        or config.get(f"{fallback_prefix}_MODEL")
        or config.get("LLM_MODEL", "openai/gpt-oss-20b")
    ).strip()
    base = (
        config.get(f"{prefix}_BASE_URL")
        or config.get(f"{fallback_prefix}_BASE_URL")
        or config.get("LLM_BASE_URL")
        or (GROQ_BASE_URL if provider == "groq" else OLLAMA_BASE_URL)
    )
    key = _api_key_for(config, prefix, provider, fallback_prefix)
    primary = _provider_instance(provider, base, model, key)

    fb_provider = str(config.get(f"{prefix}_FALLBACK_PROVIDER") or "").lower().strip()
    fb_model = str(config.get(f"{prefix}_FALLBACK_MODEL") or "").strip()
    if fb_provider and fb_model:
        fb_base = config.get(f"{prefix}_FALLBACK_BASE_URL") or (GROQ_BASE_URL if fb_provider == "groq" else OLLAMA_BASE_URL)
        fb_key = config.get(f"{prefix}_FALLBACK_API_KEY") or (config.get("GROQ_API_KEY") if fb_provider == "groq" else "")
        fallback = _provider_instance(fb_provider, fb_base, fb_model, fb_key)
        return FallbackLLM(primary, fallback)
    return primary


def get_parser_llm(config):
    provider = str(config.get("PARSER_PROVIDER") or "groq").lower()
    model = str(config.get("PARSER_MODEL") or "openai/gpt-oss-20b").strip()
    base = config.get("PARSER_BASE_URL") or (GROQ_BASE_URL if provider == "groq" else OLLAMA_BASE_URL)
    key = _api_key_for(config, "PARSER", provider, "LLM")
    return _provider_instance(provider, base, model, key)


def get_generator_llm(config):
    return _get_role_llm(config, "GENERATOR", "LLM")


def get_reviewer_llm(config):
    return _get_role_llm(config, "REVIEWER", "GENERATOR")


def get_course_llm(config):
    return _get_role_llm(config, "COURSE", "GENERATOR")


def get_tutor_llm(config):
    return _get_role_llm(config, "TUTOR", "COURSE")


def model_usage_label(model: BaseLLM) -> str:
    """Human-readable label for the model that actually answered the last request."""
    last = getattr(model, "last_used", None)
    if isinstance(last, dict) and last.get("model"):
        suffix = " (fallback)" if last.get("fallback") else ""
        return f"{last.get('provider')}:{last.get('model')}{suffix}"
    provider = getattr(model, "provider", "") or "LLM"
    name = getattr(model, "model", "") or "unknown"
    return f"{provider}:{name}"
