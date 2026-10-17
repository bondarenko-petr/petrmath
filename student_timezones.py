"""Display timezone preferences; lesson instants remain UTC."""
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def validate_zone(value):
    if value is None or value == '':
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('Выберите действующий часовой пояс IANA')
    return value

def student_zone(cursor, placeholder, student_id):
    cursor.execute(f'SELECT timezone FROM student_profiles WHERE user_id={placeholder}', (student_id,))
    row = cursor.fetchone()
    return (row['timezone'] if row else None) or os.environ.get('LESSON_TIMEZONE', 'Europe/Moscow')
