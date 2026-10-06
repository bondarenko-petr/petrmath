import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
import accounts


class AdminTests(unittest.TestCase):
    def test_authorization_pagination_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DB_BACKEND':'sqlite','TRIAL_REQUESTS_DB':directory+'/test.sqlite3','COOKIE_SECURE':'false'}):
            accounts.attempts.clear()
            client = TestClient(app)
            paths = ['/api/admin/students','/api/admin/trial-requests']
            for path in paths:
                self.assertEqual(client.get(path).status_code,401)
            headers={'X-Requested-With':'KrugPi'}
            for i in range(3):
                self.assertEqual(client.post('/api/auth/register',json={'name':f'Ученик {i}','email':f'test{i}@example.com','password':'Long test password!','role':'admin'},headers=headers).status_code,201)
            for path in paths:
                self.assertEqual(client.get(path).status_code,403)
            client.post('/api/trial-requests',json={'name':'Тест','email':'test@example.com','courses':['ЕГЭ'],'consent':True})
            with closing(sqlite3.connect(directory+'/test.sqlite3')) as db:
                db.execute("UPDATE users SET role='admin' WHERE email='test2@example.com'")
                db.commit()
            result=client.get('/api/admin/students?limit=1&offset=1')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['total'],2)
            self.assertEqual(len(result.json()['items']),1)
            self.assertNotIn('password_hash',result.text)
            self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertEqual(client.get('/api/admin/trial-requests').json()['items'][0]['courses'],'ЕГЭ')
            self.assertEqual(client.get('/api/admin/students?limit=500').status_code,422)
            with closing(sqlite3.connect(directory+'/test.sqlite3')) as db:
                db.execute("UPDATE users SET role='student'")
                db.commit()
            self.assertEqual(client.get('/api/admin/students').status_code,403)
