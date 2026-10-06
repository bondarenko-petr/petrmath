"""MySQL storage; SQLite remains available for existing local installations."""
import os
from contextlib import closing
import sqlite3
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')


def save_request(request):
    backend = os.environ.get('DB_BACKEND', 'sqlite')
    values = (request.name, str(request.email), request.phone,
              ', '.join(dict.fromkeys(request.courses)), request.message, 1)
    if backend == 'mysql':
        required = ['MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DATABASE']
        if any(not os.environ.get(key) for key in required):
            raise ValueError('Missing MySQL configuration')
        with mysql.connector.connect(
            host=os.environ.get('MYSQL_HOST', '127.0.0.1'),
            port=int(os.environ.get('MYSQL_PORT', '3306')),
            user=os.environ['MYSQL_USER'], password=os.environ['MYSQL_PASSWORD'],
            database=os.environ['MYSQL_DATABASE'], charset='utf8mb4',
            connection_timeout=5, autocommit=False,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO trial_requests (name,email,phone,courses,message,consent) VALUES (%s,%s,%s,%s,%s,%s)', values)
            connection.commit()
    elif backend == 'sqlite':
        path = Path(os.environ.get('TRIAL_REQUESTS_DB', str(ROOT / 'data/trial_requests.sqlite3')))
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=10)) as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS trial_requests (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
                courses TEXT NOT NULL, message TEXT NOT NULL, consent INTEGER NOT NULL)''')
            connection.execute('INSERT INTO trial_requests (name,email,phone,courses,message,consent) VALUES (?,?,?,?,?,?)', values)
            connection.commit()
    else:
        raise ValueError('Unknown DB_BACKEND')
