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
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT \'student\')')
        connection.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL)')
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
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('email', mode='after')
    @classmethod
    def normalize(cls, value):
        return str(value).lower()


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('name', mode='before')
    @classmethod
    def strip(cls, value):
        return value.strip() if isinstance(value, str) else value


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


@router.post('/register', status_code=201)
def register(data: Registration, request: Request, response: Response):
    guard(request)
    throttle(request)
    encoded = hash_password(data.password)
    try:
        with database() as (cursor, p):
            cursor.execute(f'INSERT INTO users (name,email,password_hash) VALUES ({p},{p},{p})', (data.name, str(data.email), encoded))
            session(cursor, p, cursor.lastrowid, request, response)
    except (sqlite3.IntegrityError, mysql.connector.IntegrityError):
        raise HTTPException(409, 'Этот email уже зарегистрирован')
    return {'status': 'registered'}


@router.post('/login')
def login(data: Credentials, request: Request, response: Response):
    guard(request)
    throttle(request)
    with database() as (cursor, p):
        cursor.execute(f'SELECT id,password_hash FROM users WHERE email={p}', (str(data.email),))
        user = cursor.fetchone()
        valid = verify(data.password, user['password_hash'] if user else DUMMY_HASH)
        if not user or not valid:
            raise HTTPException(401, 'Неверный email или пароль')
        session(cursor, p, user['id'], request, response)
    return {'status': 'authenticated'}


@router.get('/me')
def profile(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'Войдите в аккаунт')
    with database() as (cursor, p):
        cursor.execute(f'SELECT u.id,u.name,u.email,u.role FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token_hash={p} AND s.expires_at>{p}',
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
