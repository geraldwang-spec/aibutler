# 完整性修正與資料庫復原

更新：2026-10-05。此文件描述目前實作；原 PROJECT_COMPLETENESS_AUDIT.md 保留修正前的證據。依使用者要求，沒有執行功能測試、模型推論、Docker 啟動或故障切換演練。

## 已落實的修正

- 連線 teardown 與 schema 初始化分離，離開請求 rollback／close；factory 匯入不再立即連真實 DB。
- 匯入確認、草稿核准與交卷在交易中鎖狀態列；交卷與規劃更新同一提交，已完成考卷可修復規劃結果。
- 固定題與 AI 題共用格式驗證；多選答案正規化、填空支援明確的 `|` 替代答案。
- 匯入可逐題編輯、移除與取消；草稿可指定章節、編輯、核准、退回，核准建立概念關聯。
- TXT 支援 UTF-8／BOM UTF-16／CP950，DOCX 擷取表格，掃描 PDF 使用 CPU OCR；PDF 最多 100 頁、OCR 最多 20 頁。所有上傳 5 MB。概念匯入最多 20 題，固定題結構化匯入最多 500 題。
- LLM 匯入按完整題目區塊處理，不再靜默截斷整份文件；微課程分步生成，教材或來源题不足時拒絕生成。
- AI 工作改為持久化單 worker 佇列，可查狀態與取消；一般對話接上 Groq，錯題 Tutor GET 只讀歷史。
- 單次 Groq timeout 60 秒、輸出上限 800 tokens；每工作 10 分鐘／40 次／32,000 tokens，每帳號滾動 24 小時 100 次／100,000 tokens，呼叫前檢查額度。輸入預估採 UTF-8 bytes 保守上界，實際記錄 API usage；這不是 Groq TPM 配額預約。
- 微課程客觀答案比對不再使用包含判斷，答錯可重答；完成需互動題全對，概念掌握另依測驗評估。
- 弱項優先順序修正，兩年規劃不再截成 366 筆，閱讀獨立紀錄；概念可改名、合併、調整來源與技能，保留操作紀錄；固定題可補標概念。
- 動態模型題不再標成已人工驗證；錯題教學使用考卷 snapshot。
- 作答在目前瀏覽器分頁 sessionStorage 暫存；沒有跨裝置同步。
- E5 檢索改重疊窗口取最大分數，NLI 教材分段初篩，移除重複排序。分數尚未經學校題庫校準，題幹本身仍有長度界限。
- 主頁 GET 不再重算／寫統計，側欄收合進階功能；教材占位入口轉向真正知識庫。
- 安裝入口預設只裝 CPU E5／NLI／OCR，保留 Groq 設定，不下載本地 LLM。舊 setup_real_models.py 只有明確 `--legacy-local` 才會使用舊版設定。
- .dockerignore 排除秘密、模型、venv；Docker 使用 MariaDB＋Groq、Linux CPU 環境與單程序四 threads。CPU 權重由 models 掛載。
- schema 擴充由 tools/migrate_database.py 明確執行並記錄版本；一般啟動不自動迁移。BODY 業務模組沒有改動，共用連線與導覽有調整。

## 備援方式

主庫仍為原 MariaDB。SQLite 是讀取快照，MariaDB 是可恢復寫入的目的庫；不使用未支援的 PostgreSQL 當備援。

已執行備份：`instance/backups/snapshot-20261005-172152.sqlite`，49 個表、601 筆；旁邊 JSON 保存原始 MariaDB DDL、各表筆數及 SHA-256。備份讀取主庫，沒有修改主庫業務資料。擴充 migration 已執行。

`DB_STANDBY_ENABLED=true` 時，主庫初次連線失敗，該請求使用 `instance/backups/standby.sqlite` 唯讀快照；先驗證 SHA-256。页面顯示快照時間；拒絕一般 POST，允許登入／登出。已連線交易中途斷線不自動重播寫入；不能保證主庫所有故障模式都無縫切換。BODY 尚未演練唯讀運作。

啟動應用後每小時建立新快照；程式沒在跑時不會備份。失敗保留上一份，主庫恢復後新請求會回主庫。快照不接收寫入，所以沒有自動回灌／分歧合併。

手動備份：

```powershell
python tools/database_backup.py
```

資料損失上界是最後成功備份至故障期間的變更；預設目標約一小時，備份連續失敗時會更久。資料庫快照不含上傳原檔、金鑰與帳號設定；另保管 `.env` 與 `instance`，不要提交 Git。現在快照在同一台電腦，不能防整台電腦或硬碟故障，需另複製到外部磁碟／第二台機器。

## 可寫備庫復原

需要時先為獨立備用服務設定 `STANDBY_ROOT_PASSWORD` 與 `STANDBY_DB_PASSWORD`（自己的秘密，不寫進程式），再執行：

```powershell
docker compose -f docker-compose.standby.yml up -d
```

此服務在本機 3307，建立空的 `aibutler_restore`。復原工具用目前 shell 的 `DB_USER`、`DB_PASSWORD`，請設為備庫帳號及其密碼；dotenv 不覆蓋已有環境變數。保留主庫 DB_NAME，工具會拒絕同名目的庫：

```powershell
$env:DB_USER = 'aibutler_restore'
# DB_PASSWORD 在目前 shell 設為備庫密碼，勿貼到分享文件。
python tools/database_backup.py --restore instance/backups/snapshot-20261005-172152.sqlite --target-db aibutler_restore --host 127.0.0.1 --port 3307
```

工具拒絕非空目的庫，檢查 SHA-256 與每表筆數。MariaDB DDL 不具完整 rollback；失敗時可能留下部分表，勿假定目的庫仍為空。復原成功後確認資料，再手動將應用 `.env` DB_HOST／PORT／NAME／USER／PASSWORD 改為備庫并重啟。不要啟動兩個寫入实例，也不要在主庫恢復時未經確認就切回。Docker 備庫、資料復原及切換沒有執行演練。

## 尚有實作界限

- 工作重啟會標示中斷，取消於下一次 API 呼叫前生效，無法撤回已送出的請求。尚無付費生成中途成果自動續作；大批次請分批，失敗不自動重試計費。
- 同一匯入批次重送有交易鎖；跨批次相同章節、題幹、題型、答案與選項的匯入題會跳過。文字空白或選項文字變體仍視為不同內容，尚無語意去重保證。
- 考卷／草稿歷史保留，沒有自動封存刪除；不會自動清除仍被歷史引用的題目。失敗新上傳會清檔，但舊孤立檔案尚未掃描清除。
- 統計從 GET 移到寫入後更新，仍重算歷史，尚非增量摘要；BODY 相容性由同學共同驗收。
- 敏感檔案已從目前 Git 追蹤排除，舊提交仍可能含原秘密；金鑰輪替與 Git 歷史清理尚未操作。
- 本次 migration 記錄的是明確擴充版本，沒有將所有歷史 schema 改成完整的逐版欄位迁移框架。
- 不宣稱 39 項全部經動態驗收，也不宣稱可零資料損失。建議先驗收固定題匯入／修正／交卷，再驗收背景 AI／課程，再演練備庫；不執行 BODY 變更。
