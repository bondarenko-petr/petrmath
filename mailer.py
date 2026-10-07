"""Optional SMTP delivery; credentials are never logged or persisted here."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit
from pydantic import EmailStr, TypeAdapter


def send_student_credentials(recipient, name, username, password):
    required = ['SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM', 'SITE_URL']
    if any(not os.environ.get(key) for key in required):
        raise ValueError('Настройте SMTP и SITE_URL в .env перед отправкой')
    sender = str(TypeAdapter(EmailStr).validate_python(os.environ['SMTP_FROM']))
    base = os.environ['SITE_URL'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('SITE_URL должен быть HTTPS-адресом сайта без параметров')
    message = EmailMessage()
    message['Subject'] = 'Круг Пи — данные для входа в личный кабинет'
    message['From'] = sender
    message['To'] = str(TypeAdapter(EmailStr).validate_python(recipient))
    message.set_content(f'''Здравствуйте, {name}!

Преподаватель создал или обновил ваш доступ к сайту «Круг Пи».

Вход: {base}/account.html
Логин: {username}
Временный пароль: {password}

Это временный пароль. После входа сайт попросит заменить его вашим собственным паролем длиной от 10 символов. До смены пароля личный кабинет недоступен.
Не передавайте данные для входа другим людям. Если возникнут трудности, свяжитесь с преподавателем.

Круг Пи
''')
    mode = os.environ.get('SMTP_SECURITY', 'ssl')
    context = ssl.create_default_context()
    if mode == 'ssl':
        with smtplib.SMTP_SSL(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '465')), timeout=15, context=context) as smtp:
            smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            refused = smtp.send_message(message)
    elif mode == 'starttls':
        with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587')), timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            refused = smtp.send_message(message)
    else:
        raise ValueError('SMTP_SECURITY: используйте ssl или starttls')
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)
