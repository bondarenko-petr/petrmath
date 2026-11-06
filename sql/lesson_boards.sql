USE krug_pi;

CREATE TABLE IF NOT EXISTS lesson_boards (
    lesson_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    room_id CHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
) ENGINE=InnoDB;

GRANT SELECT, INSERT ON krug_pi.lesson_boards TO 'krug_pi_app'@'127.0.0.1';
