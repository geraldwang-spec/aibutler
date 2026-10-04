-- ITS Databases 測試題 1 題
-- 使用方式：先用網站註冊至少一個使用者，再在個人版自己的資料庫執行本檔。
-- 預設把題目建立給 users 表中最早建立的使用者。

SET @uid := (SELECT id FROM users ORDER BY id LIMIT 1);

INSERT INTO subjects(subject_name, created_by)
SELECT 'ITS Databases', @uid
WHERE @uid IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM subjects WHERE subject_name='ITS Databases' AND created_by=@uid
  );

SET @sid := (
  SELECT id FROM subjects
  WHERE subject_name='ITS Databases' AND created_by=@uid
  ORDER BY id LIMIT 1
);

INSERT INTO chapters(subject_id, chapter_name, order_no)
SELECT @sid, '預存程序', 1
WHERE @sid IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM chapters WHERE subject_id=@sid AND chapter_name='預存程序'
  );

SET @cid := (
  SELECT id FROM chapters
  WHERE subject_id=@sid AND chapter_name='預存程序'
  ORDER BY id LIMIT 1
);

INSERT INTO questions(chapter_id, q_type, content, answer_key, explanation, difficulty, source)
SELECT @cid, '單選',
       '您希望能夠在需要時隨時手動呼叫程式碼。請問您可以使用哪一個資料庫物件來儲存程式碼？',
       'B',
       '預存程序可將 SQL 程式碼儲存在資料庫中並由使用者或應用程式主動呼叫。',
       1,
       'ITS Databases 模擬試題 Q1'
WHERE @cid IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM questions
    WHERE chapter_id=@cid
      AND content='您希望能夠在需要時隨時手動呼叫程式碼。請問您可以使用哪一個資料庫物件來儲存程式碼？'
  );

SET @qid := (
  SELECT id FROM questions
  WHERE chapter_id=@cid
    AND content='您希望能夠在需要時隨時手動呼叫程式碼。請問您可以使用哪一個資料庫物件來儲存程式碼？'
  ORDER BY id LIMIT 1
);

INSERT INTO question_options(question_id, option_label, option_text, order_no)
SELECT @qid, 'A', '函式', 1
WHERE @qid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=@qid AND option_label='A');
INSERT INTO question_options(question_id, option_label, option_text, order_no)
SELECT @qid, 'B', '預存程序', 2
WHERE @qid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=@qid AND option_label='B');
INSERT INTO question_options(question_id, option_label, option_text, order_no)
SELECT @qid, 'C', '觸發程序', 3
WHERE @qid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=@qid AND option_label='C');
INSERT INTO question_options(question_id, option_label, option_text, order_no)
SELECT @qid, 'D', '檢視表', 4
WHERE @qid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=@qid AND option_label='D');

SELECT @uid AS user_id, @sid AS subject_id, @cid AS chapter_id, @qid AS question_id;
