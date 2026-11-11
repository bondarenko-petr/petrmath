import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from accounts import database, router as auth_router, hash_password
from materials import router as materials_router
from lessons import router as lessons_router
from lesson_board import mount_board
from board.app import atomic
from board_lifecycle import preserve, read_state, write_state, mark_completed, sweep, RETENTION, valid_pdf

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  import accounts
  accounts.attempts.clear()
  self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
  self.env=patch.dict(os.environ,{'DB_BACKEND':'sqlite','TRIAL_REQUESTS_DB':str(self.folder/'db'),'LESSON_BOARD_ENABLED':'true','LESSON_BOARD_DATA_DIR':str(self.folder/'boards'),'MATERIALS_DIR':str(self.folder/'materials'),'LESSON_BOARD_ORIGIN':'http://testserver','COOKIE_SECURE':'false'});self.env.start()
  with database() as (c,p):
   for name,role in [('teacher','admin'),('student','student'),('other','student')]:
    c.execute('INSERT INTO users(name,username,role,password_hash) VALUES(?,?,?,?)',(name,name,role,hash_password('valid-test-password')))
   now=int(time.time());c.execute("INSERT INTO lessons(student_id,starts_at,ends_at,duration_minutes,price_kopecks,timezone,status,created_at) VALUES(2,?,?,60,0,'Europe/Berlin','scheduled',?)",(now+1801,now+5401,now))
  app=FastAPI();app.include_router(auth_router);app.include_router(lessons_router);app.include_router(materials_router);mount_board(app);self.app=app
  self.clients=[TestClient(app) for _ in range(3)];self.headers={'X-Requested-With':'KrugPi'}
  for client,name in zip(self.clients,['teacher','student','other']):
   self.assertEqual(client.post('/api/auth/login',json={'username':name,'password':'valid-test-password'},headers=self.headers).status_code,200)
  self.teacher,self.student,self.other=self.clients
 def tearDown(self):self.env.stop();self.temp.cleanup()
 def open(self):
  with database() as(c,p):c.execute('UPDATE lessons SET starts_at=? WHERE id=1',(int(time.time())+1200,))
  result=self.student.post('/api/lessons/1/board',headers=self.headers);self.assertEqual(result.status_code,200,result.text)
  self.root=result.json()['url'].split('/')[-1];self.store=self.app.state.lesson_board_store
  return self.root
 def complete(self):
  with database() as(c,p):c.execute("UPDATE lessons SET starts_at=?,ends_at=?,status='completed' WHERE id=1",(int(time.time())-4000,int(time.time())-10))
  mark_completed(1)
 async def pdf(self,sheets):return b'%PDF-1.7\n'+str(len(sheets)).encode()
 def test_pdf_import_is_atomic_and_retries_do_not_duplicate_pages(self):
  room = self.open()
  base = f'/board/api/rooms/{room}'
  headers = {'X-Requested-With': 'Prosto5Board', 'Origin': 'http://testserver'}

  def page(number):
   return {
    'element': {'id': f'page-{number}', 'type': 'image', 'fileId': f'file-{number}',
                'version': 1, 'versionNonce': 1, 'x': 0, 'y': number * 100, 'width': 60, 'height': 80},
    'file': {'id': f'file-{number}', 'mimeType': 'image/jpeg', 'dataURL': 'data:image/jpeg;base64,/9j/AA=='},
   }

  def submit(destination, pages):
   return self.teacher.post(base + '/pdf-import', headers=headers, json={'destination': destination, 'pages': pages})

  broken = page(2)
  broken['file']['dataURL'] = 'invalid'
  self.assertEqual(submit('current', [page(1), broken]).status_code, 422)
  self.assertEqual(self.teacher.get(base + '/snapshot').json()['elements'], [])
  with patch('board.app.MAX_SHEETS', 2):
   self.assertEqual(submit('sheets', [page(1), page(2)]).status_code, 409)
  self.assertEqual(self.teacher.get(base + '/sheets').json()['sheets'], [room])

  def fail_commit(path, value):
   if path.name in ('scene.json', 'sheets.json'):
    raise OSError('test write failure')
   atomic(path, value)

  with patch('board.app.atomic', side_effect=fail_commit):
   self.assertEqual(submit('current', [page(1), page(2)]).status_code, 503)
   self.assertEqual(submit('sheets', [page(3), page(4)]).status_code, 503)
  self.assertEqual(self.teacher.get(base + '/snapshot').json()['elements'], [])
  self.assertEqual(self.teacher.get(base + '/sheets').json()['sheets'], [room])
  self.assertEqual(list((self.store.path / room / 'files').glob('*.json')), [])

  current = submit('current', [page(1), page(2)])
  self.assertEqual(current.status_code, 201, current.text)
  self.assertEqual(submit('current', [page(1), page(2)]).status_code, 201)
  self.assertEqual(len(self.teacher.get(base + '/snapshot').json()['elements']), 2)
  separate = submit('sheets', [page(3), page(4)])
  self.assertEqual(separate.status_code, 201, separate.text)
  ids = separate.json()['sheets']
  self.assertEqual(submit('sheets', [page(3), page(4)]).json()['sheets'], ids)
  self.assertEqual(self.teacher.get(base + '/sheets').json()['sheets'], [room, *ids])
  for sheet, number in zip(ids, (3, 4)):
   path = f'/board/api/rooms/{sheet}'
   self.assertEqual(self.student.get(path + '/snapshot').json()['elements'][0]['id'], f'page-{number}')
   self.assertEqual(self.student.get(path + f'/files/file-{number}').status_code, 200)
  self.complete()
  denied = self.student.post(base + '/pdf-import', headers=headers, json={'destination': 'current', 'pages': [page(5)]})
  self.assertEqual(denied.status_code, 403)

 def test_time_boundary_and_ownership(self):
  with patch('lesson_board.time.time',return_value=time.time()-5):
   self.assertEqual(self.student.post('/api/lessons/1/board',headers=self.headers).status_code,403)
  self.open();self.assertEqual(self.other.post('/api/lessons/1/board',headers=self.headers).status_code,404)
  self.assertEqual(self.teacher.post('/api/lessons/1/board',headers=self.headers).json()['url'],'/board/room/'+self.root)
 def test_export_all_sheets_then_delete_and_no_recreation(self):
  self.open();self.complete();child='a'*48
  atomic(self.store.path/child/'scene.json',{'elements':[],'background':'#fff','revision':0,'lesson':self.root})
  atomic(self.store.path/self.root/'sheets.json',[self.root,child])
  (self.store.path/child/'files').mkdir();(self.store.path/child/'files'/'unused.json').write_text('{}')
  state=asyncio.run(preserve(self.store,self.root,1,renderer=self.pdf));self.assertTrue(valid_pdf(state,1))
  self.assertEqual((self.folder/'materials'/(state['pdf_id']+'.pdf')).read_bytes(),b'%PDF-1.7\n2')
  asyncio.run(preserve(self.store,self.root,1,delete=True,renderer=self.pdf))
  self.assertFalse((self.store.path/self.root).exists());self.assertFalse((self.store.path/child).exists())
  self.assertEqual(self.student.post('/api/lessons/1/board',headers=self.headers).status_code,410)
  self.assertTrue(self.student.get('/api/lessons/1/board-status').json()['deleted_at'])
  self.assertEqual(self.student.get('/api/materials/files/'+state['pdf_id']).status_code,200)
 def test_export_failure_keeps_board_and_worker_records_error(self):
  self.open();self.complete();state=read_state(self.root);state['completed_at']=int(time.time())-RETENTION-1;write_state(self.root,state)
  async def fail(sheets):raise RuntimeError('test renderer failure')
  async def failed_preserve(*args,**kwargs):return await preserve(*args,**kwargs,renderer=fail)
  with patch('board_lifecycle.preserve',side_effect=failed_preserve):
   asyncio.run(sweep(self.store))
  self.assertTrue((self.store.path/self.root/'scene.json').exists());self.assertIn('failure',read_state(self.root)['error']);self.assertFalse(self.store.frozen)
  self.assertEqual(len(self.teacher.get('/api/lessons/board-cleanup-status').json()['errors']),1)
 def test_stale_or_missing_pdf_regenerated(self):
  self.open();self.complete();first=asyncio.run(preserve(self.store,self.root,1,renderer=self.pdf))
  same=asyncio.run(preserve(self.store,self.root,1,renderer=self.pdf));self.assertEqual(first['pdf_id'],same['pdf_id'])
  self.store.room(self.root).scene['background']='#000000'
  new=asyncio.run(preserve(self.store,self.root,1,renderer=self.pdf));self.assertNotEqual(first['pdf_id'],new['pdf_id'])
  (self.folder/'materials'/(new['pdf_id']+'.pdf')).unlink()
  newer=asyncio.run(preserve(self.store,self.root,1,renderer=self.pdf));self.assertNotEqual(new['pdf_id'],newer['pdf_id'])
 def test_legacy_grace_and_completion_not_reset(self):
  self.open();self.complete();first=read_state(self.root)['completed_at'];mark_completed(1);self.assertEqual(first,read_state(self.root)['completed_at'])
  (self.store.path/'.lifecycle'/(self.root+'.json')).unlink();asyncio.run(sweep(self.store))
  self.assertGreaterEqual(read_state(self.root)['completed_at'],first);self.assertTrue((self.store.path/self.root).exists())
 def test_no_space_for_pdf_preserves_board(self):
  self.open();self.complete()
  from board_lifecycle import attach_pdf
  for i in range(5):attach_pdf(1,b'%PDF-1.7\n'+str(i).encode())
  with self.assertRaises(ValueError):asyncio.run(preserve(self.store,self.root,1,delete=True,renderer=self.pdf))
  self.assertTrue((self.store.path/self.root/'scene.json').exists());self.assertFalse(read_state(self.root).get('deleted_at'))

 def test_mutations_blocked_during_export_and_unlock_after_failure(self):
  self.open();self.complete()
  async def renderer(sheets):
   response=self.teacher.post('/board/api/rooms/'+self.root+'/clear?generation=0',headers={'X-Requested-With':'Prosto5Board','Origin':'http://testserver'})
   self.assertEqual(response.status_code,409)
   raise RuntimeError('interrupted renderer')
  with self.assertRaises(RuntimeError):asyncio.run(preserve(self.store,self.root,1,renderer=renderer))
  self.assertFalse(self.store.frozen)
  response=self.teacher.post('/board/api/rooms/'+self.root+'/clear?generation=0',headers={'X-Requested-With':'Prosto5Board','Origin':'http://testserver'})
  self.assertEqual(response.status_code,200,response.text)
 def test_partial_delete_keeps_tombstone_and_retries(self):
  self.open();self.complete()
  with patch('board_lifecycle.shutil.rmtree',side_effect=OSError('test deletion failure')):
   with self.assertRaises(OSError):asyncio.run(preserve(self.store,self.root,1,delete=True,renderer=self.pdf))
  self.assertTrue(read_state(self.root)['deleted_at']);self.assertTrue(read_state(self.root)['pending_delete'])
  self.assertEqual(self.student.post('/api/lessons/1/board',headers=self.headers).status_code,410)
  asyncio.run(sweep(self.store))
  self.assertFalse((self.store.path/self.root).exists());self.assertFalse(read_state(self.root).get('pending_delete'))

 def test_completion_endpoint_starts_retention_and_due_worker_cleans(self):
  self.open()
  with database() as(c,p):c.execute('UPDATE lessons SET starts_at=?,ends_at=? WHERE id=1',(int(time.time())-4000,int(time.time())-1))
  response=self.teacher.patch('/api/lessons/1/status',json={'status':'completed','scope':'one'},headers=self.headers)
  self.assertEqual(response.status_code,200,response.text)
  self.assertTrue(read_state(self.root)['completed_at'])
  calls=[]
  async def rendered(sheets):calls.append(len(sheets));return b'%PDF-1.7\nTest all sheets'
  async def real_preserve(*args,**kwargs):return await preserve(*args,**kwargs,renderer=rendered)
  with patch('board_lifecycle.preserve',side_effect=real_preserve):
   asyncio.run(sweep(self.store));self.assertFalse(calls)
   state=read_state(self.root);state['completed_at']-=RETENTION+1;write_state(self.root,state)
   asyncio.run(sweep(self.store))
  self.assertEqual(calls,[1]);self.assertTrue(read_state(self.root)['deleted_at'])
  self.assertFalse((self.store.path/self.root).exists())

if __name__=='__main__':unittest.main()
