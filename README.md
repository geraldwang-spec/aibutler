# 考試智伴 SmartLife

Flask + SQLite 的考試與健康管理專題。已提供信箱驗證註冊、登入、題庫管理、模考評分、學習與運動紀錄；AI / RAG 尚未串接。

請先閱讀 [本機啟動與寄信設定](SETUP.md)，在 `.env` 填入 SMTP 信箱與金鑰後重啟程式。
資料會保存於 `instance/smartlife.db`，不會提交到 Git。

檔案結構
aibutler/
├── app.py          # create_app()：只負責註冊各 blueprint
├── config.py		 # 讀取env設定都集中在這裡		
├── modules/             # 共用工具，不含任何頁面
│   ├── utils.py         # 工具函式。寫一個小函式可在其他成使用ex: def add(a, b), 儘可能是以python的原生的函式為主
│   ├── mailer.py        # 寄信
│   ├── file_upload.py   # 上傳檔案儲存
│   └── account_guard.py # 目的是為了進到不同的頁面時還可以確認這個使用者是不是有正常登入
├── account/             # 註冊、登入、驗證信、個人資料
│   └── account_route.py # bluepoint 進入位置
├── question_bank/       # ① 題庫、科目、章節、匯入
│   └── question_bank_route.py # bluepoint 進入位置
├── exam/                # ② 模擬考、錯題、弱項分析
│   └── exam_route.py    # bluepoint 進入位置
├── body/                # ③ 體重、訓練、逐組紀錄
│   └── body_route.py    # bluepoint 進入位置
├── planner/             # ④ 讀書/運動計畫、課表
│   └── planner_route.py # bluepoint 進入位置
├── notes/               # ⑤ 問答記事、摘要筆記
│   └── notes_route.py   # bluepoint 進入位置
├── dashboard/           # 總覽、每日統計
│   └── dashboard_route.py  # bluepoint 進入位置
