"""Database compatibility layer for AI Butler.

Default development backend can be switched with DB_TYPE:
- sqlite   -> instance/smartlife.db
- mariadb  -> PyMySQL + DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME

Application modules intentionally keep the existing SQLite-style ``?`` parameter
markers.  The MariaDB adapter converts them to PyMySQL ``%s`` markers so team
modules do not need database-specific SQL for ordinary queries.
"""
from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import threading
import time
from collections import deque
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from flask import current_app, g


class StorageIntegrityError(Exception):
    """Backend-neutral unique/FK/constraint error."""


class DatabaseUnavailable(RuntimeError):
    pass


class CompatRow(dict):
    """Mapping row that also supports SQLite-style numeric indexing."""

    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _normalise_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _question_to_percent(sql: str) -> str:
    """Convert ? placeholders outside quoted strings to %s for PyMySQL."""
    out = []
    quote = None
    escaped = False
    for ch in sql:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and quote:
            out.append(ch)
            escaped = True
            continue
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


class MariaCursor:
    def __init__(self, cursor, connection=None):
        self._cursor = cursor
        # PyMySQL Cursor implementations differ slightly across versions.
        # Some expose ``lastrowid`` directly, while others only expose the
        # connection's latest insert id.  Keep a SQLite-compatible attribute
        # for existing application modules without assuming either shape.
        lastrowid = getattr(cursor, "lastrowid", None)
        if lastrowid is None and connection is not None:
            try:
                lastrowid = connection.insert_id()
            except (AttributeError, TypeError):
                lastrowid = None
        self.lastrowid = lastrowid or 0
        self.rowcount = getattr(cursor, "rowcount", -1)

    def _convert(self, row):
        if row is None:
            return None
        names = [column[0] for column in (self._cursor.description or [])]
        values = [_normalise_value(v) for v in row]
        return CompatRow(names, values)

    def fetchone(self):
        return self._convert(self._cursor.fetchone())

    def fetchall(self):
        return [self._convert(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class MariaConnection:
    def __init__(self, connection, pymysql_module, release=None):
        self._connection = connection
        self._pymysql = pymysql_module
        self._release = release
        self._closed = False
        self._clean = True

    def execute(self, sql, params=()):
        self._clean = False
        # Existing modules use this SQLite statement to request a write lock.
        # MariaDB starts a transaction instead; row-level locks are acquired by
        # the actual writes.
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            self._connection.begin()
            return MariaCursor(self._connection.cursor(), self._connection)

        cursor = self._connection.cursor()
        try:
            cursor.execute(_question_to_percent(sql), tuple(params or ()))
            return MariaCursor(cursor, self._connection)
        except self._pymysql.err.IntegrityError as exc:
            cursor.close()
            raise StorageIntegrityError(str(exc)) from exc

    def executemany(self, sql, params):
        """Run a batch with SQLite-style placeholders in the current transaction."""
        self._clean = False
        cursor = self._connection.cursor()
        try:
            cursor.executemany(
                _question_to_percent(sql), [tuple(row) for row in params]
            )
            return MariaCursor(cursor, self._connection)
        except self._pymysql.err.IntegrityError as exc:
            cursor.close()
            raise StorageIntegrityError(str(exc)) from exc
        except Exception:
            cursor.close()
            raise

    def commit(self):
        self._connection.commit()
        self._clean = True

    def rollback(self):
        try:
            self._connection.rollback()
        except Exception:
            self._release = None
            raise
        self._clean = True

    def close(self):
        if self._closed:
            return
        self._closed = True
        # A connection is never shared while checked out. Only a successfully
        # reset transaction may be returned for another request/user.
        if self._release:
            try:
                if not self._clean:
                    self._connection.rollback()
                self._release(self._connection)
                return
            except Exception:
                pass
        self._connection.close()


class _MariaIdlePool:
    """Keep at most four idle connections, with a 60-second idle lifetime."""
    def __init__(self):
        self._idle = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                if not self._idle:
                    return None
                raw, returned_at = self._idle.pop()
            try:
                if time.monotonic() - returned_at < 60:
                    raw.ping(reconnect=False)
                    return raw
            except Exception:
                pass
            try:
                raw.close()
            except Exception:
                pass

    def release(self, raw):
        with self._lock:
            if raw.open and len(self._idle) < 4:
                self._idle.append((raw, time.monotonic()))
                return
        raw.close()


def _backend(app=None):
    config = (app or current_app).config
    return str(config.get("DB_TYPE", "sqlite")).lower()


def backend(app=None):
    """Return normalized backend name for feature modules."""
    return _backend(app)


def _connect_mariadb(app=None):
    application = app or current_app
    config = application.config
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("MariaDB 模式需要 PyMySQL，請先執行：pip install pymysql") from exc

    pool = application.extensions.setdefault('mariadb_idle_pool', _MariaIdlePool())
    raw = pool.acquire()
    if raw is not None:
        return MariaConnection(raw, pymysql, pool.release)
    raw = pymysql.connect(
        host=config["DB_HOST"],
        port=int(config.get("DB_PORT", 3306)),
        user=config["DB_USER"],
        password=config["DB_PASSWORD"],
        database=config["DB_NAME"],
        charset=config.get("DB_CHARSET", "utf8mb4"),
        autocommit=False,
        cursorclass=pymysql.cursors.Cursor,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
    )
    try:
        with raw.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')
    except Exception:
        raw.close()
        raise
    return MariaConnection(raw, pymysql, pool.release)


def _connect_sqlite(app=None):
    config = (app or current_app).config
    connection = sqlite3.connect(config["DATABASE"], timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def db():
    if "db" not in g:
        connect_started = time.perf_counter()
        kind = _backend()
        if kind not in ('mariadb', 'sqlite'):
            raise RuntimeError('不支援的 DB_TYPE；目前支援 mariadb 或 sqlite。PostgreSQL 不可當成未同步的備援。')
        try:
            g.db = _connect_mariadb() if kind == 'mariadb' else _connect_sqlite()
            g.db_read_only = bool(current_app.config.get('DB_READ_ONLY'))
        except Exception:
            g.db_connect_ms = (time.perf_counter() - connect_started) * 1000
            standby = current_app.config.get('DB_STANDBY_PATH')
            if kind != 'mariadb' or not current_app.config.get('DB_STANDBY_ENABLED') or not standby:
                raise DatabaseUnavailable('資料庫暫時無法連線。尚未啟用可用的唯讀快照，請稍後再試。') from None
            path = Path(standby).resolve()
            if not path.is_file():
                raise DatabaseUnavailable('主資料庫無法連線，且沒有已建立的備援快照。') from None
            try:
                metadata=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                if hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:
                    raise ValueError('快照內容不符')
                g.db_snapshot_at=metadata['created_at']
            except (OSError, ValueError, KeyError):
                raise DatabaseUnavailable('備援快照缺少資訊或完整性檢查失敗；請重新建立備份。') from None
            g.db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db_read_only = True
            current_app.logger.warning('Primary database unavailable; using read-only standby snapshot')
        g.db_connect_ms = (time.perf_counter() - connect_started) * 1000
    return g.db


def read_only():
    return bool(getattr(g, 'db_read_only', False) or current_app.config.get('DB_READ_ONLY'))


def locked_sql(sql):
    return sql + (' FOR UPDATE' if backend() == 'mariadb' and not read_only() else '')


def register_storage(app):
    if app.extensions.get('storage_teardown'):
        return
    app.extensions['storage_teardown'] = True

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop('db', None)
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()


def _split_sql_script(script: str):
    """Split our schema file into statements (schema contains no procedures)."""
    statements = []
    current = []
    quote = None
    escaped = False
    for ch in script:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\" and quote:
            current.append(ch)
            escaped = True
            continue
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
        elif ch == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(ch)
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def init_storage(app):
    """Create missing tables for the selected backend and register teardown."""
    if _backend(app) == "mariadb":
        connection = _connect_mariadb(app)
        try:
            schema = Path(__file__).with_name("schema_mariadb.sql").read_text(encoding="utf-8")
            for statement in _split_sql_script(schema):
                connection.execute(statement)
            connection.commit()
        finally:
            connection.close()
    else:
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        connection = _connect_sqlite(app)
        try:
            connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            connection.commit()
        finally:
            connection.close()

    register_storage(app)
