import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from tests import test_materials as support
from tests.test_accounts import seed_user
from accounts import database
import drive_settings as drive

class FakeDrive:
    def __init__(self,corrupt=False):self.content=b'';self.corrupt=corrupt;self.deleted=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def post(self,url,**kwargs):
        if 'oauth2' in url:return SimpleNamespace(is_success=True,json=lambda:{'access_token':'test-access'})
        return SimpleNamespace(is_success=True,headers={'Location':'https://www.googleapis.com/upload/drive/v3/files?upload_id=abc'})
    def put(self,url,**kwargs):
        self.content=b''.join(kwargs['content']);return SimpleNamespace(is_success=True,json=lambda:{'id':'drive-archive-id'})
    @contextlib.contextmanager
    def stream(self,*args,**kwargs):
        yield SimpleNamespace(is_success=True,iter_bytes=lambda size:iter([b'corrupted' if self.corrupt else self.content]))
    def delete(self,url,**kwargs):self.deleted.append(url);return SimpleNamespace(is_success=True)

class ArchiveTests(unittest.TestCase):
    seed_lesson=support.MaterialsTests.seed_lesson
    upload=support.MaterialsTests.upload
    save=support.MaterialsTests.save
    def setUp(self):
        support.MaterialsTests.setUp(self)
        self.drive_env=patch.dict(os.environ,{'GOOGLE_DRIVE_PRIVATE_DIR':str(Path(self.temp.name)/'drive'),'GOOGLE_DRIVE_CLIENT_ID':'test','GOOGLE_DRIVE_CLIENT_SECRET':'secret','GOOGLE_DRIVE_REDIRECT_URI':'http://127.0.0.1:8000/api/admin/archive-settings/callback'})
        self.drive_env.start()
        with drive.storage() as data:data['connection']={'refresh_token':'private','email':'owner@example.com','folder_id':'folder'}
        self.upload();self.save()
        self.remote=FakeDrive();self.fake=patch('material_archives.httpx.Client',return_value=self.remote);self.fake.start()
    def tearDown(self):self.fake.stop();self.drive_env.stop();support.MaterialsTests.tearDown(self)
    def create(self,recent=True):return self.client.post('/api/material-archives',json={'student_id':self.id,'include_recent':recent},headers=self.headers)
    def listing(self):return self.client.get('/api/material-archives').json()['items']
    def login_student(self):self.client.post('/api/auth/login',json=self.data,headers=self.headers)
    def test_round_trip_structure_and_authorized_download(self):
        result=self.create();self.assertEqual(result.status_code,202,result.text)
        row=self.listing()[0];self.assertEqual(row['status'],'verified');self.assertEqual(row['file_count'],1)
        with ZipFile(io.BytesIO(self.remote.content)) as archive:
            self.assertIsNone(archive.testzip());names=archive.namelist();self.assertIn('Содержание.html',names)
            self.assertTrue(any('Квадратные_уравнения' in name.replace(' ','_') for name in names))
            self.assertTrue(any(name.endswith('/Задание_1.pdf') for name in names))
            self.assertTrue(any('Решить' in archive.read(name).decode() for name in names if name.endswith('Задание.txt')))
        originals=list(self.folder.iterdir());self.assertTrue(originals)
        self.login_student();download=self.client.get('/api/material-archives/'+row['id']+'/download');self.assertEqual(download.status_code,200);self.assertEqual(download.content,self.remote.content)
        self.assertEqual(self.create().status_code,403)
        seed_user('Other','other','Other password 123!')
        self.client.post('/api/auth/login',json={'username':'other','password':'Other password 123!'},headers=self.headers)
        self.assertEqual(self.listing(),[])
        self.assertEqual(self.client.get('/api/material-archives/'+row['id']+'/download').status_code,404)
    def test_age_and_duplicate_exclusion(self):
        self.assertEqual(self.create(False).status_code,409)
        with database() as (c,p):c.execute('UPDATE material_files SET created_at=?',(int(time.time())-29*86400,))
        self.assertEqual(self.create(False).status_code,202)
        self.assertEqual(self.create().status_code,409)
    def test_checksum_failure_preserves_originals_and_hides_archive(self):
        self.remote.corrupt=True;self.assertEqual(self.create().status_code,202)
        row=self.listing()[0];self.assertEqual(row['status'],'failed');self.assertTrue(self.remote.deleted)
        self.assertTrue(list(self.folder.iterdir()));self.login_student();self.assertEqual(self.listing(),[])
    def test_missing_source_fails_without_upload(self):
        for path in self.folder.iterdir():path.unlink()
        self.create();self.assertEqual(self.listing()[0]['status'],'failed');self.assertEqual(self.remote.content,b'')
    def test_download_detects_damage_and_changed_account(self):
        self.create();row=self.listing()[0];self.remote.corrupt=True
        self.assertEqual(self.client.get('/api/material-archives/'+row['id']+'/download').status_code,502)
        with drive.storage() as data:data['connection']['email']='different@example.com'
        self.assertEqual(self.client.get('/api/material-archives/'+row['id']+'/download').status_code,409)
    def test_in_progress_prevents_duplicate_and_csrf(self):
        with patch('material_archives.create_job'):
            self.assertEqual(self.create().status_code,202)
            self.assertEqual(self.create().status_code,409)
        self.assertEqual(self.client.post('/api/material-archives',json={'student_id':self.id,'include_recent':True}).status_code,403)
    def test_bad_source_path_and_html_topic_are_safe(self):
        with database() as (c,p):c.execute('UPDATE lessons SET topic=? WHERE id=?',('<script>alert(1)</script>',self.lesson_id))
        self.create();self.assertEqual(self.listing()[0]['status'],'verified')
        with ZipFile(io.BytesIO(self.remote.content)) as archive:
            index=archive.read('Содержание.html').decode();self.assertNotIn('<script>',index);self.assertIn('&lt;script&gt;',index)
    def test_new_attachment_gets_its_own_archive(self):
        self.create();self.upload(category='notes');self.create()
        self.assertEqual(len(self.listing()),2)
        with database() as (c,p):
            c.execute("SELECT manifest FROM material_archives WHERE status='verified'")
            file_sets=[{f['id'] for row in json.loads(item['manifest']) for f in row['files']} for item in c.fetchall()]
        self.assertFalse(file_sets[0]&file_sets[1])
    def test_stale_job_can_be_retried_but_cannot_later_be_published(self):
        with patch('material_archives.create_job'):self.create()
        old=self.listing()[0]['id']
        with database() as (c,p):c.execute('UPDATE material_archives SET updated_at=?',(int(time.time())-3601,))
        self.assertEqual(self.create().status_code,202)
        from material_archives import update
        self.assertEqual(update(old,'verified'),0)
    def test_size_limit_and_originals_unchanged(self):
        with database() as (c,p):c.execute('UPDATE material_files SET size=?',(201*1024*1024,))
        self.assertEqual(self.create().status_code,422);self.assertEqual(self.remote.content,b'')
    def test_source_traversal_is_rejected(self):
        outside=Path(self.temp.name)/'outside.pdf';outside.write_bytes(b'%PDF-1.7\nTest')
        with database() as (c,p):c.execute('UPDATE material_files SET storage_key=?',('../outside.pdf',))
        self.create();self.assertEqual(self.listing()[0]['status'],'failed')
    def test_student_deletion_protects_archive_references(self):
        self.create()
        response=self.client.patch('/api/admin/students/'+str(self.id)+'/active',json={'is_active':False},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.request('DELETE','/api/admin/students/'+str(self.id),json={'username':self.data['username']},headers=self.headers)
        self.assertEqual(response.status_code,409,response.text)
