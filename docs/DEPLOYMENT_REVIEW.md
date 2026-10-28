# Deployment review — не разрешение на установку

Context всех Docker builds — корень checkout. Web Dockerfile web/deploy/Workspace.Dockerfile получает обычный web/frontend/dist и единственный root planner; Node/pnpm в runtime нет. Bot deploy/Bot.Dockerfile получает broker-код, один poller. Mini App deploy/Planner.Dockerfile получает miniapp/dist + frontend-build.json из review bundle. Root Dockerfile теперь также содержит полный bot context; рекомендуемый явный путь — deploy/Bot.Dockerfile.

web/deploy/compose.workspace-review.yaml: web loopback18180, writer только UDS; PG service отсутствует. Пример config без secrets/grants. Web UID10001:G10020 PlannerRW/queueRO; writer10003:G10020 PlannerRO/queueRW; bot10001:10001 +10020, только private socket/bot key, нет Planner/queue mount. Каталоги Planner10001:G10020, queue10003:G10020 dir750/file640; keys400/600 своего UID; socket750/group-connect. Не ослаблять существующий access.db600. Это проект прав, физический proof Linux ещё нужен.

Перед rollout: image/base digest/dependency/CVE gate, Linux UDS/mount/locking, real PG DDL/least privilege/concurrency, HTTPS/session-cookie smoke, live read contracts/quotas, combined load и inventory всех export workers. Владелец сообщает6ГБ VPS; headroom не измерен. Сначала backup/test restore и совместимый legacy Mini App, затем согласованное окно одного poller/одной queue. Нельзя общий compose down/prune, менять чужие контейнеры/Nginx или запускать второй bot project.

Не запускать старые deployment workflows LeadFlow: они намеренно не импортированы. Только после отдельного решения можно готовить реальные конфиги/миграции/cutover. [Rollback](BACKUP_AND_ROLLBACK.md).
