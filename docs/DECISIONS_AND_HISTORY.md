# Решения и история

Цель — одно «Рабочее пространство», LeadFlow и «План дня» как разделы, один login/Layout/AuthProvider. Не создавать две реализации Store/distribution или вторую auth систему. Web90/30, Telegram initData/ACL отдельно, manager ownership, supervisor scope, confirmer отдельный grant. Не переписывать immutable reports/history/queue ради обновления.

| Принятая линия | LeadFlow | Planner |
|---|---|---|
| RC1 |232728efd8fb4404f45699dace8bb67b54a7f54d|6e0f9f8b8ea7433a6bf974d2af047a8793aa5c64|
| RC2 |022a91d6e1478c57a266cfbc2010174ef9e1dbe3|e87666215ebcbd93497361094430bae7b2fe53ac|
| Принятый review fixes |0fa3719e8aede5f81e250be42c5d3a009ea78d96|01cf5ae9d10e22b0b1557e79e22cc84e9f781273|

Исходные SHA нужны только для provenance, не для сборки: все необходимые исходники находятся здесь. Review-ветка основана на опубликованной Planner main, без импорта локальных private-doc commits. История существующих веток не переписывается. Полный внутренний PROJECT_MASTER_KNOWLEDGE сохранён локально, новая публичная редакция исключает внутренний операционный контекст.

D39 основной web distribution реализован локально, полный live bot parity не доказан. D40 и новые общие задачи остаются отдельным заданием. PG16/Docker/WSL/production нельзя устанавливать по наличию README. Новый Git SHA и фактическая регрессия — в COMPLETE_WORKSPACE_REPOSITORY_REPORT.md и release manifest.
