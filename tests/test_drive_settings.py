import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch,MagicMock
import unittest
from tests.test_accounts import AccountTests,seed_user
import drive_settings as drive


def answer(data=None,content=b'',ok=True):return SimpleNamespace(is_success=ok,json=lambda:data,content=content)

class DriveSettingsTests(unittest.TestCase):
    def setUp(self):
        AccountTests.setUp(self)
        self.post=AccountTests.post.__get__(self)
        seed_user('Admin','teacher','Teacher password 123!','admin')
        self.post('login',{'username':'teacher','password':'Teacher password 123!'})
        self.directory=Path(self.temp.name)/'drive'
        self.config=patch.dict(os.environ,{'GOOGLE_DRIVE_PRIVATE_DIR':str(self.directory),'GOOGLE_DRIVE_CLIENT_ID':'client-id','GOOGLE_DRIVE_CLIENT_SECRET':'secret-client','GOOGLE_DRIVE_REDIRECT_URI':'http://127.0.0.1:8000/api/admin/archive-settings/callback'})
        self.config.start();self.base='/api/admin/archive-settings'
    def tearDown(self):self.config.stop();AccountTests.tearDown(self)
    def connect(self):
        result=self.client.post(self.base+'/connect',headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        params=parse_qs(urlsplit(result.json()['url']).query)
        self.assertEqual(params['scope'],[drive.SCOPE]);self.assertIn('code_challenge',params)
        return params['state'][0]
    def fake_google(self):
        client=MagicMock();client.__enter__.return_value=client
        client.post.side_effect=[answer({'refresh_token':'secret-refresh','access_token':'secret-access','scope':drive.SCOPE}),answer({'id':'folder-id','name':'Архивы'})]
        client.get.side_effect=[answer({'user':{'emailAddress':'owner@example.com'}}),answer({'files':[]})]
        return client
    def test_auth_and_config_validation(self):
        self.post('login',self.data)
        self.assertEqual(self.client.get(self.base).status_code,403)
        self.post('login',{'username':'teacher','password':'Teacher password 123!'})
        self.assertEqual(self.client.post(self.base+'/connect').status_code,403)
        with patch.dict(os.environ,{'GOOGLE_DRIVE_CLIENT_SECRET':''}):
            self.assertFalse(self.client.get(self.base).json()['configured'])
            self.assertEqual(self.client.post(self.base+'/connect',headers=self.headers).status_code,503)
    def test_retention_no_automatic_or_delete_switches(self):
        r=self.client.put(self.base,json={'retention_days':35,'grace_days':21},headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['retention_days'],35)
        self.assertFalse(r.json()['deletion_enabled']);self.assertEqual(r.json()['mode'],'manual')
        self.assertEqual(self.client.put(self.base,json={'retention_days':0,'grace_days':14},headers=self.headers).status_code,422)
        self.assertEqual(self.client.put(self.base,json={'retention_days':28,'grace_days':14,'deletion_enabled':True},headers=self.headers).status_code,422)
    def test_callback_private_storage_and_replay(self):
        state=self.connect();client=self.fake_google()
        with patch('drive_settings.httpx.Client',return_value=client):
            r=self.client.get(self.base+'/callback',params={'state':state,'code':'secret-code'},follow_redirects=False)
        self.assertIn('connected',r.headers['location'])
        status=self.client.get(self.base);self.assertTrue(status.json()['connected'])
        for secret in ['secret-refresh','secret-access','secret-client','secret-code']:self.assertNotIn(secret,status.text)
        path=self.directory/'settings.json';self.assertEqual(path.stat().st_mode&0o777,0o600)
        replay=self.client.get(self.base+'/callback',params={'state':state,'code':'again'},follow_redirects=False)
        self.assertIn('invalid',replay.headers['location'])
        self.assertEqual(client.post.call_count,2)
    def test_invalid_session_and_expired_state(self):
        state=self.connect();self.post('logout',{});self.post('login',{'username':'teacher','password':'Teacher password 123!'})
        with patch('drive_settings.httpx.Client') as client:
            result=self.client.get(self.base+'/callback',params={'state':state,'code':'code'},follow_redirects=False)
            self.assertIn('invalid',result.headers['location']);client.assert_not_called()
        state=self.connect()
        with drive.storage() as data:
            for pending in data['oauth'].values():pending['expires']=0
        result=self.client.get(self.base+'/callback',params={'state':state,'code':'code'},follow_redirects=False)
        self.assertIn('invalid',result.headers['location'])
    def seed_connection(self):
        with drive.storage() as data:data['connection']={'refresh_token':'secret-refresh','folder_id':'folder-id','folder_name':'Архивы'}
    def test_round_trip_and_cleanup(self):
        self.seed_connection();client=MagicMock();client.__enter__.return_value=client
        client.post.side_effect=[answer({'access_token':'access'}),answer({'id':'test-file'})]
        def get(url,**kwargs):
            if kwargs.get('params',{}).get('alt')=='media':
                upload=client.post.call_args.kwargs['content'];return answer(content=upload.split(b'Content-Type: text/plain\r\n\r\n')[1].split(b'\r\n--')[0])
            return answer({'id':'folder-id','mimeType':'application/vnd.google-apps.folder','trashed':False})
        client.get.side_effect=get;client.delete.return_value=answer()
        with patch('drive_settings.httpx.Client',return_value=client):
            r=self.client.post(self.base+'/test',headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);client.delete.assert_called_once();self.assertIn('Проверка пройдена',r.json()['events'][0]['message'])
    def test_bad_checksum_still_deletes_test_file(self):
        self.seed_connection();client=MagicMock();client.__enter__.return_value=client
        client.post.side_effect=[answer({'access_token':'access'}),answer({'id':'test-file'})]
        client.get.side_effect=[answer({'mimeType':'application/vnd.google-apps.folder'}),answer(content=b'corrupt')]
        client.delete.return_value=answer()
        with patch('drive_settings.httpx.Client',return_value=client):r=self.client.post(self.base+'/test',headers=self.headers)
        self.assertEqual(r.status_code,502);client.delete.assert_called_once()
        self.assertIn('Проверка не пройдена',self.client.get(self.base).json()['events'][0]['message'])
    def test_disconnect_keeps_drive_files(self):
        self.seed_connection()
        with patch('drive_settings.httpx.Client') as client:
            self.assertEqual(self.client.post(self.base+'/disconnect',headers=self.headers).status_code,200);client.assert_not_called()
        self.assertFalse(self.client.get(self.base).json()['connected']);self.assertNotIn('secret-refresh',(self.directory/'settings.json').read_text())
