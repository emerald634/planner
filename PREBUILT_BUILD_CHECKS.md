# Проверка релиза stage1-production-v3-prebuilt

Дата: 2026-10-13. Развёртывание на VPS не выполнялось.

- Python: 101 тест, все успешно. Проверены существующее распределение,
  авторизация, роли, планы, цели, таймеры, закрытые отчёты, история и резервирование.
- Дополнительно проверены архив, отсутствие demo/maps/secrets, ошибки сборки,
  SHA256 assets, production-запуск из архива, 401 без initData, вход Яны,
  404 для preview и manifest, отказ при повреждении JavaScript.
- pnpm 11.25.0: offline install с frozen lockfile и production build успешно.
  Проверки безопасности зависимостей не отключались.
- pip check: No broken requirements found.
- Dockerfile содержит только Python; Docker на Windows отсутствует,
  сборка образа фактически не запускалась. На Ubuntu требуется доступ к PyPI.
- Контрольные суммы .env, access.db, compose.yaml, Dockerfile, bot.py,
  config.py, bitrix.py, distribution.py и requirements.txt не изменились.

Изменённые файлы: deploy/Planner.Dockerfile,
deploy/Planner.Dockerfile.dockerignore, deploy/package_release.py,
deploy/planner.env.example, miniapp/src/App.tsx, planner/api.py,
PLANNER_DEPLOY.md, tests/test_planner_production.py.
Добавлены planner/frontend.py, tests/test_frontend_release.py и этот отчёт.
compose.planner.yaml сохраняет отдельный проект, read-only доступ к базе
бота, постоянную planner.db и loopback-порт 18080.

Инструкции установки, резервирования и отката: PLANNER_DEPLOY.md.
Предыдущий каталог stage1-production-v2 и его образ сохраняются.
