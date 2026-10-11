# Groq LLM 設定

對話、課程、題庫文字解析、分類、出題與審核皆使用 `openai/gpt-oss-20b`。
各角色 API key 留空，以既有 `GROQ_API_KEY` 共用。不得將金鑰寫入文件。
本地 LLM fallback 已關閉。修改 `.env` 後須重新啟動 AI Butler。

## 輸出與輸入限制

- `.env` 的 `GROQ_MAX_OUTPUT_TOKENS=800`：每次請求輸出最多 800 tokens，包含推理 tokens；程式硬上限亦為 800。
- `reasoning_effort=low`；不傳回推理內容，使用 JSON 回覆。
- `GROQ_MAX_INPUT_BYTES=16000`：messages 序列化後的 UTF-8 bytes 上限。這不是精確 token 數；超限直接拒絕，不任意截斷整份使用者文件。
- 單次 API timeout 60 秒；429 不自動重試，也不啟用本地備援。
- 出題每次一題，分類與最終審核每批兩題。多題任務含多次請求，總耗時可能超過 60 秒。
- 每次限制不等同帳號每分鐘限制，連續請求仍可能觸發 Groq 429。
- 複雜 JSON 可能達到輸出上限而失敗；系統會明確報錯，不寫入截斷結果。

## GPU 與其他模組

教材搜尋改用 CPU E5 對文字候選進行排序，不使用 Ollama、不修改原有資料庫向量欄位或混用不同向量維度。
考題 CPU 專家模型仍使用 CPU。運動模組維持獨立配置，未修改其程式；目前沒有 `body/body.env`。
語音模組獨立於 LLM 設定。本設定不能保證其他程式或語音功能不使用 GPU。
GPT-OSS 文字模式不接收掃描圖片；掃描 PDF 需先 OCR 為可讀文字再匯入。

依使用者要求，未執行測試或模型推論。
