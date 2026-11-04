import os
import time
import unittest
from unittest.mock import patch
from tests import test_material_archives as support
from accounts import database
import archive_cleanup as cleanup
import drive_settings as drive

class CleanupTests(unittest.TestCase):
    seed_lesson=support.ArchiveTests.seed_lesson
    upload=support.ArchiveTests.upload
    save=support.ArchiveTests.save
    create=support.ArchiveTests.create
    listing=support.ArchiveTests.listing
    login_student=support.ArchiveTests.login_student
    def setUp(self):
        support.ArchiveTests.setUp(self)
        self.mail=patch('archive_cleanup.send_archive_notice');self.sender=self.mail.start()
        with database() as (c,p):
            c.execute('UPDATE material_files SET created_at=?',(int(time.time())-29*86400,))
            c.execute('INSERT INTO verified_emails (user_id,email,password_stamp) VALUES (?,?,?)',(self.id,self.data['username'],''))
        self.assertEqual(self.create().status_code,202);self.archive=self.listing()[0]['id']
        with drive.storage() as data:data['deletion_enabled']=True
    def tearDown(self):self.mail.stop();support.ArchiveTests.tearDown(self)
    def matured(self):
        old=int(time.time())-15*86400
        with database() as (c,p):c.execute('UPDATE material_archives SET verified_at=?,notified_at=?,notified_email=?',(old,old,self.data['username']))
    def test_notice_then_grace_period_and_cleanup(self):
        first=cleanup.run_cycle(force=True);self.assertEqual(first['cleaned'],0);self.sender.assert_called_once();self.assertTrue(list(self.folder.iterdir()))
        self.matured();result=cleanup.run_cycle(force=True);self.assertEqual(result['cleaned'],1,result);self.assertFalse(list(self.folder.iterdir()))
        with database() as (c,p):
            c.execute('SELECT * FROM material_files');file=dict(c.fetchone());self.assertEqual(file['archive_id'],self.archive);self.assertIsNotNone(file['archived_at'])
        self.login_student();materials=self.client.get('/api/materials').json()['items'][0];self.assertTrue(materials['files'][0]['archived_at'])
        result=self.client.get('/api/materials/files/'+file['id']);self.assertEqual(result.status_code,200);self.assertEqual(result.content,self.remote.content)
    def test_corrupt_or_missing_drive_prevents_cleanup(self):
        self.matured();self.remote.corrupt=True
        result=cleanup.run_cycle(force=True);self.assertEqual(result['cleaned'],0);self.assertEqual(result['errors'],1);self.assertTrue(list(self.folder.iterdir()))
    def test_unverified_email_and_failed_mail_block_cleanup(self):
        with database() as (c,p):c.execute('DELETE FROM verified_emails')
        result=cleanup.run_cycle(force=True);self.assertEqual(result['errors'],1);self.sender.assert_not_called();self.assertTrue(list(self.folder.iterdir()))
        with database() as (c,p):c.execute('INSERT INTO verified_emails VALUES (?,?,?)',(self.id,self.data['username'],''))
        self.sender.side_effect=RuntimeError('SMTP unavailable');result=cleanup.run_cycle(force=True);self.assertEqual(result['errors'],1)
        with database() as (c,p):c.execute('SELECT notified_at FROM material_archives');self.assertIsNone(c.fetchone()['notified_at'])
    def test_changed_source_and_new_files_preserved(self):
        self.matured();next(self.folder.iterdir()).write_bytes(b'changed')
        self.assertEqual(cleanup.run_cycle(force=True)['errors'],1);self.assertTrue(list(self.folder.iterdir()))
    def test_recent_file_not_removed_even_in_test_archive(self):
        # Keep source metadata and manifest in sync to represent a genuine fresh upload.
        import json
        now=int(time.time())
        with database() as (c,p):
            c.execute('UPDATE material_files SET created_at=?',(now,));c.execute('SELECT manifest FROM material_archives');manifest=json.loads(c.fetchone()['manifest']);manifest[0]['files'][0]['created_at']=now;c.execute('UPDATE material_archives SET manifest=?',(json.dumps(manifest),))
        self.matured();self.assertEqual(cleanup.run_cycle(force=True)['cleaned'],0);self.assertTrue(list(self.folder.iterdir()))
    def test_disabled_mode_and_daily_limit(self):
        with drive.storage() as data:data['deletion_enabled']=False
        self.assertTrue(cleanup.run_cycle(force=True)['disabled']);self.sender.assert_not_called()
        with drive.storage() as data:data['deletion_enabled']=True
        cleanup.run_cycle();self.assertTrue(cleanup.run_cycle()['waiting'])
    def test_changed_email_restarts_waiting_period(self):
        self.matured()
        with database() as (c,p):c.execute('UPDATE users SET email=? WHERE id=?',('new@example.com',self.id));c.execute('UPDATE verified_emails SET email=?',('new@example.com',))
        result=cleanup.run_cycle(force=True);self.assertEqual(result['cleaned'],0);self.sender.assert_called_once();self.assertTrue(list(self.folder.iterdir()))
    def test_new_upload_is_not_part_of_old_cleanup(self):
        self.matured();self.upload(category='notes')
        result=cleanup.run_cycle(force=True);self.assertEqual(result['cleaned'],1);self.assertEqual(len(list(self.folder.iterdir())),1)
    def test_unlink_failure_is_retryable_after_metadata_commit(self):
        self.matured()
        original=cleanup.Path.unlink
        def fail_source(path,*args,**kwargs):
            if path.parent==self.folder.resolve():raise OSError('busy')
            return original(path,*args,**kwargs)
        with patch.object(cleanup.Path,'unlink',fail_source):self.assertEqual(cleanup.run_cycle(force=True)['errors'],1)
        self.assertTrue(list(self.folder.iterdir()))
        self.assertEqual(cleanup.run_cycle(force=True)['cleaned'],1);self.assertFalse(list(self.folder.iterdir()))
    def test_settings_enable_requires_admin_and_valid_mail_config(self):
        env={'SMTP_HOST':'mail','SMTP_USER':'user','SMTP_PASSWORD':'password','SMTP_FROM':'site@example.com','SITE_URL':'https://example.com'}
        with drive.storage() as data:data['deletion_enabled']=False
        with patch.dict(os.environ,env):
            response=self.client.post('/api/admin/archive-settings/cleanup-mode',json={'enabled':True,'confirmed':True},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.json()['deletion_enabled'])
        self.login_student()
        self.assertEqual(self.client.post('/api/admin/archive-settings/cleanup-mode',json={'enabled':True,'confirmed':True},headers=self.headers).status_code,403)
    def test_increased_grace_and_different_drive_block_deletion(self):
        self.matured()
        with drive.storage() as data:data['grace_days']=30
        self.assertEqual(cleanup.run_cycle(force=True)['cleaned'],0);self.assertTrue(list(self.folder.iterdir()))
        with drive.storage() as data:data['grace_days']=14;data['connection']['email']='other@example.com'
        self.assertEqual(cleanup.run_cycle(force=True)['errors'],1);self.assertTrue(list(self.folder.iterdir()))

    def test_manual_notice_never_purges_even_if_mature(self):
        self.matured()
        with patch('archive_cleanup.purge',side_effect=AssertionError('must not delete')):
            result=self.client.post('/api/material-archives/'+self.archive+'/notify',headers=self.headers)
        self.assertEqual(result.status_code,202,result.text)
        self.sender.assert_not_called()  # Existing handoff is not duplicated.
        self.assertTrue(list(self.folder.iterdir()))
        self.assertIsNone(self.listing()[0]['cleanup_at'])
        self.assertEqual(self.client.post('/api/material-archives/'+self.archive+'/notify',headers=self.headers).status_code,429)

    def test_stale_email_error_becomes_history_then_clears(self):
        from archive_lifecycle import EMAIL_ERROR
        with database() as (c,p):c.execute('UPDATE material_archives SET cleanup_error=?',(EMAIL_ERROR,))
        row=self.listing()[0]
        self.assertEqual(row['notification_status'],'pending')
        self.assertEqual(row['notification_error'],'')
        self.assertEqual(row['previous_error'],EMAIL_ERROR)
        self.assertEqual(self.client.get('/api/material-archives?errors_only=true').json()['total'],0)
        self.client.post('/api/material-archives/'+self.archive+'/notify',headers=self.headers)
        row=self.listing()[0]
        self.assertEqual(row['cleanup_error'],'')
        self.assertEqual(row['notification_status'],'sent')
        self.assertEqual(row['cleanup_status'],'waiting_period')
        self.assertTrue(row['last_check_at'])
        with drive.storage() as config:self.assertTrue(any('ошибка устранена' in e['message'] for e in config['events']))

    def test_confirmation_retries_mail_without_waiting_daily_cleanup(self):
        with database() as (c,p):c.execute('DELETE FROM verified_emails')
        cleanup.run_notifications()
        self.sender.assert_not_called()
        self.assertEqual(cleanup.run_notifications()['processed'],0)  # Backoff while unchanged.
        with database() as (c,p):c.execute('INSERT INTO verified_emails VALUES (?,?,?)',(self.id,self.data['username'],''))
        with drive.storage() as config:config['cleanup_last_started']=int(time.time())
        self.assertTrue(cleanup.run_cycle().get('waiting'))
        with patch('archive_cleanup.purge',side_effect=AssertionError('mail path must not delete')):
            self.assertEqual(cleanup.run_notifications()['errors'],0)
        self.sender.assert_called_once()
        self.assertEqual(self.listing()[0]['notification_status'],'sent')
        self.assertTrue(list(self.folder.iterdir()))

    def test_clear_source_error_only_after_source_recheck(self):
        self.matured()
        with database() as (c,p):c.execute('UPDATE material_archives SET cleanup_error=?',('Исходный файл изменился. Очистка остановлена.',))
        self.client.post('/api/material-archives/'+self.archive+'/notify',headers=self.headers)
        self.assertTrue(self.listing()[0]['cleanup_issue'])
        self.assertTrue(list(self.folder.iterdir()))

    def test_deadline_accounts_for_both_file_age_and_grace(self):
        import json
        now=int(time.time());self.matured()
        with database() as (c,p):
            c.execute('SELECT manifest FROM material_archives');manifest=json.loads(c.fetchone()['manifest'])
            manifest[0]['files'][0]['created_at']=now
            c.execute('UPDATE material_archives SET manifest=?',(json.dumps(manifest),))
        row=self.listing()[0]
        self.assertEqual(row['cleanup_not_before'],now+28*86400)
        self.assertEqual(row['cleanup_status'],'waiting_period')
        with patch('archive_cleanup.purge',side_effect=AssertionError('not before displayed date')):
            self.assertEqual(cleanup.run_cycle(force=True)['cleaned'],0)

    def test_manual_notice_requires_admin_and_csrf(self):
        url='/api/material-archives/'+self.archive+'/notify'
        self.assertEqual(self.client.post(url).status_code,403)
        self.login_student()
        self.assertEqual(self.client.post(url,headers=self.headers).status_code,403)

    def test_manual_notice_works_with_cleanup_disabled(self):
        with drive.storage() as config:config['deletion_enabled']=False
        self.assertTrue(cleanup.run_notifications().get('disabled'))
        with patch('archive_cleanup.purge',side_effect=AssertionError('must not delete')):
            self.assertEqual(self.client.post('/api/material-archives/'+self.archive+'/notify',headers=self.headers).status_code,202)
        self.sender.assert_called_once()
        self.assertEqual(self.listing()[0]['cleanup_status'],'disabled')
        self.assertTrue(list(self.folder.iterdir()))

    def preview_manual(self):
        return self.client.post('/api/material-archives/'+self.archive+'/cleanup-preview',headers=self.headers)

    def confirm_manual(self,token):
        return self.client.post('/api/material-archives/'+self.archive+'/cleanup',json={'token':token},headers=self.headers)

    def test_manual_cleanup_preview_then_confirm_with_automatic_disabled(self):
        self.matured()
        with drive.storage() as config:config['deletion_enabled']=False
        before=list(self.folder.iterdir());preview=self.preview_manual()
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['file_count'],1)
        self.assertEqual(preview.json()['bytes'],sum(path.stat().st_size for path in before))
        with database() as (c,p):
            c.execute('SELECT archived_at,archive_id FROM material_files');file=c.fetchone()
            self.assertIsNone(file['archived_at']);self.assertIsNone(file['archive_id'])
        self.assertEqual(list(self.folder.iterdir()),before)
        self.upload(category='notes')  # Not part of the confirmed archive: preserve.
        result=self.confirm_manual(preview.json()['token'])
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(list(self.folder.iterdir())),1)
        self.assertTrue(self.listing()[0]['cleanup_at'])
        self.assertEqual(self.listing()[0]['cleanup_status'],'completed')
        self.sender.assert_not_called()
        self.assertEqual(self.confirm_manual(preview.json()['token']).status_code,409)
        with drive.storage() as config:
            self.assertFalse(config['deletion_enabled'])
            self.assertTrue(any('Ручная очистка' in item['message'] for item in config['events']))
        self.login_student()
        result=self.client.get('/api/material-archives/'+self.archive+'/download')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.content,self.remote.content)

    def test_manual_cleanup_requires_notice_and_respects_grace_and_retention(self):
        self.assertEqual(self.preview_manual().status_code,409)
        self.assertTrue(list(self.folder.iterdir()))
        cleanup.run_notifications(self.archive)
        self.assertEqual(self.preview_manual().status_code,409)
        self.matured()
        with drive.storage() as config:config['retention_days']=60
        self.assertEqual(self.preview_manual().status_code,409)
        self.assertTrue(list(self.folder.iterdir()))

    def test_manual_cleanup_rechecks_drive_and_sources_after_confirmation(self):
        self.matured();preview=self.preview_manual().json()
        self.remote.corrupt=True
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        self.assertTrue(list(self.folder.iterdir()))
        self.remote.corrupt=False;preview=self.preview_manual().json()
        next(self.folder.iterdir()).write_bytes(b'changed')
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        self.assertTrue(list(self.folder.iterdir()))
        self.assertIsNone(self.listing()[0]['cleanup_at'])

    def test_manual_confirmation_is_required_expires_and_is_bound_to_rules(self):
        self.matured()
        self.assertEqual(self.confirm_manual('x'*43).status_code,409)
        preview=self.preview_manual().json()
        with drive.storage() as config:config['manual_cleanup_confirmations'][self.archive]['expires_at']=1
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        preview=self.preview_manual().json()
        with drive.storage() as config:config['retention_days']=20
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        self.assertTrue(list(self.folder.iterdir()))

    def test_manual_cleanup_requires_admin_csrf_and_same_admin_confirmation(self):
        self.matured();preview=self.preview_manual().json()
        with drive.storage() as config:config['manual_cleanup_confirmations'][self.archive]['admin_id']=-1
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        self.assertEqual(self.client.post('/api/material-archives/'+self.archive+'/cleanup-preview').status_code,403)
        self.assertEqual(self.client.post('/api/material-archives/'+self.archive+'/cleanup',json={'token':preview['token']}).status_code,403)
        self.login_student()
        self.assertEqual(self.preview_manual().status_code,403)
        self.assertEqual(self.confirm_manual(preview['token']).status_code,403)
        self.assertTrue(list(self.folder.iterdir()))

    def test_manual_cleanup_lock_prevents_parallel_operations(self):
        import fcntl
        from pathlib import Path
        self.matured()
        with open(Path(os.environ['GOOGLE_DRIVE_PRIVATE_DIR'])/'cleanup.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.preview_manual().status_code,409)
        self.assertTrue(list(self.folder.iterdir()))

    def test_manual_cleanup_unlink_failure_can_be_retried(self):
        self.matured();preview=self.preview_manual().json()
        original=cleanup.Path.unlink
        def fail_source(path,*args,**kwargs):
            if path.parent==self.folder.resolve():raise OSError('busy')
            return original(path,*args,**kwargs)
        with patch.object(cleanup.Path,'unlink',fail_source):
            self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        self.assertTrue(list(self.folder.iterdir()))
        preview=self.preview_manual().json()
        self.assertEqual(self.confirm_manual(preview['token']).status_code,200)
        self.assertFalse(list(self.folder.iterdir()))

    def test_manual_cleanup_email_change_or_drive_switch_blocks_confirm(self):
        self.matured();preview=self.preview_manual().json()
        with database() as (c,p):c.execute('UPDATE users SET email=? WHERE id=?',('changed@example.com',self.id))
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        with database() as (c,p):c.execute('UPDATE users SET email=? WHERE id=?',(self.data['username'],self.id))
        preview=self.preview_manual().json()
        with drive.storage() as config:config['connection']['email']='other@example.com'
        self.assertEqual(self.confirm_manual(preview['token']).status_code,409)
        self.assertTrue(list(self.folder.iterdir()))

    def test_early_cleanup_only_bypasses_time_and_requires_explicit_ack(self):
        # Genuine recent file, synchronized manifest, and a newly sent notice.
        import json
        now=int(time.time())
        with database() as (c,p):
            c.execute('UPDATE material_files SET created_at=?',(now,))
            c.execute('SELECT manifest FROM material_archives');manifest=json.loads(c.fetchone()['manifest']);manifest[0]['files'][0]['created_at']=now
            c.execute('UPDATE material_archives SET manifest=?',(json.dumps(manifest),))
        with drive.storage() as config:config['deletion_enabled']=False
        cleanup.run_notifications(self.archive)
        response=self.preview_manual()
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['detail']['code'],'waiting_period')
        preview=self.client.post('/api/material-archives/'+self.archive+'/cleanup-preview?early=true',headers=self.headers)
        self.assertEqual(preview.status_code,200,preview.text)
        token=preview.json()['token']
        self.assertEqual(self.confirm_manual(token).status_code,409)
        url='/api/material-archives/'+self.archive+'/cleanup'
        self.assertEqual(self.client.post(url,json={'token':token,'early':True},headers=self.headers).status_code,409)
        self.assertTrue(list(self.folder.iterdir()))
        result=self.client.post(url,json={'token':token,'early':True,'early_ack':True},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertFalse(list(self.folder.iterdir()))
        with drive.storage() as config:
            self.assertFalse(config['deletion_enabled'])
            self.assertTrue(any('Досрочная ручная очистка' in item['message'] for item in config['events']))
        self.login_student()
        self.assertEqual(self.client.get('/api/material-archives/'+self.archive+'/download').content,self.remote.content)

    def test_early_cleanup_does_not_bypass_notice_corruption_or_source_checks(self):
        url='/api/material-archives/'+self.archive+'/cleanup-preview?early=true'
        self.assertEqual(self.client.post(url,headers=self.headers).status_code,409)
        cleanup.run_notifications(self.archive)
        self.remote.corrupt=True
        self.assertEqual(self.client.post(url,headers=self.headers).status_code,409)
        self.remote.corrupt=False
        preview=self.client.post(url,headers=self.headers).json()
        next(self.folder.iterdir()).write_bytes(b'changed')
        result=self.client.post('/api/material-archives/'+self.archive+'/cleanup',json={'token':preview['token'],'early':True,'early_ack':True},headers=self.headers)
        self.assertEqual(result.status_code,409)
        self.assertTrue(list(self.folder.iterdir()))

    def test_ordinary_token_cannot_authorize_early_cleanup(self):
        self.matured();token=self.preview_manual().json()['token']
        result=self.client.post('/api/material-archives/'+self.archive+'/cleanup',json={'token':token,'early':True,'early_ack':True},headers=self.headers)
        self.assertEqual(result.status_code,409)
        self.assertTrue(list(self.folder.iterdir()))
