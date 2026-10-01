"""Initialize the personal edition database configured in .env. Default: local SQLite."""
from app import app
from storage import init_storage

# Remote MariaDB no longer auto-runs the whole schema on every Flask startup.
# Run it explicitly here when a developer wants to initialize/check tables.
init_storage(app)

print(f"Database backend: {app.config.get('DB_TYPE')}")
if app.config.get('DB_TYPE') in ('postgresql','postgres','pg'):
    print(f"PostgreSQL + pgvector: {app.config.get('DB_HOST')}:{app.config.get('DB_PORT')}/{app.config.get('DB_NAME')}")
print("Database schema initialization completed.")
if app.config.get('DB_TYPE') == 'sqlite':
    print(f"SQLite: {app.config.get('DATABASE')}")
