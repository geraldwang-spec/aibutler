# AI Butler Personal AI

個人化學習系統：題庫／教材匯入、RAG + LLM 動態出題、自動批閱、錯題與弱項分析、學習規劃、系統小考／Checkpoint、AI 微課程。

## 快速啟動

### 本機開發
1. 建立 Python 環境並安裝：`pip install -r requirements.txt`
2. 執行 `run_dev.bat`（或 `run_dev.ps1`）
3. 瀏覽器開啟 Flask 顯示的本機網址。

### 真模型
1. 執行 **`INSTALL_MODELS.bat`**。這是唯一保留的模型安裝入口。
2. 如需 Groq，執行 `SET_GROQ_KEY.bat` 或自行設定 `.env`。
3. 執行 `RUN_REAL_AI.bat`。

目前模型與用途請看 `MODEL_INVENTORY.md`。

## 學習規劃
學習規劃採真正月曆視圖。一般學習任務不允許手動點擊完成；系統小考與階段 Checkpoint 必須依實際成績判定是否通過。完整 UI／功能規格請看 `LEARNING_CALENDAR_SPEC.md`。

## 主要目錄
- `personal_ai/`：個人 AI、RAG、Concept、學習規劃與微課程
- `TYE/`：模擬考／批閱相關模組
- `templates/`、`static/`：共用前端
- `tools/`：模型與環境工具
- `tests/`：測試

## 保留文件原則
正式專案只保留必要文件：
- `README.md`
- `MODEL_INVENTORY.md`
- `LEARNING_CALENDAR_SPEC.md`

開發過程的 Patch README、修正紀錄、階段性筆記不放入正式交付包。
