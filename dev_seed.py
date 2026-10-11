from __future__ import annotations

from werkzeug.security import generate_password_hash

from storage import db

DEV_USERNAME = "admin123"
DEV_PASSWORD = "12345678"
DEV_EMAIL = "admin123@local.test"


def ensure_dev_seed():
    """Create deterministic local-only development data.

    Call inside an application context after SQLite schema initialization.
    Never intended for production/self-host PostgreSQL.
    """
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (DEV_USERNAME,)).fetchone()
    if not user:
        cur = conn.execute(
            """INSERT INTO users(username,email,password_hash,is_email_verified,email_verified_at,password_changed_at)
               VALUES (?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
            (DEV_USERNAME, DEV_EMAIL, generate_password_hash(DEV_PASSWORD)),
        )
        user_id = cur.lastrowid
    else:
        user_id = user["id"]
        conn.execute(
            """UPDATE users SET password_hash=?,is_email_verified=1,
               email_verified_at=COALESCE(email_verified_at,CURRENT_TIMESTAMP),
               password_changed_at=CURRENT_TIMESTAMP WHERE id=?""",
            (generate_password_hash(DEV_PASSWORD), user_id),
        )

    profile = conn.execute("SELECT 1 FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
    if not profile:
        conn.execute(
            """INSERT INTO user_profiles(user_id,gender,birth_date,height_cm,activity_level,goal_type,
               workout_days_per_week,minutes_per_session,onboarded_at)
               VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (user_id, "未設定", "2000-01-01", 170, "一般", "學習測試", 0, 30),
        )

    subject = conn.execute(
        "SELECT * FROM subjects WHERE created_by=? AND subject_name=?",
        (user_id, "DEV 測試科目"),
    ).fetchone()
    if subject:
        subject_id = subject["id"]
    else:
        subject_id = conn.execute(
            "INSERT INTO subjects(subject_name,created_by) VALUES (?,?)",
            ("DEV 測試科目", user_id),
        ).lastrowid

    for order_no, name in enumerate(("概念理解", "應用練習", "綜合測驗"), 1):
        exists = conn.execute(
            "SELECT 1 FROM chapters WHERE subject_id=? AND chapter_name=?",
            (subject_id, name),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO chapters(subject_id,chapter_name,order_no) VALUES (?,?,?)",
                (subject_id, name, order_no),
            )
    conn.commit()
    return user_id
