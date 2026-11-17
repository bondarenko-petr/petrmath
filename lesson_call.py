"""Opt-in, self-hosted video rooms for scheduled lessons."""
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
from pydantic import BaseModel, StrictBool

from accounts import database, guard
from admin import require_admin
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
    token = sign(key, secret, {'roomCreate': True})
    try:
        response = httpx.post(f'http://127.0.0.1:7880/twirp/livekit.RoomService/{method}',
                              json=payload, headers={'Authorization': 'Bearer ' + token}, timeout=5)
        if method == 'DeleteRoom' and response.status_code == 404 and response.headers.get('content-type', '').startswith('application/json') and response.json().get('code') == 'not_found':
            return
        response.raise_for_status()
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


class CallMode(BaseModel):
    enabled: StrictBool


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
    available = lesson['status'] == 'scheduled' if user['role'] == 'admin' else eligible(lesson)
    current = state(path)
    return {'available': available, 'enabled': available and current.get('enabled', False)}


@router.put('/{lesson_id}/call')
def set_call(lesson_id: int, mode: CallMode, request: Request, user=Depends(require_admin)):
    guard(request)
    from lesson_board import board_enabled
    config = settings() if board_enabled() else None
    if not config:
        raise HTTPException(503, 'Видеосвязь пока не настроена')
    with lock:
        lesson, path = lesson_and_path(lesson_id)
        current = state(path)
        if mode.enabled:
            if lesson['status'] != 'scheduled':
                raise HTTPException(409, 'Видеосвязь включается для запланированного занятия')
            if current.get('enabled'):
                return {'enabled': True}
            if current.get('room'):
                room_service(config, 'DeleteRoom', {'room': current['room']})
            atomic(path, {'enabled': True, 'room': secrets.token_hex(24)})
        elif current.get('room'):
            atomic(path, {**current, 'enabled': False})
            room_service(config, 'DeleteRoom', {'room': current['room']})
            atomic(path, {})
    return {'enabled': mode.enabled}


@router.post('/{lesson_id}/call/token')
def join_call(lesson_id: int, request: Request, response: Response, user=Depends(member)):
    guard(request)
    response.headers['Cache-Control'] = 'no-store'
    from lesson_board import board_mapping
    config = settings()
    if not config:
        raise HTTPException(404, 'Видеосвязь выключена')
    with lock:
        board_mapping(lesson_id, user)
        lesson, path = lesson_and_path(lesson_id)
        current = state(path)
        if not eligible(lesson) or not current.get('enabled'):
            raise HTTPException(403, 'Видеосвязь для этого урока выключена')
        room = current['room']
        room_service(config, 'CreateRoom', {'name': room, 'max_participants': 2, 'empty_timeout': 90})
        url, key, secret = config
        identity = 'teacher' if user['role'] == 'admin' else 'student-' + str(user['id'])
        token = sign(key, secret, {'roomJoin': True, 'room': room, 'canPublish': True,
                                   'canSubscribe': True, 'canPublishData': False,
                                   'canPublishSources': ['camera', 'microphone']}, identity, user['name'])
    return {'url': url, 'token': token}
