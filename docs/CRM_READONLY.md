# Read-only CRM

planner/daily_crm.py: crm.item.list, tasks.task.list, voximplant.statistic.get; каждый источник независимо, строгая форма/owner/date/direction/category/stage.2MB/page,8MB/source decoded bytes,200pages/10k ID/8s. Межстранично сохраняются id/title и SHA256 строки, конфликт дубля отклоняется. Ошибка не затирает ручной факт.

web/backend/workspace/crm.py ограничивает async lead transport. Fresh confirmation: максимум15 дат,2 reads одновременно,8s общий бюджет, writer10s, web RPC12s. Это не доказательство portal global quota; gate2 может дать4 reads.429/live scopes/latency — отдельный gate.

verified_contracts=[] и crm_secret_file=null по умолчанию. Возможные auto projections calls.actual/new_leads.planned/pain.planned только после подтверждения live contracts, только несохранённый draft. Факт обработки/боль/качественный разговор/оплата не выводятся из наличия карточки.

Нужны read groups crm/task/telephony и пользователь с ограниченным доступом. Scope name не гарантирует read-only webhook: ACL/методы проверять отдельно. Новый LeadFlow sync_status=local исключён из legacy pending/failed export; workspace worker/service/gateway запрещают CRM-write. PATCH не снимает hold/не привязывает CRM ID. Никаких настоящих CRM вызовов в тестах/CI.
