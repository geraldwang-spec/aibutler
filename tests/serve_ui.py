"""Isolated browser smoke server; never touches instance/smartlife.db."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartlife import create_app
from storage import db
from werkzeug.security import generate_password_hash

with tempfile.TemporaryDirectory() as folder:
    app=create_app({'DATABASE':str(Path(folder)/'ui.db'),'SECRET_KEY':'ui-test-only',
                    'SMTP_HOST':'','SMTP_PORT':'','SMTP_USERNAME':'','SMTP_PASSWORD':'','SMTP_FROM_EMAIL':''})
    with app.app_context():
        db().execute("INSERT INTO users(username,email,password_hash,is_email_verified,password_changed_at) VALUES (?,?,?,1,CURRENT_TIMESTAMP)",('tester01','tester@example.com',generate_password_hash('Testing!123')))
        db().commit()
    app.run(port=5057,debug=False,use_reloader=False)
