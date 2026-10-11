# -*- coding: utf-8 -*-
"""財務小幫手（financial）模組：收支紀錄、今日／本週／本月／今年統計、支出 AI 分類。

由 app.py 呼叫 register_financial(app) 註冊，與其他組員模組相同的組裝方式。
  financial/routes.py       HTTP 路由（Blueprint 'financial'，網址前綴 /financial）
  financial/service.py      表單驗證與統計（純 Python，數字只在這裡計算）
  financial/sql_process.py  建表與所有 SQL（相容 SQLite / MariaDB）
  financial/classifier.py   支出名稱 → 食衣住行育樂（呼叫共用的 CLASSIFIER LLM）
頁面：templates/financial/，樣式與腳本：static/financial/
"""
from .routes import financial
from .sql_process import ensure_schema


def register_financial(app):
    app.register_blueprint(financial)
    # 只在啟動時建一次表（David 原版在每個 request 前都執行 CREATE TABLE）
    ensure_schema(app)
