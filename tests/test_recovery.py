import time
from unittest.mock import patch
from tests.test_accounts import AccountTests
from accounts import database

class RecoveryTests(AccountTests):
    def setUp(self):
        super().setUp()
        self.messages=[]
        self.sender=patch('recovery.send_account_link',side_effect=lambda *args:self.messages.append(args))
        self.sender.start()
    def tearDown(self):
        self.sender.stop();super().tearDown()
    def verified(self):
        self.post('login',self.data)
        self.assertEqual(self.post('verify-email/request',{}).status_code,200)
        token=self.messages[-1][2]
        self.assertEqual(self.post('verify-email/confirm',{'token':token}).status_code,200)
        self.assertEqual(self.post('verify-email/confirm',{'token':token}).status_code,400)
        self.assertTrue(self.client.get('/api/auth/email-status').json()['verified'])
    def test_reset_is_one_use_and_revokes_sessions(self):
        self.verified()
        self.post('forgot-password',{'email':self.data['username']})
        token=self.messages[-1][2]
        with database() as (c,p):
            c.execute('SELECT token_hash FROM account_links');self.assertNotEqual(c.fetchone()['token_hash'],token)
        result=self.post('reset-password',{'token':token,'new_password':'Different secure password 123!'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(self.post('reset-password',{'token':token,'new_password':'Another password 123!'}).status_code,400)
        self.assertEqual(self.post('login',self.data).status_code,401)
        self.assertEqual(self.post('login',self.data|{'password':'Different secure password 123!'}).status_code,200)
    def test_unknown_unverified_addresses_and_cooldown(self):
        first=self.post('forgot-password',{'email':'nobody@example.com'})
        second=self.post('forgot-password',{'email':self.data['username']})
        self.assertEqual(first.json(),second.json());self.assertEqual(self.messages,[])
        self.verified();self.post('forgot-password',{'email':self.data['username']});count=len(self.messages)
        self.post('forgot-password',{'email':self.data['username']});self.assertEqual(len(self.messages),count)
    def test_expired_link_and_email_change(self):
        self.verified();self.post('forgot-password',{'email':self.data['username']});token=self.messages[-1][2]
        with database() as (c,p):c.execute('UPDATE account_links SET expires_at=?',(int(time.time())-1,))
        self.assertEqual(self.post('reset-password',{'token':token,'new_password':'Different secure password!'}).status_code,400)
        self.assertEqual(self.post('profile',{'email':'changed@example.com'}).status_code,200)
        self.assertFalse(self.client.get('/api/auth/email-status').json()['verified'])
    def test_admin_reset_invalidates_link(self):
        self.verified();self.post('forgot-password',{'email':self.data['username']});token=self.messages[-1][2]
        from tests.test_accounts import seed_user
        seed_user('Admin','admin','Admin password 123!','admin')
        self.post('login',{'username':'admin','password':'Admin password 123!'})
        response=self.client.post('/api/admin/students/'+str(self.id)+'/reset-password',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.post('reset-password',{'token':token,'new_password':'New password 123!'}).status_code,400)
    def test_no_action_without_csrf_header(self):
        self.assertEqual(self.client.post('/api/auth/forgot-password',json={'email':self.data['username']}).status_code,403)
    def test_new_request_replaces_previous_and_archived_account_is_blocked(self):
        self.verified();self.post('forgot-password',{'email':self.data['username']});old=self.messages[-1][2]
        with database() as (c,p):c.execute('UPDATE account_links SET created_at=?',(int(time.time())-61,))
        self.post('forgot-password',{'email':self.data['username']});new=self.messages[-1][2];self.assertNotEqual(old,new)
        self.assertEqual(self.post('reset-password',{'token':old,'new_password':'Another password 123!'}).status_code,400)
        with database() as (c,p):c.execute('UPDATE users SET is_active=0 WHERE id=?',(self.id,))
        self.assertEqual(self.post('reset-password',{'token':new,'new_password':'Another password 123!'}).status_code,400)
    def test_regular_password_change_invalidates_reset_link(self):
        self.verified();self.post('forgot-password',{'email':self.data['username']});token=self.messages[-1][2]
        self.assertEqual(self.post('change-password',{'current_password':self.data['password'],'new_password':'Changed password 123!'}).status_code,200)
        self.assertEqual(self.post('reset-password',{'token':token,'new_password':'Another password 123!'}).status_code,400)
