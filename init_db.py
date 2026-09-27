"""Create missing tables using the backend configured in .env.

Running this file imports ``app``, whose application factory initializes the
selected schema once.  It then prints the selected backend for confirmation.
"""
from app import app

print(f"Database backend: {app.config.get('DB_TYPE')}")
if app.config.get('DB_TYPE') == 'mariadb':
    print(f"MariaDB: {app.config.get('DB_HOST')}:{app.config.get('DB_PORT')}/{app.config.get('DB_NAME')}")
print("Database schema initialization completed.")
