"""Explicit removal of one Drive ZIP; local source files and history are retained."""
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from accounts import database
from database import ROOT
import drive_settings as drive
from materials import storage

REMOVED=('deleting','delete_failed','deleted','missing')

def snapshot(archive):
    root=storage();sources=[];existing=0
    with database() as (c,p):
        c.execute(f'SELECT f.*,l.student_id FROM material_files f JOIN lessons l ON l.id=f.lesson_id WHERE l.student_id={p}',(archive['student_id'],))
        files={row['id']:dict(row) for row in c.fetchall()}
    for lesson in json.loads(archive['manifest']):
        for original in lesson['files']:
            file=files.get(original['id']);present=False
            if file and file['deleted_at'] is None and file['lesson_id']==lesson['id'] and file['size']==original['size'] and file['storage_key']==original['storage_key'] and re.fullmatch(r'[0-9a-f]{32}\.(pdf|jpg|png)',file['storage_key']):
                path=root/file['storage_key']
                present=not path.is_symlink() and path.is_file() and path.stat().st_size==original['size']
                if present:
                    h=hashlib.sha256()
                    with path.open('rb') as source:
                        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
                    present=bool(original.get('sha256') and h.hexdigest()==original['sha256'])
            sources.append((original['id'],present));existing+=bool(present)
    signature=hashlib.sha256(json.dumps([archive['id'],archive['student_id'],archive['drive_id'],archive['drive_account'],archive['sha256'],archive['manifest'],archive['status'],sources],sort_keys=True).encode()).hexdigest()
    return {'signature':signature,'file_count':sum(len(row['files']) for row in json.loads(archive['manifest'])),'local_count':existing}

def remote_info(client,headers,archive):
    response=client.get('https://www.googleapis.com/drive/v3/files/'+quote(archive['drive_id'],safe=''),headers=headers,params={'fields':'id,mimeType,appProperties'})
    if response.status_code==404:return None
    if not response.is_success:raise ValueError('Не удалось проверить архив на Google Диске. Проверьте доступ и повторите позже.')
    info=response.json()
    if info.get('id')!=archive['drive_id'] or info.get('mimeType')!='application/zip' or info.get('appProperties',{}).get('krug_pi_archive')!=archive['id']:
        raise ValueError('Файл Google Диска не совпадает с архивом сайта. Удаление запрещено.')
    return info

def set_status(archive_id,status,error='',archive=None):
    with database() as (c,p):
        if archive is not None:
            if p=='?':c.execute('BEGIN IMMEDIATE')
            c.execute(f'SELECT id FROM users WHERE id={p}'+(' FOR UPDATE' if p!='?' else ''),(archive['student_id'],));c.fetchall()
            c.execute(f'SELECT id FROM lessons WHERE student_id={p} ORDER BY id'+(' FOR UPDATE' if p!='?' else ''),(archive['student_id'],));c.fetchall()
            root=storage()
            for lesson in json.loads(archive['manifest']):
                for original in lesson['files']:
                    c.execute(f'SELECT f.*,l.student_id FROM material_files f JOIN lessons l ON l.id=f.lesson_id WHERE f.id={p}',(original['id'],));file=c.fetchone()
                    if not file or file['deleted_at'] is not None or file['student_id']!=archive['student_id'] or file['lesson_id']!=lesson['id']:continue
                    if any(file[key]!=original[key] for key in ('storage_key','category','size','created_at')):continue
                    if file['archive_id'] not in (None,archive_id) or not re.fullmatch(r'[0-9a-f]{32}\.(pdf|jpg|png)',file['storage_key']):continue
                    path=root/file['storage_key']
                    if path.exists() or path.is_symlink():continue
                    c.execute(f'UPDATE material_files SET archive_id={p},archived_at=COALESCE(archived_at,{p}) WHERE id={p}',(archive_id,int(time.time()),file['id']))
        c.execute(f'UPDATE material_archives SET status={p},updated_at={p},error={p} WHERE id={p}',(status,int(time.time()),error,archive_id))

def remove_zip(archive_id,admin_id,token=None,ack=False,*,automatic=False):
    with drive.storage():pass
    folder=Path(os.getenv('GOOGLE_DRIVE_PRIVATE_DIR',str(ROOT/'data'/'google-drive'))).resolve()
    with open(folder/'cleanup.lock','a') as lock:
        os.chmod(folder/'cleanup.lock',0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise HTTPException(409,'Выполняется другая операция с архивами. Повторите позже.')
        with database() as (c,p):
            c.execute(f'SELECT * FROM material_archives WHERE id={p}',(archive_id,));row=c.fetchone()
        if not row:raise HTTPException(404,'Архив не найден')
        archive=dict(row)
        if archive['status'] not in ('verified','deleting','delete_failed','missing'):
            raise HTTPException(409,'Удаление доступно для готового архива или незавершённой попытки удаления.')
        data=snapshot(archive);now=int(time.time())
        with drive.storage() as config:
            connection=config.get('connection')
            if not connection or connection.get('email')!=archive['drive_account']:
                raise HTTPException(409,'Подключите Google-аккаунт, в котором сохранён этот архив.')
            settings=json.loads(json.dumps(config))
            if automatic:
                from archive_cloud import validate_auto
                validate_auto(archive,config)
            if token is not None:
                confirmation=config.get('zip_delete_confirmations',{}).get(archive_id)
                if not ack or not confirmation or confirmation['admin_id']!=admin_id or confirmation['expires_at']<=now or not secrets.compare_digest(confirmation['token'],token) or confirmation['signature']!=data['signature']:
                    raise HTTPException(409,'Требуется новое подтверждение удаления ZIP. Проверьте данные архива заново.')
                del config['zip_delete_confirmations'][archive_id]
        started=False
        try:
            with httpx.Client(timeout=60,follow_redirects=False) as client:
                headers=drive.access(client,settings['connection'],settings)
                info=remote_info(client,headers,archive)
                if token is None:
                    value=secrets.token_urlsafe(32)
                    with drive.storage() as config:
                        config.setdefault('zip_delete_confirmations',{})[archive_id]={'token':value,'admin_id':admin_id,'expires_at':now+300,'signature':data['signature']}
                    return {'token':value,'file_count':data['file_count'],'local_count':data['local_count'],'missing_on_drive':info is None,'filename':archive['filename']}
                with drive.storage() as latest:
                    if latest.get('connection',{}).get('email')!=archive['drive_account']:raise ValueError('Подключён другой Google-аккаунт. Повторите проверку.')
                    if automatic:
                        from archive_cloud import validate_auto
                        validate_auto(archive,latest)
                # Persist a non-downloadable state BEFORE the remote request.
                set_status(archive_id,'deleting');started=True
                if info is None:
                    final='missing';message='Архив недоступен на Google Диске. Ссылки отключены; удаление через сайт не подтверждено.'
                else:
                    response=client.delete('https://www.googleapis.com/drive/v3/files/'+quote(archive['drive_id'],safe=''),headers=headers)
                    if not response.is_success:raise ValueError('Google Диск не подтвердил удаление. Повторите проверку удаления.')
                    final='deleted';message='ZIP удалён с Google Диска безвозвратно. История занятий, тексты и имеющиеся исходные файлы сохранены.'
                set_status(archive_id,final,archive=archive)
            started=False  # Remote result is durably reflected in the archive row.
            try:
                with drive.storage() as config:
                    config.setdefault('zip_deletions',{})[archive_id]={'at':int(time.time()),'admin_id':admin_id,'status':final}
                    drive.log(config,'Архив '+archive_id[:8]+': '+message+(' Планировщик.' if automatic else ' Администратор: '+str(admin_id)+'.'))
            except Exception:logging.getLogger(__name__).warning('Archive removal completed; operation log could not be saved')
            return {'status':final,'message':message}
        except Exception as error:
            message=str(error) if isinstance(error,ValueError) and not str(error).isascii() else 'Удаление ZIP не завершено. Проверьте доступ к Google Диску и повторите проверку удаления.'
            if started:set_status(archive_id,'delete_failed',message)
            raise HTTPException(409,message) from error
