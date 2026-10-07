import os
from unittest.mock import patch, MagicMock
import smtplib
import tests.test_accounts as support
from admin import temporary_password
from mailer import send_student_credentials


class CredentialsEmailTests(support.AccountTests):
    def test_short_password_and_delivery_authorization(self):
        for _ in range(100):
            password=temporary_password()
            self.assertEqual(len(password),8)
            self.assertFalse(set(password)&set('0O1Il'))
        support.seed_user('Админ','admin','Admin test password!','admin')
        self.post('login',{'username':'admin','password':'Admin test password!'})
        data={'name':'Ученик','username':'mailstudent','email':'student@example.org','default_price_kopecks':0,'default_duration_minutes':60}
        created=self.client.post('/api/admin/students',json=data,headers=self.headers).json()
        path=f"/api/admin/students/{created['id']}/send-credentials"
        payload={'temporary_password':created['temporary_password']}
        with patch('admin.send_student_credentials') as send:
            self.assertEqual(self.client.post(path,json=payload,headers=self.headers).status_code,200)
            send.assert_called_once_with('student@example.org','Ученик','mailstudent',created['temporary_password'])
            self.assertEqual(self.client.post(path,json={'temporary_password':'invalid0'},headers=self.headers).status_code,409)
        with patch('admin.send_student_credentials',side_effect=smtplib.SMTPException('failure')):
            self.assertEqual(self.client.post(path,json=payload,headers=self.headers).status_code,502)
        self.post('login',self.data)
        self.assertEqual(self.client.post(path,json=payload,headers=self.headers).status_code,403)

    def test_message_and_secure_smtp(self):
        env={'SMTP_HOST':'smtp.example.org','SMTP_USER':'sender','SMTP_PASSWORD':'test-only','SMTP_FROM':'sender@example.org','SITE_URL':'https://example.org','SMTP_SECURITY':'ssl','SMTP_PORT':'465'}
        smtp=MagicMock();smtp.__enter__.return_value=smtp;smtp.send_message.return_value={}
        with patch.dict(os.environ,env),patch('mailer.smtplib.SMTP_SSL',return_value=smtp):
            send_student_credentials('student@example.org','Ученик','learner','Ab2Cd3Ef')
            message=smtp.send_message.call_args.args[0]
            self.assertIn('https://example.org/account.html',message.get_content())
            self.assertIn('Ab2Cd3Ef',message.get_content())
            self.assertIn('заменить',message.get_content())
        with patch.dict(os.environ,env|{'SITE_URL':'http://127.0.0.1:8000'}):
            self.assertRaises(ValueError,send_student_credentials,'student@example.org','Ученик','learner','Ab2Cd3Ef')
