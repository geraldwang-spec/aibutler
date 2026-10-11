"""Render static layout previews only. No app, database, API or model imports."""
import calendar
import shutil
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment,FileSystemLoader,select_autoescape

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'instance'/'ui_preview'
OUT.mkdir(parents=True,exist_ok=True)
for name in ('css','js','fonts'):
    source=ROOT/'static'/name
    if source.is_dir(): shutil.copytree(source,OUT/'static'/name,dirs_exist_ok=True)
env=Environment(loader=FileSystemLoader([str(ROOT/'templates'),str(ROOT/'personal_ai/templates')]),autoescape=select_autoescape())
links={'dashboard':'index.html','personal_ai.knowledge':'knowledge.html','personal_ai.micro_courses':'courses.html','personal_ai.chat_index':'chat.html','personal_ai.chat_page':'chat.html'}
def url_for(endpoint,**kwargs):
    return '/static/'+kwargs['filename'] if endpoint=='static' else '/'+links.get(endpoint,'index.html')
env.globals.update(url_for=url_for,get_flashed_messages=lambda **kwargs:[])
now=date.today();month=now.replace(day=1)
subjects=[dict(id=1,subject_name='Python 程式設計'),dict(id=2,subject_name='SQL 資料庫'),dict(id=3,subject_name='網路與資安')]
base=dict(g=SimpleNamespace(user=SimpleNamespace(username='admin123')),csrf_token='',catalog={},error=None,database_read_only=False,subjects=subjects)
events={}
for offset in range(28):
    day=month+timedelta(days=offset)
    events[day.isoformat()]=[dict(title=label,kind='study',status='planned',url='/courses.html') for label in ['Python：變數與型別','SQL：查詢與篩選','資安：HTTP 與 API']]
dashboard=dict(title='學習總覽',counts=[5,3,0],calendar_month=month,calendar_weeks=calendar.Calendar().monthdatescalendar(month.year,month.month),calendar_today=now,calendar_events=events,previous_month=(month-timedelta(days=1)).strftime('%Y-%m'),next_month=(month+timedelta(days=32)).strftime('%Y-%m'),today_events=events.get(now.isoformat(),[]),daily=[])
materials=[dict(id=i+1,title=title,subject_name=subjects[i//3]['subject_name'],file_type='md',chunk_count=3,parse_status='完成') for i,title in enumerate(['變數與資料型別','條件與迴圈','函式與串列','查詢與篩選','主鍵外鍵與 JOIN','聚合與交易','IP、DNS 與連線','HTTP 與 API','帳號防護與備份'])]
courses=[dict(id=i+1,title=m['title'],subject_name=m['subject_name'],concept_name=m['title'],estimated_minutes=8,status='active',reason='從觀念、範例到檢核，一步步建立理解。') for i,m in enumerate(materials)]
chat=SimpleNamespace(id=1,title='一起讀懂 Python')
for filename,template,endpoint,data in [
    ('index.html','dashboard_live.html','dashboard',dashboard),
    ('knowledge.html','knowledge.html','personal_ai.knowledge',dict(title='教材與講義',materials=materials,chapters=[])),
    ('courses.html','micro_courses.html','personal_ai.micro_courses',dict(title='我的課程',courses=courses,weakness=[],subject_id=None)),
    ('chat.html','chat.html','personal_ai.chat_page',dict(title='AI 對話',chat=chat,chats=[chat],messages=[]))]:
    request=SimpleNamespace(endpoint=endpoint,path='/preview',view_args={},form={})
    html=env.get_template(template).render(**dict(base,request=request,**data))
    (OUT/filename).write_text(html,encoding='utf-8')
print('靜態排版預覽已產生：',OUT)
