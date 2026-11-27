"""Self-hosted video rooms available to all scheduled lesson participants."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from accounts import database, guard
from board.app import atomic
from lessons import get_lesson, member

router = APIRouter(prefix='/api/lessons')
lock = threading.Lock()


def settings():
    url = os.getenv('LESSON_CALL_URL', '')
    key = os.getenv('LESSON_CALL_KEY', '')
    secret = os.getenv('LESSON_CALL_SECRET', '')
    if urlsplit(url).scheme == 'wss' and key and len(secret) >= 32:
        return url, key, secret
    return None


def sign(key, secret, grants, identity='', name=''):
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=')
    now = int(time.time())
    claims = {'iss': key, 'nbf': now - 5, 'exp': now + 60, 'video': grants}
    if identity:
        claims.update(sub=identity, name=name)
    body = encode(b'{"alg":"HS256","typ":"JWT"}') + b'.' + encode(json.dumps(claims).encode())
    return (body + b'.' + encode(hmac.digest(secret.encode(), body, hashlib.sha256))).decode()


def room_service(config, method, payload):
    _, key, secret = config
    grants = {'roomAdmin': True, 'room': payload['room']} if method == 'ListParticipants' else {'roomCreate': True}
    token = sign(key, secret, grants)
    try:
        response = httpx.post(f'http://127.0.0.1:7880/twirp/livekit.RoomService/{method}',
                              json=payload, headers={'Authorization': 'Bearer ' + token}, timeout=5)
        if method == 'DeleteRoom' and response.status_code == 404 and response.headers.get('content-type', '').startswith('application/json') and response.json().get('code') == 'not_found':
            return
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        raise HTTPException(503, 'Сервис видеосвязи недоступен. Повторите попытку.') from error


def lesson_and_path(lesson_id):
    from lesson_board import board_data
    with database() as (cursor, placeholder):
        lesson = get_lesson(cursor, placeholder, lesson_id)
    return lesson, board_data() / '.calls' / f'{lesson_id}.json'


def state(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def eligible(lesson):
    from lesson_board import OPEN_BEFORE_SECONDS
    return lesson['status'] == 'scheduled' and lesson['starts_at'] - OPEN_BEFORE_SECONDS <= time.time()


@router.get('/{lesson_id}/call')
def call_status(lesson_id: int, response: Response, user=Depends(member)):
    response.headers['Cache-Control'] = 'no-store'
    from lesson_board import board_enabled
    config = settings() if board_enabled() else None
    if not config:
        return {'available': False, 'enabled': False}
    lesson, path = lesson_and_path(lesson_id)
    if user['role'] != 'admin' and lesson['student_id'] != user['id']:
        raise HTTPException(404, 'Занятие не найдено')
    available = eligible(lesson)
    return {'available': available, 'enabled': available}


class CallDevice(BaseModel):
    deviceId: str = Field(default='', max_length=100)
    transfer: bool = False


@router.post('/{lesson_id}/call/token')
def join_call(lesson_id: int, request: Request, response: Response,
              device: CallDevice | None = None, user=Depends(member)):
    guard(request)
    response.headers['Cache-Control'] = 'no-store'
    from lesson_board import board_mapping
    config = settings()
    if not config:
        raise HTTPException(404, 'Видеосвязь выключена')
    device = device or CallDevice()
    with lock:
        board_mapping(lesson_id, user)
        lesson, path = lesson_and_path(lesson_id)
        current = state(path)
        if not eligible(lesson):
            raise HTTPException(403, 'Видеосвязь для этого урока выключена')
        room = current.get('room')
        if not room:
            room = secrets.token_hex(24)
            atomic(path, {'room': room})
        room_service(config, 'CreateRoom', {'name': room, 'max_participants': 2, 'empty_timeout': 90})
        url, key, secret = config
        identity = 'teacher' if user['role'] == 'admin' else 'student-' + str(user['id'])
        participants = room_service(config, 'ListParticipants', {'room': room}).get('participants', [])
        active = next((p for p in participants if p.get('identity') == identity), None)
        claims = current.get('devices', {})
        pending = claims.get(identity, {})
        reserved = pending.get('until', 0) > time.time()
        if (active or reserved) and not device.transfer:
            return {'otherDevice': True}
        microphone = True
        if active:
            microphone = any(t.get('source') in ('MICROPHONE', 2) and not t.get('muted', False)
                             for t in active.get('tracks', []))
        elif reserved:
            microphone = pending.get('microphone', False)
        # Reserve the identity until the issued token expires, covering simultaneous opens.
        claims[identity] = {'id': device.deviceId, 'until': time.time() + 60, 'microphone': microphone}
        atomic(path, {**current, 'room': room, 'devices': claims})
        token = sign(key, secret, {'roomJoin': True, 'room': room, 'canPublish': True,
                                   'canSubscribe': True, 'canPublishData': False,
                                   'canPublishSources': ['camera', 'microphone']}, identity, user['name'])
    return {'url': url, 'token': token, 'microphone': microphone}


@router.post('/{lesson_id}/call/release')
def release_call(lesson_id: int, request: Request, device: CallDevice, user=Depends(member)):
    guard(request)
    from lesson_board import board_mapping
    with lock:
        board_mapping(lesson_id, user)
        _, path = lesson_and_path(lesson_id)
        current = state(path)
        identity = 'teacher' if user['role'] == 'admin' else 'student-' + str(user['id'])
        claims = current.get('devices', {})
        if device.deviceId and claims.get(identity, {}).get('id') == device.deviceId:
            claims.pop(identity)
            atomic(path, {**current, 'devices': claims})
    return {'ok': True}
