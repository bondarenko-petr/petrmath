"""Manual payments and balances derived from payments and completed lessons."""
import time
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from accounts import database, guard
from admin import require_admin
from lessons import member, lock_schedule

router = APIRouter(prefix='/api/finance', tags=['Finance'])


class PaymentInput(BaseModel):
    request_id: UUID
    student_id: int = Field(gt=0, strict=True)
    amount_kopecks: int = Field(gt=0, le=100000000, strict=True)
    lesson_count: int = Field(gt=0, le=1000, strict=True)
    note: str = Field(default='', max_length=300)

    @field_validator('note')
    @classmethod
    def strip_note(cls, value):
        return value.strip()


class VoidInput(BaseModel):
    reason: str = Field(min_length=1, max_length=300)

    @field_validator('reason', mode='before')
    @classmethod
    def strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


def student(cursor, p, student_id):
    cursor.execute(f"SELECT id,name,is_active FROM users WHERE id={p} AND role='student'", (student_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, 'Ученик не найден')
    return dict(row)


def balance(cursor, p, student_id):
    owner = student(cursor, p, student_id)
    cursor.execute(f'''SELECT COALESCE(SUM(amount_kopecks),0) AS paid_kopecks,
        COALESCE(SUM(lesson_count),0) AS paid_lessons FROM payments
        WHERE student_id={p} AND voided_at IS NULL''', (student_id,))
    paid = dict(cursor.fetchone())
    cursor.execute(f'''SELECT COUNT(*) AS completed_lessons, COALESCE(SUM(price_kopecks),0) AS spent_kopecks
        FROM lessons WHERE student_id={p} AND status='completed' ''', (student_id,))
    spent = dict(cursor.fetchone())
    # MySQL SUM returns Decimal, SQLite returns int. Money always stays in kopecks.
    return owner | {k:int(v) for k,v in (paid | spent).items()} | {
        'balance_kopecks': int(paid['paid_kopecks']) - int(spent['spent_kopecks']),
        'remaining_lessons': int(paid['paid_lessons']) - int(spent['completed_lessons'])}


@router.get('/balance')
def get_balance(response: Response, student_id: int | None = Query(None, gt=0),
                limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(member)):
    owner_id = user['id'] if user['role']=='student' else student_id
    if owner_id is None:
        raise HTTPException(422, 'Выберите ученика')
    with database() as (c,p):
        if p == '?':
            c.execute('BEGIN')
        result = balance(c,p,owner_id)
        c.execute(f'''SELECT (SELECT COUNT(*) FROM payments WHERE student_id={p}) +
            (SELECT COUNT(*) FROM lessons WHERE student_id={p} AND status='completed') AS total''', (owner_id,owner_id))
        total = int(c.fetchone()['total'])
        c.execute(f'''SELECT * FROM (
            SELECT id,'payment' AS kind,created_at AS occurred_at,amount_kopecks,lesson_count,
                note,voided_at,void_reason FROM payments WHERE student_id={p}
            UNION ALL
            SELECT id,'lesson' AS kind,ends_at AS occurred_at,-CAST(price_kopecks AS SIGNED) AS amount_kopecks,
                -1 AS lesson_count,topic AS note,NULL AS voided_at,'' AS void_reason
                FROM lessons WHERE student_id={p} AND status='completed'
            ) AS ledger ORDER BY occurred_at DESC,kind,id DESC LIMIT {p} OFFSET {p}''', (owner_id,owner_id,limit,offset))
        history = [dict(row) for row in c.fetchall()]
    response.headers['Cache-Control']='no-store'
    return {'student':result,'items':history,'total':total,'limit':limit,'offset':offset}


@router.post('/payments', status_code=201)
def create_payment(data: PaymentInput, request: Request, response: Response, user=Depends(require_admin)):
    guard(request)
    with database() as (c,p):
        # The same lock as completion: serializes payment retries across workers.
        lock_schedule(c,p,user['id'])
        student(c,p,data.student_id)
        c.execute(f'SELECT * FROM payments WHERE request_id={p}', (str(data.request_id),))
        old = c.fetchone()
        if old:
            if (old['student_id'],old['amount_kopecks'],old['lesson_count'],old['note']) != (data.student_id,data.amount_kopecks,data.lesson_count,data.note):
                raise HTTPException(409, 'Этот запрос оплаты уже использован с другими данными')
            response.status_code=200
            payment_id=old['id']
        else:
            c.execute(f'''INSERT INTO payments (request_id,student_id,amount_kopecks,lesson_count,note,created_at,created_by)
                VALUES ({','.join([p]*7)})''', (str(data.request_id),data.student_id,data.amount_kopecks,data.lesson_count,data.note,int(time.time()),user['id']))
            payment_id=c.lastrowid
    response.headers['Cache-Control']='no-store'
    return {'id':payment_id,'status':'saved'}


@router.post('/payments/{payment_id}/void')
def void_payment(payment_id:int, data:VoidInput, request:Request, response:Response, user=Depends(require_admin)):
    guard(request)
    with database() as (c,p):
        lock_schedule(c,p,user['id'])
        c.execute(f'SELECT id,voided_at FROM payments WHERE id={p}', (payment_id,))
        row=c.fetchone()
        if not row:
            raise HTTPException(404,'Оплата не найдена')
        if row['voided_at'] is None:
            c.execute(f'UPDATE payments SET voided_at={p},voided_by={p},void_reason={p} WHERE id={p}',
                (int(time.time()),user['id'],data.reason,payment_id))
    response.headers['Cache-Control']='no-store'
    return {'status':'voided'}
