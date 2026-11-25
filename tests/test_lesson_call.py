import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts import database
from tests import test_lessons as lesson_tests
from tests.test_accounts import seed_user


class LessonCallTests(unittest.TestCase):
    setUp = lesson_tests.LessonTests.setUp
    tearDown = lesson_tests.LessonTests.tearDown
    post = lesson_tests.LessonTests.post
    create = lesson_tests.LessonTests.create

    def test_automatic_call_shared_room_and_closed_lesson(self):
        with tempfile.TemporaryDirectory() as folder,                 patch('lesson_board.board_enabled', return_value=True),                 patch('lesson_board.board_data', return_value=Path(folder)),                 patch('lesson_call.settings', return_value=('wss://video.example', 'key', 'x'*32)),                 patch('lesson_call.room_service') as service:
            lesson_id = self.create().json()['ids'][0]
            path = '/api/lessons/' + str(lesson_id)
            self.assertFalse(self.client.get(path+'/call').json()['enabled'])
            with database() as (c,p):
                c.execute('UPDATE lessons SET starts_at=?,ends_at=? WHERE id=?',
                          (int(time.time())-60,int(time.time())+3000,lesson_id))
            self.assertTrue(self.client.get(path+'/call').json()['enabled'])
            self.assertEqual(self.client.post(path+'/board',headers=self.headers).status_code,200)
            teacher = self.client.post(path+'/call/token', headers=self.headers)
            self.assertEqual(teacher.status_code,200,teacher.text)
            self.post('logout',{})
            self.post('login',self.data)
            student = self.client.post(path+'/call/token',headers=self.headers)
            self.assertEqual(student.status_code,200,student.text)
            def claims(response):
                encoded = response.json()['token'].split('.')[1]
                return json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
            self.assertEqual(claims(teacher)['video']['room'],claims(student)['video']['room'])
            self.assertEqual(service.call_count,2)
            with database() as (c,p):
                c.execute("UPDATE lessons SET status='completed' WHERE id=?",(lesson_id,))
            self.assertFalse(self.client.get(path+'/call').json()['enabled'])
            self.assertEqual(self.client.post(path+'/call/token',headers=self.headers).status_code,403)

    def test_other_student_cannot_join(self):
        with tempfile.TemporaryDirectory() as folder,                 patch('lesson_board.board_enabled', return_value=True),                 patch('lesson_board.board_data', return_value=Path(folder)),                 patch('lesson_call.settings', return_value=('wss://video.example','key','x'*32)),                 patch('lesson_call.room_service') as service:
            lesson_id=self.create().json()['ids'][0]
            with database() as (c,p):
                c.execute('UPDATE lessons SET starts_at=? WHERE id=?',(int(time.time())-60,lesson_id))
            seed_user('Другой','outsider','Outsider password 2026!')
            self.post('logout',{})
            self.post('login',{'username':'outsider','password':'Outsider password 2026!'})
            path='/api/lessons/'+str(lesson_id)
            self.assertEqual(self.client.get(path+'/call').status_code,404)
            self.assertEqual(self.client.post(path+'/call/token',headers=self.headers).status_code,404)
            service.assert_not_called()
