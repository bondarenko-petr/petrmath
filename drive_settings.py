"""Administrator-only Google Drive setup. No archive cleanup runs in this module."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlsplit
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ConfigDict, SecretStr
from accounts import COOKIE, guard, throttle
from admin import require_admin
from database import ROOT

def no_store(response:Response):response.headers['Cache-Control']='no-store'

router=APIRouter(prefix='/api/admin/archive-settings',tags=['Archive settings'],dependencies=[Depends(no_store)])
SCOPE='https://www.googleapis.com/auth/drive.file'
FIELDS=['GOOGLE_DRIVE_CLIENT_ID','GOOGLE_DRIVE_CLIENT_SECRET','GOOGLE_DRIVE_REDIRECT_URI']

@contextlib.contextmanager
def storage():
    folder=Path(os.getenv('GOOGLE_DRIVE_PRIVATE_DIR',str(ROOT/'data'/'google-drive'))).resolve()
    public=(ROOT/'landing'/'dist').resolve()
    if folder==public or public in folder.parents:raise HTTPException(503,'Каталог настроек должен находиться вне публичной папки сайта')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(folder,0o700)
    with open(folder/'lock','a') as lock:
        os.chmod(folder/'lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        path=folder/'settings.json'
        try:data=json.loads(path.read_text()) if path.exists() else {}
        except (ValueError,OSError):raise HTTPException(503,'Не удалось прочитать настройки Google Drive')
        try:
            yield data
            tmp=folder/('settings-'+secrets.token_hex(8)+'.tmp')
            try:
                fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as stream:
                    json.dump(data,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
                os.replace(tmp,path)
            finally:tmp.unlink(missing_ok=True)
        finally:fcntl.flock(lock,fcntl.LOCK_UN)

def effective_config(data):
    return data.get('app_config') or {key:os.getenv(env,'') for key,env in zip(('client_id','client_secret','redirect_uri'),FIELDS)}

def validate_config(config,status=503):
    missing=[env for key,env in zip(('client_id','client_secret','redirect_uri'),FIELDS) if not config.get(key)]
    if missing:raise HTTPException(status,'Не заданы параметры: '+', '.join(missing))
    try:parsed=urlsplit(config['redirect_uri']);hostname=parsed.hostname;port=parsed.port
    except ValueError:raise HTTPException(status,'Проверьте адрес возврата Google Drive')
    local=hostname in ('localhost','127.0.0.1')
    if not hostname or (parsed.scheme!='https' and not (parsed.scheme=='http' and local)):raise HTTPException(status,'Адрес возврата должен использовать HTTPS (HTTP разрешён только для localhost)')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path!='/api/admin/archive-settings/callback':raise HTTPException(status,'Проверьте адрес возврата Google Drive')
    return config

def configuration(data):return validate_config(effective_config(data))

def session_stamp(request):return hashlib.sha256(request.cookies.get(COOKIE,'').encode()).hexdigest()

def log(data,message):
    events=data.setdefault('events',[]);events.insert(0,{'at':int(time.time()),'message':message});del events[20:]

def public(data):
    connection=data.get('connection',{});config=effective_config(data)
    return {'client_id':config.get('client_id',''),'secret_saved':bool(config.get('client_secret')),'config_source':'settings' if data.get('app_config') else 'environment','configured':all(config.get(key) for key in ('client_id','client_secret','redirect_uri')),'missing':[env for key,env in zip(('client_id','client_secret','redirect_uri'),FIELDS) if not config.get(key)],'redirect_uri':config.get('redirect_uri',''),'connected':bool(connection.get('refresh_token')),'email':connection.get('email',''),'folder_id':connection.get('folder_id',''),'folder_name':connection.get('folder_name',''),'retention_days':data.get('retention_days',28),'grace_days':data.get('grace_days',14),'mode':'manual','deletion_enabled':bool(data.get('deletion_enabled',False)),'cleanup_last_finished':data.get('cleanup_last_finished'),'cleanup_result':data.get('cleanup_result'),'events':data.get('events',[])}

@router.get('')
def settings(response:Response,user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    with storage() as data:return public(data)

class Retention(BaseModel):
    model_config=ConfigDict(extra='forbid')
    retention_days:int=Field(28,ge=7,le=365)
    grace_days:int=Field(14,ge=7,le=90)

@router.put('')
def save_settings(values:Retention,request:Request,user=Depends(require_admin)):
    guard(request)
    with storage() as data:
        data.update(values.model_dump());log(data,'Сроки хранения сохранены.')
        return public(data)

class OAuthConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    client_id:str=Field(min_length=1,max_length=300)
    client_secret:SecretStr|None=None
    redirect_uri:str=Field(min_length=1,max_length=1000)

@router.put('/oauth-config')
def save_oauth_config(values:OAuthConfig,request:Request,user=Depends(require_admin)):
    guard(request);throttle(request)
    with storage() as data:
        previous=effective_config(data)
        supplied=values.client_secret.get_secret_value().strip() if values.client_secret else ''
        client_id=values.client_id.strip()
        if not supplied and client_id!=previous.get('client_id'):raise HTTPException(422,'При смене Client ID укажите новый Client Secret')
        secret=supplied or previous.get('client_secret','')
        if not secret or len(secret)>500 or any(ch.isspace() for ch in secret):raise HTTPException(422,'Укажите корректный Client Secret')
        if not client_id.endswith('.apps.googleusercontent.com') or any(ch.isspace() for ch in client_id):raise HTTPException(422,'Client ID должен заканчиваться на .apps.googleusercontent.com')
        config=validate_config({'client_id':client_id,'client_secret':secret,'redirect_uri':values.redirect_uri.strip()},422)
        changed=config!=previous
        data['app_config']=config
        if changed:
            data.pop('connection',None);data.pop('oauth',None)
            log(data,'Параметры Google обновлены. Требуется заново подключить диск. Архивы в Drive сохранены.')
        return public(data)

@router.post('/connect')
def connect(request:Request,user=Depends(require_admin)):
    guard(request);throttle(request)
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    with storage() as data:
        config=configuration(data)
        pending=data.setdefault('oauth',{});now=int(time.time())
        for key in list(pending):
            if pending[key]['expires']<=now:del pending[key]
        pending[hashlib.sha256(state.encode()).hexdigest()]={'owner':user['id'],'session':session_stamp(request),'expires':now+600,'verifier':verifier}
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return {'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':config['client_id'],'redirect_uri':config['redirect_uri'],'response_type':'code','scope':SCOPE,'access_type':'offline','prompt':'consent select_account','state':state,'code_challenge':challenge,'code_challenge_method':'S256'})}

def checked(response):
    if not response.is_success:raise ValueError('google_api_failed')
    return response.json()

def access(client,connection,data):
    config=configuration(data)
    result=checked(client.post('https://oauth2.googleapis.com/token',data={'client_id':config['client_id'],'client_secret':config['client_secret'],'refresh_token':connection['refresh_token'],'grant_type':'refresh_token'}))
    return {'Authorization':'Bearer '+result['access_token']}

@router.get('/callback')
def callback(request:Request,state:str='',code:str='',error:str='',user=Depends(require_admin)):
    result='failed'
    with storage() as data:
        pending=data.setdefault('oauth',{}).pop(hashlib.sha256(state.encode()).hexdigest(),None)
        if not pending or pending['owner']!=user['id'] or pending['session']!=session_stamp(request) or pending['expires']<=int(time.time()):
            result='invalid'
        elif error or not code:log(data,'Подключение Google Drive отменено.')
        else:
            try:
                config=configuration(data)
                with httpx.Client(timeout=20,follow_redirects=False) as client:
                    token=checked(client.post('https://oauth2.googleapis.com/token',data={**config,'grant_type':'authorization_code','code':code,'code_verifier':pending['verifier']}))
                    if not token.get('refresh_token') or SCOPE not in token.get('scope','').split():raise ValueError('missing_permission')
                    headers={'Authorization':'Bearer '+token['access_token']}
                    about=checked(client.get('https://www.googleapis.com/drive/v3/about',headers=headers,params={'fields':'user(emailAddress,permissionId)'}))['user']
                    # Find only a folder created by this application, never broaden Drive access.
                    folders=checked(client.get('https://www.googleapis.com/drive/v3/files',headers=headers,params={'q':"trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has { key='krug_pi_archives' and value='1' }",'fields':'files(id,name)','pageSize':100}))['files']
                    folder=folders[0] if folders else checked(client.post('https://www.googleapis.com/drive/v3/files',headers=headers,params={'fields':'id,name'},json={'name':'Круг Пи — архивы учеников','mimeType':'application/vnd.google-apps.folder','appProperties':{'krug_pi_archives':'1'}}))
                    data['connection']={'refresh_token':token['refresh_token'],'email':about.get('emailAddress',''),'folder_id':folder['id'],'folder_name':folder['name']}
                    log(data,'Google Drive подключён. Создана или найдена папка архивов.');result='connected'
            except Exception:log(data,'Не удалось подключить Google Drive. Проверьте настройки приложения и разрешения.')
    return RedirectResponse('/archive-settings.html?connection='+result,status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

@router.post('/test')
def test_connection(request:Request,user=Depends(require_admin)):
    guard(request);throttle(request);failure=False
    with storage() as data:
        connection=data.get('connection')
        if not connection:raise HTTPException(409,'Сначала подключите Google Drive')
        file_id=None;cleaned=False
        try:
            with httpx.Client(timeout=20,follow_redirects=False) as client:
                headers=access(client,connection,data)
                folder=checked(client.get('https://www.googleapis.com/drive/v3/files/'+connection['folder_id'],headers=headers,params={'fields':'id,trashed,mimeType'}))
                if folder.get('trashed') or folder.get('mimeType')!='application/vnd.google-apps.folder':raise ValueError('folder_unavailable')
                content=('Круг Пи: проверка '+secrets.token_hex(16)).encode();boundary=secrets.token_hex(16)
                meta=json.dumps({'name':'krug-pi-connection-test.txt','parents':[connection['folder_id']]}).encode()
                body=b'--'+boundary.encode()+b'\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'+meta+b'\r\n--'+boundary.encode()+b'\r\nContent-Type: text/plain\r\n\r\n'+content+b'\r\n--'+boundary.encode()+b'--\r\n'
                try:
                    uploaded=checked(client.post('https://www.googleapis.com/upload/drive/v3/files',params={'uploadType':'multipart','fields':'id'},headers={**headers,'Content-Type':'multipart/related; boundary='+boundary},content=body));file_id=uploaded['id']
                    downloaded=client.get('https://www.googleapis.com/drive/v3/files/'+file_id,headers=headers,params={'alt':'media'})
                    if not downloaded.is_success or hashlib.sha256(downloaded.content).digest()!=hashlib.sha256(content).digest():raise ValueError('checksum_mismatch')
                finally:
                    if file_id:cleaned=client.delete('https://www.googleapis.com/drive/v3/files/'+file_id,headers=headers).is_success
                if not cleaned:raise ValueError('cleanup_failed')
            log(data,'Проверка пройдена: тестовый файл загружен, скачан, сверен и удалён.')
        except Exception:
            failure=True;log(data,'Проверка не пройдена. '+('Тестовый файл мог остаться в папке Drive.' if file_id and not cleaned else 'Проверьте подключение, права и свободное место.'))
        output=public(data)
    if failure:raise HTTPException(502,'Проверка Google Drive не пройдена. Подробности в журнале настроек.')
    return output

@router.post('/disconnect')
def disconnect(request:Request,user=Depends(require_admin)):
    guard(request)
    with storage() as data:
        data.pop('connection',None);data.pop('oauth',None);log(data,'Подключение отключено на сервере. Файлы в Drive сохранены.')
    return {'status':'disconnected'}


class CleanupMode(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool

@router.post('/cleanup-mode')
def cleanup_mode(values:CleanupMode,request:Request,user=Depends(require_admin)):
    guard(request)
    if values.enabled:
        from accounts import database
        with database() as (c,p):c.execute('SELECT verified_at,notified_at,cleanup_at FROM material_archives LIMIT 1');c.fetchall()
        if any(not os.getenv(key) for key in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM','SITE_URL')):raise HTTPException(422,'Сначала настройте SMTP и SITE_URL для уведомлений')
        base=urlsplit(os.getenv('SITE_URL',''))
        if base.scheme!='https' or not base.hostname or base.username or base.password or base.query or base.fragment:raise HTTPException(422,'Для уведомлений задайте корректный HTTPS SITE_URL')
    with storage() as data:
        if values.enabled:
            configuration(data)
            if not data.get('connection'):raise HTTPException(409,'Сначала подключите Google Drive')
        data['deletion_enabled']=values.enabled
        if values.enabled:data['cleanup_last_started']=0
        log(data,'Автоматическая очистка '+('включена. Проверенные архивы будут обработаны после уведомления и резервного срока.' if values.enabled else 'выключена.'))
        return public(data)

@router.post('/cleanup-run')
def cleanup_run(request:Request,tasks:BackgroundTasks,user=Depends(require_admin)):
    guard(request);throttle(request)
    with storage() as data:
        if not data.get('deletion_enabled'):raise HTTPException(409,'Автоматическая очистка выключена')
    from archive_cleanup import run_cycle
    tasks.add_task(run_cycle,True)
    return {'status':'started'}
