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
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
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
        connection.execute("CREATE TABLE IF NOT EXISTS student_profiles (user_id INTEGER PRIMARY KEY REFERENCES users(id), phone TEXT NOT NULL DEFAULT '', school_grade INTEGER, default_price_kopecks INTEGER NOT NULL DEFAULT 0, default_duration_minutes INTEGER NOT NULL DEFAULT 45)")
        if 'timezone' not in {row[1] for row in connection.execute('PRAGMA table_info(student_profiles)')}:
            connection.execute('ALTER TABLE student_profiles ADD COLUMN timezone TEXT')
        profile_columns={row[1] for row in connection.execute('PRAGMA table_info(student_profiles)')}
        for name in ('parent_name','parent_phone'):
            if name not in profile_columns:connection.execute(f"ALTER TABLE student_profiles ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        connection.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS lesson_series (id INTEGER PRIMARY KEY, timezone TEXT NOT NULL, created_at INTEGER NOT NULL)')
        connection.execute("CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id), series_id INTEGER REFERENCES lesson_series(id), starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, duration_minutes INTEGER NOT NULL, price_kopecks INTEGER NOT NULL, topic TEXT NOT NULL DEFAULT '', meeting_url TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', created_at INTEGER NOT NULL)")
        connection.execute('CREATE INDEX IF NOT EXISTS lessons_start ON lessons(starts_at)')
        connection.execute('CREATE INDEX IF NOT EXISTS lessons_student_start ON lessons(student_id,starts_at)')
        from payment_schema import ensure_payments
        ensure_payments(connection)
        connection.execute("CREATE TABLE IF NOT EXISTS trial_requests (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, courses TEXT NOT NULL, message TEXT NOT NULL, consent INTEGER NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS trial_request_management (request_id INTEGER PRIMARY KEY REFERENCES trial_requests(id), status TEXT NOT NULL DEFAULT 'new', admin_note TEXT NOT NULL DEFAULT '', close_reason TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL, updated_by INTEGER NOT NULL REFERENCES users(id))")
        connection.execute('CREATE INDEX IF NOT EXISTS trial_management_status ON trial_request_management(status,request_id)')
        from material_schema import ensure_materials
        ensure_materials(connection)
        from archive_schema import ensure_archives
        ensure_archives(connection)
        from recovery import ensure_schema
        ensure_schema(connection)
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
        cursor.execute(f"SELECT u.id,u.name,u.email,u.username,u.role,u.must_change_password,COALESCE(sp.phone,'') AS phone,COALESCE(sp.parent_name,'') AS parent_name,COALESCE(sp.parent_phone,'') AS parent_phone,sp.timezone FROM users u LEFT JOIN student_profiles sp ON sp.user_id=u.id JOIN sessions s ON u.id=s.user_id WHERE s.token_hash={p} AND s.expires_at>{p} AND u.is_active=1",
                       (hashlib.sha256(token.encode()).hexdigest(), int(time.time())))
        user = cursor.fetchone()
    if not user:
        raise HTTPException(401, 'Сессия истекла. Войдите снова.')
    response.headers['Cache-Control'] = 'no-store'
    result=dict(user)
    result['effective_timezone']=result['timezone'] or os.environ.get('LESSON_TIMEZONE','Europe/Moscow')
    return result


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


class StudentProfileEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email: EmailStr | None = Field(default=None,max_length=254)
    phone: str = Field(default='',max_length=40)
    parent_name: str = Field(default='',max_length=100)
    parent_phone: str = Field(default='',max_length=40)
    timezone: str | None = Field(default=None,max_length=100)

    @field_validator('phone','parent_name','parent_phone',mode='before')
    @classmethod
    def clean_phone(cls,value):
        return value.strip() if isinstance(value,str) else value

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls,value):
        from student_timezones import validate_zone
        return validate_zone(value)


@router.post('/profile')
def edit_own_student_profile(data:StudentProfileEdit,request:Request,response:Response):
    guard(request)
    user=profile(request,response)
    if user['role']!='student' or user['must_change_password']:
        raise HTTPException(403,'Редактирование доступно ученику после смены временного пароля')
    try:
        with database() as (c,p):
            if p=='?':c.execute('BEGIN IMMEDIATE')
            c.execute(f"SELECT id FROM users WHERE id={p} AND role='student' AND is_active=1"+(' FOR UPDATE' if p!='?' else ''),(user['id'],))
            if not c.fetchone():raise HTTPException(409,'Аккаунт изменился. Войдите снова.')
            next_email=str(data.email).lower() if data.email else None
            if (user['email'] or '').lower()!=(next_email or ''):
                c.execute(f'DELETE FROM verified_emails WHERE user_id={p}',(user['id'],))
                c.execute(f'DELETE FROM account_links WHERE user_id={p}',(user['id'],))
            c.execute(f'UPDATE users SET email={p} WHERE id={p}',(str(data.email).lower() if data.email else None,user['id']))
            c.execute(f'SELECT user_id FROM student_profiles WHERE user_id={p}',(user['id'],))
            if c.fetchone():
                c.execute(f'UPDATE student_profiles SET phone={p},parent_name={p},parent_phone={p},timezone={p} WHERE user_id={p}',(data.phone,data.parent_name,data.parent_phone,data.timezone,user['id']))
            else:
                c.execute(f'INSERT INTO student_profiles (user_id,phone,parent_name,parent_phone,timezone,default_duration_minutes) VALUES ({p},{p},{p},{p},{p},45)',(user['id'],data.phone,data.parent_name,data.parent_phone,data.timezone))
    except (sqlite3.IntegrityError,mysql.connector.IntegrityError):
        raise HTTPException(409,'Этот email уже используется другим аккаунтом')
    response.headers['Cache-Control']='no-store'
    return {'status':'updated'}
