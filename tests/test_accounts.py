import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import accounts
from main import app


def seed_user(name, username, password, role='student'):
    with accounts.database() as (c,p):
        c.execute(f'INSERT INTO users (name,username,email,password_hash,role) VALUES ({p},{p},{p},{p},{p})',(name,username,username if '@' in username else None,accounts.hash_password(password),role))
        return c.lastrowid


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'DB_BACKEND':'sqlite','TRIAL_REQUESTS_DB':self.temp.name+'/test.sqlite3','COOKIE_SECURE':'false'})
        self.env.start();accounts.attempts.clear();self.client=TestClient(app)
        self.headers={'X-Requested-With':'KrugPi'}
        self.data={'username':'student@example.com','password':'A long test password 123!'}
        self.id=seed_user('Ученик',self.data['username'],self.data['password'])

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def post(self,path,data):
        return self.client.post('/api/auth/'+path,json=data,headers=self.headers)

    def test_login_profile_logout(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        result=self.post('login',self.data);self.assertEqual(result.status_code,200)
        self.assertIn('HttpOnly',result.headers['set-cookie'])
        self.assertEqual(self.client.get('/api/auth/me').json()['role'],'student')
        token=self.client.cookies.get(accounts.COOKIE)
        self.post('logout',{});self.client.cookies.set(accounts.COOKIE,token)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_password_change_and_registration_disabled(self):
        self.assertEqual(self.post('register',{}).status_code,403)
        self.assertEqual(self.post('login',self.data|{'password':'wrong'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json=self.data).status_code,403)
        self.post('login',self.data)
        old_token=self.client.cookies.get(accounts.COOKIE)
        self.assertEqual(self.post('change-password',{'current_password':self.data['password'],'new_password':'New password 2026!'}).status_code,200)
        other=TestClient(app);other.cookies.set(accounts.COOKIE,old_token)
        self.assertEqual(other.get('/api/auth/me').status_code,401)
        self.assertEqual(self.post('login',self.data).status_code,401)

    def test_limit(self):
        for _ in range(10):self.assertEqual(self.post('login',self.data|{'password':'wrong'}).status_code,401)
        self.assertEqual(self.post('login',self.data).status_code,429)

    def test_legacy_sqlite_migration_preserves_account(self):
        import sqlite3
        from contextlib import closing
        legacy=self.temp.name+'/legacy.sqlite3'
        encoded=accounts.hash_password('Legacy password!')
        with closing(sqlite3.connect(legacy)) as db:
            db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'student')")
            db.execute("INSERT INTO users VALUES (1,'Прежний аккаунт','legacy@example.com',?,'admin')",(encoded,))
            db.commit()
        with patch.dict(os.environ,{'TRIAL_REQUESTS_DB':legacy}):
            self.assertEqual(self.post('login',{'username':'legacy@example.com','password':'Legacy password!'}).status_code,200)
            self.assertEqual(self.client.get('/api/auth/me').json()['role'],'admin')
