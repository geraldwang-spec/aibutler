"""Reset and seed the ITS Databases test bank for the TYE exam module.

Usage:
    python TYE/reset_its_questionbank.py --username TYE1124

The script only resets the subject named "ITS Databases" owned by the selected
user.  It also removes dependent quiz/wrong-answer/import rows for that subject
so the reset is FK-safe.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from storage import db

SUBJECT_NAME = "ITS Databases"

QUESTIONS = [
    {
        "chapter": "程式化物件與檢視表",
        "type": "單選",
        "content": "您撰寫了一系列執行冗長複雜查詢的 SQL 陳述式。您希望能夠在需要時隨時手動呼叫程式碼。請問您可以使用哪一個資料庫物件來儲存程式碼？",
        "answer": "B",
        "options": [("A", "函式"), ("B", "預存程序"), ("C", "觸發程序"), ("D", "檢視表")],
        "source": "ITS Databases 模擬試題.pdf Q1",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "多選",
        "content": "您正在開發一個 SQL 陳述式以建立資料表。請問哪兩個 SQL 關鍵字可用於 CREATE TABLE 陳述式？",
        "answer": "C,D",
        "options": [("A", "INSERT INTO"), ("B", "ORDER BY"), ("C", "PRIMARY KEY"), ("D", "CONSTRAINT")],
        "source": "ITS Databases 模擬試題.pdf Q2",
    },
    {
        "chapter": "程式化物件與檢視表",
        "type": "單選",
        "content": "您建立了一個名為 Games 的資料表，其中包含最近發行之電玩遊戲的評論分數。您需要建立一個檢視表，傳回依字母順序排列的遊戲名稱。哪一個陳述式符合需求？",
        "answer": "C",
        "options": [
            ("A", "CREATE VIEW MyGames AS SELECT Name FROM Games"),
            ("B", "CREATE VIEW MyGames AS SELECT * FROM Games"),
            ("C", "CREATE VIEW MyGames AS SELECT Name FROM Games ORDER BY Name"),
            ("D", "CREATE VIEW MyGames AS SELECT * FROM Games WHERE Name BETWEEN 'A' AND 'Z'")
        ],
        "source": "ITS Databases 模擬試題.pdf Q4",
    },
    {
        "chapter": "SQL 查詢與資料操作",
        "type": "單選",
        "content": "請問哪一個 SQL 陳述式會傳回訂單數目少於 50 的國家/地區，以及各國家/地區的訂單數目？",
        "answer": "D",
        "options": [
            ("A", "SELECT Country, orderID FROM Orders WHERE COUNT(orderID) < 50 GROUP BY Country;"),
            ("B", "SELECT COUNT(orderID), Country FROM Orders HAVING COUNT(orderID) < 50 GROUP BY Country;"),
            ("C", "SELECT Country, orderID FROM Orders GROUP BY Country WHERE COUNT(orderID) < 50;"),
            ("D", "SELECT COUNT(orderID), Country FROM Orders GROUP BY Country HAVING COUNT(orderID) < 50;")
        ],
        "source": "ITS Databases 模擬試題.pdf Q6",
    },
    {
        "chapter": "程式化物件與檢視表",
        "type": "單選",
        "content": "您需要從資料庫中移除名為 EmployeeView 的檢視表。請問您應該使用哪一個陳述式？",
        "answer": "C",
        "options": [("A", "DELETE EmployeeView"), ("B", "DELETE VIEW EmployeeView"), ("C", "DROP VIEW EmployeeView"), ("D", "DROP EmployeeView")],
        "source": "ITS Databases 模擬試題.pdf Q7",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "單選",
        "content": "您的資料庫有一個 Department 資料表以及一個 Employee 資料表。您需要確保一位員工只能被指派到一個現有的部門。請問您應該對 Employee 資料表套用什麼？",
        "answer": "B",
        "options": [("A", "唯一條件約束"), ("B", "外部索引鍵"), ("C", "資料類型"), ("D", "索引"), ("E", "主索引鍵")],
        "source": "ITS Databases 模擬試題.pdf Q9",
    },
    {
        "chapter": "正規化與資料關聯",
        "type": "多選",
        "content": "您需要將資料庫正規化為第一正規形式。請問您必須符合哪兩項需求？",
        "answer": "B,D",
        "options": [("A", "排除外部索引鍵"), ("B", "排除重複資料列"), ("C", "排除複合索引鍵"), ("D", "排除重複群組")],
        "source": "ITS Databases 模擬試題.pdf Q10",
    },
    {
        "chapter": "SQL 查詢與資料操作",
        "type": "單選",
        "content": "請問哪一個陳述式會刪除未輸入員工電話號碼的資料列？",
        "answer": "A",
        "options": [("A", "DELETE FROM Employee WHERE Phone IS NULL"), ("B", "DELETE FROM Employee WHERE Phone IS NOT NULL"), ("C", "DELETE FROM Employee WHERE Phone = NULLABLE"), ("D", "DELETE FROM Employee WHERE Phone = NULL")],
        "source": "ITS Databases 模擬試題.pdf Q11",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "單選",
        "content": "Road 資料表定義為 RoadID INTEGER NOT NULL、Distance INTEGER NOT NULL，且已有 RoadID 1234。執行 INSERT INTO Road VALUES (1234, 36) 後會發生什麼？",
        "answer": "C",
        "options": [("A", "發生錯誤，指出不允許重複的 ID"), ("B", "發生錯誤，指出不允許 NULL 值"), ("C", "資料表中的新資料列"), ("D", "語法錯誤")],
        "source": "ITS Databases 模擬試題.pdf Q13",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "單選",
        "content": "您需要刪除某個資料庫資料表。請問您應該使用哪一個資料定義語言（DDL）關鍵字？",
        "answer": "C",
        "options": [("A", "TRUNCATE"), ("B", "ALTER"), ("C", "DROP"), ("D", "DELETE")],
        "source": "ITS Databases 模擬試題.pdf Q14",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "單選",
        "content": "請問關聯式資料庫會使用哪一項功能來確保輸入資料列中的資料正確？",
        "answer": "C",
        "options": [("A", "屬性"), ("B", "主索引鍵"), ("C", "條件約束"), ("D", "索引")],
        "source": "ITS Databases 模擬試題.pdf Q16",
    },
    {
        "chapter": "SQL 查詢與資料操作",
        "type": "單選",
        "content": "Customer 資料表包含 CustomerID、FirstName 和 DateJoined。執行 SELECT CustomerID, FirstName, DateJoined FROM Customer，在沒有 ORDER BY 的情況下，查詢結果集會以哪種方式傳回資料列？",
        "answer": "C",
        "options": [("A", "按照 FirstName 的字母順序"), ("B", "按照插入資料列的順序"), ("C", "按照無法預期的順序"), ("D", "按照 DateJoined 的時間順序")],
        "source": "ITS Databases 模擬試題.pdf Q17",
    },
    {
        "chapter": "程式化物件與檢視表",
        "type": "單選",
        "content": "建立預存程序的其中一個原因是要：",
        "answer": "A",
        "options": [("A", "提升效能"), ("B", "略過區分大小寫需求"), ("C", "將儲存空間最小化"), ("D", "讓使用者能夠控制查詢邏輯")],
        "source": "ITS Databases 模擬試題.pdf Q21",
    },
    {
        "chapter": "正規化與資料關聯",
        "type": "多選",
        "content": "Chapter 與 Language 形成多對多關聯並建立 ChapterLanguage 關聯資料表。請問 ChapterLanguage 應包含哪兩個欄位？",
        "answer": "B,D",
        "options": [("A", "City"), ("B", "LanguageId"), ("C", "Country"), ("D", "ChapterId"), ("E", "Region"), ("F", "LanguageName")],
        "source": "ITS Databases 模擬試題.pdf Q22",
    },
    {
        "chapter": "SQL 查詢與資料操作",
        "type": "單選",
        "content": "Product 資料表包含約一百萬個資料列，查詢使用 WHERE Category = 'Science'。以下何者最可能讓這種搜尋更有效率？",
        "answer": "C",
        "options": [("A", "Price 資料行的叢集索引"), ("B", "ProductName 資料行的叢集索引"), ("C", "Category 資料行的非叢集索引"), ("D", "Price 資料行的非叢集索引")],
        "source": "ITS Databases 模擬試題.pdf Q24",
    },
    {
        "chapter": "SQL 查詢與資料操作",
        "type": "單選",
        "content": "您執行了一個交易內的陳述式，準備從資料表刪除 100 個資料列；僅刪除 40 個資料列之後交易被復原。請問資料庫的結果為何？",
        "answer": "D",
        "options": [("A", "資料表將損毀"), ("B", "交易將重新啟動"), ("C", "系統將從資料表中刪除 40 個資料列"), ("D", "系統不會從資料表中刪除任何資料列")],
        "source": "ITS Databases 模擬試題.pdf Q25",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "單選",
        "content": "您刪除了 Order 資料表中的資料列，OrderItem 資料表中的對應資料列也被自動刪除。這是哪一種程序的範例？",
        "answer": "D",
        "options": [("A", "繼承法刪除 (Inherited Delete)"), ("B", "函式法刪除 (Functional Delete)"), ("C", "瀑布法刪除 (Waterfall Delete)"), ("D", "串聯刪除 (Cascade Delete)"), ("E", "骨牌法刪除 (Domino Delete)")],
        "source": "ITS Databases 模擬試題.pdf Q27",
    },
    {
        "chapter": "DDL、鍵與約束",
        "type": "單選",
        "content": "請問哪一個陳述式會建立索引？",
        "answer": "B",
        "options": [("A", "CREATE TABLE Employee (EmployeeID INTEGER NULL)"), ("B", "CREATE TABLE Employee (EmployeeID INTEGER PRIMARY KEY)"), ("C", "CREATE TABLE Employee (EmployeeID INTEGER DISTINCT)"), ("D", "CREATE TABLE Employee (EmployeeID INTEGER INDEX)")],
        "source": "ITS Databases 模擬試題.pdf Q28",
    },
    {
        "chapter": "SQL 查詢與資料操作",
        "type": "單選",
        "content": "您執行 SELECT EmployeeID, FirstName, DepartmentName FROM Employee, Department。這種作業稱為什麼？",
        "answer": "B",
        "options": [("A", "等聯結"), ("B", "笛卡兒乘積"), ("C", "交集"), ("D", "外部聯結")],
        "source": "ITS Databases 模擬試題.pdf Q29",
    },
    {
        "chapter": "正規化與資料關聯",
        "type": "單選",
        "content": "資料表包含 ProductID 與 ProductCategory。若每一個 ProductID 都決定其 ProductCategory，請問這兩個資料行之間的關聯稱為什麼？",
        "answer": "B",
        "options": [("A", "決定性"), ("B", "功能相依"), ("C", "關聯相依"), ("D", "複合"), ("E", "世代")],
        "source": "ITS Databases 模擬試題.pdf Q30",
    },
]

CHAPTERS = [
    "程式化物件與檢視表",
    "DDL、鍵與約束",
    "SQL 查詢與資料操作",
    "正規化與資料關聯",
]


def placeholders(values):
    return ",".join("?" for _ in values)


def delete_existing_subject(user_id: int):
    subjects = db().execute(
        "SELECT id FROM subjects WHERE subject_name=? AND (created_by=? OR created_by IS NULL)",
        (SUBJECT_NAME, user_id),
    ).fetchall()
    subject_ids = [row["id"] for row in subjects]
    if not subject_ids:
        return

    sph = placeholders(subject_ids)
    chapters = db().execute(f"SELECT id FROM chapters WHERE subject_id IN ({sph})", tuple(subject_ids)).fetchall()
    chapter_ids = [row["id"] for row in chapters]
    question_ids = []
    if chapter_ids:
        cph = placeholders(chapter_ids)
        question_ids = [row["id"] for row in db().execute(f"SELECT id FROM questions WHERE chapter_id IN ({cph})", tuple(chapter_ids)).fetchall()]
    session_ids = [row["id"] for row in db().execute(f"SELECT id FROM quiz_sessions WHERE subject_id IN ({sph})", tuple(subject_ids)).fetchall()]
    import_ids = [row["id"] for row in db().execute(f"SELECT id FROM exam_imports WHERE subject_id IN ({sph})", tuple(subject_ids)).fetchall()]
    exam_plan_ids = [row["id"] for row in db().execute(f"SELECT id FROM exam_plans WHERE subject_id IN ({sph})", tuple(subject_ids)).fetchall()]
    material_ids = [row["id"] for row in db().execute(f"SELECT id FROM materials WHERE subject_id IN ({sph})", tuple(subject_ids)).fetchall()]

    if question_ids:
        qph = placeholders(question_ids)
        db().execute(f"DELETE FROM wrong_answers WHERE question_id IN ({qph})", tuple(question_ids))
        db().execute(f"DELETE FROM import_items WHERE question_id IN ({qph})", tuple(question_ids))
    if session_ids:
        seph = placeholders(session_ids)
        db().execute(f"DELETE FROM quiz_answers WHERE session_id IN ({seph})", tuple(session_ids))
        db().execute(f"DELETE FROM quiz_sessions WHERE id IN ({seph})", tuple(session_ids))
    if question_ids:
        qph = placeholders(question_ids)
        db().execute(f"DELETE FROM quiz_answers WHERE question_id IN ({qph})", tuple(question_ids))
        db().execute(f"DELETE FROM question_options WHERE question_id IN ({qph})", tuple(question_ids))
        db().execute(f"DELETE FROM questions WHERE id IN ({qph})", tuple(question_ids))
    if import_ids:
        iph = placeholders(import_ids)
        db().execute(f"DELETE FROM import_items WHERE import_id IN ({iph})", tuple(import_ids))
        db().execute(f"DELETE FROM exam_imports WHERE id IN ({iph})", tuple(import_ids))
    if chapter_ids:
        cph = placeholders(chapter_ids)
        db().execute(f"DELETE FROM study_plans WHERE chapter_id IN ({cph})", tuple(chapter_ids))
        db().execute(f"DELETE FROM summaries WHERE chapter_id IN ({cph})", tuple(chapter_ids))
        db().execute(f"UPDATE chapters SET parent_chapter_id=NULL WHERE id IN ({cph})", tuple(chapter_ids))
    if exam_plan_ids:
        eph = placeholders(exam_plan_ids)
        db().execute(f"DELETE FROM study_plans WHERE exam_plan_id IN ({eph})", tuple(exam_plan_ids))
        db().execute(f"DELETE FROM exam_plans WHERE id IN ({eph})", tuple(exam_plan_ids))
    if material_ids:
        mph = placeholders(material_ids)
        doc_ids = [row["id"] for row in db().execute(f"SELECT id FROM rag_documents WHERE material_id IN ({mph})", tuple(material_ids)).fetchall()]
        if doc_ids:
            dph = placeholders(doc_ids)
            db().execute(f"DELETE FROM rag_chunks WHERE doc_id IN ({dph})", tuple(doc_ids))
            db().execute(f"DELETE FROM rag_documents WHERE id IN ({dph})", tuple(doc_ids))
        db().execute(f"DELETE FROM materials WHERE id IN ({mph})", tuple(material_ids))
    if chapter_ids:
        cph = placeholders(chapter_ids)
        db().execute(f"DELETE FROM rag_chunks WHERE chapter_id IN ({cph})", tuple(chapter_ids))
        db().execute(f"DELETE FROM chapters WHERE id IN ({cph})", tuple(chapter_ids))
    db().execute(f"DELETE FROM subjects WHERE id IN ({sph})", tuple(subject_ids))


def seed(user_id: int):
    delete_existing_subject(user_id)
    cursor = db().execute("INSERT INTO subjects(subject_name,created_by) VALUES (?,?)", (SUBJECT_NAME, user_id))
    subject_id = cursor.lastrowid

    chapter_ids = {}
    for order_no, name in enumerate(CHAPTERS, 1):
        cursor = db().execute(
            "INSERT INTO chapters(subject_id,chapter_name,order_no) VALUES (?,?,?)",
            (subject_id, name, order_no),
        )
        chapter_ids[name] = cursor.lastrowid

    for question in QUESTIONS:
        cursor = db().execute(
            """INSERT INTO questions(chapter_id,q_type,content,answer_key,explanation,difficulty,source)
               VALUES (?,?,?,?,?,?,?)""",
            (
                chapter_ids[question["chapter"]],
                question["type"],
                question["content"],
                question["answer"],
                "答案：" + question["answer"],
                1,
                question["source"],
            ),
        )
        question_id = cursor.lastrowid
        db().executemany(
            "INSERT INTO question_options(question_id,option_label,option_text,order_no) VALUES (?,?,?,?)",
            [(question_id, label, text, order_no) for order_no, (label, text) in enumerate(question["options"], 1)],
        )
    db().commit()
    return subject_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", help="Owner username. Defaults to the first verified user.")
    args = parser.parse_args()

    with app.app_context():
        if args.username:
            user = db().execute("SELECT id,username FROM users WHERE username=?", (args.username,)).fetchone()
        else:
            user = db().execute("SELECT id,username FROM users WHERE is_email_verified=1 ORDER BY id LIMIT 1").fetchone()
        if not user:
            raise SystemExit("找不到可用使用者。請先註冊，或使用 --username 指定既有帳號。")

        subject_id = seed(user["id"])
        rows = db().execute(
            """SELECT c.chapter_name, COUNT(q.id) AS n
               FROM chapters c LEFT JOIN questions q ON q.chapter_id=c.id
               WHERE c.subject_id=? GROUP BY c.id,c.chapter_name,c.order_no
               ORDER BY c.order_no""",
            (subject_id,),
        ).fetchall()
        print(f"已重建 {SUBJECT_NAME}，owner={user['username']} (user_id={user['id']})")
        print(f"subject_id={subject_id}, total_questions={len(QUESTIONS)}")
        for row in rows:
            print(f"- {row['chapter_name']}: {row['n']} 題")


if __name__ == "__main__":
    main()
