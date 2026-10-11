# MODEL INVENTORY

本檔只記錄正式專案目前實際使用／預留的 AI 模型與責任。新增、替換或移除模型時必須同步更新。

| 功能 | Provider | 模型 | 狀態 |
|---|---|---|---|
| 通用文字 LLM | Groq API | `qwen/qwen3.8-27b` | 實際使用，單一 `GROQ_API_KEY` |
| 題目知識概念／Concept 分類 | Groq API | `qwen/qwen3.8-27b` | 實際使用，單一 `GROQ_API_KEY` |
| 文件 / 題庫 LLM 解析 | Groq API | `qwen/qwen3.8-27b` | 實際使用，單一 `GROQ_API_KEY` |
| Embedding / RAG / 相似度 | Ollama | `bge-m3` | 實際使用 |
| 動態出題 | Groq | `qwen/qwen3.8-27b` | 有 API Key 時使用 |
| 出題審核 | Groq | `qwen/qwen3.8-27b` | 有 API Key 時使用 |
| AI 微課程 | Groq | `openai/gpt-oss-120b` | 有 API Key 時使用 |
| Tutor / 後續追問 | Groq | `openai/gpt-oss-120b` | 有 API Key 時使用 |
| 語音轉文字 | Local | Whisper `large-v3` | 安裝後可用 |
| 中文語音輸出 | Local | Kokoro `Kokoro-82M-v1.1-zh` | 安裝後可用 |

## Fallback 規則

Groq 未設定、逾時或不可用時，Generator / Reviewer / Course / Tutor 依目前設定回退到本機 Ollama `qwen3.5:4b`。Embedding 使用 `bge-m3`。

## 模型安裝入口

正式專案只保留一個模型安裝腳本：

`INSTALL_MODELS.bat`

它負責呼叫 `tools/setup_real_models.py`。舊的 `install_ai_models.bat` 與 voice-only 舊安裝腳本不再放入正式專案。

## 設計原則

模型只是可替換的推理／生成元件；題庫、Concept、RAG、批閱、學習規劃、Checkpoint 等核心流程不綁死單一模型。切換 Provider 或模型時應優先修改 `.env`，避免改動業務流程。
