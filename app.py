# -*- coding: utf-8 -*-

import os
from pathlib import Path

from dotenv import load_dotenv

# =========================================================
# 1. 載入 .env
# =========================================================

# app.py 所在的資料夾
BASE_DIR = Path(__file__).resolve().parent

# .env 路徑
ENV_FILE = BASE_DIR / ".env"

# 明確讀取目前專案資料夾內的 .env
load_dotenv(dotenv_path=ENV_FILE)


# =========================================================
# 2. 載入 Flask App
#    注意：一定要在 load_dotenv() 後面
# =========================================================

from smartlife import create_app

app = create_app()


# =========================================================
# 3. 將 .env 設定寫入 Flask config
# =========================================================

app.config.update(

    # Flask Secret Key
    SECRET_KEY=os.getenv("SECRET_KEY"),

    # SMTP
    SMTP_HOST=os.getenv("SMTP_HOST"),
    SMTP_PORT=os.getenv("SMTP_PORT", "587"),
    SMTP_USERNAME=os.getenv("SMTP_USERNAME"),
    SMTP_PASSWORD=os.getenv("SMTP_PASSWORD"),
    SMTP_FROM_EMAIL=os.getenv("SMTP_FROM_EMAIL"),
    SMTP_FROM_NAME=os.getenv("SMTP_FROM_NAME", "考試智伴"),
    SMTP_SECURITY=os.getenv("SMTP_SECURITY", "starttls").lower(),

    # Cookie
    SESSION_COOKIE_SECURE=
        os.getenv("COOKIE_SECURE", "false").lower() == "true",
)


# =========================================================
# 4. 啟動時檢查設定
#    不會顯示 SMTP 密碼內容
# =========================================================

def check_environment():
    print("=" * 50)
    print("環境設定檢查")
    print("=" * 50)

    print(f".env 路徑：{ENV_FILE}")
    print(f".env 是否存在：{ENV_FILE.exists()}")

    print()
    print("SECRET_KEY：",
          "已載入" if app.config.get("SECRET_KEY") else "未設定")

    print("SMTP_HOST：",
          app.config.get("SMTP_HOST") or "未設定")

    print("SMTP_PORT：",
          app.config.get("SMTP_PORT") or "未設定")

    print("SMTP_USERNAME：",
          app.config.get("SMTP_USERNAME") or "未設定")

    print("SMTP_PASSWORD：",
          "已載入" if app.config.get("SMTP_PASSWORD") else "未設定")

    print("SMTP_FROM_EMAIL：",
          app.config.get("SMTP_FROM_EMAIL") or "未設定")

    print("SMTP_FROM_NAME：",
          app.config.get("SMTP_FROM_NAME") or "未設定")

    print("SMTP_SECURITY：",
          app.config.get("SMTP_SECURITY") or "未設定")

    print("COOKIE_SECURE：",
          app.config.get("SESSION_COOKIE_SECURE"))

    print("=" * 50)


# =========================================================
# 5. 本機執行
# =========================================================

if __name__ == "__main__":

    check_environment()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )