-- Run as root after lessons.sql. Back up the database first.
USE krug_pi;
CREATE TABLE IF NOT EXISTS lesson_materials (
  lesson_id BIGINT UNSIGNED PRIMARY KEY,
  homework MEDIUMTEXT NOT NULL,
  notes MEDIUMTEXT NOT NULL,
  due_mode VARCHAR(8) NOT NULL DEFAULT 'next',
  due_date DATE NULL,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  updated_at BIGINT NOT NULL,
  updated_by BIGINT UNSIGNED NOT NULL,
  FOREIGN KEY (lesson_id) REFERENCES lessons(id),
  FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS material_files (
  id CHAR(32) PRIMARY KEY,
  lesson_id BIGINT UNSIGNED NOT NULL,
  category VARCHAR(8) NOT NULL,
  storage_key VARCHAR(40) NOT NULL UNIQUE,
  filename VARCHAR(200) NOT NULL,
  media_type VARCHAR(40) NOT NULL,
  size INT UNSIGNED NOT NULL,
  created_at BIGINT NOT NULL,
  created_by BIGINT UNSIGNED NOT NULL,
  deleted_at BIGINT NULL,
  INDEX material_files_lesson (lesson_id,category,deleted_at),
  FOREIGN KEY (lesson_id) REFERENCES lessons(id),
  FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
GRANT SELECT, INSERT, UPDATE ON krug_pi.lesson_materials TO 'krug_pi_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE ON krug_pi.material_files TO 'krug_pi_app'@'127.0.0.1';
-- Parent-row locks used by uploads and edits need UPDATE permission (already
-- granted by lessons.sql). File content is stored outside the public directory.
