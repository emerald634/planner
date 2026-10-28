# Данные и миграции

| Хранилище | Версия / расширение |
|---|---|
| Planner SQLite | user_version4; daily_extension1/daily_records, previews, crm_observations1 |
| Queue SQLite | schema1, UNIQUE московский день, immutable triggers, DELETE journal |
| Canonical auth PostgreSQL | Alembic0005_workspace_links после0004 sessions |
| Telegram ACL SQLite | Существующий access.db, отдельно, без копирования поверх |

Runtime не мигрирует/не seed-ит при старте. tools/prepare_workspace_copy.py под web/ открывает source mode=ro, online backup в новый O_EXCL destination, fingerprint старых таблиц, transactional additive DDL и integrity/FK checks. Вызов: python web/tools/prepare_workspace_copy.py --source /ISOLATED/source.db --destination /ISOLATED/NEW.db. Это только заранее разрешённая синтетическая/отдельная копия.

Не выполнять Alembic production upgrade из README автоматически. На отдельном разрешённом PG стенде: cd web/backend; alembic upgrade head, затем concurrency/rollback/privilege tests. Здесь PG не установлен. local status длиной5 не требует новой Planner schema; реальные PG CHECK/ENUM проверяются до rollout.

Старые отчёты не переписываются. Closed daily читается из reports.snapshot; confirm/close атомарно фиксируют initial daily и audit. Существующие задачи/timers/comments/goal requests/queue rows сохраняются. [Backup/rollback](BACKUP_AND_ROLLBACK.md).
