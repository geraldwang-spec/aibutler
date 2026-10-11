# -*- coding: utf-8 -*-
"""財務模組的建表與 SQL。所有查詢都帶 user_id，資料歸屬由後端檢查。

沿用 storage.db() 的 ? 參數寫法；MariaDB 由 storage 自動轉成 %s。
資料表沿用 David 原版的 transactions 欄位，既有資料可直接使用。
"""
from storage import backend, db

TABLE = 'transactions'

_DDL = {
    'sqlite': """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type VARCHAR(10) NOT NULL,
            record_date DATE NOT NULL,
            category VARCHAR(20) NOT NULL,
            title VARCHAR(100) NOT NULL,
            amount INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    'mariadb': """
        CREATE TABLE IF NOT EXISTS transactions (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            type VARCHAR(10) NOT NULL,
            record_date DATE NOT NULL,
            category VARCHAR(20) NOT NULL,
            title VARCHAR(100) NOT NULL,
            amount INT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX ix_transactions_user_date (user_id, record_date),
            CONSTRAINT fk_transactions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
}
_SQLITE_INDEX = 'CREATE INDEX IF NOT EXISTS ix_transactions_user_date ON transactions(user_id, record_date)'


def ddl(kind=None):
    """建表 SQL（給管理員手動執行時顯示用）。"""
    return _DDL.get(kind or backend(), _DDL['mariadb']).strip() + ';'


def create_table():
    """在目前的連線建立 transactions 表；成功回 True，失敗（例如沒有 CREATE 權限）回 False。"""
    kind = backend()
    if kind not in _DDL:
        return False
    connection = db()
    try:
        connection.rollback()
        connection.execute(_DDL[kind])
        if kind == 'sqlite':
            connection.execute(_SQLITE_INDEX)
        connection.commit()
        return True
    except Exception as exc:
        connection.rollback()
        from flask import current_app
        current_app.logger.warning('[financial] 無法建立 transactions 資料表：%s', exc)
        return False


def is_missing_table(exc):
    """判斷是否為「transactions 表不存在」：SQLite 'no such table'、MariaDB 錯誤碼 1146。"""
    text = str(exc)
    return TABLE in text and ('no such table' in text or '1146' in text or "doesn't exist" in text)


def ensure_schema(app):
    """啟動時建立 transactions 表；唯讀備援或連不上資料庫時只記錄警告，不阻擋網站啟動。
    建表失敗時，進入財務頁面會再試一次，仍失敗就顯示說明頁（routes.py 的 missing_table）。"""
    if app.config.get('DB_READ_ONLY') or backend(app) not in _DDL:
        return
    with app.app_context():
        try:
            create_table()
        except Exception as exc:  # 例如啟動時資料庫連不上
            app.logger.warning('[financial] 無法建立 transactions 資料表：%s', exc)


def insert(user_id, tx_type, record_date, category, title, amount):
    connection = db()
    connection.execute(
        'INSERT INTO transactions (user_id, type, record_date, category, title, amount) VALUES (?,?,?,?,?,?)',
        (user_id, tx_type, record_date, category, title, amount))
    connection.commit()


def delete(user_id, record_id):
    """只刪自己的紀錄；回傳是否真的刪到（別人的 id 一律當作不存在）。"""
    connection = db()
    cursor = connection.execute('DELETE FROM transactions WHERE id=? AND user_id=?', (record_id, user_id))
    connection.commit()
    return cursor.rowcount > 0


def rows_between(user_id, start, end):
    """取得日期區間內（含頭尾）的金額資料，給 service 計算統計。日期為 ISO 字串。"""
    return db().execute(
        'SELECT type, record_date, category, amount FROM transactions '
        'WHERE user_id=? AND record_date>=? AND record_date<=?',
        (user_id, start, end)).fetchall()


def recent(user_id, tx_type=None, limit=50):
    sql = 'SELECT id, type, record_date, category, title, amount FROM transactions WHERE user_id=?'
    params = [user_id]
    if tx_type:
        sql += ' AND type=?'
        params.append(tx_type)
    sql += ' ORDER BY record_date DESC, id DESC LIMIT ?'
    params.append(int(limit))
    return db().execute(sql, tuple(params)).fetchall()
