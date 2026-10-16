-- Run as root after mysql.sql and accounts.sql. Back up the database first.
-- Request contents stay unchanged. Existing requests are shown as new.
USE krug_pi;
CREATE TABLE IF NOT EXISTS trial_request_management (
  request_id BIGINT UNSIGNED PRIMARY KEY,
  status VARCHAR(24) NOT NULL DEFAULT 'new',
  admin_note TEXT NOT NULL,
  close_reason VARCHAR(24) NOT NULL DEFAULT '',
  version INT UNSIGNED NOT NULL DEFAULT 1,
  updated_at BIGINT NOT NULL,
  updated_by BIGINT UNSIGNED NOT NULL,
  INDEX trial_management_status (status,request_id),
  FOREIGN KEY (request_id) REFERENCES trial_requests(id),
  FOREIGN KEY (updated_by) REFERENCES users(id),
  CHECK (status IN ('new','contacting','trial_scheduled','enrolled','closed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
GRANT SELECT, UPDATE ON krug_pi.trial_requests TO 'krug_pi_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE ON krug_pi.trial_request_management TO 'krug_pi_app'@'127.0.0.1';
