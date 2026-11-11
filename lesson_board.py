"""Connect a scheduled lesson with its private whiteboard."""
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from accounts import database, guard
from board.app import atomic, create_app
from lessons import get_lesson, lock_schedule, member
from admin import require_admin
from board_lifecycle import read_state, status, mark_completed, preserve

router = APIRouter(prefix='/api/lessons', tags=['Lesson board'])
OPEN_BEFORE_SECONDS = 30 * 60
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
        raise HTTPException(403, 'Доска доступна за 30 минут до начала занятия')
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
    if read_state(room_id).get('deleted_at'):
        raise HTTPException(410, 'Доска удалена. PDF доступен в материалах занятия')
    return access | {
        'lesson_id': lesson['id'],
        'lesson_starts_at': lesson['starts_at'],
        'lesson_ends_at': lesson['ends_at'],
        'can_edit': lesson_access(lesson, user, write=write),
        'can_attach_pdf': user['role'] == 'admin' and lesson['status'] == 'completed',
    }


@router.get('/board-settings')
def board_settings():
    return {'enabled': board_enabled(), 'open_before_seconds': OPEN_BEFORE_SECONDS,
            'cleanup_enabled': os.environ.get('LESSON_BOARD_CLEANUP_ENABLED', '').lower() == 'true'}


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
        if read_state(room_id).get('deleted_at'):
            raise HTTPException(410, 'Доска удалена. PDF доступен в материалах занятия')
        scene = board_data() / room_id / 'scene.json'
        if not scene.is_file():
            atomic(scene, {'elements': [], 'background': '#ffffff', 'revision': 0, 'created': int(time.time())})
        if not row:
            cursor.execute(f'INSERT INTO lesson_boards (lesson_id,room_id) VALUES ({placeholder},{placeholder})',
                           (lesson_id, room_id))
    return {'url': '/board/room/' + room_id}


def board_mapping(lesson_id, user):
    if not board_enabled():
        raise HTTPException(404, 'Доска не подключена')
    with database() as (c, p):
        lesson = get_lesson(c, p, lesson_id)
        lesson_access(lesson, user)
        c.execute(f'SELECT room_id FROM lesson_boards WHERE lesson_id={p}', (lesson_id,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, 'Доска не найдена')
    return lesson, row['room_id']


@router.get('/board-cleanup-status')
def cleanup_status(user=Depends(require_admin)):
    if not board_enabled():
        return {'errors': []}
    with database() as (c, p):
        c.execute('SELECT lesson_id,room_id FROM lesson_boards')
        rows = [dict(row) for row in c.fetchall()]
    errors = []
    for row in rows:
        error = read_state(row['room_id']).get('error')
        if error:
            errors.append({'lesson_id': row['lesson_id'], 'error': error})
    return {'errors': errors}


@router.get('/{lesson_id}/board-status')
def board_status(lesson_id: int, user=Depends(member)):
    lesson, root = board_mapping(lesson_id, user)
    if lesson['status'] == 'completed':
        mark_completed(lesson_id)
    return status(root)


@router.post('/{lesson_id}/board-pdf')
async def board_pdf(lesson_id: int, request: Request, user=Depends(require_admin)):
    guard(request)
    lesson, root = board_mapping(lesson_id, user)
    if lesson['status'] != 'completed':
        raise HTTPException(409, 'Сначала отметьте занятие проведённым')
    mark_completed(lesson_id)
    try:
        state = await preserve(request.app.state.lesson_board_store, root, lesson_id, admin_id=user['id'])
        return {'file_id': state.get('pdf_id')}
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger('uvicorn.error').exception('lesson_board_pdf_failed lesson=%s', lesson_id)
        raise HTTPException(503, 'Не удалось сохранить PDF. Доска сохранена; проверьте настройку экспорта и свободное место для вложений')


def mount_board(app):
    app.include_router(router)
    if board_enabled():
        origin = os.environ.get('LESSON_BOARD_ORIGIN', 'https://prosto5.ru')
        static = Path(os.environ.get('LESSON_BOARD_DIST', ROOT / 'board' / 'frontend' / 'dist'))
        board = create_app(board_data(), origin, static, lesson_access=authorize_board)
        app.state.lesson_board_store = board.state.store
        app.mount('/board', board, name='lesson-board')
