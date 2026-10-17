"""SQLite schema for teacher-authored lesson materials and private files."""
def ensure_materials(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS lesson_materials (
        lesson_id INTEGER PRIMARY KEY REFERENCES lessons(id),
        homework TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        due_mode TEXT NOT NULL DEFAULT 'next', due_date TEXT,
        version INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL,
        updated_by INTEGER NOT NULL REFERENCES users(id))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS material_files (
        id TEXT PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        category TEXT NOT NULL, storage_key TEXT NOT NULL UNIQUE,
        filename TEXT NOT NULL, media_type TEXT NOT NULL, size INTEGER NOT NULL,
        created_at INTEGER NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
        deleted_at INTEGER)""")
    connection.execute('CREATE INDEX IF NOT EXISTS material_files_lesson ON material_files(lesson_id,category,deleted_at)')
