"""Single-process board retention. Never remove a board without a durable PDF."""
import asyncio
import base64
from contextlib import asynccontextmanager, AsyncExitStack
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

from fastapi import HTTPException
from accounts import database
from board.app import ID, KEY, MAX_SHEETS, atomic, encode

LOG = logging.getLogger('uvicorn.error')
PDF_LAYOUT_VERSION = 'width-pages-1'
RETENTION = 24 * 3600
EXPORT_LIMIT = 32 * 1024 * 1024
EXPORT_LOCK = asyncio.Lock()


def state_path(root):
    from lesson_board import board_data
    if not ID.fullmatch(root):
        raise ValueError('Invalid board identifier')
    return board_data() / '.lifecycle' / (root + '.json')


def read_state(root):
    try:
        return json.loads(state_path(root).read_text())
    except FileNotFoundError:
        return {}


def write_state(root, state):
    path = state_path(root)
    atomic(path, state)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def mark_completed(lesson_id):
    from lesson_board import board_enabled
    if not board_enabled():
        return
    with database() as (c, p):
        c.execute(f'SELECT room_id FROM lesson_boards WHERE lesson_id={p}', (lesson_id,))
        row = c.fetchone()
    if row:
        state = read_state(row['room_id'])
        if not state.get('completed_at'):
            state['completed_at'] = int(time.time())
            write_state(row['room_id'], state)


def status(root):
    state = read_state(root)
    return {'deleted_at': state.get('deleted_at'), 'error': bool(state.get('error'))} | {
        'expires_at': state['completed_at'] + RETENTION if state.get('completed_at') else None,
    }


def sheet_ids(store, root):
    path = store.path / root / 'sheets.json'
    ids = json.loads(path.read_text()) if path.exists() else [root]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SHEETS or ids[0] != root
            or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids)):
        raise ValueError('Некорректный список листов; удаление отменено')
    for sheet in ids[1:]:
        if store.room(sheet).scene.get('lesson') != root:
            raise ValueError('Лист принадлежит другой доске; удаление отменено')
    return ids


@asynccontextmanager
async def frozen(store, root):
    # Mark before waiting for locks: already queued mutations recheck this gate.
    async with store.creation_lock:
        if root in store.frozen:
            raise HTTPException(409, 'Доска уже сохраняется. Повторите позже')
        store.frozen.add(root)
        try:
            ids = sheet_ids(store, root)
            async with AsyncExitStack() as stack:
                for sheet in ids:
                    await stack.enter_async_context(store.room(sheet).lock)
                yield ids
        finally:
            store.frozen.discard(root)


def snapshots(store, ids):
    sheets = []
    total = 0
    for sheet in ids:
        scene = store.room(sheet).scene
        visible = [e for e in scene['elements'] if not e.get('isDeleted')]
        total += len(encode(visible).encode())
        files = {}
        for e in visible:
            if e['type'] == 'image' and e.get('fileId'):
                key = e['fileId']
                if not KEY.fullmatch(key):
                    raise ValueError('Некорректный идентификатор картинки')
                if key in files:
                    continue
                path = store.path / sheet / 'files' / (key + '.json')
                total += path.stat().st_size
                if total > EXPORT_LIMIT:
                    raise ValueError('Материалы доски превышают 32 МБ для автоматического PDF. Доска сохранена')
                files[key] = json.loads(path.read_text())
        if total > EXPORT_LIMIT:
            raise ValueError('Доска слишком велика для автоматического PDF. Доска сохранена')
        sheets.append({'elements': visible, 'background': scene['background'], 'files': files})
    fingerprint = hashlib.sha256((PDF_LAYOUT_VERSION + encode(sheets)).encode()).hexdigest()
    return sheets, fingerprint


def valid_pdf(state, lesson_id):
    """An unrelated attachment, deleted file or missing local PDF is not proof."""
    from materials import storage
    if not state.get('pdf_id'):
        return False
    with database() as (c, p):
        c.execute(f"SELECT storage_key,size FROM material_files WHERE id={p} AND lesson_id={p} AND category='notes' AND media_type='application/pdf' AND deleted_at IS NULL AND archived_at IS NULL", (state['pdf_id'], lesson_id))
        row = c.fetchone()
    if not row:
        return False
    path = storage() / row['storage_key']
    if path.parent != storage() or not path.is_file():
        return False
    raw = path.read_bytes()
    return raw.startswith(b'%PDF-') and len(raw) == row['size'] and hashlib.sha256(raw).hexdigest() == state.get('pdf_sha256')


async def render_pdf(sheets):
    # No authenticated browser or public scene endpoint: snapshots stay in memory.
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise RuntimeError('Серверный экспорт PDF не настроен: установите Playwright и Chromium') from error
    port = int(os.environ.get('LESSON_BOARD_RENDER_PORT', '8000'))
    origin = f'http://127.0.0.1:{port}'
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            async def route(request_route):
                url = request_route.request.url
                if url.startswith(origin + '/board/') or url.startswith(('data:', 'blob:')):
                    await request_route.continue_()
                else:
                    await request_route.abort()
            await page.route('**/*', route)
            await page.goto(origin + '/board/export.html', wait_until='networkidle', timeout=60000)
            await page.wait_for_function('typeof window.renderLessonPdf === "function"', timeout=30000)
            if await page.evaluate('window.lessonPdfLayoutVersion') != PDF_LAYOUT_VERSION:
                raise RuntimeError('Обновите сборку доски: версия экспорта PDF не совпадает с сервером')
            encoded = await asyncio.wait_for(page.evaluate('(sheets) => window.renderLessonPdf(sheets)', sheets), 180)
            raw = base64.b64decode(encoded, validate=True)
            if not raw.startswith(b'%PDF-'):
                raise ValueError('Экспорт не создал PDF')
            return raw
        finally:
            await browser.close()


def attach_pdf(lesson_id, raw, admin_id=None):
    from materials import storage, MAX_FILE_SIZE, lesson
    if len(raw) > MAX_FILE_SIZE:
        raise ValueError('PDF превышает 10 МБ. Доска сохранена; требуется ручное сохранение материалов')
    root = storage()
    file_id = uuid4().hex
    key = file_id + '.pdf'
    path = root / key
    try:
        with database() as (c, p):
            if admin_id is None:
                c.execute("SELECT id FROM users WHERE role='admin' AND is_active=1 ORDER BY id LIMIT 1")
                row = c.fetchone()
                if not row:
                    raise ValueError('Не найден активный администратор для сохранения PDF')
                admin_id = row['id']
            lesson(c, p, lesson_id, {'id':admin_id,'role':'admin'}, True)
            c.execute(f"SELECT COUNT(*) AS total FROM material_files WHERE lesson_id={p} AND category='notes' AND deleted_at IS NULL AND archived_at IS NULL", (lesson_id,))
            if c.fetchone()['total'] >= 5:
                raise ValueError('В конспекте уже 5 вложений. Освободите место для PDF; доска сохранена')
            with path.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            descriptor = os.open(root, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            c.execute('INSERT INTO material_files (id,lesson_id,category,storage_key,filename,media_type,size,created_at,created_by) VALUES (' + ','.join([p]*9) + ')', (file_id, lesson_id, 'notes', key, 'Записи с доски.pdf', 'application/pdf', len(raw), int(time.time()), admin_id))
        return file_id
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def preserve(store, root, lesson_id, *, delete=False, admin_id=None, renderer=render_pdf):
    state = read_state(root)
    if state.get('deleted_at'):
        return state
    async with frozen(store, root) as ids:
        state = read_state(root)
        sheets, fingerprint = snapshots(store, ids)
        if state.get('pdf_fingerprint') != fingerprint or not valid_pdf(state, lesson_id):
            async with EXPORT_LOCK:
                raw = await renderer(sheets)
            file_id = await asyncio.to_thread(attach_pdf, lesson_id, raw, admin_id)
            state.update(pdf_id=file_id, pdf_fingerprint=fingerprint, pdf_sha256=hashlib.sha256(raw).hexdigest(), pdf_at=int(time.time()))
            write_state(root, state)
        if delete:
            # Persist a tombstone before unlinking. A partial deletion is retried,
            # never treated as an empty new board or a reason to remove the PDF.
            state.update(deleted_at=int(time.time()), pending_delete=ids, error=None)
            write_state(root, state)
            for sheet in ids:
                room = store.rooms.get(sheet)
                if room:
                    for socket in list(room.peers.values()):
                        try:
                            await socket.close(code=1008, reason='board_expired_pdf_saved')
                        except Exception:
                            pass
        else:
            state['error'] = None
            state.pop('retry_after', None)
            write_state(root, state)
    if delete:
        await finish_delete(store, root, state)
    return state


async def finish_delete(store, root, state):
    for sheet in state.get('pending_delete', []):
        if not isinstance(sheet, str) or not ID.fullmatch(sheet):
            raise ValueError('Некорректный путь очистки')
        # Only root and verified children recorded while frozen are ever removed.
        target = store.path / sheet
        if target.is_symlink():
            raise ValueError('Символические ссылки в хранилище запрещены')
        if target.exists():
            await asyncio.to_thread(shutil.rmtree, target)
        store.rooms.pop(sheet, None)
    state.pop('pending_delete', None)
    state['error'] = None
    write_state(root, state)


async def sweep(store):
    with database() as (c, p):
        c.execute("SELECT b.lesson_id,b.room_id FROM lesson_boards b JOIN lessons l ON l.id=b.lesson_id WHERE l.status='completed'")
        rows = [dict(row) for row in c.fetchall()]
    for row in rows:
        root = row['room_id']
        try:
            state = read_state(root)
            if state.get('deleted_at'):
                if state.get('pending_delete'):
                    await finish_delete(store, root, state)
                continue
            if not state.get('completed_at'):
                # Legacy boards receive a full day, not immediate deletion.
                mark_completed(row['lesson_id'])
                continue
            if time.time() >= max(state['completed_at'] + RETENTION, state.get('retry_after', 0)):
                await preserve(store, root, row['lesson_id'], delete=True)
        except Exception as error:
            LOG.exception('lesson_board_cleanup_failed lesson=%s', row['lesson_id'])
            try:
                state = read_state(root)
                state['error'] = str(error)[:300]
                state['retry_after'] = int(time.time()) + 900
                write_state(root, state)
            except Exception:
                LOG.exception('lesson_board_cleanup_status_failed')


async def worker(store):
    while True:
        try:
            await sweep(store)
        except Exception:
            LOG.exception('lesson_board_cleanup_cycle_failed')
        await asyncio.sleep(60)
