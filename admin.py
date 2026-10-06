"""Read-only admin endpoints; authorization always comes from the stored role."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from accounts import database, profile

router = APIRouter(prefix='/api/admin', tags=['Administration'])


def require_admin(request: Request, response: Response):
    user = profile(request, response)
    if user['role'] != 'admin':
        raise HTTPException(403, 'Доступ только для администратора')
    return user


@router.get('/students')
def students(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(require_admin)):
    with database() as (cursor, p):
        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role='student'")
        total = cursor.fetchone()['total']
        cursor.execute(f"SELECT id,name,email,role FROM users WHERE role='student' ORDER BY id DESC LIMIT {p} OFFSET {p}", (limit, offset))
        items = [dict(row) for row in cursor.fetchall()]
    response.headers['Cache-Control'] = 'no-store'
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/trial-requests')
def requests(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(require_admin)):
    with database() as (cursor, p):
        cursor.execute('SELECT COUNT(*) AS total FROM trial_requests')
        total = cursor.fetchone()['total']
        cursor.execute(f'SELECT id,created_at,name,email,phone,courses,message,consent FROM trial_requests ORDER BY id DESC LIMIT {p} OFFSET {p}', (limit, offset))
        items = [dict(row) for row in cursor.fetchall()]
    response.headers['Cache-Control'] = 'no-store'
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}
