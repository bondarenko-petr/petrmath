import unittest
from tests import test_accounts as support
from accounts import database


class StudentProfileTests(unittest.TestCase):
    setUp=support.AccountTests.setUp
    tearDown=support.AccountTests.tearDown
    post=support.AccountTests.post

    def login(self):self.post('login',self.data)

    def test_student_updates_contact_and_timezone_without_changing_login_or_rates(self):
        self.login()
        with database() as (c,p):
            c.execute('INSERT INTO student_profiles (user_id,default_price_kopecks,default_duration_minutes) VALUES (?,123456,90)',(self.id,))
            c.execute("INSERT INTO lessons (student_id,starts_at,ends_at,duration_minutes,price_kopecks,timezone,status,created_at) VALUES (?,2000000000,2000002700,45,123456,'Europe/Moscow','scheduled',0)",(self.id,))
        response=self.post('profile',{'email':'NewContact@example.com','phone':'  +49 123 456  ','timezone':'Asia/Vladivostok'})
        self.assertEqual(response.status_code,200,response.text)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['email'],'newcontact@example.com');self.assertEqual(me['phone'],'+49 123 456');self.assertEqual(me['username'],self.data['username'])
        self.assertEqual(self.client.get('/api/lessons/settings').json()['timezone'],'Asia/Vladivostok')
        with database() as (c,p):
            c.execute('SELECT * FROM student_profiles WHERE user_id=?',(self.id,));row=c.fetchone();self.assertEqual(row['default_price_kopecks'],123456);self.assertEqual(row['default_duration_minutes'],90)
            c.execute('SELECT starts_at FROM lessons WHERE student_id=?',(self.id,));self.assertEqual(c.fetchone()['starts_at'],2000000000)
        self.post('logout',{});self.assertEqual(self.post('login',self.data).status_code,200)

    def test_permissions_validation_and_email_conflict_are_atomic(self):
        self.assertEqual(self.post('profile',{'phone':'x'}).status_code,401)
        self.login()
        for extra in [{'role':'admin'},{'student_id':999},{'default_price_kopecks':0},{'username':'changed'}]:
            self.assertEqual(self.post('profile',{'phone':'x',**extra}).status_code,422)
        self.assertEqual(self.post('profile',{'timezone':'Bad/Zone'}).status_code,422)
        self.assertEqual(self.post('profile',{'email':'not-an-email'}).status_code,422)
        support.seed_user('Другой','otherprofile@example.com','Other password!')
        response=self.post('profile',{'email':'otherprofile@example.com','phone':'should not persist','timezone':'UTC'})
        self.assertEqual(response.status_code,409,response.text)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['phone'],'');self.assertEqual(me['email'],self.data['username'])
        self.assertEqual(self.client.post('/api/auth/profile',json={'phone':'x'}).status_code,403)

    def test_missing_profile_created_and_temporary_password_cannot_edit(self):
        self.login();self.assertEqual(self.post('profile',{'phone':'123','timezone':None}).status_code,200)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['phone'],'123');self.assertIsNone(me['timezone']);self.assertEqual(me['effective_timezone'],'Europe/Moscow')
        with database() as (c,p):c.execute('UPDATE users SET must_change_password=1 WHERE id=?',(self.id,))
        self.assertEqual(self.post('profile',{'phone':'changed'}).status_code,403)

    def test_parent_contacts_are_shared_between_student_and_admin_editors(self):
        self.login()
        result=self.post('profile',{'email':self.data['username'],'parent_name':'  Анна Петровна  ','parent_phone':'  +7 999 123-45-67  '})
        self.assertEqual(result.status_code,200,result.text)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['parent_name'],'Анна Петровна');self.assertEqual(me['parent_phone'],'+7 999 123-45-67')
        support.seed_user('Преподаватель','parent_teacher','Teacher password!','admin')
        self.post('logout',{});self.post('login',{'username':'parent_teacher','password':'Teacher password!'})
        row=next(row for row in self.client.get('/api/admin/students').json()['items'] if row['id']==self.id)
        self.assertEqual(row['parent_name'],'Анна Петровна')
        response=self.client.put(f'/api/admin/students/{self.id}',json={'name':row['name'],'username':row['username'],'email':row['email'],'phone':row['phone'],'default_price_kopecks':row['default_price_kopecks'],'default_duration_minutes':row['default_duration_minutes'],'timezone':row['timezone'],'parent_name':'Алексей','parent_phone':'+49 123'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.post('logout',{});self.post('login',self.data)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['parent_name'],'Алексей');self.assertEqual(me['parent_phone'],'+49 123')

    def test_parent_contact_length_validation(self):
        self.login()
        self.assertEqual(self.post('profile',{'parent_name':'x'*101}).status_code,422)
        self.assertEqual(self.post('profile',{'parent_phone':'1'*41}).status_code,422)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['parent_name'],'');self.assertEqual(me['parent_phone'],'')

    def test_information_card_is_admin_only_and_returns_current_contacts(self):
        endpoint=f'/api/admin/students/{self.id}'
        self.assertEqual(self.client.get(endpoint).status_code,401)
        self.login();self.assertEqual(self.client.get(endpoint).status_code,403)
        self.post('profile',{'phone':'+49 100','parent_name':'Анна','parent_phone':'+49 200','timezone':'Europe/Berlin'})
        admin_id=support.seed_user('Преподаватель','info_teacher','Teacher password!','admin')
        self.post('logout',{});self.post('login',{'username':'info_teacher','password':'Teacher password!'})
        response=self.client.get(endpoint);self.assertEqual(response.status_code,200,response.text)
        info=response.json();self.assertEqual(info['phone'],'+49 100');self.assertEqual(info['parent_name'],'Анна');self.assertEqual(info['parent_phone'],'+49 200');self.assertEqual(info['effective_timezone'],'Europe/Berlin');self.assertEqual(info['balance_kopecks'],0)
        self.assertNotIn('password_hash',info);self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(self.client.get(f'/api/admin/students/{admin_id}').status_code,404)
