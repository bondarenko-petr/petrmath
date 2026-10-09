"""Scheduling source of truth: UTC timestamps, local wall-time recurrence."""
import os
import time
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from accounts import database, profile, guard
from admin import require_admin

router = APIRouter(prefix='/api/lessons', tags=['Lessons'])


def member(request: Request, response: Response):
    user = profile(request, response)
    if user['must_change_password']:
        raise HTTPException(403, 'Сначала смените временный пароль')
    if user['role'] not in ('admin', 'student'):
        raise HTTPException(403, 'Нет доступа к расписанию')
    return user


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, 'Неизвестный часовой пояс')


def timestamp(value, tz):
    if value.tzinfo is not None:
        return int(value.timestamp())
    aware = value.replace(tzinfo=zone(tz))
    if datetime.fromtimestamp(aware.timestamp(), zone(tz)).replace(tzinfo=None) != value:
        raise HTTPException(422, 'Такого местного времени нет из-за перевода часов')
    if value.replace(tzinfo=zone(tz), fold=1).utcoffset() != aware.utcoffset():
        raise HTTPException(422, 'Время неоднозначно из-за перевода часов. Выберите другое время.')
    return int(aware.timestamp())


class LessonInput(BaseModel):
    student_id: int = Field(gt=0, strict=True)
    starts_at: datetime
    timezone: str = Field(default='Europe/Moscow', max_length=100)
    duration_minutes: int | None = Field(default=None, ge=1, le=1440, strict=True)
    price_kopecks: int | None = Field(default=None, ge=0, le=100000000, strict=True)
    topic: str = Field(default='', max_length=300)
    meeting_url: str = Field(default='', max_length=2000)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    recurrence_end: date | None = None

    @field_validator('weekdays')
    @classmethod
    def weekdays_valid(cls, values):
        if any(type(v) is not int or not 0 <= v <= 6 for v in values):
            raise ValueError('Дни недели должны быть от 0 до 6')
        return sorted(set(values))

    @field_validator('meeting_url')
    @classmethod
    def url_valid(cls, value):
        from urllib.parse import urlsplit
        value = value.strip()
        if value:
            url = urlsplit(value)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('Ссылка на занятие должна начинаться с https://')
        return value

    @field_validator('topic')
    @classmethod
    def strip_topic(cls, value):
        return value.strip()


class LessonEdit(LessonInput):
    scope: Literal['one', 'following', 'series'] = 'one'


class StatusInput(BaseModel):
    status: Literal['scheduled', 'completed', 'cancelled']
    scope: Literal['one', 'following', 'series'] = 'one'


def serialize(row):
    data = dict(row)
    data['starts_at'] = datetime.fromtimestamp(data['starts_at'], timezone.utc).isoformat()
    data['ends_at'] = datetime.fromtimestamp(data['ends_at'], timezone.utc).isoformat()
    return data


def lock_schedule(cursor, p, admin_id):
    # Single-teacher MVP: all writers acquire the same transaction lock.
    if p == '?':
        cursor.execute('BEGIN IMMEDIATE')
    else:
        cursor.execute('SELECT id FROM lesson_schedule_lock WHERE id=1 FOR UPDATE')
        cursor.fetchone()


def get_lesson(cursor, p, lesson_id):
    cursor.execute(f'SELECT * FROM lessons WHERE id={p}', (lesson_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, 'Занятие не найдено')
    return dict(row)


def selected(cursor, p, row, scope):
    if scope == 'one' or row['series_id'] is None:
        return [row]
    clause = f'series_id={p}'
    args = [row['series_id']]
    if scope == 'following':
        clause += f' AND starts_at>={p}'
        args.append(row['starts_at'])
    cursor.execute(f'SELECT * FROM lessons WHERE {clause} ORDER BY starts_at', tuple(args))
    return [dict(r) for r in cursor.fetchall()]


def check_conflicts(cursor, p, records, excluded=()):
    intervals = sorted((r['starts_at'], r['ends_at']) for r in records if r['status'] == 'scheduled')
    if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
        raise HTTPException(409, 'Занятия серии пересекаются')
    for start, end in intervals:
        sql = f"SELECT id FROM lessons WHERE status='scheduled' AND starts_at<{p} AND ends_at>{p}"
        args = [end, start]
        if excluded:
            sql += ' AND id NOT IN (' + ','.join([p] * len(excluded)) + ')'
            args.extend(excluded)
        cursor.execute(sql + ' LIMIT 1', tuple(args))
        if cursor.fetchone():
            raise HTTPException(409, 'В это время уже назначено другое занятие')


def student_defaults(cursor, p, student_id):
    cursor.execute(f"SELECT u.is_active,COALESCE(s.default_duration_minutes,60) AS duration,COALESCE(s.default_price_kopecks,0) AS price FROM users u LEFT JOIN student_profiles s ON s.user_id=u.id WHERE u.id={p} AND u.role='student'", (student_id,))
    row = cursor.fetchone()
    if not row or not row['is_active']:
        raise HTTPException(422, 'Выберите активного ученика')
    return row


@router.get('/settings')
def settings(user=Depends(member)):
    name = os.environ.get('LESSON_TIMEZONE', 'Europe/Moscow')
    zone(name)
    return {'timezone': name, 'role': user['role'], 'today': datetime.now(zone(name)).date().isoformat()}


@router.get('')
def list_lessons(response: Response, from_ts: int = Query(0, ge=0), to_ts: int | None = Query(None, ge=0),
                 from_date: date | None = None, to_date: date | None = None, student_id: int | None = Query(None, gt=0), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(member)):
    tz = os.environ.get('LESSON_TIMEZONE', 'Europe/Moscow')
    if from_date:
        from_ts = timestamp(datetime.combine(from_date, datetime.min.time()), tz)
    if to_date:
        to_ts = timestamp(datetime.combine(to_date, datetime.min.time()), tz)
    if to_ts is not None and to_ts <= from_ts:
        raise HTTPException(422, 'Конец периода должен быть позже начала')
    with database() as (c, p):
        clause, args = f'l.starts_at>={p}', [from_ts]
        if to_ts is not None:
            clause += f' AND l.starts_at<{p}'; args.append(to_ts)
        owner = user['id'] if user['role'] == 'student' else student_id
        if owner is not None:
            clause += f' AND l.student_id={p}'; args.append(owner)
        c.execute(f'SELECT COUNT(*) AS total FROM lessons l WHERE {clause}', tuple(args))
        total = c.fetchone()['total']
        c.execute(f'SELECT l.*,u.name AS student_name FROM lessons l JOIN users u ON u.id=l.student_id WHERE {clause} ORDER BY l.starts_at,l.id LIMIT {p} OFFSET {p}', (*args, limit, offset))
        items = [serialize(r) for r in c.fetchall()]
    response.headers['Cache-Control'] = 'no-store'
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/summary')
def summary(user=Depends(member)):
    now = int(time.time())
    tz = zone(os.environ.get('LESSON_TIMEZONE', 'Europe/Moscow'))
    today = datetime.fromtimestamp(now, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    with database() as (c, p):
        owner = '' if user['role'] == 'admin' else f' AND l.student_id={p}'
        args = () if user['role'] == 'admin' else (user['id'],)
        base = 'SELECT l.*,u.name AS student_name FROM lessons l JOIN users u ON u.id=l.student_id WHERE '
        c.execute(base + f"l.ends_at>{p} AND l.status='scheduled'" + owner + ' ORDER BY l.starts_at LIMIT 5', (now, *args))
        upcoming = [serialize(r) for r in c.fetchall()]
        c.execute(base + f'l.starts_at>={p} AND l.starts_at<{p}' + owner + ' ORDER BY l.starts_at', (int(week.timestamp()), int((week + timedelta(days=7)).timestamp()), *args))
        current_week = [serialize(r) for r in c.fetchall()]
    return {'timezone': str(tz), 'upcoming': upcoming, 'week': current_week, 'today': [r for r in current_week if datetime.fromisoformat(r['starts_at']).astimezone(tz).date() == today.date()]}


@router.post('', status_code=201)
def create(data: LessonInput, request: Request, user=Depends(require_admin)):
    guard(request)
    tz = zone(data.timezone)
    first = data.starts_at.astimezone(tz).replace(tzinfo=None) if data.starts_at.tzinfo else data.starts_at
    dates = [first]
    if data.weekdays or data.recurrence_end:
        if not data.weekdays or not data.recurrence_end or not first.date() <= data.recurrence_end <= first.date() + timedelta(days=366):
            raise HTTPException(422, 'Укажите дни недели и конец серии в пределах года')
        dates = [first + timedelta(days=n) for n in range((data.recurrence_end - first.date()).days + 1) if (first + timedelta(days=n)).weekday() in data.weekdays]
        if not dates:
            raise HTTPException(422, 'В выбранном периоде нет занятий')
    starts = [timestamp(d, data.timezone) for d in dates]
    if min(starts) < int(time.time()):
        raise HTTPException(422, 'Новое занятие должно быть в будущем')
    with database() as (c, p):
        lock_schedule(c, p, user['id'])
        defaults = student_defaults(c, p, data.student_id)
        duration = data.duration_minutes if data.duration_minutes is not None else defaults['duration']
        price = data.price_kopecks if data.price_kopecks is not None else defaults['price']
        records = [dict(starts_at=s, ends_at=s + duration * 60, status='scheduled') for s in starts]
        check_conflicts(c, p, records)
        series_id = None
        if data.weekdays:
            c.execute(f'INSERT INTO lesson_series (timezone,created_at) VALUES ({p},{p})', (data.timezone, int(time.time())))
            series_id = c.lastrowid
        ids = []
        for record in records:
            c.execute(f'INSERT INTO lessons (student_id,series_id,starts_at,ends_at,duration_minutes,price_kopecks,topic,meeting_url,timezone,status,created_at) VALUES ({",".join([p]*11)})', (data.student_id, series_id, record['starts_at'], record['ends_at'], duration, price, data.topic, data.meeting_url, data.timezone, 'scheduled', int(time.time())))
            ids.append(c.lastrowid)
    return {'ids': ids, 'series_id': series_id, 'count': len(ids)}


@router.put('/{lesson_id}')
def edit(lesson_id: int, data: LessonEdit, request: Request, user=Depends(require_admin)):
    guard(request)
    if data.weekdays or data.recurrence_end:
        raise HTTPException(422, 'Для новой периодичности создайте новую серию')
    with database() as (c, p):
        lock_schedule(c, p, user['id'])
        row = get_lesson(c, p, lesson_id)
        rows = selected(c, p, row, data.scope)
        if row['status'] == 'completed' or row['starts_at'] <= int(time.time()):
            raise HTTPException(409, 'Историческое занятие нельзя переносить')
        if data.scope != 'one':
            rows = [r for r in rows if r['status'] != 'completed' and r['starts_at'] > int(time.time())]
        student_defaults(c, p, data.student_id)
        target = datetime.fromtimestamp(timestamp(data.starts_at, data.timezone), zone(data.timezone)).replace(tzinfo=None)
        original = datetime.fromtimestamp(row['starts_at'], zone(row['timezone'])).replace(tzinfo=None)
        delta = target - original
        records = []
        for r in rows:
            local = datetime.fromtimestamp(r['starts_at'], zone(r['timezone'])).replace(tzinfo=None)
            start = timestamp(local + delta, data.timezone)
            if start < int(time.time()):
                raise HTTPException(422, 'Перенос возможен только на будущее время')
            duration = data.duration_minutes if data.duration_minutes is not None else r['duration_minutes']
            records.append(r | {'student_id': data.student_id, 'starts_at': start, 'ends_at': start + duration*60, 'duration_minutes': duration, 'price_kopecks': data.price_kopecks if data.price_kopecks is not None else r['price_kopecks'], 'topic': data.topic, 'meeting_url': data.meeting_url, 'timezone': data.timezone})
        check_conflicts(c, p, records, [r['id'] for r in rows])
        for r in records:
            fields = ['student_id','starts_at','ends_at','duration_minutes','price_kopecks','topic','meeting_url','timezone']
            c.execute('UPDATE lessons SET ' + ','.join(f'{f}={p}' for f in fields) + f' WHERE id={p}', (*[r[f] for f in fields], r['id']))
    return {'updated': len(records)}


@router.patch('/{lesson_id}/status')
def status(lesson_id: int, data: StatusInput, request: Request, user=Depends(require_admin)):
    guard(request)
    with database() as (c, p):
        lock_schedule(c, p, user['id'])
        row = get_lesson(c, p, lesson_id)
        rows = selected(c, p, row, data.scope)
        if data.scope != 'one' and data.status == 'completed':
            raise HTTPException(422, 'Отмечайте проведённым каждый урок отдельно')
        rows = [r for r in rows if data.scope == 'one' or (r['status'] != 'completed' and r['starts_at'] > int(time.time()))]
        for r in rows:
            if data.status == 'completed' and r['ends_at'] > int(time.time()):
                raise HTTPException(422, 'Занятие ещё не закончилось')
            if r['status'] == 'completed' and data.status != 'completed':
                raise HTTPException(409, 'История проведённых занятий сохраняется')
        if data.status == 'scheduled':
            if any(r['starts_at'] < int(time.time()) for r in rows):
                raise HTTPException(422, 'Возобновить можно только будущее занятие')
            check_conflicts(c, p, [r | {'status':'scheduled'} for r in rows], [r['id'] for r in rows])
        for r in rows:
            c.execute(f'UPDATE lessons SET status={p} WHERE id={p}', (data.status, r['id']))
    return {'updated': len(rows)}


@router.delete('/{lesson_id}')
def delete(lesson_id: int, request: Request, scope: Literal['one','following','series']='one', user=Depends(require_admin)):
    guard(request)
    with database() as (c, p):
        lock_schedule(c, p, user['id'])
        row = get_lesson(c, p, lesson_id)
        rows = selected(c, p, row, scope)
        if scope == 'one' and (row['starts_at'] <= int(time.time()) or row['status'] == 'completed'):
            raise HTTPException(409, 'Исторические занятия нельзя удалять; используйте отмену')
        rows = [r for r in rows if r['starts_at'] > int(time.time()) and r['status'] != 'completed']
        for r in rows:
            c.execute(f'DELETE FROM lessons WHERE id={p}', (r['id'],))
    return {'deleted': len(rows)}
