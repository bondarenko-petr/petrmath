import sqlite3
import unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests import test_materials as material_support
from tests.test_accounts import seed_user
from accounts import database
from main import app


class StudentLifecycleTests(unittest.TestCase):
    setUp=material_support.MaterialsTests.setUp
    tearDown=material_support.MaterialsTests.tearDown
    upload=material_support.MaterialsTests.upload
    save=material_support.MaterialsTests.save
    seed_lesson=material_support.MaterialsTests.seed_lesson

    def archive(self,active=False):
        return self.client.patch(f'/api/admin/students/{self.id}/active',json={'is_active':active},headers=self.headers)

    def delete(self,username=None):
        return self.client.request('DELETE',f'/api/admin/students/{self.id}',json={'username':username or self.data['username']},headers=self.headers)

    def test_archive_tabs_restore_and_future_lessons_remain(self):
        pupil=TestClient(app);pupil.post('/api/auth/login',json=self.data,headers=self.headers)
        self.assertEqual(pupil.get('/api/auth/me').status_code,200)
        self.assertEqual(self.archive().status_code,200)
        self.assertIn(pupil.get('/api/auth/me').status_code,(401,403))
        data=self.client.get('/api/admin/students?archive=true&include_finance=true').json()
        self.assertEqual(data['counts']['archive'],1)
        self.assertEqual([r['id'] for r in data['items']],[self.id])
        self.assertEqual(self.client.get('/api/admin/students?archive=false').json()['total'],0)
        preview=self.client.get(f'/api/admin/students/{self.id}/deletion-preview').json()
        self.assertEqual(preview['lessons'],2);self.assertEqual(preview['future_lessons'],1)
        self.assertEqual(self.archive(True).status_code,200)
        self.assertEqual(self.client.get('/api/admin/students?archive=false').json()['total'],1)
        with database() as (c,p):
            c.execute('SELECT status FROM lessons WHERE id=?',(self.next_id,));self.assertEqual(c.fetchone()['status'],'scheduled')

    def test_permanent_deletion_cleans_data_files_and_preserves_other_students(self):
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.upload().status_code,201)
        self.assertEqual(self.client.post('/api/finance/payments',json={'request_id':str(uuid4()),'student_id':self.id,'amount_kopecks':300000},headers=self.headers).status_code,201)
        other=seed_user('Другой','otherstudent','Other password!')
        other_lesson=self.seed_lesson(other,self.start+86400,'completed')
        with database() as (c,p):
            c.execute("INSERT INTO lesson_series (timezone,created_at) VALUES ('UTC',0)");series=c.lastrowid
            c.execute('UPDATE lessons SET series_id=? WHERE id IN (?,?)',(series,self.lesson_id,other_lesson))
            c.execute('SELECT storage_key FROM material_files');key=c.fetchone()['storage_key']
        path=self.folder/key;self.assertTrue(path.exists())
        self.archive();preview=self.client.get(f'/api/admin/students/{self.id}/deletion-preview').json()
        self.assertEqual(preview['files'],1);self.assertEqual(preview['payments'],1);self.assertEqual(preview['balance_kopecks'],100000)
        result=self.delete();self.assertEqual(result.status_code,200,result.text);self.assertFalse(result.json()['file_cleanup_pending'])
        self.assertFalse(path.exists())
        with database() as (c,p):
            for table,field in [('users','id'),('student_profiles','user_id'),('sessions','user_id'),('payments','student_id'),('lessons','student_id')]:
                c.execute(f'SELECT COUNT(*) AS n FROM {table} WHERE {field}=?',(self.id,));self.assertEqual(c.fetchone()['n'],0)
            c.execute('SELECT COUNT(*) AS n FROM material_files');self.assertEqual(c.fetchone()['n'],0)
            c.execute('SELECT COUNT(*) AS n FROM lesson_materials');self.assertEqual(c.fetchone()['n'],0)
            c.execute('SELECT id FROM users WHERE id=?',(other,));self.assertIsNotNone(c.fetchone())
            c.execute('SELECT id FROM lesson_series WHERE id=?',(series,));self.assertIsNotNone(c.fetchone())
        self.assertEqual(self.delete().status_code,404)

    def test_deletion_requires_admin_archive_exact_login_and_csrf(self):
        self.assertEqual(self.delete().status_code,409)
        self.archive();self.assertEqual(self.delete('wrong-login').status_code,422)
        self.assertEqual(self.client.request('DELETE',f'/api/admin/students/{self.id}',json={'username':self.data['username']}).status_code,403)
        anonymous=TestClient(app)
        self.assertEqual(anonymous.request('DELETE',f'/api/admin/students/{self.id}',json={'username':self.data['username']},headers=self.headers).status_code,401)
        other=seed_user('Активный','activeother','Other password!')
        pupil=TestClient(app);pupil.post('/api/auth/login',json={'username':'activeother','password':'Other password!'},headers=self.headers)
        self.assertEqual(pupil.request('DELETE',f'/api/admin/students/{self.id}',json={'username':self.data['username']},headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/api/admin/students').json()['total'],2)

    def test_database_failure_restores_staged_files_and_all_records(self):
        self.upload();self.archive()
        with database() as (c,p):
            c.execute('SELECT storage_key FROM material_files');key=c.fetchone()['storage_key']
            c.execute("CREATE TRIGGER block_student_delete BEFORE DELETE ON users BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.assertEqual(self.delete().status_code,503)
        self.assertTrue((self.folder/key).exists())
        preview=self.client.get(f'/api/admin/students/{self.id}/deletion-preview').json()
        self.assertEqual(preview['files'],1);self.assertEqual(preview['lessons'],2)
