"""Database compatibility layer for AI Butler personal edition.

Backends:
- postgresql -> recommended personal backend; supports pgvector RAG search.
- sqlite     -> lightweight fallback for tests/offline work (no pgvector search).

Application modules keep SQLite-style ``?`` parameter markers. The PostgreSQL
adapter converts them to psycopg ``%s`` markers so existing modules do not need
to be rewritten just to change databases.
"""
from __future__ import annotations

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
    """Convert ? placeholders outside quoted strings to %s."""
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


class PgCursor:
    def __init__(self, cursor, lastrowid=0):
        self._cursor = cursor
        self.lastrowid = lastrowid or 0
        self.rowcount = getattr(cursor, "rowcount", -1)

    def _convert(self, row):
        if row is None:
            return None
        names = [column.name if hasattr(column, "name") else column[0] for column in (self._cursor.description or [])]
        return CompatRow(names, [_normalise_value(v) for v in row])

    def fetchone(self):
        return self._convert(self._cursor.fetchone())

    def fetchall(self):
        return [self._convert(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    _SERIAL_TABLES = {
        'users','reset_auth','body_metrics','subjects','chapters','questions','question_options',
        'exam_imports','import_items','quiz_sessions','quiz_answers','summaries','exam_plans',
        'study_plans','exercises','workouts','workout_sets','workout_templates','template_items',
        'chat_sessions','chat_messages','materials','rag_documents','rag_chunks','generated_quizzes',
        'ai_suggestions','ai_question_drafts','concepts','tutor_threads','tutor_messages','learning_goals','learning_phases','learning_milestones','learning_phase_concepts','learning_tasks','learning_checkpoint_attempts','micro_courses','micro_course_steps','micro_course_messages'
    }

    def __init__(self, connection, psycopg_module):
        self._connection = connection
        self._psycopg = psycopg_module

    @staticmethod
    def _insert_table(sql):
        import re
        match = re.match(r'\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)', sql, re.I)
        return match.group(1).lower() if match else None

    def execute(self, sql, params=()):
        stripped = sql.strip().upper()
        if stripped == "BEGIN IMMEDIATE":
            # psycopg starts a transaction automatically on the first statement.
            return PgCursor(self._connection.cursor())

        converted = _question_to_percent(sql)
        table = self._insert_table(sql)
        wants_id = table in self._SERIAL_TABLES and ' RETURNING ' not in (' ' + stripped + ' ')
        if wants_id:
            converted = converted.rstrip().rstrip(';') + ' RETURNING id'

        cursor = self._connection.cursor()
        try:
            cursor.execute(converted, tuple(params or ()))
            lastrowid = 0
            if wants_id:
                row = cursor.fetchone()
                lastrowid = int(row[0]) if row else 0
            return PgCursor(cursor, lastrowid)
        except self._psycopg.IntegrityError as exc:
            self._connection.rollback()
            cursor.close()
            raise StorageIntegrityError(str(exc)) from exc

    def executemany(self, sql, seq_of_params):
        cursor = self._connection.cursor()
        try:
            cursor.executemany(_question_to_percent(sql), [tuple(p or ()) for p in seq_of_params])
            return PgCursor(cursor)
        except self._psycopg.IntegrityError as exc:
            self._connection.rollback()
            cursor.close()
            raise StorageIntegrityError(str(exc)) from exc

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

def _backend(app=None):
    config = (app or current_app).config
    value = str(config.get("DB_TYPE", "postgresql")).lower()
    if value in ("postgres", "postgresql", "pg"):
        return "postgresql"
    return "sqlite"


def backend():
    return _backend()


def _connect_postgresql(app=None):
    config = (app or current_app).config
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('PostgreSQL 模式需要 psycopg，請先執行：pip install "psycopg[binary]"') from exc

    raw = psycopg.connect(
        host=config.get("DB_HOST", "127.0.0.1"),
        port=int(config.get("DB_PORT", 5432)),
        user=config.get("DB_USER", ""),
        password=config.get("DB_PASSWORD", ""),
        dbname=config.get("DB_NAME", ""),
        connect_timeout=10,
    )
    return PgConnection(raw, psycopg)


def _connect_sqlite(app=None):
    config = (app or current_app).config
    connection = sqlite3.connect(config["DATABASE"], timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def db():
    if "db" not in g:
        g.db = _connect_postgresql() if _backend() == "postgresql" else _connect_sqlite()
    return g.db


def _split_sql_script(script: str):
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
    """Create missing tables for selected backend and register teardown."""
    if _backend(app) == "postgresql":
        connection = _connect_postgresql(app)
        try:
            schema = Path(__file__).with_name("schema_postgres.sql").read_text(encoding="utf-8")
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
