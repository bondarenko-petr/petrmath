import time
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import unittest
from tests import test_accounts as account_tests
seed_user = account_tests.seed_user
from main import app
from accounts import database


class LessonTests(unittest.TestCase):
    post = account_tests.AccountTests.post
    tearDown = account_tests.AccountTests.tearDown
    def setUp(self):
        account_tests.AccountTests.setUp(self)
        seed_user('Преподаватель','teacher','Teacher password 2026!', 'admin')
        self.post('login',{'username':'teacher','password':'Teacher password 2026!'})
        with database() as (c,p):
            c.execute('INSERT INTO student_profiles (user_id,default_price_kopecks,default_duration_minutes) VALUES (?,123456,45)',(self.id,))
        self.start=(datetime.now(timezone.utc)+timedelta(days=14)).replace(hour=10,minute=0,second=0,microsecond=0)
        self.lesson={'student_id':self.id,'starts_at':self.start.isoformat(),'timezone':'Europe/Moscow','topic':'Дроби'}

    def create(self,data=None):
        return self.client.post('/api/lessons',json=data or self.lesson,headers=self.headers)

    def test_snapshot_conflict_and_student_permissions(self):
        result=self.create();self.assertEqual(result.status_code,201,result.text)
        lesson_id=result.json()['ids'][0]
        self.assertEqual(self.create().status_code,409)
        with database() as (c,p):
            c.execute('UPDATE student_profiles SET default_price_kopecks=999 WHERE user_id=?',(self.id,))
        row=self.client.get('/api/lessons').json()['items'][0]
        self.assertEqual(row['price_kopecks'],123456);self.assertEqual(row['duration_minutes'],45)
        self.post('logout',{});self.post('login',self.data)
        self.assertEqual(self.client.get('/api/lessons').json()['total'],1)
        other=seed_user('Другой','another','Another password!')
        self.assertEqual(self.client.get('/api/lessons?student_id='+str(other)).json()['total'],1)
        self.assertEqual(self.create().status_code,403)
        self.assertEqual(self.client.delete('/api/lessons/'+str(lesson_id),headers=self.headers).status_code,403)
        outsider=TestClient(app)
        self.assertEqual(outsider.get('/api/lessons').status_code,401)

    def test_series_scopes_and_atomic_conflict(self):
        end=self.start+timedelta(days=21)
        result=self.create(self.lesson|{'weekdays':[self.start.weekday()],'recurrence_end':end.date().isoformat()})
        self.assertEqual(result.status_code,201,result.text);self.assertEqual(result.json()['count'],4)
        ids=result.json()['ids']
        response=self.client.put('/api/lessons/'+str(ids[1]),json=self.lesson|{'starts_at':(self.start+timedelta(days=7,hours=1)).isoformat(),'scope':'following'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['updated'],3)
        rows=self.client.get('/api/lessons').json()['items']
        self.assertEqual(datetime.fromisoformat(rows[0]['starts_at']),self.start)
        self.assertEqual(datetime.fromisoformat(rows[1]['starts_at']),self.start+timedelta(days=7,hours=1))
        self.assertEqual(self.client.patch('/api/lessons/'+str(ids[1])+'/status',json={'status':'cancelled','scope':'following'},headers=self.headers).json()['updated'],3)
        self.assertEqual(self.client.delete('/api/lessons/'+str(ids[2])+'?scope=following',headers=self.headers).json()['deleted'],2)
        self.assertEqual(self.client.get('/api/lessons').json()['total'],2)

    def test_history_and_validation(self):
        lesson_id=self.create().json()['ids'][0]
        self.assertEqual(self.client.patch('/api/lessons/'+str(lesson_id)+'/status',json={'status':'completed'},headers=self.headers).status_code,422)
        with database() as (c,p):
            c.execute('UPDATE lessons SET starts_at=?,ends_at=? WHERE id=?',(int(time.time())-7200,int(time.time())-3600,lesson_id))
        self.assertEqual(self.client.patch('/api/lessons/'+str(lesson_id)+'/status',json={'status':'completed'},headers=self.headers).status_code,200)
        self.assertEqual(self.client.delete('/api/lessons/'+str(lesson_id),headers=self.headers).status_code,409)
        self.assertEqual(self.create(self.lesson|{'meeting_url':'javascript:alert(1)'}).status_code,422)
        self.assertEqual(self.create(self.lesson|{'price_kopecks':1.5}).status_code,422)
        self.assertEqual(self.create(self.lesson|{'starts_at':'2027-03-28T02:30','timezone':'Europe/Berlin'}).status_code,422)
        self.assertEqual(self.create(self.lesson|{'starts_at':'2027-10-31T02:30','timezone':'Europe/Berlin'}).status_code,422)

    def test_own_summary_and_forced_change(self):
        other=seed_user('Другой','another','Another password!')
        self.create();self.create(self.lesson|{'student_id':other,'starts_at':(self.start+timedelta(hours=2)).isoformat()})
        self.post('logout',{});self.post('login',self.data)
        summary=self.client.get('/api/lessons/summary').json()
        self.assertEqual(len(summary['upcoming']),1)
        self.assertEqual(summary['upcoming'][0]['student_id'],self.id)
        with database() as (c,p):c.execute('UPDATE users SET must_change_password=1 WHERE id=?',(self.id,))
        self.assertEqual(self.client.get('/api/lessons').status_code,403)

    def test_conflicting_series_rolls_back_and_scope_one(self):
        self.create(self.lesson | {'starts_at':(self.start+timedelta(days=7)).isoformat()})
        result=self.create(self.lesson | {'weekdays':[self.start.weekday()],'recurrence_end':(self.start+timedelta(days=14)).date().isoformat()})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.client.get('/api/lessons').json()['total'],1)
        series=self.create(self.lesson | {'starts_at':(self.start+timedelta(hours=2)).isoformat(),'weekdays':[self.start.weekday()],'recurrence_end':(self.start+timedelta(days=14)).date().isoformat()})
        ids=series.json()['ids']
        self.assertEqual(self.client.patch('/api/lessons/'+str(ids[0])+'/status',json={'status':'cancelled','scope':'one'},headers=self.headers).json()['updated'],1)
        self.assertEqual(self.client.patch('/api/lessons/'+str(ids[1])+'/status',json={'status':'cancelled','scope':'series'},headers=self.headers).json()['updated'],3)

    def test_recurrence_keeps_local_time_across_dst(self):
        result=self.create(self.lesson | {'starts_at':'2027-03-21T10:00','timezone':'Europe/Berlin','weekdays':[6],'recurrence_end':'2027-03-28'})
        self.assertEqual(result.status_code,201,result.text)
        rows=self.client.get('/api/lessons').json()['items']
        first=datetime.fromisoformat(rows[0]['starts_at'])
        second=datetime.fromisoformat(rows[1]['starts_at'])
        self.assertEqual(first.hour,9);self.assertEqual(second.hour,8)
