# Этап 2.1 — stage2-1-production-v1

Подготовка локально; ни одна команда ниже не выполнена на VPS.
Применять только после отдельного разрешения. Никаких общих compose down,
prune, --remove-orphans, обновления Nginx или чужих контейнеров.

## Состав и версии

Один отдельный архив planner-stage2-1-production-v1.tar.gz содержит оба компонента,
prebuilt React, отдельные Dockerfiles, Compose, документацию и инструменты.
Bot image: bitrix-missed-calls-bot:stage2-1-production-v1.
Mini App image: bitrix-workday-planner:stage2-1-production-v1.
Planner schema: **4**, миграция 2→3→4; queue schema: **1**.
Ранее в ТЗ указана 2→3, но в части 4 добавлена диагностика попыток схемы 4.
Предыдущий stage1-production-v3-prebuilt остаётся в своей папке и со своим тегом.

Изменения этапа: подтверждение выбранного распределения, явные полномочия,
снимок ID/дат IN_PROCESS, отдельная очередь, атомарный импорт, manager confirm,
защищённые цели, системный аудит, review UI, фоновая синхронизация.
Корневые Dockerfile/compose.yaml старого бота не заменяются: новый бот собирается
по deploy/Bot.Dockerfile, обновляется через compose.bot.release.yaml с прежним
project/service именем bitrix-missed-calls-bot/bot. Отдельный Mini App project
bitrix-workday-planner, только 127.0.0.1:18080.

## Локальная упаковка Windows

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
.\.venv\Scripts\python.exe deploy/package_release.py --stage2 --output deployment-artifacts/planner-stage2-1-production-v1.tar.gz
Get-FileHash .\deployment-artifacts\planner-stage2-1-production-v1.tar.gz -Algorithm SHA256
scp .\deployment-artifacts\planner-stage2-1-production-v1.tar.gz root@IP_СЕРВЕРА:/tmp/
scp .\deployment-artifacts\planner-stage2-1-production-v1.tar.gz.sha256 root@IP_СЕРВЕРА:/tmp/
```

Упаковщик требует pnpm в PATH (или --pnpm полный путь), выполняет offline frozen
install и production build. Проверки зависимостей не отключены. Docker не
устанавливает Node/pnpm; Python-зависимости по-прежнему скачиваются из PyPI.
В архиве только allowlist: нет рабочих .env/SQLite/node_modules/maps/клиентских
данных. release-files.json содержит SHA256 всех файлов; frontend-build.json
отдельно проверяется Dockerfile и backend. Файл SHA256 архива хранить отдельно.

## 1. Сначала только чтение на сервере

```bash
docker inspect bitrix-missed-calls-bot-bot-1 --format '{{.Id}} {{.Config.Image}} {{.Image}} {{.State.StartedAt}} {{json .Mounts}} {{json .Config.Labels}}'
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
docker ps -a --filter label=com.docker.compose.project=bitrix-workday-planner --format '{{.Names}} {{.Image}} {{.Status}}'
df -h /opt /tmp
ss -ltnp 'sport = :18080'
stat -c '%u:%g %a %n' /opt/bitrix_missed_calls_bot/data/access.db /opt/bitrix_missed_calls_bot/planner-data
docker exec bitrix-missed-calls-bot-bot-1 python -c 'import os,json; print(json.dumps({k:os.getenv(k,"") for k in ("MANAGER_1_NAME","MANAGER_2_NAME","MANAGER_3_NAME")},ensure_ascii=False))'
```

18080 уже может принадлежать текущей Mini App — это ожидаемо. Если порт принадлежит
другому приложению, остановиться. Проверить project label именно старого бота;
если имя отличается, wrapper не запускать. Сохранить ID старых образов обоих
компонентов и исходные настройки Mini App. Не публиковать Config.Env/.env или
полный compose config. Для rollback сохранить старый bot image отдельным тегом:
`docker image tag ID_СТАРОГО_BOT_IMAGE bitrix-missed-calls-bot:before-stage2-1`.

## 2. Установить новый каталог, не перезаписывая старые файлы

```bash
set -eu
cd /tmp
sha256sum -c planner-stage2-1-production-v1.tar.gz.sha256
release=/opt/bitrix_missed_calls_bot/planner-releases/stage2-1-production-v1
test ! -e "$release"
install -d -m 750 -o bitrixbot -g "$(id -gn bitrixbot)" "$release"
chmod 644 /tmp/planner-stage2-1-production-v1.tar.gz
runuser -u bitrixbot -- tar -xzf /tmp/planner-stage2-1-production-v1.tar.gz -C "$release"
cd "$release"
python3 -B deploy/release_check.py
install -m 600 deploy/planner.env.example deploy/planner.env
export PLANNER_BOT_ENV_FILE=/opt/bitrix_missed_calls_bot/.env
```

Отредактировать **только новый несекретный deploy/planner.env**. Старый .env не
меняется. Установить MANAGER_N_TELEGRAM_ID в соответствии с проверенными именами:
Вячеслав 8306778724, Яна 7939114214, Евгений — пусто. Не угадывать порядок слотов.
DISTRIBUTION_CONFIRMER_IDS=8306778724; supervisor 1073597301 добавляется только
при отдельном решении. Админская роль сама разрешения не даёт.
PLANNER_ACTIVE_MANAGER_IDS=8306778724,7939114214.
Сверить PLANNER_DATA_DIR и ACCESS_DIR с реально установленным прежним релизом.

## 3. Резервирование при активных соединениях

Из нового каталога; это стандартная библиотека, токены не нужны:

```bash
backup=/opt/bitrix_missed_calls_bot/planner-backups
test -d "$backup" || install -d -m 700 "$backup"
python3 -B -m planner.backup create --database /opt/bitrix_missed_calls_bot/planner-data/planner.db --directory "$backup"
python3 -B -m planner.backup verify --backup "$backup/ИМЯ_PLANNER_КОПИИ.db"
```

Если очередь уже существует, также:

```bash
python3 -B -m planner.backup create --kind queue --database /opt/bitrix_missed_calls_bot/distribution-queue/confirmations.db --directory "$backup"
python3 -B -m planner.backup verify --kind queue --backup "$backup/ИМЯ_QUEUE_КОПИИ.db"
```

Используется SQLite Backup API, не cp живых SQLite. Копии эксклюзивные, mode600,
integrity/foreign key/SHA256 проверки. Два backup не являются общей транзакцией:
queue append-only позволяет восстановить недоставленные распределения повторным
импортом. Перед фактической миграцией остановить только Mini App и сделать вторую
финальную копию planner.db, чтобы избежать потери записей между backup/обновлением.
Старый бот в это время продолжает прежнюю работу, пока его обновление не согласовано.

## 4. Тестовая миграция на копии

```bash
copy=/opt/bitrix_missed_calls_bot/planner-migration-test-stage2-1
test ! -e "$copy"
install -d -m 700 -o 10001 -g 10001 "$copy"
python3 -B -m planner.backup restore --backup "$backup/ИМЯ_PLANNER_КОПИИ.db" --directory "$copy"
chown 10001:10001 "$copy/planner.db"
python3 -B -c 'from pathlib import Path; from planner.store import Store; s=Store(Path("/opt/bitrix_missed_calls_bot/planner-migration-test-stage2-1/planner.db")); s.initialize(); s.initialize(); print("Migration copy OK")'
python3 -B -m planner.backup create --database "$copy/planner.db" --directory "$backup"
```

Рабочая БД здесь не открывается на запись. Сверить роли, число планов/задач/отчётов,
историю и активные таймеры на копии. Не подменять рабочую базу этой копией.

## 5. Права очереди и сборка образов

```bash
queue=/opt/bitrix_missed_calls_bot/distribution-queue
if [ ! -e "$queue" ]; then install -d -m 700 -o 10001 -g 10001 "$queue"; fi
stat -c '%u:%g %a %n' "$queue"
sh deploy/planner-compose.sh config --quiet
sh deploy/bot-release-compose.sh config --quiet
sh deploy/planner-compose.sh build planner
sh deploy/bot-release-compose.sh build bot
```

Сборка не запускает polling/миграцию. Если существующая
папка очереди имеет другие права — выяснить причину, не делать массовый chmod/chown
data/ или planner-data. База очереди создаётся ботом с mode600, UID/GID10001.
Bot mount: data RW как раньше, queue RW; planner.db вообще не смонтирована.
Mini App: access dir RO, queue RO, planner-data RW. Корень контейнеров read-only.
Очередь journal DELETE, не WAL. Папка монтируется целиком для видимости journal.
После аварии hot journal восстанавливает writer при старте бота или подтверждении;
RO reader повторяет позже. Ошибка инициализации очереди не останавливает polling.

## 6. Обязательный Linux smoke test на отдельной временной папке

```bash
smoke=/opt/bitrix_missed_calls_bot/sqlite-smoke-stage2-1
test ! -e "$smoke"
install -d -m 700 -o 10001 -g 10001 "$smoke"
image=bitrix-workday-planner:stage2-1-production-v1
docker run --rm --network none --user 10001:10001 --mount type=bind,src="$smoke",dst=/queue --mount type=bind,src="$release/deploy/sqlite_mount_check.py",dst=/check.py,readonly "$image" python /check.py init
docker run -d --name planner-stage2-1-smoke-writer --network none --user 10001:10001 --mount type=bind,src="$smoke",dst=/queue --mount type=bind,src="$release/deploy/sqlite_mount_check.py",dst=/check.py,readonly "$image" python /check.py writer
docker run --rm --network none --user 10001:10001 --mount type=bind,src="$smoke",dst=/queue,readonly --mount type=bind,src="$release/deploy/sqlite_mount_check.py",dst=/check.py,readonly "$image" python /check.py reader
docker wait planner-stage2-1-smoke-writer
docker rm planner-stage2-1-smoke-writer
```

Только временный контейнер и синтетическая SQLite: UID/GID, mode600, DELETE,
live writer + RO reader и невозможность записи с RO mount. При неуспехе не
обновлять рабочие сервисы. Ни токенов, ни сети, ни рабочих БД.

## 7. Изолированная проверка цепочки на сервере

```bash
docker run --rm --network none --read-only --tmpfs /tmp:rw,mode=1777 --mount type=bind,src="$release/deploy/test_release_chain.py",dst=/app/check_chain.py,readonly bitrix-workday-planner:stage2-1-production-v1 python -B /app/check_chain.py
```

Этот тест создаёт queue/planner в /tmp, использует искусственные лиды и не
обращается к CRM/Telegram. Нельзя публиковать тестовое распределение в рабочую
очередь: оно заняло бы дневной слот и могло изменить реальные планы.

## 8. Только после отдельного согласования обновления контейнеров

```bash
sh deploy/planner-compose.sh stop planner
python3 -B -m planner.backup create --database /opt/bitrix_missed_calls_bot/planner-data/planner.db --directory "$backup"
sh deploy/planner-compose.sh up -d --no-deps --no-build planner
sh deploy/planner-compose.sh ps planner
curl --fail http://127.0.0.1:18080/healthz
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/api/me
sh deploy/planner-compose.sh exec -T planner python -m planner.ops
sh deploy/bot-release-compose.sh up -d --no-deps --no-build bot
sh deploy/bot-release-compose.sh ps bot
stat -c '%u:%g %a %n' "$queue" "$queue/confirmations.db"
```

Mini App healthy, API401 без initData, ops ready:true. До обновления бота queue DB
может ещё отсутствовать: новый бот создаёт её при старте с явными полномочиями;
reader безопасно повторяет попытки, healthz остаётся доступным. Проверить
UID/GID10001 и mode600 после запуска нового бота.
Compose up заменяет только указанный сервис; project labels проверены заранее.
Ни второй polling, ни общий down не использовать. Новый bot использует прежний
токен/env и прежний access.db. Nginx/HTTPS/BotFather остаются как настроены.

## 9. Проверка после установки

```bash
sh deploy/planner-compose.sh logs --tail=50 planner
sh deploy/bot-release-compose.sh logs --tail=50 bot
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
curl --fail https://plan.prav-buro.ru/healthz
```

Проверить /start, варианты и ручные даты без подтверждения, доступ Яны/Вячеслава/
руководителя. Реальное дневное подтверждение отдельно согласовать: оно создаёт
реальные задания (CRM не меняет). После него проверить variant_index, по одной
задаче на сотрудника, статусы импорта, подтверждение планов, таймер/факт/историю.
При queue error/review разбирать причину, не удалять записи и не подменять БД.
Сравнить список чужих контейнеров до/после, их StartedAt должны сохраниться.

## Откат

1. Сначала сохранить новые planner/queue backups через новый код, если БД читаются.
   Сохранить неудачные каталоги/образы/логи. Не удалять очередь или её историю.
2. Остановить только новый bot и planner через соответствующие wrappers.
3. Если достаточно вернуть старый bot, из исходной папки использовать старый
   Compose с override image на сохранённый before-stage2-1, up --no-deps --no-build
   bot. Не собирать старый тег из нового кода. Ни других сервисов, ни второго бота.
4. Старый Mini App schema2 не запускается с schema4. Восстановить предмиграционную
   копию в новую planner-data-rollback-УНИКАЛЬНОЕ_ИМЯ, owner10001/mode700 и файл600.
   Создать новую rollback-копию прежнего релиза с его сохранённым образом; в её
   новом несекретном env поменять только PLANNER_DATA_DIR. Прежний релиз не править.
   Запустить его wrapper up -d --no-deps --no-build planner, проверить health/API401.
5. access.db/.env/Nginx не восстанавливать и не менять. Queue сохранить без reset:
   возвращение на этап2.1 позволит идемпотентно импортировать подтверждения.

**Восстановление старого planner backup не содержит записей после его создания.**
До отката остановить запись, сохранить актуальную БД и согласовать перенос новых
планов/факта/отчётов. Автоматически объединить эти данные с schema2 не обещаем.
Бездумный rollback может потерять новые результаты даже при сохранности CRM.

Команды восстановления в новую папку:

```bash
restore=/opt/bitrix_missed_calls_bot/planner-data-rollback-УНИКАЛЬНОЕ_ИМЯ
test ! -e "$restore"
install -d -m 700 -o 10001 -g 10001 "$restore"
python3 -B -m planner.backup restore --backup "$backup/ПРЕДМИГРАЦИОННАЯ_КОПИЯ.db" --directory "$restore"
chown 10001:10001 "$restore/planner.db"
```

Для старого bot override создать отдельный файл с services.bot.image=
bitrix-missed-calls-bot:before-stage2-1 и запускать явно -p bitrix-missed-calls-bot
-f /opt/bitrix_missed_calls_bot/compose.yaml -f ПУТЬ_OVERRIDE up -d --no-deps
--no-build bot, --project-directory исходной папки. Никогда не compose down.

Конкретный пример после сохранения новых данных и остановки только двух новых
сервисов (теги/пути сверить с ранее зафиксированными):

```bash
bot_override=/opt/bitrix_missed_calls_bot/planner-releases/stage2-1-rollback-bot.yaml
test ! -e "$bot_override"
cat > "$bot_override" <<'YAML'
services:
  bot:
    image: bitrix-missed-calls-bot:before-stage2-1
YAML
docker compose --project-directory /opt/bitrix_missed_calls_bot -p bitrix-missed-calls-bot -f /opt/bitrix_missed_calls_bot/compose.yaml -f "$bot_override" up -d --no-deps --no-build bot

rollback_release=/opt/bitrix_missed_calls_bot/planner-releases/stage2-1-rollback-planner
test ! -e "$rollback_release"
cp -a /opt/bitrix_missed_calls_bot/planner-releases/stage1-production-v3-prebuilt "$rollback_release"
sed -i "s|^PLANNER_DATA_DIR=.*|PLANNER_DATA_DIR=$restore|" "$rollback_release/deploy/planner.env"
cd "$rollback_release"
export PLANNER_BOT_ENV_FILE=/opt/bitrix_missed_calls_bot/.env
sh deploy/planner-compose.sh config --quiet
sh deploy/planner-compose.sh up -d --no-deps --no-build planner
curl --fail http://127.0.0.1:18080/healthz
```

Это изменяет только новую rollback-копию env, не исходный релиз. Перед up проверить
сохранённый тег Mini App в этой копии. Не подставлять stage2 образ к schema2 копии.

## Ограничения и готовность

Локальная цепочка и миграции проверяются без производственных БД. Docker Engine
локально отсутствует, реальная Linux сборка/RO bind/UID/journal smoke остаются
обязательными проверками до production, а не подтверждённым фактом.
Маппинг MANAGER_N_NAME и текущие настройки на сервере необходимо перепроверить.
Live active из Mini App в бот пока не передаётся: бот использует явный список,
а importer повторно проверяет active и при конфликте требует review.
Процедура замены распределения и разрешения review ещё не реализована.
Критерий: готово к согласованной установочной проверке, не к безусловному
автоматическому развёртыванию. Никаких действий на Ubuntu не выполнялось.
