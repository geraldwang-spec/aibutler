import sqlite3
from contextlib import closing
from pathlib import Path
from flask import current_app, g


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def init_storage(app):
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(app.config['DATABASE'])) as connection:
        connection.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
        connection.commit()

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop('db', None)
        if connection is not None:
            connection.close()
