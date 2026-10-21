# Web-авторизация: утверждённые принципы, без реализации

Актуализация bridge 21.10.2026: PR №5 принят (`6501ef2`); отдельным заданием
разрешён и реализован локальный schema5-compatibility. Store сохраняет цель
миграций 4, но дополнительно открывает только известную 5 после строгой read-only
проверки структуры/registry/checksum/FK/integrity. На 4 не создаёт auth-таблицы.
На 5 не вызывает migration, не ремонтирует и не меняет auth-данные. Backup API
поддерживает известную 5. Отдельный профиль --bridge включает только нужные
schema/validation, без policy/password/migration. Профили legacy не получают
bridge capability. Реальные web routes, cookie login и account-admin отсутствуют.
Отчёт: SCHEMA5_COMPATIBILITY_REPORT.md; упаковка: SCHEMA5_BRIDGE_RELEASE.md.
Физический DDL не утверждён для production; Linux/Docker smoke и отдельное
разрешение на установку/миграцию остаются обязательны. История foundation ниже
описывает прежний этап и не заменяет эти новые результаты.

21.10.2026. PR №4 принят (merge `50ec7e8`); по последующему разрешению выполнен
локальный foundation: изолированные модели/policy, проект DDL и явная миграция
только синтетических БД. Рабочих endpoints, password verifier и production
schema5 нет; API по-прежнему требует Telegram HMAC. Физический DDL/reset_pending
остаётся проектом для review. Спецификация — `WEB_AUTH_FOUNDATION_SPEC.md`,
реальные результаты — `WEB_AUTH_FOUNDATION_REPORT.md`. Compatibility bridge
теперь реализован локально отдельным этапом, ждёт review (см. актуализацию выше).

## Общая идентичность и границы

Один employees.id, существующие manager/supervisor, одна planner.db. Никакого
поля роли в клиентской сессии, которое принимается за полномочия. Каждый запрос
проверяет сессию, активность web-учётки, сотрудника и актуальную роль; затем
применяются прежние Store.owner/план/задача/revision/closed/goal правила.
Администратор бота не становится supervisor. Web не доверяет employee_id,
переданному клиентом, при определении текущего пользователя.

Предлагается два явных auth-входа к общей бизнес-логике: существующий Telegram
actor остаётся без изменений; web actor проверяет cookie и CSRF, возвращая тот
же внутренний employee actor. Для будущих web business endpoints — явный router
`/api/web/...` с общей реализацией операций, без дублирования Store. Telegram
`/api/...` не начинает молча принимать cookie. Ошибка одного способа авторизации
не вызывает fallback на другой. Сам web не запускает второй Telegram polling.

**Утверждено 21.10.2026:** web-вход не зависит от Telegram ID и bot ACL.
Общие employees.id/active/roles применяются к обоим каналам. Отключение employee
блокирует оба; отключение web credential — только web. /removeuser и блокировка
бота не меняют web-доступ автоматически. Telegram HMAC/ACL остаются прежними.
История: предложение сохранить Telegram ACL для первого web-релиза заменено
этим решением; открытой альтернативой оно больше не является.

## Пароли и сессии

Предлагается Argon2id с индивидуальной солью, минимум 19 MiB/t=2/p=1, с
измерением нагрузки и ограничением параллельных проверок на новом сервере.
Библиотеку и версии фиксировать в отдельном auth-PR, не писать собственную
криптографию. Это базовая рекомендация [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
а не подтверждённый замер RAM текущей инфраструктуры.

Сессия: случайный непрозрачный токен 32 байта из CSPRNG; в SQLite только его
SHA256 (это случайный токен, не пароль), employee/credential ID, issued/expiry/
revoked times и credential version. При входе — новый токен, старый не принимается
для фиксации сессии. Logout/revoke/password reset/deactivate отзывают сессии.
Никаких токенов в URL, localStorage, логах или frontend-конфигурации.

Cookie: `__Host-planner_session`, HttpOnly, Secure, SameSite=Strict, Path=/,
без Domain. Web и API на одном HTTPS origin, без wildcard credential CORS.
Утверждённые сроки: **90 дней от входа** абсолютно и **30 дней без посещений**.
Посещения не продлевают абсолютный срок. Cookie постоянная, Max-Age/Expires
ограничен исходной абсолютной границей. Краткое бездействие, закрытие браузера
и выключение компьютера не завершают сессию. Polling/health не считаются посещением.
Протокол foreground-посещений и частота записи last_visited ещё проектируются.
История: предложенные 12 часов / 30 минут отменены 21.10.2026.
Чувствительные действия руководителя требуют повторного подтверждения пароля.
Очистка истёкших сессий ограниченными пакетами. Роль из сессии не кешировать.
Основание: [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

## CSRF и ограничение входа

Сессионный synchronizer CSRF token, выдаваемый same-origin endpoint и передаваемый
в X-CSRF-Token для POST/PATCH/DELETE. Проверять Origin и Fetch Metadata; не
принимать мутации через GET или простые cross-origin формы. SameSite не заменяет
CSRF. Для login — отдельная короткая pre-auth cookie/CSRF пара, защита от login
CSRF; ротация после входа. Никакого cookie-only обхода в Telegram endpoints.
См. [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

Предлагаемая начальная политика, подлежит согласованию/нагрузочным тестам:
5 неудач на нормализованный login за 15 минут и 20 на IP, ограниченная задержка,
429/Retry-After без бесконечного глобального блокирования сотрудника. Счётчики
общие для процессов, не Python dict. Только доверенный proxy может задавать IP;
иначе использовать peer address. Равный ответ для неизвестного/отключённого
login, dummy hash-проверка, не раскрывать существование учётки. Ограничить размер
полей/тела и число одновременных Argon2 вычислений до дорогостоящей проверки.

## Предлагаемые API и таблицы

| Будущий API | Доступ и действие |
|---|---|
| GET /api/web/auth/csrf | Короткий pre-auth контекст, без данных сотрудников |
| POST /api/web/auth/login | CSRF + rate limit, выдача новой сессии |
| GET /api/web/auth/me | Валидная сессия, актуальная роль/active |
| POST /api/web/auth/logout | CSRF, отзыв текущей сессии, удаление cookie |
| POST /api/web/auth/password | CSRF, старый пароль/повторная проверка, отзыв сессий |
| GET/POST /api/web/accounts | Только supervisor, привязка к существующему employee |
| PATCH /api/web/accounts/{id} | Только supervisor, отключение web-учётки |
| POST /api/web/accounts/{id}/reset | Supervisor с повторным вводом пароля, отзыв всех сессий |
| /api/web/plans, tasks, requests… | Тот же Store и те же полномочия объектов |

Принцип additive schema5 в одной planner.db утверждён; точный DDL ещё проектируется.
Предлагаемый состав: web_credentials(employee_id UNIQUE FK,
login_normalized UNIQUE, password_hash, active, credential_version, timestamps),
web_sessions(token_hash PK, credential FK, created/last_seen/expires/revoked),
ограниченная таблица login_attempts и auth_audit без паролей/cookie. Индексы для
expired/token/account lookup. Роли в credentials не хранить. Не перезаписывать
employees/старые планы/задачи/таймеры/отчёты/аудит и не создавать второй планировщик.
Тестовая миграция 4→5 должна быть транзакционной, повторяемой и с rollback при
внедрённом сбое. Существующий код, допускающий только schema≤4, не сможет открыть
5. Утверждён порядок: сначала проверенный backend bridge для schema4+schema5,
потом отдельно разрешённая production-миграция после backup/restore trial.
Основной откат — bridge с актуальной БД, не исходный 2.1.1 и не старая копия.
На foundation-этапе миграция изолирована и запускается явно лишь на синтетических
БД; Store.initialize, рабочая SCHEMA_VERSION=4 и guard новой схемы не меняются.
Также проектируется web_password_actions для одноразовых invitation/reset.

Bootstrap первого web-supervisor — отдельная локальная защищённая админ-команда
в согласованное окно, не публичная регистрация. Руководитель не меняет роль
через web credential API, не создаёт произвольного supervisor и не сбрасывает
чужие supervisor credentials через manager CRUD. Защитить последний доступный
supervisor от потери входа. Bootstrap/recovery — пока техническое предложение.
Утверждено: supervisor создаёт учётки существующим manager, инициирует reset
после подтверждения собственного пароля; одноразовый reset-код — 30 минут.
Менеджер сам выбирает постоянный пароль, руководитель его не видит. Reset
немедленно делает старый пароль недействительным, отзывает все web-сессии
и запрещает обычный вход до самостоятельной установки менеджером нового
пароля по действующему одноразовому коду (30 минут). Аудит — без пароля/кода.
Уточнение от 21.10.2026: reset_pending или эквивалент — проверяемое логическое
состояние; конкретный столбец/DDL пока не утверждён. Истечение кода не разрешает
вход старым паролем; повторный сброс аннулирует прежние неиспользованные коды.
Смена состояния, инвалидирование пароля, отзыв сессий и создание нового кода
с отменой прежних выполняются атомарно, при ошибке — полный rollback.
Login/reset сериализуются: проверка пароля до reset не позволяет после reset
выдать действующую сессию. Погашение кода атомарно меняет пароль, отмечает код
использованным и снимает reset_pending; повтор кода запрещён. Прочие active/role
ограничения сохраняются. Telegram-доступ, история, планы, задачи и таймеры
не меняются. Это контракт будущей реализации, не существующий API.
Доставка секрета,
отдельный TTL приглашения и recovery supervisor требуют согласования.

## Обязательные тесты перед реальными данными

- Оба manager и supervisor; IDOR для чужих планов/задач/requests/reports/notices.
- Актуальные role/active проверяются на каждом запросе; bot ACL влияет только
  на Telegram, web без Telegram ID работает; admin бота не supervisor.
- Границы 90/30 дней, посещения/polling, сохранение cookie после закрытия браузера,
  replay revoked session, fixation, reset/logout/revoke в нескольких процессах.
- Cookie flags; отсутствие хранения токенов на frontend; wrong/missing CSRF и Origin,
  login CSRF, попытка cookie в Telegram API и initData в web API — отказ.
- Rate limit для неизвестных/активных/отключённых login, IP spoofing, concurrency,
  контроль CPU/RAM/SQLite locks и отсутствие account enumeration.
- SQL/HTML injection, ошибки БД/хеширования без утечки секретов, auth audit.
- Миграция только синтетической schema4 с сохранением всех прежних сущностей, повтор,
  прерванный запуск, backup/restore и реалистичный откат с последующими записями.
- Общий серверный таймер между Mini App и web, stale mutations/revisions,
  confirm idempotency, locked imported targets, closed reports immutability.

Открыты технические параметры: rate/concurrency/retention, password/hash library
и замеры RAM, login normalization, visit protocol, bootstrap/recovery, доставка
секрета/приглашения, sensitive-action reauth protocol, точный DDL и HTTPS origin.
Независимость каналов, 90/30 дней, manager reset и порядок bridge уже утверждены.
Референсы визуального shell приняты; памятка новичков и CRM-контракт относятся
к отдельным будущим функциям. Документ не разрешает миграцию или установку.
