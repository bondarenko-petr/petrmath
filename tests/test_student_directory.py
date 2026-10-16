import time
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from tests import test_accounts as support
from accounts import database
from main import app


class StudentDirectoryTests(unittest.TestCase):
    def setUp(self):
        support.AccountTests.setUp(self)
        self.admin_id=support.seed_user('Учитель','teacher','Teacher password!','admin')
        self.client.post('/api/auth/login',json={'username':'teacher','password':'Teacher password!'},headers=self.headers)
        self.debtor=support.seed_user('Борис','boris','Another password!')
        self.archived=support.seed_user('Анна','anna','Another password!')
        with database() as (c,p):
            c.execute('UPDATE users SET is_active=0 WHERE id=?',(self.archived,))
            c.execute('INSERT INTO student_profiles (user_id,default_price_kopecks,school_grade) VALUES (?,150000,9)',(self.id,))
            for amount in [150000,250000]:
                c.execute('INSERT INTO payments (request_id,student_id,amount_kopecks,lesson_count,note,created_at,created_by) VALUES (?,?,?,NULL,?,?,?)',
                    (str(uuid4()),self.id,amount,'Оплата',int(time.time()),self.admin_id))
            c.execute('INSERT INTO payments (request_id,student_id,amount_kopecks,lesson_count,note,created_at,created_by,voided_at) VALUES (?,?,?,NULL,?,?,?,?)',
                    (str(uuid4()),self.debtor,999999,'Отменённая оплата',int(time.time()),self.admin_id,int(time.time())))
            for student_id,price,status in [(self.id,100000,'completed'),(self.debtor,200000,'completed'),(self.id,500000,'scheduled'),(self.debtor,500000,'cancelled')]:
                c.execute('INSERT INTO lessons (student_id,starts_at,ends_at,duration_minutes,price_kopecks,timezone,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (student_id,1000,4600,60,price,'Europe/Moscow',status,1000))

    def tearDown(self):
        support.AccountTests.tearDown(self)

    def get(self,**params):
        return self.client.get('/api/admin/students',params={'include_finance':'true',**params})

    def test_all_balances_and_debt_filter(self):
        data=self.get().json()
        self.assertEqual(data['total'],3)
        rows={s['id']:s for s in data['items']}
        self.assertEqual(rows[self.id]['balance_kopecks'],300000)
        self.assertEqual(rows[self.debtor]['balance_kopecks'],-200000)
        self.assertEqual(rows[self.debtor]['debt_kopecks'],200000)
        self.assertEqual(rows[self.archived]['balance_kopecks'],0)
        self.assertEqual(rows[self.id]['school_grade'],9)
        debt=self.get(view='debt').json()
        self.assertEqual(debt['total'],1)
        self.assertEqual(debt['items'][0]['id'],self.debtor)
        self.assertEqual(self.get().headers['cache-control'],'no-store')

    def test_search_archive_and_escaped_wildcards(self):
        for query in ['boris','Борис','student@example.com']:
            self.assertEqual(self.get(search=query).json()['total'],1)
        for query in ['missing','%',"' OR 1=1 --"]:
            self.assertEqual(self.get(search=query).json()['total'],0)
        self.assertEqual(self.get(view='archive').json()['items'][0]['id'],self.archived)
        self.assertEqual(self.get(view='active').json()['total'],2)
        self.assertEqual(self.get(search='boris',view='archive').json()['total'],0)

    def test_server_sorting_and_pagination(self):
        first=self.get(sort='balance_asc',limit=1).json()
        second=self.get(sort='balance_asc',limit=1,offset=1).json()
        self.assertEqual(first['total'],3)
        self.assertEqual(first['items'][0]['id'],self.debtor)
        self.assertEqual(second['items'][0]['id'],self.archived)
        self.assertEqual(self.get(sort='balance_desc',limit=1).json()['items'][0]['id'],self.id)
        plain=self.client.get('/api/admin/students').json()
        self.assertNotIn('balance_kopecks',plain['items'][0])

    def test_access_and_invalid_filters(self):
        self.assertEqual(self.get(sort='DROP TABLE users').status_code,422)
        self.assertEqual(self.get(view='bad').status_code,422)
        self.assertEqual(self.get(search='x'*201).status_code,422)
        self.assertEqual(self.get(offset=-1).status_code,422)
        self.assertEqual(TestClient(app).get('/api/admin/students?include_finance=true').status_code,401)
        self.client.post('/api/auth/login',json=self.data,headers=self.headers)
        self.assertEqual(self.get().status_code,403)
