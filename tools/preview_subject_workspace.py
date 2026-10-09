"""Local-only UI fixture with throwaway DB. Never uses production accounts/data."""
import tempfile
from pathlib import Path
from flask import session, request, abort
from app import create_app
from storage import db


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='subject-ui-') as temporary:
        app=create_app(dict(TESTING=True,SECRET_KEY='local-ui-fixture-only',DB_TYPE='sqlite',
            DATABASE=str(Path(temporary)/'preview.db'),DB_READ_ONLY=False))
        app.instance_path=temporary
        with app.app_context():
            con=db()
            con.execute("INSERT INTO users(id,username,email,password_hash,is_email_verified) VALUES(1,'preview','preview@example.invalid','unused',1)")
            for sid,name in [(1,'會考數學'),(2,'會考英文'),(3,'Python 程式設計')]:
                con.execute('INSERT INTO subjects(id,subject_name,created_by) VALUES(?,?,1)',(sid,name))
            for cid,sid,parent,name in [(1,1,None,'代數與函數'),(2,1,1,'變數與數值'),(3,1,1,'一元一次方程式'),
                                      (4,1,None,'幾何與測量'),(5,1,4,'平面圖形'),(6,1,4,'立體圖形'),(7,2,None,'動詞與時態')]:
                con.execute('INSERT INTO chapters(id,subject_id,parent_chapter_id,chapter_name,order_no) VALUES(?,?,?,?,?)',(cid,sid,parent,name,cid))
            con.commit()
        def fixture_session():
            if request.remote_addr not in ('127.0.0.1','::1'): abort(403)
            session['user_id']=1
            session['password_changed_at']=None
        app.before_request_funcs.setdefault(None,[]).insert(0,fixture_session)
        app.run(host='127.0.0.1',port=8765,debug=False,use_reloader=False)
