-- Run as database owner after student_management.sql; safe to repeat.
USE krug_pi;
DROP PROCEDURE IF EXISTS migrate_parent_contacts;
DELIMITER $$
CREATE PROCEDURE migrate_parent_contacts()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='student_profiles' AND column_name='parent_name') THEN
    ALTER TABLE student_profiles ADD COLUMN parent_name VARCHAR(100) NOT NULL DEFAULT '';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='student_profiles' AND column_name='parent_phone') THEN
    ALTER TABLE student_profiles ADD COLUMN parent_phone VARCHAR(40) NOT NULL DEFAULT '';
  END IF;
END$$
DELIMITER ;
CALL migrate_parent_contacts();
DROP PROCEDURE migrate_parent_contacts;
