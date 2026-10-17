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
import re
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, Literal

router = APIRouter(prefix='/api/admin', tags=['Administration'])


def require_admin(request: Request, response: Response):
    user = profile(request, response)
    if user['must_change_password']:
        raise HTTPException(403, 'Сначала смените временный пароль')
    if user['role'] != 'admin':
        raise HTTPException(403, 'Доступ только для администратора')
    return user


@router.get('/students')
def students(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
             search: str = Query('',max_length=200), view: Literal['all','active','debt','archive']='all',
             sort: Literal['newest','name','balance_asc','balance_desc']='newest',
             include_finance: bool=False, user=Depends(require_admin)):
    with database() as (c,p):
        if p=='?':
            c.execute('BEGIN')
        financial = include_finance or view=='debt' or sort in ('balance_asc','balance_desc')
        fields = "u.id,u.name,u.email,u.username,u.role,u.is_active,u.must_change_password,COALESCE(s.phone,'') AS phone,s.school_grade,s.timezone,COALESCE(s.default_price_kopecks,0) AS default_price_kopecks,COALESCE(s.default_duration_minutes,60) AS default_duration_minutes"
        joins = " FROM users u LEFT JOIN student_profiles s ON s.user_id=u.id"
        if financial:
            fields += ",CAST(COALESCE(paid.total,0) AS SIGNED)-CAST(COALESCE(spent.total,0) AS SIGNED) AS balance_kopecks"
            joins += " LEFT JOIN (SELECT student_id,SUM(amount_kopecks) AS total FROM payments WHERE voided_at IS NULL GROUP BY student_id) paid ON paid.student_id=u.id LEFT JOIN (SELECT student_id,SUM(price_kopecks) AS total FROM lessons WHERE status='completed' GROUP BY student_id) spent ON spent.student_id=u.id"
        source = " FROM (SELECT " + fields + joins + " WHERE u.role='student') student_list"
        clauses=['1=1'];args=[]
        if view=='active': clauses.append('is_active=1')
        elif view=='archive': clauses.append('is_active=0')
        elif view=='debt': clauses.append('balance_kopecks<0')
        if search.strip():
            pattern='%'+search.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            clauses.append(f"(name LIKE {p} ESCAPE '!' OR username LIKE {p} ESCAPE '!' OR email LIKE {p} ESCAPE '!')")
            args.extend([pattern]*3)
        where=' WHERE '+' AND '.join(clauses)
        c.execute('SELECT COUNT(*) AS total'+source+where,tuple(args))
        total=int(c.fetchone()['total'])
        order={'newest':'id DESC','name':'name ASC,id ASC','balance_asc':'balance_kopecks ASC,id ASC','balance_desc':'balance_kopecks DESC,id ASC'}[sort]
        c.execute('SELECT *'+source+where+' ORDER BY '+order+f' LIMIT {p} OFFSET {p}',(*args,limit,offset))
        items=[dict(row) for row in c.fetchall()]
        if financial:
            for row in items:
                row['balance_kopecks']=int(row['balance_kopecks'])
                row['debt_kopecks']=max(-row['balance_kopecks'],0)
    response.headers['Cache-Control']='no-store'
    return {'items':items,'total':total,'limit':limit,'offset':offset}


TrialStatus = Literal['new','contacting','trial_scheduled','enrolled','closed']
CloseReason = Literal['','declined','no_response','duplicate','spam','other']


@router.get('/trial-requests')
def requests(response: Response, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
             view: Literal['active','archive'] = 'active', status: Optional[TrialStatus] = None,
             search: str = Query('', max_length=200), user=Depends(require_admin)):
    with database() as (c,p):
        if p == '?':
            c.execute('BEGIN')
        source = " FROM trial_requests r LEFT JOIN trial_request_management m ON m.request_id=r.id"
        state = "COALESCE(m.status,'new')"
        c.execute("SELECT " + state + " AS status,COUNT(*) AS total" + source + " GROUP BY " + state)
        counts = {key:0 for key in ['new','contacting','trial_scheduled','enrolled','closed']}
        counts.update({row['status']:int(row['total']) for row in c.fetchall()})
        condition = state + (" IN ('enrolled','closed')" if view == 'archive' else " NOT IN ('enrolled','closed')")
        args = []
        if status:
            condition += f' AND {state}={p}'
            args.append(status)
        if search.strip():
            pattern = '%' + search.strip().replace('!','!!').replace('%','!%').replace('_','!_') + '%'
            condition += f" AND (r.name LIKE {p} ESCAPE '!' OR r.email LIKE {p} ESCAPE '!' OR r.phone LIKE {p} ESCAPE '!')"
            args.extend([pattern]*3)
        c.execute('SELECT COUNT(*) AS total'+source+' WHERE '+condition,tuple(args))
        total = int(c.fetchone()['total'])
        c.execute("SELECT r.*,COALESCE(m.status,'new') AS status,COALESCE(m.admin_note,'') AS admin_note,COALESCE(m.close_reason,'') AS close_reason,COALESCE(m.version,0) AS version,m.updated_at"+source+' WHERE '+condition+f' ORDER BY r.id DESC LIMIT {p} OFFSET {p}',(*args,limit,offset))
        items = [dict(row) for row in c.fetchall()]
    response.headers['Cache-Control']='no-store'
    return {'items':items,'total':total,'limit':limit,'offset':offset,'counts':counts,
            'active_total':sum(counts[k] for k in ['new','contacting','trial_scheduled']),
            'archive_total':counts['enrolled']+counts['closed']}


class TrialUpdate(BaseModel):
    status: TrialStatus
    admin_note: str = Field(default='', max_length=2000)
    close_reason: CloseReason = ''
    version: int = Field(ge=0, strict=True)

    @field_validator('admin_note', mode='before')
    @classmethod
    def clean_note(cls,value):
        return value.strip() if isinstance(value,str) else value


@router.patch('/trial-requests/{request_id}')
def update_trial(request_id: int, data: TrialUpdate, request:Request, response:Response, user=Depends(require_admin)):
    guard(request)
    if data.status=='closed' and not data.close_reason:
        raise HTTPException(422,'Укажите причину закрытия заявки')
    reason=data.close_reason if data.status=='closed' else ''
    with database() as (c,p):
        if p=='?':
            c.execute('BEGIN IMMEDIATE')
        c.execute(f'SELECT id FROM trial_requests WHERE id={p}' + (' FOR UPDATE' if p!='?' else ''),(request_id,))
        if not c.fetchone():
            raise HTTPException(404,'Заявка не найдена')
        c.execute(f'SELECT version FROM trial_request_management WHERE request_id={p}',(request_id,))
        old=c.fetchone()
        current=int(old['version']) if old else 0
        if current!=data.version:
            raise HTTPException(409,'Заявка уже изменена в другом окне. Скопируйте заметку и обновите список перед повторным сохранением.')
        values=(data.status,data.admin_note,reason,current+1,int(time.time()),user['id'],request_id)
        if old:
            c.execute(f'UPDATE trial_request_management SET status={p},admin_note={p},close_reason={p},version={p},updated_at={p},updated_by={p} WHERE request_id={p}',values)
        else:
            c.execute('INSERT INTO trial_request_management (status,admin_note,close_reason,version,updated_at,updated_by,request_id) VALUES ('+','.join([p]*7)+')',values)
    response.headers['Cache-Control']='no-store'
    return {'status':'saved','version':current+1}


class StudentData(BaseModel):
    timezone: str | None = Field(default=None, max_length=100)

    @field_validator('timezone')
    @classmethod
    def timezone_valid(cls, value):
        from student_timezones import validate_zone
        return validate_zone(value)

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


class StudentEditData(StudentData):
    # Legacy accounts used email as the login. Preserve existing identifiers;
    # only newly assigned logins must satisfy the current format.
    username: str = Field(min_length=1, max_length=254)


def temporary_password():
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(8))


def student_exists(cursor, p, user_id):
    cursor.execute(f"SELECT id,username FROM users WHERE id={p} AND role='student'", (user_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, 'Ученик не найден')
    return dict(row)


def write_student_profile(cursor, p, user_id, data):
    cursor.execute(f'SELECT user_id FROM student_profiles WHERE user_id={p}', (user_id,))
    values = (data.phone,data.school_grade,data.default_price_kopecks,data.default_duration_minutes,data.timezone)
    if cursor.fetchone():
        cursor.execute(f'UPDATE student_profiles SET phone={p},school_grade={p},default_price_kopecks={p},default_duration_minutes={p},timezone={p} WHERE user_id={p}', (*values,user_id))
    else:
        cursor.execute(f'INSERT INTO student_profiles (phone,school_grade,default_price_kopecks,default_duration_minutes,timezone,user_id) VALUES ({p},{p},{p},{p},{p},{p})', (*values,user_id))


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
def edit_student(user_id: int, data: StudentEditData, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    try:
        with database() as (cursor,p):
            existing = student_exists(cursor,p,user_id)
            if data.username != existing['username'] and not re.fullmatch(r'[a-zA-Z0-9._-]{3,40}', data.username):
                raise HTTPException(422, 'Новый логин: от 3 до 40 символов, латиница, цифры, точка, дефис или подчёркивание')
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
