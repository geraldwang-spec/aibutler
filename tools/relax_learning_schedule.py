"""Apply recovery days to one account's unstarted learning tasks only."""
import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from storage import _connect_mariadb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    parser.add_argument('--from-date', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--restore-backup', type=Path)
    args = parser.parse_args()
    start = date.fromisoformat(args.from_date)
    config = dotenv_values(ROOT / '.env')
    app = SimpleNamespace(config={key: config[key] for key in ('DB_HOST','DB_PORT','DB_USER','DB_PASSWORD','DB_NAME')}, extensions={})
    spec = importlib.util.spec_from_file_location('schedule_rhythm', ROOT / 'personal_ai' / 'schedule_rhythm.py')
    rhythm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rhythm)
    connection = _connect_mariadb(app)
    try:
        user = connection.execute('SELECT id FROM users WHERE username=?', (args.username,)).fetchone()
        if not user:
            raise ValueError('找不到指定帳號，沒有更新資料。')
        if args.restore_backup:
            originals = json.loads(args.restore_backup.read_text(encoding='utf-8'))
            for row in originals:
                if int(row['user_id']) != int(user['id']):
                    raise ValueError('備份帳號不符，沒有更新資料。')
                connection.execute(
                    "UPDATE learning_tasks SET task_type=?,title=?,target_minutes=?,reason=?,concept_id=?,chapter_id=? "
                    "WHERE id=? AND user_id=? AND status='planned' AND COALESCE(question_count,0)=0 "
                    "AND task_type IN ('休息','運動建議','輕量學習') AND NOT EXISTS "
                    "(SELECT 1 FROM learning_checkpoint_attempts a WHERE a.task_id=learning_tasks.id)",
                    (row['task_type'],row['title'],row['target_minutes'],row['reason'],row['concept_id'],row['chapter_id'],row['id'],user['id']))
        rows = connection.execute(
            "SELECT lt.*,EXISTS(SELECT 1 FROM learning_checkpoint_attempts a WHERE a.task_id=lt.id) AS has_attempt "
            "FROM learning_tasks lt JOIN learning_goals lg ON lg.id=lt.goal_id AND lg.user_id=lt.user_id "
            "WHERE lt.user_id=? AND lt.task_date>=? AND lg.status='active' AND lg.exam_date>? "
            "ORDER BY lt.goal_id,lt.task_date,lt.id FOR UPDATE",
            (user['id'], start.isoformat(), start.isoformat())).fetchall()
        updates = []
        originals = []
        counts = Counter()
        grouped = defaultdict(list)
        for row in rows:
            grouped[(row['goal_id'],str(row['task_date'])[:10])].append(row)
        rhythms = {}
        for (goal_id, day), day_rows in grouped.items():
            state = rhythms.setdefault(goal_id, rhythm.RecoveryRhythm())
            minutes = sum(int(r['target_minutes'] or 0) for r in day_rows)
            assessed = any(r['question_count'] or r['has_attempt'] for r in day_rows)
            protected = any(r['status']!='planned' for r in day_rows)
            next_day = (date.fromisoformat(day) + __import__('datetime').timedelta(days=1)).isoformat()
            upcoming = any(r['question_count'] for r in grouped.get((goal_id,next_day),[]))
            recovery = None if protected else state.choose(minutes, assessment=assessed, before_assessment=upcoming)
            if not recovery:
                state.record(minutes, day_rows[0]['task_type'],1 if assessed else 0)
                continue
            for index,row in enumerate(day_rows):
                title = recovery['title']
                if recovery['task_type'] == '輕量學習':
                    title = '輕量回顧：' + row['title'].partition('：')[-1]
                clear_concept = recovery['task_type'] in ('休息', '運動建議')
                updates.append((recovery['task_type'], title, recovery['minutes'] if index==0 else 0, recovery['reason'],
                                None if clear_concept else row['concept_id'], None if clear_concept else row['chapter_id'], row['id'], user['id']))
                originals.append(dict(row))
                counts[recovery['task_type']] += 1
            state.record(recovery['minutes'], recovery['task_type'])
        if args.apply:
            backup = ROOT / 'instance' / ('schedule_before_recovery_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
            backup.write_text(json.dumps(originals, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
            connection.executemany(
                'UPDATE learning_tasks SET task_type=?,title=?,target_minutes=?,reason=?,concept_id=?,chapter_id=? WHERE id=? AND user_id=?', updates)
            connection.commit()
            print('已更新：', dict(counts))
            print('原始安排已備份：', backup.name)
        else:
            print('預計更新：', dict(counts))
            connection.rollback()
    finally:
        connection.close()
        for raw, _ in app.extensions.get('mariadb_idle_pool')._idle:
            raw.close()


if __name__ == '__main__':
    main()
