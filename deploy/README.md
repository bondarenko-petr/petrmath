# Автоматическое обновление prosto5.ru

Цепочка: локальная проверка → Commit/Push → PR → Merge в `main` → GitHub Actions
(Python и JS тесты) → SSH → обновление точного коммита → перезапуск → HTTP/DB проверки.
При неудаче после остановки службы скрипт пытается восстановить предыдущий код и
Python-окружение, затем запустить службу. Откат БД не выполняется.

**До однократной настройки ничего автоматически не развёртывается.**
Переменная `PRODUCTION_DEPLOY_ENABLED` должна отсутствовать или быть `false`.
Сервер: Debian 12, `/srv/petrmath/app`, пользователь `petrmath`, служба
`petrmath.service`, Nginx и HTTPS уже настроены. В этом PR база и приложение не меняются.

## 1. Отдельный ключ (на Mac)

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/prosto5_deploy" -C "github-actions-prosto5"
```

Для unattended Actions оставьте passphrase пустой. Не заменяйте существующий ключ,
если файл с таким именем уже есть: выберите другое имя. Закрытый ключ — файл без
`.pub` — нужен только GitHub Secret, не чату, Git, приложению или серверу.
Передайте **публичную часть** на сервер:

```bash
scp "$HOME/.ssh/prosto5_deploy.pub" root@178.212.14.19:/root/prosto5-deploy.pub
```

## 2. Установка (сервер, root, после объединения PR)

Перед изменением версии закончите архивирование/работу с материалами и сохраните
обычную резервную копию MySQL и файлов. Если есть другие изменения SQL в новых PR,
сначала разберите их отдельно: не запускайте все файлы `sql/` подряд.

```bash
cd /srv/petrmath/app
runuser -u petrmath -- git status --short
```

Продолжайте только при пустом выводе:

```bash
runuser -u petrmath -- git pull --ff-only origin main
```

Проверьте `deploy/install.sh`, `deploy/deploy.sh`, `deploy/ssh-entry.sh`, затем:

```bash
bash deploy/install.sh /root/prosto5-deploy.pub
systemctl restart petrmath
curl -fsS https://prosto5.ru/api/health
```

Установщик ставит sudo, curl и util-linux, создаёт отдельную SSH-учётную запись
`prosto5-deploy`, root-owned forced-command wrapper и рабочий скрипт. SSH-ключ
не даёт shell, SFTP, туннелей или root-доступа: принимает только `deploy <SHA>`.
Развёртывание выполняется от `petrmath`; sudo разрешает этому пользователю только
stop/start/restart и read-only is-active своей службы. Существующая `.env` и материалы не копируются и
не заменяются. Учётная запись SSH не может редактировать ограничения своего ключа.
Повторный install заменит разрешённый ключ и установленные копии скриптов.

Скрипты в `/usr/local/libexec` обновляются только явным повторным запуском install
после проверки diff, а не автоматически из нового коммита.

## 3. Ключ сервера (защита от подключения к другому серверу)

В уже проверенном SSH-сеансе root получите публичный ключ сервера и отпечаток:

```bash
cat /etc/ssh/ssh_host_ed25519_key.pub
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Сверьте отпечаток с панелью провайдера/ранее проверенным SSH-ключом.
Сформируйте строку known_hosts: IP, пробел, затем **вся публичная строка ключа**:

```text
178.212.14.19 ssh-ed25519 AAAA...значение_с_сервера...
```

Это не закрытый ключ. Не используйте `StrictHostKeyChecking=no` и не доверяйте
одному непроверенному `ssh-keyscan`.

## 4. GitHub Settings

В репозитории откройте Settings → Secrets and variables → Actions.

Repository secrets:

- `DEPLOY_SSH_KEY`: весь файл `$HOME/.ssh/prosto5_deploy` с Mac, включая строки
  BEGIN/END. Скопируйте локально в буфер: `pbcopy < "$HOME/.ssh/prosto5_deploy"`.
- `DEPLOY_KNOWN_HOSTS`: строка из шага 3.

Repository variables:

- `DEPLOY_HOST` = `178.212.14.19`.
- `PRODUCTION_DEPLOY_ENABLED` = `true` **только когда остальные шаги готовы**.

Пароли MySQL/Gmail и `.env` в GitHub не нужны. Workflow использует окружение
`production`; при желании можно добавить reviewers и разрешить только ветку main
в Settings → Environments. Если review включён, обновление ждёт его.

## 5. Первый запуск

GitHub → Actions → Test and deploy → Run workflow → branch `main`.
Проверки должны стать зелёными. При первом запуске текущий коммит уже может быть
на сервере: сообщение `This commit is already deployed` нормально.
После этого каждое новое изменение в `main` запускает тесты и обновление автоматически.
Два обновления не выполняются параллельно; начатое не отменяется новым push.
Устаревший workflow не может откатить сервер на более ранний коммит.
PR и другие ветки только тестируются, не получают SSH secrets.

На сервере:

```bash
systemctl is-active petrmath
journalctl -u petrmath -n 30 --no-pager
runuser -u petrmath -- git -C /srv/petrmath/app rev-parse HEAD
```

Затем проверьте вход и изменённую функцию сайта. Health и простые DB-запросы
не заменяют функциональные проверки. Первый реальный deploy требует SSH/Secrets;
локальные тесты этой разработки их не используют.

## Когда обновление останавливается

- Локальные изменения в серверном checkout: устранить вручную, без `reset --hard`.
- SQL-файлы изменены: сделать backup, проверить миграцию и выполнить её вручную.
  Только для обратно совместимых миграций, после выполнения, root подтверждает
  **точный целевой SHA из Actions**:

  ```bash
  install -d -o root -g root -m 755 /etc/petrmath-deploy/migrations
  ```

  ```bash
  printf '%s\n' 'ЦЕЛЕВОЙ_40_СИМВОЛЬНЫЙ_SHA' > /etc/petrmath-deploy/migrations/ЦЕЛЕВОЙ_40_СИМВОЛЬНЫЙ_SHA
  chmod 644 /etc/petrmath-deploy/migrations/ЦЕЛЕВОЙ_40_СИМВОЛЬНЫЙ_SHA
  ```

  Это **не выполняет SQL**. Для несовместимой миграции остановить автообновление и
  провести обновление/восстановление отдельно: возврат кода не вернёт старую схему.
  Изменения схемы без изменения файлов `sql/` автоматически не распознаются — каждый
  PR с изменением схемы обязан включать миграцию. SQL-скрипты сами не запускаются.
- Архив строится или работает очистка: повторить после завершения, не начинать
  новые архивы во время обновления. Блокировка очистки удерживается до завершения.
- Осталось окружение после неудачной попытки: убедиться, что оно не является
  текущим (`readlink -f /srv/petrmath/app/.venv`), затем удалить **только каталог
  `/srv/petrmath/venvs/<SHA_неудачной_попытки>`** и повторить workflow. Старые рабочие
  окружения автоматически не удаляются, контролируйте свободное место на 30ГБ диске.
- Старые active archive jobs после аварии требуют проверки согласно разделу
  архивов в основном README; деплой не обходит такие статусы автоматически.

Остановка на start/restart кратковременная: это не zero-downtime deployment.
Зависимости устанавливаются до остановки сайта. Поскольку requirements пока не
содержит полного lock-файла, новый venv может получить более свежие транзитивные
версии; прежний venv сохраняется для отката.

Отключение: `PRODUCTION_DEPLOY_ENABLED=false`. Не отменяйте workflow посреди
остановки/смены версии; при аварийном kill проверьте службу вручную. Для отзыва
ключа удалите его строку из `/var/lib/prosto5-deploy/.ssh/authorized_keys`.
MySQL, материалы, OAuth-настройки и `.env` требуют самостоятельных защищённых
резервных копий: автодеплой не синхронизирует локальную базу и не заменяет backup.

### Минимальная Debian: Failed to connect to bus

Если deploy останавливается после Git fetch с `Failed to connect to bus: No such
file or directory`, SSH уже работает. На минимальной Debian у непривилегированного
пользователя может отсутствовать доступный system bus. Проверки is-active теперь
выполняются через sudo, как start/stop/restart; разрешена только точная команда
`/usr/bin/systemctl is-active --quiet petrmath.service`. После принятия исправления
обновите код и повторите `bash deploy/install.sh /root/prosto5-deploy.pub` под root:
нужны и обновлённый worker, и sudoers. Затем запустите новый workflow для main.
Не перезапускайте старый run с устаревшим SHA, если main уже изменился.
