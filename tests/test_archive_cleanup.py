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
            response=self.client.post('/api/admin/archive-settings/cleanup-mode',json={'enabled':True},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.json()['deletion_enabled'])
        self.login_student()
        self.assertEqual(self.client.post('/api/admin/archive-settings/cleanup-mode',json={'enabled':True},headers=self.headers).status_code,403)
    def test_increased_grace_and_different_drive_block_deletion(self):
        self.matured()
        with drive.storage() as data:data['grace_days']=30
        self.assertEqual(cleanup.run_cycle(force=True)['cleaned'],0);self.assertTrue(list(self.folder.iterdir()))
        with drive.storage() as data:data['grace_days']=14;data['connection']['email']='other@example.com'
        self.assertEqual(cleanup.run_cycle(force=True)['errors'],1);self.assertTrue(list(self.folder.iterdir()))
