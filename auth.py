import hashlib
import hmac
import secrets
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from functools import wraps

from email_validator import validate_email, EmailNotValidError
from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from storage import db

auth = Blueprint('auth', __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        return view(*args, **kwargs)
    return wrapped


def normalized_email(value):
    try:
        return validate_email(value.strip(), check_deliverability=False, allow_smtputf8=False).normalized.lower()
    except EmailNotValidError:
        raise ValueError('請輸入有效的電子信箱。')


def valid_credential(value, minimum, maximum):
    # English ASCII letters, digits and symbols; no spaces/control characters.
    return minimum <= len(value) <= maximum and all(33 <= ord(c) <= 126 for c in value)


def code_hash(email, code):
    return hmac.new(current_app.secret_key.encode(), (email+':'+code).encode(), hashlib.sha256).hexdigest()


def limited(bucket, maximum, seconds):
    now = int(time.time())
    connection = db()
    connection.execute('BEGIN IMMEDIATE')
    row = connection.execute('SELECT * FROM rate_limits WHERE bucket=?', (bucket,)).fetchone()
    if row and now-row['started_at'] < seconds and row['count'] >= maximum:
        connection.rollback()
        return True
    if not row or now-row['started_at'] >= seconds:
        connection.execute('INSERT OR REPLACE INTO rate_limits VALUES (?,1,?)', (bucket,now))
    else:
        connection.execute('UPDATE rate_limits SET count=count+1 WHERE bucket=?', (bucket,))
    connection.commit()
    return False


def send_code(email, code):
    config = current_app.config
    if not all(config.get(k) for k in ('SMTP_HOST','SMTP_PORT','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM_EMAIL')):
        raise ValueError('無法發送：管理員尚未設定寄信信箱與 SMTP 金鑰。')
    try:
        port = int(config['SMTP_PORT'])
        sender = normalized_email(config['SMTP_FROM_EMAIL'])
        if config['SMTP_SECURITY'] not in ('ssl','starttls'):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('無法發送：SMTP 連接埠、寄件信箱或加密設定有誤。')
    message = EmailMessage()
    message['Subject'] = '考試智伴｜註冊驗證碼'
    from email.utils import formataddr
    message['From'] = formataddr((config['SMTP_FROM_NAME'], sender))
    message['To'] = email
    message.set_content(f'您的註冊驗證碼為：{code}\n\n有效時間為 30 分鐘，請勿將驗證碼交給他人。\n若您未申請註冊，請忽略此信。')
    context = ssl.create_default_context()
    if config['SMTP_SECURITY'] == 'ssl':
        client = smtplib.SMTP_SSL(config['SMTP_HOST'], port, timeout=15, context=context)
    else:
        client = smtplib.SMTP(config['SMTP_HOST'], port, timeout=15)
    with client:
        if config['SMTP_SECURITY'] == 'starttls':
            client.starttls(context=context)
        client.login(config['SMTP_USERNAME'], config['SMTP_PASSWORD'])
        refused = client.send_message(message)
        if refused:
            raise smtplib.SMTPException('recipient refused')


@auth.post('/send-verification')
def send_verification():
    try:
        email = normalized_email(request.form.get('email',''))
    except ValueError as exc:
        return jsonify(ok=False, message=str(exc)), 400
    if limited('mail-ip:'+request.remote_addr, 10, 3600) or limited('mail:'+email, 5, 3600):
        return jsonify(ok=False,message='發送次數過多，請一小時後再試。'), 429
    connection = db()
    now = int(time.time())
    code = f'{secrets.randbelow(1000000):06d}'
    digest = code_hash(email, code)
    connection.execute('BEGIN IMMEDIATE')
    if connection.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
        connection.rollback()
        return jsonify(ok=False,message='此信箱已註冊，請前往登入。'), 409
    old = connection.execute('SELECT * FROM registration_codes WHERE email=?',(email,)).fetchone()
    if old and now-old['sent_at'] < 60:
        connection.rollback()
        return jsonify(ok=False,message='請等待 60 秒後再重新發送。'), 429
    connection.execute('INSERT OR REPLACE INTO registration_codes (email,code_hash,expires_at,sent_at,state,request_ip) VALUES (?,?,?,?,?,?)', (email,digest,now+1800,now,'sending',request.remote_addr))
    connection.commit()
    try:
        send_code(email,code)
    except (ValueError, smtplib.SMTPException, OSError) as exc:
        connection.execute("UPDATE registration_codes SET state='failed' WHERE email=? AND code_hash=?",(email,digest))
        connection.commit()
        message = str(exc) if isinstance(exc,ValueError) else '驗證信發送失敗，請確認信箱或稍後再試；管理員請檢查 SMTP 設定。'
        return jsonify(ok=False,message=message), 503
    connection.execute("UPDATE registration_codes SET state='sent', expires_at=? WHERE email=? AND code_hash=?",(int(time.time())+1800,email,digest))
    connection.commit()
    return jsonify(ok=True,message='驗證信已送出，驗證碼 30 分鐘內有效。重寄後請使用最新一封。',retry_after=60)


@auth.route('/register', methods=['GET','POST'])
def register():
    error = None
    if request.method == 'POST':
        try:
            if limited('register:'+request.remote_addr,30,900):
                raise ValueError('嘗試次數過多，請 15 分鐘後再試。')
            username = request.form.get('username','')
            password = request.form.get('password','')
            email = normalized_email(request.form.get('email',''))
            code = request.form.get('code','').strip()
            if not valid_credential(username,6,80):
                raise ValueError('帳號須為 6–80 字元，可使用英文、數字及符號，不含空白。')
            if not valid_credential(password,8,128):
                raise ValueError('密碼須為 8–128 字元，可使用英文、數字及符號，不含空白。')
            password_hash = generate_password_hash(password)
            connection = db()
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM registration_codes WHERE email=?',(email,)).fetchone()
            if not row or row['state'] != 'sent' or row['used_at'] or row['expires_at'] <= int(time.time()):
                raise ValueError('驗證碼不存在、已失效或超過 30 分鐘，請重新發送。')
            if row['attempts'] >= 5:
                raise ValueError('驗證碼錯誤已達 5 次，請重新發送。')
            if not hmac.compare_digest(row['code_hash'],code_hash(email,code)):
                connection.execute('UPDATE registration_codes SET attempts=attempts+1 WHERE email=?',(email,))
                connection.commit()
                raise ValueError('驗證碼不正確，請查看最新一封驗證信。')
            connection.execute('INSERT INTO users (username,email,password_hash,is_email_verified,email_verified_at,password_changed_at) VALUES (?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',(username,email,password_hash))
            connection.execute('UPDATE registration_codes SET used_at=?,state=? WHERE email=?',(int(time.time()),'used',email))
            connection.commit()
            flash('註冊成功，信箱已驗證，請登入。','success')
            return redirect(url_for('auth.login'))
        except sqlite3.IntegrityError:
            db().rollback()
            error = '帳號或電子信箱已被使用。'
        except ValueError as exc:
            db().rollback()
            error = str(exc)
    return render_template('auth.html',register=True,error=error), 400 if error else 200


@auth.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username','')
        password = request.form.get('password','')
        bucket = hashlib.sha256(username.encode()).hexdigest()
        if limited('login-ip:'+request.remote_addr,40,900) or limited('login-user:'+bucket,10,900):
            error = '登入嘗試過多，請 15 分鐘後再試。'
        else:
            user = db().execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            stored = user['password_hash'] if user else current_app.config['DUMMY_PASSWORD_HASH']
            valid = len(password) <= 128 and check_password_hash(stored,password)
            if not user or not valid or not user['is_email_verified']:
                error = '帳號或密碼不正確，或信箱尚未完成驗證。'
            else:
                session.clear()
                session['user_id'] = user['id']
                session['password_changed_at'] = user['password_changed_at']
                session.permanent = True
                db().execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?',(user['id'],))
                db().commit()
                profile = db().execute('SELECT onboarded_at FROM user_profiles WHERE user_id=?',(user['id'],)).fetchone()
                return redirect(url_for('dashboard' if profile and profile['onboarded_at'] else 'profile'))
    return render_template('auth.html',register=False,error=error), 400 if error else 200


@auth.post('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
