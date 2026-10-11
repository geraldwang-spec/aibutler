# TYE 模組

此資料夾由 TYE 負責維護，避免與其他組員的功能互相衝突。

## exam_module.py

負責：

- 模擬考設定
- 依科目 / 章節 / 題型抽題
- 固定題目 Snapshot
- 模擬考作答與自動批閱
- 成績紀錄
- 錯題累計與錯題複習
- 每章最近 20 次作答的弱項分析
- 使用者資料隔離

路由不在本檔案匯入時自動建立，而是由 `app.py`：

```python
from TYE import register_tye_exam
register_tye_exam(app)
```

統一完成註冊。

## MariaDB 遷移注意

目前整個專案的 `storage.py` 仍使用 SQLite，因此尚未真正切換 MariaDB；但本模組的新邏輯刻意避免 `RANDOM()` 與 `ON CONFLICT` 等 SQLite 特有語法。參數 placeholder 仍沿用目前專案的 `?`，正式更換 DB driver 時應由共用資料存取層統一處理。
