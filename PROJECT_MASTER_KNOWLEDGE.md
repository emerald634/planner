# Публичная техническая база знаний «Рабочее пространство»

Редакция:2026-10-28-complete-workspace-review. Это самостоятельный исходный monorepo; внутренняя полная база знаний сохранена владельцем локально без потерь. Публичная редакция не содержит внутреннего эксплуатационного реестра/переписок/доступов. Никакие secrets/рабочие данные/production сюда не переносятся.

Авторитетная карта: [README](README.md), [архитектура](docs/ARCHITECTURE.md), [компоненты](docs/COMPONENTS.md), [auth](docs/API_AND_AUTH.md), [CRM](docs/CRM_READONLY.md), [данные](docs/DATABASES_AND_MIGRATIONS.md), [проверки](docs/TESTING.md), [deployment review](docs/DEPLOYMENT_REVIEW.md), [откат](docs/BACKUP_AND_ROLLBACK.md), [ограничения](docs/KNOWN_LIMITATIONS.md), [решения](docs/DECISIONS_AND_HISTORY.md), [provenance](docs/PROVENANCE.md).

Принятые upstream SHA: LeadFlow0fa3719e8aede5f81e250be42c5d3a009ea78d96; Planner01cf5ae9d10e22b0b1557e79e22cc84e9f781273. Предыдущие результаты RC2 fixes:236/94/60 и33 Edge групп; результаты переноса и новый Git SHA — в COMPLETE_WORKSPACE_REPOSITORY_REPORT.md. Не выдавать старые числа за новый прогон.

РЕАЛИЗОВАНО: единый web frontend/login,8 дневных показателей/сохранение/отчёты, distribution, один queue writer, прежний bot/Mini App, session/CSRF/ownership/local hold/recovery. ГОТОВО К REVIEW исходников; не разрешение установки. НЕ ПОДТВЕРЖДЕНО: Linux/PG/HTTPS/live CRM/combined load. ТРЕБУЕТ ОТДЕЛЬНОГО РАЗРЕШЕНИЯ: PG16/Docker/WSL/production/реальные данные/merge.

Общие задачи/подпункты/«В течение дня»/D40 не реализованы. Planner core4, queue1, auth0005; business данные не мигрированы. Исторические root deployment-документы не заменяют актуальный deployment review. Вложение ChatGPT Project само от изменения Git не обновляется.

## Итог самостоятельного репозитория

Source snapshot4b6f51ac00f10759e1136a0522db91cb9dea7c47; web/ содержит полный принятый source, корневой planner/ единственный business core. В отдельном clone установлены свои dependencies и проверены236 Planner/94 web/60 frontend/33 Edge группы, обе React builds. Pydantic2.13.5 совместим с aiogram; bot/runtime/test pins и pnpm frozen lock находятся здесь. Runtime build context — корень; package_workspace создаёт source+prebuilt ZIP и schema/file/commit manifest. История внутренних документов не импортирована новой веткой. Полная база сохранена локально отдельно. Полный отчёт — COMPLETE_WORKSPACE_REPOSITORY_REPORT.md. Публикация только review-ветки/Draft PR, без main/merge/production. Linux images/UDS/mount/PG/HTTPS/live CRM/ресурсы всё ещё отдельные gates.
