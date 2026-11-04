"""Operational archive states; no schema change and no deletion on read."""
import hashlib
import json
import time
from accounts import database
import drive_settings as drive

EMAIL_ERROR='Подтверждённая почта активного ученика недоступна. Очистка отложена.'

def identity(archive):
    with database() as (c,p):
        c.execute(f'SELECT u.email,u.is_active,v.email AS verified FROM users u LEFT JOIN verified_emails v ON v.user_id=u.id WHERE u.id={p}',(archive['student_id'],))
        row=c.fetchone()
    return dict(row) if row else {}

def fingerprint(user):
    return hashlib.sha256(json.dumps([user.get('email'),user.get('verified'),user.get('is_active')]).encode()).hexdigest()

def email_ready(user):
    return bool(user.get('is_active') and user.get('email') and user['email'].lower()==user.get('verified'))

def record(archive,error='',stage='notification',user=None):
    now=int(time.time())
    with drive.storage() as config:
        check=config.setdefault('archive_checks',{}).setdefault(archive['id'],{})
        old=check.get('error') or archive.get('cleanup_error','')
        old_stage=check.get('stage', 'notification' if old==EMAIL_ERROR else 'cleanup')
        # A mail check cannot clear an unresolved source-deletion error.
        current_error=error or (old if old_stage=='cleanup' and stage=='notification' else '')
        current_stage=stage if error or not current_error else old_stage
        check.update(last_check_at=now,error=current_error,stage=current_stage,notice_requested_at=0)
        if stage=='notification':
            check['notice_attempt_at']=now
            check['identity']=fingerprint(user or {})
            check['retry_at']=now+(600 if error else 0)
        if error:
            check['last_error_at']=now;check['last_error']=error
            if old!=error:drive.log(config,'Архив '+archive['id'][:8]+': '+error)
        elif old and not current_error:
            check['last_error']=old
            drive.log(config,'Архив '+archive['id'][:8]+': предыдущая ошибка устранена: '+old)
        with database() as (c,p):
            c.execute(f'UPDATE material_archives SET cleanup_error={p} WHERE id={p}',(current_error[:500],archive['id']))

def presentation(row,config):
    if row['status'] in ('deleting','delete_failed','deleted','missing'):
        return {'notification_status':'not_applicable','cleanup_status':'not_applicable','zip_deleted_at':row.get('updated_at') if row['status']=='deleted' else None}
    check=config.get('archive_checks',{}).get(row['id'],{})
    user={'email':row.get('current_email'),'verified':row.get('confirmed_email'),'is_active':row.get('student_active')}
    ready=email_ready(user)
    current_notice=bool(ready and row.get('notified_at') and row.get('notified_email')==user['email'].lower())
    notice='sent' if current_notice else 'pending' if ready else 'blocked'
    error=row.get('cleanup_error') or ''
    stage=check.get('stage','notification' if error==EMAIL_ERROR else 'cleanup')
    previous_error=''
    # Re-evaluate the email condition without sending mail or changing stored data.
    if error==EMAIL_ERROR and ready:
        previous_error=error;error=''
    notice_error=error if stage=='notification' else ''
    cleanup_error=error if stage=='cleanup' else ''
    if notice_error:notice='error'
    deadline=not_before(row,config) if current_notice else None
    if current_notice and deadline is None:cleanup_error='Не удалось рассчитать срок очистки. Требуется повторная проверка.'
    if check.get('notice_requested_at',0)>check.get('last_check_at',0) and int(time.time())-check['notice_requested_at']<300:notice='checking'
    if row.get('cleanup_at'):cleanup='completed'
    elif row['status']!='verified':cleanup='waiting_archive';notice='waiting_archive'
    elif not config.get('deletion_enabled'):cleanup='disabled'
    elif not current_notice:cleanup='waiting_notice'
    elif cleanup_error:cleanup='blocked'
    elif deadline is None:cleanup='blocked'
    elif int(time.time())<deadline:cleanup='waiting_period'
    else:cleanup='ready'
    from archive_cloud import presentation as cloud_presentation
    return {**cloud_presentation(row,config),'notification_status':notice,'cleanup_status':cleanup,'cleanup_not_before':deadline,
            'last_check_at':check.get('last_check_at'),'notification_error':notice_error,
            'cleanup_issue':cleanup_error,'previous_error':previous_error,
            'last_error_at':check.get('last_error_at'),'last_error':check.get('last_error') or previous_error}

def not_before(archive,config):
    try:
        verified=archive.get('verified_at') or archive.get('updated_at')
        if not verified or not archive.get('notified_at'):return None
        times=[f['created_at']+config.get('retention_days',28)*86400 for lesson in json.loads(archive.get('manifest') or '[]') for f in lesson.get('files',[])]
        return max([verified+config.get('grace_days',14)*86400,archive['notified_at']+config.get('grace_days',14)*86400,*times])
    except (ValueError,TypeError,KeyError):return None
