-- Run as root after lessons.sql. Back up the DB first. Existing completed lessons
-- count as expenses; enter earlier payments to reconcile opening balances.
USE krug_pi;
CREATE TABLE IF NOT EXISTS payments (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  request_id CHAR(36) NOT NULL UNIQUE,
  student_id BIGINT UNSIGNED NOT NULL,
  amount_kopecks BIGINT NOT NULL,
  lesson_count INT NOT NULL,
  note VARCHAR(300) NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  created_by BIGINT UNSIGNED NOT NULL,
  voided_at BIGINT NULL,
  voided_by BIGINT UNSIGNED NULL,
  void_reason VARCHAR(300) NOT NULL DEFAULT '',
  INDEX payments_student_created (student_id,created_at),
  FOREIGN KEY (student_id) REFERENCES users(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  FOREIGN KEY (voided_by) REFERENCES users(id),
  CHECK (amount_kopecks > 0),
  CHECK (lesson_count > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
GRANT SELECT, INSERT, UPDATE ON krug_pi.payments TO 'krug_pi_app'@'127.0.0.1';
