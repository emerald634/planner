# Компоненты

| Источник | Назначение |
|---|---|
| bot.py/access.py/keyboards.py/reminders.py | Существующий poller, FSM, ACL, напоминания; не запускать в synthetic tests |
| bitrix.py/distribution.py | Read-only leads и общий алгоритм дат/баланса |
| planner/store.py/daily.py/server_migration.py | Единый Store,8 показателей, revision/CAS, snapshots |
| planner/distribution_queue.py/queue_broker.py/confirmation_reads.py | Schema1 queue, private client, fresh checks |
| planner/distribution_import.py/sync.py | Атомарный импорт, inbox, attempts/retry, system audit |
| planner/api.py + miniapp/ | Существующий Telegram Mini App и HMAC |
| web/backend/app | LeadFlow API/auth/models/services, local hold |
| web/backend/workspace | Ordinary web runtime, grants/CSRF, private writer, recovery |
| web/backend/local_web + web/tools | Только synthetic owned harness |
| web/frontend | Общий React интерфейс, обычный dist |

Нет второго Planner Store/алгоритма в web. Старый standalone Bitrix export service в app сохранён для истории/совместимости, но workspace его запуск запрещает. [Права](API_AND_AUTH.md).
