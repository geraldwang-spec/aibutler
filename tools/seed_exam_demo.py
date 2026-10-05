"""Create only exam demo data for admin123; safe to rerun, no model calls."""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from flask import Flask
from storage import _connect_mariadb, _split_sql_script

# chapter, concept, stem, four options, answer, explanation
QUESTIONS = [
    ('Python 入門', '變數與型別', 'Python 中哪個值是整數？', ['12', '"12"', '12.5', 'True'], 'A', '12 是 int；引號內是字串。'),
    ('Python 入門', '變數與型別', 'type("hello") 的結果代表哪種型別？', ['整數', '字串', '浮點數', '串列'], 'B', '雙引號包住的文字屬於 str。'),
    ('Python 入門', '條件判斷', 'x = 5，x > 3 的結果是什麼？', ['False', 'None', 'True', '3'], 'C', '5 大於 3，因此結果為 True。'),
    ('Python 入門', '條件判斷', 'Python 使用哪個關鍵字開始條件判斷？', ['for', 'def', 'return', 'if'], 'D', 'if 用來依條件選擇執行分支。'),
    ('Python 入門', '迴圈與串列', 'len([10, 20, 30]) 的結果是什麼？', ['3', '2', '30', '60'], 'A', '串列中有三個元素。'),
    ('Python 入門', '迴圈與串列', 'list(range(3)) 的結果是什麼？', ['[1, 2, 3]', '[0, 1, 2]', '[0, 1, 2, 3]', '[3]'], 'B', 'range 從 0 開始，不包含終點 3。'),
    ('SQL 入門', 'SELECT 與篩選', '查詢資料表內容使用哪個 SQL 指令？', ['DELETE', 'INSERT', 'SELECT', 'UPDATE'], 'C', 'SELECT 用來讀取查詢資料。'),
    ('SQL 入門', 'SELECT 與篩選', '要篩選 age 大於 18 的資料，應使用哪個子句？', ['ORDER BY age', 'GROUP BY age', 'LIMIT 18', 'WHERE age > 18'], 'D', 'WHERE 用來篩選符合條件的資料列。'),
    ('SQL 入門', '鍵值與關聯', 'PRIMARY KEY 的主要用途是什麼？', ['唯一識別資料列', '加密所有欄位', '自動排序文字', '刪除重複資料表'], 'A', '主鍵用來唯一識別資料列，不能為 NULL。'),
    ('SQL 入門', '鍵值與關聯', 'FOREIGN KEY 主要維護什麼？', ['字串長度', '資料表間的參照完整性', '查詢排序', '欄位顏色'], 'B', '外鍵將資料列與另一個資料表的鍵建立關聯。'),
    ('SQL 入門', '排序與交易', 'ORDER BY score DESC 會如何排序？', ['分數由低到高', '隨機排序', '分數由高到低', '只留下最高分'], 'C', 'DESC 表示降冪排序。'),
    ('SQL 入門', '排序與交易', '要取消尚未提交的交易變更，使用哪個指令？', ['COMMIT', 'SELECT', 'CREATE TABLE', 'ROLLBACK'], 'D', 'ROLLBACK 回復尚未提交的交易。'),
]


def main():
    values = dotenv_values(ROOT / '.env')
    if values.get('DB_TYPE') != 'mariadb':
        raise SystemExit('This command expects the configured MariaDB database.')
    app = Flask(__name__)
    app.config.update(values)
    conn = _connect_mariadb(app)
    try:
        user = conn.execute('SELECT id FROM users WHERE username=?', ('admin123',)).fetchone()
        if not user:
            raise RuntimeError('Create admin123 before seeding its exam data.')
        uid = user['id']
        allowed = {'subjects', 'chapters', 'questions', 'question_options', 'exam_imports',
                   'import_items', 'quiz_sessions', 'quiz_answers', 'wrong_answers',
                   'concepts', 'question_concepts', 'source_question_items', 'question_metadata', 'ai_question_drafts'}
        for filename in ('schema_mariadb.sql', 'schema_tye_personal_mariadb.sql'):
            for statement in _split_sql_script((ROOT / filename).read_text(encoding='utf-8')):
                # Strip comments so selection does not depend on file formatting.
                clean = re.sub(r'(?m)^\s*--.*$', '', statement).strip()
                match = re.match(r'CREATE TABLE IF NOT EXISTS (\w+)', clean, re.I)
                if match and match[1] in allowed:
                    conn.execute(clean)
        totals = {}
        for strategy, title in [('fixed', '示範｜程式與資料庫・固定題庫'), ('concept', '示範｜程式與資料庫・概念題庫')]:
            subject = conn.execute('SELECT id FROM subjects WHERE created_by=? AND subject_name=?', (uid, title)).fetchone()
            sid = subject['id'] if subject else conn.execute('INSERT INTO subjects(subject_name,created_by) VALUES (?,?)', (title, uid)).lastrowid
            for chapter, concept, stem, options, answer, explanation in QUESTIONS:
                row = conn.execute('SELECT id FROM chapters WHERE subject_id=? AND chapter_name=?', (sid, chapter)).fetchone()
                cid = row['id'] if row else conn.execute('INSERT INTO chapters(subject_id,chapter_name,order_no) VALUES (?,?,?)', (sid, chapter, 1 if chapter.startswith('Python') else 2)).lastrowid
                if strategy == 'fixed':
                    exists = conn.execute('SELECT id FROM questions WHERE chapter_id=? AND content=?', (cid, stem)).fetchone()
                    if not exists:
                        qid = conn.execute('INSERT INTO questions(chapter_id,q_type,content,answer_key,explanation,difficulty,source) VALUES (?,?,?,?,?,?,?)', (cid, '單選', stem, answer, explanation, 1, 'demo_fixed')).lastrowid
                        conn.executemany('INSERT INTO question_options(question_id,option_label,option_text,order_no) VALUES (?,?,?,?)', [(qid, label, text, n) for n, (label, text) in enumerate(zip('ABCD', options), 1)])
                else:
                    row = conn.execute('SELECT id FROM concepts WHERE subject_id=? AND name=?', (sid, concept)).fetchone()
                    concept_id = row['id'] if row else conn.execute('INSERT INTO concepts(subject_id,chapter_id,name,description,importance) VALUES (?,?,?,?,?)', (sid, cid, concept, '入門觀念：' + concept, 3)).lastrowid
                    exists = conn.execute('SELECT id FROM source_question_items WHERE user_id=? AND subject_id=? AND raw_question=?', (uid, sid, stem)).fetchone()
                    if not exists:
                        conn.execute('INSERT INTO source_question_items(user_id,subject_id,chapter_id,source_file,raw_question,q_type,answer_key,explanation,options_json,concept_id,skill,cognitive_level,difficulty,classification_confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (uid, sid, cid, 'seed_exam_demo.py', stem, '單選', answer, explanation, json.dumps(dict(zip('ABCD', options)), ensure_ascii=False), concept_id, '辨識與基礎判讀', 'understand', 1, 1.0))
            totals[strategy] = sid
        conn.commit()
        output = ROOT / 'test_data' / 'exam_demo'
        output.mkdir(parents=True, exist_ok=True)
        with (output / '入門固定題庫.csv').open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['chapter_name', 'q_type', 'content', 'answer_key', 'explanation', 'difficulty', 'option_A', 'option_B', 'option_C', 'option_D'])
            for chapter, _, stem, options, answer, explanation in QUESTIONS:
                writer.writerow([chapter, '單選', stem, answer, explanation, 1, *options])
        (output / '入門文字題庫.txt').write_text('\n\n'.join(f'{n}. 單選 {stem}\n' + '\n'.join(f'{k}. {v}' for k,v in zip('ABCD', options)) + f'\n答案：{answer}\n解析：{explanation}' for n, (_, _, stem, options, answer, explanation) in enumerate(QUESTIONS, 1)), encoding='utf-8')
        print('Demo data created for admin123: 12 fixed questions; 6 concepts with 12 source examples. Subject IDs:', totals)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
