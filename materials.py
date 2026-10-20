"""Teacher-authored homework, notes and private lesson attachments."""
import os
import json
import re
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from accounts import database, guard
from admin import require_admin
from database import ROOT
from lessons import member, zone, settings

router=APIRouter(prefix='/api/materials',tags=['Lesson materials'])
MAX_FILE_SIZE=10*1024*1024
MAX_UPLOAD_SIZE=51*1024*1024
Category=Literal['homework','notes']


def storage():
    folder=Path(os.environ.get('MATERIALS_DIR',str(ROOT/'data'/'materials'))).resolve()
    public=(ROOT/'landing'/'dist').resolve()
    if folder==public or folder.is_relative_to(public):
        raise HTTPException(503,'Папка вложений должна находиться вне публичной папки сайта')
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def lesson(c,p,lesson_id,user,lock=False):
    if lock and p=='?': c.execute('BEGIN IMMEDIATE')
    c.execute(f'SELECT l.*,u.name AS student_name FROM lessons l JOIN users u ON u.id=l.student_id WHERE l.id={p}'+(' FOR UPDATE' if lock and p!='?' else ''),(lesson_id,))
    row=c.fetchone()
    if not row or (user['role']!='admin' and row['student_id']!=user['id']):
        raise HTTPException(404,'Урок не найден')
    if row['status']!='completed':
        raise HTTPException(409,'Материалы добавляются только к проведённым урокам')
    return dict(row)


def describe(c,p,row):
    c.execute(f'SELECT * FROM lesson_materials WHERE lesson_id={p}',(row['id'],))
    m=c.fetchone()
    result={'lesson_id':row['id'],'student_id':row['student_id'],'student_name':row['student_name'],
            'topic':row['topic'],'starts_at':datetime.fromtimestamp(row['starts_at'],timezone.utc).isoformat(),
            'timezone':row['timezone'],'homework':'','notes':'','due_mode':'next','due_date':None,'version':0,'updated_at':None}
    if m:
        result.update({k:dict(m)[k] for k in ['homework','notes','due_mode','due_date','version','updated_at']})
    result['next_lesson_at']=None
    if result['due_mode']=='next':
        # Include a subsequently completed lesson, so historical deadlines do
        # not drift forward simply because the next class has taken place.
        c.execute(f"SELECT starts_at FROM lessons WHERE student_id={p} AND starts_at>={p} AND status!='cancelled' ORDER BY starts_at,id LIMIT 1",(row['student_id'],row['ends_at']))
        nxt=c.fetchone()
        if nxt: result['next_lesson_at']=datetime.fromtimestamp(nxt['starts_at'],timezone.utc).isoformat()
    c.execute(f'SELECT id,category,filename,media_type,size,created_at,archive_id,archived_at FROM material_files WHERE lesson_id={p} AND deleted_at IS NULL ORDER BY created_at,id',(row['id'],))
    result['files']=[dict(f) for f in c.fetchall()]
    return result


@router.get('')
def list_materials(response:Response,student_id:int|None=Query(None,gt=0),lesson_id:int|None=Query(None,gt=0),
                   limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),content:Category|None=Query(None),missing:Literal['homework','notes','any','both']|None=Query(None),from_date:date|None=None,to_date:date|None=None,user=Depends(member)):
    if from_date and to_date and from_date>to_date:
        raise HTTPException(422,'Начало периода должно быть не позже конца')
    display_zone=zone(settings(user)['timezone'])
    with database() as (c,p):
        if p=='?': c.execute('BEGIN')
        condition="l.status='completed'";args=[]
        owner=user['id'] if user['role']=='student' else student_id
        if owner is not None: condition+=f' AND l.student_id={p}';args.append(owner)
        if lesson_id is not None: condition+=f' AND l.id={p}';args.append(lesson_id)
        if user['role']=='student':
            condition+=" AND (EXISTS (SELECT 1 FROM lesson_materials m WHERE m.lesson_id=l.id AND (m.homework!='' OR m.notes!='')) OR EXISTS (SELECT 1 FROM material_files f WHERE f.lesson_id=l.id AND f.deleted_at IS NULL))"
        if content:
            # Column names come exclusively from the Literal category above.
            condition+=f" AND (EXISTS (SELECT 1 FROM lesson_materials m WHERE m.lesson_id=l.id AND m.{content}!='') OR EXISTS (SELECT 1 FROM material_files f WHERE f.lesson_id=l.id AND f.category={p} AND f.deleted_at IS NULL))"
            args.append(content)
        if missing:
            categories=['homework','notes'] if missing in ('any','both') else [missing]
            checks=[]
            for category in categories:
                checks.append(f"(NOT EXISTS (SELECT 1 FROM lesson_materials m WHERE m.lesson_id=l.id AND m.{category}!='') AND NOT EXISTS (SELECT 1 FROM material_files f WHERE f.lesson_id=l.id AND f.category={p} AND f.deleted_at IS NULL))")
                args.append(category)
            condition+=' AND ('+(' OR ' if missing=='any' else ' AND ').join(checks)+')'
        if from_date:
            condition+=f' AND l.starts_at>={p}';args.append(int(datetime.combine(from_date,datetime.min.time(),tzinfo=display_zone).timestamp()))
        if to_date:
            condition+=f' AND l.starts_at<{p}';args.append(int(datetime.combine(to_date+timedelta(days=1),datetime.min.time(),tzinfo=display_zone).timestamp()))
        c.execute('SELECT COUNT(*) AS total FROM lessons l WHERE '+condition,tuple(args))
        total=int(c.fetchone()['total'])
        c.execute('SELECT l.*,u.name AS student_name FROM lessons l JOIN users u ON u.id=l.student_id WHERE '+condition+f' ORDER BY l.starts_at DESC,l.id DESC LIMIT {p} OFFSET {p}',(*args,limit,offset))
        rows=[dict(r) for r in c.fetchall()]
        items=[describe(c,p,row) for row in rows]
        if user['role']=='student':
            from student_timezones import student_zone
            display_zone=student_zone(c,p,user['id'])
            for item in items: item['timezone']=display_zone
    response.headers['Cache-Control']='no-store'
    return {'items':items,'total':total,'limit':limit,'offset':offset,'role':user['role']}


class MaterialInput(BaseModel):
    homework:str=Field(default='',max_length=20000)
    notes:str=Field(default='',max_length=20000)
    due_mode:Literal['next','manual']='next'
    due_date:date|None=None
    version:int=Field(ge=0,strict=True)

    @model_validator(mode='after')
    def validate_date(self):
        if self.due_mode=='manual' and self.due_date is None:
            raise ValueError('Укажите дату выполнения задания')
        self.homework=self.homework.strip();self.notes=self.notes.strip()
        return self


@router.put('/{lesson_id}')
def save_materials(lesson_id:int,data:MaterialInput,request:Request,response:Response,user=Depends(require_admin)):
    guard(request)
    with database() as (c,p):
        row=lesson(c,p,lesson_id,user,True)
        if data.due_mode=='manual' and data.due_date<datetime.fromtimestamp(row['starts_at'],zone(row['timezone'])).date():
            raise HTTPException(422,'Срок задания не может быть раньше даты урока')
        c.execute(f'SELECT version FROM lesson_materials WHERE lesson_id={p}',(lesson_id,))
        old=c.fetchone();version=int(old['version']) if old else 0
        if version!=data.version:
            raise HTTPException(409,'Материалы изменены в другом окне. Скопируйте свой текст и обновите страницу.')
        values=(data.homework,data.notes,data.due_mode,data.due_date.isoformat() if data.due_mode=='manual' else None,version+1,int(time.time()),user['id'],lesson_id)
        if old:
            c.execute('UPDATE lesson_materials SET '+','.join(f'{k}={p}' for k in ['homework','notes','due_mode','due_date','version','updated_at','updated_by'])+f' WHERE lesson_id={p}',values)
        else:
            c.execute('INSERT INTO lesson_materials (homework,notes,due_mode,due_date,version,updated_at,updated_by,lesson_id) VALUES ('+','.join([p]*8)+')',values)
    response.headers['Cache-Control']='no-store'
    return {'status':'saved','version':version+1}


def file_type(filename,head):
    ext=Path(filename).suffix.lower()
    if ext=='.pdf' and head.startswith(b'%PDF-'): return 'pdf','application/pdf'
    if ext in ('.jpg','.jpeg') and head.startswith(b'\xff\xd8\xff'): return 'jpg','image/jpeg'
    if ext=='.png' and head.startswith(b'\x89PNG\r\n\x1a\n'): return 'png','image/png'
    raise HTTPException(422,'Допустимы только PDF, JPG и PNG с соответствующим содержимым')


@router.post('/{lesson_id}/files',status_code=201)
async def upload_files(lesson_id:int,request:Request,category:Category=Query(...),user=Depends(require_admin)):
    guard(request)
    # Authorize the lesson before reading or storing any upload.
    with database() as (c,p): lesson(c,p,lesson_id,user)
    if request.headers.get('content-length','').isdigit() and int(request.headers['content-length'])>MAX_UPLOAD_SIZE:
        raise HTTPException(413,'Общий размер загрузки слишком большой')
    received=0;over_limit=False
    async def receive():
        nonlocal received,over_limit
        message=await request.receive()
        received+=len(message.get('body',b''))
        if received>MAX_UPLOAD_SIZE:
            over_limit=True
            raise MultiPartException('Upload is too large')
        return message
    bounded=Request(request.scope,receive)
    paths=[]
    try:
        async with bounded.form(max_files=5,max_fields=2) as form:
            uploads=form.getlist('files')
            if not uploads or not all(isinstance(f,UploadFile) for f in uploads):
                raise HTTPException(422,'Выберите файлы для загрузки')
            if len(uploads)>5: raise HTTPException(422,'Не более 5 файлов на каждый блок')
            root=storage()
            result=[]
            with database() as (c,p):
                lesson(c,p,lesson_id,user,True)
                c.execute(f'SELECT COUNT(*) AS total FROM material_files WHERE lesson_id={p} AND category={p} AND deleted_at IS NULL AND archived_at IS NULL',(lesson_id,category))
                if c.fetchone()['total']+len(uploads)>5:
                    raise HTTPException(422,'В этом блоке уже есть файлы. Максимум — 5 вложений.')
                for f in uploads:
                    name=Path((f.filename or 'file').replace('\\','/')).name
                    name=re.sub(r'[\x00-\x1f\x7f]','',name).strip()
                    if not name or len(name)>200: raise HTTPException(422,'Имя файла должно содержать от 1 до 200 символов')
                    head=await f.read(16)
                    ext,media=file_type(name,head)
                    file_id=uuid4().hex;key=file_id+'.'+ext;path=root/key;paths.append(path);size=len(head)
                    if size>MAX_FILE_SIZE: raise HTTPException(413,'Каждый файл должен быть не больше 10 МБ')
                    with path.open('xb') as dest:
                        dest.write(head)
                        while chunk:=await f.read(1024*1024):
                            size+=len(chunk)
                            if size>MAX_FILE_SIZE: raise HTTPException(413,'Каждый файл должен быть не больше 10 МБ')
                            dest.write(chunk)
                    c.execute('INSERT INTO material_files (id,lesson_id,category,storage_key,filename,media_type,size,created_at,created_by) VALUES ('+','.join([p]*9)+')',(file_id,lesson_id,category,key,name,media,size,int(time.time()),user['id']))
                    result.append({'id':file_id,'filename':name})
            return Response(content=json.dumps({'files':result}),media_type='application/json',status_code=201,headers={'Cache-Control':'no-store'})
    except BaseException as error:
        for path in paths: path.unlink(missing_ok=True)
        if over_limit: raise HTTPException(413,'Общий размер загрузки слишком большой') from error
        if isinstance(error,OSError): raise HTTPException(503,'Не удалось сохранить файлы. Попробуйте ещё раз.') from error
        raise


@router.get('/files/{file_id}')
def download_file(file_id:str,user=Depends(member)):
    with database() as (c,p):
        c.execute(f'SELECT f.*,l.student_id,l.status FROM material_files f JOIN lessons l ON l.id=f.lesson_id WHERE f.id={p} AND f.deleted_at IS NULL',(file_id,))
        row=c.fetchone()
        if not row or row['status']!='completed' or (user['role']!='admin' and row['student_id']!=user['id']):
            raise HTTPException(404,'Вложение не найдено')
        row=dict(row)
    if row.get('archived_at') and row.get('archive_id'):
        return RedirectResponse('/api/material-archives/'+row['archive_id']+'/download',status_code=303,headers={'Cache-Control':'no-store'})
    if not re.fullmatch(r'[0-9a-f]{32}\.(pdf|jpg|png)',row['storage_key']): raise HTTPException(404,'Вложение не найдено')
    path=storage()/row['storage_key']
    if path.is_symlink() or path.resolve().parent!=storage() or not path.is_file(): raise HTTPException(404,'Файл отсутствует в хранилище. Обратитесь к преподавателю.')
    return FileResponse(path,media_type=row['media_type'],filename=row['filename'],content_disposition_type='attachment',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.delete('/files/{file_id}')
def remove_file(file_id:str,request:Request,response:Response,user=Depends(require_admin)):
    guard(request)
    with database() as (c,p):
        c.execute(f'SELECT lesson_id FROM material_files WHERE id={p}',(file_id,));row=c.fetchone()
        if not row: raise HTTPException(404,'Вложение не найдено')
        lesson(c,p,row['lesson_id'],user,True)
        c.execute(f'UPDATE material_files SET deleted_at={p} WHERE id={p} AND deleted_at IS NULL',(int(time.time()),file_id))
    response.headers['Cache-Control']='no-store'
    return {'status':'removed'}
