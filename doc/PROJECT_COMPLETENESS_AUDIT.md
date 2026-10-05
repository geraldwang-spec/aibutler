# AI Butler 專案完整性排查

> 本文是修正前排查記錄。2026-10-05 已實作的修正、備援方式與尚存限制，請見 [修正與復原記錄](REMEDIATION_AND_RECOVERY.md)；以下舊證據不代表修正後仍全部成立。

日期：2026-10-05。方法：檢查目前工作區原始碼、模板、設定、資料庫 schema、啟動與部署腳本；未執行測試、模型推論、HTTP 功能操作或正式資料庫查詢。未修改業務程式，BODY 僅唯讀檢查。

本報告依目前含未提交修改的工作區判斷。標示「已確認」指程式可直接確認的缺口；「風險」指缺少保護，實際故障頻率仍需操作驗證。並不以檔案存在代表功能已完成，也不給未經實測的完成百分比。

## 整體判斷

這是一個功能範圍廣、具備真實帳號與考題流程的學校專題，但尚未形成一致的使用者流程。主要缺口在資料關聯、AI 任務管理、匯入人工修正、學習評量及部署一致性。繼續增加模型之前，应先補齊現有流程；更多模型不能解決連線生命週期、資料重複及完成狀態不一致。

優先完成兩條流程：

1. 固定題庫：匯入 → 預覽與修正 → 正式題庫 → 普通抽題 → 作答／交卷 → 錯題 → 重練。
2. 自適應學習：概念來源 → 草稿生成／審核 → 正式題與概念關聯 → 概念弱項 → 微課程 → 階段驗收 → 規劃更新。

## 最優先處理

### A01｜P1｜MariaDB 連線關閉與初始化綁在一起【已確認】

證據：`smartlife.py:123` 只在 SQLite 或 AUTO_INIT_DB=true 呼叫 init_storage；`storage.py:258` 卻在 init_storage 內註冊唯一的 teardown_appcontext。目前是 MariaDB / AUTO_INIT_DB=false。

影響：目前組裝路徑沒有註冊共用 DB 的明確關閉鉤子。請求離開後無法依賴框架及時關閉連線，長任務與多使用者容易放大連線資源問題；不能斷言每個請求永久洩漏，仍可能由物件回收關閉。

建議：連線 teardown 無條件註冊；schema 初始化獨立。錯誤時 rollback，請求結束 close。這是共用層修正，需要兼顧同學 BODY 模組。

### A02｜P1｜敏感設定與 session 金鑰仍受 Git 追蹤【已確認】

證據：`git ls-files .env instance/session.key` 回傳兩個檔案；`.gitignore` 雖排除它們，既有追蹤仍存在。

影響：之後 commit／分享版本可能包含 API／DB 設定及簽署 session 的金鑰。是否已外流未檢查，也沒有輸出任何金鑰。

建議：移除追蹤但保留本機檔案；只維護無秘密的 example。若金鑰已提交並分享，需更換相關金鑰，必要時清理歷史。不要直接刪除同學共用檔案。

### A03｜P1｜核准 AI 草稿沒有建立 question_concepts【已確認】

證據：`personal_ai/routes.py:85` 核准只新增 questions、options、metadata；`personal_ai/coaching.py:32` 概念弱項依賴 question_concepts。動態模擬考另一條路徑在 `TYE/exam_module.py:245` 有建立關聯。

影響：同樣的 AI 題目，從草稿核准進固定題庫後作答，可能不會進入 Concept 弱項分析。正式題、概念與微課程的流程斷裂。

建議：使用單一正式題建立服務，一次建立題目、選項、concept id、metadata，核准與動態模擬考共用。

### A04｜P1｜跨章節草稿會卡住，缺少修正入口【已確認】

證據：`personal_ai/routes.py:90` 要求先指定章節；`personal_ai/templates/ai_questions.html` 只有核准按鈕，無章節編輯、題幹修正、退回／刪除。

影響：chapter_id 為空的草稿無法核准；模型答案有誤時也不能在審核頁直接修正。「先人工審核」目前主要等同接受或放棄。

建議：提供編輯草稿、指定章節與概念、退回、刪除；核准前重新執行格式檢查。

### A05｜P1｜交卷、核准及匯入確認缺少並行冪等保護【風險】

證據：`TYE/exam_module.py:374` 先讀 finished_at 再更新；`personal_ai/routes.py:85` 先讀 draft 狀態再新增；`smartlife.py` import_review 用 BEGIN IMMEDIATE，但 `storage.py` 在 MariaDB 僅轉為 begin，沒有 SELECT FOR UPDATE。source_question_items 的 import_item_id 未設唯一限制。

影響：循序重送有部分防護，但同時雙擊／兩分頁／多人請求可都讀到舊狀態，造成重複題目、重複來源或錯題計數更新不一致。

建議：交易內鎖住狀態列或條件更新並檢查 rowcount，配合唯一限制與 idempotency key。前端禁用按鈕只作輔助。

### A06｜P1｜AI token 限制尚未配合所有功能輸出需求【已確認的設計缺口】

證據：`personal_ai/llm_provider.py:253` 統一 800 completion tokens、16,000 UTF-8 bytes 輸入；`question_importer.py:230` 仍一次解析整份最多 20,000 字文件；`microcourse.py` 仍一次要求至少四種步驟，課程與 Tutor 傳入多段教材／歷史。

影響：一般內容容易觸發輸入拒絕；多題解析或完整課程 JSON 可能被截斷。這些是目前上限與請求設計不匹配的風險，未實測失敗門檻。僅改遠端模型不代表所有功能已相容。

建議：輸入先依功能組裝預算；解析以完整題目區塊分批，答案區獨立對照；課程先生成大綱、再逐步內容。輸出保留推理 tokens 所需空間。上限依角色配置且有硬限制，不以無上限解決。

### A07｜P1｜AI 缺少整個任務的額度、取消、續作與佇列【已確認】

證據：LLM 限制每次呼叫；出題、匯入分類都在同步 POST 中循序多次呼叫。500 題概念匯入在每批兩題時，僅最終分類就最多 250 次 Groq 請求；動態考卷可選 100 題。

影響：60 秒是單次 API timeout，整個功能可能遠超過 60 秒。關閉頁面不是取消任務；每次 800-token 上限也不是每日費用或每分鐘總量控制。

建議：AI job 表／背景 worker，狀態 queued/running/partial/completed/failed/cancelled；每任務最大請求數、累計 input/output tokens、deadline；只在批次邊界續作。先做小型工作佇列即可，不需要大型微服務。

### A08｜P1｜考卷與規劃結果分成兩次提交，失敗後無自動修復【已確認】

證據：`TYE/exam_module.py:423` 交卷 commit 後才 apply_planner_quiz_result；再次交卷在 finished_at 已存在時直接返回。checkpoint start 的 create_quiz 也先 commit，再建立 planner attempt。

影響：後半段失敗時，可能已交卷但階段未更新，或考卷已建立但未連結規劃。rollback 無法撤回前段提交。

建議：拆除服務內任意 commit，由外層控制原子交易；AI 生成不可整段占用交易時，可用明確的可復原狀態與補償流程。對已完成考卷允許安全重算 planner 結果。

## 功能不合理與完成度缺口

| ID／優先度 | 項目與具體影響 | 證據與建議 |
|---|---|---|
| A09／P1 | 一般問答頁只存提問，沒有 AI 回答。切換所有 LLM 設定不會自動補上這項功能。 | `records.py:44`、`smartlife.py:298`；真正 Tutor 在另外兩套流程。一般對话应接一個明确入口，或改名為提問筆記。 |
| A10／P2 | 匯入預覽沒有逐題編輯、移除及概念修正。低信心分類也只能整批接受。 | `templates/import_review.html` 只有確認按鈕；增設逐題修正、錯誤標記與只匯入合格題。 |
| A11／P1 | 真正無文字層的 PDF 在 parse_file 就拋錯，尚未抵達後面的 Vision fallback；現在 GPT-OSS 也不接受該圖片路徑。錯誤提示仍叫使用者重試 Vision。 | `personal_ai/parsers.py` PDF 分支、`question_importer.py:284`、`smartlife.py` 無題目提示。先 OCR 成文字，或清楚禁用扫描檔；不能把重試當解法。 |
| A12／P2 | 匯入 AI 解析直接 source[:20000]，沒有告知尾段被省略。 | `question_importer.py:230`；尾端答案區可能消失。按區塊分批並顯示頁數／題數對照，不靜默截斷。 |
| A13／P2 | DOCX 只讀 paragraphs，忽略表格中的題目／選項；TXT 固定 UTF-8 並替換錯誤字元。 | `personal_ai/parsers.py`；與 Notepad++ 常見 Big5／其他編碼及表格題庫不一致。提供編碼選擇、表格擷取與解析預覽。 |
| A14／P2 | 檔案大小規格不一致：全站 5 MB，匯入程式稱 20 MB。 | `smartlife.py:97`、`:503`；實際先被 Flask 擋下。統一設定與介面提示。 |
| A15／P1 | AI 題型格式驗證比手動題庫弱：單選 A,B 仍可能通過；是非值、答案長度等也未完整驗證。 | `services.py:41` 對照 smartlife.validate_question；所有來源共用同一 validator。匯入允許答案到 100 字，交卷只能 50 字，也應統一。 |
| A16／P1 | 微課程回答用子字串判斷，含答案的否定句也可能算對。 | `microcourse.py:317`；「不是 INNER JOIN」包含 INNER JOIN。客觀題使用固定答案；開放題使用可稽核 rubric，不能拿 contains 當掌握度。 |
| A17／P2 | 微課程可未答互動題就按完成；課程完成與後續驗收不強制連結。 | `microcourse.py:425`、micro_course 模板末尾；分開「已閱讀」「互動通過」「概念驗收」，不要把按鈕完成當學會。 |
| A18／P1 | 初始規劃把 _sort 由大到小排序，但此值越低表示越弱。 | `coaching.py:431` 對照 calculate_concept_weakness；強概念可能先排入前期，與弱項優先的註解相反。使用統一優先度方向。 |
| A19／P2 | 最多規劃 730 天，顯示任務只抓最早 366 筆。 | `coaching.py` 目標建立、`routes.py:256`；第二年或後期月份可能看不到任務。依所選月份查詢，列表分頁。 |
| A20／P2 | 規劃閱讀任務始終 planned，沒有閱讀紀錄；daily study_plans 與 learning_tasks 又使用不同完成方式。 | `_rebuild_goal_tasks`、records catalog；保留測驗作為掌握度門檻，但讀完任務也應有獨立狀態。 |
| A21／P1 | 錯題 Tutor 的 GET 每次重新生成並寫訊息。 | `routes.py:203` → coaching.answer_wrong_question；重新整理、返回頁面會追加費用及重複回覆。GET 顯示已有歷史，POST 才生成。 |
| A22／P2 | 正式題來源版本與錯題教學版本不完全一致。 | `coaching.py:131` 取目前題目答案／解析，但只從 snapshot 取 options；TYE 的錯題簿已有 snapshot 邏輯。共用考卷 snapshot 作教學基準。 |
| A23／P2 | 選擇題交卷使用標籤排序，但不重新驗證選項；填空完全字串相等。 | `TYE/exam_module.py:82`、`:401`；多選標準答案若未正規化順序會誤判；填空應支援明確設定的可接受答案／大小寫／數值容差，不能任意放寬。 |
| A24／P2 | 作答無草稿保存，未完成時不能交卷；刷新或離開會丟失輸入。 | quiz_take 模板及 exam/live JS；提供暫存／恢復及明確放棄考卷。限時模擬考與一般練習应区分是否允許空白交卷。 |
| A25／P2 | 概念同科目同名只能指向一個 chapter_id，跨章節概念合併後範圍可能偏向首次章節。 | schema_tye_personal_mariadb concepts 唯一 subject/name；建立 concept_chapters 關聯，或明確採科目層級概念與來源範圍查詢。 |
| A26／P2 | 固定匯入／手動題目沒有概念分類入口，普通測驗多半只能形成章節弱項。 | smartlife.import_review 固定分支、records.questions；可選擇補標概念，維持固定題目而不強迫動態生成。 |
| A27／P2 | 動態考卷把模型審查的題目標成 is_verified=1，容易與人工或程式驗證混淆。 | `TYE/exam_module.py:227`；拆成格式驗證、模型審核、專家計算、人工核准等來源及時間。 |

## 冗餘、效能與維護

| ID／優先度 | 已確認的現況 | 建議 |
|---|---|---|
| A28／P2 | 教材候選在 rag.retrieve CPU 排序後，services 又做一次相同 rank；E5/NLI 每題仍送最终 LLM，没有省略最終裁決。 | 刪除重複排序，快取候選；量測每題耗時／API 次數。保留 LLM 最終主體時，不宣稱大量 CPU 模型必然減少 API 次數。 |
| A29／P2 | E5/NLI tokenizer 固定截 256 tokens；長教材／題目超過部分不参与分數。 | 增設分段評分與 max 聚合；標示未校準分數，安排學校題庫標註後再評估。 |
| A30／P2 | dashboard GET 呼叫 refresh_stats，重算全部歷史、刪除再建立 daily_summary；每天另查肌群。 | 在寫入事件更新摘要，或一次聚合／快取；GET 不修改統計與計畫狀態。需與 BODY 同學協調共用層。 |
| A31／P2 | 科目、章節、題庫、兩種弱項、兩種計畫、兩種教材入口、兩種 Tutor／提問紀錄同時放在側欄。`/materials` 還是第二階段占位，`/knowledge` 才是真教材。 | 以「題庫」「練習／成績」「學習計畫」「AI 老師」「教材」為主入口；進階概念與環境移至子頁。頁面合併不等於立即刪表。 |
| A32／P2 | app.py 與 smartlife.py 重複維護各 AI 配置；啟動 bat 仍印 Qwen 27B 與 bge-m3；旧模板／空 route 模組保留。 | 一套設定來源、明確活躍入口，封存舊樣板並更新 README／MODEL_INVENTORY／啟動訊息。 |
| A33／P2 | 動態生成每次保存 questions＋drafts＋options＋metadata，正常固定池排除它們，但沒有歷史封存／清理方案。教材上傳解析失敗也未清理已存檔。 | 保存必要快照與生成來源；定義放棄任务／未使用草稿／失败上传保留期，避免直接刪除仍被考卷引用的題。 |
| A34／P2 | 概念列表主要只讀；缺少合併、改名、拆分、人工調整技能及來源。 | 提供最小概念維護工具；保留操作紀錄，避免重新分類破壞歷史弱項。 |
| A35／P2 | 全域 LLM 回應忽略 usage，不记录耗時與任务 token；BODY 已有數字型 usage log。 | 共用數字型用量記錄（不記秘密／完整輸入），由 job/user/feature/model 聚合，支援每日額度。 |

## 部署與完整性

### A36｜P1｜PostgreSQL 部署檔與 storage 實作不相容【已確認】

`docker-compose.selfhost.yml` 設 DB_TYPE=postgresql，但 `storage.py:196` 只有 MariaDB 分支，其餘使用 SQLite。schema_postgres.sql 與 pgvector 查詢不能代表實際已有 PostgreSQL connection adapter。

同一 compose 還把 LLM_BASE_URL 強制指向 Ollama，與目前 Groq provider 衝突。Dockerfile 沒安裝 requirements-exam-ai、models；CPU bridge 又硬編碼 Windows Scripts/python.exe。現有 Docker 路徑不能宣稱可直接使用目前架構。

建議：學校報告先支持一個明確的 Windows＋MariaDB＋Groq 配置。其他部署設為未支援，或補齊 adapter、Linux CPU worker 路徑與模型掛載后再開放。

### A37｜P1｜Docker build context 沒有排除本機秘密與大型檔案【已確認】

沒有 `.dockerignore`，Dockerfile 使用 COPY . .。build context 可能包含 `.env`、instance、Git、venv 及模型；Git ignore 不等同 Docker ignore。

建議：加入明確的 .dockerignore，秘密執行時注入、模型外部掛載。未檢查已建映像，不能斷言已泄漏。

### A38｜P2｜schema 初始化不是版本迁移，且啟動時依賴 CREATE 權限【已確認】

app.create_app 每次啟動執行 extension CREATE TABLE IF NOT EXISTS；此方式不会更新既有表的欄位或約束。啟動檢查僅覆蓋少數表，无法确认所有 features schema。

建議：以 migration version 記錄變更，開發者明確執行；正常 app 帳號只保留必要資料權限。啟動檢查給出可讀提示，不自動重建同學的表。

### A39｜P2｜測試隔離與支援矩陣不足【靜態確認，未執行】

tests/test_app.py 匯入 app.create_app，但 app.py 模組最下方會立即 create_app()。在測試開始之前可能先接目前真實 MariaDB 並執行 extension DDL。之後 test_config 又可能被 app.py 的 os.getenv 覆寫 AI 設定。

建議：app factory 與執行入口分離；test_config 最後套用，測試全程禁止對真實 DB/API 操作。已存在的測試主要不等同 MariaDB 並行及新 CPU／Groq 工作流完整覆蓋。

## 已做得比較完整、應保留的設計

- 共用登入與資料所有權檢查：login_required、owned／_subject／_owned_quiz，查詢多數明確限制 user／科目。
- POST CSRF、防快取、基本安全標頭；登出 POST。密碼使用 Werkzeug 雜湊，驗證碼 HMAC 與有效期／嘗試限制。
- 表名由 CATALOG 白名單控制、數值與日期基本驗證、SQL 使用參數，不直接信任 request 當 SQL 片段。
- 考卷題目 snapshot；未交卷從模板資料移除答案與解析；已被作答的手動題禁止修改。
- 固定 bank_random 不以 AI 補題，錯題複習保留原題；概念来源与固定题来源有明确区分。
- 章節／概念弱項由程式計算，樣本不足明確標示；不讓 LLM 任意決定使用者掌握度。
- 草稿与正式題分開、CPU 模型明確使用 CPUExecutionProvider、模型評分未校準有提示。
- BODY 分層為 HTTP／service／SQL，前端採 textContent；使用量紀錄只寫數字。这些分层值得其他模組借鉴。

上述是已存在的保護，並不代表已完成安全審計或動態驗證。登入限流在 MariaDB 並行下的 read-then-write 也應於後續驗證。

## 建議修正順序與驗收方式

1. 基礎安全與資源：A01、A02、A37。驗收連線數可回收、正常提交不含秘密、build context 排除秘密；不擅自操作共享部署或歷史。
2. 固定題库闭环：A05、A10、A14、A15、A23、A24。你操作匯入錯誤／重送／刷新／交卷與錯題複習。
3. 概念學習闭环：A03、A04、A16–A20、A26、A34。確定每個正式題都能追溯概念，弱項真正影响安排。
4. AI 任務與成本：A06–A08、A21、A28、A35。验证限额、失败恢复、取消、重复刷新不计费、token usage 可追溯。
5. 清理重複入口与文档，選定一套能展示的部署；其他標成未實作／未支援。

使用者先前要求測試由自己執行，因此本次沒有跑測試，也沒有更換金鑰、修改正式資料、清理 Git 历史或變更 BODY。
