-- Run as root. Replace the email below with your registered site account.
USE krug_pi;
UPDATE users SET role='admin' WHERE email='REPLACE_WITH_YOUR_EMAIL';
SELECT id,name,email,role FROM users WHERE email='REPLACE_WITH_YOUR_EMAIL';
