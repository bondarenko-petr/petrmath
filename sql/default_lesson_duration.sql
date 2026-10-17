-- Optional: align the database default for inserts without an explicit duration.
-- Existing profiles and scheduled lessons are unchanged.
USE krug_pi;
ALTER TABLE student_profiles ALTER COLUMN default_duration_minutes SET DEFAULT 45;
