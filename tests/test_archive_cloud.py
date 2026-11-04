import calendar
from datetime import datetime,timezone
import os
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tests import test_archive_cleanup as support
from accounts import database
import drive_settings as drive
import archive_cloud as cloud

class CloudTests(unittest.TestCase):
    setUpBase=support.CleanupTests.setUp
    tearDownBase=support.CleanupTests.tearDown
    seed_lesson=support.CleanupTests.seed_lesson
    upload=support.CleanupTests.upload
    save=support.CleanupTests.save
    create=support.CleanupTests.create
    listing=support.CleanupTests.listing
    login_student=support.CleanupTests.login_student
    def setUp(self):
        self.setUpBase();self.now=int(time.time());self.warning=patch('archive_cloud.send_archive_expiry_notice');self.send_warning=self.warning.start()
        with database() as (c,p):c.execute('UPDATE material_archives SET verified_at=?',(self.now-100*86400,))
        with drive.storage() as data:data['deletion_enabled']=False
        self.remote.get=lambda *a,**k:SimpleNamespace(is_success=True,status_code=200,json=lambda:{'id':'drive-archive-id','mimeType':'application/zip','appProperties':{'krug_pi_archive':self.archive}})
    def tearDown(self):self.warning.stop();self.tearDownBase()
    def enable(self):
        with drive.storage() as data:data.update(cloud_deletion_enabled=True,cloud_generation='first',cloud_last_started=0)
    def cycle(self,at=None):
        with patch('archive_cloud.time.time',return_value=self.now if at is None else at):return cloud.run_cycle(force=True)
    def row(self):
        with database() as (c,p):c.execute('SELECT * FROM material_archives WHERE id=?',(self.archive,));return dict(c.fetchone())
    def test_calendar_months_clamp_month_end_and_leap_day(self):
        stamp=lambda y,m,d:int(datetime(y,m,d,12,tzinfo=timezone.utc).timestamp())
        self.assertEqual(cloud.expires_at({'verified_at':stamp(2026,12,31)},{'cloud_retention_months':2}),stamp(2027,2,28))
        self.assertEqual(cloud.expires_at({'verified_at':stamp(2023,12,31)},{'cloud_retention_months':2}),stamp(2024,2,29))
        self.assertEqual(cloud.expires_at({'verified_at':stamp(2026,10,20)},{'cloud_retention_months':2}),stamp(2026,12,20))
    def test_disabled_cloud_never_warns_or_deletes(self):
        self.assertTrue(self.cycle()['disabled']);self.send_warning.assert_not_called();self.assertFalse(self.remote.deleted)
    def test_old_zip_warns_then_waits_full_seven_days(self):
        self.enable();result=self.cycle();self.assertEqual(result['warned'],1,result);self.assertEqual(result['deleted'],0)
        self.send_warning.assert_called_once();self.assertFalse(self.remote.deleted)
        self.assertEqual(self.cycle(self.now+7*86400-1)['deleted'],0)
        result=self.cycle(self.now+7*86400);self.assertEqual(result['deleted'],1,result)
        self.assertEqual(self.row()['status'],'deleted');self.assertTrue(list(self.folder.iterdir()))
        self.assertEqual(self.cycle(self.now+8*86400)['processed'],0)
    def test_new_zip_waits_until_warning_window_and_expiry(self):
        self.enable()
        with database() as (c,p):c.execute('UPDATE material_archives SET verified_at=?',(self.now,))
        with drive.storage() as data:expiry=cloud.expires_at(self.row(),data)
        self.assertEqual(self.cycle()['warned'],0)
        self.assertEqual(self.cycle(expiry-7*86400)['warned'],1)
        self.assertEqual(self.cycle(expiry-1)['deleted'],0)
        self.assertEqual(self.cycle(expiry)['deleted'],1)
    def test_smtp_failure_blocks_deletion_and_backs_off(self):
        self.enable();self.send_warning.side_effect=RuntimeError('smtp')
        self.assertEqual(self.cycle()['errors'],1);self.assertEqual(self.cycle()['errors'],0)
        self.send_warning.assert_called_once();self.assertFalse(self.remote.deleted)
        self.assertEqual(self.cycle(self.now+8*86400)['deleted'],0)
        with drive.storage() as data:self.assertFalse(data['cloud_checks'][self.archive].get('warned_at'))
    def test_changed_confirmed_email_gets_a_new_full_warning_period(self):
        self.enable();self.cycle()
        with database() as (c,p):c.execute('UPDATE users SET email=? WHERE id=?',('new@example.com',self.id));c.execute('UPDATE verified_emails SET email=? WHERE user_id=?',('new@example.com',self.id))
        result=self.cycle(self.now+8*86400);self.assertEqual(result['warned'],1);self.assertEqual(result['deleted'],0)
        self.assertEqual(self.send_warning.call_args.args[0],'new@example.com')
        self.assertEqual(self.cycle(self.now+15*86400-1)['deleted'],0)
        self.assertEqual(self.cycle(self.now+15*86400)['deleted'],1)
    def test_disable_or_policy_change_prevents_old_notice_from_deleting(self):
        self.enable();self.cycle()
        with drive.storage() as data:data['cloud_deletion_enabled']=False
        self.assertTrue(self.cycle(self.now+8*86400)['disabled'])
        with drive.storage() as data:data.update(cloud_deletion_enabled=True,cloud_generation='second')
        self.assertEqual(self.cycle(self.now+8*86400)['warned'],1)
        self.assertFalse(self.remote.deleted)
    def test_corrupt_zip_or_unconfirmed_user_never_gets_warning(self):
        self.enable();self.remote.corrupt=True
        self.assertEqual(self.cycle()['errors'],1);self.send_warning.assert_not_called()
        self.remote.corrupt=False
        with database() as (c,p):c.execute('DELETE FROM verified_emails')
        self.assertEqual(self.cycle(self.now+86400)['errors'],1);self.send_warning.assert_not_called();self.assertFalse(self.remote.deleted)
    def test_switching_off_after_preview_blocks_automatic_delete(self):
        self.enable();self.cycle()
        from archive_deletion import remove_zip
        with patch('archive_cloud.time.time',return_value=self.now+8*86400):
            preview=remove_zip(self.archive,0,automatic=True)
            with drive.storage() as data:data['cloud_deletion_enabled']=False
            with self.assertRaises(ValueError):remove_zip(self.archive,0,preview['token'],True,automatic=True)
        self.assertFalse(self.remote.deleted)
    def test_save_cloud_policy_does_not_enable_any_mode_and_requires_admin(self):
        result=self.client.put('/api/admin/archive-settings/cloud-retention',json={'cloud_retention_months':3,'cloud_warning_days':10},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertFalse(result.json()['deletion_enabled']);self.assertFalse(result.json()['cloud_deletion_enabled'])
        self.assertEqual(self.client.put('/api/admin/archive-settings/cloud-retention',json={'cloud_retention_months':0,'cloud_warning_days':1},headers=self.headers).status_code,422)
        self.assertEqual(self.client.put('/api/admin/archive-settings/cloud-retention',json={'cloud_retention_months':2,'cloud_warning_days':7}).status_code,403)
        self.login_student();self.assertEqual(self.client.put('/api/admin/archive-settings/cloud-retention',json={'cloud_retention_months':2,'cloud_warning_days':7},headers=self.headers).status_code,403)
    def test_mode_enable_requires_confirmation_and_new_epoch_on_reenable(self):
        env={'SMTP_HOST':'mail','SMTP_USER':'user','SMTP_PASSWORD':'password','SMTP_FROM':'site@example.com','SITE_URL':'https://example.com'}
        url='/api/admin/archive-settings/cloud-cleanup-mode'
        with patch.dict(os.environ,env):
            self.assertEqual(self.client.post(url,json={'enabled':True},headers=self.headers).status_code,422)
            result=self.client.post(url,json={'enabled':True,'confirmed':True},headers=self.headers);self.assertEqual(result.status_code,200,result.text)
            self.assertFalse(result.json()['deletion_enabled'])
            with drive.storage() as data:before=data['cloud_generation']
            self.client.post(url,json={'enabled':False},headers=self.headers)
            self.client.post(url,json={'enabled':True,'confirmed':True},headers=self.headers)
            with drive.storage() as data:self.assertNotEqual(before,data['cloud_generation'])
        self.send_warning.assert_not_called();self.assertFalse(self.remote.deleted)

    def test_database_failure_is_visible_and_clears_running_indicator(self):
        self.enable()
        with patch('archive_cloud.database',side_effect=RuntimeError('unavailable')):
            result=self.cycle()
        self.assertEqual(result['errors'],1)
        with drive.storage() as data:self.assertEqual(data['cloud_running_at'],0)

    def test_policy_changed_after_warning_starts_new_wait(self):
        self.enable();self.cycle()
        result=self.client.put('/api/admin/archive-settings/cloud-retention',json={'cloud_retention_months':1,'cloud_warning_days':7},headers=self.headers)
        self.assertEqual(result.status_code,200)
        result=self.cycle(self.now+8*86400)
        self.assertEqual(result['warned'],1);self.assertEqual(result['deleted'],0)
        self.assertFalse(self.remote.deleted)
