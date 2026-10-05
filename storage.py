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
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from flask import current_app, g


class StorageIntegrityError(Exception):
    """Backend-neutral unique/FK/constraint error."""


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
    def __init__(self, connection, pymysql_module):
        self._connection = connection
        self._pymysql = pymysql_module

    def execute(self, sql, params=()):
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

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def _backend(app=None):
    config = (app or current_app).config
    return str(config.get("DB_TYPE", "sqlite")).lower()


def backend(app=None):
    """Return normalized backend name for feature modules."""
    return _backend(app)


def _connect_mariadb(app=None):
    config = (app or current_app).config
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("MariaDB 模式需要 PyMySQL，請先執行：pip install pymysql") from exc

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
    return MariaConnection(raw, pymysql)


def _connect_sqlite(app=None):
    config = (app or current_app).config
    connection = sqlite3.connect(config["DATABASE"], timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def db():
    if "db" not in g:
        g.db = _connect_mariadb() if _backend() == "mariadb" else _connect_sqlite()
    return g.db


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

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()
