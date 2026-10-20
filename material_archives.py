"""Manual ZIP archives. Originals are never removed or modified."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from datetime import datetime,timezone
from urllib.parse import urlsplit,quote
from zipfile import ZipFile, ZIP_DEFLATED
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from accounts import database,guard,throttle
from admin import require_admin
from lessons import member
from materials import storage as material_storage
from student_timezones import student_zone
import drive_settings as drive

router=APIRouter(prefix='/api/material-archives',tags=['Material archives'])
MAX_BYTES=200*1024*1024
ACTIVE=('building','uploading','verifying')

class ArchiveInput(BaseModel):
    student_id:int=Field(gt=0)
    include_recent:bool=False

def safe_name(value):
    cleaned=re.sub(r'[^\w .-]','_',value,flags=re.UNICODE).strip(' ._')[:70]
    return cleaned or 'Математика'

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def select_materials(c,p,student,days,include_recent):
    c.execute(f'SELECT manifest FROM material_archives WHERE student_id={p} AND status={p}',(student,'verified'))
    archived={f['id'] for row in c.fetchall() for lesson in json.loads(row['manifest']) for f in lesson['files']}
    cutoff=int(time.time())-days*86400
    c.execute(f"SELECT l.*,m.homework,m.notes,m.due_mode,m.due_date,m.version AS material_version FROM lessons l LEFT JOIN lesson_materials m ON m.lesson_id=l.id WHERE l.student_id={p} AND l.status='completed' ORDER BY l.starts_at,l.id",(student,))
    lessons=[dict(row) for row in c.fetchall()];result=[];total=0;count=0
    for lesson in lessons:
        c.execute(f'SELECT id,category,storage_key,filename,size,created_at FROM material_files WHERE lesson_id={p} AND deleted_at IS NULL ORDER BY created_at,id',(lesson['id'],))
        files=[dict(f) for f in c.fetchall() if f['id'] not in archived and (include_recent or f['created_at']<=cutoff)]
        if not files:continue
        total+=sum(f['size'] for f in files);count+=len(files)
        if total>MAX_BYTES or count>1000:raise HTTPException(422,'За один раз можно архивировать до 200 МБ и 1000 файлов. Обратитесь к администратору для разделения материалов.')
        lesson['files']=files;result.append(lesson)
    if not result:raise HTTPException(409,'Подходящих файлов нет: они ещё не достигли срока хранения или уже включены в проверенный архив.')
    return result

def build_zip(path,manifest,tz):
    from zoneinfo import ZoneInfo
    root=material_storage();index=[];expected=[];stamp=datetime.now(timezone.utc).isoformat()
    with ZipFile(path,'w',ZIP_DEFLATED) as archive:
        for lesson in manifest:
            date=datetime.fromtimestamp(lesson['starts_at'],ZoneInfo(tz)).strftime('%Y-%m-%d_%H-%M')
            folder=date+'_'+safe_name(lesson['topic'] or 'Математика')+'_урок-'+str(lesson['id'])
            links=[]
            for key,label in [('homework','Задание'),('notes','Конспект')]:
                value=lesson.get(key) or ''
                if key=='homework':
                    due=lesson.get('due_date');value+=('\n\nСрок: '+str(due)) if due else '\n\nСрок: к следующему занятию'
                name=folder+'/'+label+'.txt';archive.writestr(name,value);expected.append(name);links.append(name)
            counts={}
            for file in lesson['files']:
                target=(root/file['storage_key']).resolve()
                if target.parent!=root or not target.is_file() or target.stat().st_size!=file['size']:raise ValueError('source_unavailable')
                category=file['category'];counts[category]=counts.get(category,0)+1
                ext=Path(file['filename']).suffix.lower()
                if ext not in ('.pdf','.jpg','.jpeg','.png'):ext='.bin'
                name=folder+'/'+('Задание' if category=='homework' else 'Конспект')+'_'+str(counts[category])+ext
                # Hash exactly the bytes added to ZIP, retaining a source manifest for later cleanup.
                h=hashlib.sha256();written=0
                with open(target,'rb') as source,archive.open(name,'w') as output:
                    for chunk in iter(lambda:source.read(1024*1024),b''):
                        written+=len(chunk)
                        if written>file['size']:raise ValueError('source_changed')
                        h.update(chunk);output.write(chunk)
                if written!=file['size']:raise ValueError('source_changed')
                file['sha256']=h.hexdigest();file['archive_path']=name;expected.append(name);links.append(name)
            index.append('<h2>'+html.escape(date+' · '+(lesson['topic'] or 'Математика'))+'</h2><ul>'+''.join('<li><a href="'+quote(name,safe='/')+'">'+html.escape(name.split('/')[-1])+'</a></li>' for name in links)+'</ul>')
        archive.writestr('Содержание.html','<!doctype html><meta charset="utf-8"><title>Материалы уроков</title><h1>Задания и конспекты</h1><p>Часовой пояс: '+html.escape(tz)+'</p><p>Создано (UTC): '+stamp+'</p>'+''.join(index))
        archive.writestr('manifest.json',json.dumps([{'lesson_id':row['id'],'topic':row['topic'],'starts_at':row['starts_at'],'timezone':tz,'files':[{key:file.get(key) for key in ('id','filename','category','size','sha256','archive_path')} for file in row['files']]} for row in manifest],ensure_ascii=False,default=str))
    with ZipFile(path) as archive:
        if archive.testzip() is not None or set(archive.namelist())!=set(expected+['Содержание.html','manifest.json']):raise ValueError('zip_invalid')

def snapshot_drive():
    with drive.storage() as data:
        if not data.get('connection'):raise HTTPException(409,'Сначала подключите Google Drive в настройках')
        drive.configuration(data)
        return json.loads(json.dumps(data))

def remote_download(client,headers,file_id,target,expected_size,expected_hash):
    url='https://www.googleapis.com/drive/v3/files/'+quote(file_id,safe='')
    total=0;h=hashlib.sha256()
    with client.stream('GET',url,headers=headers,params={'alt':'media'}) as response:
        if not response.is_success:raise ValueError('drive_download_failed')
        with open(target,'wb') as output:
            for chunk in response.iter_bytes(1024*1024):
                total+=len(chunk)
                if total>expected_size:raise ValueError('size_mismatch')
                h.update(chunk);output.write(chunk)
    if total!=expected_size or h.hexdigest()!=expected_hash:raise ValueError('checksum_mismatch')

def remote_upload(client,headers,connection,path,filename,archive_id):
    metadata={'name':filename,'parents':[connection['folder_id']],'appProperties':{'krug_pi_archive':archive_id}}
    response=client.post('https://www.googleapis.com/upload/drive/v3/files',params={'uploadType':'resumable','fields':'id'},headers={**headers,'X-Upload-Content-Type':'application/zip','X-Upload-Content-Length':str(path.stat().st_size)},json=metadata)
    if not response.is_success:raise ValueError('upload_failed')
    url=response.headers.get('Location','');parts=urlsplit(url)
    if parts.scheme!='https' or parts.hostname!='www.googleapis.com' or not parts.path.startswith('/upload/drive/'):raise ValueError('invalid_upload_location')
    with open(path,'rb') as payload:
        result=drive.checked(client.put(url,headers={**headers,'Content-Type':'application/zip','Content-Length':str(path.stat().st_size)},content=iter(lambda:payload.read(1024*1024),b'')))
    return result['id']

def update(archive_id,status,**values):
    with database() as (c,p):
        fields={'status':status,'updated_at':int(time.time()),**values}
        c.execute('UPDATE material_archives SET '+','.join(key+'='+p for key in fields)+f" WHERE id={p} AND status IN ('building','uploading','verifying')",(*fields.values(),archive_id))
        return c.rowcount

def create_job(archive_id,manifest,tz,filename,config):
    file_id=None;headers=None
    try:
        with tempfile.TemporaryDirectory(prefix='krug-pi-archive-') as folder:
            path=Path(folder)/'archive.zip';build_zip(path,manifest,tz)
            size=path.stat().st_size
            if size>MAX_BYTES+10*1024*1024:raise ValueError('archive_too_large')
            checksum=digest(path);update(archive_id,'uploading')
            with httpx.Client(timeout=120,follow_redirects=False) as client:
                headers=drive.access(client,config['connection'],config)
                file_id=remote_upload(client,headers,config['connection'],path,filename,archive_id)
                update(archive_id,'verifying',drive_id=file_id)
                remote_download(client,headers,file_id,Path(folder)/'verify.zip',size,checksum)
                if not update(archive_id,'verified',size=size,sha256=checksum,manifest=json.dumps(manifest,ensure_ascii=False,default=str)):
                    raise ValueError('archive_removed')
    except Exception:
        if file_id and headers:
            try:
                with httpx.Client(timeout=20) as client:client.delete('https://www.googleapis.com/drive/v3/files/'+quote(file_id,safe=''),headers=headers)
            except Exception:pass
        update(archive_id,'failed',error='Не удалось создать или проверить архив. Исходные файлы сохранены. Проверьте Drive, наличие исходников и свободное место.')

@router.post('',status_code=202)
def create(data:ArchiveInput,request:Request,tasks:BackgroundTasks,user=Depends(require_admin)):
    guard(request);throttle(request);config=snapshot_drive();archive_id=secrets.token_hex(16);now=int(time.time())
    with database() as (c,p):
        if p=='?':c.execute('BEGIN IMMEDIATE')
        c.execute(f"SELECT id FROM users WHERE id={p} AND role='student'"+(' FOR UPDATE' if p!='?' else ''),(data.student_id,))
        if not c.fetchone():raise HTTPException(404,'Ученик не найден')
        c.execute(f"SELECT id,updated_at FROM material_archives WHERE student_id={p} AND status IN ('building','uploading','verifying')",(data.student_id,))
        pending=c.fetchall()
        for row in pending:
            if now-row['updated_at']<3600:raise HTTPException(409,'Архив этого ученика уже создаётся. Дождитесь завершения.')
            c.execute(f'UPDATE material_archives SET status={p},error={p},updated_at={p} WHERE id={p}',('failed','Создание было прервано. Исходные материалы сохранены.',now,row['id']))
        manifest=select_materials(c,p,data.student_id,config.get('retention_days',28),data.include_recent)
        tz=student_zone(c,p,data.student_id)
        from zoneinfo import ZoneInfo
        dates=[datetime.fromtimestamp(row['starts_at'],ZoneInfo(tz)).strftime('%Y-%m-%d') for row in manifest]
        filename='Материалы_'+min(dates)+'_'+max(dates)+'_'+archive_id[:8]+'.zip'
        count=sum(len(row['files']) for row in manifest)
        c.execute('INSERT INTO material_archives (id,student_id,created_by,created_at,updated_at,status,filename,file_count,lesson_count,drive_account,manifest) VALUES ('+','.join([p]*11)+')',(archive_id,data.student_id,user['id'],now,now,'building',filename,count,len(manifest),config['connection'].get('email',''),json.dumps(manifest,ensure_ascii=False,default=str)))
    tasks.add_task(create_job,archive_id,manifest,tz,filename,config)
    return {'id':archive_id,'status':'building'}

@router.get('')
def list_archives(response:Response,student_id:int|None=Query(None,gt=0),limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),user=Depends(member)):
    owner=user['id'] if user['role']=='student' else student_id
    condition='1=1';args=[]
    if owner is not None:condition+=' AND student_id=%s';args.append(owner)
    with database() as (c,p):
        condition=condition.replace('%s',p)
        if user['role']=='student':condition+=" AND status='verified'"
        c.execute('SELECT COUNT(*) AS n FROM material_archives WHERE '+condition,tuple(args));total=c.fetchone()['n']
        c.execute('SELECT id,student_id,status,filename,file_count,lesson_count,size,created_at,updated_at,error FROM material_archives WHERE '+condition+f' ORDER BY created_at DESC,id DESC LIMIT {p} OFFSET {p}',(*args,limit,offset))
        rows=[dict(row) for row in c.fetchall()]
    response.headers['Cache-Control']='no-store'
    return {'items':rows,'total':total}

@router.get('/{archive_id}/download')
def download(archive_id:str,request:Request,user=Depends(member)):
    throttle(request)
    with database() as (c,p):
        c.execute(f'SELECT * FROM material_archives WHERE id={p}',(archive_id,));row=c.fetchone()
    if not row or (user['role']!='admin' and row['student_id']!=user['id']):raise HTTPException(404,'Архив не найден')
    if row['status']!='verified':raise HTTPException(409,'Архив ещё не прошёл проверку')
    config=snapshot_drive()
    if config['connection'].get('email','')!=row['drive_account']:raise HTTPException(409,'Архив находится в другом Google-аккаунте. Обратитесь к администратору.')
    fd,name=tempfile.mkstemp(prefix='krug-pi-download-',suffix='.zip');os.close(fd);path=Path(name)
    try:
        with httpx.Client(timeout=120,follow_redirects=False) as client:
            headers=drive.access(client,config['connection'],config)
            remote_download(client,headers,row['drive_id'],path,row['size'],row['sha256'])
    except Exception:
        path.unlink(missing_ok=True);raise HTTPException(502,'Не удалось скачать проверенную копию архива. Обратитесь к администратору.')
    return FileResponse(path,filename=row['filename'],media_type='application/zip',headers={'Cache-Control':'no-store'},background=BackgroundTask(path.unlink,missing_ok=True))
