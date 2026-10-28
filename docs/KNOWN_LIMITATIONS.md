# Известные ограничения

- Локальная регрессия не равна production. Linux source tests/build в GitHub Actions прошли; Docker images/kernel UDS/mount/locking, реальный PG/DDL/roles/concurrency и HTTPS пока не подтверждены.
- Реальные CRM fields/scopes/quotas/global pacing не проверены; auto contracts выключены. Новые adapters read-only. Нет распределённого snapshot CRM одного мгновения.
- Planner хранится в SQLite; PostgreSQL auth не означает перенос business DB.
- Новые общие задачи/подпункты, «В течение дня» и D40 не реализованы этим этапом.
- Явные production user→employee mappings/grants не создавались. Протокольные fixture IDs в старом Store/тестах не означают реальные web аккаунты/доступ.
- Исторические roster bindings/неполная динамика сотрудников и большие старые bot CRM выборки остаются прежними рисками, не скрытым изменением бизнес-логики.
-6ГБ RAM сообщены владельцем, текущий VPS не измерялся. Изолированные Windows peaks не доказывают combined load/cgroup headroom.
- Mutable base images, Linux wheels и CVE gate требуют отдельного review. Supply-chain checks не отключены.
- Полная внутренняя база знаний сохранена отдельно локально. Публичный технический срез не является разрешением публиковать новые секреты/клиентские данные.
