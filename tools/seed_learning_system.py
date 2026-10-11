"""Add an original, labelled learning dataset; no model calls or fabricated grades."""
import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values
from flask import Flask,g
from storage import db,register_storage
from personal_ai.question_validation import validate
from personal_ai.parsers import chunk_sections

# Subject, chapter, explanation, example, pitfall, two multiple-choice questions,
# true/false question, and a short fill-in question. All content is original.
UNITS=[
 ('Python 程式設計','變數與資料型別',
  '變數名稱指向物件。指派使用 =，比較是否相等使用 ==。整數 int、浮點數 float、字串 str 和布林 bool 有不同用途。input() 回傳字串；要做整數運算可使用 int() 轉換，但格式不合時會產生 ValueError。不可把「文字看起來像數字」當成已經是數字。',
  'age_text = "18"\nage = int(age_text)\nnext_age = age + 1\nprint(next_age)  # 19\nprint(type(age_text).__name__)  # str',
  '"2" + "3" 得到 "23"，不是 5。int("3.5") 不接受小數格式；若需要小數可用 float("3.5")。不要對不可信輸入直接使用 eval()。',
  [('input() 在 Python 3 預設回傳什麼型別？',['字串','整數','浮點數','布林'],'A','input() 取得的文字為 str，數值運算前需明確轉換。'),
   ('已知 x = "7"，哪個運算結果為整數 8？',['x + "1"','int(x) + 1','x * 8','len(x)'],'B','int(x) 將字串轉為整數 7，再加 1。')],
  ('Python 中 = 與 == 的用途完全相同。','否','= 是指派；== 是相等比較。'),
  ('將 "12" 轉為整數，應使用哪個內建函式？','int','int("12") 得到整數 12。')),
 ('Python 程式設計','條件與迴圈',
  'if、elif、else 根據条件選擇分支。Python 使用縮排界定區塊；同一層的程式應保持一致縮排。for 依序處理可迭代物件；while 在條件為真時重複。range(start, stop) 包含 start、不包含 stop；range(n) 從 0 到 n-1。break 結束最近一層迴圈，continue 跳到下一次迭代。',
  'total = 0\nfor n in range(1, 4):\n    total += n\nprint(total)  # 6\nif total >= 6:\n    print("達標")',
  'range(1, 4) 不是 1 到 4。while 如果條件一直為真且沒有 break，就可能無限重複。if 的分支只會選擇第一個成立的條件，不會將每個 elif 都執行。',
  [('list(range(2, 5)) 的結果是？',['[2, 3, 4, 5]','[0, 1, 2, 3, 4]','[2, 3, 4]','[3, 4, 5]'],'C','起點 2 包含在內，終點 5 不包含。'),
   ('要結束目前這一層迴圈，使用哪個關鍵字？',['if','continue','pass','break'],'D','break 直接離開最近一層迴圈。')],
  ('continue 會略過本次迭代後續程式，開始下一次迭代。','是','continue 不會直接結束整個迴圈。'),
  ('在 if 後補充另一個條件分支的 Python 關鍵字是？','elif','elif 表示前面條件不成立時再檢查另一個條件。')),
 ('Python 程式設計','函式與串列',
  'def 定義函式，參數是函式接收輸入的名稱。return 將結果交回呼叫端，print 只輸出文字；沒有 return 的函式通常回傳 None。串列 list 可依索引讀寫，第一個索引為 0，負索引 -1 表示最後一個元素。len() 取得元素個數，append() 在末端加入單一元素。',
  'def double(n):\n    return n * 2\nitems = [10, 20, 30]\nitems.append(double(5))\nprint(items[-1])  # 10\nprint(len(items))  # 4',
  '三個元素的有效非負索引為 0、1、2，讀取索引 3 會出錯。append() 原地修改串列且回傳 None，不能用 items = items.append(40) 保留串列。',
  [('items = [10, 20, 30]，items[0] 是？',['10','20','30','0'],'A','索引從 0 開始，所以第一個元素為 10。'),
   ('函式要將計算結果交給呼叫端，使用？',['print','return','append','input'],'B','return 是回傳值；print 只是顯示。')],
  ('沒有明確 return 的 Python 函式一定回傳整數 0。','否','通常回傳 None，而不是 0。'),
  ('將單一元素加入串列末端的方法名稱是？','append','items.append(value) 會原地加入元素。')),
 ('SQL 資料庫','查詢與篩選',
  'SELECT 選擇要讀取的欄位，FROM 指定來源資料表，WHERE 篩選資料列。ORDER BY 排序，ASC 為升冪、DESC 為降冪；沒有 ORDER BY 不保證結果順序。WHERE 中可使用 AND、OR 組合條件，括號能明確表達優先順序。SQL 的 NULL 表示未知或缺值，檢查時使用 IS NULL，而不是 = NULL。',
  'SELECT name, score\nFROM students\nWHERE score >= 60 AND active = 1\nORDER BY score DESC;\n-- 讀取啟用且及格的學生，分數由高至低',
  'WHERE score > 60 不包含 60；WHERE score >= 60 才包含。SELECT * 會選取所有欄位，實際系統可明確列出必要欄位。資料沒有指定排序時不能假設照主鍵排列。',
  [('要留下 score >= 60 的資料列，使用哪個子句？',['WHERE score >= 60','ORDER BY score','FROM score','SELECT 60'],'A','WHERE 負責篩選資料列。'),
   ('要讓分數由高到低排序，應使用？',['ORDER BY score ASC','ORDER BY score DESC','WHERE score DESC','GROUP BY DESC'],'B','DESC 表示降冪。')],
  ('沒有 ORDER BY 時，SQL 查詢一定依照主鍵升冪回傳。','否','資料庫不保證未指定排序的結果順序。'),
  ('檢查某欄位為 NULL，使用 IS 後的關鍵字是？','NULL','條件可寫成 column_name IS NULL。')),
 ('SQL 資料庫','主鍵外鍵與 JOIN',
  '主鍵 PRIMARY KEY 用來唯一識別一列資料，不允許重複與 NULL；一張表可以有由多欄組成的複合主鍵。外鍵 FOREIGN KEY 表示對其他鍵的參照，用來維護參照完整性，外鍵值本身不一定唯一。INNER JOIN 保留符合關聯條件的配對；LEFT JOIN 保留左表全部資料，右側找不到配對的欄位顯示 NULL。',
  'SELECT s.name, d.department_name\nFROM students s\nLEFT JOIN departments d\n  ON s.department_id = d.id;\n-- 未分配科系的學生仍保留，科系欄位可能為 NULL',
  'LEFT JOIN 後若在 WHERE 要求右表欄位等於某值，可能排除沒有配對的左表資料。外鍵可以重複，例如多位學生屬於同一科系。主鍵與外鍵不是用來加密資料的。',
  [('要保留左表全部資料，包括沒有配對的資料，應使用？',['INNER JOIN','CROSS JOIN','LEFT JOIN','DELETE JOIN'],'C','LEFT JOIN 保留左側所有資料列。'),
   ('外鍵最主要維護哪一項？',['字體大小','結果顏色','欄位加密','參照完整性'],'D','外鍵使資料間的參照遵守約束。')],
  ('一張資料表的主鍵可以由多個欄位共同组成。','是','這稱為複合主鍵。'),
  ('僅保留符合配對條件的關聯查詢，在 JOIN 前使用哪個關鍵字？','INNER','INNER JOIN 只保留符合條件的配對。')),
 ('SQL 資料庫','聚合與交易',
  'COUNT、SUM、AVG 是常用聚合函式。COUNT(*) 計算資料列數，COUNT(column) 不計算該欄為 NULL 的列。GROUP BY 按欄位分組，HAVING 篩選分組後的聚合結果。交易把多個資料變更組成邏輯單位；COMMIT 提交，ROLLBACK 撤回尚未提交的變更。實際操作仍受資料庫引擎及自動提交設定影響。',
  'SELECT department_id, COUNT(*) AS people\nFROM students\nGROUP BY department_id\nHAVING COUNT(*) >= 2;\n-- 只顯示至少有兩位學生的科系\nSTART TRANSACTION;\nUPDATE accounts SET balance = balance - 100 WHERE id = 1;\nROLLBACK;',
  'WHERE 在分組前篩選列，HAVING 在分組後篩選聚合結果。已提交的交易不能靠下一個 ROLLBACK 撤回。備份與交易不是相同用途，交易不能代替定期備份。',
  [('分組後要篩選 COUNT(*) >= 2，使用哪個子句？',['HAVING','WHERE','ORDER','LIMIT'],'A','HAVING 篩選分組後的聚合結果。'),
   ('撤回尚未提交的交易變更，使用？',['COMMIT','ROLLBACK','SELECT','COUNT'],'B','ROLLBACK 撤回未提交的變更。')],
  ('COUNT(column) 會將該欄位為 NULL 的列也計入。','否','COUNT(column) 忽略 NULL，COUNT(*) 計算資料列數。'),
  ('確認並提交目前交易的 SQL 指令是？','COMMIT','COMMIT 提交交易。')),
 ('網路與資安','IP、DNS 與連線',
  'IP 位址用來在 IP 網路中識別介面；連接埠用來區分同一主機上的服務。DNS 將網域名稱查詢成相關紀錄，例如 A 紀錄的 IPv4 位址。DNS 名稱解析成功不代表目的服務正在運行。TCP 建立連線後提供可靠且有序的位元組傳輸；服務未監聽指定埠時可能拒絕連線。',
  '使用者輸入 example.com → DNS 查詢 → 取得目的 IP → 連到指定連接埠 → 應用層請求。\n檢查問題時分開確認名稱、位址、埠、服務程序與防火牆規則。',
  '連線被拒絕與等待逾時不是同一訊息：前者通常代表目的端回應拒絕，後者可能是網路阻擋或服務未及時回應。ping 成功也不能保證網站或資料庫的 TCP 埠可用。',
  [('將網域名稱解析成相關位址紀錄，主要由哪個系統處理？',['FTP','CPU','DNS','SQL'],'C','DNS 提供名稱查詢。'),
   ('同一主機上區分不同網路服務，主要使用？',['螢幕尺寸','檔案副檔名','主機顏色','連接埠'],'D','連接埠用來區分服務端點。')],
  ('DNS 查詢成功就能保證網站服務目前可連線。','否','名稱解析與服務是否可用是不同層的問題。'),
  ('提供可靠、有序位元組傳輸的傳輸層協定縮寫是？','TCP','TCP 提供可靠且有序的位元組傳輸。')),
 ('網路與資安','HTTP 與 API',
  'HTTP 請求包含方法、路徑、標頭與可能的內容。GET 通常讀取資源，POST 用來提交內容。狀態碼 200 表示該請求成功，401 表示缺乏有效驗證，403 表示拒絕存取，429 表示請求受到限流，500 表示伺服器內部錯誤。API 金鑰應保存在伺服器的設定或秘密管理工具，不放在公開前端程式。',
  'GET /materials 讀取教材列表。\nPOST /quiz/123 提交作答。\nAPI 回傳 429 時應閱讀服務配額與錯誤訊息，減少單次 token 或控制頻率；不應無限制重試。',
  '429 不必然代表金鑰失效。timeout 是等待上限，不是成功保證。重試寫入請求前要考慮是否已完成，避免重複建立資料；可用冪等鍵或交易保護。',
  [('API 回傳 HTTP 429，最符合哪種問題？',['請求受限流或配額限制','所有資料已刪除','DNS 名稱一定不存在','密碼一定正確'],'A','429 表示 Too Many Requests，需檢查限制。'),
   ('讀取教材列表，較適合使用哪個 HTTP 方法？',['DELETE','GET','PATCH','POST'],'B','GET 通常用來讀取資源。')],
  ('公開前端 JavaScript 適合直接放置秘密 API 金鑰。','否','前端內容可被使用者讀取，秘密應留在伺服器。'),
  ('HTTP 中常用來提交表單內容的方法是？','POST','POST 用來提交內容。')),
 ('網路與資安','帳號防護與備份',
  '密碼應使用適合密碼的雜湊方法保存，不以明文保存。最小權限原則只提供完成工作所需權限。MFA 加入不同類型的驗證因素，可降低單一密碼外洩的影響。備份應保留可恢復的資料副本；同一台主機的副本不能抵禦整台主機或硬碟故障。備份完成不等於復原一定成功，需安排復原演練。',
  '應用帳號平時只取得必要資料讀寫權限；資料迁移由另有權限的帳號操作。\n資料庫故障可先用唯讀快照查閱，恢復寫入則把資料復原到獨立資料庫，確認後再切換。',
  '備份不是零資料損失的保證。最後一次成功備份之後的變更可能遺失。把兩個資料庫都開成可寫，沒有同步與衝突處理機制時可能產生資料分歧。',
  [('只給帳號完成工作所需權限，稱為？',['所有權限原則','資料重複原則','最小權限原則','公開密碼原則'],'C','最小權限能縮小帳號受侵害時的影響。'),
   ('哪個做法能減少整台主機故障對備份的影響？',['只改檔名','放在同一磁碟另一個資料夾','不記錄備份時間','另存到不同主機或外部媒體'],'D','副本應避開相同故障來源。')],
  ('同一硬碟上的另一份資料足以防止整顆硬碟故障。','否','同一硬碟故障會影響兩份資料。'),
  ('多因素驗證的常見英文縮寫是？','MFA','MFA 是 Multi-Factor Authentication。')),
]


def export_subject_files(rows,output):
    for subject in dict.fromkeys(row[0] for row in rows):
        path=output/(subject.replace('示範課程｜','')+'_固定題庫.csv')
        with path.open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.writer(file)
            writer.writerow(['chapter_name','q_type','content','answer_key','explanation','difficulty','option_A','option_B','option_C','option_D'])
            writer.writerows(row[1:] for row in rows if row[0]==subject)


def seed(username):
    app=Flask(__name__)
    app.config.update(dotenv_values(ROOT/'.env'))
    app.config.update(DB_READ_ONLY=False,DB_STANDBY_ENABLED=False)
    if app.config.get('DB_TYPE')!='mariadb': raise ValueError('此建構腳本僅對目前 MariaDB 設定執行。')
    register_storage(app)
    output=ROOT/'instance'/'learning_demo'
    output.mkdir(parents=True,exist_ok=True)
    counts={}
    manifest=dict(account=username,created_at=date.today().isoformat(),subjects={},materials=[],quiz_ids=[],goal_ids=[])
    def put(table,values):
        ident=db().execute('INSERT INTO '+table+' ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values())).lastrowid
        counts[table]=counts.get(table,0)+1
        return ident
    with app.app_context():
        user=db().execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if not user: raise ValueError('找不到指定帳號；不會擅自新建或重設密碼。')
        g.user=user
        uid=user['id']; subject_chapters={}; fixed_export=[]
        # Lock the owner throughout the data transaction to avoid concurrent seed duplication.
        db().execute('SELECT id FROM users WHERE id=? FOR UPDATE',(uid,)).fetchone()
        for subject,chapter,explanation,example,pitfall,mc,tf,fill in UNITS:
            subject_title='示範課程｜'+subject
            row=db().execute('SELECT id FROM subjects WHERE created_by=? AND subject_name=?',(uid,subject_title)).fetchone()
            sid=row['id'] if row else put('subjects',dict(subject_name=subject_title,created_by=uid))
            manifest['subjects'][subject_title]=sid
            row=db().execute('SELECT id FROM chapters WHERE subject_id=? AND chapter_name=?',(sid,chapter)).fetchone()
            cid=row['id'] if row else put('chapters',dict(subject_id=sid,chapter_name=chapter,order_no=len(subject_chapters.get(sid,[]))+1))
            subject_chapters.setdefault(sid,[]).append(cid)
            row=db().execute('SELECT id FROM concepts WHERE subject_id=? AND name=?',(sid,chapter)).fetchone()
            concept_id=row['id'] if row else put('concepts',dict(subject_id=sid,chapter_id=cid,name=chapter,description=explanation,importance=3))
            title=f'示範講義｜{subject}－{chapter}'
            source=f'''# {title}

原創入門示範教材，用於學校報告；不是官方考試講義。

## 學習目標
理解「{chapter}」的定義，能說明用途、閱讀簡單例子，並辨識常見錯誤。

## 核心觀念
{explanation}

## 完整示例
{example}

## 常見誤解
{pitfall}

## 自我檢核
{tf[0]} 正確判斷：{tf[1]}。理由：{tf[2]}
{fill[0]} 參考答案：{fill[1]}。理由：{fill[2]}

## 建議練習
先自行回答自我檢核，再比較上述理由；使用普通隨機測驗練習本章題目。
完成閱讀不代表已通過測驗；請以實際作答結果決定是否需要複習。
'''
            path=output/(subject+'_'+chapter+'.md')
            if not path.exists(): path.write_text(source,encoding='utf-8')
            row=db().execute('SELECT id FROM materials WHERE user_id=? AND subject_id=? AND title=?',(uid,sid,title)).fetchone()
            if row:
                mid=row['id']
                chunk_ids=[r['id'] for r in db().execute('SELECT c.id FROM rag_chunks c JOIN rag_documents d ON d.id=c.doc_id WHERE d.material_id=? ORDER BY c.chunk_index',(mid,))]
            else:
                mid=put('materials',dict(user_id=uid,subject_id=sid,title=title,file_path=str(path),file_type='md',page_count=1,parse_status='完成'))
                did=put('rag_documents',dict(source_type='upload',material_id=mid,title=title))
                sections=[dict(text=explanation,title='核心觀念',locator='示範講義：核心觀念'),dict(text=example+'\n'+pitfall,title='示例與誤解',locator='示範講義：示例與誤解'),dict(text=tf[0]+' '+tf[1]+' '+tf[2]+'\n'+fill[0]+' '+fill[1]+' '+fill[2],title='自我檢核',locator='示範講義：自我檢核')]
                chunk_ids=[]
                for index,chunk in enumerate(chunk_sections(sections)):
                    chunk_id=put('rag_chunks',dict(doc_id=did,chunk_index=index,content=chunk['text'],token_count=len(chunk['text'])//2,chapter_id=cid))
                    put('rag_chunk_meta',dict(chunk_id=chunk_id,source_locator=chunk['locator'],section_title=chunk['title']))
                    chunk_ids.append(chunk_id)
            manifest['materials'].append(dict(id=mid,title=title,file=str(path),chunk_ids=chunk_ids))
            questions=[dict(q_type='單選',content=q,options=dict(zip('ABCD',options)),answer_key=answer,explanation=why,difficulty=1) for q,options,answer,why in mc]
            questions += [dict(q_type='是非',content=tf[0],options={},answer_key=tf[1],explanation=tf[2],difficulty=1),dict(q_type='填空',content=fill[0],options={},answer_key=fill[1],explanation=fill[2],difficulty=1)]
            for item in questions:
                item,pairs=validate(item,item['options'])
                item['options']=dict(pairs)
                row=db().execute('SELECT id FROM questions WHERE chapter_id=? AND content=?',(cid,item['content'])).fetchone()
                qid=row['id'] if row else put('questions',dict(chapter_id=cid,q_type=item['q_type'],content=item['content'],answer_key=item['answer_key'],explanation=item['explanation'],difficulty=1,source='demo_fixed'))
                for index,(label,text) in enumerate(item['options'].items(),1):
                    if not db().execute('SELECT id FROM question_options WHERE question_id=? AND option_label=?',(qid,label)).fetchone():
                        put('question_options',dict(question_id=qid,option_label=label,option_text=text,order_no=index))
                if not db().execute('SELECT 1 FROM question_concepts WHERE question_id=? AND concept_id=?',(qid,concept_id)).fetchone():
                    put('question_concepts',dict(question_id=qid,concept_id=concept_id,weight=1))
                if not db().execute('SELECT 1 FROM question_metadata WHERE question_id=?',(qid,)).fetchone():
                    put('question_metadata',dict(question_id=qid,source_type='demo_fixed',generation_model='原創示範資料；非模型生成',evidence_chunk_ids=json.dumps(chunk_ids),concepts_json=json.dumps([chapter],ensure_ascii=False),skill='辨識與應用',is_verified=0))
                if not db().execute('SELECT id FROM source_question_items WHERE user_id=? AND subject_id=? AND raw_question=?',(uid,sid,item['content'])).fetchone():
                    put('source_question_items',dict(user_id=uid,subject_id=sid,chapter_id=cid,source_file=path.name,raw_question=item['content'],q_type=item['q_type'],answer_key=item['answer_key'],explanation=item['explanation'],options_json=json.dumps(item['options'],ensure_ascii=False),concept_id=concept_id,skill='辨識與應用',cognitive_level='understand',difficulty=1,classification_confidence=0))
                fixed_export.append([subject_title,chapter,item['q_type'],item['content'],item['answer_key'],item['explanation'],1,*[item['options'].get(k,'') for k in 'ABCD']])
            # A real usable manual lesson, clearly distinguished from generated AI lessons.
            course_title='示範微課程｜'+chapter
            row=db().execute('SELECT id FROM micro_courses WHERE user_id=? AND concept_id=? AND title=?',(uid,concept_id,course_title)).fetchone()
            if not row:
                course_id=put('micro_courses',dict(user_id=uid,subject_id=sid,concept_id=concept_id,title=course_title,objective='理解核心觀念並完成客觀檢核',reason='手工編排的示範入門課程，非依虛構弱項生成。',estimated_minutes=8,status='active',generation_model='原創人工示範；未呼叫 LLM',evidence_chunk_ids=json.dumps(chunk_ids),weakness_snapshot=json.dumps(dict(mastery=None,status='未測驗'),ensure_ascii=False)))
                for index,(kind,name,text,question,answer,why) in enumerate([
                    ('teach','觀念說明',explanation,None,None,None),('example','閱讀示例',example+'\n'+pitfall,None,None,None),
                    ('check','觀念檢核','請回答是或否。',tf[0],tf[1],tf[2]),('summary','課程回顧','複習核心觀念，接著練習本章固定題。',None,None,None)],1):
                    put('micro_course_steps',dict(course_id=course_id,step_no=index,step_type=kind,title=name,content=text,question=question,answer_key=answer,explanation=why,status='planned'))
            draft=questions[0]
            draft_title='【示範待審核】'+draft['content']
            if not db().execute('SELECT id FROM ai_question_drafts WHERE user_id=? AND subject_id=? AND content=?',(uid,sid,draft_title)).fetchone():
                put('ai_question_drafts',dict(user_id=uid,subject_id=sid,chapter_id=cid,q_type=draft['q_type'],content=draft_title,options_json=json.dumps(draft['options'],ensure_ascii=False),answer_key=draft['answer_key'],explanation=draft['explanation'],evidence_chunk_ids=json.dumps(chunk_ids),concepts_json=json.dumps([chapter],ensure_ascii=False),skill='辨識與應用',difficulty=1,status='draft',model_name='人工示範審核資料；非 AI 生成'))
        db().commit()
        # Reuse the deterministic planner, never the AI lesson/generation services.
        from personal_ai.coaching import create_learning_goal_plan
        from TYE.exam_module import create_quiz
        for sid,chapter_ids in subject_chapters.items():
            name=next(k for k,v in manifest['subjects'].items() if v==sid)
            goal_name=name+'｜28 天入門計畫'
            row=db().execute('SELECT id FROM learning_goals WHERE user_id=? AND subject_id=? AND goal_name=?',(uid,sid,goal_name)).fetchone()
            goal_id=row['id'] if row else create_learning_goal_plan(uid,sid,goal_name,date.today()+timedelta(days=28),chapter_ids,20,30,'beginner')
            manifest['goal_ids'].append(goal_id)
            row=db().execute("SELECT id FROM quiz_sessions WHERE user_id=? AND subject_id=? AND finished_at IS NULL AND mode='練習' ORDER BY id LIMIT 1",(uid,sid)).fetchone()
            quiz_id=row['id'] if row else create_quiz(sid,8,'練習',chapter_ids,['單選','是非','填空'],True,'bank_random')
            manifest['quiz_ids'].append(quiz_id)
        with (output/'全部固定題庫.csv').open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.writer(file);writer.writerow(['subject_name','chapter_name','q_type','content','answer_key','explanation','difficulty','option_A','option_B','option_C','option_D']);writer.writerows(fixed_export)
        export_subject_files(fixed_export,output)
        manifest['new_rows']=counts
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(account=username,new_rows=counts,subjects=manifest['subjects'],goals=manifest['goal_ids'],unanswered_quizzes=manifest['quiz_ids'],output=str(output)),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--username',default='admin123')
    seed(parser.parse_args().username)
