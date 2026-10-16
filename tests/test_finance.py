import time
import unittest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from tests import test_accounts as support
from accounts import database
from main import app


class FinanceTests(unittest.TestCase):
    def setUp(self):
        support.AccountTests.setUp(self)
        self.admin_id=support.seed_user('Преподаватель','teacher','Teacher password!','admin')
        self.client.post('/api/auth/login',json={'username':'teacher','password':'Teacher password!'},headers=self.headers)
        self.payload={'request_id':str(uuid4()),'student_id':self.id,'amount_kopecks':800000,'lesson_count':4,'note':'Пакет'}

    def tearDown(self):
        support.AccountTests.tearDown(self)

    def pay(self,payload=None,client=None):
        return (client or self.client).post('/api/finance/payments',json=payload or self.payload,headers=self.headers)

    def summary(self,client=None,**params):
        return (client or self.client).get('/api/finance/balance',params={'student_id':self.id,**params})

    def historic_lesson(self,price=200000,status='scheduled'):
        with database() as (c,p):
            now=int(time.time())
            c.execute("INSERT INTO lessons (student_id,starts_at,ends_at,duration_minutes,price_kopecks,timezone,status,created_at) VALUES (?,?,?,?,?,'Europe/Moscow',?,?)",(self.id,now-7200,now-3600,60,price,status,now))
            return c.lastrowid

    def test_balances_completion_and_cancelled_lesson(self):
        self.assertEqual(self.pay().status_code,201)
        lesson=self.historic_lesson()
        cancelled=self.historic_lesson(status='cancelled')
        for _ in range(2):
            r=self.client.patch(f'/api/lessons/{lesson}/status',json={'status':'completed'},headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
        data=self.summary().json()
        self.assertEqual(data['student']['remaining_lessons'],3)
        self.assertEqual(data['student']['balance_kopecks'],600000)
        self.assertEqual(data['student']['completed_lessons'],1)
        self.assertEqual(data['total'],2)
        self.assertEqual(sum(i['amount_kopecks'] for i in data['items']),600000)
        self.assertNotIn(cancelled,[i['id'] for i in data['items'] if i['kind']=='lesson'])
        self.assertEqual(self.summary().headers['cache-control'],'no-store')

    def test_existing_lessons_and_independent_balances(self):
        self.historic_lesson(price=123456,status='completed')
        before=self.summary().json()['student']
        self.assertEqual(before['remaining_lessons'],-1)
        self.assertEqual(before['balance_kopecks'],-123456)
        self.pay(self.payload|{'amount_kopecks':500001,'lesson_count':2})
        with database() as (c,p):
            c.execute('INSERT INTO student_profiles (user_id,default_price_kopecks) VALUES (?,999999)',(self.id,))
        data=self.summary().json()['student']
        self.assertEqual(data['remaining_lessons'],1)
        self.assertEqual(data['balance_kopecks'],376545)
        self.assertEqual(data['spent_kopecks'],123456)

    def test_retry_and_conflicting_idempotency_payload(self):
        self.assertEqual(self.pay().status_code,201)
        self.assertEqual(self.pay().status_code,200)
        self.assertEqual(self.pay(self.payload|{'amount_kopecks':1}).status_code,409)
        self.assertEqual(self.summary().json()['total'],1)
        self.assertEqual(self.summary().json()['student']['balance_kopecks'],800000)

    def test_concurrent_retries_create_one_payment(self):
        cookies=dict(self.client.cookies)
        def send(_):
            with TestClient(app) as client:
                client.cookies.update(cookies)
                return self.pay(client=client).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes=list(pool.map(send,range(4)))
        self.assertEqual(codes.count(201),1,codes)
        self.assertEqual(codes.count(200),3,codes)
        self.assertEqual(self.summary().json()['total'],1)

    def test_void_preserves_audit_and_is_idempotent(self):
        payment=self.pay().json()['id']
        self.historic_lesson(status='completed')
        url=f'/api/finance/payments/{payment}/void'
        self.assertEqual(self.client.post(url,json={'reason':'   '},headers=self.headers).status_code,422)
        for _ in range(2):
            self.assertEqual(self.client.post(url,json={'reason':'Ошибка ввода'},headers=self.headers).status_code,200)
        data=self.summary().json()
        self.assertEqual(data['student']['balance_kopecks'],-200000)
        self.assertEqual(data['student']['remaining_lessons'],-1)
        payment_row=next(r for r in data['items'] if r['kind']=='payment')
        self.assertTrue(payment_row['voided_at'])
        self.assertEqual(payment_row['void_reason'],'Ошибка ввода')
        self.assertEqual(self.pay().status_code,200)
        self.assertEqual(self.summary().json()['student']['balance_kopecks'],-200000)

    def test_authorization_ownership_and_forced_password_change(self):
        self.pay()
        other=support.seed_user('Другой','other','Another password!')
        self.pay(self.payload|{'request_id':str(uuid4()),'student_id':other,'amount_kopecks':12345})
        anonymous=TestClient(app)
        self.assertEqual(self.summary(client=anonymous).status_code,401)
        self.client.post('/api/auth/login',json=self.data,headers=self.headers)
        data=self.summary(student_id=other).json()
        self.assertEqual(data['student']['id'],self.id)
        self.assertEqual(data['student']['balance_kopecks'],800000)
        self.assertEqual(self.pay().status_code,403)
        self.assertEqual(self.client.post('/api/finance/payments/1/void',json={'reason':'x'},headers=self.headers).status_code,403)
        with database() as (c,p):
            c.execute('UPDATE users SET must_change_password=1 WHERE id=?',(self.id,))
        self.assertEqual(self.summary().status_code,403)

    def test_validation_csrf_and_pagination(self):
        for change in [{'amount_kopecks':0},{'amount_kopecks':1.5},{'lesson_count':0},{'lesson_count':True},{'request_id':'bad'}]:
            self.assertEqual(self.pay(self.payload|change).status_code,422)
        self.assertEqual(self.client.post('/api/finance/payments',json=self.payload).status_code,403)
        self.assertEqual(self.pay(self.payload|{'student_id':self.admin_id}).status_code,404)
        self.pay()
        self.historic_lesson(status='completed')
        first=self.summary(limit=1,offset=0).json()
        second=self.summary(limit=1,offset=1).json()
        self.assertEqual(first['total'],2)
        self.assertNotEqual(first['items'][0]['kind'],second['items'][0]['kind'])
        self.assertEqual(self.summary(limit=101).status_code,422)
        self.assertEqual(self.client.get('/api/finance/balance').status_code,422)
