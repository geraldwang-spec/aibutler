# CPU 與長題匯入修正

目前工作分支：main。E5、MiniLM NLI 與 RapidOCR 使用獨立的 Python 3.12
環境 `.venv-exam-ai`，不使用 GPU。模型下載目錄為 `models/exam`。

## 安裝與檢查

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_exam_ai.ps1
.\.venv-exam-ai\Scripts\python.exe -X utf8 tools/check_exam_ai.py
```

安裝腳本保留既有環境內容、補齊套件和模型檔，最後實際執行 E5、NLI 與
中文 OCR 測試。檢查腳本不使用雲端 API 或應用程式資料庫。
專用題型／概念／技能分類頭需要人工確認的訓練資料；沒有 trained manifest
時維持「尚未訓練」，不以假模型補上。`EXAM_MODULAR_AI` 保留本機原設定。

## 文件匯入

- 規則解析支援全形題號、括號選項、題目/Question 標記、英文答案標記、
  無題號的空行分隔題目、多行解析及有範圍標記的共用題組文章。
- Word 的段落與表格維持原始順序；PDF 文字層明顯異常時使用 CPU OCR。
- AI 解析以有界視窗標記原文欄位位置，由程式取回原文，避免長題全文輸出
  遭 800-token 上限截斷。任何視窗缺少或重複片段時停止，不默默匯入部分題目。
- 長題概念分類先逐段建立分類脈絡，原題不改寫；結果標示需人工複核。
  長題可能需要較多 API 呼叫，仍受既有 AI 工作預算與服務端額度限制。
- 題目及解析最多 20,000 字、每欄 UTF-8 最多 60,000 bytes；選項最多
  10,000 字。超限會提示，不截短；配合既有 MariaDB TEXT 欄位。
- 新解析方式不是對所有版面正確率的保證。答案缺失、公式圖形、重複題號、
  多欄閱讀順序等仍須在預覽中確認，必要時在文字工作區修正。

## 驗證紀錄

- E5 384 維向量、NLI 三分類、中文 OCR 實際推論成功，ONNX session
  僅啟用 CPUExecutionProvider。
- 主程式 Python 原先缺少 python-docx，已補齊 1.2.0 與 lxml；PDF、Excel
  解析套件皆已存在。
- 十一項新測試通過，含長題尾段保存、12,000 字題目寫入隔離預覽資料庫、
  非固定格式、題組文章、數字選項、Word 表格順序、欄位長度及漏題防護。
- 原有 51 項回歸測試有 3 failures / 7 errors；換回 Git 原版解析器後結果
  相同，涉及舊介面、背景匯入與 Body API 測試，不由本次解析修正引入。
- 測試時目前 `.env` 未提供 Groq 金鑰，真實雲端版面解析尚未驗證。

變更後請重啟應用程式。資料庫、既有題庫與 API 金鑰未由本次修正更動。
