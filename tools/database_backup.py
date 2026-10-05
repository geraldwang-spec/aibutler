"""Consistent MariaDB snapshot for read-only standby and explicit restore to an EMPTY database."""
import argparse
import datetime
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from decimal import Decimal
import pymysql
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]


def connect(database=None):
    return pymysql.connect(host=os.getenv('DB_HOST','127.0.0.1'),port=int(os.getenv('DB_PORT','3306')),
        user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'),database=database,
        charset='utf8mb4',autocommit=False,connect_timeout=10,read_timeout=120)


def sql_name(value):
    return '`'+value.replace('`','``')+'`'


def value(v):
    if isinstance(v,datetime.datetime): return v.isoformat(sep=' ')
    if isinstance(v,datetime.date): return v.isoformat()
    if isinstance(v,datetime.timedelta): return str(v)
    if isinstance(v,Decimal): return float(v)
    return v


def backup():
    folder=ROOT/'instance'/'backups'; folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    snapshot=folder/('snapshot-'+stamp+'.sqlite'); temporary=folder/(stamp+'.partial')
    schema={}; counts={}
    source=connect(os.getenv('DB_NAME'))
    target=sqlite3.connect(temporary)
    try:
        with source.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            cur.execute('SHOW FULL TABLES WHERE Table_type = %s',('BASE TABLE',))
            tables=[row[0] for row in cur.fetchall()]
            for table in tables:
                cur.execute('SHOW CREATE TABLE '+sql_name(table)); schema[table]=cur.fetchone()[1]
                cur.execute('SELECT * FROM '+sql_name(table)+' LIMIT 0')
                columns=[column[0] for column in cur.description]
                quoted='"'+table.replace('"','""')+'"'
                names=['"'+c.replace('"','""')+'"' for c in columns]
                target.execute('CREATE TABLE '+quoted+' ('+','.join(names)+')')
                cur.execute('SELECT * FROM '+sql_name(table)); count=0
                while True:
                    rows=cur.fetchmany(500)
                    if not rows: break
                    target.executemany('INSERT INTO '+quoted+' VALUES ('+','.join('?' for _ in columns)+')',
                                       [tuple(value(v) for v in row) for row in rows])
                    count+=len(rows)
                counts[table]=count
        target.commit(); target.close(); source.rollback(); source.close()
        temporary.replace(snapshot)
        metadata=dict(created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_database=os.getenv('DB_NAME'),
                      sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),rows=counts,schema=schema)
        snapshot.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        # Atomic publish; retain timestamped snapshot and schema for restoration.
        import shutil
        pending=folder/'standby.pending'; shutil.copyfile(snapshot,pending); pending.replace(folder/'standby.sqlite')
        meta_pending=folder/'standby-meta.pending'
        meta_pending.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        meta_pending.replace(folder/'standby.json')
        print(f'完整快照已建立：{snapshot}；{len(tables)} 個表、{sum(counts.values())} 筆。未修改主資料庫。')
    except Exception:
        target.close(); source.close(); temporary.unlink(missing_ok=True)
        raise


def restore(path,database):
    if not database or database==os.getenv('DB_NAME'):
        raise ValueError('復原目的地必須是不同名稱的空 MariaDB 資料庫；不允許覆寫主庫。')
    snapshot=Path(path).resolve(); metadata=json.loads(snapshot.with_suffix('.json').read_text(encoding='utf-8'))
    if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=metadata['sha256']:
        raise ValueError('快照雜湊不符，已拒絕復原。')
    source=sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)
    target=connect(database)
    try:
        with target.cursor() as cur:
            cur.execute('SHOW TABLES')
            if cur.fetchone(): raise ValueError('目的資料庫不是空的，已拒絕復原。')
            cur.execute('SET FOREIGN_KEY_CHECKS=0')
            for table,ddl in metadata['schema'].items():
                cur.execute(ddl)
                rows=source.execute('SELECT * FROM "'+table.replace('"','""')+'"')
                names=[c[0] for c in rows.description]
                sql='INSERT INTO '+sql_name(table)+' ('+','.join(sql_name(c) for c in names)+') VALUES ('+','.join('%s' for _ in names)+')'
                count=0
                while True:
                    batch=rows.fetchmany(500)
                    if not batch: break
                    cur.executemany(sql,batch); count+=len(batch)
                if count!=metadata['rows'][table]: raise ValueError('復原筆數不一致：'+table)
            cur.execute('SET FOREIGN_KEY_CHECKS=1')
        target.commit()
        print('已復原到指定空資料庫；尚未切換應用程式。請確認 DB 設定後再啟動。')
    except Exception:
        target.rollback(); raise
    finally:
        target.close(); source.close()


if __name__=='__main__':
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser()
    parser.add_argument('--restore'); parser.add_argument('--target-db');parser.add_argument('--host');parser.add_argument('--port',type=int)
    args=parser.parse_args()
    if args.host:os.environ['DB_HOST']=args.host
    if args.port:os.environ['DB_PORT']=str(args.port)
    if args.restore: restore(args.restore,args.target_db)
    else: backup()
