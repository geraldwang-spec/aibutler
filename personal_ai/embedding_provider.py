from __future__ import annotations

import hashlib
import json
import math
import urllib.request


class EmbeddingError(RuntimeError):
    pass


class BaseEmbedding:
    enabled = False
    provider = "disabled"
    model = ""

    def embed(self, texts):
        raise EmbeddingError("Embedding 尚未設定。請設定 EMBEDDING_PROVIDER / EMBEDDING_MODEL。")

    def embed_query(self, text):
        return self.embed([text])[0]

    def ping(self):
        return {"ok": False, "message": "Embedding 尚未設定。", "provider": self.provider, "model": self.model}


class MockEmbedding(BaseEmbedding):
    enabled = True
    provider = "mock"
    model = "mock-embedding-384"

    @staticmethod
    def _one(text):
        # Stable deterministic vector for workflow testing only.
        values = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < 384:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend((b - 127.5) / 127.5 for b in digest)
            counter += 1
        values = values[:384]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def embed(self, texts):
        return [self._one(str(t)) for t in texts]

    def ping(self):
        return {"ok": True, "message": "Mock Embedding 可用（僅供流程測試）。", "provider": self.provider, "model": self.model}


class OpenAICompatibleEmbedding(BaseEmbedding):
    enabled = True
    provider = "openai_compatible"

    def __init__(self, base_url, model, api_key="", timeout=90):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def embed(self, texts):
        payload = json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/embeddings", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            rows = sorted(data["data"], key=lambda x: x.get("index", 0))
            return [row["embedding"] for row in rows]
        except Exception as exc:
            raise EmbeddingError(f"Embedding API 呼叫失敗：{exc}") from exc

    def ping(self):
        try:
            vec = self.embed(["AI Butler embedding connection test"])[0]
            return {"ok": bool(vec), "message": f"Embedding API 連線成功，維度 {len(vec)}。", "provider": self.provider, "model": self.model}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "provider": self.provider, "model": self.model}


class OllamaEmbedding(BaseEmbedding):
    enabled = True
    provider = "ollama"

    def __init__(self, base_url, model, timeout=90):
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.base_url = base
        self.model = model
        self.timeout = timeout

    def embed(self, texts):
        payload = json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/api/embed", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["embeddings"]
        except Exception as exc:
            raise EmbeddingError(f"Ollama embedding 呼叫失敗：{exc}") from exc

    def ping(self):
        try:
            vec = self.embed(["AI Butler embedding connection test"])[0]
            return {"ok": bool(vec), "message": f"Ollama Embedding 連線成功，維度 {len(vec)}。", "provider": self.provider, "model": self.model}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "provider": self.provider, "model": self.model}


class CPUEmbedding(BaseEmbedding):
    enabled = True
    provider = 'cpu'
    model = 'intfloat/multilingual-e5-small'

    @staticmethod
    def _encode(texts):
        from .exam_modules import cpu, ExamModuleError
        try:
            return cpu('embed', texts=texts)
        except ExamModuleError as exc:
            raise EmbeddingError(str(exc)) from exc

    def embed(self, texts):
        vectors = []
        for start in range(0, len(texts), 8):
            vectors.extend(self._encode(['passage: ' + str(t) for t in texts[start:start+8]]))
        return vectors

    def embed_query(self, text):
        return self._encode(['query: ' + str(text)])[0]

    def ping(self):
        try:
            vector = self.embed_query('CPU embedding connection test')
            return dict(ok=bool(vector), message=f'CPU Embedding 可用，維度 {len(vector)}。', provider=self.provider, model=self.model)
        except EmbeddingError as exc:
            return dict(ok=False, message=str(exc), provider=self.provider, model=self.model)


def get_embedder(config):
    provider = str(config.get("EMBEDDING_PROVIDER", "disabled")).lower()
    model = str(config.get("EMBEDDING_MODEL", "")).strip()
    if provider == 'cpu':
        return CPUEmbedding()
    if provider == "mock":
        return MockEmbedding()
    if not model:
        return BaseEmbedding()
    if provider == "ollama":
        return OllamaEmbedding(config.get("EMBEDDING_BASE_URL") or "http://127.0.0.1:11434", model)
    if provider in ("openai_compatible", "api"):
        return OpenAICompatibleEmbedding(
            config.get("EMBEDDING_BASE_URL") or "http://127.0.0.1:11434/v1",
            model,
            config.get("EMBEDDING_API_KEY", ""),
        )
    return BaseEmbedding()


def vector_literal(values):
    return "[" + ",".join(format(float(x), ".10g") for x in values) + "]"
