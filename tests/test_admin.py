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

    def test_edit_price_with_legacy_email_login(self):
        support.seed_user('Админ','teacher','Teacher password!','admin')
        self.post('login',{'username':'teacher','password':'Teacher password!'})
        payload={'name':'Ученик','username':self.data['username'],'email':self.data['username'],
                 'phone':'','school_grade':9,'default_price_kopecks':225050,'default_duration_minutes':60}
        url=f'/api/admin/students/{self.id}'
        response=self.client.put(url,json=payload,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        saved=next(s for s in self.client.get('/api/admin/students').json()['items'] if s['id']==self.id)
        self.assertEqual(saved['default_price_kopecks'],225050)
        self.assertEqual(saved['username'],self.data['username'])
        # New accounts still require short logins; preserving a legacy login
        # does not allow assigning arbitrary identifiers to another account.
        self.assertEqual(self.client.post('/api/admin/students',json=payload,headers=self.headers).status_code,422)
        self.assertEqual(self.client.put(url,json=payload|{'username':'invalid@new','default_price_kopecks':1},headers=self.headers).status_code,422)
        saved=next(s for s in self.client.get('/api/admin/students').json()['items'] if s['id']==self.id)
        self.assertEqual(saved['default_price_kopecks'],225050)

    def test_username_suggestions(self):
        self.assertEqual(self.client.get('/api/admin/username-suggestion?name=Иван').status_code,401)
        self.post('login',self.data)
        self.assertEqual(self.client.get('/api/admin/username-suggestion?name=Иван').status_code,403)
        support.seed_user('Админ','teacher','Teacher password!','admin')
        self.post('login',{'username':'teacher','password':'Teacher password!'})
        def suggestion(name):
            result=self.client.get('/api/admin/username-suggestion',params={'name':name})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.headers['cache-control'],'no-store')
            return result.json()['username']
        self.assertEqual(suggestion('Иван'),'ivan')
        self.assertEqual(suggestion('  Анна Смирнова  '),'anna.smirnova')
        support.seed_user('Иван','IVAN','Student password!','student')
        support.seed_user('Иван','ivan2','Student password!','student')
        from accounts import database
        with database() as (cursor,p):cursor.execute("UPDATE users SET is_active=0 WHERE username='ivan2'")
        self.assertEqual(suggestion('Иван'),'ivan3')
        for name in ['李','Я','А'*100,'!!!']:
            login=suggestion(name)
            self.assertGreaterEqual(len(login),3)
            self.assertLessEqual(len(login),40)
            self.assertRegex(login,r'^[a-z0-9.]+$')
