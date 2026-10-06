# Круг Пи

Сайт «Круг Пи»: занятия по математике и подготовка к ОГЭ и ЕГЭ.
Сервер — Python + FastAPI, интерфейс — HTML, CSS и JavaScript.

Доступен REST API `GET /api/health`. Вход, регистрация и учебные материалы
показывают статус разработки. Заявки сохраняются через `POST /api/trial-requests` в SQLite.

## Первый запуск в PyCharm

1. После слияния Pull Request клонируйте репозиторий через
   **Get from Version Control** или **Git → Clone**:
   `https://github.com/bondarenko-petr/petrmath.git`.
   Выберите новую пустую папку, например `PycharmProjects/petrmath`.
   Существующий проект `math-website` можно сохранить отдельно.
2. Создайте виртуальное окружение `.venv` в корне клонированного проекта
   и выберите его Python-интерпретатор в настройках PyCharm.
3. В Terminal из корня проекта установите зависимости:

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```

4. Откройте `run.py` и выберите **Run 'run'**.
5. Откройте http://127.0.0.1:8000/.

Проверка сервера: http://127.0.0.1:8000/api/health.
Интерактивная документация API: http://127.0.0.1:8000/docs.

Остановка — кнопка Stop. Изменения Python-кода перезапускают сервер.
После правок HTML/CSS/JavaScript обновите страницу браузера.
Если порт 8000 занят, остановите прежний сервер или измените порт в `run.py`.

## Запуск через Terminal

На macOS/Linux из корня проекта:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Если окружение уже создано, первую команду пропустите.
Остановка — Ctrl+C. Сервер предназначен для локальной разработки.

## Как получать изменения

Изменения публикуются в отдельных ветках `codex/...` через Pull Request.
Проверьте Pull Request на GitHub и выполните **Merge**, когда готовы принять его.
Затем из корня локального клона на ветке `main`:

```bash
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements.txt
```

Перед обновлением сохраните собственные изменения коммитом или через Git Stash.
Если обновление не может выполниться без слияния, Git остановится:
не удаляйте свои правки, сначала разберите расхождения.
Перезапустите сервер после обновления зависимостей.

## Файлы

- `main.py` — приложение FastAPI и маршруты REST API.
- `run.py` — запуск для PyCharm.
- `requirements.txt` — зависимости.
- `landing/dist/` — HTML, CSS и JavaScript лендинга.
- `REQUIREMENTS.md` — требования к будущей системе.

Маршруты `/api/...` добавляйте до `app.mount("/", ...)` в `main.py`.
Сайт и API используют один адрес; JavaScript может обращаться к `/api/...`.

## Лендинг из архива web-master

Основа главной страницы перенесена из предоставленного архива web-master.
Название и векторный логотип обновлены на «Круг Пи», содержание адаптировано
для математики, ОГЭ и ЕГЭ.
`landing/dist/assets/css/` содержит исходные стили Nicepage и страницы,
`styles.css` — адаптацию навигации и узких экранов, `script.js` — локальные
интерактивные элементы. Вход, регистрация и учебные материалы показывают
статус разработки; форма заявки подключена к REST API.
Контактные ссылки взяты из оригинальной страницы. Содержимое архива не
меняет требования к будущему MVP: услуги и контакты требуют отдельного
согласования перед публичным запуском.

## Заявки на пробный урок

Форма сохраняет имя, email, телефон, выбранные направления, комментарий,
согласие и время заявки в `data/trial_requests.sqlite3`. База создаётся
автоматически и исключена из Git. Перезапуск сервера не удаляет заявки.
Уведомления на почту или в Telegram не отправляются.

Просмотреть заявки локально можно в SQLite-клиенте (например, DB Browser for SQLite)
или через Terminal:

```bash
sqlite3 -header -column data/trial_requests.sqlite3 'SELECT * FROM trial_requests ORDER BY id DESC;'
```

База находится вне публичного каталога сайта. Переменная `TRIAL_REQUESTS_DB`
позволяет выбрать другой путь к базе, например на постоянном диске сервера.

## Подключение MySQL локально

Интеграция использует официальный MySQL Connector/Python:
https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html

1. Установите MySQL Community Server с https://dev.mysql.com/downloads/mysql/
   и запустите сервер. Для удобного просмотра таблиц можно установить MySQL Workbench.
2. Обновите зависимости проекта:

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. В MySQL Workbench подключитесь локально как администратор и выполните
   содержимое `sql/mysql.sql`: появятся база `krug_pi` и таблица `trial_requests`.
4. Создайте отдельного пользователя приложения. Замените пример пароля своим:

   ```sql
   CREATE USER 'krug_pi_app'@'127.0.0.1' IDENTIFIED BY 'replace_with_your_password';
   GRANT INSERT, SELECT ON krug_pi.trial_requests TO 'krug_pi_app'@'127.0.0.1';
   ```

5. Скопируйте `.env.example` в `.env` в корне проекта:

   ```bash
   cp .env.example .env
   ```

   Укажите `MYSQL_PASSWORD` и, при необходимости, остальные параметры.
   `.env` автоматически читается при запуске и исключён из Git.
   Настройки окружения PyCharm имеют приоритет над `.env`.
6. Перезапустите `run.py`, отправьте заявку и проверьте её в Workbench:

   ```sql
   SELECT * FROM krug_pi.trial_requests ORDER BY id DESC;
   ```

Без настройки `DB_BACKEND` сайт продолжает использовать SQLite.
С `DB_BACKEND=mysql` ошибки MySQL возвращают HTTP 503: незаметного переключения
на SQLite нет. Старые заявки SQLite не удаляются и автоматически не переносятся.
Файл `sql/mysql.sql` создаёт таблицу заранее: приложение не требует прав CREATE.
После подключения MySQL данные хранятся на сервере MySQL, а не в файле SQLite.
