import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tests import test_archive_cleanup as support
from accounts import database
import drive_settings as drive

class DeleteTests(unittest.TestCase):
    setUp=support.CleanupTests.setUp
    tearDown=support.CleanupTests.tearDown
    seed_lesson=support.CleanupTests.seed_lesson
    upload=support.CleanupTests.upload
    save=support.CleanupTests.save
    create=support.CleanupTests.create
    listing=support.CleanupTests.listing
    login_student=support.CleanupTests.login_student
    matured=support.CleanupTests.matured
    def cloud(self,fail=False,missing=False,wrong=False):
        self.remote.get=lambda *a,**k:SimpleNamespace(is_success=not missing,status_code=404 if missing else 200,json=lambda:{'id':'drive-archive-id','mimeType':'application/zip','appProperties':{'krug_pi_archive':'other' if wrong else self.archive}})
        def delete(url,**kwargs):
            self.remote.deleted.append(url)
            return SimpleNamespace(is_success=not fail,status_code=403 if fail else 204)
        self.remote.delete=delete
    def preview(self):return self.client.post('/api/material-archives/'+self.archive+'/delete-preview',headers=self.headers)
    def delete(self,token,ack=True):return self.client.post('/api/material-archives/'+self.archive+'/delete',json={'token':token,'acknowledge_loss':ack},headers=self.headers)
    def test_delete_keeps_local_files_and_history_requires_confirmation(self):
        self.cloud();before=list(self.folder.iterdir());preview=self.preview()
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['local_count'],1)
        self.assertFalse(self.remote.deleted)
        self.assertEqual(self.delete(preview.json()['token'],False).status_code,409)
        result=self.delete(preview.json()['token']);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'deleted')
        self.assertEqual(list(self.folder.iterdir()),before)
        self.assertEqual(self.listing()[0]['status'],'deleted')
        self.assertEqual(self.client.get('/api/material-archives/'+self.archive+'/download').status_code,410)
        self.assertEqual(self.delete(preview.json()['token']).status_code,409)
        self.login_student();self.assertEqual(self.listing()[0]['status'],'deleted')
    def test_delete_last_copy_disables_both_download_routes(self):
        self.matured()
        from archive_cleanup import run_cycle
        self.assertEqual(run_cycle(force=True)['cleaned'],1)
        self.cloud();preview=self.preview().json();self.assertEqual(preview['local_count'],0)
        self.assertEqual(self.delete(preview['token']).status_code,200)
        self.login_student()
        materials=self.client.get('/api/materials').json()['items'][0]
        self.assertEqual(materials['files'][0]['archive_status'],'deleted')
        self.assertEqual(self.client.get('/api/materials/files/'+materials['files'][0]['id']).status_code,410)
        self.assertTrue(materials['homework'])
    def test_wrong_drive_or_file_identity_is_never_deleted(self):
        self.cloud(wrong=True);self.assertEqual(self.preview().status_code,409);self.assertFalse(self.remote.deleted)
        self.cloud()
        with drive.storage() as data:data['connection']['email']='other@example.com'
        self.assertEqual(self.preview().status_code,409);self.assertFalse(self.remote.deleted)
    def test_timeout_failure_and_retry_are_not_reported_as_success(self):
        self.cloud(fail=True);preview=self.preview().json();self.assertEqual(self.delete(preview['token']).status_code,409)
        self.assertEqual(self.listing()[0]['status'],'delete_failed')
        self.assertEqual(self.client.get('/api/material-archives?errors_only=true').json()['total'],1)
        self.cloud();preview=self.preview().json();self.assertEqual(self.delete(preview['token']).status_code,200)
        self.assertEqual(self.listing()[0]['status'],'deleted')
    def test_missing_remote_is_reported_missing_not_successful_deletion(self):
        self.cloud(missing=True);preview=self.preview().json();self.assertTrue(preview['missing_on_drive'])
        result=self.delete(preview['token']);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'missing');self.assertFalse(self.remote.deleted)
    def test_delete_requires_admin_csrf_and_fresh_owner_bound_token(self):
        self.cloud();self.assertEqual(self.delete('x'*43).status_code,409)
        self.assertEqual(self.client.post('/api/material-archives/'+self.archive+'/delete-preview').status_code,403)
        preview=self.preview().json()
        with drive.storage() as data:data['zip_delete_confirmations'][self.archive]['expires_at']=1
        self.assertEqual(self.delete(preview['token']).status_code,409)
        preview=self.preview().json()
        self.login_student();self.assertEqual(self.preview().status_code,403);self.assertEqual(self.delete(preview['token']).status_code,403)
        self.assertFalse(self.remote.deleted)

    def test_old_missing_unlinked_sources_become_unavailable_when_zip_is_removed(self):
        next(self.folder.iterdir()).unlink();self.cloud()
        preview=self.preview().json();self.assertEqual(preview['local_count'],0)
        self.assertEqual(self.delete(preview['token']).status_code,200)
        self.login_student();file=self.client.get('/api/materials').json()['items'][0]['files'][0]
        self.assertEqual(file['archive_status'],'deleted')
        self.assertEqual(self.client.get('/api/materials/files/'+file['id']).status_code,410)

    def test_auto_cleanup_does_not_touch_deleted_archive_or_enable_itself(self):
        self.cloud();preview=self.preview().json();self.assertEqual(self.delete(preview['token']).status_code,200)
        from archive_cleanup import run_cycle
        result=run_cycle(force=True);self.assertEqual(result['processed'],0)
        self.assertEqual(self.listing()[0]['status'],'deleted')
        self.assertTrue(list(self.folder.iterdir()))
