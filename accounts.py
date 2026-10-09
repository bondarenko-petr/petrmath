"""Registration, password authentication and revocable server-side sessions."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from collections import OrderedDict
from contextlib import contextmanager
from threading import Lock

import mysql.connector
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from database import ROOT

router = APIRouter(prefix='/api/auth', tags=['Account'])
COOKIE = 'krug_pi_session'
TTL = 7 * 24 * 3600
attempts = OrderedDict()
lock = Lock()


@contextmanager
def database():
    if os.environ.get('DB_BACKEND', 'sqlite') == 'mysql':
        connection = mysql.connector.connect(host=os.environ.get('MYSQL_HOST', '127.0.0.1'),
            port=int(os.environ.get('MYSQL_PORT', '3306')), user=os.environ['MYSQL_USER'],
            password=os.environ['MYSQL_PASSWORD'], database=os.environ['MYSQL_DATABASE'],
            charset='utf8mb4', connection_timeout=5, autocommit=False)
        cursor = connection.cursor(dictionary=True)
        placeholder = '%s'
    elif os.environ.get('DB_BACKEND', 'sqlite') == 'sqlite':
        from pathlib import Path
        path = Path(os.environ.get('TRIAL_REQUESTS_DB', str(ROOT / 'data/trial_requests.sqlite3')))
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute('PRAGMA table_info(users)')}
        if columns and 'username' not in columns:
            connection.execute('PRAGMA foreign_keys=OFF')
            connection.execute("CREATE TABLE users_new (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student', username TEXT NOT NULL UNIQUE COLLATE NOCASE, must_change_password INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL DEFAULT 0, password_changed_at INTEGER)")
            connection.execute("INSERT INTO users_new (id,name,email,password_hash,role,username) SELECT id,name,email,password_hash,role,lower(email) FROM users")
            connection.execute('DROP TABLE users')
            connection.execute('ALTER TABLE users_new RENAME TO users')
            connection.commit()
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student', username TEXT NOT NULL UNIQUE COLLATE NOCASE, must_change_password INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL DEFAULT 0, password_changed_at INTEGER)")
        connection.execute("CREATE TABLE IF NOT EXISTS student_profiles (user_id INTEGER PRIMARY KEY REFERENCES users(id), phone TEXT NOT NULL DEFAULT '', school_grade INTEGER, default_price_kopecks INTEGER NOT NULL DEFAULT 0, default_duration_minutes INTEGER NOT NULL DEFAULT 60)")
        connection.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS lesson_series (id INTEGER PRIMARY KEY, timezone TEXT NOT NULL, created_at INTEGER NOT NULL)')
        connection.execute("CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id), series_id INTEGER REFERENCES lesson_series(id), starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, duration_minutes INTEGER NOT NULL, price_kopecks INTEGER NOT NULL, topic TEXT NOT NULL DEFAULT '', meeting_url TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', created_at INTEGER NOT NULL)")
        connection.execute('CREATE INDEX IF NOT EXISTS lessons_start ON lessons(starts_at)')
        connection.execute('CREATE INDEX IF NOT EXISTS lessons_student_start ON lessons(student_id,starts_at)')
        cursor = connection.cursor()
        placeholder = '?'
    else:
        raise HTTPException(503, 'Ошибка настройки базы')
    try:
        yield cursor, placeholder
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64).hex()
    return f'scrypt${salt}${digest}'


DUMMY_HASH = hash_password('dummy password for timing')


def verify(password, stored):
    return hmac.compare_digest(hash_password(password, stored.split('$')[1]), stored)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('username', mode='after')
    @classmethod
    def normalize(cls, value):
        return str(value).strip().lower()


def guard(request):
    # Cross-site forms cannot send this custom header; CORS is not enabled.
    if request.headers.get('x-requested-with') != 'KrugPi':
        raise HTTPException(403, 'Недопустимый запрос')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Недопустимый источник запроса')


def throttle(request):
    key = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    with lock:
        recent = [t for t in attempts.get(key, []) if now - t < 60]
        if len(recent) >= 10:
            raise HTTPException(429, 'Слишком много попыток. Подождите минуту.')
        attempts[key] = recent + [now]
        attempts.move_to_end(key)
        while len(attempts) > 10000:
            attempts.popitem(last=False)


def session(cursor, placeholder, user_id, request, response):
    previous = request.cookies.get(COOKIE)
    if previous:
        cursor.execute(f'DELETE FROM sessions WHERE token_hash={placeholder}', (hashlib.sha256(previous.encode()).hexdigest(),))
    token = secrets.token_urlsafe(32)
    cursor.execute(f'DELETE FROM sessions WHERE expires_at < {placeholder}', (int(time.time()),))
    cursor.execute(f'INSERT INTO sessions (token_hash,user_id,expires_at) VALUES ({placeholder},{placeholder},{placeholder})',
                   (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + TTL))
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite='lax',
                        secure=os.environ.get('COOKIE_SECURE', 'false').lower() == 'true')
    response.headers['Cache-Control'] = 'no-store'


@router.post('/register')
def register():
    raise HTTPException(403, 'Аккаунт ученика создаёт преподаватель')


@router.post('/login')
def login(data: Credentials, request: Request, response: Response):
    guard(request)
    throttle(request)
    with database() as (cursor, p):
        cursor.execute(f'SELECT id,password_hash,is_active FROM users WHERE username={p}', (data.username,))
        user = cursor.fetchone()
        valid = verify(data.password, user['password_hash'] if user else DUMMY_HASH)
        if not user or not valid or not user['is_active']:
            raise HTTPException(401, 'Неверный логин или пароль')
        session(cursor, p, user['id'], request, response)
    return {'status': 'authenticated'}


@router.get('/me')
def profile(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'Войдите в аккаунт')
    with database() as (cursor, p):
        cursor.execute(f'SELECT u.id,u.name,u.email,u.username,u.role,u.must_change_password FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token_hash={p} AND s.expires_at>{p} AND u.is_active=1',
                       (hashlib.sha256(token.encode()).hexdigest(), int(time.time())))
        user = cursor.fetchone()
    if not user:
        raise HTTPException(401, 'Сессия истекла. Войдите снова.')
    response.headers['Cache-Control'] = 'no-store'
    return dict(user)


@router.post('/logout')
def logout(request: Request, response: Response):
    guard(request)
    token = request.cookies.get(COOKIE)
    if token:
        with database() as (cursor, p):
            cursor.execute(f'DELETE FROM sessions WHERE token_hash={p}', (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(COOKIE)
    response.headers['Cache-Control'] = 'no-store'
    return {'status': 'logged_out'}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@router.post('/change-password')
def change_password(data: PasswordChange, request: Request, response: Response):
    guard(request)
    throttle(request)
    user = profile(request, response)
    with database() as (cursor, p):
        cursor.execute(f'SELECT password_hash FROM users WHERE id={p}', (user['id'],))
        old = cursor.fetchone()['password_hash']
        if not verify(data.current_password, old):
            raise HTTPException(401, 'Неверный текущий пароль')
        if verify(data.new_password, old):
            raise HTTPException(422, 'Новый пароль должен отличаться от текущего')
        cursor.execute(f'UPDATE users SET password_hash={p},must_change_password=0,password_changed_at={p} WHERE id={p} AND password_hash={p} AND is_active=1',
                       (hash_password(data.new_password), int(time.time()), user['id'], old))
        if cursor.rowcount != 1:
            raise HTTPException(409, 'Аккаунт изменился. Войдите снова.')
        cursor.execute(f'DELETE FROM sessions WHERE user_id={p}', (user['id'],))
        session(cursor, p, user['id'], request, response)
    return {'status':'password_changed'}
