# Проект web-авторизации — на согласование, без реализации

21.10.2026. Ни endpoints, ни таблицы, ни миграции из этого документа не созданы.
Текущий прототип изолирован; production API по-прежнему требует Telegram HMAC.
Внедрение — отдельный небольшой PR после принятия архитектуры и политики доступа.

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

**Открытая политика:** нынешний Telegram actor дополнительно проверяет access.db.
Нельзя молча исключить эту проверку для нового канала. Для первого web-релиза
предлагается сохранить текущий ACL для уже привязанных сотрудников; доступ
сотрудников без Telegram-привязки и отделение web-доступа от bot ACL требуют
явного решения. Нельзя технически подменять web-вход фиктивным initData.

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
Предлагаемые сроки на согласование: 30 минут бездействия, 12 часов абсолютный
срок. Обновление last_seen группировать, чтобы не писать SQLite каждую секунду.
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

Возможная schema 5, ещё не утверждена: web_credentials(employee_id UNIQUE FK,
login_normalized UNIQUE, password_hash, active, credential_version, timestamps),
web_sessions(token_hash PK, credential FK, created/last_seen/expires/revoked),
ограниченная таблица login_attempts и auth_audit без паролей/cookie. Индексы для
expired/token/account lookup. Роли в credentials не хранить. Не перезаписывать
employees/старые планы/задачи/таймеры/отчёты/аудит и не создавать второй планировщик.
Тестовая миграция 4→5 должна быть транзакционной, повторяемой и с rollback при
внедрённом сбое. Существующий код, допускающий только schema≤4, не сможет открыть
5: откат образа/базы нужно проектировать отдельно с сохранением новых записей.

Bootstrap первого web-supervisor — отдельная локальная защищённая админ-команда
в согласованное окно, не публичная регистрация. Руководитель не меняет роль
через web credential API, не создаёт произвольного supervisor и не сбрасывает
чужие supervisor credentials через manager CRUD. Защитить последний доступный
supervisor от потери входа. Одноразовый reset secret — не в аудит/URL; механизм
доставки и необходимость must_change_password нужно отдельно согласовать.

## Обязательные тесты перед реальными данными

- Оба manager и supervisor; IDOR для чужих планов/задач/requests/reports/notices.
- Смена/отключение роли и bot ACL действует на следующем запросе; admin бота не supervisor.
- Expiry, idle, replay revoked session, fixation, reset/logout/revoke в нескольких процессах.
- Cookie flags; отсутствие хранения токенов на frontend; wrong/missing CSRF и Origin,
  login CSRF, попытка cookie в Telegram API и initData в web API — отказ.
- Rate limit для неизвестных/активных/отключённых login, IP spoofing, concurrency,
  контроль CPU/RAM/SQLite locks и отсутствие account enumeration.
- SQL/HTML injection, ошибки БД/хеширования без утечки секретов, auth audit.
- Миграция на временной копии с сохранением всех прежних сущностей, повтор,
  прерванный запуск, backup/restore и реалистичный откат с последующими записями.
- Общий серверный таймер между Mini App и web, stale mutations/revisions,
  confirm idempotency, locked imported targets, closed reports immutability.

До реализации согласовать ACL без Telegram, сроки сессий/лимиты, bootstrap/reset,
HTTPS-origin и референсы дизайна; получить полную памятку новичков и контракт
CRM-событий. Этот документ не является разрешением на миграцию или установку.
