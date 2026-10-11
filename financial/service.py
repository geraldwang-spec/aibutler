# -*- coding: utf-8 -*-
"""財務模組的表單驗證與統計。所有金額加總都在這裡由程式計算，不交給 LLM。"""
from datetime import date, timedelta

INCOME, EXPENSE = '收入', '支出'
TX_TYPES = {'income': INCOME, 'expense': EXPENSE}          # 網址參數 → 資料庫值
EXPENSE_CATEGORIES = ('食', '衣', '住', '行', '育', '樂')
UNCATEGORIZED = '未分類'
CATEGORY_LABELS = {'食': '食（餐飲）', '衣': '衣（服飾）', '住': '住（居住）',
                   '行': '行（交通）', '育': '育（教育）', '樂': '樂（娛樂）',
                   UNCATEGORIZED: '未分類', INCOME: '收入'}
MAX_AMOUNT = 99_999_999
MAX_TITLE = 100


class FormError(ValueError):
    """給使用者看的驗證錯誤。"""


def parse_form(form, today=None):
    """驗證新增表單，回傳 (title, amount, record_date_iso, manual_category 或 None)。"""
    today = today or date.today()
    title = (form.get('title') or '').strip()
    if not title:
        raise FormError('請輸入紀錄名稱。')
    if len(title) > MAX_TITLE:
        raise FormError(f'紀錄名稱最多 {MAX_TITLE} 個字。')

    raw_amount = (form.get('amount') or '').strip().replace(',', '')
    try:
        amount = int(raw_amount)
    except ValueError:
        raise FormError('金額請輸入正整數。') from None
    if not 1 <= amount <= MAX_AMOUNT:
        raise FormError(f'金額需介於 1 到 {MAX_AMOUNT:,}。')

    raw_date = (form.get('record_date') or '').strip() or today.isoformat()
    try:
        record_date = date.fromisoformat(raw_date)
    except ValueError:
        raise FormError('日期格式不正確。') from None
    if not 2000 <= record_date.year <= today.year + 1:
        raise FormError('日期超出可記錄的範圍。')

    # 使用者可手動指定分類；留空（預設）代表交給 AI 判斷
    category = (form.get('category') or '').strip() or None
    if category is not None and category not in EXPENSE_CATEGORIES:
        raise FormError('分類不正確。')
    return title, amount, record_date.isoformat(), category


def periods(today=None):
    """今日／本週（週一到週日）／本月／今年的起訖日期。"""
    today = today or date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return {
        'day': (today, today),
        'week': (week_start, week_start + timedelta(days=6)),
        'month': (month_start, next_month - timedelta(days=1)),
        'year': (today.replace(month=1, day=1), today.replace(month=12, day=31)),
    }


def query_range(today=None):
    """一次查詢涵蓋所有統計區間的日期範圍（本週可能跨到去年）。"""
    spans = periods(today).values()
    return min(s for s, _ in spans).isoformat(), max(e for _, e in spans).isoformat()


def _as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def summarize(rows, today=None):
    """依區間加總收入、支出與結餘。rows 需含 type、record_date、amount。"""
    spans = periods(today)
    summary = {key: {'income': 0, 'expense': 0} for key in spans}
    for row in rows:
        day = _as_date(row['record_date'])
        field = 'income' if row['type'] == INCOME else 'expense'
        for key, (start, end) in spans.items():
            if start <= day <= end:
                summary[key][field] += int(row['amount'])
    for item in summary.values():
        item['balance'] = item['income'] - item['expense']
    return summary


def category_breakdown(rows, start, end):
    """區間內支出依分類加總，回傳 [(分類, 金額, 百分比)]，金額大到小，百分比由程式計算。"""
    totals = {}
    for row in rows:
        if row['type'] != EXPENSE or not start <= _as_date(row['record_date']) <= end:
            continue
        totals[row['category']] = totals.get(row['category'], 0) + int(row['amount'])
    grand = sum(totals.values())
    return [(cat, amt, round(amt * 100 / grand, 1) if grand else 0)
            for cat, amt in sorted(totals.items(), key=lambda kv: -kv[1])]
