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
    
