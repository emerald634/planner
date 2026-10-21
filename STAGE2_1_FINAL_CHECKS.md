# Финальные локальные проверки этапа 2.1

Дата: 13.10.2026. На Ubuntu не подключались и ничего не развёртывали.

Результат: 142 Python-теста успешно; TypeScript и Vite production build успешно;
оба Edge/Playwright сценария успешно. Дополнительный поставляемый изолированный
тест релиза успешно. Shell wrapper нового bot release проверен sh -n.

Полная цепочка: варианты бота → окончательный вариант → очередь с ID/датами/
менеджерами → автоматический импорт → оба manager confirm → supervisor видит
approved → таймер/результат/комментарий → immutable закрытые отчёты. Искусственные
данные, временные SQLite, mock Bitrix API; рабочей CRM/Telegram нет.

Миграция: тестовая schema2 с сотрудниками/ролями, планами, задачами, живым таймером,
фактом/комментарием/результатом, closed report, аудитом и pending goal request
сохранена по всем прежним колонкам после Backup API → новая копия → 2→3→4 и
повторного initialize. Новая task.creation_actor=employee для старых задач.
Сбой миграции откатывается; исходная тестовая schema2 остаётся schema2.

Backup queue: SQLite Backup API при открытом writer-соединении с BEGIN IMMEDIATE,
SHA256/integrity/snapshot checks, restore в новый файл и запрет перезаписи.
Planner backup и restore покрыты прежними тестами, включая schema4.

Архив: allowlist обоих компонентов, prebuilt React, manifest SHA256 всех файлов,
без .env/DB/node_modules/maps/pyc/клиентских данных. Дополнительно сканируются
credential-like литералы; frontend проверен на отсутствие demo/секретов.
Фактические checksum архива находятся в отдельном .tar.gz.sha256 рядом с архивом.
Secrets не печатались; новые sync-логи содержат безопасные общие ошибки, не payload.

Docker: локального Engine нет. Образы не были собраны и не запускались локально;
Linux UID/GID/RO bind/DELETE journal проверка поставлена обязательным smoke gate.
Конфигурация задаёт UID/GID10001, queue RW только у бота, RO у Mini App; planner.db
не монтируется боту. Новых публичных портов нет. Source-only scanner не заменяет
проверку настоящего образа на Ubuntu.

Изменённые/добавленные файлы заключительной части:
compose.planner.yaml, compose.bot.release.yaml, deploy/Bot.Dockerfile,
deploy/Bot.Dockerfile.dockerignore, deploy/bot-release-compose.sh,
deploy/planner.env.example, deploy/package_release.py, deploy/release_check.py,
deploy/sqlite_mount_check.py, deploy/test_release_chain.py, planner/backup.py,
bot.py (инициализация очереди при старте), tests/test_release_stage2.py,
tests/test_bot_confirmation.py, PLANNER_DEPLOY.md, STAGE2_1_RELEASE.md и этот отчёт.
miniapp/dist пересобран. Полный функционал этапа описан в отчётах частей 1–4.

Не изменены рабочие .env/access.db, корневые Dockerfile/compose.yaml. Старые
архивы и каталог предыдущего релиза не перезаписаны. Контейнеры/Nginx/сервер/CRM
не затронуты. Готовность: локальные проверки пройдены; production требует
согласованного этапа установки и Linux smoke check. Не объявляется безусловно
готовым к автоматическому запуску.
