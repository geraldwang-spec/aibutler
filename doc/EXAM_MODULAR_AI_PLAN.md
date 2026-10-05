# 考題模組分工架構提案（僅規劃，尚未實作）

日期：2026-10-05。適用目前 RTX 3070 / 8GB 與本機 4B 模型。範圍只含考題、教材與學習排程，不含 BODY／運動模組。

## 目前已完成

admin123 有兩個獨立示範科目：固定題庫 12 題；概念題庫 6 個概念、12 個來源樣本。示範為 Python / SQL 入門單選題。

重建指令（已執行成功，可重跑，不會重複新增相同示範題）：

```powershell
python tools/seed_exam_demo.py
```

只有考題相关缺少的資料表會用 CREATE TABLE IF NOT EXISTS 補建；不清空、不改運動資料。登入帳號必須已存在。資料表 DDL 會由 MariaDB 隱含提交，因此建表與示範資料寫入不能視為同一可回復交易。

範例檔：test_data/exam_demo/入門固定題庫.csv、入門文字題庫.txt。

## 主架構

輸入 → 格式解析／OCR → 題型與概念分類 → 題庫／教材檢索 → 任務決策 → 原題抽取或模板組題 → 規則驗證 → LLM 最終整合／少量語句生成 → 結構驗證 → 人工確認／儲存。

LLM 是 AI 工作流程的最終裁決與語言整合層。分類器及求解器先決定候選方案，LLM 接收題目 ID、概念標籤、候選答案、必要證據與衝突清單，輸出 accept / revise / needs_review 與短理由。它不必重新閱讀整份教材或重新產生所有 JSON。不能讓 LLM 的同意覆蓋外鍵、答案選項、章節權限、計算正確性等硬性規則。固定隨機模考維持不呼叫 AI 的既有約定。

## 模組選擇

| 工作 | 第一選擇 | 運行位置／限制 |
| --- | --- | --- |
| CSV、Excel、Word、文字型 PDF | csv、openpyxl、python-docx、PyMuPDF | CPU；沿用既有解析器 |
| 掃描 PDF、圖片 | PP-OCRv5；多欄／表格才用 PP-StructureV3 | 先評估 CPU；不要對所有文件跑 OCR；獨立環境確認 Python 版本相容性 |
| 單選、多選、是非、填空辨認 | 格式規則；模糊資料用字元 n-gram TF-IDF + LogisticRegression | CPU；需要已標註資料，不能宣稱開箱就懂本校題型 |
| 科目、Concept、Skill 標籤 | embeddings 近鄰 + 分類器；資料較少可評估 SetFit | CPU 優先；新概念／低信心轉 LLM 或人工；信心要校準 |
| 檢索與去重 | 保留 bge-m3 + 關鍵字檢索；CPU 壓力大再比較 multilingual-e5-small | 快取教材與概念向量；換模型要重建索引；不混用不同維度向量 |
| 重排序 | 僅在必要時引入 Cross-Encoder | CPU、只重排少量候選；先驗證是否實際改善 |
| 難度、弱項、出題配額 | 規則及統計；有足夠歷史紀錄再訓練分類模型 | CPU；未蒐集真實作答前，不宣稱難度模型有效 |
| 學習排程 | 簡單規則；複雜時用 OR-Tools CP-SAT | CPU；選題數、時間與先後依賴，交 LLM 解釋即可 |
| 固定模考 | 資料庫篩選 + 不重複隨機抽樣 | 不使用生成模型 |
| 入門動態題 | 經人工審核的模板 + 參數化出題 + 解答函式 | CPU；改數字只能當基礎練習，不能冒充新的高階情境題 |
| 新情境題、教學語句 | 原本本機 qwen3.5:4b | GPU；需真正的新內容時仍然要生成相應 tokens |
| 最終裁決 | 同一個 4B 模型短批次整合 | GPU；不再新增一個獨立常駐大型 Reviewer |

最適合第一版：既有規則解析 + 分類器 + 現有 bge-m3 快取 + 模板出題 + 同一個 4B 最終整合。SetFit、OCR、重排序與求解器依需求逐步加入，不一次裝滿模型。

## 任務與 GPU 生命週期

1. 前台交付任務 ID，後台排隊；顯示解析／分類／組題／驗證／最終整合進度。
2. GPU 併發先限制為 1，避免 Embedding、Generator、Reviewer 同時搶 8GB 顯存。分類、解析與求解先留在 CPU。
3. 模型結果與 embedding 依內容雜湊、模型版本、提示版本快取；修改題目後失效。
4. 保留 60 秒等待設定，但另外需要端到端截止時間、取消旗標、關閉串流、取消後停止後續子任務。socket timeout 不等於整個任務最多 60 秒，也不保證模型立即停算。
5. keep_alive 控制閒置卸載；它不是取消正在運算的機制。卸載與取消需分開處理，不能任意停止同學或其他使用者共用的模型服務。
6. 狀態明確區分 queued / running / cancelled / timed_out / failed / completed；取消後不寫入未完成考卷。

## 負擔評估（情境推算，非實測）

不能把 LLM token 減少比例直接當作 GPU 使用率降低比例。GPU 生成期間仍可能 100%，但工作時間與總運算量可以降低；常駐 4B 權重顯存不會因改成分工就自動縮小。

規劃目標：結構化匯入／標籤辨識的 LLM token 量減少 70–95%；模板占大多數的基礎出題減少 60–85%；大量全新情境題僅減少約 10–40%。這些區間取決於文件規則性、模板占比、分類正確率、最後 LLM 重看內容的長度。沒有 GPU 時間量測，不能提供可信的實際 GPU 降幅。

示例：10 題基礎題，舊流程生成題目約 2500 tokens，再審 10 題各 150 tokens，合計 4000 output tokens。新流程若 8 題模板、2 題需生成約 500 tokens，最後批次短裁決 300 tokens，合計 800 tokens，輸出量約減少 80%。若 10 題都要新內容，2500 + 300 = 2800，只有約 30%。這是具假設的算式，並非此專案目前的量測值。

整體 GPU 秒數節省量應以原工作負載中可移交的占比估算：若 70% GPU 工作可移交，該部分減少 80%，其餘減少 20%，整體理論節省 0.7×0.8 + 0.3×0.2 = 62%；還需扣除新模組、最終裁決與搬移資料的成本。

後續由使用者決定測試：同一批 100 題匯入、20 題固定抽題、10 題模板混合出題、10 題全新題，對照 input/output tokens、prompt_eval_duration、eval_duration、總等待時間、峰值顯存、需人工修正比例、答案正確率。不要只看工作管理員瞬間 GPU 百分比。

## 先做順序

第一階段：任務佇列與取消、單 GPU 工作、模型／向量快取、減少重複審題、規則驗證。
第二階段：收集人工確認的題型／Concept 標籤，建立 CPU 分類器與模板題。
第三階段：驗證需求後才加 OCR、重排序、學習排程求解器。

## 查閱來源

- PaddleOCR PP-StructureV3：https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html
- scikit-learn LogisticRegression：https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html
- 分類信心校準：https://scikit-learn.org/stable/modules/calibration.html
- SetFit：https://huggingface.co/docs/setfit/main/en/index
- BGE-M3：https://huggingface.co/BAAI/bge-m3
- multilingual-e5-small：https://huggingface.co/intfloat/multilingual-e5-small
- 檢索與重排序：https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- OR-Tools 排程：https://developers.google.com/optimization/scheduling
- Ollama 回應計時、tokens、keep_alive：https://docs.ollama.com/api/generate
