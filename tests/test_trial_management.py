import unittest
from fastapi.testclient import TestClient
from tests import test_accounts as support


class TrialManagementTests(unittest.TestCase):
    def setUp(self):
        support.AccountTests.setUp(self)
        support.seed_user('Админ','teacher','Teacher password!','admin')
        self.post=support.AccountTests.post.__get__(self)
        self.post('login',{'username':'teacher','password':'Teacher password!'})
        self.payload={'name':'Иван','email':'ivan@example.com','phone':'+79991234567','message':'ОГЭ','courses':['ОГЭ'],'consent':True}
        result=self.client.post('/api/trial-requests',json=self.payload)
        self.assertEqual(result.status_code,201,result.text)
        self.request_id=self.list().json()['items'][0]['id']

    def tearDown(self):
        support.AccountTests.tearDown(self)

    def list(self,**params):
        return self.client.get('/api/admin/trial-requests',params=params)

    def update(self,**data):
        return self.client.patch('/api/admin/trial-requests/'+str(self.request_id),json={'status':'contacting','admin_note':'Написал, жду ответ','close_reason':'','version':0,**data},headers=self.headers)

    def test_existing_requests_are_new_and_note_is_persistent(self):
        data=self.list().json()
        self.assertEqual(data['counts']['new'],1)
        self.assertEqual(data['items'][0]['status'],'new')
        self.assertEqual(data['items'][0]['version'],0)
        self.assertEqual(self.update().status_code,200)
        row=self.list().json()['items'][0]
        self.assertEqual(row['status'],'contacting')
        self.assertEqual(row['admin_note'],'Написал, жду ответ')
        self.assertEqual(row['email'],self.payload['email'])
        self.assertEqual(row['message'],self.payload['message'])
        self.assertEqual(self.list().headers['cache-control'],'no-store')

    def test_archive_reason_restore_and_enrollment(self):
        self.assertEqual(self.update(status='closed').status_code,422)
        self.assertEqual(self.update(status='closed',close_reason='no_response').status_code,200)
        data=self.list().json()
        self.assertEqual(data['total'],0)
        self.assertEqual(data['archive_total'],1)
        archived=self.list(view='archive').json()['items'][0]
        self.assertEqual(archived['close_reason'],'no_response')
        self.assertEqual(self.update(status='new',version=1).status_code,200)
        row=self.list().json()['items'][0]
        self.assertEqual(row['close_reason'],'')
        self.assertEqual(row['admin_note'],'Написал, жду ответ')
        self.assertEqual(self.update(status='enrolled',version=2).status_code,200)
        self.assertEqual(self.list().json()['total'],0)
        self.assertEqual(self.list(view='archive',status='enrolled').json()['total'],1)

    def test_search_filters_and_pagination(self):
        for term in ['Иван','ivan@','1234567']:
            self.assertEqual(self.list(search=term).json()['total'],1)
        for term in ['missing','%','_',"' OR 1=1 --"]:
            self.assertEqual(self.list(search=term).json()['total'],0)
        self.assertEqual(self.list(status='contacting').json()['total'],0)
        self.update(status='trial_scheduled')
        self.assertEqual(self.list(status='trial_scheduled').json()['total'],1)
        self.client.post('/api/trial-requests',json=self.payload|{'name':'Другой'})
        first=self.list(limit=1).json();second=self.list(limit=1,offset=1).json()
        self.assertEqual(first['total'],2)
        self.assertNotEqual(first['items'][0]['id'],second['items'][0]['id'])
        self.assertEqual(self.list(view='archive').json()['total'],0)

    def test_concurrent_edit_does_not_overwrite_note(self):
        self.assertEqual(self.update().status_code,200)
        self.assertEqual(self.update(admin_note='Устаревшее окно').status_code,409)
        self.assertEqual(self.list().json()['items'][0]['admin_note'],'Написал, жду ответ')

    def test_permissions_and_validation(self):
        self.assertEqual(self.list(limit=101).status_code,422)
        self.assertEqual(self.update(status='bad').status_code,422)
        self.assertEqual(self.update(version=True).status_code,422)
        self.assertEqual(self.update(admin_note='x'*2001).status_code,422)
        url='/api/admin/trial-requests/'+str(self.request_id)
        self.assertEqual(self.client.patch(url,json={'status':'new','version':0}).status_code,403)
        self.assertEqual(self.client.patch('/api/admin/trial-requests/9999',json={'status':'new','version':0},headers=self.headers).status_code,404)
        self.assertEqual(TestClient(self.client.app).get('/api/admin/trial-requests').status_code,401)
        self.post('login',self.data)
        self.assertEqual(self.list().status_code,403)
        self.assertEqual(self.update().status_code,403)

    def test_delete_archived_request_only_and_preserve_users(self):
        url='/api/admin/trial-requests/'+str(self.request_id)+'?version=1'
        self.assertEqual(self.client.delete(url,headers=self.headers).status_code,409)
        self.assertEqual(self.update(status='closed',close_reason='declined').status_code,200)
        self.assertEqual(self.client.delete(url.replace('version=1','version=2'),headers=self.headers).status_code,409)
        self.assertEqual(self.client.delete(url).status_code,403)
        result=self.client.delete(url,headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.list(view='archive').json()['archive_total'],0)
        from accounts import database
        with database() as (c,p):
            c.execute('SELECT COUNT(*) AS n FROM trial_requests');self.assertEqual(c.fetchone()['n'],0)
            c.execute('SELECT COUNT(*) AS n FROM trial_request_management');self.assertEqual(c.fetchone()['n'],0)
            c.execute('SELECT COUNT(*) AS n FROM users');self.assertEqual(c.fetchone()['n'],2)
        self.assertEqual(self.client.delete(url,headers=self.headers).status_code,404)

    def test_restored_request_cannot_be_deleted_and_student_forbidden(self):
        self.update(status='enrolled')
        self.assertEqual(self.update(status='new',version=1).status_code,200)
        url='/api/admin/trial-requests/'+str(self.request_id)+'?version=2'
        self.assertEqual(self.client.delete(url,headers=self.headers).status_code,409)
        self.post('login',self.data)
        self.assertEqual(self.client.delete(url,headers=self.headers).status_code,403)
