# Самостоятельный репозиторий «Рабочее пространство»

28.10.2026. Назначение: только public emerald634/planner, review-ветка
`review/complete-workspace-20261028`. Production и main не менялись.

## 1. Статусы

| Статус | Результат |
|---|---|
| РЕАЛИЗОВАНО | Один source checkout: web/backend/frontend + корневые Planner/бот/Mini App, общий Store/algorithm/queue, portable tools, полная README и связанная документация |
| ЛОКАЛЬНО ПРОВЕРЕНО | Новый отдельный clone, собственная venv и frozen JS dependencies,236 Planner/94 web/60 frontend/33 Edge групп; обе production React-сборки; единый review ZIP/manifest/SHA256 |
| ГОТОВО К REVIEW | Полные исходники и tests, provenance, обычные Docker build contexts, безопасная review-ветка/Draft PR; не разрешение установки |
| НЕ ПОДТВЕРЖДЕНО | Фактические Docker images/Linux kernel UDS/UID/RO mounts/DELETE locking, real PG16/DDL/concurrency, HTTPS/live CRM, server headroom и полноценный CVE/image gate |
| ТРЕБУЕТ ОТДЕЛЬНОГО РАЗРЕШЕНИЯ | PostgreSQL/Docker/WSL install, реальные webhook/данные/БД/VPS, Nginx/cutover/deploy, merge |

Новые задачи/подпункты/«В течение дня»/D40 не добавлялись. Перенос не является
полной реализацией2.2 или миграцией Planner в PostgreSQL.

## 2. Исходные версии, разрешение, сохранность

- LeadFlow: `0fa3719e8aede5f81e250be42c5d3a009ea78d96`.
- Planner: `01cf5ae9d10e22b0b1557e79e22cc84e9f781273`.
- Опубликованная база новой ветки: `592db81abd47fced33986140dcd1cae4c9dbda9a`.
- Основной import: `ca119a6f18a56b3b833422dc727a0c3b64750e33`.
- Bot pins/build contexts: `84e77b9effb00038a71d5b56b26d6ec2153d224a`.
- Итоговый программный snapshot: **`4b6f51ac00f10759e1136a0522db91cb9dea7c47`**.
  Последующие commits документации/ссылки PR не меняют бизнес-код. Точный final
  source_commit подготовленного bundle записан в workspace-release.json.

LICENSE в исходном LeadFlow не найден. До импорта владелец прямо подтвердил
разрешение публичного размещения в своём Planner. Основание — это подтверждение,
не сам факт публичного репозитория и не придуманная MIT/Apache лицензия.
Авторство/происхождение сохранены в [PROVENANCE](docs/PROVENANCE.md).

Из LeadFlow включён151 отслеживаемый source/config/test/tool файл; полный перечень
с исходными и адаптированными hashes — [source-import-manifest.json](docs/source-import-manifest.json).
Его GitHub, checkout, branches и commits не изменялись: HEAD тот же, проверены
SHA256 всех173 исходных tracked файлов, изменений0; status совпадает с pre-import.
Никаких push/PR/настроек LeadFlow. Внешний checkout в тестах/сборке не используется.

## 3. Итоговая структура

```text
README.md, PROJECT_MASTER_KNOWLEDGE.md (public safe), COMPLETE_WORKSPACE_REPOSITORY_REPORT.md
bot.py, access.py, bitrix.py, config.py, distribution.py, keyboards.py, reminders.py
planner/                           единственный business core/Store/queue/importer
miniapp/                           Telegram React и отдельный desktop-прототип
web/backend/app/                   LeadFlow API/models/services/sessions
web/backend/workspace/             ordinary factory, CSRF, identity, private writer/recovery
web/backend/alembic/               auth0001–0005
web/backend/local_web/             только owned synthetic harness
web/backend/tests/                 web regression
web/frontend/                     React sources, package.json, package-lock/pnpm-lock
web/tools/                        portable test/browser/copy-migration launchers
web/deploy/                       ordinary Dockerfile/context ignore, config, Linux recipe
deploy/                           сохранённые bot/Mini App/release/backup recipes
tools/                            checkout/history checks и unified packaging
tests/                            сохранённый Planner/Telegram набор
docs/                             architecture/components/auth/CRM/data/testing/deploy/rollback/limits/history/provenance
.github/workflows/source-checks.yml synthetic CI only
```

Ни web/planner, ни второй distribution.py не создавались. Корневые Store,
bot/config/daily/queue и алгоритм совпадают с принятыми Planner исходниками.
Прежняя Mini App совместимость/история/роли сохранены.

## 4. Изменённые пути и зависимости

Source LeadFlow размещён в web/. Runtime импортирует корневой planner через
тот же checkout/PYTHONPATH Docker container, не через соседний source directory.
Python test runner добавляет только web/backend и текущий root. Удалены
Path.home/default author checkout и fallback к чужому venv в bot integration test.
Synthetic scratch — .workbench/browser; launcher отвергает external planner-source;
его ownership/local-auth ограничения сохранены и тесты проходят.
Внутренняя адаптация количества parents затрагивала3 isolation теста; исправлена,
без ослабления проверок. Первый запуск core browser опередил готовность порта;
повтор после готовности прошёл12 групп. Эти промежуточные ошибки не скрываются
за итоговыми успешными результатами.

Реальный dependency conflict: aiogram3.31 требует Pydantic<2.14, прежний web pin2.14.1.
В новом checkout закреплены2.13.5/core2.46.5 (Planner baseline), проверен полный
совместный набор; исходный LeadFlow не изменён. requirements-workspace-dev.txt
фиксирует shared runtime/test/bot stack; requirements-bot.lock.txt —24 bot pins.
pip check чист. JS direct versions взяты из принятого package-lock, latest заменён
на точные версии, pnpm11.25 lock закрепляет всю итоговую установку; supply-chain
checks не отключались. Original package-lock сохранён с согласованными direct specs.
Linux-specific wheels/полный vulnerability gate не выдаются за выполненные.

## 5. Как собираются компоненты

Из одного клона: установить requirements-workspace-dev.txt в свою venv, pnpm frozen
для web/frontend и miniapp. Команды README проверены; Node/pnpm не нужны в Python
runtime image. Web Dockerfile получает root planner/bitrix/distribution и обычный
web/frontend/dist. Bot Dockerfile включает broker + новый lock; root Dockerfile
также исправлен. Mini App Dockerfile получает miniapp/dist + generated root
frontend-build.json, который создаёт unified packager.

COPY/build contexts и состав проверены статически. **Реальные docker build/run
не выполнялись:** Docker отсутствует, WSL не установлен; ничего не устанавливалось.
Команды из README — для отдельно разрешённого Linux gate, не для текущего VPS.

## 6. Чистый checkout и регрессия

Создан отдельный `git clone --no-local --single-branch` review-ветки, без alternates
и папки LeadFlow, затем собственная новая venv и обе frozen dependency installations.
Кэши используются только для third-party packages, не исходников соседнего проекта.
Source runner/Planner/fixtures/scripts берутся из этого клона. Check_repository
подтверждает отсутствие author-path fallback и дублирующего core.

| Проверка в чистом clone | Результат |
|---|---|
| Planner/Telegram/Mini App Python |236 passed,0 failures/errors/skips; повтор после bot lock/release-context правки тоже236 |
| Web Python |94 passed,2 deprecation warnings, synthetic auth DB; не real PostgreSQL |
| Web frontend |60 passed, TypeScript/ESLint/обычная Vite production build passed |
| Mini App |TypeScript + Vite production build passed, demo bypass не включён |
| Edge business |21 группа passed; реальный local backend, CRM mocks,0external/0unhandled errors |
| Edge core |12 групп passed; tasks/timer/requests/roles/CSRF/history/reload |
| Dependency check |pip check: no broken requirements |
| Static |AST/single core/author-path checks, Ruff F выбранных source/tools, git diff --check passed |

Synthetic end-to-end: единый login, manager/supervisor/two managers,8 показателей,
создание/редактирование задач, timer, goal approval, immutable closed report;
web distribution variants→confirm→queue→autoimport; настоящий bot callback→BrokerQueue
→writer ASGI→queue→importer, повторы/конкуренция/ошибки CRM/writer/restart/lost-response.
Manager не читает чужое, admin не supervisor, confirm требует grant, CSRF и local
CRM-write hold сохранены. Linux physical UDS не подменяется ASGI результатом.

## 7. Безопасность публичного дерева/истории/Actions

Review-ветка основана на опубликованной main, а не на локальных private knowledge
commits. Полная внутренняя база сохранена локально без потерь, root файл заменён
публичным техническим индексом. Историю main/старых веток не переписывали;
force push/rebase/reset/clean не выполнялись.

Сканированы опубликованная база (153blob), полная достижимая история после import
(343blob) и новая отправляемая часть (190blob), затем финальные новые commits:
нет совпадений с high-confidence private-key/Telegram-token/credential-DSN/webhook
patterns и private DB/.env paths. Сканер tools/audit_public_tree.py проверяет сами
Git objects, не только текущий файл. Искусственные DSN тестов идентифицированы
явно; это ограниченный scan, не универсальный DLP. Git author identities и прежние
опубликованные protocol roster bindings не скрываются как якобы удалённые данные.
Новые рабочие аккаунты/CRM-клиенты/БД/секреты не включались и не читались.

Исходные .github/workflows/ci.yml/deploy.yml LeadFlow **не импортированы**:
deploy.yml имел автоматический SSH/compose запуск. Новый source-checks workflow
только читает checkout, устанавливает dependencies и запускает synthetic tests/build;
contents:read, нет SSH/deploy/production secrets/CRM-write/PG services.
После push GitHub Actions подтвердили Linux frontend tests/build и установку Python3.12 dependencies. Первый synthetic job выявил4 packaging errors: miniapp/dist не был собран в этом отдельном job. Workflow/README исправлены: production Mini App build теперь предшествует Python regression; тесты не отключены. Повторный Linux run проверяется отдельно, не заменяет Docker/UDS/PG gates.

## 8. Release bundle

tools/package_workspace.py требует чистый source tree, обязательно заново собирает
оба frontend, проверяет Mini App static allowlist/no demo/maps, запрещённые
paths/tokens, ZIP integrity и hashes всех файлов. Создаёт source+prebuilt review ZIP,
workspace-release.json, .manifest.json и .sha256; target существовать не должен.
Фиксирует текущий Git SHA, обе исходные линии и schemas4/1/daily1/observations1/auth0005.
Проверены исходный пакет320 entries и затем итоговый пакет с этим отчётом.
Примеры config без secrets включены; .env/DB/key/node_modules/private workbench исключены.
Source tests/fixtures входят как исходники; production Docker context исключает local_web/tests.
Это review/source bundle, не опубликованный бинарный GitHub release и не production install proof.

Локальный итоговый архив: `.workbench/clean-checkout/release-artifacts/workspace-complete-review-final-20261028.zip`
с соседними .sha256/.manifest.json. Они не добавляются в Git вместо исходников.
Полная схема регенерации — README; исходник источника в отдельной папке не нужен.

## 9. Installation gates и будущий откат

До installation: Linux/Python3.12 image/dependency/CVE/base digest, UDS двух UID/RO
mounts/DELETE journal, real PostgreSQL16 DDL/roles/concurrency/backup/restore,
HTTPS/proxy/cookies, live read-only CRM contracts/quotas и combined load/CPU/IO/locks.
Владелец сообщил6ГБ VPS, новый headroom не измерялся. Полный код теперь здесь,
но наличие исходников не подтверждает эти внешние условия.

Planner core4/queue1/auth0005, old plans/tasks/timers/reports/audit/sessions/local
status сохранены по synthetic regression. Production migrations/данные не трогались.
Сначала online backup/test restore и совместимый legacy Mini App; после отдельного
разрешения — согласованный cutover своих publishers/importer и одного poller,
одна прежняя очередь. Нет chmod RO reader для queue-write, второго бота/очереди.
При ошибке — свежие backups/deltas и совместимый read-only recovery, без
destructive downgrade/перезаписи текущих данных старой копией. Старый writable ORM
без local не безопасен; local→pending ради отката запрещён. Чужие контейнеры,
Nginx/CRM/swap/production не затрагиваются этим заданием.

## 10. Публикация и локальная база знаний

Review-ветка: https://github.com/emerald634/planner/tree/review/complete-workspace-20261028

Draft PR: **https://github.com/emerald634/planner/pull/9** — открыт, Draft, без merge.

Публикация только в emerald634/planner, public сохраняется, main не меняется,
Draft остаётся Draft, merge/deploy не выполняются. GitHub подтвердил отсутствие конфликтов с main.
Локальная полная внутренняя база дополнена картой monorepo/проверками/процессом
release; публичная редакция и docs — в этом репозитории. ChatGPT Project автоматически
не обновлён. Сопроводительные evidence JSON/скриншоты/private scratch остаются
локальными test-artifacts, воспроизведение выполняется по зафиксированным scripts.
