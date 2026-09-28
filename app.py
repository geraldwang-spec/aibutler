# -*- coding: utf-8 -*-

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

from smartlife import create_app as create_base_app
from TYE import register_tye_exam


def create_app(test_config=None):
    """組裝 AI Butler。

    smartlife.py 保留共用/其他組員功能；TYE/ 由筠翔維護的模擬考模組在此註冊。
    後續其他組員也可採同樣方式由自己的資料夾提供 register_* 函式。
    """
    flask_app = create_base_app(test_config)
    register_tye_exam(flask_app)
    return flask_app


app = create_app()

app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or app.config.get("SECRET_KEY"),
    SMTP_HOST=os.getenv("SMTP_HOST", app.config.get("SMTP_HOST", "")),
    SMTP_PORT=os.getenv("SMTP_PORT", app.config.get("SMTP_PORT", "587")),
    SMTP_USERNAME=os.getenv("SMTP_USERNAME", app.config.get("SMTP_USERNAME", "")),
    SMTP_PASSWORD=os.getenv("SMTP_PASSWORD", app.config.get("SMTP_PASSWORD", "")),
    SMTP_FROM_EMAIL=os.getenv("SMTP_FROM_EMAIL", app.config.get("SMTP_FROM_EMAIL", "")),
    SMTP_FROM_NAME=os.getenv("SMTP_FROM_NAME", app.config.get("SMTP_FROM_NAME", "考試智伴")),
    SMTP_SECURITY=os.getenv("SMTP_SECURITY", app.config.get("SMTP_SECURITY", "starttls")).lower(),
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)


def check_environment():
    print("=" * 50)
    print("環境設定檢查")
    print("=" * 50)
    print(f".env 路徑：{ENV_FILE}")
    print(f".env 是否存在：{ENV_FILE.exists()}")
    print("SECRET_KEY：", "已載入" if app.config.get("SECRET_KEY") else "未設定")
    print("SMTP_HOST：", app.config.get("SMTP_HOST") or "未設定")
    print("SMTP_PORT：", app.config.get("SMTP_PORT") or "未設定")
    print("SMTP_USERNAME：", app.config.get("SMTP_USERNAME") or "未設定")
    print("SMTP_PASSWORD：", "已載入" if app.config.get("SMTP_PASSWORD") else "未設定")
    print("SMTP_FROM_EMAIL：", app.config.get("SMTP_FROM_EMAIL") or "未設定")
    print("SMTP_FROM_NAME：", app.config.get("SMTP_FROM_NAME") or "未設定")
    print("SMTP_SECURITY：", app.config.get("SMTP_SECURITY") or "未設定")
    print("COOKIE_SECURE：", app.config.get("SESSION_COOKIE_SECURE"))
    print("TYE 模組：已註冊")
    print("=" * 50)


if __name__ == "__main__":
    check_environment()
    app.run(host="127.0.0.1", port=5000, debug=True)
