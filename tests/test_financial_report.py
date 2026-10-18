import unittest
from datetime import datetime,timezone
from uuid import uuid4
from tests import test_finance as support
from tests.test_accounts import seed_user
from accounts import database


class FinancialReportTests(unittest.TestCase):
    setUp=support.FinanceTests.setUp
    tearDown=support.FinanceTests.tearDown
    pay=support.FinanceTests.pay
    historic_lesson=support.FinanceTests.historic_lesson

    def report(self,**params):
        return self.client.get('/api/finance/report',params={'from_date':'2027-01-01','to_date':'2027-01-01',**params})

    def test_period_totals_current_debts_archives_and_date_boundaries(self):
        start=int(datetime(2026,12,31,23,tzinfo=timezone.utc).timestamp())
        payment=self.pay().json()['id'];lesson=self.historic_lesson(status='completed');cancelled=self.historic_lesson(price=999999,status='cancelled')
        other=seed_user('Архивный','archive_report','Other password!')
        with database() as (c,p):
            c.execute('UPDATE payments SET created_at=? WHERE id=?',(start,payment))
            c.execute('UPDATE lessons SET ends_at=? WHERE id IN (?,?)',(start+3600,lesson,cancelled))
            c.execute('UPDATE users SET is_active=0 WHERE id=?',(other,))
            c.execute("INSERT INTO lessons (student_id,starts_at,ends_at,duration_minutes,price_kopecks,timezone,status,created_at) VALUES (?,?,?,45,300000,'UTC','completed',0)",(other,start-7200,start-3600))
        response=self.report();self.assertEqual(response.status_code,200,response.text)
        data=response.json();totals=data['totals']
        self.assertEqual(totals['received_kopecks'],800000);self.assertEqual(totals['earned_kopecks'],200000);self.assertEqual(totals['completed_lessons'],1)
        self.assertEqual(totals['debt_kopecks'],300000);self.assertEqual(totals['debtors_count'],1)
        filtered=self.report(debt_only='true').json();self.assertEqual(filtered['total'],1);self.assertEqual(filtered['items'][0]['id'],other);self.assertEqual(filtered['items'][0]['earned_kopecks'],0)
        self.assertEqual(self.report(state='active').json()['total'],1)
        self.assertEqual(self.report(search='archive_report').json()['totals'],totals)
        # An entry at the next local midnight is outside the inclusive day filter.
        with database() as (c,p):c.execute('UPDATE payments SET created_at=? WHERE id=?',(start+86400,payment))
        self.assertEqual(self.report().json()['totals']['received_kopecks'],0)

    def test_voided_payments_excluded_and_permissions_and_invalid_period(self):
        payment=self.pay().json()['id']
        with database() as (c,p):c.execute('UPDATE payments SET created_at=?,voided_at=1 WHERE id=?',(int(datetime(2027,1,1,12,tzinfo=timezone.utc).timestamp()),payment))
        self.assertEqual(self.report().json()['totals']['received_kopecks'],0)
        self.assertEqual(self.report(from_date='2027-01-02').status_code,422)
        self.client.post('/api/auth/logout',json={},headers=self.headers)
        self.assertEqual(self.report().status_code,401)
        self.client.post('/api/auth/login',json=self.data,headers=self.headers)
        self.assertEqual(self.report().status_code,403)

    def test_empty_report_and_pagination(self):
        for n in range(3):seed_user('Отчёт '+str(n),'report_'+str(n),'Other password!')
        data=self.report(limit=2,offset=2).json();self.assertEqual(data['total'],4);self.assertEqual(len(data['items']),2)
        self.assertEqual(data['totals']['received_kopecks'],0)
        self.assertEqual(self.report(search='nobody').json()['items'],[])
