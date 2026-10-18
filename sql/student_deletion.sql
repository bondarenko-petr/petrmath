-- Run as database owner. Grants required for permanent student deletion.
USE krug_pi;
GRANT DELETE ON krug_pi.users TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.student_profiles TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.sessions TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.lessons TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.lesson_series TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.payments TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.lesson_materials TO 'krug_pi_app'@'127.0.0.1';
GRANT DELETE ON krug_pi.material_files TO 'krug_pi_app'@'127.0.0.1';
