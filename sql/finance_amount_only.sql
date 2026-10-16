-- Run as root after finance.sql. Back up the database first.
-- Keeps all existing payment amounts, package quantities and audit fields.
USE krug_pi;
ALTER TABLE payments MODIFY COLUMN lesson_count INT NULL DEFAULT NULL;
-- The existing CHECK (lesson_count > 0) permits NULL for money-only top-ups.
