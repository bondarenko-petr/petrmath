"""Read-only admin endpoints; authorization always comes from the stored role."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from accounts import database, profile, guard, hash_password
import secrets
import smtplib
from mailer import send_student_credentials
from accounts import verify, throttle
import sqlite3
import mysql.connector
import time
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional

router = APIRouter(prefix='/api/admin', tags=['Administration'])


def require_admin(request: Request, response: Response):
    user = profile(request, response)
    if user['must_change_password']:
        raise HTTPException(403, 'Сначала смените временный пароль')
    if user['role'] != 'admin':
        raise HTTPException(403, 'Доступ только для администратора')
    return user


@router.get('/students')
def students(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(require_admin)):
    with database() as (cursor, p):
        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role='student'")
        total = cursor.fetchone()['total']
        cursor.execute(f"SELECT u.id,u.name,u.email,u.username,u.role,u.is_active,u.must_change_password,COALESCE(s.phone,'') AS phone,s.school_grade,COALESCE(s.default_price_kopecks,0) AS default_price_kopecks,COALESCE(s.default_duration_minutes,60) AS default_duration_minutes FROM users u LEFT JOIN student_profiles s ON s.user_id=u.id WHERE u.role='student' ORDER BY u.id DESC LIMIT {p} OFFSET {p}", (limit, offset))
        items = [dict(row) for row in cursor.fetchall()]
    response.headers['Cache-Control'] = 'no-store'
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/trial-requests')
def requests(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(require_admin)):
    with database() as (cursor, p):
        cursor.execute('SELECT COUNT(*) AS total FROM trial_requests')
        total = cursor.fetchone()['total']
        cursor.execute(f'SELECT id,created_at,name,email,phone,courses,message,consent FROM trial_requests ORDER BY id DESC LIMIT {p} OFFSET {p}', (limit, offset))
        items = [dict(row) for row in cursor.fetchall()]
    response.headers['Cache-Control'] = 'no-store'
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


class StudentData(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9._-]+$')
    email: Optional[EmailStr] = Field(default=None, max_length=254)
    phone: str = Field(default='', max_length=40)
    school_grade: Optional[int] = Field(default=None, ge=1, le=11)
    default_price_kopecks: int = Field(ge=0, le=100000000, strict=True)
    default_duration_minutes: int = Field(ge=1, le=1440, strict=True)

    @field_validator('name', 'phone', mode='before')
    @classmethod
    def strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('username', mode='after')
    @classmethod
    def normalize(cls, value):
        return value.lower()


def temporary_password():
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(8))


def student_exists(cursor, p, user_id):
    cursor.execute(f"SELECT id FROM users WHERE id={p} AND role='student'", (user_id,))
    if not cursor.fetchone():
        raise HTTPException(404, 'Ученик не найден')


def write_student_profile(cursor, p, user_id, data):
    cursor.execute(f'SELECT user_id FROM student_profiles WHERE user_id={p}', (user_id,))
    values = (data.phone,data.school_grade,data.default_price_kopecks,data.default_duration_minutes)
    if cursor.fetchone():
        cursor.execute(f'UPDATE student_profiles SET phone={p},school_grade={p},default_price_kopecks={p},default_duration_minutes={p} WHERE user_id={p}', (*values,user_id))
    else:
        cursor.execute(f'INSERT INTO student_profiles (phone,school_grade,default_price_kopecks,default_duration_minutes,user_id) VALUES ({p},{p},{p},{p},{p})', (*values,user_id))


@router.post('/students', status_code=201)
def create_student(data: StudentData, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    password = temporary_password()
    try:
        with database() as (cursor,p):
            cursor.execute(f"INSERT INTO users (name,username,email,password_hash,role,must_change_password,is_active,created_at) VALUES ({p},{p},{p},{p},'student',1,1,{p})", (data.name,data.username,str(data.email).lower() if data.email else None,hash_password(password),int(time.time())))
            user_id = cursor.lastrowid
            write_student_profile(cursor,p,user_id,data)
    except (sqlite3.IntegrityError,mysql.connector.IntegrityError):
        raise HTTPException(409, 'Логин или email уже используется')
    response.headers['Cache-Control']='no-store'
    return {'id':user_id,'username':data.username,'email':str(data.email) if data.email else None,'temporary_password':password}


@router.put('/students/{user_id}')
def edit_student(user_id: int, data: StudentData, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    try:
        with database() as (cursor,p):
            student_exists(cursor,p,user_id)
            cursor.execute(f"UPDATE users SET name={p},username={p},email={p} WHERE id={p} AND role='student'", (data.name,data.username,str(data.email).lower() if data.email else None,user_id))
            write_student_profile(cursor,p,user_id,data)
    except (sqlite3.IntegrityError,mysql.connector.IntegrityError):
        raise HTTPException(409, 'Логин или email уже используется')
    response.headers['Cache-Control']='no-store'
    return {'status':'updated'}


@router.post('/students/{user_id}/reset-password')
def reset_student(user_id: int, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    password=temporary_password()
    with database() as (cursor,p):
        student_exists(cursor,p,user_id)
        cursor.execute(f'UPDATE users SET password_hash={p},must_change_password=1,password_changed_at={p} WHERE id={p}',(hash_password(password),int(time.time()),user_id))
        cursor.execute(f'DELETE FROM sessions WHERE user_id={p}',(user_id,))
        cursor.execute(f'SELECT username,email FROM users WHERE id={p}',(user_id,))
        student=cursor.fetchone()
    response.headers['Cache-Control']='no-store'
    return {'id':user_id,'username':student['username'],'email':student['email'],'temporary_password':password}


class ActiveState(BaseModel):
    is_active: bool


@router.patch('/students/{user_id}/active')
def active_student(user_id: int, data: ActiveState, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    with database() as (cursor,p):
        student_exists(cursor,p,user_id)
        cursor.execute(f'UPDATE users SET is_active={p} WHERE id={p}',(int(data.is_active),user_id))
        if not data.is_active:
            cursor.execute(f'DELETE FROM sessions WHERE user_id={p}',(user_id,))
    response.headers['Cache-Control']='no-store'
    return {'status':'updated'}


class CredentialsEmail(BaseModel):
    temporary_password: str = Field(min_length=8, max_length=128)


@router.post('/students/{user_id}/send-credentials')
def email_credentials(user_id: int, data: CredentialsEmail, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    throttle(request)
    with database() as (cursor,p):
        student_exists(cursor,p,user_id)
        cursor.execute(f'SELECT name,username,email,password_hash,must_change_password,is_active FROM users WHERE id={p}',(user_id,))
        student=cursor.fetchone()
        if not student['is_active'] or not student['must_change_password']:
            raise HTTPException(409, 'У аккаунта нет действующего временного пароля')
        if not student['email']:
            raise HTTPException(422, 'Сначала укажите email ученика')
        if not verify(data.temporary_password,student['password_hash']):
            raise HTTPException(409, 'Временный пароль уже изменён. Выполните сброс при необходимости.')
    try:
        send_student_credentials(student['email'],student['name'],student['username'],data.temporary_password)
    except ValueError as error:
        raise HTTPException(503, 'Проверьте настройки SMTP, SITE_URL и email отправителя') from error
    except (smtplib.SMTPException,OSError) as error:
        raise HTTPException(502, 'Почтовый сервер не принял письмо. Данные для ручной передачи остаются действительными.') from error
    response.headers['Cache-Control']='no-store'
    return {'status':'accepted','email':student['email']}
