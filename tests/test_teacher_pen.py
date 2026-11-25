import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from board import app as module


class TeacherPenTests(unittest.TestCase):
    def test_teacher_width_permissions_and_late_join(self):
        with tempfile.TemporaryDirectory() as folder:
         root=Path(folder);room='a'*48
         (root/room).mkdir()
         (root/room/'scene.json').write_text(json.dumps({'elements':[],'background':'#ffffff','revision':0,'created':1}))
         def auth(connection,room_id,write):
          role=connection.headers.get('x-role','student')
          return {'label':role,'role':role,'can_edit':True}
         app=module.create_app(root,origin='https://testserver',lesson_access=auth)
         with TestClient(app) as client:
          headers={'origin':'https://testserver','x-role':'admin'}
          with client.websocket_connect('/ws/'+room,headers=headers) as teacher:
           assert teacher.receive_json()['role']=='admin'
           teacher.receive_json()
           with client.websocket_connect('/ws/'+room,headers={'origin':'https://testserver'}) as student:
            assert student.receive_json()['teacherPenWidth']==0.25
            student.receive_json();teacher.receive_json()
            teacher.send_json({'type':'teacher_pen','width':0.5})
            assert teacher.receive_json()=={'type':'teacher_pen','width':0.5}
            assert student.receive_json()=={'type':'teacher_pen','width':0.5}
            student.send_json({'type':'teacher_pen','width':4})
            student.send_json({'type':'pointer','x':0,'y':0})
            student.receive_json()
            assert json.loads((root/room/'teacher-pen.json').read_text())['width']==0.5
           with client.websocket_connect('/ws/'+room,headers={'origin':'https://testserver'}) as late:
            assert late.receive_json()['teacherPenWidth']==0.5
