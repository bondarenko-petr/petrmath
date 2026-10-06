import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import main


class TrialRequestTests(unittest.TestCase):
    def test_saved_request_survives_new_connection(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'DB_BACKEND':'sqlite','TRIAL_REQUESTS_DB':str(Path(directory) / 'requests.sqlite3')}):
            client = TestClient(main.app)
            payload = dict(name=' Тест ', email='test@example.com', phone='', message='Профильный уровень', courses=['ЕГЭ'], consent=True)
            self.assertEqual(client.post('/api/trial-requests', json=payload).status_code, 201)
            with sqlite3.connect(Path(directory) / 'requests.sqlite3') as db:
                self.assertEqual(db.execute('SELECT name,courses,consent FROM trial_requests').fetchone(), ('Тест', 'ЕГЭ', 1))
            for invalid in [dict(consent=False), dict(courses=[]), dict(courses=['Python']), dict(name='   '), dict(email='invalid')]:
                self.assertEqual(client.post('/api/trial-requests', json=payload | invalid).status_code, 422)
            with sqlite3.connect(Path(directory) / 'requests.sqlite3') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM trial_requests').fetchone()[0], 1)
            self.assertEqual(client.get('/data/requests.sqlite3').status_code, 404)

    def test_storage_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'file'
            file.write_text('not a directory')
            with patch.dict('os.environ', {'DB_BACKEND':'sqlite','TRIAL_REQUESTS_DB':str(file / 'requests.sqlite3')}):
                response = TestClient(main.app).post('/api/trial-requests', json=dict(name='Тест',email='test@example.com',courses=['ОГЭ'],consent=True))
                self.assertEqual(response.status_code, 503)

    def test_mysql_commit_and_parameterized_insert(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        with patch.dict('os.environ', {'DB_BACKEND':'mysql', 'MYSQL_USER':'test', 'MYSQL_PASSWORD':'test', 'MYSQL_DATABASE':'test'}), patch('database.mysql.connector.connect', return_value=connection):
            payload = dict(name="О'Брайен", email='test@example.com', courses=['ЕГЭ'], consent=True)
            self.assertEqual(TestClient(main.app).post('/api/trial-requests', json=payload).status_code, 201)
            query, values = cursor.execute.call_args.args
            self.assertIn('%s', query)
            self.assertNotIn(payload['name'], query)
            self.assertEqual(values[0], payload['name'])
            connection.commit.assert_called_once()

    def test_mysql_unavailable_returns_503(self):
        import mysql.connector
        with patch.dict('os.environ', {'DB_BACKEND':'mysql', 'MYSQL_USER':'test', 'MYSQL_PASSWORD':'test', 'MYSQL_DATABASE':'test'}), patch('database.mysql.connector.connect', side_effect=mysql.connector.Error('unavailable')):
            response = TestClient(main.app).post('/api/trial-requests', json=dict(name='Тест',email='test@example.com',courses=['ОГЭ'],consent=True))
            self.assertEqual(response.status_code, 503)
