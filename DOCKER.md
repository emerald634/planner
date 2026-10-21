# Перенос на Docker Compose: Ubuntu 24.04

## Обновление уже работающего Docker-бота

В PowerShell на компьютере передайте исходники, включая `reminders.py`, обновлённые
`Dockerfile` и `.dockerignore` (иначе новый модуль не попадёт в образ):

```powershell
cd C:\Users\user\bitrix_missed_calls_bot
scp .\*.py .\requirements.txt .\Dockerfile .\compose.yaml .\.dockerignore root@IP_СЕРВЕРА:/opt/bitrix_missed_calls_bot/
```

На сервере добавьте/обновите только эти строки в существующем `.env`:

```env
INCONVENIENT_STAGE_ID=PROCESSED
UNPROCESSED_STAGE_ID=NEW
```

Имя «Женя» автоматически отображается как «Евгений»; при желании обновите и строку
соответствующего `MANAGER_N_NAME`. Затем в SSH-терминале:

```bash
cd /opt/bitrix_missed_calls_bot
docker compose up -d --build --force-recreate
docker compose logs --tail=50 bot
```

SQLite обновит структуру автоматически, сохранив пользователей. `data/access.db`
и серверный `.env` не заменяйте локальными копиями. Для напоминания в выбранной группе
администратор должен выполнить `/reminders_on@имя_бота`; в личных чатах пользователей
с доступом напоминания включаются автоматически. Полные правила описаны в README.

## Первоначальный перенос с systemd

Команды ниже предназначены для сервера, на котором проект уже находится в
`/opt/bitrix_missed_calls_bot`. SSH-пользователь — `root`. PowerShell на компьютере
используется только в шаге копирования файлов. Если команда завершилась ошибкой,
разберите её перед переходом к следующему шагу.

## 1. Проверка Docker — на сервере

```bash
docker --version
docker compose version
```

Если обе команды работают, перейдите к шагу 2. Если Docker отсутствует, установите
его по [официальной инструкции для Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
Для новой установки на Ubuntu 24.04 под root:

```bash
apt update
apt install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker --version
docker compose version
```

Если уже установлен Docker из другого источника или работают другие контейнеры,
не удаляйте пакеты автоматически: сначала проверьте существующую установку.

## 2. Передача обновлённого кода — в Windows PowerShell

Замените `IP_СЕРВЕРА` адресом VPS. Команда переносит только исходники и файлы Docker.
Существующие серверные `.env` и `access.db` остаются на месте.

```powershell
cd C:\Users\user\bitrix_missed_calls_bot
scp .\*.py .\requirements.txt .\Dockerfile .\compose.yaml .\.dockerignore root@IP_СЕРВЕРА:/opt/bitrix_missed_calls_bot/
```

Не копируйте Windows-папку `.venv`; зависимости устанавливаются внутри образа.

## 3. Сборка — на сервере

```bash
cd /opt/bitrix_missed_calls_bot
docker compose config --quiet
docker compose build
```

Сборка не запускает бота. Используйте `config --quiet`: обычный `docker compose config`
может вывести значения из `.env`. Код читает настройки из окружения контейнера;
сам `.env` в образ не копируется.

## 4. Остановка старого бота и перенос базы — на сервере

Остановите локального бота на компьютере, если он ещё запущен. На VPS:

```bash
systemctl disable --now bitrix-missed-calls-bot
systemctl is-active bitrix-missed-calls-bot
```

Последняя команда должна показать `inactive` и вернуть ненулевой код — здесь это
нормально. Если служба ранее не создавалась, убедитесь, что не работает ручной запуск
`python bot.py`. Один токен должен обслуживаться одним экземпляром бота.

Следующий блок создаёт согласованную копию SQLite в `data/access.db` и резервную копию
в `backups`. Он читает текущую **серверную** базу, не изменяет её и отказывается
перезаписывать уже существующую базу Docker. Скопируйте весь блок, включая `PY`:

```bash
cd /opt/bitrix_missed_calls_bot
python3 - <<'PY'
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

source = Path("access.db")
target = Path("data/access.db")
if not source.is_file():
    raise SystemExit("Исходная access.db не найдена. Проверьте папку проекта.")
if target.exists():
    raise SystemExit("data/access.db уже существует. Перенос остановлен, база не перезаписана.")
target.parent.mkdir(mode=0o700, exist_ok=True)
Path("backups").mkdir(mode=0o700, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
backup = Path("backups") / f"access-before-docker-{stamp}.db"
with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
    count = original.execute("SELECT COUNT(*) FROM allowed_users").fetchone()[0]
    for path in (backup, target):
        path.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(path)) as destination:
            original.backup(destination)
print(f"База перенесена. Пользователей в таблице: {count}. Резервная копия: {backup}")
PY
```

Продолжайте после сообщения «База перенесена». Если база уже существует от предыдущего
успешного переноса, используйте её; не заменяйте её старой копией. При сбое во время
копирования не запускайте контейнер до проверки копии.

Задайте права для пользователя контейнера UID/GID 10001:

```bash
chown 10001:10001 data data/access.db
chmod 700 data
chmod 600 data/access.db .env
```

## 5. Проверка и запуск — на сервере

Проверка настроек, целостности и записи в базу без подключения к Telegram/Bitrix24:

```bash
docker compose run --rm --no-deps bot python -c 'import sqlite3; from contextlib import closing; from config import load_config; c = load_config(); print("Configuration OK"); db = sqlite3.connect(c.access_db_path); print("SQLite:", db.execute("PRAGMA quick_check").fetchone()[0]); db.execute("BEGIN IMMEDIATE"); db.rollback(); print("Users:", db.execute("SELECT COUNT(*) FROM allowed_users").fetchone()[0]); db.close()'
```

Ожидается `Configuration OK`, `SQLite: ok` и то же количество записей, что при переносе.
При успешной проверке:

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=50 bot
```

Проверьте `/start`, `/users` от администратора и распределение в Telegram.
Статус `Up` подтверждает работу процесса; реальную связь с API проверяют логи и команды
в Telegram. При запуске сохраняется правило повторного импорта `ALLOWED_TELEGRAM_IDS`.

После проверки можно закрыть SSH и выключить компьютер. Настройка
[`restart: unless-stopped`](https://docs.docker.com/reference/compose-file/services/#restart)
перезапускает контейнер после сбоя и запуска Docker, если его не остановили вручную.
Docker должен быть включён через `systemctl enable --now docker`.

## Управление — на сервере из папки проекта

```bash
cd /opt/bitrix_missed_calls_bot
```

| Действие | Команда |
| --- | --- |
| Остановить | `docker compose stop` |
| Запустить | `docker compose up -d` |
| Перезапустить | `docker compose restart` |
| Применить изменения `.env` | `docker compose up -d --force-recreate` |
| Обновить после загрузки кода | `docker compose up -d --build` |
| Проверить состояние | `docker compose ps` |
| Смотреть логи | `docker compose logs --tail=100 -f bot` |

`Ctrl+C` в окне просмотра логов завершает только просмотр. После изменения `.env`
нужно пересоздание контейнера: обычный `restart` не перечитывает `env_file`.

После перехода актуальный список доступа находится **только в `data/access.db`**;
исходная `access.db` больше не обновляется. Пересоздание контейнера не удаляет `data`.
При обновлении кода не заменяйте папки `data`, `backups` и серверный `.env` локальными копиями.
Для резервного копирования остановите контейнер, скопируйте папку `data` целиком
в защищённое место, затем запустите контейнер снова.

Для возврата к systemd сначала остановите контейнер. Укажите в серверном `.env`
`ACCESS_DB_PATH=/opt/bitrix_missed_calls_bot/data/access.db`, передайте владельца папки
`data` и её файлов пользователю `bitrixbot`, затем включите прежнюю службу.
Так systemd будет использовать актуальную базу. Два экземпляра одновременно не запускайте.

## Устройство контейнера

- Python 3.12, зависимости из `requirements.txt`, запуск без root (UID/GID 10001).
- `.dockerignore` разрешает передавать в сборку только явно перечисленные исходники.
- `.env` передаётся через `env_file`; секреты не включаются в слои образа.
- `/data` — постоянная папка с SQLite и её служебными файлами. Монтируется папка,
  чтобы SQLite могла создавать журнал рядом с базой.
- `ACCESS_DB_PATH=/data/access.db` задаётся Compose; обычный запуск без этой переменной
  по-прежнему использует `access.db` рядом с исходниками.
- Корневая файловая система контейнера доступна только для чтения, `/tmp` — временный.
- Логи ограничены тремя файлами по 10 МБ. Порты не публикуются: бот использует polling.
