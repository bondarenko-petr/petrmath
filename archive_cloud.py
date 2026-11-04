"""Opt-in cloud retention. Warn first, delete only after both calendar and notice deadlines."""
import calendar
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from accounts import database
from database import ROOT
import drive_settings as drive
import archive_lifecycle as lifecycle
from mailer import send_archive_expiry_notice


def expires_at(archive,config):
    stamp=archive.get('verified_at')
    if not stamp:raise ValueError('Не сохранена дата проверки ZIP. Автоматическое удаление отложено.')
    date=datetime.fromtimestamp(stamp,timezone.utc)
    months=date.year*12+date.month-1+config.get('cloud_retention_months',2)
    year,month=divmod(months,12);month+=1
    return int(date.replace(year=year,month=month,day=min(date.day,calendar.monthrange(year,month)[1])).timestamp())

def key(archive,config,user):
    return hashlib.sha256(json.dumps([config.get('cloud_generation'),config.get('cloud_retention_months',2),config.get('cloud_warning_days',7),archive['drive_id'],archive['sha256'],archive.get('verified_at'),lifecycle.fingerprint(user)]).encode()).hexdigest()

def policy(archive,config,now=None):
    now=int(time.time()) if now is None else now
    user=lifecycle.identity(archive);record=config.get('cloud_checks',{}).get(archive['id'],{})
    expiry=expires_at(archive,config);days=config.get('cloud_warning_days',7)
    valid=bool(lifecycle.email_ready(user) and record.get('policy_key')==key(archive,config,user) and record.get('warned_at'))
    deadline=max(expiry,record['warned_at']+days*86400) if valid else None
    return user,record,expiry,deadline

def validate_auto(archive,config):
    if not config.get('cloud_deletion_enabled'):raise ValueError('Автоматическая очистка Google Диска выключена.')
    if archive['status'] not in ('verified','delete_failed','deleting'):raise ValueError('Архив не готов к автоматическому удалению.')
    user,record,expiry,deadline=policy(archive,config)
    if deadline is None or int(time.time())<deadline:raise ValueError('Предупреждение или срок хранения ZIP ещё не позволяют удаление.')

def presentation(archive,config):
    if not config.get('cloud_deletion_enabled'):return {'cloud_status':'disabled'}
    try:
        user,record,expiry,deadline=policy(archive,config)
        state='blocked' if not lifecycle.email_ready(user) else 'warning_sent' if deadline else 'waiting_warning'
        if record.get('error'):state='blocked'
        return {'cloud_status':state,'cloud_expires_at':expiry,'cloud_delete_not_before':deadline,
                'cloud_warning_at':record.get('warned_at') if deadline else None,'cloud_issue':record.get('error','')}
    except ValueError as error:return {'cloud_status':'blocked','cloud_issue':str(error)}

def run_cycle(force=False):
    with drive.storage() as config:
        if not config.get('cloud_deletion_enabled'):return {'disabled':True}
    folder=Path(os.getenv('GOOGLE_DRIVE_PRIVATE_DIR',str(ROOT/'data'/'google-drive'))).resolve()
    with open(folder/'cloud-cycle.lock','a') as cycle_lock:
        os.chmod(folder/'cloud-cycle.lock',0o600)
        try:fcntl.flock(cycle_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'busy':True}
        now=int(time.time())
        with drive.storage() as config:
            if not config.get('cloud_deletion_enabled'):return {'disabled':True}
            if not force and now-config.get('cloud_last_started',0)<3600:return {'waiting':True}
            config['cloud_last_started']=now;config['cloud_running_at']=now
        result={'processed':0,'warned':0,'deleted':0,'errors':0}
        try:
            with database() as (c,p):
                c.execute("SELECT * FROM material_archives WHERE status IN ('verified','delete_failed','deleting') ORDER BY created_at,id")
                rows=[dict(row) for row in c.fetchall()]
            for archive in rows:
                with drive.storage() as data:config=json.loads(json.dumps(data))
                if not config.get('cloud_deletion_enabled'):break
                result['processed']+=1;user={}
                try:
                    user,record,expiry,deadline=policy(archive,config,now)
                    if not lifecycle.email_ready(user):raise ValueError('Нужна подтверждённая почта активного ученика для предупреждения об удалении ZIP.')
                    if now<expiry-config.get('cloud_warning_days',7)*86400:continue
                    if deadline is None:
                        if record.get('retry_at',0)>now and record.get('attempt_key')==key(archive,config,user):continue
                        with open(folder/'cleanup.lock','a') as operation_lock:
                            try:fcntl.flock(operation_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                            except BlockingIOError:continue
                            # Reload to avoid warning for an archive already removed manually.
                            with database() as (c,p):
                                c.execute(f'SELECT * FROM material_archives WHERE id={p}',(archive['id'],));current=c.fetchone()
                            if not current or current['status']!='verified':continue
                            archive=dict(current)
                            with drive.storage() as data:latest=json.loads(json.dumps(data))
                            if not latest.get('cloud_deletion_enabled'):break
                            current_user=lifecycle.identity(archive)
                            if not lifecycle.email_ready(current_user):raise ValueError('Подтвердите текущую почту ученика перед предупреждением.')
                            from archive_cleanup import inspect_drive
                            inspect_drive(archive,latest)
                            sent_at=int(time.time());delete_after=max(expires_at(archive,latest),sent_at+latest.get('cloud_warning_days',7)*86400)
                            send_archive_expiry_notice(current_user['email'].lower(),archive['filename'],delete_after)
                            with drive.storage() as data:
                                check=data.setdefault('cloud_checks',{}).setdefault(archive['id'],{})
                                check.update(policy_key=key(archive,latest,current_user),warned_at=int(time.time()),warned_email=current_user['email'].lower(),error='',retry_at=0)
                                drive.log(data,'Предупреждение об удалении ZIP '+archive['id'][:8]+' передано почтовому серверу.')
                            result['warned']+=1
                        continue  # Never delete in the same cycle as a new warning.
                    if now<deadline:continue
                    from archive_deletion import remove_zip
                    preview=remove_zip(archive['id'],0,automatic=True)
                    removed=remove_zip(archive['id'],0,preview['token'],True,automatic=True)
                    if removed['status']=='deleted':result['deleted']+=1
                    with drive.storage() as data:data.setdefault('cloud_checks',{}).setdefault(archive['id'],{})['error']=''
                except Exception as error:
                    result['errors']+=1
                    message=str(error) if isinstance(error,ValueError) and not str(error).isascii() else 'Не удалось предупредить ученика или удалить ZIP. Удаление отложено; проверьте SMTP и Google Диск.'
                    with drive.storage() as data:
                        check=data.setdefault('cloud_checks',{}).setdefault(archive['id'],{})
                        if check.get('error')!=message:drive.log(data,'ZIP '+archive['id'][:8]+': '+message)
                        check.update(error=message,retry_at=now+600,attempt_key=key(archive,config,user))
        except Exception:
            result['errors']+=1
            with drive.storage() as data:drive.log(data,'Цикл очистки Google Диска не завершён. Проверьте базу и настройки.')
        finally:
            with drive.storage() as data:
                data['cloud_running_at']=0;data['cloud_last_finished']=int(time.time());data['cloud_result']=result
        return result
