# Проверки одного checkout

Установить только requirements-workspace-dev.txt в чистую venv и оба pnpm frozen lock. Не добавлять PYTHONPATH на соседние репозитории, symlinks на author sources или fallback source paths. python tools/check_repository.py проверяет layout; synthetic launcher отвергает внешний planner-source.

Сначала `pnpm --dir miniapp build`: packaging regression использует настоящий miniapp/dist, не скрытый старый артефакт. Затем python -B -m tests.run_foundation_checks — весь Planner/бот/Mini App; python -B web/tools/run_session_checks.py — web backend. Они используют свои test-artifacts, запрещают реальные .env/SQLite и внешний egress. TestClient auth transport — synthetic SQLite, **не доказательство PG**. Actual bot callback/BrokerQueue/writer/importer проверяется без poller; UDS заменён ASGI только в Windows tests. В GitHub Actions каждый job сам подготавливает требуемый build; dist другого job не считается доступным.

Frontend: pnpm --dir web/frontend test, lint, build. Mini App: pnpm --dir miniapp build. Для UI harness нужен установленный Edge; Playwright пакет из miniapp dependencies. Команды prepare/run/stop и два независимых RUN_ID — в README. Не публиковать созданные credentials/control files. Browser делает реальные local API mutations, CRM только synthetic.

Чистый gate: отдельный git clone --no-local выбранной review-ветки в пустой каталог, отдельная установка locked third-party dependencies, повтор checks/build/tests/browser. Кэш пакетов допустим; внешние source directories — нет. Результаты и фактические ограничения — COMPLETE_WORKSPACE_REPOSITORY_REPORT.md.

Linux kernel UDS/UID/RO mounts/DELETE, real PG, HTTPS/live CRM не подменяются Windows tests. Рецепт web/deploy/linux_smoke.py и review compose не запускает Docker/PG автоматически. GitHub Actions выполняют только синтетические тесты/build, без SSH/deploy/CRM secrets.
