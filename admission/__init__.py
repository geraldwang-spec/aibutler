"""學測落點分析：依歷年個人申請一階篩選結果推估可通過的校系。"""
import json

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from auth import login_required
from .placement import TIERS, coverage, parse_scores, place, SUBJECTS

bp = Blueprint('admission', __name__, template_folder='templates')
FORM_FIELDS = (*SUBJECTS, '英聽', 'gender', 'special')


def _form(source):
    return {key: source.get(key, '') for key in FORM_FIELDS if source.get(key, '')}


def _job_result(job_id, kind):
    from personal_ai.jobs import read
    job = read(current_app, job_id, g.user['id'])
    if not job or job['kind'] != kind or job['status'] != 'completed' or not job['result']:
        return None
    return job


def _advice(job_id, fields):
    job = _job_result(job_id, 'admission_advice')
    # 網址上的級分被改過時，舊的解讀已不適用
    if not job or json.loads(job['payload'] or '{}') != fields:
        return None
    return json.loads(job['result']).get('advice')


def _interest(job_id):
    # 推薦科系只看興趣；各校分級在顯示時依目前級分重算，不必比對級分
    job = _job_result(job_id, 'admission_interest')
    return json.loads(job['result']).get('interest') if job else None


@bp.get('/admission')
@login_required
def placement():
    from .interest import MAX_INTEREST, attach_schools
    result, error, advice, interest = None, None, None, None
    fields = _form(request.args)
    # 表單送出時一定帶科目欄位；只帶 interest 的網址代表只看興趣推薦
    if any(subject in request.args for subject in SUBJECTS):
        try:
            scores, listening, gender = parse_scores(request.args)
            result = place(scores, listening, gender, include_special=request.args.get('special') == '1')
        except ValueError as exc:
            error = str(exc)
    if result and request.args.get('advice'):
        advice = _advice(request.args['advice'], fields)
    if request.args.get('interest'):
        interest = _interest(request.args['interest'])
        if interest:
            interest = attach_schools(interest, result)
    schools, years = coverage()
    return render_template('admission/placement.html', title='學測落點分析', subjects=SUBJECTS,
                           tiers=TIERS, form=request.args, fields=fields, schools=schools,
                           years=sorted(years), result=result, error=error, advice=advice,
                           interest=interest, interest_id=request.args.get('interest', '') if interest else '',
                           max_interest=MAX_INTEREST)


def _submit(kind, payload, back):
    from personal_ai.jobs import submit
    try:
        job_id = submit(current_app._get_current_object(), g.user['id'], kind, payload)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admission.placement', **back))
    return redirect(url_for('personal_ai.job_page', job_id=job_id))


@bp.post('/admission/advice')
@login_required
def request_advice():
    form = _form(request.form)
    try:
        parse_scores(form)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admission.placement', **form))
    return _submit('admission_advice', form, form)


@bp.post('/admission/interest')
@login_required
def request_interest():
    from .interest import parse_interest
    form = _form(request.form)
    try:
        interest = parse_interest(request.form)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admission.placement', **form))
    return _submit('admission_interest', dict(form, interest=interest), form)


def register_admission(app):
    app.register_blueprint(bp)
