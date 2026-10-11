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

    # MariaDB 由同學既有 teamdb 作為唯一正式資料庫。
    # BODY 的既有 schema 不在這裡重建；此處只補 TYE / Personal AI 自己新增的資料表。
    # 注意：舊專案 .env 可能有 AUTO_INIT_DB=false，這個旗標只控制「完整 schema」初始化，
    # 不應阻止整合模組建立自己的 extension tables。
    if str(flask_app.config.get("DB_TYPE", "")).lower() == "mariadb" and not flask_app.config.get("TESTING") and os.getenv("AUTO_MIGRATE", "false").lower() == "true":
        from storage import _connect_mariadb, _split_sql_script

        extension_schema = BASE_DIR / "schema_tye_personal_mariadb.sql"
        connection = _connect_mariadb(flask_app)
        try:
            for statement in _split_sql_script(extension_schema.read_text(encoding="utf-8")):
                connection.execute(statement)
            connection.commit()

            # 啟動時立即驗證最關鍵的擴充表，避免到匯入題庫時才出現 1146。
            required_tables = (
                "concepts",
                "source_question_items",
                "question_concepts",
                "ai_question_drafts",
                "question_metadata",
            )
            missing = []
            for table_name in required_tables:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.tables "
                    "WHERE table_schema=? AND table_name=?",
                    (flask_app.config["DB_NAME"], table_name),
                ).fetchone()
                if not row or int(row["n"]) == 0:
                    missing.append(table_name)
            if missing:
                raise RuntimeError("MariaDB 擴充資料表建立失敗：" + ", ".join(missing))
            print("TYE / Personal AI MariaDB 擴充表：已確認")
        except Exception as exc:
            connection.rollback()
            raise RuntimeError(
                "無法建立 TYE / Personal AI 的 MariaDB 擴充資料表。"
                "請確認 DB_USER 對 teamdb 具有 CREATE/ALTER 權限。原始錯誤：" + str(exc)
            ) from exc
        finally:
            connection.close()

    # 模組保持獨立：只在組裝入口註冊，不修改 body/ 與 TYE/ 內部內容。
    flask_app.register_blueprint(body)
    register_tye_exam(flask_app)
    register_personal_ai(flask_app)
    from workspace_ui import register_workspace_ui
    register_workspace_ui(flask_app)
    if not flask_app.config.get('TESTING') and not flask_app.config.get('DB_READ_ONLY') and str(flask_app.config.get('APP_MODE','dev')).lower() == 'dev' and flask_app.config.get('DB_TYPE') == 'sqlite':
        from dev_seed import ensure_dev_seed
        with flask_app.app_context():
            ensure_dev_seed()
    return flask_app


def check_environment(app):
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
    print("GROQ_API_KEY：", "已設定（所有文字 AI 共用）" if app.config.get("GROQ_API_KEY") else "未設定 ← 請在 .env 最上方貼入 KEY")
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
<<<<<<< HEAD

    check_environment()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
    
import os
from flask import Flask, render_template, request, jsonify, session

# 如果要串真實 Gemini 或 OpenAI，可在此載入 API 金鑰
# 建議寫在 .env 檔案中：GEMINI_API_KEY=你的金鑰
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ----------------- 第 5 部分：重點摘要與問答 ----------------- #

@app.route('/notes-ai')
def notes_ai_dashboard():
    """載入重點筆記與 AI 問答的整合面板頁面"""
    current_user = session.get('username', '訪客')
    return render_template('notes_ai.html', username=current_user)


@app.route('/api/summaries', methods=['GET'])
def get_summaries():
    """
    取得重點摘要清單
    [第一步 Mock] 先回傳符合資料表規格的範例資料
    後續只要把這裡改為讀取資料庫 summaries 表即可
    """
    mock_summaries = [
        {
            "id": 1,
            "chapter_name": "第 1 章：資料庫系統導論",
            "title": "關聯式資料庫正規化（1NF 到 3NF）",
            "content": "1NF 要求屬性值不可再分；2NF 消除部分相依；3NF 消除遞移相依，避免資料重複與更新異常。",
            "mastery": "複習中",  # 未讀 / 複習中 / 已熟
            "is_edited": False
        },
        {
            "id": 2,
            "chapter_name": "第 2 章：SQL 語法與查詢",
            "title": "SQL JOIN 差異比較",
            "content": "INNER JOIN 只取交集；LEFT JOIN 保留左表全部資料與右表交集；FULL OUTER JOIN 包含兩表全部資料。",
            "mastery": "已熟",
            "is_edited": True
        }
    ]
    return jsonify({"status": "success", "data": mock_summaries})


@app.route('/api/chat', methods=['POST'])
def chat_with_ai():
    """
    AI 問答接口
    支援方案 B（真實呼叫 LLM），若尚未填 API Key 則自動切換為 Demo 模式
    """
    data = request.get_json() or {}
    user_prompt = data.get("prompt", "").strip()
    context_note = data.get("context_note", "")  # 使用者若從左側筆記點擊提問，會附帶筆記內容

    if not user_prompt:
        return jsonify({"status": "error", "message": "請輸入問題內容"}), 400

    # 組合 Prompt（若有附帶筆記，形成簡單的 RAG / 脈絡提示）
    full_prompt = user_prompt
    if context_note:
        full_prompt = f"【參考筆記重點】：{context_note}\n\n【使用者問題】：{user_prompt}"

    # 判斷是否走「方案 B 真實 LLM」
    if GEMINI_API_KEY:
        try:
            # 範例：真實呼叫 Google Gemini API
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=full_prompt,
            )
            ai_reply = response.text
        except Exception as e:
            ai_reply = f"（真實 API 連線出現問題: {str(e)}，暫時回覆模擬結果）"
    else:
        # [第一步 Mock 模式] 尚未填入 API Key 時，先回傳模擬回答
        ai_reply = f"【AI 模擬回覆】：我收到你關於「{user_prompt}」的提問！這在考試中是常見弱項，建議多加強概念複習。"

    return jsonify({
        "status": "success",
        "reply": ai_reply,
        "intent": "learning",
        "context_used": context_note
    })
=======
    app = create_app()
    check_environment(app)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
>>>>>>> tye
