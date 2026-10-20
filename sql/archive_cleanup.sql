USE krug_pi;
-- Add columns idempotently; run as the database administrator.
DROP PROCEDURE IF EXISTS upgrade_archive_cleanup;
DELIMITER //
CREATE PROCEDURE upgrade_archive_cleanup()
BEGIN
 IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='material_archives' AND column_name='verified_at') THEN
  ALTER TABLE material_archives ADD verified_at BIGINT NULL;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='material_archives' AND column_name='notified_at') THEN
  ALTER TABLE material_archives ADD notified_at BIGINT NULL, ADD notified_email VARCHAR(254) NOT NULL DEFAULT '', ADD cleanup_at BIGINT NULL, ADD cleanup_error VARCHAR(500) NOT NULL DEFAULT '', ADD purged_count INT NOT NULL DEFAULT 0;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='material_files' AND column_name='archive_id') THEN
  ALTER TABLE material_files ADD archive_id CHAR(32) NULL, ADD archived_at BIGINT NULL;
 END IF;
 UPDATE material_archives SET verified_at=updated_at WHERE status='verified' AND verified_at IS NULL;
END//
DELIMITER ;
CALL upgrade_archive_cleanup();
DROP PROCEDURE upgrade_archive_cleanup;
