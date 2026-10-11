# -*- coding: utf-8 -*-
"""財務小幫手的網址（只負責 HTTP；驗證與統計在 service.py，SQL 在 sql_process.py）。

  GET       /financial/                 收支紀錄總覽：今日／本週／本月／今年、本月支出分類、最近紀錄
  GET/POST  /financial/income           收入：列表＋新增（分類固定為「收入」）
  GET/POST  /financial/expense          支出：列表＋新增（未手動選分類時由 AI 判斷食衣住行育樂）
  POST      /financial/<id>/delete      刪除自己的一筆紀錄
CSRF 與唯讀模式由 smartlife.py 的 before_request 統一檢查。
"""
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth import login_required

from . import sql_process as sql
from .classifier import classify_expense
from .service import (CATEGORY_LABELS, EXPENSE, EXPENSE_CATEGORIES, INCOME, FormError,
                      category_breakdown, parse_form, periods, query_range, summarize)

financial = Blueprint('financial', __name__, url_prefix='/financial')


@financial.app_template_filter('money')
def money(value):
    """金額千分位：1234 → 1,234。"""
    return f'{int(value or 0):,}'


def _stats(today):
    rows = sql.rows_between(g.user['id'], *query_range(today))
    return rows, summarize(rows, today)


@financial.get('/')
@login_required
def overview():
    today = date.today()
    rows, summary = _stats(today)
    month_start, month_end = periods(today)['month']
    return render_template('financial/overview.html', title='收支紀錄', summary=summary,
                           breakdown=category_breakdown(rows, month_start, month_end),
                           labels=CATEGORY_LABELS, records=sql.recent(g.user['id'], limit=10))


def _ledger_page(tx_key):
    """收入頁與支出頁共用：GET 顯示，POST 驗證後新增再導回（PRG）。"""
    tx_type = INCOME if tx_key == 'income' else EXPENSE
    today = date.today()
    form, error = {}, None
    if request.method == 'POST':
        form = request.form
        try:
            title, amount, record_date, category = parse_form(form, today)
        except FormError as exc:
            error = str(exc)
        else:
            notice = None
            if tx_type == INCOME:
                category = INCOME
            elif category is None:
                category, notice = classify_expense(title)
            sql.insert(g.user['id'], tx_type, record_date, category, title, amount)
            if tx_type == INCOME:
                flash(f'已新增收入「{title}」{amount:,} 元。', 'success')
            elif notice:
                flash(f'已新增支出「{title}」，但{notice}，先標為「未分類」。', 'info')
            else:
                flash(f'已新增支出「{title}」，分類：{CATEGORY_LABELS[category]}。', 'success')
            return redirect(url_for(f'financial.{tx_key}'))

    rows, summary = _stats(today)
    month_start, month_end = periods(today)['month']
    return render_template(f'financial/{tx_key}.html',
                           title='財務小幫手：' + tx_type, tx_key=tx_key, tx_type=tx_type,
                           summary=summary, labels=CATEGORY_LABELS, categories=EXPENSE_CATEGORIES,
                           breakdown=category_breakdown(rows, month_start, month_end) if tx_type == EXPENSE else [],
                           records=sql.recent(g.user['id'], tx_type), form=form, error=error,
                           current_date=today.isoformat()), (400 if error else 200)


@financial.route('/income', methods=['GET', 'POST'])
@login_required
def income():
    return _ledger_page('income')


@financial.route('/expense', methods=['GET', 'POST'])
@login_required
def expense():
    return _ledger_page('expense')


@financial.post('/<int:record_id>/delete')
@login_required
def delete(record_id):
    if not sql.delete(g.user['id'], record_id):
        abort(404)
    flash('已刪除一筆紀錄。', 'success')
    back = request.form.get('next', '')
    # 只允許導回本模組頁面，避免開放式重新導向
    allowed = {url_for('financial.overview'), url_for('financial.income'), url_for('financial.expense')}
    return redirect(back if back in allowed else url_for('financial.overview'))
