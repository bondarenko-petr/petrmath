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
