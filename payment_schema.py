"""SQLite payment schema upgrade; preserves all rows and their original IDs."""
PAYMENTS_SCHEMA = """CREATE TABLE payments (
 id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
 student_id INTEGER NOT NULL REFERENCES users(id),
 amount_kopecks INTEGER NOT NULL CHECK(amount_kopecks>0),
 lesson_count INTEGER CHECK(lesson_count>0), note TEXT NOT NULL DEFAULT '',
 created_at INTEGER NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
 voided_at INTEGER, voided_by INTEGER REFERENCES users(id),
 void_reason TEXT NOT NULL DEFAULT '')"""


def ensure_payments(connection):
    connection.execute(PAYMENTS_SCHEMA.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
    columns = {row[1]:row for row in connection.execute('PRAGMA table_info(payments)')}
    if columns['lesson_count'][3]:
        connection.execute('BEGIN IMMEDIATE')
        try:
            # Another worker may have performed the upgrade while we waited.
            locked = {row[1]:row for row in connection.execute('PRAGMA table_info(payments)')}
            if locked['lesson_count'][3]:
                connection.execute(PAYMENTS_SCHEMA.replace('CREATE TABLE payments', 'CREATE TABLE payments_amount_upgrade', 1))
                names = 'id,request_id,student_id,amount_kopecks,lesson_count,note,created_at,created_by,voided_at,voided_by,void_reason'
                connection.execute(f'INSERT INTO payments_amount_upgrade ({names}) SELECT {names} FROM payments')
                connection.execute('DROP TABLE payments')
                connection.execute('ALTER TABLE payments_amount_upgrade RENAME TO payments')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    connection.execute('CREATE INDEX IF NOT EXISTS payments_student_created ON payments(student_id,created_at)')
