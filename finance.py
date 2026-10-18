"""Manual payments and balances derived from payments and completed lessons."""
import time
from datetime import date
from typing import Literal
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
    lesson_count: int | None = Field(default=None, gt=0, le=1000, strict=True)
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
    cursor.execute(f"SELECT u.id,u.name,u.is_active,COALESCE(s.default_price_kopecks,0) AS current_price_kopecks FROM users u LEFT JOIN student_profiles s ON s.user_id=u.id WHERE u.id={p} AND u.role='student'", (student_id,))
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
    # Only money is authoritative. Package quantities are historical metadata,
    # not a second entitlement or a guarantee when lesson prices differ.
    cash = int(paid['paid_kopecks']) - int(spent['spent_kopecks'])
    rate = int(owner['current_price_kopecks'])
    available = max(cash,0) // rate if rate>0 else None
    return owner | {k:int(v) for k,v in (paid | spent).items()} | {
        'current_price_kopecks':rate, 'balance_kopecks':cash,
        'available_lessons':available, 'remaining_lessons':available,
        'remainder_kopecks':max(cash,0) % rate if rate>0 else None,
        'debt_kopecks':max(-cash,0)}


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


@router.get('/report')
def financial_report(response:Response,from_date:date|None=None,to_date:date|None=None,
                     search:str=Query('',max_length=200),debt_only:bool=False,
                     state:Literal['all','active','archive']='all',
                     limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),user=Depends(require_admin)):
    from datetime import datetime,timedelta
    from lessons import settings,zone
    tz=zone(settings(user)['timezone']);today=datetime.now(tz).date()
    first=from_date or today.replace(day=1);last=to_date or today
    if first>last:raise HTTPException(422,'Начало периода должно быть не позже конца')
    if last==date.max:raise HTTPException(422,'Выберите дату окончания раньше 31.12.9999')
    start=int(datetime.combine(first,datetime.min.time(),tzinfo=tz).timestamp())
    end=int(datetime.combine(last+timedelta(days=1),datetime.min.time(),tzinfo=tz).timestamp())
    with database() as (c,p):
        if p=='?':c.execute('BEGIN')
        source=f''' FROM (SELECT u.id,u.name,u.username,u.is_active,
          COALESCE(pa.received,0) AS received_kopecks,COALESCE(sp.earned,0) AS earned_kopecks,
          COALESCE(sp.completed,0) AS completed_lessons,
          CAST(COALESCE(pa.paid,0) AS SIGNED)-CAST(COALESCE(sp.spent,0) AS SIGNED) AS balance_kopecks
          FROM users u
          LEFT JOIN (SELECT student_id,SUM(amount_kopecks) AS paid,
             SUM(CASE WHEN created_at>={p} AND created_at<{p} THEN amount_kopecks ELSE 0 END) AS received
             FROM payments WHERE voided_at IS NULL GROUP BY student_id) pa ON pa.student_id=u.id
          LEFT JOIN (SELECT student_id,SUM(price_kopecks) AS spent,
             SUM(CASE WHEN ends_at>={p} AND ends_at<{p} THEN price_kopecks ELSE 0 END) AS earned,
             SUM(CASE WHEN ends_at>={p} AND ends_at<{p} THEN 1 ELSE 0 END) AS completed
             FROM lessons WHERE status='completed' GROUP BY student_id) sp ON sp.student_id=u.id
          WHERE u.role='student') report'''
        args=[start,end,start,end,start,end]
        c.execute('SELECT COALESCE(SUM(received_kopecks),0) AS received_kopecks,COALESCE(SUM(earned_kopecks),0) AS earned_kopecks,COALESCE(SUM(completed_lessons),0) AS completed_lessons,COALESCE(SUM(CASE WHEN balance_kopecks<0 THEN -balance_kopecks ELSE 0 END),0) AS debt_kopecks,COALESCE(SUM(CASE WHEN balance_kopecks<0 THEN 1 ELSE 0 END),0) AS debtors_count'+source,tuple(args))
        totals={key:int(value) for key,value in dict(c.fetchone()).items()}
        clauses=['1=1']
        if debt_only:clauses.append('balance_kopecks<0')
        if state!='all':clauses.append('is_active='+('1' if state=='active' else '0'))
        if search.strip():
            pattern='%'+search.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            clauses.append(f"(name LIKE {p} ESCAPE '!' OR username LIKE {p} ESCAPE '!')");args.extend([pattern,pattern])
        where=' WHERE '+' AND '.join(clauses)
        c.execute('SELECT COUNT(*) AS total'+source+where,tuple(args));total=int(c.fetchone()['total'])
        c.execute('SELECT *'+source+where+f' ORDER BY balance_kopecks ASC,name,id LIMIT {p} OFFSET {p}',(*args,limit,offset))
        items=[]
        for row in c.fetchall():
            row=dict(row)
            for key in ['received_kopecks','earned_kopecks','completed_lessons','balance_kopecks']:row[key]=int(row[key])
            row['debt_kopecks']=max(-row['balance_kopecks'],0);items.append(row)
    response.headers['Cache-Control']='no-store'
    return {'from_date':first.isoformat(),'to_date':last.isoformat(),'timezone':str(tz),'totals':totals,'items':items,'total':total,'limit':limit,'offset':offset}
