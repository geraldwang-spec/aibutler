"""Atomic review of an explicit snapshot of selected drafts."""
import json
import sqlite3
from flask import request, g, jsonify, redirect, url_for, flash
from storage import db, locked_sql, StorageIntegrityError
from .draft_review import prepare, apply


def bulk_questions():
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def result(message, status=200, **extra):
        if ajax:
            return jsonify(message=message, **extra), status
        flash(message, 'success' if status == 200 else 'error')
        return redirect(url_for('personal_ai.ai_questions'))

    try:
        action = request.form.get('action', '')
        if action not in ('approve', 'reject', 'save'):
            raise ValueError('請選擇批次處理方式。')
        raw_ids = request.form.getlist('draft_ids')
        if request.form.get('scope') == 'all':
            raw_ids = request.form.getlist('all_draft_ids')
        if not raw_ids or len(raw_ids) > 200:
            raise ValueError('請選擇 1–200 題；更多草稿請分批處理。')
        ids = sorted(set(int(value) for value in raw_ids))
        if any(value <= 0 for value in ids):
            raise ValueError('草稿編號不正確。')
        edits = json.loads(request.form.get('edits', '{}'))
        if not isinstance(edits, dict):
            raise ValueError('草稿修正資料不正確。')
        db().execute('BEGIN IMMEDIATE')
        pending, skipped, errors = [], [], []
        placeholders = ','.join('?' for _ in ids)
        drafts = db().execute(locked_sql('SELECT * FROM ai_question_drafts WHERE user_id=? '
                                         f'AND id IN ({placeholders}) ORDER BY id'), (g.user['id'], *ids)).fetchall()
        if len(drafts) != len(ids):
            db().rollback()
            return result('所選草稿已不存在或無法存取。', 404)
        allowed_chapters = set()
        if action != 'reject':
            allowed_chapters = {(c['id'], c['subject_id']) for c in db().execute(
                'SELECT c.id,c.subject_id FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE s.created_by=?',
                (g.user['id'],)).fetchall()}
        for draft in drafts:
            draft_id = draft['id']
            if draft['status'] != 'draft':
                skipped.append(draft_id)
                continue
            try:
                edit = edits.get(str(draft_id), {})
                if not isinstance(edit, dict) or any(not isinstance(v, (str, int, type(None))) for v in edit.values()):
                    raise ValueError('草稿修正資料不正確。')
                prepared = None if action == 'reject' else prepare(draft, edit, g.user['id'], allowed_chapters)
                pending.append((draft, prepared))
            except (ValueError, TypeError) as exc:
                errors.append(dict(draft_id=draft_id, error=str(exc)))
        if errors:
            db().rollback()
            message = '尚未處理任何草稿，請先修正：' + '；'.join(f"#{e['draft_id']} {e['error']}" for e in errors)
            return result(message, 400, errors=errors)
        saved = []
        for draft, prepared in pending:
            apply(draft, action, prepared)
            if action == 'save':
                data, pairs, chapter_id = prepared
                saved.append(dict(id=draft['id'], chapter_id=chapter_id, options=dict(pairs), **data))
        db().commit()
        verb = {'save': '儲存修正', 'approve': '核准加入題庫', 'reject': '退回草稿'}[action]
        message = f'已{verb} {len(pending)} 題。'
        if skipped:
            message += f'另有 {len(skipped)} 題已處理，已略過。'
        return result(message, action=action, processed=[d['id'] for d, _ in pending], skipped=skipped, drafts=saved)
    except (ValueError, TypeError, sqlite3.IntegrityError, StorageIntegrityError) as exc:
        db().rollback()
        return result(str(exc) if isinstance(exc, (ValueError, TypeError)) else '題庫資料有衝突，本批次未寫入，請重新整理後再試。', 400)
    except Exception:
        db().rollback()
        raise
