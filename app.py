# -*- coding: utf-8 -*-

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

from smartlife import create_app as create_base_app
from body.body_route import body
from TYE import register_tye_exam
from personal_ai import register_personal_ai


def create_app(test_config=None):
    """組裝 AI Butler。

    smartlife.py 保留共用/其他組員功能；TYE/ 由筠翔維護的模擬考模組在此註冊。
    後續其他組員也可採同樣方式由自己的資料夾提供 register_* 函式。
    """
    flask_app = create_base_app(test_config)

    # 模組保持獨立：只在組裝入口註冊，不修改 body/ 與 TYE/ 內部內容。
    flask_app.register_blueprint(body)
    register_tye_exam(flask_app)
    flask_app.config.update(
        APP_MODE=os.getenv("APP_MODE", flask_app.config.get("APP_MODE", "dev")),
        GROQ_API_KEY=os.getenv("GROQ_API_KEY", flask_app.config.get("GROQ_API_KEY", "")),
        LLM_PROVIDER=os.getenv("LLM_PROVIDER", flask_app.config.get("LLM_PROVIDER", "ollama")),
        LLM_BASE_URL=os.getenv("LLM_BASE_URL", flask_app.config.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")),
        LLM_API_KEY=os.getenv("LLM_API_KEY", flask_app.config.get("LLM_API_KEY", "")),
        LLM_MODEL=os.getenv("LLM_MODEL", flask_app.config.get("LLM_MODEL", "qwen3.5:4b")),
        CLASSIFIER_PROVIDER=os.getenv("CLASSIFIER_PROVIDER", flask_app.config.get("CLASSIFIER_PROVIDER", "ollama")),
        CLASSIFIER_BASE_URL=os.getenv("CLASSIFIER_BASE_URL", flask_app.config.get("CLASSIFIER_BASE_URL", "http://127.0.0.1:11434/v1")),
        CLASSIFIER_API_KEY=os.getenv("CLASSIFIER_API_KEY", flask_app.config.get("CLASSIFIER_API_KEY", "")),
        CLASSIFIER_MODEL=os.getenv("CLASSIFIER_MODEL", flask_app.config.get("CLASSIFIER_MODEL", "qwen3.5:4b")),
        PARSER_PROVIDER=os.getenv("PARSER_PROVIDER", flask_app.config.get("PARSER_PROVIDER", "ollama")),
        PARSER_BASE_URL=os.getenv("PARSER_BASE_URL", flask_app.config.get("PARSER_BASE_URL", "http://127.0.0.1:11434/v1")),
        PARSER_API_KEY=os.getenv("PARSER_API_KEY", flask_app.config.get("PARSER_API_KEY", "")),
        PARSER_MODEL=os.getenv("PARSER_MODEL", flask_app.config.get("PARSER_MODEL", "qwen3.5:4b")),
    )
    register_personal_ai(flask_app)
    if str(flask_app.config.get('APP_MODE','dev')).lower() == 'dev' and flask_app.config.get('DB_TYPE') == 'sqlite':
        from dev_seed import ensure_dev_seed
        with flask_app.app_context():
            ensure_dev_seed()
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
    print("Body 模組：已註冊")
    print("TYE 模組：已註冊")
    print("Personal AI 模組：已註冊")
    print("APP_MODE：", app.config.get("APP_MODE"))
    print("LLM_PROVIDER：", app.config.get("LLM_PROVIDER"))
    print("LLM_MODEL：", app.config.get("LLM_MODEL") or "未設定")
    print("CLASSIFIER_PROVIDER：", app.config.get("CLASSIFIER_PROVIDER"))
    print("CLASSIFIER_MODEL：", app.config.get("CLASSIFIER_MODEL") or "未設定")
    print("DB_TYPE：", app.config.get("DB_TYPE"))
    if app.config.get('APP_MODE') == 'dev':
        print("DEV 測試帳號：admin123 / 12345678")
    if app.config.get("DB_TYPE") == "mariadb":
        print("DB_HOST：", app.config.get("DB_HOST"))
        print("DB_PORT：", app.config.get("DB_PORT"))
        print("DB_NAME：", app.config.get("DB_NAME"))
        print("DB_USER：", app.config.get("DB_USER"))
    print("=" * 50)


if __name__ == "__main__":
    check_environment()
    app.run(host="127.0.0.1", port=5000, debug=True)
