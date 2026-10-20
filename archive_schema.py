"""SQLite schema; MySQL installation uses sql/material_archives.sql."""
def ensure_archives(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS material_archives (
        id TEXT PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_by INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
        status TEXT NOT NULL, filename TEXT NOT NULL, file_count INTEGER NOT NULL,
        lesson_count INTEGER NOT NULL, size INTEGER NOT NULL DEFAULT 0,
        sha256 TEXT NOT NULL DEFAULT '', drive_id TEXT NOT NULL DEFAULT '',
        drive_account TEXT NOT NULL DEFAULT '', manifest TEXT NOT NULL,
        error TEXT NOT NULL DEFAULT '')""")
    connection.execute('CREATE INDEX IF NOT EXISTS material_archives_student ON material_archives(student_id,created_at)')
    # Additive upgrade for existing local SQLite installations.
    columns={row[1] for row in connection.execute('PRAGMA table_info(material_archives)')}
    for name,sql in [('verified_at','INTEGER'),('notified_at','INTEGER'),('notified_email',"TEXT NOT NULL DEFAULT ''"),('cleanup_at','INTEGER'),('cleanup_error',"TEXT NOT NULL DEFAULT ''"),('purged_count','INTEGER NOT NULL DEFAULT 0')]:
        if name not in columns:connection.execute('ALTER TABLE material_archives ADD COLUMN '+name+' '+sql)
    if connection.execute("SELECT id FROM material_archives WHERE status='verified' AND verified_at IS NULL LIMIT 1").fetchone():
        connection.execute("UPDATE material_archives SET verified_at=updated_at WHERE status='verified' AND verified_at IS NULL")
    file_columns={row[1] for row in connection.execute('PRAGMA table_info(material_files)')}
    for name,sql in [('archive_id','TEXT'),('archived_at','INTEGER')]:
        if name not in file_columns:connection.execute('ALTER TABLE material_files ADD COLUMN '+name+' '+sql)
