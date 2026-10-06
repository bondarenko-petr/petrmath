import os
from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import accounts
from main import app


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + '/test.sqlite3'
        self.env = patch.dict(os.environ, {'DB_BACKEND':'sqlite','TRIAL_REQUESTS_DB':self.path,'COOKIE_SECURE':'false'})
        self.env.start()
        accounts.attempts.clear()
        self.client = TestClient(app)
        self.headers = {'X-Requested-With':'KrugPi'}
        self.data = {'name':'Ученик','email':'student@example.com','password':'A long test password 123!'}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def post(self, path, data):
        return self.client.post('/api/auth/' + path, json=data, headers=self.headers)

    def test_registration_profile_logout_login(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        result = self.post('register', self.data | {'role':'teacher'})
        self.assertEqual(result.status_code, 201)
        self.assertIn('HttpOnly', result.headers['set-cookie'])
        profile = self.client.get('/api/auth/me').json()
        self.assertEqual(profile['role'], 'student')
        self.assertNotIn('password_hash', profile)
        with closing(sqlite3.connect(self.path)) as db:
            stored = db.execute('SELECT password_hash FROM users').fetchone()[0]
            self.assertNotEqual(stored, self.data['password'])
            self.assertTrue(accounts.verify(self.data['password'], stored))
        token = self.client.cookies.get(accounts.COOKIE)
        self.assertEqual(self.post('logout', {}).status_code, 200)
        self.client.cookies.set(accounts.COOKIE, token)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.post('login', self.data).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)

    def test_duplicate_wrong_password_expiry_and_csrf(self):
        self.assertEqual(self.client.post('/api/auth/register', json=self.data).status_code, 403)
        self.assertEqual(self.post('register', self.data | {'password':'short'}).status_code, 422)
        self.post('register', self.data)
        self.assertEqual(self.post('register', self.data | {'email':'STUDENT@example.com'}).status_code, 409)
        self.assertEqual(self.post('login', self.data | {'password':'wrong'}).status_code, 401)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE sessions SET expires_at=?', (int(time.time()) - 1,))
            db.commit()
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.post('/api/auth/logout', json={}, headers=self.headers | {'Sec-Fetch-Site':'cross-site'}).status_code, 403)

    def test_limit(self):
        for _ in range(10):
            self.assertEqual(self.post('login', self.data).status_code, 401)
        self.assertEqual(self.post('login', self.data).status_code, 429)
