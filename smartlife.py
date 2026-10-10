import csv
import calendar
import io
import json
import math
import os
import secrets
import time
import sqlite3
import zipfile
from xml.etree.ElementTree import ParseError
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for, Response
from werkzeug.security import generate_password_hash

from auth import auth, login_required
from records import CATALOG, PROFILE_FIELDS, options, ownership
from subject_management import render_subject_workspace, validate_chapter, register_subject_management
from storage import db, init_storage, register_storage, read_only, locked_sql, StorageIntegrityError, DatabaseUnavailable


def create_app(test_config=None):
    root = Path(__file__).parent
    load_dotenv(root / '.env')
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.getenv('DATABASE', str(root/'instance'/'personal_ai_dev.db')),
        APP_MODE=os.getenv('APP_MODE','dev').lower(),
        DB_TYPE=os.getenv('DB_TYPE','mariadb').lower(),
        DB_HOST=os.getenv('DB_HOST','127.0.0.1'),
        DB_PORT=int(os.getenv('DB_PORT','3306')),
        DB_USER=os.getenv('DB_USER',''),
        DB_PASSWORD=os.getenv('DB_PASSWORD',''),
        DB_NAME=os.getenv('DB_NAME',''),
        DB_CHARSET=os.getenv('DB_CHARSET','utf8mb4'),
        DB_READ_ONLY=os.getenv('DB_READ_ONLY','false').lower()=='true',
        DB_STANDBY_ENABLED=os.getenv('DB_STANDBY_ENABLED','false').lower()=='true',
        DB_STANDBY_PATH=os.getenv('DB_STANDBY_PATH',str(root/'instance'/'backups'/'standby.sqlite')),
        # Groq handles all LLM roles; CPU specialists handle exam retrieval.
        # Local LLM fallback is disabled to avoid GPU inference.
        GROQ_API_KEY=os.getenv('GROQ_API_KEY',''),
        EXAM_MODULAR_AI=os.getenv('EXAM_MODULAR_AI','false'),
        EXAM_GENERATION_MODE=os.getenv('EXAM_GENERATION_MODE','hybrid'),
        LLM_PROVIDER=os.getenv('LLM_PROVIDER','groq'),
        LLM_BASE_URL=os.getenv('LLM_BASE_URL','https://api.groq.com/openai/v1'),
        LLM_API_KEY=os.getenv('LLM_API_KEY',''),
        LLM_MODEL=os.getenv('LLM_MODEL','openai/gpt-oss-20b'),
        EMBEDDING_PROVIDER=os.getenv('EMBEDDING_PROVIDER','cpu'),
        EMBEDDING_BASE_URL=os.getenv('EMBEDDING_BASE_URL','http://127.0.0.1:11434'),
        EMBEDDING_API_KEY=os.getenv('EMBEDDING_API_KEY',''),
        EMBEDDING_MODEL=os.getenv('EMBEDDING_MODEL','intfloat/multilingual-e5-small'),
        CLASSIFIER_PROVIDER=os.getenv('CLASSIFIER_PROVIDER','groq'),
        CLASSIFIER_BASE_URL=os.getenv('CLASSIFIER_BASE_URL','https://api.groq.com/openai/v1'),
        CLASSIFIER_API_KEY=os.getenv('CLASSIFIER_API_KEY',''),
        CLASSIFIER_MODEL=os.getenv('CLASSIFIER_MODEL','openai/gpt-oss-20b'),
        PARSER_PROVIDER=os.getenv('PARSER_PROVIDER','groq'),
        PARSER_BASE_URL=os.getenv('PARSER_BASE_URL','https://api.groq.com/openai/v1'),
        PARSER_API_KEY=os.getenv('PARSER_API_KEY',''),
        PARSER_MODEL=os.getenv('PARSER_MODEL','openai/gpt-oss-20b'),
        GENERATOR_PROVIDER=os.getenv('GENERATOR_PROVIDER','groq'),
        GENERATOR_BASE_URL=os.getenv('GENERATOR_BASE_URL','https://api.groq.com/openai/v1'),
        GENERATOR_API_KEY=os.getenv('GENERATOR_API_KEY',''),
        GENERATOR_MODEL=os.getenv('GENERATOR_MODEL','openai/gpt-oss-20b'),
        GENERATOR_FALLBACK_PROVIDER=os.getenv('GENERATOR_FALLBACK_PROVIDER',''),
        GENERATOR_FALLBACK_BASE_URL=os.getenv('GENERATOR_FALLBACK_BASE_URL',''),
        GENERATOR_FALLBACK_API_KEY=os.getenv('GENERATOR_FALLBACK_API_KEY',''),
        GENERATOR_FALLBACK_MODEL=os.getenv('GENERATOR_FALLBACK_MODEL',''),
        REVIEWER_PROVIDER=os.getenv('REVIEWER_PROVIDER','groq'),
        REVIEWER_BASE_URL=os.getenv('REVIEWER_BASE_URL','https://api.groq.com/openai/v1'),
        REVIEWER_API_KEY=os.getenv('REVIEWER_API_KEY',''),
        REVIEWER_MODEL=os.getenv('REVIEWER_MODEL','openai/gpt-oss-20b'),
        REVIEWER_FALLBACK_PROVIDER=os.getenv('REVIEWER_FALLBACK_PROVIDER',''),
        REVIEWER_FALLBACK_BASE_URL=os.getenv('REVIEWER_FALLBACK_BASE_URL',''),
        REVIEWER_FALLBACK_API_KEY=os.getenv('REVIEWER_FALLBACK_API_KEY',''),
        REVIEWER_FALLBACK_MODEL=os.getenv('REVIEWER_FALLBACK_MODEL',''),
        COURSE_PROVIDER=os.getenv('COURSE_PROVIDER','groq'),
        COURSE_BASE_URL=os.getenv('COURSE_BASE_URL','https://api.groq.com/openai/v1'),
        COURSE_API_KEY=os.getenv('COURSE_API_KEY',''),
        COURSE_MODEL=os.getenv('COURSE_MODEL','openai/gpt-oss-20b'),
        COURSE_FALLBACK_PROVIDER=os.getenv('COURSE_FALLBACK_PROVIDER',''),
        COURSE_FALLBACK_BASE_URL=os.getenv('COURSE_FALLBACK_BASE_URL',''),
        COURSE_FALLBACK_API_KEY=os.getenv('COURSE_FALLBACK_API_KEY',''),
        COURSE_FALLBACK_MODEL=os.getenv('COURSE_FALLBACK_MODEL',''),
        TUTOR_PROVIDER=os.getenv('TUTOR_PROVIDER','groq'),
        TUTOR_BASE_URL=os.getenv('TUTOR_BASE_URL','https://api.groq.com/openai/v1'),
        TUTOR_API_KEY=os.getenv('TUTOR_API_KEY',''),
        TUTOR_MODEL=os.getenv('TUTOR_MODEL','openai/gpt-oss-20b'),
        TUTOR_FALLBACK_PROVIDER=os.getenv('TUTOR_FALLBACK_PROVIDER',''),
        TUTOR_FALLBACK_BASE_URL=os.getenv('TUTOR_FALLBACK_BASE_URL',''),
        TUTOR_FALLBACK_API_KEY=os.getenv('TUTOR_FALLBACK_API_KEY',''),
        TUTOR_FALLBACK_MODEL=os.getenv('TUTOR_FALLBACK_MODEL',''),
        VOICE_ENABLED=os.getenv('VOICE_ENABLED','false').lower()=='true',
        STT_PROVIDER=os.getenv('STT_PROVIDER','faster_whisper'),
        STT_MODEL=os.getenv('STT_MODEL','large-v3'),
        TTS_PROVIDER=os.getenv('TTS_PROVIDER','kokoro'),
        TTS_MODEL=os.getenv('TTS_MODEL','hexgrad/Kokoro-82M-v1.1-zh'),
        TTS_LANGUAGE=os.getenv('TTS_LANGUAGE','z'),
        SECRET_KEY=os.getenv('SECRET_KEY',''),
        MAX_CONTENT_LENGTH=5*1024*1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE')=='true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    for key in ('SMTP_HOST','SMTP_PORT','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM_EMAIL'):
        app.config[key] = os.getenv(key,'')
    app.config['SMTP_FROM_NAME'] = os.getenv('SMTP_FROM_NAME','考試智伴')
    app.config['SMTP_SECURITY'] = os.getenv('SMTP_SECURITY','starttls')
    if test_config:
        app.config.update(test_config)
        if 'DATABASE' in test_config and 'DB_TYPE' not in test_config:
            app.config['DB_TYPE'] = 'sqlite'
        if test_config.get('TESTING'):
            for role in ('LLM','CLASSIFIER','PARSER','GENERATOR','REVIEWER','COURSE','TUTOR'):
                app.config[role+'_PROVIDER']=test_config.get(role+'_PROVIDER','mock')
            app.config['EXAM_MODULAR_AI']=test_config.get('EXAM_MODULAR_AI','false')
            app.config['EMBEDDING_PROVIDER']=test_config.get('EMBEDDING_PROVIDER','mock')
    if not app.config['SECRET_KEY']:
        secret_file = root/'instance'/'session.key'
        secret_file.parent.mkdir(exist_ok=True)
        try:
            with secret_file.open('x', encoding='utf-8') as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_file.read_text(encoding='utf-8').strip()
    app.config['DUMMY_PASSWORD_HASH'] = generate_password_hash(secrets.token_hex(16))
    # Team integration uses teammate MariaDB by default.
    # SQLite remains available only as a lightweight test fallback.
    register_storage(app)
    if not app.config['DB_READ_ONLY'] and (app.config['DB_TYPE'] == 'sqlite' or os.getenv('AUTO_INIT_DB','false').lower() == 'true'):
        init_storage(app)
    app.register_blueprint(auth)

    @app.before_request
    def security():
        g.request_started = time.perf_counter()
        # Static files must never trigger a database lookup. CSS/JS/image requests
        # do not need user hydration and should remain fast.
        if request.endpoint == 'static':
            return None

        g.user = None
        if session.get('user_id'):
            user = db().execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
            if user and user['is_email_verified'] and session.get('password_changed_at') == user['password_changed_at']:
                g.user = user
            else:
                session.clear()
        if request.method == 'POST':
            db()
        if request.method == 'POST' and read_only() and request.endpoint not in ('auth.login','auth.logout'):
            abort(503, '目前使用唯讀備援，新增、交卷與 AI 工作暫停。請等待主資料庫恢復。')
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token','')
        if request.method == 'POST' and not secrets.compare_digest(token, session['csrf_token']):
            if request.path == '/send-verification' or request.path.startswith('/body/api/') :
                return jsonify(ok=False,message='頁面已過期，請重新整理後再試。'),400
            abort(400, '頁面已過期，請重新整理後再試。')

    @app.after_request
    def headers(response):
        elapsed = (time.perf_counter() - getattr(g, 'request_started', time.perf_counter())) * 1000
        response.headers['Server-Timing'] = f"app;dur={elapsed:.1f}, dbconnect;dur={getattr(g, 'db_connect_ms', 0):.1f}"
        if elapsed > 2000 and request.endpoint != 'static':
            app.logger.warning('Slow page endpoint=%s duration_ms=%.0f db_connect_ms=%.0f',
                               request.endpoint, elapsed, getattr(g, 'db_connect_ms', 0))
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'self'"
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def common():
        return dict(catalog=CATALOG, csrf_token=session.get('csrf_token',''), today=date.today().isoformat(), database_read_only=read_only(), database_snapshot_at=getattr(g,'db_snapshot_at',None))

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(503)
    def error_page(error):
        message = '檔案不可超過 5 MB。' if error.code==413 else ('找不到此資料，或您沒有存取權限。' if error.code==404 else str(error.description))
        return render_template('error.html',title='無法完成操作',message=message), error.code

    @app.get('/')
    def index():
        return redirect(url_for('dashboard' if g.user else 'auth.login'))

    @app.errorhandler(DatabaseUnavailable)
    def database_unavailable(error):
        return render_template('error.html',title='資料庫暫時無法連線',message=str(error)),503

    @app.get('/dashboard')
    @login_required
    def dashboard():
        pass # Statistics are updated after writes; viewing the dashboard never rewrites history.
        count_row = db().execute(
            "SELECT (SELECT count(*) FROM subjects WHERE created_by=?) AS subjects, "
            "(SELECT count(*) FROM quiz_sessions WHERE user_id=? AND finished_at IS NOT NULL) AS exams, "
            "(SELECT count(*) FROM wrong_answers WHERE user_id=? AND status='待複習') AS wrong",
            (g.user['id'], g.user['id'], g.user['id'])).fetchone()
        counts = [count_row['subjects'], count_row['exams'], count_row['wrong']]
        daily = db().execute('SELECT * FROM daily_summary WHERE user_id=? ORDER BY summary_date DESC LIMIT 14',(g.user['id'],)).fetchall()
        now = date.today()
        try:
            month = date.fromisoformat(request.args.get('month', now.strftime('%Y-%m')) + '-01')
        except (ValueError, TypeError):
            month = now.replace(day=1)
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        selected_goal = request.args.get('goal_id', type=int)
        schedule_goals = {}
        events = {}
        all_plans = db().execute(
            'SELECT p.*, '
            '(SELECT wt.minutes_per_session FROM workout_templates wt WHERE wt.user_id=p.user_id AND wt.is_active=1 '
            'ORDER BY wt.created_at DESC,wt.id DESC LIMIT 1) AS template_minutes, '
            '(SELECT up.minutes_per_session FROM user_profiles up WHERE up.user_id=p.user_id LIMIT 1) AS profile_minutes '
            'FROM study_plans p WHERE p.user_id=? AND (p.plan_date BETWEEN ? AND ? OR p.plan_date=?) ORDER BY p.plan_date,p.id',
            (g.user['id'], month.isoformat(), month_end.isoformat(), now.isoformat())).fetchall()
        def plan_event(plan):
            unit = str(plan['target_unit'] or '')
            value = plan['target_value'] or 0
            minutes = float(value) if unit.strip().lower() in ('分鐘', '分', 'minute', 'minutes', 'min') else 0
            if unit.strip().lower() in ('小時', '時', 'hour', 'hours', 'hr', 'h'):
                minutes = float(value) * 60
            elif unit.strip().lower() in ('秒', '秒鐘', 'second', 'seconds', 'sec', 's'):
                minutes = float(value) / 60
            time_source = '本項安排'
            if minutes <= 0 and plan['plan_type'] == 'workout':
                if plan['template_minutes']:
                    minutes = float(plan['template_minutes'])
                    time_source = '採用中的運動課表：每次預計'
                elif plan['profile_minutes']:
                    minutes = float(plan['profile_minutes'])
                    time_source = '個人設定：每次運動預計'
            return dict(title=plan['title'], kind=plan['plan_type'], status=plan['status'],
                        source='plan', minutes=minutes, time_source=time_source,
                        duration_label=f'{minutes:g} 分鐘' if minutes > 0 else '未設定時長',
                        target_label=f'{value} {unit}'.strip(),
                        url=url_for('records', table='study_plans', edit=plan['id']))

        def task_event(task):
            minutes = int(task['target_minutes'] or 0)
            kind = 'rest' if task['task_type'] in ('休息', '輕量學習') else ('workout' if task['task_type']=='運動建議' else 'study')
            return dict(title=task['title'], kind=kind, status=task['status'],
                        source='task', goal_id=task['goal_id'], goal_name=task['goal_name'], task_id=task['id'], task_type=task['task_type'],
                        question_count=int(task['question_count'] or 0), minutes=minutes,
                        duration_label=f'{minutes} 分鐘' if minutes > 0 else ('休息日，不安排必修' if kind=='rest' else '未設定時長'),
                        url=url_for('personal_ai.adaptive_planner', goal_id=task['goal_id'], month=str(task['task_date'])[:7]))
        for plan in all_plans:
            if selected_goal and plan['plan_type'] != 'workout':
                continue
            if not month.isoformat() <= str(plan['plan_date'])[:10] <= month_end.isoformat():
                continue
            events.setdefault(str(plan['plan_date'])[:10], []).append(plan_event(plan))
        tasks = []
        if 'personal_ai' in app.blueprints:
            tasks = db().execute(
                'SELECT lt.id,lt.goal_id,lt.task_date,lt.title,lt.status,lt.task_type,lt.target_minutes,lt.question_count,lg.goal_name '
                'FROM learning_tasks lt JOIN learning_goals lg ON lg.id=lt.goal_id AND lg.user_id=lt.user_id '
                'WHERE lt.user_id=? AND (lt.task_date BETWEEN ? AND ? OR lt.task_date=?) ORDER BY lt.task_date,lt.id',
                (g.user['id'], month.isoformat(), month_end.isoformat(), now.isoformat())).fetchall()
            schedule_goals = {int(t['goal_id']): t['goal_name'] for t in tasks}
            if selected_goal:
                tasks = [t for t in tasks if int(t['goal_id']) == selected_goal]
            for task in tasks:
                if not month.isoformat() <= str(task['task_date'])[:10] <= month_end.isoformat():
                    continue
                events.setdefault(str(task['task_date'])[:10], []).append(task_event(task))
        today_tasks = [p for p in all_plans if str(p['plan_date'])[:10] == now.isoformat()
                       and (not selected_goal or p['plan_type'] == 'workout')]
        today_events = [plan_event(p) for p in today_tasks]
        if 'personal_ai' in app.blueprints:
            for t in tasks:
                if str(t['task_date'])[:10] != now.isoformat():
                    continue
                today_events.append(task_event(t))
        return render_template('dashboard_live.html',title='學習與健康總覽',counts=counts,daily=daily,
            calendar_month=month, calendar_weeks=calendar.Calendar().monthdatescalendar(month.year,month.month),
            calendar_events=events, calendar_today=now, today_events=today_events,
            schedule_goals=schedule_goals, selected_goal=selected_goal,
            previous_month=(month-timedelta(days=1)).strftime('%Y-%m'),
            next_month=(month_end+timedelta(days=1)).strftime('%Y-%m'))

    @app.route('/profile',methods=['GET','POST'])
    @login_required
    def profile():
        row = db().execute('SELECT * FROM user_profiles WHERE user_id=?',(g.user['id'],)).fetchone()
        values = dict(row) if row else {}
        error = None
        if request.method=='POST':
            values = request.form
            try:
                data = parse_fields(PROFILE_FIELDS)
                if data['birth_date'] > date.today().isoformat():
                    raise ValueError('生日不可晚於今天。')
                columns = ','.join(data)
                existing_profile = db().execute('SELECT 1 FROM user_profiles WHERE user_id=?',(g.user['id'],)).fetchone()
                if existing_profile:
                    db().execute(
                        f'UPDATE user_profiles SET '+','.join(k+'=?' for k in data)+',onboarded_at=CURRENT_TIMESTAMP WHERE user_id=?',
                        (*data.values(), g.user['id'])
                    )
                else:
                    db().execute(
                        f'INSERT INTO user_profiles (user_id,{columns},onboarded_at) VALUES (?,{",".join("?" for _ in data)},CURRENT_TIMESTAMP)',
                        (g.user['id'],*data.values())
                    )
                initial_weight = request.form.get('initial_weight','').strip()
                if initial_weight:
                    weight = float(initial_weight)
                    if not math.isfinite(weight) or not 1<=weight<=600:
                        raise ValueError('體重須介於 1–600 kg。')
                    metric = db().execute('SELECT id FROM body_metrics WHERE user_id=? AND record_date=?',(g.user['id'],date.today().isoformat())).fetchone()
                    if metric:
                        db().execute('UPDATE body_metrics SET weight_kg=? WHERE id=?',(weight,metric['id']))
                    else:
                        db().execute('INSERT INTO body_metrics (user_id,record_date,weight_kg) VALUES (?,?,?)',(g.user['id'],date.today().isoformat(),weight))
                db().commit()
                flash('個人資料已儲存。','success')
                return redirect(url_for('dashboard'))
            except (ValueError,sqlite3.IntegrityError,StorageIntegrityError) as exc:
                db().rollback()
                error = str(exc) if isinstance(exc,ValueError) else '資料格式錯誤，請重新檢查。'
        return render_template('profile.html',title='個人資料與目標',fields=PROFILE_FIELDS,values=values,error=error,choices={})

    @app.route('/records/<table>',methods=['GET','POST'])
    @login_required
    def records(table):
        if table not in CATALOG:
            abort(404)
        title, icon, fields = CATALOG[table]
        error = None
        values = {}
        edit_id = request.args.get('edit',type=int)
        if edit_id:
            values = dict(owned(table,edit_id))
        if request.method=='POST':
            values = request.form
            try:
                record_id = request.form.get('id',type=int)
                if record_id:
                    owned(table,record_id)
                data = parse_fields(fields)
                if table=='subjects':
                    duplicate=db().execute('SELECT id FROM subjects WHERE created_by=? AND LOWER(TRIM(subject_name))=LOWER(?) AND id<>?',
                                           (g.user['id'],data['subject_name'],record_id or 0)).fetchone()
                    if duplicate:
                        raise ValueError('已有同名科目，請直接選擇該科目管理章節。')
                if table == 'chapters':
                    validate_chapter(data, record_id)
                if table == 'questions':
                    # Freeze questions used in exams; changing answers would corrupt history.
                    if record_id and db().execute('SELECT 1 FROM quiz_answers WHERE question_id=?',(record_id,)).fetchone():
                        raise ValueError('此題已有作答紀錄，請新增另一題以保留歷史版本。')
                    data, question_options = validate_question(data,request.form)
                if table == 'workouts':
                    start,end = datetime.fromisoformat(data['started_at']),datetime.fromisoformat(data['ended_at'])
                    if end<=start or start.date().isoformat()!=data['workout_date'] or (end-start).total_seconds()>86400:
                        raise ValueError('訓練開始日期須符合訓練日，結束須晚於開始且時長不超過 24 小時。')
                    data['duration_min'] = int((end-start).total_seconds()/60)
                if table=='template_items':
                    template=owned('workout_templates',data['template_id'])
                    if data['day_index']>template['days_per_week']:
                        raise ValueError('訓練日不可超過課表的一週天數。')
                if table=='workout_templates':
                    if record_id and db().execute('SELECT 1 FROM template_items WHERE template_id=? AND day_index>?',(record_id,data['days_per_week'])).fetchone():
                        raise ValueError('請先調整超過新天數的課表項目。')
                    if data['is_active']=='1':
                        db().execute('UPDATE workout_templates SET is_active=0 WHERE user_id=?',(g.user['id'],))
                if table=='chat_messages':
                    data['role']='user'
                if record_id:
                    db().execute(f'UPDATE {table} SET '+','.join(k+'=?' for k in data)+' WHERE id=?',(*data.values(),record_id))
                else:
                    if table in ('subjects','exercises'):
                        data['created_by']=g.user['id']
                    elif table not in ('chapters','questions','workout_sets','template_items','chat_messages'):
                        data['user_id']=g.user['id']
                    record_id = insert(table,data)
                if table=='questions':
                    db().execute('DELETE FROM question_options WHERE question_id=?',(record_id,))
                    for label,text in question_options:
                        insert('question_options',dict(question_id=record_id,option_label=label,option_text=text,order_no=ord(label)))
                refresh_stats(commit=False)
                db().commit()
                flash('資料已儲存。','success')
                if table in ('subjects','chapters'):
                    return redirect(url_for('records',table='subjects',subject_id=record_id if table=='subjects' else data['subject_id']))
                if table=='questions' and request.args.get('chapter_id',type=int):
                    return redirect(url_for('records',table=table,chapter_id=data['chapter_id']))
                return redirect(url_for('records',table=table))
            except (ValueError,sqlite3.IntegrityError,StorageIntegrityError) as exc:
                db().rollback()
                error = str(exc) if isinstance(exc,ValueError) else '資料重複或關聯不正確；同一天的體重請編輯原紀錄。'
        if table in ('subjects','chapters'):
            return render_subject_workspace(table, values, error, edit_id)
        if table == 'questions':
            # Keep the manual/fixed question-bank screen clean.  Concept source
            # examples live in Concept Bank, while concept_dynamic rows are per-quiz
            # history snapshots and must not look like reusable fixed questions.
            chapter_filter=request.args.get('chapter_id',type=int)
            if chapter_filter:
                filtered_chapter=owned('chapters',chapter_filter)
                title='固定題庫 · '+filtered_chapter['chapter_name']
                if not values:
                    values={'chapter_id':chapter_filter}
            rows = db().execute(
                "SELECT * FROM questions WHERE " + ownership(table) +
                " AND COALESCE(source,'manual') <> 'concept_dynamic'" +
                (' AND chapter_id=?' if chapter_filter else '') + ' ORDER BY id DESC',
                (g.user['id'],chapter_filter) if chapter_filter else (g.user['id'],),
            ).fetchall()
        else:
            rows = db().execute(f'SELECT * FROM {table} WHERE {ownership(table)} ORDER BY id DESC',(g.user['id'],)).fetchall()
        choices = {field.name:options(db(),field.ref,g.user['id']) for field in fields if field.ref}
        option_values = {}
        if table=='questions' and edit_id:
            option_values = {'option_'+r['option_label']:r['option_text'] for r in db().execute('SELECT * FROM question_options WHERE question_id=?',(edit_id,))}
        return render_template('records.html',title=title,table=table,fields=fields,rows=rows,choices=choices,values=values,error=error,edit_id=edit_id,option_values=option_values)

    @app.post('/records/<table>/<int:record_id>/delete')
    @login_required
    def delete_record(table,record_id):
        if table not in CATALOG:
            abort(404)
        deleted_record=owned(table,record_id)
        try:
            if table=='chapters':
                for plan_table in ('exam_plans','learning_goals'):
                    for plan in db().execute(f'SELECT chapter_ids FROM {plan_table} WHERE subject_id=?',(deleted_record['subject_id'],)):
                        if str(record_id) in {str(value) for value in json.loads(plan['chapter_ids'] or '[]')}:
                            raise ValueError('此章節已被學習或考試計畫選用，請先調整該計畫。')
            if table=='questions':
                db().execute('DELETE FROM question_options WHERE question_id=?',(record_id,))
            db().execute(f'DELETE FROM {table} WHERE id=?',(record_id,))
            refresh_stats(commit=False)
            db().commit()
            flash('資料已刪除。','success')
        except (ValueError,sqlite3.IntegrityError,StorageIntegrityError) as exc:
            db().rollback()
            flash(str(exc) if isinstance(exc,ValueError) else '此資料仍被其他紀錄使用，請先處理相關資料；已有作答的題目會保留。','error')
        if table in ('subjects','chapters'):
            return redirect(url_for('records',table='subjects',**({'subject_id':deleted_record['subject_id']} if table=='chapters' else {})))
        if table=='questions' and request.args.get('chapter_id',type=int):
            return redirect(url_for('records',table=table,chapter_id=deleted_record['chapter_id']))
        return redirect(url_for('records',table=table))

    @app.get('/workspace/<page>')
    @login_required
    def workspace(page):
        mapping={'overview':'dashboard','mock':'quiz_start','results':'results','analysis':'analysis','sources':'imports','wellness':'body.index'}
        if page=='review':
            return redirect(url_for('records',table='summaries'))
        if page not in mapping:
            abort(404)
        return redirect(url_for(mapping[page]))

    for old, endpoint in [('data-visualization','analysis'),('maps','quiz_start'),('manage-users','profile'),('preferences','profile')]:
        app.add_url_rule('/'+old,old,login_required(lambda target=endpoint: redirect(url_for(target))))

    register_subject_management(app)
    register_learning(app)
    return app


def insert(table,data):
    return db().execute(f'INSERT INTO {table} ({",".join(data)}) VALUES ({",".join("?" for _ in data)})',tuple(data.values())).lastrowid


def owned(table,record_id):
    row=db().execute(f'SELECT * FROM {table} WHERE id=? AND {ownership(table)}',(record_id,g.user['id'])).fetchone()
    if not row:
        abort(404)
    return row


def parse_fields(fields):
    data={}
    for field in fields:
        value=request.form.get(field.name,'').strip()
        if not value:
            if field.required:
                raise ValueError('請填寫：'+field.label)
            data[field.name]=None
            continue
        if field.kind in ('number','decimal','ref'):
            try:
                value=float(value) if field.kind=='decimal' else int(value)
            except ValueError:
                raise ValueError(field.label+' 必須是有效數字。')
            if field.ref:
                owned(field.ref,value)
            elif not math.isfinite(value) or not field.minimum<=value<=field.maximum:
                raise ValueError(f'{field.label} 須介於 {field.minimum}–{field.maximum}。')
        elif field.kind=='select':
            if value not in field.choices:
                raise ValueError(field.label+' 選項無效。')
        elif field.kind in ('date','datetime-local'):
            try:
                parsed=date.fromisoformat(value) if field.kind=='date' else datetime.fromisoformat(value)
                if field.kind=='datetime-local' and parsed.tzinfo is not None:
                    raise ValueError()
                value=parsed.isoformat()
            except ValueError:
                raise ValueError(field.label+' 日期或時間無效。')
        elif len(value)>field.limit:
            raise ValueError(f'{field.label} 不可超過 {field.limit} 字。')
        data[field.name]=value
    return data


def validate_question(data,form):
    from personal_ai.question_validation import validate
    return validate(data,{k:form.get('option_'+k,'') for k in 'ABCD'})


def refresh_stats(commit=True):
    if read_only():
        return
    uid=g.user['id']
    db().execute(locked_sql('SELECT id FROM users WHERE id=?'),(uid,)).fetchone()
    db().execute("UPDATE study_plans SET status='missed' WHERE user_id=? AND status='planned' AND plan_date<?",(uid,date.today().isoformat()))
    db().execute('UPDATE workouts SET total_volume=COALESCE((SELECT sum(weight_kg*reps) FROM workout_sets WHERE workout_id=workouts.id),0) WHERE user_id=?',(uid,))
    daily={}
    for r in db().execute('SELECT substr(a.answered_at,1,10) day,count(*) n,sum(a.is_correct) c FROM quiz_answers a JOIN quiz_sessions s ON s.id=a.session_id WHERE s.user_id=? AND s.finished_at IS NOT NULL GROUP BY day',(uid,)):
        daily[r['day']]={'answered_count':r['n'],'accuracy':round(r['c']/r['n']*100,2)}
    for r in db().execute('SELECT workout_date,sum(total_volume) volume FROM workouts WHERE user_id=? GROUP BY workout_date',(uid,)):
        daily.setdefault(r['workout_date'],{})['workout_volume']=r['volume']
    db().execute('DELETE FROM daily_summary WHERE user_id=?',(uid,))
    for day,data in daily.items():
        groups=[r[0] for r in db().execute('SELECT DISTINCT e.muscle_group FROM workout_sets s JOIN workouts w ON w.id=s.workout_id JOIN exercises e ON e.id=s.exercise_id WHERE w.user_id=? AND w.workout_date=?',(uid,day))]
        insert('daily_summary',dict(user_id=uid,summary_date=day,trained_groups=json.dumps(groups,ensure_ascii=False),**data))
    if commit:
        db().commit()


def register_learning(app):
    @app.get('/materials')
    @login_required
    def materials():
        return redirect(url_for('personal_ai.knowledge'))

    @app.get('/imports/template')
    @login_required
    def import_template():
        output=io.StringIO()
        writer=csv.writer(output)
        writer.writerow(['chapter_name','q_type','content','answer_key','explanation','difficulty','option_A','option_B','option_C','option_D'])
        writer.writerow(['範例章節','單選','下列何者是關聯式資料庫？','A','SQLite 是關聯式資料庫。',1,'SQLite','HTML','',''])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=questions-template.csv'})

    @app.post('/imports/subjects')
    @login_required
    def import_create_subject():
        try:
            # Same validation and ownership as the subject management screen.
            data=parse_fields(CATALOG['subjects'][2])
            db().execute(locked_sql('SELECT id FROM users WHERE id=?'),(g.user['id'],)).fetchone()
            existing=db().execute('SELECT id,subject_name FROM subjects WHERE created_by=? AND LOWER(TRIM(subject_name))=LOWER(?)',
                                  (g.user['id'],data['subject_name'])).fetchone()
            if existing:
                db().commit()
                return jsonify(ok=True,created=False,subject=dict(existing),message='已有同名科目，已選取現有科目。')
            sid=insert('subjects',dict(data,created_by=g.user['id']))
            db().commit()
            return jsonify(ok=True,created=True,subject=dict(id=sid,subject_name=data['subject_name']),message='科目已建立，可直接繼續匯入。'),201
        except (ValueError,sqlite3.IntegrityError,StorageIntegrityError) as exc:
            db().rollback()
            return jsonify(ok=False,message=str(exc) if isinstance(exc,ValueError) else '無法建立科目，請重新檢查名稱。'),400

    @app.route('/imports',methods=['GET','POST'])
    @login_required
    def imports():
        error=None
        if request.method=='POST':
            try:
                from personal_ai.question_importer import extract_questions

                from personal_ai.jobs import submit
                subject_id=int(request.form.get('subject_id','0')); owned('subjects',subject_id)
                upload=request.files.get('file')
                if request.form.get('source_mode')=='text':
                    raw=request.form.get('question_text','').encode('utf-8')
                    filename='文字題庫.'+request.form.get('text_format','txt')
                else:
                    if not upload or not upload.filename: raise ValueError('請選擇檔案。')
                    raw=upload.read(); filename=Path(upload.filename).name
                if not raw or len(raw)>5*1024*1024: raise ValueError('檔案需為 1 byte–5 MB。')
                folder=Path(app.instance_path)/'job_uploads'; folder.mkdir(parents=True,exist_ok=True)
                path=folder/(secrets.token_hex(16)+Path(filename).suffix.lower()); path.write_bytes(raw)
                try:
                    form=list(request.form.items(multi=True))
                    form=[(k,v) for k,v in form if k not in ('source_mode','question_text','csrf_token')]
                    job_id=submit(app,g.user['id'],'import',dict(path=str(path),filename=filename,form=form))
                except Exception:
                    path.unlink(missing_ok=True); raise
                return redirect(url_for('personal_ai.job_page',job_id=job_id))
            except (ValueError,RuntimeError,UnicodeError,zipfile.BadZipFile,StopIteration,KeyError,TypeError,OverflowError,ParseError) as exc:
                db().rollback()
                error=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else '無法讀取檔案，請確認檔案內容與格式。'

        batches=db().execute('SELECT * FROM exam_imports WHERE user_id=? ORDER BY id DESC',(g.user['id'],)).fetchall()
        return render_template('imports.html',title='題庫文件匯入',subjects=options(db(),'subjects',g.user['id']),batches=batches,error=error)

    @app.route('/imports/<int:batch>',methods=['GET','POST'])
    @login_required
    def import_review(batch):
        record=owned('exam_imports',batch)
        if request.method=='POST':
            db().execute('BEGIN IMMEDIATE')
            record=db().execute(locked_sql('SELECT * FROM exam_imports WHERE id=? AND user_id=?'),(batch,g.user['id'])).fetchone()
            if not record: abort(404)
            if record['status']=='待確認':
                owned('subjects',record['subject_id'])
                rows=db().execute('SELECT * FROM import_items WHERE import_id=?',(batch,)).fetchall()
                concept_mode=bool(rows and json.loads(rows[0]['parsed_json']).get('_import_strategy')=='concept')
                concept_ids=set()
                db().execute(locked_sql('SELECT id FROM subjects WHERE id=?'),(record['subject_id'],)).fetchone()
                added_count=0
                for row in rows:
                    item=json.loads(row['parsed_json'])
                    chapter=db().execute('SELECT id FROM chapters WHERE subject_id=? AND chapter_name=?',(record['subject_id'],item['chapter_name'])).fetchone()
                    cid=chapter['id'] if chapter else insert('chapters',dict(subject_id=record['subject_id'],chapter_name=item['chapter_name']))
                    data={k:item.get(k,'') for k in ('q_type','content','answer_key','explanation','difficulty')}
                    data,opts=validate_question(data,item)
                    if item.get('_import_strategy')=='concept':
                        concept_id=item.get('_concept_id')
                        concept=None
                        if concept_id:
                            concept=db().execute('SELECT * FROM concepts WHERE id=? AND subject_id=?',(concept_id,record['subject_id'])).fetchone()
                        if not concept:
                            cname=(item.get('_concept_name') or '待人工命名概念').strip()[:255]
                            concept=db().execute('SELECT * FROM concepts WHERE subject_id=? AND lower(name)=lower(?)',(record['subject_id'],cname)).fetchone()
                            if not concept:
                                concept_id=insert('concepts',dict(subject_id=record['subject_id'],chapter_id=cid,name=cname,description=(item.get('_concept_description') or '')[:1200],importance=3))
                            else:
                                concept_id=concept['id']
                        else:
                            concept_id=concept['id']
                        concept_ids.add(int(concept_id))
                        options_json=json.dumps({label:text for label,text in opts},ensure_ascii=False)
                        duplicate=db().execute('SELECT id FROM source_question_items WHERE user_id=? AND subject_id=? AND chapter_id=? AND raw_question=? AND q_type=? AND answer_key=? AND options_json=?',
                            (g.user['id'],record['subject_id'],cid,data['content'],data['q_type'],data['answer_key'],options_json)).fetchone()
                        if duplicate:
                            db().execute('UPDATE import_items SET chapter_id=?,question_id=NULL,is_confirmed=1 WHERE id=?',(cid,row['id']))
                            continue
                        insert('source_question_items',dict(
                            user_id=g.user['id'],subject_id=record['subject_id'],chapter_id=cid,import_id=batch,import_item_id=row['id'],
                            source_file=record['file_name'],raw_question=data['content'],q_type=data['q_type'],answer_key=data['answer_key'],
                            explanation=data.get('explanation',''),options_json=options_json,concept_id=concept_id,
                            skill=(item.get('_skill') or '')[:255],cognitive_level=(item.get('_cognitive_level') or '')[:32],
                            difficulty=data.get('difficulty',2),classification_confidence=float(item.get('_concept_confidence') or 0)
                        ))
                        db().execute('UPDATE import_items SET chapter_id=?,question_id=NULL,is_confirmed=1 WHERE id=?',(cid,row['id']))
                    else:
                        candidates=db().execute("SELECT id FROM questions WHERE chapter_id=? AND content=? AND q_type=? AND answer_key=? AND source='import'",(cid,data['content'],data['q_type'],data['answer_key'])).fetchall()
                        duplicate=None
                        for candidate in candidates:
                            old=[(o['option_label'],o['option_text']) for o in db().execute('SELECT option_label,option_text FROM question_options WHERE question_id=? ORDER BY option_label',(candidate['id'],))]
                            if old==sorted(opts): duplicate=candidate['id']; break
                        if duplicate:
                            db().execute('UPDATE import_items SET chapter_id=?,question_id=?,is_confirmed=1 WHERE id=?',(cid,duplicate,row['id']))
                            continue
                        qid=insert('questions',dict(chapter_id=cid,source='import',**data))
                        for label,text in opts:
                            insert('question_options',dict(question_id=qid,option_label=label,option_text=text,order_no=ord(label)))
                        db().execute('UPDATE import_items SET chapter_id=?,question_id=?,is_confirmed=1 WHERE id=?',(cid,qid,row['id']))
                    added_count+=1
                if concept_mode:
                    db().execute("UPDATE exam_imports SET status='已歸類',imported_count=? WHERE id=?",(added_count,batch))
                else:
                    db().execute("UPDATE exam_imports SET status='已匯入',imported_count=? WHERE id=?",(added_count,batch))
            db().commit()
            flash('已確認：概念型匯入會保留來源樣本但不加入固定考題池；傳統模式則已加入題庫。','success')
            return redirect(url_for('imports'))
        items=[dict(json.loads(r['parsed_json']),_item_id=r['id']) for r in db().execute('SELECT * FROM import_items WHERE import_id=?',(batch,))]
        return render_template('import_review.html',title='確認匯入題目',batch=record,items=items)

    @app.post('/imports/<int:batch>/items/<int:item_id>')
    @login_required
    def revise_import(batch,item_id):
        from personal_ai.import_review import revise
        try:
            revise(batch,item_id,request.form)
            flash('題目已修正。','success')
        except (ValueError,TypeError) as exc:
            db().rollback(); flash(str(exc),'error')
        return redirect(url_for('import_review',batch=batch))

    @app.post('/imports/<int:batch>/cancel')
    @login_required
    def cancel_import(batch):
        record=owned('exam_imports',batch)
        if record['status']=='待確認':
            db().execute("UPDATE exam_imports SET status='已取消' WHERE id=?",(batch,)); db().commit()
        return redirect(url_for('imports'))


def process_import_file(app,form,upload):
    from personal_ai.question_importer import extract_questions
    subject_id=int(form.get('subject_id','0'))
    owned('subjects',subject_id)
    upload=upload
    if form.get('source_mode') == 'text':
        from werkzeug.datastructures import FileStorage
        text = form.get('question_text', '').strip()
        if not text:
            raise ValueError('請先貼上或編輯題庫文字。')
        text_format = form.get('text_format', 'txt')
        if text_format not in ('txt', 'csv'):
            raise ValueError('文字格式設定不正確。')
        upload = FileStorage(stream=io.BytesIO(text.encode('utf-8')),
                             filename='文字題庫.' + text_format)
    if not upload or not upload.filename:
        raise ValueError('請選擇題庫檔案。')

    suffix=Path(upload.filename).suffix.lower()
    allowed={'.pdf','.docx','.xlsx','.xlsm','.csv','.txt','.md'}
    if suffix not in allowed:
        raise ValueError('支援 PDF、DOCX、XLSX/XLSM、CSV、TXT、MD。')

    raw=upload.read()
    if not raw:
        raise ValueError('檔案內容為空。')
    if len(raw)>5*1024*1024:
        raise ValueError('題庫檔案上限 5 MB。')

    folder=Path(app.instance_path)/'imports'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(secrets.token_hex(16)+suffix)
    path.write_bytes(raw)
    g.import_pending_path = path

    rows=None
    parser_name=''
    # CSV / Excel with the legacy template remain the most deterministic path.
    if suffix=='.csv':
        try:
            candidate=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            headers=set(candidate[0].keys()) if candidate else set()
            if {'chapter_name','content','answer_key'}<=headers:
                rows=candidate
                parser_name='結構化 CSV'
        except (UnicodeError,csv.Error):
            rows=None
    elif suffix in ('.xlsx','.xlsm'):
        from openpyxl import load_workbook
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(z.file_size for z in archive.infolist())>50*1024*1024:
                raise ValueError('Excel 解壓後過大，請拆分檔案。')
        book=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
        try:
            iterator=book.active.iter_rows(values_only=True)
            keys=next(iterator,None)
            if keys:
                keys=[str(k).strip() if k is not None else '' for k in keys]
                if {'chapter_name','content','answer_key'}<=set(keys):
                    rows=[]
                    for line in iterator:
                        if any(v is not None for v in line):
                            rows.append(dict(zip(keys,line)))
                    parser_name='結構化 Excel'
        finally:
            book.close()

    default_chapter=(form.get('default_chapter') or '').strip()
    if not default_chapter:
        default_chapter=(Path(upload.filename).stem[:90]+' 自動匯入')[:120]
    parse_mode=(form.get('parse_mode') or 'auto').strip().lower()
    if parse_mode not in {'auto','rules','llm'}:
        parse_mode='auto'

    if rows is None:
        rows,parser_name=extract_questions(path,default_chapter,app.config,parse_mode)

    if not rows:
        raise ValueError('沒有判讀到可匯入的完整考題。若是 PDF，可能是掃描檔或文字層編碼異常；請先 OCR 為可讀文字，或改用 CSV／文字題庫。')

    clean=[]
    for i,row in enumerate(rows,1):
        item={str(k):str(v).strip() if v is not None else '' for k,v in row.items() if not str(k).startswith('_')}
        if not item.get('chapter_name'):
            item['chapter_name']=default_chapter
        if not item.get('content') or not item.get('answer_key'):
            raise ValueError(f'第 {i} 題缺少題目或答案。')
        if len(item['chapter_name'])>120 or len(item['content'])>20000 or len(item['answer_key'])>50 or len(item.get('explanation',''))>20000:
            raise ValueError(f'第 {i} 題文字過長。')
        if item.get('q_type') not in ('單選','多選','是非','填空'):
            raise ValueError(f'第 {i} 題題型無效：{item.get("q_type") or "未辨識"}。')
        try:
            item['difficulty']=int(item.get('difficulty') or '2')
        except (TypeError,ValueError):
            item['difficulty']=2
        if not 1<=item['difficulty']<=5:
            item['difficulty']=2
        item,_=validate_question(item,item)
        if row.get('_question_no') is not None:
            item['_question_no']=row['_question_no']
        if row.get('_answer_source')=='ai_inferred':
            item['_answer_source']='ai_inferred'
            item['_answer_model']=str(row.get('_answer_model') or '')[:120]
        clean.append(item)

    import_strategy=(form.get('import_strategy') or 'concept').strip().lower()
    if import_strategy not in {'concept','question_bank'}:
        import_strategy='concept'
    classifier_name='未使用'
    from personal_ai import import_checkpoints as checkpoints
    checkpoints.put('total',max(len(clean),checkpoints.get('total',0)))
    checkpoints.put('questions',clean)
    checkpoints.put('stage','題目與答案已完成，準備概念分類' if import_strategy=='concept' else '準備建立匯入預覽')
    if import_strategy=='concept':
        from personal_ai.concept_classifier import classify_question_batch, attach_classifications
        classifications,classifier_name=classify_question_batch(clean,subject_id,app.config)
        clean=attach_classifications(clean,classifications,'concept')
    else:
        for item in clean:
            item['_import_strategy']='question_bank'

    failures=checkpoints.get('answer_failures',[])
    warning=('；待補資料題號：'+ '、'.join(str(x['number']) for x in failures)) if failures else ''
    batch=insert('exam_imports',dict(
        user_id=g.user['id'],subject_id=subject_id,
        file_name=Path(upload.filename).name[:255],file_path=str(path),
        file_type=suffix[1:],status='待確認',total_rows=len(clean),
        error_log=(f'解析器：{parser_name}；概念分類：{classifier_name}'+warning)[:1000]))
    for item in clean:
        encoded=json.dumps(item,ensure_ascii=False)
        insert('import_items',dict(import_id=batch,raw_content=encoded,parsed_json=encoded))
    checkpoints.put('final_batch_id',batch)
    db().commit()
    checkpoints.put('questions',clean)
    checkpoints.put('stage',f'已完成 {len(clean)} 題分析與預覽；{len(failures)} 題待補資料' if failures else '完整預覽已建立')
    return batch
