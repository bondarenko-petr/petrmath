USE krug_pi;
CREATE TABLE IF NOT EXISTS account_links (
 token_hash CHAR(64) PRIMARY KEY,
 user_id BIGINT UNSIGNED NOT NULL,
 purpose VARCHAR(10) NOT NULL,
 email VARCHAR(254) NOT NULL,
 password_stamp CHAR(64) NOT NULL,
 expires_at BIGINT NOT NULL,
 created_at BIGINT NOT NULL,
 INDEX account_links_user (user_id,purpose),
 FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS verified_emails (
 user_id BIGINT UNSIGNED PRIMARY KEY,
 email VARCHAR(254) NOT NULL,
 password_stamp CHAR(64) NOT NULL,
 FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
GRANT SELECT, INSERT, DELETE ON krug_pi.account_links TO 'krug_pi_app'@'127.0.0.1';
GRANT SELECT, INSERT, DELETE ON krug_pi.verified_emails TO 'krug_pi_app'@'127.0.0.1';
