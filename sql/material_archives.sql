USE krug_pi;
CREATE TABLE IF NOT EXISTS material_archives (
 id CHAR(32) PRIMARY KEY,
 student_id BIGINT UNSIGNED NOT NULL,
 created_by BIGINT UNSIGNED NOT NULL,
 created_at BIGINT NOT NULL,
 updated_at BIGINT NOT NULL,
 status VARCHAR(20) NOT NULL,
 filename VARCHAR(200) NOT NULL,
 file_count INT NOT NULL,
 lesson_count INT NOT NULL,
 size BIGINT NOT NULL DEFAULT 0,
 sha256 CHAR(64) NOT NULL DEFAULT '',
 drive_id VARCHAR(200) NOT NULL DEFAULT '',
 drive_account VARCHAR(254) NOT NULL DEFAULT '',
 manifest MEDIUMTEXT NOT NULL,
 error VARCHAR(500) NOT NULL DEFAULT '',
 INDEX material_archives_student (student_id,created_at),
 FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
GRANT SELECT, INSERT, UPDATE, DELETE ON krug_pi.material_archives TO 'krug_pi_app'@'127.0.0.1';
