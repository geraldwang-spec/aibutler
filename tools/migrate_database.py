"""Explicit, idempotent extension migration. Never runs on app import."""
import os
from pathlib import Path
from dotenv import load_dotenv
import pymysql
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import _split_sql_script

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    load_dotenv(ROOT/'.env')
    con=pymysql.connect(host=os.getenv('DB_HOST'),port=int(os.getenv('DB_PORT','3306')),user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),database=os.getenv('DB_NAME'),charset='utf8mb4',autocommit=False)
    try:
        with con.cursor() as cur:
            cur.execute('CREATE TABLE IF NOT EXISTS project_migrations (version VARCHAR(80) PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            for sql in _split_sql_script((ROOT/'schema_tye_personal_mariadb.sql').read_text(encoding='utf-8')):
                cur.execute(sql)
            cur.execute("INSERT IGNORE INTO project_migrations(version) VALUES ('2026-10-05-completeness')")
        con.commit(); print('擴充 schema 已更新並記錄版本；未重建 BODY 或刪除資料。')
    finally:
        con.close()
