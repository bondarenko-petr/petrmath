"""Isolated pilot: Excalidraw scenes and images stay on this host. One worker only."""
import asyncio
import base64
from collections import defaultdict,deque
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import time
from fastapi import FastAPI,Request,HTTPException,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles

ID=re.compile(r'^[0-9a-f]{48}$')
KEY=re.compile(r'^[A-Za-z0-9_-]{1,128}$')
TYPES={'rectangle','diamond','ellipse','line','arrow','freedraw','text','image','frame','magicframe'}
MAX_ELEMENTS=3000
MAX_SHEETS=30
MAX_SCENE=4*1024*1024
MAX_IMAGE=5*1024*1024
MAX_FILES_BYTES=40*1024*1024
MAX_FRAME=1024*1024
MESSAGES_PER_SECOND = 40
MESSAGE_BURST = 120
LOG=logging.getLogger('uvicorn.error')
BUILD='pilot-eraser-protection-1'


def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.parent/('.'+secrets.token_hex(8)+'.tmp')
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(encode(value));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


class SheetCapacityError(ValueError):
    pass


def sheet_usage(scene, path):
    # The scene file includes metadata, so this is slightly conservative.
    return min(100, int(max(
        len(scene['elements']) / MAX_ELEMENTS,
        path.stat().st_size / MAX_SCENE,
    ) * 100))


def elements(value):
    if not isinstance(value,list):raise ValueError('Некорректный список объектов.')
    if len(value)>MAX_ELEMENTS:raise SheetCapacityError('На листе достигнут лимит объектов.')
    ids=set()
    for item in value:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not KEY.fullmatch(item['id']) or item['id'] in ids:raise ValueError('Некорректные объекты доски.')
        ids.add(item['id'])
        if item.get('type') not in TYPES:raise ValueError('В тестовой доске внешние встраивания не поддерживаются.')
        for field in ('version','versionNonce'):
            if type(item.get(field)) is not int or not 0<=item[field]<=2**53-1:raise ValueError('Некорректная версия объекта.')
        for field in ('x','y','width','height'):
            number=item.get(field)
            if type(number) not in (float,int) or not math.isfinite(number) or abs(number)>10**7:raise ValueError('Некорректные размеры объекта.')
        if item['type']=='image' and item.get('fileId') is not None and (not isinstance(item['fileId'],str) or not KEY.fullmatch(item['fileId'])):raise ValueError('Некорректное изображение.')
    if len(encode(value).encode())>MAX_SCENE:raise SheetCapacityError('На листе достигнут лимит объёма данных.')
    return value


def merge(current,incoming):
    merged={element['id']:element for element in current};changed=[]
    for element in incoming:
        old=merged.get(element['id'])
        # Same rule as Excalidraw: greater version wins; lower nonce wins a tie.
        if old is None or element['version']>old['version'] or (element['version']==old['version'] and element['versionNonce']<old['versionNonce']):
            merged[element['id']]=element;changed.append(element)
    result=list(merged.values())
    if all(isinstance(item.get('index'),str) for item in result):result.sort(key=lambda item:(item['index'],item['id']))
    elements(result)
    return result,changed


def image(value):
    if not isinstance(value,dict) or not isinstance(value.get('id'),str) or not KEY.fullmatch(value['id']):raise ValueError('Некорректный файл.')
    mime=value.get('mimeType');data=value.get('dataURL','')
    if mime not in ('image/png','image/jpeg','image/webp','image/gif') or not isinstance(data,str) or not data.startswith('data:'+mime+';base64,'):raise ValueError('Для теста поддерживаются PNG, JPG, WEBP и GIF. SVG пока не поддерживается.')
    try:raw=base64.b64decode(data.split(',',1)[1],validate=True)
    except Exception:raise ValueError('Не удалось прочитать изображение.')
    valid={'image/png':raw.startswith(b'\x89PNG\r\n\x1a\n'),'image/jpeg':raw.startswith(b'\xff\xd8\xff'),'image/webp':raw[:4]==b'RIFF' and raw[8:12]==b'WEBP','image/gif':raw[:6] in (b'GIF87a',b'GIF89a')}[mime]
    if not valid or not 0<len(raw)<=MAX_IMAGE:raise ValueError('Картинка повреждена или превышает 5 МБ.')
    return {'id':value['id'],'mimeType':mime,'dataURL':data,'created':int(time.time()*1000)},len(raw)

class Room:
    def __init__(self,path,scene):
        self.path=path;self.scene=scene;self.lock=asyncio.Lock();self.peers={}
    async def broadcast(self,message):
        # Do not let a disconnected/slow tab hold everybody else's drawing.
        peers=list(self.peers.values())
        async def send(peer):
            try:await asyncio.wait_for(peer.send_text(encode(message)),2)
            except Exception as error:
                LOG.warning('board_ws_send_failed room=%s error=%s peers=%s',hashlib.sha256(str(self.path).encode()).hexdigest()[:12],type(error).__name__,len(self.peers))
                try:await peer.close(code=1013,reason='send_timeout_or_failure')
                except Exception:pass
        await asyncio.gather(*(send(peer) for peer in peers))

class Store:
    def __init__(self,path):self.path=path;path.mkdir(parents=True,exist_ok=True,mode=0o700);self.rooms={};self.creation_lock=asyncio.Lock()
    def room(self,room_id):
        if not ID.fullmatch(room_id):raise HTTPException(404,'Доска не найдена')
        if room_id not in self.rooms:
            file=self.path/room_id/'scene.json'
            if not file.is_file():raise HTTPException(404,'Доска не найдена')
            try:
                scene=json.loads(file.read_text());elements(scene['elements'])
            except Exception:raise HTTPException(503,'Не удалось прочитать доску. Исходные данные сохранены; обратитесь к преподавателю.')
            self.rooms[room_id]=Room(file.parent,scene)
        return self.rooms[room_id]


def create_app(data_dir=None,origin=None,static_dir=None,trusted_proxy='127.0.0.1',lesson_access=None):
    data=Path(data_dir or os.getenv('BOARD_DATA_DIR','./board-data')).resolve()
    allowed=origin or os.environ.get('BOARD_ORIGIN','https://board.prosto5.ru')
    static=Path(static_dir or os.environ.get('BOARD_STATIC_DIR',str(Path(__file__).resolve().parent/'frontend'/'dist')))
    store=Store(data);rates=defaultdict(deque)
    @asynccontextmanager
    async def lifespan(app):
        yield
        for room in store.rooms.values():
            for socket in list(room.peers.values()):
                try:await socket.close(code=1001)
                except Exception:pass
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    async def auth(connection, room_id=None, *, write=False):
        if lesson_access is not None:
            root_id = None
            if room_id is not None:
                room = store.room(room_id)
                root_id = room.scene.get('lesson', room_id)
            return await asyncio.to_thread(lesson_access, connection, root_id, write)
        user=connection.headers.get('x-board-user','')
        if not connection.client or connection.client.host!=trusted_proxy or not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,80}',user):raise HTTPException(401,'Откройте доску по защищённому адресу и введите тестовый логин и пароль.')
        return user
    def origin_check(connection,required=False):
        value=connection.headers.get('origin')
        if value!=allowed and (value is not None or required):raise HTTPException(403,'Недопустимый источник запроса')
    def limit(user,action,count,seconds):
        key = user['rate_key'] if isinstance(user, dict) else user
        values=rates[(key,action)];now=time.monotonic()
        while values and values[0]<now-seconds:values.popleft()
        if len(values)>=count:raise HTTPException(429,'Слишком много запросов. Подождите немного.')
        values.append(now)
    @app.middleware('http')
    async def headers(request,call_next):
        response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
        if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        return response
    @app.get('/healthz')
    def health():return {'status':'ok','editor_ready':(static/'index.html').is_file(),'build':BUILD}
    @app.post('/api/connection-diagnostics')
    async def connection_diagnostics(request: Request):
        user = await auth(request)
        origin_check(request)
        if request.headers.get('x-requested-with') != 'Prosto5Board':
            raise HTTPException(403, 'Недопустимый запрос')
        limit(user, 'connection-diagnostics', 12, 60)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, 'Отчёт слишком большой')
        try:
            events = json.loads(body)
        except (ValueError, UnicodeError):
            raise HTTPException(422, 'Некорректный отчёт')
        if not isinstance(events, list) or not 1 <= len(events) <= 20:
            raise HTTPException(422, 'Некорректный список событий')
        required = {'id', 'at', 'code', 'online'}
        optional = {'connection', 'pendingUpdates', 'oldestPendingMs'}
        for event in events:
            if (not isinstance(event, dict) or not required <= event.keys() <= required | optional
                    or not isinstance(event['id'], str) or not re.fullmatch(r'[a-f0-9-]{36}', event['id'])
                    or type(event['at']) is not int or not 0 <= event['at'] < 10**13
                    or type(event['code']) is not int or not 1000 <= event['code'] <= 4999
                    or type(event['online']) is not bool):
                raise HTTPException(422, 'Некорректное событие')
            connection = event.get('connection')
            if connection is not None and (not isinstance(connection, str) or not re.fullmatch(r'[a-f0-9]{16}', connection)):
                raise HTTPException(422, 'Некорректный идентификатор соединения')
            for key in ('pendingUpdates', 'oldestPendingMs'):
                value = event.get(key)
                if value is not None and (type(value) is not int or not 0 <= value <= 10**10):
                    raise HTTPException(422, 'Некорректные показатели соединения')
        for event in events:
            LOG.info(
                'board_browser_disconnect event=%s connection=%s client_ms=%s code=%s browser_online=%s pending=%s oldest_pending_ms=%s',
                event['id'], event.get('connection'), event['at'], event['code'], event['online'],
                event.get('pendingUpdates'), event.get('oldestPendingMs'),
            )
        return {'ok': True}
    @app.post('/api/rooms',status_code=201)
    async def new_room(request:Request):
        if lesson_access is not None:
            raise HTTPException(404, 'Откройте доску из карточки занятия')
        user=await auth(request);origin_check(request)
        if request.headers.get('x-requested-with')!='Prosto5Board':raise HTTPException(403,'Недопустимый запрос')
        limit(user,'create',10,3600)
        async with store.creation_lock:
            if sum(not room_file.with_name('sheet').exists() for room_file in data.glob('*/scene.json'))>=20:raise HTTPException(409,'В тестовом режиме доступно 20 досок. Обратитесь к преподавателю.')
            room_id=secrets.token_hex(24);scene={'elements':[],'background':'#ffffff','revision':0,'created':int(time.time())}
            await asyncio.to_thread(atomic,data/room_id/'scene.json',scene)
            return {'id':room_id,'url':'/room/'+room_id}
    def lesson_sheets(room_id):
        room = store.room(room_id)
        root_id = room.scene.get('lesson', room_id)
        path = data / root_id / 'sheets.json'
        try:
            return root_id, json.loads(path.read_text())
        except FileNotFoundError:
            return root_id, [root_id]

    @app.get('/api/rooms/{room_id}/sheets')
    async def list_sheets(room_id: str, request: Request):
        await auth(request, room_id)
        _, sheets = lesson_sheets(room_id)
        return {'sheets': sheets}

    @app.post('/api/rooms/{room_id}/sheets', status_code=201)
    async def new_sheet(room_id: str, request: Request):
        user = await auth(request, room_id, write=True)
        origin_check(request)
        if request.headers.get('x-requested-with') != 'Prosto5Board':
            raise HTTPException(403, 'Недопустимый запрос')
        limit(user, 'sheet', 10, 60)
        async with store.creation_lock:
            root_id, sheets = lesson_sheets(room_id)
            if len(sheets) >= MAX_SHEETS:
                raise HTTPException(409, 'Достигнут предел в 30 листов на урок.')
            sheet_id = secrets.token_hex(24)
            scene = {'elements': [], 'background': '#ffffff', 'revision': 0,
                     'created': int(time.time()), 'lesson': root_id}
            sheet_path = data / sheet_id / 'scene.json'
            await asyncio.to_thread(atomic, sheet_path.with_name('sheet'), True)
            await asyncio.to_thread(atomic, sheet_path, scene)
            try:
                await asyncio.to_thread(atomic, data / root_id / 'sheets.json', [*sheets, sheet_id])
            except OSError:
                sheet_path.unlink(missing_ok=True)
                raise
            await asyncio.gather(*(store.rooms[sheet].broadcast({'type': 'sheets', 'sheets': [*sheets, sheet_id]})
                                   for sheet in sheets if sheet in store.rooms))
        return {'id': sheet_id}

    @app.get('/api/rooms/{room_id}/snapshot')
    async def sheet_snapshot(room_id: str, request: Request):
        await auth(request, room_id)
        if not ID.fullmatch(room_id):
            raise HTTPException(404, 'Лист не найден')
        room = store.rooms.get(room_id)
        if room is None:
            try:
                scene = await asyncio.to_thread(lambda: json.loads((data / room_id / 'scene.json').read_text()))
            except FileNotFoundError:
                raise HTTPException(404, 'Лист не найден')
        else:
            scene = room.scene
        items = [element for element in scene['elements'] if not element.get('isDeleted')]
        file_ids = sorted({element['fileId'] for element in items
                           if element['type'] == 'image' and element.get('fileId')})
        return {'elements': items, 'background': scene['background'], 'fileIds': file_ids}

    @app.post('/api/rooms/{room_id}/clear')
    async def clear_sheet(room_id: str, request: Request, generation: int):
        user = await auth(request, room_id, write=True)
        origin_check(request)
        if request.headers.get('x-requested-with') != 'Prosto5Board':
            raise HTTPException(403, 'Недопустимый запрос')
        limit(user, 'clear-sheet', 10, 60)
        room = store.room(room_id)
        async with room.lock:
            if generation != room.scene.get('generation', 0):
                raise HTTPException(409, 'Лист уже обновился. Проверьте содержимое перед очисткой.')
            scene = {
                **room.scene, 'elements': [], 'generation': generation + 1,
                'revision': room.scene['revision'] + 1,
            }
            await asyncio.to_thread(atomic, room.path / 'scene.json', scene)
            room.scene = scene
            for file in (room.path / 'files').glob('*.json'):
                try:
                    file.unlink()
                except OSError:
                    LOG.warning('board_clear_file_cleanup_failed', exc_info=True)
            await room.broadcast({
                'type': 'scene', **scene, 'reset': True, 'usage': 0, 'fileIds': [],
            })
        return {'generation': scene['generation']}

    @app.post('/api/rooms/{room_id}/files')
    async def upload(room_id:str,request:Request,generation:int=0):
        user=await auth(request, room_id, write=True);origin_check(request)
        if request.headers.get('x-requested-with')!='Prosto5Board':raise HTTPException(403,'Недопустимый запрос')
        limit(user,'upload',30,60);body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>7*1024*1024:raise HTTPException(413,'Картинка слишком большая. Предел — 5 МБ.')
        try:file,size=image(json.loads(body))
        except (ValueError,TypeError) as error:raise HTTPException(422,str(error))
        room = store.room(room_id)
        async with room.lock:
            if generation != room.scene.get('generation', 0):
                raise HTTPException(409, 'Лист был очищен. Загрузите файл заново.')
            target=room.path/'files'/(file['id']+'.json')
            if target.exists():
                old=json.loads(target.read_text())
                if old['dataURL']!=file['dataURL']:raise HTTPException(409,'Идентификатор картинки уже используется.')
            else:
                if sum(f.stat().st_size for f in (room.path/'files').glob('*.json'))+len(encode(file).encode())>MAX_FILES_BYTES:raise HTTPException(413,'Лимит картинок на пробной доске достигнут. Создайте новую доску.')
                await asyncio.to_thread(atomic,target,file)
        return {'id':file['id']}
    @app.get('/api/rooms/{room_id}/files/{file_id}')
    async def get_file(room_id:str,file_id:str,request:Request):
        await auth(request, room_id)
        if not ID.fullmatch(room_id) or not KEY.fullmatch(file_id):
            raise HTTPException(404, 'Файл не найден')
        target = data / room_id / 'files' / (file_id + '.json')
        if not target.is_file():raise HTTPException(404,'Картинка не найдена. Сохраните копию доски и сообщите преподавателю.')
        return JSONResponse(json.loads(target.read_text()))
    @app.websocket('/ws/{room_id}')
    async def websocket(room_id:str,socket:WebSocket):
        try:user=await auth(socket, room_id);origin_check(socket,True);room=store.room(room_id)
        except HTTPException:await socket.close(code=1008);return
        async with room.lock:
            if len(room.peers)>=6:await socket.close(code=1013);return
            await socket.accept();peer=secrets.token_hex(8);room.peers[peer]=socket
            await socket.send_text(encode({'type':'scene',**room.scene,'initial':True,'clientId':peer,'canEdit':user.get('can_edit',True) if isinstance(user,dict) else True,'lessonId':user.get('lesson_id') if isinstance(user,dict) else None,'canAttachPdf':user.get('can_attach_pdf',False) if isinstance(user,dict) else False,'usage':sheet_usage(room.scene,room.path/'scene.json'),'sheets':lesson_sheets(room_id)[1],'fileIds':[p.stem for p in (room.path/'files').glob('*.json')]}))
            await room.broadcast({'type':'presence','count':len(room.peers)})
        frames=deque();started=time.monotonic();received=0;largest=0;max_rate=0;slowest=0;close_code=None;close_reason='unknown'
        message_budget = MESSAGE_BURST
        budget_updated_at = started
        room_tag=hashlib.sha256(room_id.encode()).hexdigest()[:12]
        LOG.info('board_ws_open room=%s connection=%s peers=%s build=%s',room_tag,peer,len(room.peers),BUILD)
        try:
            while True:
                raw=await socket.receive_text();now=time.monotonic();processing_started=now;received+=1;size=len(raw.encode());largest=max(largest,size)
                while frames and frames[0]<now-1:frames.popleft()
                max_rate=max(max_rate,len(frames)+1)
                # Allow queued messages to arrive together without disconnecting a normal client.
                message_budget = min(MESSAGE_BURST, message_budget + (now - budget_updated_at) * MESSAGES_PER_SECOND)
                budget_updated_at = now
                if message_budget < 1:
                    close_code=1008;close_reason='message_rate_limit';await socket.close(code=close_code,reason=close_reason);break
                if size>MAX_FRAME:
                    close_code=1009;close_reason='message_size_limit';await socket.close(code=close_code,reason=close_reason);break
                message_budget -= 1
                frames.append(now)
                try:
                    message=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Некорректное число')))
                    if not isinstance(message,dict):raise ValueError('Некорректный запрос')
                    if message.get('type')=='pointer':
                        x,y=message.get('x'),message.get('y')
                        if type(x) not in (int,float) or type(y) not in (int,float) or not math.isfinite(x+y) or abs(x)+abs(y)>2*10**7:continue
                        await room.broadcast({'type':'pointer','id':peer,'user':user['label'] if isinstance(user,dict) else user,'x':x,'y':y});continue
                    if message.get('type')=='ping':await socket.send_text('{"type":"pong"}');continue
                    if message.get('type')!='update':raise ValueError('Некорректный запрос')
                    if lesson_access is not None:
                        try:
                            await auth(socket, room_id, write=True)
                        except HTTPException as error:
                            await socket.send_text(encode({'type': 'error', 'message': error.detail}))
                            close_code=1008;close_reason='lesson_access';await socket.close(code=1008)
                            break
                    incoming=elements(message.get('elements'));seq=message.get('seq')
                    if type(seq) is not int or not 0<=seq<=2**53-1:raise ValueError('Некорректный номер обновления')
                    background=message.get('background')
                    if background is not None and (not isinstance(background,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',background)):raise ValueError('Некорректный фон')
                    async with room.lock:
                        generation = message.get('generation', 0)
                        if type(generation) is not int or generation != room.scene.get('generation', 0):
                            await socket.send_text(encode({
                                'type': 'error', 'code': 'sheet_generation',
                                'message': 'Лист был очищен. Обновите страницу.',
                            }))
                            continue
                        for item in incoming:
                            if item['type']=='image' and not item.get('isDeleted') and item.get('fileId') and not (room.path/'files'/(item['fileId']+'.json')).is_file():raise ValueError('Сначала дождитесь загрузки картинки.')
                        merged,changed=merge(room.scene['elements'],incoming)
                        updated=bool(changed or (background is not None and background!=room.scene['background']))
                        next_scene={**room.scene,'elements':merged,'background':background or room.scene['background'],'revision':room.scene['revision']+int(updated)}
                        if updated:await asyncio.to_thread(atomic,room.path/'scene.json',next_scene);room.scene=next_scene
                        canonical={item['id']:item for item in merged}
                        await room.broadcast({'type':'scene','elements':[canonical[item['id']] for item in incoming],'background':room.scene['background'],'revision':room.scene['revision'],'usage':sheet_usage(room.scene,room.path/'scene.json'),'seq':seq,'senderId':peer,'fileIds':list({item['fileId'] for item in [canonical[value['id']] for value in incoming] if item['type']=='image' and item.get('fileId')})})
                except SheetCapacityError as error:
                    await socket.send_text(encode({'type': 'error', 'code': 'sheet_capacity', 'message': str(error)}))
                except (ValueError,TypeError,KeyError) as error:await socket.send_text(encode({'type':'error','message':str(error)[:200]}))
                except OSError:
                    LOG.exception('board_save_failed room=%s connection=%s',room_tag,peer)
                    await socket.send_text(encode({'type':'error','message':'Не удалось сохранить доску. Скачайте копию на своё устройство.'}))
                finally:
                    elapsed=time.monotonic()-processing_started;slowest=max(slowest,elapsed)
                    if elapsed>1:LOG.warning('board_slow_message room=%s connection=%s seconds=%.3f bytes=%s',room_tag,peer,elapsed,size)
        except WebSocketDisconnect as error:
            close_code=error.code;close_reason='peer_or_transport_closed'
        except Exception:
            close_reason='handler_error';LOG.exception('board_ws_handler_error room=%s connection=%s',room_tag,peer)
            try:await socket.close(code=1011,reason='handler_error')
            except Exception:pass
            raise
        finally:
            LOG.info('board_ws_close room=%s connection=%s code=%s cause=%s seconds=%.1f messages=%s max_bytes=%s max_rate=%s slowest_seconds=%.3f',room_tag,peer,close_code,close_reason,time.monotonic()-started,received,largest,max_rate,slowest)
            room.peers.pop(peer,None)
            await room.broadcast({'type':'leave','id':peer,'count':len(room.peers)})
            if not room.peers and not room.lock.locked():store.rooms.pop(room_id,None)
    @app.get('/')
    @app.get('/room/{room_id}')
    async def index(request:Request,room_id:str|None=None):
        await auth(request, room_id)
        if room_id:store.room(room_id)
        return FileResponse(static/'index.html',headers={'Cache-Control':'no-store'})
    app.mount('/assets',StaticFiles(directory=static/'assets',check_dir=False),name='assets')
    app.mount('/excalidraw-assets',StaticFiles(directory=static/'excalidraw-assets',check_dir=False),name='fonts')
    return app

