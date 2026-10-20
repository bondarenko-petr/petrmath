"""Daily cleanup of verified, notified archives. No automatic archive creation."""
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import httpx
from accounts import database
from database import ROOT
import drive_settings as drive
from mailer import send_archive_notice
from material_archives import remote_download,digest
from materials import storage as material_storage

logger=logging.getLogger(__name__)

def notice_target(archive):
    with database() as (c,p):
        c.execute(f'SELECT u.email,u.is_active,v.email AS verified FROM users u LEFT JOIN verified_emails v ON v.user_id=u.id WHERE u.id={p}',(archive['student_id'],));user=c.fetchone()
    if not user or not user['is_active'] or not user['email'] or user['email'].lower()!=user['verified']:raise ValueError('Подтверждённая почта активного ученика недоступна. Очистка отложена.')
    return user['email'].lower()

def save_error(archive_id,message):
    with database() as (c,p):c.execute(f'UPDATE material_archives SET cleanup_error={p} WHERE id={p}',(message[:500],archive_id))

def inspect_drive(archive,config):
    connection=config.get('connection')
    if not connection or connection.get('email','')!=archive['drive_account']:raise ValueError('Подключён другой Google-аккаунт. Очистка отложена.')
    with tempfile.TemporaryDirectory(prefix='krug-pi-cleanup-check-') as folder,httpx.Client(timeout=120,follow_redirects=False) as client:
        headers=drive.access(client,connection,config)
        remote_download(client,headers,archive['drive_id'],Path(folder)/'verified.zip',archive['size'],archive['sha256'])

def purge(archive,config,now):
    days=config.get('retention_days',28);grace=config.get('grace_days',14)
    root=material_storage();sources=[]
    with database() as (c,p):
        if p=='?':c.execute('BEGIN IMMEDIATE')
        c.execute(f'SELECT id FROM users WHERE id={p}'+(' FOR UPDATE' if p!='?' else ''),(archive['student_id'],))
        if not c.fetchone():raise ValueError('Ученик не найден.')
        c.execute(f'SELECT * FROM material_archives WHERE id={p}',(archive['id'],));current=c.fetchone()
        if not current or current['status']!='verified':raise ValueError('Архив не прошёл проверку.')
        current=dict(current)
        if current['sha256']!=archive['sha256'] or current['drive_id']!=archive['drive_id'] or current['manifest']!=archive['manifest']:raise ValueError('Состав архива изменился. Очистка отложена.')
        c.execute(f'SELECT u.email,u.is_active,v.email AS verified FROM users u LEFT JOIN verified_emails v ON v.user_id=u.id WHERE u.id={p}',(archive['student_id'],));user=c.fetchone()
        if not user or not user['is_active'] or not user['email'] or user['email'].lower()!=user['verified'] or user['email'].lower()!=current['notified_email']:raise ValueError('Почта изменилась или не подтверждена. Очистка отложена.')
        if not current['verified_at'] or not current['notified_at'] or now-max(current['verified_at'],current['notified_at'])<grace*86400:return False
        # Lock lessons in the same order as ordinary material edits and deletion.
        c.execute(f'SELECT id FROM lessons WHERE student_id={p} ORDER BY id'+(' FOR UPDATE' if p!='?' else ''),(archive['student_id'],));c.fetchall()
        for lesson in json.loads(current['manifest']):
            for original in lesson['files']:
                c.execute(f'SELECT f.*,l.student_id FROM material_files f JOIN lessons l ON l.id=f.lesson_id WHERE f.id={p}',(original['id'],));file=c.fetchone()
                if not file or file['deleted_at'] is not None:continue
                if file['student_id']!=archive['student_id'] or file['lesson_id']!=lesson['id'] or file['storage_key']!=original['storage_key'] or file['size']!=original['size'] or file['category']!=original['category'] or file['created_at']!=original['created_at']:raise ValueError('Исходные сведения изменились. Очистка остановлена.')
                if file['created_at']>now-days*86400:return False
                if file['archive_id'] not in (None,archive['id']):raise ValueError('Файл связан с другим архивом.')
                if not re.fullmatch(r'[0-9a-f]{32}\.(pdf|jpg|png)',file['storage_key']):raise ValueError('Некорректное имя исходного файла.')
                path=root/file['storage_key']
                if path.is_symlink():raise ValueError('Обнаружена ссылка вместо исходного файла.')
                if path.exists():
                    if path.stat().st_size!=file['size'] or digest(path)!=original.get('sha256'):raise ValueError('Исходный файл изменился. Очистка остановлена.')
                elif not file['archived_at']:raise ValueError('Исходный файл отсутствует. Очистка остановлена.')
                sources.append((dict(file),path))
        # Commit usable archive references BEFORE unlinking. A crash can retain extra
        # local copies, but never leaves a missing original with no download path.
        for file,path in sources:
            c.execute(f'UPDATE material_files SET archive_id={p},archived_at=COALESCE(archived_at,{p}) WHERE id={p}',(archive['id'],now,file['id']))
    # Recheck the current toggle immediately before deleting any bytes.
    with drive.storage() as latest:
        if not latest.get('deletion_enabled'):return False
        if latest.get('connection',{}).get('email','')!=archive['drive_account']:return False
        if now-max(current['verified_at'],current['notified_at'])<latest.get('grace_days',14)*86400:return False
        if any(file['created_at']>now-latest.get('retention_days',28)*86400 for file,path in sources):return False
        with database() as (c,p):
            if p=='?':c.execute('BEGIN IMMEDIATE')
            c.execute(f'SELECT email,is_active FROM users WHERE id={p}'+(' FOR UPDATE' if p!='?' else ''),(archive['student_id'],));user=c.fetchone()
            c.execute(f'SELECT email FROM verified_emails WHERE user_id={p}',(archive['student_id'],));confirmed=c.fetchone()
            if not user or not confirmed or not user['is_active'] or not user['email'] or user['email'].lower()!=current['notified_email'] or confirmed['email']!=current['notified_email']:return False
            hashes={f['id']:f['sha256'] for lesson in json.loads(current['manifest']) for f in lesson['files']}
            for file,path in sources:
                # File bytes are immutable through the API. Keep the user lock so a
                # concurrent email change or account deletion cannot race unlinking.
                if path.is_symlink():raise ValueError('Исходник изменился. Остальные копии сохранены.')
                if path.exists():
                    if digest(path)!=hashes[file['id']]:raise ValueError('Исходник изменился. Остальные копии сохранены.')
                    path.unlink()
            c.execute(f'UPDATE material_archives SET cleanup_at={p},purged_count={p},cleanup_error={p} WHERE id={p}',(now,len(sources),'',archive['id']))
    return True

def run_cycle(force=False):
    # OS lock covers mail and filesystem operations across workers on one host.
    with drive.storage() as data:enabled=data.get('deletion_enabled',False)
    if not enabled:return {'processed':0,'cleaned':0,'errors':0,'disabled':True}
    folder=Path(os.getenv('GOOGLE_DRIVE_PRIVATE_DIR',str(ROOT/'data'/'google-drive'))).resolve()
    with open(folder/'cleanup.lock','a') as lock:
        os.chmod(folder/'cleanup.lock',0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'busy':True}
        with drive.storage() as config:
            if not config.get('deletion_enabled'):return {'disabled':True}
            now=int(time.time())
            if not force and now-config.get('cleanup_last_started',0)<86400:return {'waiting':True}
            config['cleanup_last_started']=now;snapshot=json.loads(json.dumps(config))
        result={'processed':0,'cleaned':0,'errors':0}
        try:
            with database() as (c,p):
                c.execute("SELECT * FROM material_archives WHERE status='verified' AND cleanup_at IS NULL ORDER BY created_at,id")
                archives=[dict(row) for row in c.fetchall()]
            for archive in archives:
                with drive.storage() as latest:
                    if not latest.get('deletion_enabled'):break
                    # Use current settings/connection, not an account revoked earlier.
                    snapshot=json.loads(json.dumps(latest))
                result['processed']+=1
                try:
                    email=notice_target(archive)
                    if not archive['notified_at'] or archive['notified_email']!=email:
                        inspect_drive(archive,snapshot)
                        send_archive_notice(email,archive['filename'])
                        with database() as (c,p):c.execute(f'UPDATE material_archives SET notified_at={p},notified_email={p},cleanup_error={p} WHERE id={p}',(int(time.time()),email,'',archive['id']))
                        continue
                    if now-max(archive['verified_at'] or archive['updated_at'],archive['notified_at'])<snapshot.get('grace_days',14)*86400:continue
                    inspect_drive(archive,snapshot)
                    if purge(archive,snapshot,now):result['cleaned']+=1
                except Exception as error:
                    result['errors']+=1
                    # Only deliberately constructed local errors may be displayed.
                    message=str(error) if isinstance(error,ValueError) and str(error)[:1].isupper() and not str(error).isascii() else 'Проверка Drive, почты или исходников не удалась. Очистка отложена.'
                    save_error(archive['id'],message)
        except Exception:
            result['errors']+=1;logger.warning('Archive cleanup cycle failed; source files are preserved where not processed')
        with drive.storage() as config:
            config['cleanup_last_finished']=int(time.time());config['cleanup_result']=result
            drive.log(config,'Очистка архивов: обработано '+str(result['processed'])+', очищено '+str(result['cleaned'])+', ошибок '+str(result['errors'])+'.')
        return result

_stop=threading.Event()
_thread=None

def start_worker():
    global _thread
    _stop.clear()
    def work():
        while not _stop.wait(60):
            try:run_cycle()
            except Exception:logger.warning('Archive cleanup worker unavailable; check migration and configuration')
    _thread=threading.Thread(target=work,name='archive-cleanup',daemon=True);_thread.start()

def stop_worker():
    _stop.set()
    if _thread:_thread.join(timeout=1)

if __name__=='__main__':
    print(json.dumps(run_cycle(force=True),ensure_ascii=False))
