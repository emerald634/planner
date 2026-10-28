# Архитектура

Один checkout, один корневой planner/Store и distribution.py. Web Python добавляет только транспорт/API/canonical identity, не копию бизнес-таблиц. Обычный frontend использует workspace endpoints и прежние LeadFlow services. Telegram Mini App остаётся отдельным клиентом прежнего Planner API.

Browser→web(session+CSRF)→private UDS writer(web-key+session); единственный poller→writer(bot-key+actor); writer→read-only CRM→одна append-only schema1 queue; importer читает RO и транзакционно пишет Planner. Writer видит Planner RO. Cross-DB transaction отсутствует: queue хранит авторитетный snapshot, inbox/idempotency — в Planner.

Production auth — каноническая PostgreSQL users/sessions/links. Planner пока SQLite core4 с additive extensions. Наличие PostgreSQL auth не означает выполненный перенос business DB. Local synthetic factory не используется как production fallback.

См. [компоненты](COMPONENTS.md), [auth](API_AND_AUTH.md), [deployment gates](DEPLOYMENT_REVIEW.md).
