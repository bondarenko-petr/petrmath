-- Run the entire file as root after student_management.sql. Back up the DB first.
USE krug_pi;
CREATE TABLE IF NOT EXISTS lesson_schedule_lock (id TINYINT UNSIGNED PRIMARY KEY) ENGINE=InnoDB;
INSERT IGNORE INTO lesson_schedule_lock (id) VALUES (1);
CREATE TABLE IF NOT EXISTS lesson_series (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  timezone VARCHAR(100) NOT NULL,
  created_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS lessons (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  student_id BIGINT UNSIGNED NOT NULL,
  series_id BIGINT UNSIGNED NULL,
  starts_at BIGINT NOT NULL,
  ends_at BIGINT NOT NULL,
  duration_minutes INT UNSIGNED NOT NULL,
  price_kopecks BIGINT UNSIGNED NOT NULL,
  topic VARCHAR(300) NOT NULL DEFAULT '',
  meeting_url VARCHAR(2000) NOT NULL DEFAULT '',
  timezone VARCHAR(100) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
  created_at BIGINT NOT NULL,
  INDEX lessons_start (starts_at),
  INDEX lessons_student_start (student_id,starts_at),
  FOREIGN KEY (student_id) REFERENCES users(id),
  FOREIGN KEY (series_id) REFERENCES lesson_series(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
GRANT SELECT, UPDATE ON krug_pi.lesson_schedule_lock TO 'krug_pi_app'@'127.0.0.1';
GRANT SELECT, INSERT ON krug_pi.lesson_series TO 'krug_pi_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE ON krug_pi.lessons TO 'krug_pi_app'@'127.0.0.1';
