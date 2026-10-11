# 考題 CPU 分工模式使用說明

已安裝在專案 .venv-exam-ai（Python 3.12），與主程式 Python 隔離。兩個 ONNX 模型位於 models/exam，均明確使用 CPUExecutionProvider；不使用 CUDA。

## 已接入流程

- 概念匯入：CPU E5 候選檢索 → MiniLM NLI 分類初篩 → 已訓練分類頭建議（若有）→ 每 8 題一次本機 LLM 最終裁決。
- 動態出題：教材候選 → CPU 排序取前 4 段 → 支援範圍的程式答案模板／必要的模型新題 → CPU 重複選項、答案標籤與語意支持初篩 → 每 4 題一次 LLM 最終裁決 → 草稿／人工核准。
- 固定隨機模考保持不呼叫 AI。
- 本機模型採串流、60 秒時間限制，每個應用程序一次一個 Ollama 請求；逾時或不完整裁決不繼續後續子任務。多程序部署需設定單一模型工作程序，這個鎖不是跨程序鎖。
- 串流逾時會關閉連線，但沒有保證 Ollama 服務一定立即停止正在執行的推論；尚未實作前台任務取消按鈕／跨程序工作佇列。

## 使用

重啟 AI Butler；AI 出題頁選「分工節能」或「全新情境」。節能模板只支援：難度 1–2、單選、沒有指定 focus，且概念為迴圈／串列、條件判斷或 SQL 排序。其他範圍維持生成模型出題。模板題會標示來源，不能當成全新高階情境。

.env 中 EXAM_MODULAR_AI=true 已啟用；EXAM_MODULAR_AI=false 可切回舊分類／審題流程。Ollama 串流與 60 秒限制不受此旗標影響。

CPU worker 每個操作最多等 60 秒，超時會停止 worker。模型載入與推論尚未測試，建議使用者從少量題目開始自行驗證。

重新安裝／下載（Python 3.12）：

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_exam_ai.ps1 -Python python
```

## 特製分類模型

只接受人工確認過的 JSONL，欄位：content、q_type、concept_name、skill、cognitive_level、subject_id、human_verified。例：

```json
{"content":"type(12) 屬於什麼型別？","q_type":"單選","concept_name":"變數與型別","skill":"辨識資料型別","cognitive_level":"understand","subject_id":4,"human_verified":true}
```

```powershell
.\.venv-exam-ai\Scripts\python.exe tools/train_exam_heads.py 人工標註題庫.jsonl
```

題型／認知層次使用全域分類頭；概念／技能使用科目獨立分類頭。每類至少 20 個人工確認樣本才訓練；此門檻只避免極端資料不足，不代表準確率保證。訓練後仍標示 trained_unvalidated，只當最終 LLM 的建議，不自動取代答案或分類。須使用者另外建立獨立驗證資料，再做校準及評估。訓練後重啟系統載入新分類頭。

目前的 12 題示範資料不足，所以沒有假造訓練結果，也沒有自動把 LLM 產生的標籤當人工真值。

## 尚未實作的範圍

掃描文件的專用 OCR、任意 Python 程式隔離執行、任意 SQL 題沙盒驗證、答對率模型與跨程序排隊取消不在此版。不要把 NLI 的支持分數視為正確答案的保證。現有解析器的 AI/Vision fallback 仍可能呼叫模型；快速解析可避開。

## 安裝與驗證狀態

已下載 E5 與 MiniLM ONNX 模型及 tokenizer/config。已安裝 ONNX Runtime、tokenizers、huggingface_hub、NumPy、scikit-learn、joblib。未執行模型推論、功能測試或 GPU benchmark，遵照使用者要求。沒有修改 BODY／運動模組。
