import os
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests import test_accounts as support
from accounts import database
from main import app


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        support.AccountTests.setUp(self)
        self.folder=Path(self.temp.name)/'attachments'
        self.files_env=patch.dict(os.environ,{'MATERIALS_DIR':str(self.folder)})
        self.files_env.start()
        self.admin_id=support.seed_user('Преподаватель','teacher','Teacher password!','admin')
        self.client.post('/api/auth/login',json={'username':'teacher','password':'Teacher password!'},headers=self.headers)
        self.start=int(datetime(2026,10,17,10,tzinfo=timezone.utc).timestamp())
        self.lesson_id=self.seed_lesson(self.id,self.start,'completed')
        self.next_id=self.seed_lesson(self.id,self.start+4*86400,'scheduled')

    def tearDown(self):
        self.files_env.stop()
        support.AccountTests.tearDown(self)

    def seed_lesson(self,student,start,status):
        with database() as (c,p):
            c.execute('INSERT INTO lessons (student_id,starts_at,ends_at,duration_minutes,price_kopecks,topic,timezone,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (student,start,start+3600,60,200000,'Квадратные уравнения','Europe/Moscow',status,int(time.time())))
            return c.lastrowid

    def save(self,**fields):
        return self.client.put(f'/api/materials/{self.lesson_id}',json={'homework':'Решить 125–130','notes':'Формула дискриминанта','due_mode':'next','due_date':None,'version':0,**fields},headers=self.headers)

    def listing(self,**params):
        return self.client.get('/api/materials',params={'student_id':self.id,**params})

    def upload(self,category='homework',files=None,lesson=None):
        return self.client.post(f'/api/materials/{lesson or self.lesson_id}/files?category={category}',files=files or [('files',('задачи.pdf',b'%PDF-1.7\nTest','application/pdf'))],headers=self.headers)

    def test_text_dates_and_dynamic_next_lesson(self):
        self.assertEqual(self.save().status_code,200)
        row=self.listing().json()['items'][0]
        self.assertEqual(row['lesson_id'],self.lesson_id)
        self.assertEqual(row['starts_at'],'2026-10-17T10:00:00+00:00')
        self.assertEqual(row['next_lesson_at'],'2026-10-21T10:00:00+00:00')
        self.assertGreater(row['updated_at'],0)
        with database() as (c,p):
            c.execute('UPDATE lessons SET starts_at=starts_at+86400,ends_at=ends_at+86400 WHERE id=?',(self.next_id,))
        self.assertEqual(self.listing().json()['items'][0]['next_lesson_at'],'2026-10-22T10:00:00+00:00')
        with database() as (c,p):c.execute("UPDATE lessons SET status='completed' WHERE id=?",(self.next_id,))
        row=next(r for r in self.listing().json()['items'] if r['lesson_id']==self.lesson_id)
        self.assertEqual(row['next_lesson_at'],'2026-10-22T10:00:00+00:00')
        with database() as (c,p):c.execute("UPDATE lessons SET status='cancelled' WHERE id=?",(self.next_id,))
        self.assertIsNone(self.listing().json()['items'][0]['next_lesson_at'])

    def test_manual_deadline_and_conflict(self):
        self.assertEqual(self.save(due_mode='manual').status_code,422)
        self.assertEqual(self.save(due_mode='manual',due_date='2026-10-16').status_code,422)
        self.assertEqual(self.save(due_mode='manual',due_date='2026-10-25').status_code,200)
        self.assertEqual(self.save(notes='stale').status_code,409)
        row=self.listing().json()['items'][0]
        self.assertEqual(row['due_date'],'2026-10-25')
        self.assertIsNone(row['next_lesson_at'])
        self.assertEqual(row['notes'],'Формула дискриминанта')

    def test_ownership_forced_password_and_completed_only(self):
        self.assertEqual(self.upload(lesson=self.next_id).status_code,409)
        saved=self.save();self.assertEqual(saved.status_code,200)
        file_id=self.upload().json()['files'][0]['id']
        anonymous=TestClient(app)
        self.assertEqual(anonymous.get('/api/materials').status_code,401)
        self.assertEqual(anonymous.get('/api/materials/files/'+file_id).status_code,401)
        self.client.post('/api/auth/login',json=self.data,headers=self.headers)
        self.assertEqual(self.listing(student_id=99999).json()['total'],1)
        self.assertEqual(self.client.get('/api/materials/files/'+file_id).status_code,200)
        self.assertEqual(self.save(version=1).status_code,403)
        self.assertEqual(self.upload().status_code,403)
        self.assertEqual(self.client.delete('/api/materials/files/'+file_id,headers=self.headers).status_code,403)
        with database() as (c,p):c.execute('UPDATE users SET must_change_password=1 WHERE id=?',(self.id,))
        self.assertEqual(self.listing().status_code,403)

    def test_other_student_cannot_download_or_list(self):
        self.save();file_id=self.upload().json()['files'][0]['id']
        support.seed_user('Другой','other','Another password!')
        self.client.post('/api/auth/login',json={'username':'other','password':'Another password!'},headers=self.headers)
        self.assertEqual(self.listing().json()['total'],0)
        self.assertEqual(self.client.get('/api/materials/files/'+file_id).status_code,404)

    def test_files_download_private_remove_and_category_limits(self):
        data=self.upload(files=[('files',(f'{n}.pdf',b'%PDF-1.7 Test','application/pdf')) for n in range(5)])
        self.assertEqual(data.status_code,201,data.text)
        file_id=data.json()['files'][0]['id']
        downloaded=self.client.get('/api/materials/files/'+file_id)
        self.assertEqual(downloaded.content,b'%PDF-1.7 Test')
        self.assertIn('attachment',downloaded.headers['content-disposition'])
        self.assertEqual(downloaded.headers['cache-control'],'no-store')
        self.assertEqual(downloaded.headers['x-content-type-options'],'nosniff')
        key=next(self.folder.iterdir()).name
        self.assertEqual(self.client.get('/data/materials/'+key).status_code,404)
        self.assertEqual(self.upload().status_code,422)
        self.assertEqual(self.upload(category='notes').status_code,201)
        self.assertEqual(self.client.delete('/api/materials/files/'+file_id,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/materials/files/'+file_id).status_code,404)
        self.assertEqual(self.upload().status_code,201)

    def test_signatures_size_batch_rollback_and_csrf(self):
        bad=self.upload(files=[('files',('fake.pdf',b'<script>alert(1)</script>','application/pdf'))])
        self.assertEqual(bad.status_code,422)
        with patch('materials.MAX_FILE_SIZE',20):
            result=self.upload(files=[('files',('small.pdf',b'%PDF-1.7','application/pdf')),('files',('large.pdf',b'%PDF-1.7'+b'x'*40,'application/pdf'))])
            self.assertEqual(result.status_code,413)
        self.assertEqual(list(self.folder.iterdir()),[])
        self.assertEqual(self.listing().json()['items'][0]['files'],[])
        self.assertEqual(self.client.post(f'/api/materials/{self.lesson_id}/files?category=homework',files={'files':('a.pdf',b'%PDF-1.7')}).status_code,403)
        with patch('materials.MAX_UPLOAD_SIZE',20):
            self.assertEqual(self.upload().status_code,413)
        result=self.upload(files=[('files',(f'{n}.pdf',b'%PDF-1.7','application/pdf')) for n in range(6)])
        self.assertEqual(result.status_code,400)

    def test_student_history_filters_and_latest_across_pages(self):
        self.save(homework='Первое задание',notes='')
        for n in range(22):self.seed_lesson(self.id,self.start+(n+10)*86400,'completed')
        self.assertEqual(self.listing(limit=1,content='homework').json()['items'][0]['homework'],'Первое задание')
        self.assertEqual(self.listing(content='notes').json()['total'],0)
        self.client.post('/api/auth/login',json=self.data,headers=self.headers)
        data=self.listing().json()
        self.assertEqual(data['total'],1)
        self.assertEqual(data['items'][0]['homework'],'Первое задание')

    def test_storage_cannot_be_public_and_missing_file_is_clear(self):
        from database import ROOT
        with patch.dict(os.environ,{'MATERIALS_DIR':str(ROOT/'landing'/'dist'/'uploads')}):
            self.assertEqual(self.upload().status_code,503)
        file_id=self.upload().json()['files'][0]['id']
        for path in self.folder.iterdir():path.unlink()
        response=self.client.get('/api/materials/files/'+file_id)
        self.assertEqual(response.status_code,404)

    def test_compact_filters_include_file_only_materials_and_count_all_pages(self):
        other=self.seed_lesson(self.id,self.start-86400,'completed')
        self.assertEqual(self.listing(missing='homework').json()['total'],2)
        self.assertEqual(self.upload('homework').status_code,201)
        result=self.listing(missing='homework',limit=1).json()
        self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['lesson_id'],other)
        self.assertEqual(self.listing(missing='notes').json()['total'],2)
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.listing(missing='notes').json()['total'],1)
        date_filter=self.listing(from_date='2026-10-17',to_date='2026-10-17').json()
        self.assertEqual(date_filter['total'],1);self.assertEqual(date_filter['items'][0]['lesson_id'],self.lesson_id)
        self.assertEqual(self.listing(from_date='2026-10-18',to_date='2026-10-17').status_code,422)
        self.assertEqual(self.listing(missing='invalid').status_code,422)
