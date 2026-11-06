"""Connect a scheduled lesson with its private whiteboard."""
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from accounts import database, guard
from board.app import atomic, create_app
from lessons import get_lesson, lock_schedule, member

router = APIRouter(prefix='/api/lessons', tags=['Lesson board'])
OPEN_BEFORE_SECONDS = 10 * 60
ROOT = Path(__file__).resolve().parent


def board_enabled():
    return os.environ.get('LESSON_BOARD_ENABLED', '').lower() == 'true'


def board_data():
    return Path(os.environ.get('LESSON_BOARD_DATA_DIR', ROOT / 'data' / 'lesson-boards'))


def lesson_access(lesson, user, *, write=False):
    if user['role'] == 'student' and lesson['student_id'] != user['id']:
        raise HTTPException(404, 'Доска занятия не найдена')
    if lesson['status'] == 'cancelled':
        raise HTTPException(404, 'Занятие отменено')
    if lesson['status'] == 'scheduled' and time.time() < lesson['starts_at'] - OPEN_BEFORE_SECONDS:
        raise HTTPException(403, 'Доска доступна за 10 минут до начала занятия')
    can_edit = user['role'] == 'admin' or lesson['status'] != 'completed'
    if write and not can_edit:
        raise HTTPException(403, 'Доска проведённого занятия доступна для просмотра')
    return can_edit


def authorize_board(connection, room_id, write):
    user = member(connection, Response())
    access = {'label': user['name'], 'rate_key': user['id']}
    if room_id is None:
        return access
    with database() as (cursor, placeholder):
        cursor.execute(f'SELECT lesson_id FROM lesson_boards WHERE room_id={placeholder}', (room_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, 'Доска занятия не найдена')
        lesson = get_lesson(cursor, placeholder, row['lesson_id'])
    return access | {
        'lesson_id': lesson['id'],
        'can_edit': lesson_access(lesson, user, write=write),
        'can_attach_pdf': user['role'] == 'admin' and lesson['status'] == 'completed',
    }


@router.get('/board-settings')
def board_settings():
    return {'enabled': board_enabled(), 'open_before_seconds': OPEN_BEFORE_SECONDS}


@router.post('/{lesson_id}/board')
def open_lesson_board(lesson_id: int, request: Request, user=Depends(member)):
    guard(request)
    if not board_enabled():
        raise HTTPException(404, 'Доска для занятий пока не подключена')
    with database() as (cursor, placeholder):
        lock_schedule(cursor, placeholder, user['id'])
        lesson = get_lesson(cursor, placeholder, lesson_id)
        lesson_access(lesson, user)
        cursor.execute(f'SELECT room_id FROM lesson_boards WHERE lesson_id={placeholder}', (lesson_id,))
        row = cursor.fetchone()
        if not row and lesson['status'] == 'completed':
            raise HTTPException(404, 'Для этого занятия доска не была создана')
        room_id = row['room_id'] if row else secrets.token_hex(24)
        scene = board_data() / room_id / 'scene.json'
        if not scene.is_file():
            atomic(scene, {'elements': [], 'background': '#ffffff', 'revision': 0, 'created': int(time.time())})
        if not row:
            cursor.execute(f'INSERT INTO lesson_boards (lesson_id,room_id) VALUES ({placeholder},{placeholder})',
                           (lesson_id, room_id))
    return {'url': '/board/room/' + room_id}


def mount_board(app):
    app.include_router(router)
    if board_enabled():
        origin = os.environ.get('LESSON_BOARD_ORIGIN', 'https://prosto5.ru')
        static = Path(os.environ.get('LESSON_BOARD_DIST', ROOT / 'board' / 'frontend' / 'dist'))
        app.mount('/board', create_app(board_data(), origin, static, lesson_access=authorize_board), name='lesson-board')
