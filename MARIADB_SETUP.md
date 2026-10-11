# AI Butler - MariaDB / Tailscale 開發模式

## 1. 安裝依賴

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` 已包含 `PyMySQL`。

## 2. `.env`

專案以以下變數切換資料庫：

```env
DB_TYPE=mariadb
DB_HOST=100.68.147.95
DB_PORT=3306
DB_USER=llmclass
DB_PASSWORD=<你的 MariaDB 密碼>
DB_NAME=teamdb
DB_CHARSET=utf8mb4
```

正式提交 Git 時不要提交 `.env`；只提交 `.env.example`。

## 3. 建立 Table

方法 A：直接啟動專案。`create_app()` 會執行 `schema_mariadb.sql` 的 `CREATE TABLE IF NOT EXISTS`。

```powershell
python app.py
```

方法 B：只初始化資料庫。

```powershell
python init_db.py
```

方法 C：HeidiSQL 開啟 `schema_mariadb.sql`，連線到 `teamdb` 後執行整份 SQL。

## 4. 測試題

`TYE/ITS_Databases_sample.csv` 可以從網站既有題庫匯入功能匯入。

也可以在已至少有一個 users 帳號後，於 HeidiSQL 執行：

```text
TYE/seed_its_database_sample.sql
```

它會建立：

- 科目：ITS Databases
- 章節：預存程序
- 題型：單選
- 1 題測試題

## 5. SQLite 回退

如果 MariaDB 暫時無法連線，把 `.env` 改成：

```env
DB_TYPE=sqlite
```

就會回到 `instance/smartlife.db`，方便離線開發與單元測試。
