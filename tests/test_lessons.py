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

    def test_week_overlap_includes_previous_day_lesson(self):
        start=datetime(2027,1,3,23,30,tzinfo=timezone.utc)
        lesson_id=self.create(self.lesson|{'starts_at':start.isoformat(),'timezone':'UTC','duration_minutes':90}).json()['ids'][0]
        lower=int(datetime(2027,1,4,tzinfo=timezone.utc).timestamp())
        upper=lower+7*86400
        normal=self.client.get('/api/lessons',params={'from_ts':lower,'to_ts':upper}).json()
        overlapping=self.client.get('/api/lessons',params={'from_ts':lower,'to_ts':upper,'overlap':'true'}).json()
        self.assertEqual(normal['total'],0)
        self.assertEqual(overlapping['total'],1)
        self.assertEqual(overlapping['items'][0]['id'],lesson_id)
        with database() as (c,p):c.execute('UPDATE lessons SET ends_at=? WHERE id=?',(lower,lesson_id))
        self.assertEqual(self.client.get('/api/lessons',params={'from_ts':lower,'to_ts':upper,'overlap':'true'}).json()['total'],0)

    def test_student_timezone_filters_and_profile_change_keep_instants(self):
        result=self.create(self.lesson|{'starts_at':'2027-01-04T20:00:00Z'})
        self.assertEqual(result.status_code,201,result.text)
        with database() as (c,p):c.execute('UPDATE student_profiles SET timezone=? WHERE user_id=?',('Asia/Vladivostok',self.id))
        admin_row=self.client.get('/api/lessons').json()['items'][0]
        self.assertEqual(admin_row['student_timezone'],'Asia/Vladivostok')
        self.post('logout',{});self.post('login',self.data)
        self.assertEqual(self.client.get('/api/lessons/settings').json()['timezone'],'Asia/Vladivostok')
        rows=self.client.get('/api/lessons?from_date=2027-01-05&to_date=2027-01-06').json()['items']
        self.assertEqual(rows[0]['starts_at'],'2027-01-04T20:00:00+00:00')
        self.assertEqual(self.client.get('/api/lessons?from_date=2027-01-04&to_date=2027-01-05').json()['total'],0)
        self.assertEqual(self.client.get('/api/lessons/summary').json()['timezone'],'Asia/Vladivostok')
        with database() as (c,p):c.execute('UPDATE student_profiles SET timezone=? WHERE user_id=?',('Europe/Berlin',self.id))
        self.assertEqual(self.client.get('/api/lessons').json()['items'][0]['starts_at'],rows[0]['starts_at'])

    def test_student_series_keeps_wall_time_across_dst_and_bulk_edit(self):
        with database() as (c,p):c.execute('UPDATE student_profiles SET timezone=? WHERE user_id=?',('Europe/Berlin',self.id))
        data=self.lesson|{'starts_at':'2027-03-22T20:00:00','timezone':'Europe/Moscow','weekdays':[0],'recurrence_end':'2027-04-05','recurrence_timezone':'student'}
        result=self.create(data);self.assertEqual(result.status_code,201,result.text)
        rows=self.client.get('/api/lessons').json()['items']
        self.assertEqual([r['starts_at'][11:16] for r in rows],['17:00','16:00','16:00'])
        self.assertTrue(all(r['timezone']=='Europe/Berlin' for r in rows))
        # The editor submits an absolute instant and the existing series timezone.
        edit=self.lesson|{'starts_at':'2027-03-22T17:00:00Z','timezone':'Europe/Berlin','scope':'series','topic':'Новая тема'}
        response=self.client.put('/api/lessons/'+str(rows[0]['id']),json=edit,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([r['starts_at'] for r in self.client.get('/api/lessons').json()['items']],[r['starts_at'] for r in rows])

    def test_profile_timezone_validation_and_storage(self):
        data={'name':'Новый','username':'timezonetest','default_price_kopecks':1000,'default_duration_minutes':60,'timezone':'Mars/Unknown'}
        response=self.client.post('/api/admin/students',json=data,headers=self.headers)
        self.assertEqual(response.status_code,422,response.text)
        data['timezone']='Asia/Vladivostok'
        response=self.client.post('/api/admin/students',json=data,headers=self.headers)
        self.assertEqual(response.status_code,201,response.text)
        rows=self.client.get('/api/admin/students').json()['items']
        self.assertEqual(next(r for r in rows if r['id']==response.json()['id'])['timezone'],'Asia/Vladivostok')

    def test_admin_berlin_display_preserves_student_fallback_and_lesson(self):
        from unittest.mock import patch
        with patch.dict('os.environ',{'ADMIN_TIMEZONE':'Europe/Berlin','LESSON_TIMEZONE':'Europe/Moscow'}):
            settings=self.client.get('/api/lessons/settings').json()
            self.assertEqual(settings['timezone'],'Europe/Berlin')
            self.assertEqual(settings['student_default_timezone'],'Europe/Moscow')
            result=self.create(self.lesson|{'starts_at':'2027-01-04T23:30:00Z'})
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual(self.client.get('/api/lessons?from_date=2027-01-05&to_date=2027-01-06').json()['total'],1)
            self.assertEqual(self.client.get('/api/lessons/summary').json()['timezone'],'Europe/Berlin')
            self.post('logout',{});self.post('login',self.data)
            self.assertEqual(self.client.get('/api/lessons/settings').json()['timezone'],'Europe/Moscow')
            self.assertEqual(self.client.get('/api/lessons').json()['items'][0]['starts_at'],'2027-01-04T23:30:00+00:00')

    def test_admin_display_timezone_filters_without_changing_student_settings(self):
        response=self.create(self.lesson|{'starts_at':'2027-01-04T22:30:00Z'})
        self.assertEqual(response.status_code,201,response.text)
        params={'from_date':'2027-01-05','to_date':'2027-01-06','display_timezone':'Europe/Moscow'}
        self.assertEqual(self.client.get('/api/lessons',params=params).json()['total'],1)
        params['display_timezone']='Europe/Berlin'
        self.assertEqual(self.client.get('/api/lessons',params=params).json()['total'],0)
        self.assertEqual(self.client.get('/api/lessons?display_timezone=Bad/Zone').status_code,422)
        self.post('logout',{});self.post('login',self.data)
        # A student cannot override the profile's timezone with this admin parameter.
        self.assertEqual(self.client.get('/api/lessons',params=params).json()['total'],1)
        row=self.client.get('/api/lessons').json()['items'][0]
        self.assertEqual(row['starts_at'],'2027-01-04T22:30:00+00:00')

    def test_cancellation_preserves_history_balance_and_restoration_checks_conflict(self):
        lesson_id=self.create().json()['ids'][0]
        before=self.client.get('/api/finance/balance',params={'student_id':self.id}).json()['student']['balance_kopecks']
        cancelled=self.client.patch('/api/lessons/'+str(lesson_id)+'/status',json={'status':'cancelled'},headers=self.headers)
        self.assertEqual(cancelled.status_code,200,cancelled.text)
        rows=self.client.get('/api/lessons').json()['items']
        self.assertEqual(rows[0]['status'],'cancelled')
        self.assertEqual(self.client.get('/api/finance/balance',params={'student_id':self.id}).json()['student']['balance_kopecks'],before)
        replacement=self.create();self.assertEqual(replacement.status_code,201,replacement.text)
        restore=self.client.patch('/api/lessons/'+str(lesson_id)+'/status',json={'status':'scheduled'},headers=self.headers)
        self.assertEqual(restore.status_code,409)
        self.post('logout',{});self.post('login',self.data)
        forbidden=self.client.patch('/api/lessons/'+str(lesson_id)+'/status',json={'status':'cancelled'},headers=self.headers)
        self.assertEqual(forbidden.status_code,403)
        self.assertTrue(any(row['id']==lesson_id and row['status']=='cancelled' for row in self.client.get('/api/lessons').json()['items']))
