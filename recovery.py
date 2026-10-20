"""One-use email links. Raw tokens never enter the database or logs."""
import hashlib
import logging
import secrets
import time
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from accounts import database, profile, guard, throttle, hash_password
from mailer import send_account_link

router=APIRouter(prefix='/api/auth',tags=['Account recovery'])
GENERIC='Если этот адрес привязан к аккаунту и подтверждён, мы отправили ссылку для восстановления. Проверьте также папку «Спам».'

def ensure_schema(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS account_links (token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,purpose TEXT NOT NULL,email TEXT NOT NULL,password_stamp TEXT NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS verified_emails (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,email TEXT NOT NULL,password_stamp TEXT NOT NULL)')

def stamp(value):return hashlib.sha256(value.encode()).hexdigest()

def safe_send(email,purpose,token=None):
    try:send_account_link(email,purpose,token)
    except Exception:logging.getLogger(__name__).warning('Account email delivery failed (%s)',purpose)

def lock_user(c,p,user_id):
    c.execute(f'SELECT * FROM users WHERE id={p}'+(' FOR UPDATE' if p!='?' else ''),(user_id,))
    row=c.fetchone()
    return dict(row) if row else None

def issue(c,p,user,purpose):
    now=int(time.time())
    c.execute(f'SELECT MAX(created_at) AS last FROM account_links WHERE user_id={p} AND purpose={p}',(user['id'],purpose))
    last=c.fetchone()['last']
    if last is not None and now-last<60:return None
    token=secrets.token_urlsafe(32)
    c.execute(f'DELETE FROM account_links WHERE user_id={p} AND purpose={p}',(user['id'],purpose))
    c.execute(f'INSERT INTO account_links (token_hash,user_id,purpose,email,password_stamp,expires_at,created_at) VALUES ({",".join([p]*7)})',(stamp(token),user['id'],purpose,user['email'].lower(),stamp(user['password_hash']),now+1800,now))
    return token

@router.get('/email-status')
def email_status(request:Request,response:Response):
    user=profile(request,response)
    with database() as (c,p):
        c.execute(f'SELECT email FROM verified_emails WHERE user_id={p}',(user['id'],))
        verified=c.fetchone()
    return {'email':user['email'],'verified':bool(verified and user['email'] and verified['email']==user['email'].lower())}

@router.post('/verify-email/request')
def request_verification(request:Request,response:Response,tasks:BackgroundTasks):
    guard(request);throttle(request);user=profile(request,response)
    if user['must_change_password']:raise HTTPException(403,'Сначала смените временный пароль')
    with database() as (c,p):
        if p=='?':c.execute('BEGIN IMMEDIATE')
        user=lock_user(c,p,user['id'])
        if not user or not user['is_active'] or not user['email']:raise HTTPException(422,'Сначала укажите email в профиле')
        token=issue(c,p,user,'verify')
    if token:tasks.add_task(safe_send,user['email'],'verify',token)
    return {'message':'Если письмо ещё не отправлено, ссылка придёт на указанную почту. Повторный запрос доступен через 60 секунд.'}

class EmailRequest(BaseModel):email:EmailStr
class LinkRequest(BaseModel):token:str=Field(min_length=20,max_length=200)
class ResetRequest(LinkRequest):new_password:str=Field(min_length=10,max_length=128)

@router.post('/forgot-password')
def forgot(data:EmailRequest,request:Request,tasks:BackgroundTasks):
    guard(request);throttle(request)
    with database() as (c,p):
        if p=='?':c.execute('BEGIN IMMEDIATE')
        c.execute(f'SELECT id FROM users WHERE LOWER(email)={p} AND is_active=1',(str(data.email).lower(),))
        ids=c.fetchall();user=None;token=None
        if len(ids)==1:
            user=lock_user(c,p,ids[0]['id'])
            c.execute(f'SELECT email FROM verified_emails WHERE user_id={p}',(user['id'],));verified=c.fetchone()
            if verified and verified['email']==user['email'].lower():token=issue(c,p,user,'reset')
    if token:tasks.add_task(safe_send,user['email'],'reset',token)
    return {'message':GENERIC}

def consume(data,purpose):
    with database() as (c,p):
        if p=='?':c.execute('BEGIN IMMEDIATE')
        # Read owner first, then lock that user consistently with link issuance.
        c.execute(f'SELECT user_id FROM account_links WHERE token_hash={p}',(stamp(data.token),));owner=c.fetchone()
        user=lock_user(c,p,owner['user_id']) if owner else None
        c.execute(f'SELECT * FROM account_links WHERE token_hash={p}',(stamp(data.token),));link=c.fetchone()
        if not user or not link or not user['is_active'] or link['purpose']!=purpose or link['expires_at']<=int(time.time()) or (user['email'] or '').lower()!=link['email'] or stamp(user['password_hash'])!=link['password_stamp']:
            raise HTTPException(400,'Ссылка недействительна или истекла. Запросите новую.')
        if purpose=='verify':
            c.execute(f'DELETE FROM verified_emails WHERE user_id={p}',(user['id'],))
            c.execute(f'INSERT INTO verified_emails (user_id,email,password_stamp) VALUES ({p},{p},{p})',(user['id'],link['email'],link['password_stamp']))
            c.execute(f'DELETE FROM account_links WHERE token_hash={p}',(stamp(data.token),))
        else:
            c.execute(f'SELECT email FROM verified_emails WHERE user_id={p}',(user['id'],));verified=c.fetchone()
            if not verified or verified['email']!=link['email']:raise HTTPException(400,'Ссылка недействительна. Подтвердите почту.')
            c.execute(f'UPDATE users SET password_hash={p},must_change_password=0,password_changed_at={p} WHERE id={p}',(hash_password(data.new_password),int(time.time()),user['id']))
            c.execute(f'DELETE FROM sessions WHERE user_id={p}',(user['id'],))
            c.execute(f'DELETE FROM account_links WHERE user_id={p}',(user['id'],))
    return user['email']

@router.post('/verify-email/confirm')
def verify_email(data:LinkRequest,request:Request):
    guard(request);throttle(request);consume(data,'verify');return {'message':'Почта подтверждена. Теперь можно восстанавливать пароль по email.'}

@router.post('/reset-password')
def reset(data:ResetRequest,request:Request,tasks:BackgroundTasks,response:Response):
    guard(request);throttle(request);email=consume(data,'reset');tasks.add_task(safe_send,email,'changed')
    response.headers['Cache-Control']='no-store'
    return {'message':'Пароль изменён. Войдите с новым паролем.'}
