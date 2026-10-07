-- Run the entire file as root AFTER accounts.sql. Existing accounts retain email as login.
USE krug_pi;
DROP PROCEDURE IF EXISTS migrate_student_management;
DELIMITER $$
CREATE PROCEDURE migrate_student_management()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='users' AND column_name='username') THEN
    ALTER TABLE users ADD username VARCHAR(254) NULL, ADD must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
      ADD is_active BOOLEAN NOT NULL DEFAULT TRUE, ADD created_at BIGINT NOT NULL DEFAULT 0, ADD password_changed_at BIGINT NULL;
    UPDATE users SET username=LOWER(email);
    ALTER TABLE users MODIFY username VARCHAR(254) NOT NULL, ADD UNIQUE KEY uq_users_username (username);
  END IF;
  ALTER TABLE users MODIFY email VARCHAR(254) NULL;
END$$
DELIMITER ;
CALL migrate_student_management();
DROP PROCEDURE migrate_student_management;
CREATE TABLE IF NOT EXISTS student_profiles (
  user_id BIGINT UNSIGNED PRIMARY KEY,
  phone VARCHAR(40) NOT NULL DEFAULT '',
  school_grade TINYINT UNSIGNED NULL,
  default_price_kopecks BIGINT UNSIGNED NOT NULL DEFAULT 0,
  default_duration_minutes INT UNSIGNED NOT NULL DEFAULT 60,
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
INSERT IGNORE INTO student_profiles (user_id) SELECT id FROM users WHERE role='student';
GRANT SELECT, INSERT, UPDATE ON krug_pi.users TO 'krug_pi_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE ON krug_pi.student_profiles TO 'krug_pi_app'@'127.0.0.1';
