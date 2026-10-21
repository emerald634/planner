# Mini App рядом с действующим Docker-ботом: подготовка к production

Актуальная инструкция этапа 2.1 — **STAGE2_1_RELEASE.md**. Ниже сохранена
инструкция предыдущего этапа 1; для нового релиза с очередью использовать
отдельные Dockerfiles, настройки, миграцию и откат из новой инструкции.

Команды ниже — инструкция для отдельного согласованного развёртывания.
На сервере они автоматически не выполнялись. Рабочий бот не требуется обновлять
или перезапускать: Mini App открывается кнопкой меню, настроенной через BotFather.

## Проверенные параметры VPS

Получены из присланных пользователем read-only команд:

| Параметр | Значение |
| --- | --- |
| Существующий бот | `bitrix-missed-calls-bot-bot-1`, Docker |
| Рабочая папка | `/opt/bitrix_missed_calls_bot`, владелец `bitrixbot` |
| Bind mount бота | `/opt/bitrix_missed_calls_bot/data` → `/data` |
| База доступа | `/opt/bitrix_missed_calls_bot/data/access.db` |
| Права базы / процесс бота | UID/GID `10001:10001`, файл `600`, journal mode `delete` |
| Вячеслав в старом боте | Администратор — подтверждено |
| Занятые локальные порты приложений | `8043`, `8080`, `8123` |
| HTTPS / HTTP | Уже работает host Nginx на `80/443`, IPv4 и IPv6 |
| Действующие сайты | `call.prav-buro.ru`, `lead.prav-buro.ru`, `pravburo-admin` |
| Mini App | Отдельный проект `bitrix-workday-planner`, порт `127.0.0.1:18080` |
| Домен Mini App | Пока `planner.example.com` — placeholder |

18080 был свободен в присланном выводе. Проверить снова непосредственно перед
запуском. Поддомен собственного домена подходит, например `plan.prav-buro.ru`,
но такое имя пока не утверждено, DNS и право на выпуск сертификата не проверены.

## Схема запуска

```text
Telegram → HTTPS:443 → существующий host Nginx, отдельный server_name
                            ↓ 127.0.0.1:18080
                 bitrix-workday-planner / planner
                    FastAPI + собранный React
                     ├─ /bot-data/access.db   READ ONLY
                     │   существующая /opt/bitrix_missed_calls_bot/data
                     └─ /planner-data/planner.db   READ/WRITE
                         /opt/bitrix_missed_calls_bot/planner-data

bitrix-missed-calls-bot-bot-1 продолжает свой прежний polling независимо.
```

В API-образе нет `bot.py`, aiogram или процесса polling. Передаются только
существующий BOT_TOKEN, ADMIN_TELEGRAM_IDS и параметры планировщика; Bitrix webhook
не передаётся в контейнер. Frontend не получает токен. `access.db` открывается
через SQLite `mode=ro`, вся исходная папка монтируется read-only. Это сохраняет
видимость текущих изменений `/adduser` и `/removeuser`.

SQLite хранится в отдельной постоянной папке, контейнер работает под `10001:10001`.
Read-only filesystem контейнера, `cap_drop: ALL`, `no-new-privileges`, лимиты
512 MiB / 1 CPU / 128 процессов и healthcheck предусмотрены в Compose.
Нет общего volume с PostgreSQL/Redis или портов этих приложений.

## Сотрудники и график

| Сотрудник | Telegram ID | Bitrix24 ID | Mini App |
| --- | --- | --- | --- |
| Вячеслав | 8306778724 | 460 | manager |
| Яна | 7939114214 | 110 | manager |
| Руководитель | 1073597301 | — | supervisor |

Вячеслав сохраняет существующее администрирование бота. Это не делает его
руководителем Mini App. Supervisor может назначать/редактировать задачи обоих
менеджеров, менять цели и плановое время, утверждать планы и запросы.

Новая база получает эти три записи. Миграция v1 → v2 заполняет только пустой
Telegram ID существующего manager с Bitrix24 ID 110. Заполненный ID, имя,
активность и другие записи сохраняются. Дубли не создаются. Занятый другим
сотрудником ID вызывает откат миграции. Несоответствия обнаружит `planner.ops`;
их нужно разобрать через интерфейс руководителя, не исправлять массовым SQL.
История, планы, фактические результаты и снимки закрытых дней сохраняются.

График: Europe/Moscow, 10:00–19:00. Он отображается в интерфейсе. Редактирование
после 19:00 разрешено; новые автоматические напоминания Mini App не включены.
Существующие напоминания распределения недозвонов относятся к прежнему боту.

Через существующего бота Вячеслав проверяет `/users`. Если доступа нет, выполняет
`/adduser 7939114214` и `/adduser 1073597301` в личном чате. Для роли supervisor
не нужно добавлять руководителя в ADMIN_TELEGRAM_IDS. Эти команды не отправлялись
автоматически; данные доступа в подготовке не менялись.

## 1. Собрать архив локально — PowerShell

```powershell
cd C:\Users\user\bitrix_missed_calls_bot
cd miniapp
pnpm install --frozen-lockfile
pnpm run build
cd ..
.\.venv\Scripts\python.exe deploy/package_release.py --output deployment-artifacts/planner-stage1-production-v3-prebuilt.tar.gz
```

Упаковщик самостоятельно повторяет `pnpm install --offline --frozen-lockfile`
и `pnpm run build`; успешная предыдущая сборка не заменяет эту проверку.
Если локального кеша недостаточно, сначала выполнить обычную установку выше.
Проверки безопасности pnpm сохраняются. Если pnpm отсутствует в PATH, передать
`--pnpm ПОЛНЫЙ_ПУТЬ_К_pnpm.cmd`. Ошибка сборки или неполный dist прекращает упаковку.
В архив входят готовые `miniapp/dist` и `frontend-build.json` с SHA256 файлов.
Manifest проверяется при сборке Docker и запуске production backend; frontend
исходники не передаются на VPS. Docker использует только Python, без Node/pnpm;
Python-зависимости по-прежнему устанавливаются из PyPI.

Получится новый файл в `deployment-artifacts/`. Список включаемых файлов
задан явно: нет `.env`, БД, `bot.py`, основного Compose/Dockerfile, демонстрации,
node_modules или клиентских карт исходников. Архив не заменяет существующий файл.

Передать **только этот архив**, подставив его настоящее имя и адрес VPS:

```powershell
scp .\deployment-artifacts\planner-stage1-production-v3-prebuilt.tar.gz root@IP_СЕРВЕРА:/tmp/
```

## 2. Проверить сервер повторно — только чтение

```bash
docker inspect bitrix-missed-calls-bot-bot-1 --format '{{.Id}} {{.State.StartedAt}} {{.State.Status}}'
docker ps --format 'table {{.Names}}\t{{.Ports}}'
ss -ltnp 'sport = :18080'
stat -c '%u:%g %a %n' /opt/bitrix_missed_calls_bot/data /opt/bitrix_missed_calls_bot/data/access.db
docker ps -a --filter label=com.docker.compose.project=bitrix-workday-planner --format '{{.Names}} {{.Status}}'
nginx -t
command -v certbot
```

Зафиксировать ID/StartedAt рабочего бота до и после операций. Свободный порт
не должен иметь LISTEN. Если проект `bitrix-workday-planner` уже существует,
выяснить его назначение перед запуском; чужой проект с таким именем не заменять.
`nginx -t` только проверяет действующие конфиги. Не публиковать `.env`, `docker
inspect .Config.Env` или полный `docker compose config`: они могут содержать токен.

## 3. Установить исходники отдельно внутри папки проекта

В SSH root после разрешения на развёртывание. Выбрать уникальные имя выпуска и
реальное имя архива. Все пути ниже относятся только к новой папке Mini App.

```bash
set -eu
planner_release=/opt/bitrix_missed_calls_bot/planner-releases/stage1-production-v3-prebuilt
planner_archive=/tmp/planner-stage1-production-v3-prebuilt.tar.gz
test -f "$planner_archive"
test ! -e "$planner_release"
tar -tzf "$planner_archive"
install -d -m 750 -o bitrixbot -g "$(id -gn bitrixbot)" "$planner_release"
chmod 644 "$planner_archive"
runuser -u bitrixbot -- tar -xzf "$planner_archive" -C "$planner_release"
cd "$planner_release"
test -f /opt/bitrix_missed_calls_bot/data/access.db
test -f /opt/bitrix_missed_calls_bot/.env
test ! -e deploy/planner.env
install -m 600 deploy/planner.env.example deploy/planner.env
```

Существующие исходники бота и его `.env` не копируются и не заменяются. Выпуск
Mini App располагается внутри текущей папки сервера в своей поддиректории.
Для последующих выпусков выбирать новые имя папки и тег PLANNER_IMAGE.

Проверить `deploy/planner.env`: подтверждённый путь базы, выбранный порт,
собственная папка данных и уникальный тег образа. В этом файле **нет секретов**.
Не указывать PLANNER_DATA_DIR равным `data/` или чужому каталогу.

Создать папку данных при первом запуске. Если она уже существует, проверить её
владельца и наличие прежнего planner.db; не создавать другую базу поверх неё.

```bash
if [ ! -e /opt/bitrix_missed_calls_bot/planner-data ]; then
  install -d -m 700 -o 10001 -g 10001 /opt/bitrix_missed_calls_bot/planner-data
fi
stat -c '%u:%g %a %n' /opt/bitrix_missed_calls_bot/planner-data
```

Нужны `10001:10001`, права `700`. Существующие `data/`, `access.db` и владельца
корневой папки не менять. SQLite нужны права записи **на папку**, включая journal.
Если planner.db уже есть, сделать его копию по разделу резервирования **до** первого
запуска новой версии и миграции. Прежний schema v1 образ нельзя запускать с v2 БД.

## 4. Проверить и запустить только Mini App

Каталог `stage1-production-v2` сохраняется. Новый тег:
`bitrix-workday-planner:stage1-production-v3-prebuilt`.
При обновлении сравнить PLANNER_DATA_DIR/ACCESS_DIR/PORT с прежним
`deploy/planner.env` без изменения прежнего файла. Использовать ту же папку
planner-data, иначе история останется в старой базе. Если база уже существует,
сначала выполнить резервное копирование из раздела 7.

Из папки нового выпуска, после явного разрешения:

```bash
export PLANNER_BOT_ENV_FILE=/opt/bitrix_missed_calls_bot/.env
sh deploy/planner-compose.sh config --quiet
sh deploy/planner-compose.sh build planner
sh deploy/planner-compose.sh run --rm --no-deps planner python -m planner.ops --access-only
sh deploy/planner-compose.sh up -d --no-deps --no-build planner
sh deploy/planner-compose.sh ps planner
sh deploy/planner-compose.sh exec -T planner python -m planner.ops
stat -c '%u:%g %a %n' /opt/bitrix_missed_calls_bot/planner-data/planner.db
curl --fail http://127.0.0.1:18080/healthz
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/api/me
```

Ожидается: healthy, readiness `{"status":"ok"}`, отсутствие авторизации — **401**,
новый planner.db принадлежит `10001:10001` и имеет права `600`,
`planner.ops` показывает всех трёх сотрудников с `binding_ok:true`,
`bot_access:true`, `ready:true`. Если доступа нет, исправить его через существующие
команды бота. Если путь, роли или права не соответствуют — остановить только
новую Mini App и исправить причину.

`planner.ops --access-only` — одноразовый контейнер только с read-only проверкой
файла доступа, без миграции и без открытого порта. `up` создаёт только API:
нет Telegram polling. Wrapper всегда указывает один Compose-файл и отдельный
проект, отказывает в команде `down`. Не применять основной compose.yaml как overlay,
не использовать `--remove-orphans`, Docker prune или остановку других приложений.
API без токена не выдаёт пользовательские данные; `/healthz` показывает только готовность.

Логи: `sh deploy/planner-compose.sh logs --tail=50 planner`.
Порт публикуется только на 127.0.0.1, порт контейнера 8000 не открыт наружу.
Backend принимает production initData с HMAC-проверкой и проверяет роль/владельца
каждого объекта. Preview не входит в production-сборку. Весь PostgreSQL/Redis стек
продолжает работать независимо.

## 5. HTTPS через существующий Nginx

При исправлении Docker-сборки этот раздел **не выполнять**: существующие
Nginx-конфигурации и HTTPS остаются без изменений. Ниже сохранена инструкция
только для отдельной первоначальной настройки HTTPS по согласованию.

Домен ниже — **пример**, заменить на утверждённый поддомен. A-запись должна
вести на VPS; AAAA добавлять только если IPv6 доступен и также ведёт на этот VPS.
Проверить DNS и отсутствие такого server_name в действующих конфигурациях.

```bash
getent ahosts planner.example.com
grep -R -n --fixed-strings 'planner.example.com' /etc/nginx/sites-enabled
```

В шаблонах два файла:
- `deploy/planner.nginx.http.example`: только ACME webroot, обычный HTTP отвечает 404;
- `deploy/planner.nginx.example`: HTTPS proxy на 127.0.0.1:18080 и HTTP → HTTPS redirect.

HTTP/HTTPS обслуживает **существующий host Nginx**, новый контейнер на 80/443 не
создаётся. Имя нового сайта — `bitrix-workday-planner`. Сначала отредактировать
локальную копию bootstrap-шаблона, подставив согласованный домен. Затем:

```bash
test ! -e /etc/nginx/sites-available/bitrix-workday-planner
test ! -e /etc/nginx/sites-enabled/bitrix-workday-planner
install -d -m 755 /var/www/bitrix-workday-planner-acme
install -m 644 deploy/planner.nginx.http.example /etc/nginx/sites-available/bitrix-workday-planner
ln -s /etc/nginx/sites-available/bitrix-workday-planner /etc/nginx/sites-enabled/bitrix-workday-planner
nginx -t && systemctl reload nginx
```

Если `nginx -t` не прошёл — **не reload**: убрать только новую ссылку, оставить
действующий Nginx и прежние сайты работающими. Перед Certbot убедиться, что
`/.well-known/acme-challenge/` на этом домене обслуживается именно новым сайтом.

Выпустить сертификат через **certonly webroot**, без автоматического редактирования
существующих Nginx-сайтов (Certbot должен быть доступен на сервере):

```bash
certbot certonly --webroot -w /var/www/bitrix-workday-planner-acme -d planner.example.com
```

Проверить выданные пути сертификата. В HTTPS-шаблоне заменить домен в server_name
и `/etc/letsencrypt/live/...`, сохранить bootstrap-конфигурацию этого **нового**
сайта в папке выпуска, затем заменить только его файл:

```bash
cp -n /etc/nginx/sites-available/bitrix-workday-planner ./planner-nginx-bootstrap.saved
install -m 644 deploy/planner.nginx.example /etc/nginx/sites-available/bitrix-workday-planner
nginx -t && systemctl reload nginx
curl --fail https://planner.example.com/healthz
curl -s -o /dev/null -w '%{http_code}\n' https://planner.example.com/api/me
```

Ответы: readiness OK, API 401. Если выбран другой PLANNER_PORT, изменить proxy_pass
только в шаблоне нового сайта. Проверить прежние сайты по их HTTPS-адресам и ID/
StartedAt рабочего бота. Убедиться, что общий firewall не изменялся и API-порт
не оказался публичным.

Для продления сертификата проверить уже существующий механизм Certbot (`systemctl
list-timers --all`), сначала тестировать **этот** сертификат:
`certbot renew --cert-name planner.example.com --dry-run`. После успешного
выпуска/продления сертификата Nginx требуется reload. В отдельном renewal deploy
hook можно использовать `nginx -t && systemctl reload nginx`; не заменять чужие
hooks и не создавать дублирующий cron. На этой подготовке расписания не создавались.

Webroot-подход сверён с [официальной документацией Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot).

## 6. Подключить к действующему боту через BotFather

После работоспособного публичного HTTPS:

1. [@BotFather](https://t.me/BotFather) → `/mybots` → действующий бот →
   **Bot Settings → Menu Button** (или `/setmenubutton`).
2. Текст `План дня`, URL `https://УТВЕРЖДЁННЫЙ_ДОМЕН/`.
3. При необходимости включить основную Mini App в профиле с тем же URL.
4. Проверить вход от Вячеслава, Яны и руководителя. Обычный браузер без Telegram
   получает приглашение открыть бот; API без initData — 401.

Меню работает с существующим токеном и не требует изменения `.env`, рестарта
контейнера, замены webhook или запуска ещё одного бота. Команда `/plan` и кнопка
в `/start` требуют обновлённого кода старого бота и MINI_APP_URL — это отдельная
возможная работа, **не часть данного развёртывания без изменений бота**.
Правила initData и Menu Button: [документация Telegram](https://core.telegram.org/bots/webapps).

## 7. Резервное копирование и проверка восстановления

Первая копия — до обновления/миграции уже существующего planner.db. Затем
рекомендуется ежедневная копия и копия перед каждым выпуском; сам график добавить
только после согласования. Начальный вариант хранения: 14 ежедневных и 4
еженедельных копии плюс отдельная копия перед миграцией. В этом этапе автоматическая
очистка не настроена, чтобы не удалить единственную нужную копию.

Резервирование работает через SQLite Backup API при запущенной Mini App, включает
планы, журнал и отчёты, проверяет integrity/foreign keys, создаёт SHA256. Не копировать
открытый planner.db обычным cp/scp. Источник открывается только для чтения.

На VPS из папки установленного выпуска (Python 3.12, дополнительных пакетов не нужно):

```bash
if [ ! -e /opt/bitrix_missed_calls_bot/planner-backups ]; then
  install -d -m 700 /opt/bitrix_missed_calls_bot/planner-backups
fi
python3 -m planner.backup create \
  --database /opt/bitrix_missed_calls_bot/planner-data/planner.db \
  --directory /opt/bitrix_missed_calls_bot/planner-backups
python3 -m planner.backup verify \
  --backup /opt/bitrix_missed_calls_bot/planner-backups/ИМЯ_КОПИИ.db
```

Если при откате меняли PLANNER_DATA_DIR, подставить в `--database` действительный
путь из env текущего выпуска, а не прежнюю папку с неудачной базой.

Каждая копия получает уникальное UTC-имя и права 600. Хранить `.db` и `.db.sha256`
вместе; дополнительно переносить зашифрованную копию на отдельное хранилище после
согласования. В архивы исходников базы и `.env` не входят.

Пробное восстановление — в новый пустой каталог, не в рабочую папку:

```bash
planner_restore=/opt/bitrix_missed_calls_bot/planner-restore-test-УНИКАЛЬНОЕ_ИМЯ
test ! -e "$planner_restore"
install -d -m 700 -o 10001 -g 10001 "$planner_restore"
python3 -m planner.backup restore \
  --backup /opt/bitrix_missed_calls_bot/planner-backups/ИМЯ_КОПИИ.db \
  --directory "$planner_restore"
chown 10001:10001 "$planner_restore/planner.db"
```

Существующий файл planner.db никогда не перезаписывается инструментом. Проверить
восстановленную копию и журналы, не переключая рабочий сервис во время такой проверки.

## 8. Откат

- Сбой при первом запуске: `sh deploy/planner-compose.sh stop planner`.
  Рабочий бот и другие контейнеры остаются работающими. Не удалять папку данных.
- Сбой HTTPS: если новый конфиг ещё не применился, восстановить сохранённый файл
  **только нового** сайта, проверить `nginx -t`; текущий Nginx не перезапускать.
  Если нужно убрать Mini App, удалить только ссылку
  `/etc/nginx/sites-enabled/bitrix-workday-planner`, `nginx -t` и reload.
- Для обновлений заранее хранить предыдущую папку выпуска, тег образа,
  `deploy/planner.env` и резервную копию непосредственно перед миграцией.
- Если схема совместима, остановить только planner, перейти в прежнюю папку
  выпуска, убедиться в прежнем теге образа и запустить её wrapper с `up -d
  --no-deps --no-build planner`. Не использовать прежний код v1 с БД v2.
- При несовместимой схеме восстановить соответствующую старому коду копию в
  **новую** папку `planner-data-rollback-УНИКАЛЬНОЕ_ИМЯ` через проверяемый инструмент.
  Установить владельца файла/каталога 10001:10001; в env прежнего выпуска изменить
  только PLANNER_DATA_DIR на эту папку. Остановить текущий planner и запустить
  старый образ из прежней папки. Не пересобирать старый образ из нового кода.
- Сохранить неудачную БД отдельно для разбора и переноса новых данных: восстановление
  старой копии не включает записи после её создания. Access.db не восстанавливается
  и не заменяется при откате Mini App.

После отката повторить healthz, API 401, роль/доступ, проверку истории/отчётов и
работу старого распределения. Меню BotFather на время устранения ошибки можно
отключить вручную, не меняя бот-токен.

## Проверки перед публикацией

Повторная проверка из корня проекта в PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-planner.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
cd miniapp
pnpm install --frozen-lockfile
pnpm run build
```

Для UI-теста запустить отдельный `python -m tests.planner_browser_server` из корня,
затем `node tests/ui.cjs` из miniapp (на Windows с Edge установить
`$env:PLAYWRIGHT_CHANNEL='msedge'`). Этот сервер использует временную БД и тестовый
токен; он не читает рабочую `.env`. Перед повторным UI-тестом перезапустить только
его, чтобы получить чистую временную базу.

Локально выполняются Python-тесты и сборка frontend; браузерный тест использует
только временные базы и искусственный токен с реальной HMAC-проверкой.
Docker на рабочей Windows-машине отсутствует: production-образ нужно собрать
и проверить на VPS после разрешения. Успешные локальные тесты не подтверждают
DNS, сертификат, Nginx-конфигурацию на сервере или доступ с Telegram-клиентов.

Статистика Bitrix24 на этом этапе не синхронизируется. Изменения backend относятся
к миграции пользователя, рабочему графику, готовности и эксплуатационным средствам;
распределение недозвонов и исходники старого бота не меняются.
