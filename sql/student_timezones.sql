-- Run as the database owner after student_management.sql. Safe to repeat.
USE krug_pi;
DROP PROCEDURE IF EXISTS migrate_student_timezones;
DELIMITER $$
CREATE PROCEDURE migrate_student_timezones()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='student_profiles' AND column_name='timezone') THEN
    ALTER TABLE student_profiles ADD COLUMN timezone VARCHAR(100) NULL;
  END IF;
END$$
DELIMITER ;
CALL migrate_student_timezones();
DROP PROCEDURE migrate_student_timezones;
