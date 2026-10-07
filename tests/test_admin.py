import tests.test_accounts as support


class StudentManagementTests(support.AccountTests):
    def test_management_flow(self):
        self.post('login',self.data)
        self.assertEqual(self.client.get('/api/admin/students').status_code,403)
        support.seed_user('Админ','admin','Admin test password!','admin')
        self.post('login',{'username':'admin','password':'Admin test password!'})
        data={'name':'Новый ученик','username':'learner','email':None,'phone':'123','school_grade':9,'default_price_kopecks':150050,'default_duration_minutes':45}
        result=self.client.post('/api/admin/students',json=data,headers=self.headers)
        self.assertEqual(result.status_code,201)
        self.assertEqual(self.client.post('/api/admin/students',json=data|{'username':'badprice','default_price_kopecks':1.5},headers=self.headers).status_code,422)
        created=result.json();password=created['temporary_password'];uid=created['id']
        self.assertNotIn(password,self.client.get('/api/admin/students').text)
        self.assertEqual(self.client.post('/api/admin/students',json=data|{'username':'LEARNER'},headers=self.headers).status_code,409)
        from fastapi.testclient import TestClient
        from main import app
        learner=TestClient(app)
        self.assertEqual(learner.post('/api/auth/login',json={'username':'LEARNER','password':password},headers=self.headers).status_code,200)
        self.assertTrue(learner.get('/api/auth/me').json()['must_change_password'])
        self.assertEqual(learner.get('/api/admin/students').status_code,403)
        self.assertEqual(learner.post('/api/auth/change-password',json={'current_password':password,'new_password':'Own new password!'},headers=self.headers).status_code,200)
        self.assertFalse(learner.get('/api/auth/me').json()['must_change_password'])
        self.assertEqual(self.client.put(f'/api/admin/students/{uid}',json=data|{'default_price_kopecks':200000},headers=self.headers).status_code,200)
        reset=self.client.post(f'/api/admin/students/{uid}/reset-password',json={},headers=self.headers)
        self.assertEqual(reset.status_code,200)
        self.assertEqual(learner.get('/api/auth/me').status_code,401)
        self.assertEqual(self.client.patch(f'/api/admin/students/{uid}/active',json={'is_active':False},headers=self.headers).status_code,200)
        self.assertEqual(learner.post('/api/auth/login',json={'username':'learner','password':reset.json()['temporary_password']},headers=self.headers).status_code,401)
        self.assertEqual(self.client.post('/api/admin/students/'+str(self.id)+'/reset-password',json={},headers={}).status_code,403)
        self.assertEqual(self.client.get('/api/admin/students?limit=500').status_code,422)
        admin_id=self.client.get('/api/auth/me').json()['id']
        self.assertEqual(self.client.patch(f'/api/admin/students/{admin_id}/active',json={'is_active':False},headers=self.headers).status_code,404)
