# 考試智伴 SmartLife 本機使用說明

## 啟動

需要 Python 3.11 以上。於專案資料夾執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

已有 uv 時亦可使用 `uv run --python 3.12 --with-requirements requirements.txt python app.py`；首次執行可能下載 Python 與依賴。
瀏覽器開啟 http://127.0.0.1:5000 ，由登入頁進入註冊。沒有預設帳號，也沒有略過驗證的正式入口。

## 寄信設定

本機 `.env` 已建立，寄信相關欄位留空並註明；交給組員時提供 `.env.example`，由組員複製為 `.env`。

| 欄位 | 填寫內容 |
| --- | --- |
| SMTP_HOST | SMTP 主機名稱 |
| SMTP_PORT | 寄信服務提供的連接埠 |
| SMTP_USERNAME | SMTP 登入帳號 |
| SMTP_PASSWORD | SMTP 密碼、應用程式密碼或 SMTP 專用金鑰 |
| SMTP_FROM_EMAIL | 服務允許使用的寄件信箱 |
| SMTP_FROM_NAME | 寄件者名稱，預設考試智伴 |
| SMTP_SECURITY | starttls 或 ssl，依服務商設定 |

常見組合為 starttls / 587 或 ssl / 465，請以服務商文件為準。一般 HTTP API 金鑰不一定能當作 SMTP 密碼。
若密碼含 `#` 或空白，請使用引號包住整個值。設定後重新啟動程式。
設定留空或寄送失敗會在註冊頁顯示紅字，不會假裝已寄送，也不會把驗證碼顯示在網頁或伺服器日誌中。
SMTP 伺服器接受信件不代表已進入收件匣，請一併檢查垃圾郵件。

註冊需填帳號、密碼、mail、六位數驗證碼。帳號 6–80 字元、密碼 8–128 字元，支援可見 ASCII 英文、數字及符號，不含空白，不要求三種字元都包含。
驗證碼自成功寄送起有效 30 分鐘；60 秒內不可重寄。重寄會替換舊碼；錯誤 5 次即失效；每個信箱每小時最多 5 次、同一 IP 每小時最多 10 次申請。註冊及登入也有嘗試次數限制。

## 資料儲存

- `instance/smartlife.db`：SQLite 資料庫，第一次啟動自動建立；重啟不會清除。
- `instance/session.key`：本機簽章金鑰，SECRET_KEY 留空時自動建立；刪除或更換會使登入與現有驗證碼失效。
- `instance/imports/`：原始 CSV / XLSX 題庫檔案，採隨機檔名，不提供公開下載路徑。
- `.env` 與 `instance/` 都已排除 Git，避免信箱金鑰與個人資料被提交。
- 備份時先停止程式，再備份整個 `instance/`。尚未提供資料庫遷移系統；後續接外部資料庫時需另做遷移。

## 目前可操作功能

1. 註冊驗證、帳號密碼登入、登出；首次登入引導個人資料設定。
2. 個人資料、運動目標與體重／體脂紀錄。
3. 科目、章節、題庫的新增／編輯／刪除，含單選、多選、是非、填空及解析。
4. CSV／XLSX 題庫上傳、逐題預覽、整批確認後入庫。先下載頁面提供的範本；每批最多 500 題、5 MB；CSV 使用 UTF-8。
5. 指定科目抽题、模考、錯題複習、交卷評分、成績與解析。填空以去除前後空白後精確比對；尚無計時交卷或作答草稿自動保存。
6. 錯題簿累計錯誤次數，錯題複習答對後標記已克服；章節正確率與簡單規則式加強方向。
7. 手動重點筆記、熟練度、考試日期與準備時間、讀書／運動計畫。逾期計畫在操作或查看總覽時更新為 missed。
8. 個人動作庫、訓練日、逐組紀錄、手動運動課表及項目。訓練分鐘由起迄時間計算，訓練量由重量×次數計算。
9. 對話主題與提問文字保存，目前不產生 AI 回答。
10. 總覽依實際作答與訓練產生每日結算。

所有一般資料查詢、編輯、刪除與關聯選擇都檢查使用者歸屬。題目被考試引用後不可修改答案；每次開考保留快照，作答頁不輸出正確答案與解析，交卷才顯示。
有關聯資料的刪除會被阻擋，以避免破壞歷史。

## 文件對應與暫緩項目

已依《SmartLife AI 資料表明細.docx》建立 29 張領域表，另加 `registration_codes`、`rate_limits`。
新增註冊專用驗證表，因為完成註冊前尚無 user_id；依本次要求使用 30 分鐘，覆蓋文件中的註冊 24 小時描述。
SQLite 的 ENUM / JSON 先以 TEXT、BOOLEAN 以 INTEGER 儲存；欄位驗證由後端處理。向量欄位先以空 BLOB 預留。
`body_metrics` 增加 id 方便編輯，仍以 (user_id, record_date) 保持一天一筆；`quiz_answers` 增加 question_snapshot 保存歷史版本。

第二階段的教材解析、向量檢索、RAG、AI 出題與建議僅預留表及入口，沒有模型呼叫。
忘記密碼、共用系統題庫管理、自動讀書／運動排程、課表一鍵套用、推播通知與月曆視圖尚未實作。考試範圍排除日期等進階欄位先保留預設值。
本機開發使用 HTTP；正式部署需 HTTPS 並設定 COOKIE_SECURE=true、穩定的 SECRET_KEY，以及正式 WSGI 伺服器。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

測試使用獨立暫存資料庫與模擬 SMTP，不寄真實信件。另有 `tests/serve_ui.py` 和 `tests/ui_smoke.cjs` 供 Playwright 瀏覽器測試，使用獨立測試伺服器與帳號；不會寫入正式 db。
