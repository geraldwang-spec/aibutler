"""Allowlisted forms and ownership rules for the SmartLife schema."""
from dataclasses import dataclass


@dataclass
class Field:
    name: str
    label: str
    kind: str = 'text'
    required: bool = True
    choices: tuple = ()
    ref: str = ''
    minimum: float = 0
    maximum: float = 10000
    limit: int = 200


def f(name, label, kind='text', **kw):
    return Field(name, label, kind, **kw)


def choice(name, label, *values):
    return f(name, label, 'select', choices=values)


def ref(name, label, table, required=True):
    return f(name, label, 'ref', ref=table, required=required)


# Table names and SQL fragments only originate here, never in request data.
CATALOG = {
 'subjects': ('科目管理', 'book', [f('subject_name','科目名稱',limit=80)]),
 'chapters': ('章節管理', 'list', [ref('subject_id','科目','subjects'), f('chapter_name','章節名稱',limit=120), f('order_no','排序','number',maximum=999)]),
 'questions': ('我的題庫', 'question-circle', [ref('chapter_id','章節','chapters'), choice('q_type','題型','單選','多選','是非','填空'), f('content','題目','textarea',limit=10000), f('answer_key','正確答案（選項代號 / 是、否 / 填空文字）',limit=50), f('explanation','解析','textarea',required=False,limit=10000), f('difficulty','難度 1–5','number',minimum=1,maximum=5)]),
 'summaries': ('重點摘要與筆記', 'file-text-o', [ref('chapter_id','章節','chapters'), choice('summary_type','類型','overview','card'), f('title','標題',limit=120), f('content','手動筆記內容','textarea',limit=20000), choice('mastery','熟練度','未讀','複習中','已熟')]),
 'exam_plans': ('考試準備設定', 'calendar', [ref('subject_id','科目','subjects'), f('exam_date','考試日期','date'), f('weekday_minutes','平日每日讀書分鐘','number',maximum=1440), f('weekend_minutes','週末每日讀書分鐘','number',maximum=1440), f('review_days','考前複習天數','number',maximum=90), choice('status','狀態','進行中','已完成','已放棄')]),
 'study_plans': ('讀書與運動計畫', 'calendar-check-o', [f('plan_date','日期','date'), choice('plan_type','類型','study','workout'), f('title','任務名稱',limit=120), ref('chapter_id','相關章節','chapters',False), f('target_value','目標量','number',minimum=1), f('target_unit','單位（分鐘、題、組）',limit=20), choice('status','狀態','planned','done','missed')]),
 'body_metrics': ('體重與體脂紀錄', 'heartbeat', [f('record_date','量測日期','date'), f('weight_kg','體重 kg','decimal',minimum=1,maximum=600), f('body_fat_pct','體脂率 %','decimal',required=False,maximum=100)]),
 'exercises': ('運動動作庫', 'bolt', [f('exercise_name','動作名稱',limit=80), choice('muscle_group','部位','胸','背','腿','肩','手臂','核心'), f('equipment','器材',limit=50), choice('is_cardio','是否有氧','0','1')]),
 'workouts': ('訓練紀錄', 'heart-o', [f('workout_date','訓練日期','date'), f('started_at','開始時間','datetime-local'), f('ended_at','結束時間','datetime-local'), f('note','備註','textarea',required=False,limit=255)]),
 'workout_sets': ('逐組運動紀錄', 'list-ol', [ref('workout_id','訓練日','workouts'), ref('exercise_id','動作','exercises'), f('set_no','第幾組','number',minimum=1,maximum=100), f('weight_kg','重量 kg','decimal',maximum=1000), f('reps','次數','number',maximum=10000), f('duration_sec','有氧秒數','number',required=False,maximum=86400), f('distance_km','距離 km','decimal',required=False,maximum=1000), f('rpe','主觀強度 1–10','number',required=False,minimum=1,maximum=10)]),
 'workout_templates': ('運動課表', 'th-list', [choice('split_type','課表樣板','全身','推拉腿','上下肢分化'), f('days_per_week','一週訓練天數','number',minimum=1,maximum=7), f('minutes_per_session','每次分鐘','number',minimum=1,maximum=1440), choice('equipment_scope','器材範圍','健身房','家用啞鈴','徒手'), choice('is_active','採用中','1','0')]),
 'template_items': ('課表動作項目', 'tasks', [ref('template_id','課表','workout_templates'), f('day_index','第幾個訓練日','number',minimum=1,maximum=7), choice('muscle_group','部位','胸','背','腿','肩','手臂','核心'), ref('exercise_id','動作','exercises'), f('order_no','排序','number',maximum=100), f('target_sets','組數','number',minimum=1,maximum=100), f('target_reps','次數','number',minimum=1,maximum=1000), f('suggested_weight_kg','預定重量 kg','decimal',required=False,maximum=1000)]),
 'chat_sessions': ('問答記事（AI 待串接）', 'comments-o', [f('title','對話主題',limit=120)]),
 'chat_messages': ('我的提問紀錄', 'comment-o', [ref('chat_id','對話主題','chat_sessions'), f('content','提問內容（目前只儲存，不產生 AI 回答）','textarea',limit=10000), choice('intent','主題','learning','diet','workout','rag')]),
}

PROFILE_FIELDS = [choice('gender','性別','m','f','other'), f('birth_date','生日','date'), f('height_cm','身高 cm','decimal',minimum=30,maximum=260), choice('activity_level','日常活動量','低','中','高'), choice('goal_type','運動目標','減脂','增肌','維持','體能'), f('workout_days_per_week','一週可運動天數','number',maximum=7), f('minutes_per_session','每次運動分鐘','number',minimum=1,maximum=1440)]

OWNER = {
 'subjects': 'created_by=?', 'exercises': 'created_by=?',
 'chapters': 'subject_id IN (SELECT id FROM subjects WHERE created_by=?)',
 'questions': 'chapter_id IN (SELECT c.id FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE s.created_by=?)',
 'workout_sets': 'workout_id IN (SELECT id FROM workouts WHERE user_id=?)',
 'template_items': 'template_id IN (SELECT id FROM workout_templates WHERE user_id=?)',
 'chat_messages': 'chat_id IN (SELECT id FROM chat_sessions WHERE user_id=?)',
}


def ownership(table):
    return OWNER.get(table, 'user_id=?')


def options(db, table, user_id):
    field = CATALOG[table][2][0].name
    if table == 'chapters':
        return [(r['id'], r['subject_name']+' / '+r['chapter_name']) for r in db.execute('SELECT c.*,s.subject_name FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE s.created_by=? ORDER BY c.order_no,c.id', (user_id,))]
    if table == 'workouts':
        field = 'workout_date'
    return [(r['id'], str(r[field])+' (#'+str(r['id'])+')') for r in db.execute(f'SELECT * FROM {table} WHERE {ownership(table)} ORDER BY id DESC', (user_id,))]
