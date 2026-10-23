# Единая авторизация — результаты локальных проверок

Дата: 23.10.2026. Это проверка ограниченного PoC, не production-авторизации.
Архитектура, матрица ролей, crosswalk, PostgreSQL-план и будущий cutover описаны
в `UNIFIED_AUTH_INTEGRATION.md`.

## Источники и изменения

- Planner base main: `6501ef264e17f8a8c2ff166515a014c7c843b47c`.
- Planner PR №6 остаётся открыт, HEAD `7cc780818a71b22b19d5db1cab7d6e697839aa41`.
- LeadFlow master: `d3e461f89532b997e8f236ae77f1fd15ed5515c9` (удалённая сверка).
- LeadFlow local-only branch `feature/unified-auth-poc`, commit `837fbbfdb5d058fa4a9c15d20723cbcd03f969ef`.
- Local clone: `C:\Users\user\Documents\ChatGPT\План дня\lead-flow-auth-poc`.
- Planner branch `docs/unified-auth-integration`, его commit/PR фиксируются в Git
  и итоговом сообщении после завершения. Main не меняется.

В LeadFlow **только 4 новых файла**, ни одного изменения прежних исходников:

1. backend/poc/__init__.py.
2. backend/poc/unified_auth.py.
3. backend/poc/run_checks.py.
4. backend/tests/test_unified_auth_poc.py.

Первый factory подключает исходный api_router и shared dependencies, не создаёт
новый login/hasher/JWT/session store. Два GET возвращают лишь текущую identity и
результат supervisor-role gate. Второй factory/worker/deployment не запускается;
app.main и workflows не изменены. Отсутствие runtime routes проверено тестом.

В Planner **7 файлов**:

1. PROJECT_MASTER_KNOWLEDGE.md — новое направление и границы/история.
2. WEB_AUTH_ARCHITECTURE.md — новое решение с пометкой заменённого SQLite-плана.
3. WEB_AUTH_NEXT_STAGE.md — актуальная последовательность и исторический план.
4. UNIFIED_AUTH_INTEGRATION.md — архитектурная сверка.
5. UNIFIED_AUTH_TEST_REPORT.md — этот отчёт.
6. tests/test_unified_auth_boundary.py — 2 теста cookie/HMAC separation.
7. review/leadflow-unified-auth-poc.patch — локальный review diff, не активный код Planner.

Patch SHA256: `3b891033d69ffb455dbe5362b38c635624c162496257f59e8b96c99d381710c3`.
Patch получен git diff --binary --full-index master HEAD локальной копии LeadFlow.
Проверка применимости к d3e461f — git apply --reverse --check на локальном HEAD;
никаких реальных файлов этим check не меняют. Не применять к другой версии вслепую.
Никакого push/PR/merge в LeadFlow нет; для публикации нужно отдельное согласование
владельца. В Planner не создан альтернативный auth backend.

## Реальные результаты

| Набор | Результат |
|---|---|
| LeadFlow backend existing + PoC | 28 passed:14 прежних+14 новых parametrized cases; pytest12.32 с, safe runner 14.65 с |
| LeadFlow Ruff | check всего backend, включая PoC: OK |
| LeadFlow frontend Vitest | 19/19 passed,4 test files |
| LeadFlow ESLint | OK |
| LeadFlow TypeScript/Vite build | OK; Vite8.2.1,1812 modules,3 production assets |
| Planner полный Python-набор | 190 OK,32.776 с,0 skips/failures/errors (188 прежних+2 новых) |
| git diff --check | Без ошибок в обоих репозиториях; повторяется перед публикацией Planner |
| npm ci | Из существующего package-lock; исходный lockfile не менялся; audit не отключался |
| npm audit | 7 замечаний:5 high,2 moderate,0 critical; без автоматических fix/updates |
| PostgreSQL integration | НЕ ВЫПОЛНЕНО: нет изолированного PG/Docker/psql/initdb в доступной среде |
| Production/VPS/реальные БД/CRM/Telegram | НЕ ВЫПОЛНЕНО, не подключались |

Planner тестируется на main+текущем regression evidence. 53 теста открытого PR №6
в эту ветку намеренно не перенесены: его принятие не симулируется и прежний отчёт
241 tests не выдаётся за текущий запуск. PR №6 остаётся отдельной веткой/артефактом.
Frontend Planner не менялся и заново не тестировался; это не общий UI-release.

## Что именно доказывает PoC

- Реальный исходный pwdlib verifier, JWT issuance, Secure/HttpOnly-cookie и
  get_current_user; auth dependency не mock-заменена. Подменён только get_db
  временной SQLAlchemy SQLite :memory: fixture; реальные users не использованы.
- Один login и одна cookie дают LeadFlow /auth/me и /planner-poc/identity, без
  повторного пароля/отдельного token. Актуальные role/is_active читаются из users.
- Неверные пароль/email, unknown/inactive, fake/expired JWT и missing cookie —401.
- Manager не получает supervisor-check и не может users API; extra role/query
  user_id не определяют текущую identity. Другой manager's lead закрыт исходными tests.
- Supervisor gate разрешён только роли supervisor, downgrade в БД виден сразу.
  Admin сохраняет свои LeadFlow users API, но role=admin не alias planner-supervisor.
- Telegram-заголовки без cookie не становятся web-auth; LeadFlow cookie без HMAC
  не авторизует Planner; cookie не повышает Telegram manager до supervisor.
- Ответы не содержат password/hash/JWT, проверенные logs не содержат введённого
  тестового пароля/токена. Полный аудит всех production log sources здесь не выполнен.
- Logout удаляет browser cookie. Повтор сохранённого JWT снова проходит:
  это **проверенный inherited gap**, а не server revoke. 90/30/reset/CSRF/visit
  специально не выдаются за реализацию этого этапа.

SQLite fixture не проверяет PostgreSQL DDL, FK, locks, timezone, isolation или
Alembic migrations. Не выполнялись реальные 90-дневные browser lifecycle tests,
общий React интерфейс, foreground protocol, password reset и concurrent PG login/reset.

## Среда и воспроизведение

Windows, Python3.14.7, Node24.22.1, npm11.21.1 установлен только в отдельном
каталоге проверок. Зависимости Python — отдельная .venv внутри копии LeadFlow,
окружение Planner не менялось. Pyproject/lockfiles в LeadFlow не модифицированы.

| Пакет локального backend | Версия |
|---|---|
| fastapi / starlette | 0.161.1 /1.9.0 |
| sqlalchemy | 2.1.6 |
| PyJWT | 2.15.1 |
| pwdlib /argon2-cffi | 0.3.1 /25.1.0 |
| pytest /ruff | 8.4.2 /0.17.2 |
| psycopg /alembic | 3.3.6 /1.20.1 (PG-сервер не использовался) |

Из backend копии LeadFlow:

```powershell
..\.venv\Scripts\python.exe -B -m poc.run_checks -o faulthandler_timeout=15
..\.venv\Scripts\ruff.exe check .
```

Из Planner:

```powershell
.\.venv\Scripts\python.exe -B -m tests.run_foundation_checks
```

Frontend проверялся существующими npm scripts: `npm test`, `npm run lint`,
`npm run build` после npm ci. Локально npm отсутствовал в PATH, поэтому CLI
вызван через node из отдельного `unified-auth-checks/node-tools/node_modules/npm`.
Для Vitest TEMP/TMP указывали на `unified-auth-checks`; конфиг тестов не менялся.

Ранний LeadFlow backend sandbox-прогон завис до тестов на внутреннем loopback
Windows/Python3.14; он прерван и не засчитан. Итоговый запуск выполнен с
разрешённым local loopback; runner при этом запрещал внешнюю сеть/DNS, чтение .env
и файловые SQLite. В Vitest первый sandbox TEMP дал EPERM rename и0 tests;
после назначения доступного TEMP все19 tests прошли. Тесты не ослабляли/не удаляли.
Два tracked tsbuildinfo, созданные frontend build, восстановлены точно к master;
исходники остались нетронутыми. По исходникам не исправляли A01–A25 или LeadFlow auth.

JSON результатов и полный pip metadata/служебные npm caches — только в локальном
`C:\Users\user\Documents\ChatGPT\План дня\unified-auth-checks`, не в Git/release.
Тестовый JWT secret создавался случайно в процессе и не записывался в отчёт/файлы.
Bootstrap/worker/migrate/deploy не выполнялись, сервер/публичные порты не запускались.
Starlette сообщил deprecation httpx TestClient; зависимости не обновлялись ради
скрытия предупреждения, а устанавливались по существующему pyproject диапазону.

## Найденные npm advisories

По текущему registry audit и **неизменённому** package-lock. Количество package
entries не равно количеству отдельных advisories. Применимость к production
объединённого продукта надо отдельно оценить; автоматический force fix запрещён.

- @vitest/mocker — moderate; [advisory](https://github.com/advisories/GHSA-82fw-gwwq-j7x9), [advisory](https://github.com/advisories/GHSA-qxg6-89mg-rqv8).
- brace-expansion — high; [advisory](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr), [advisory](https://github.com/advisories/GHSA-qhr7-859c-m2p7).
- nanoid — high; [advisory](https://github.com/advisories/GHSA-2v37-7h3g-55p8).
- source-map-js — high; [advisory](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).
- undici — high; [advisory](https://github.com/advisories/GHSA-3wwx-pv8p-q78v), [advisory](https://github.com/advisories/GHSA-pmjh-fq2x-6v4x).
- vite — high; [advisory](https://github.com/advisories/GHSA-698v-4r3x-3vcv), [advisory](https://github.com/advisories/GHSA-r825-w8mm-5pxw).
- vitest — moderate; [advisory](https://github.com/advisories/GHSA-82fw-gwwq-j7x9).

## Следующие блокирующие решения для production

Право публикации PoC в LeadFlow; admin/role-assignment/командные права;
операторское соответствие реальных сотрудников/active конфликтов; PG sessions90/30,
server revoke/reset_pending/CSRF/visit и все альтернативные password setters;
PG schema/migrations/backup+restore/load; проверенный current-data rollback;
dependency lock/audit hardening. Отдельный production release не разрешён.

## Точные backend test IDs LeadFlow

- `tests/test_api.py::test_login_and_current_user` — passed.
- `tests/test_api.py::test_login_is_rate_limited_after_repeated_failures` — passed.
- `tests/test_api.py::test_logout_clears_session` — passed.
- `tests/test_api.py::test_admin_can_create_user_and_lead` — passed.
- `tests/test_api.py::test_manager_sees_only_own_leads` — passed.
- `tests/test_api.py::test_manager_cannot_manage_users_or_create_leads` — passed.
- `tests/test_api.py::test_leads_are_automatically_balanced_between_available_managers` — passed.
- `tests/test_api.py::test_day_off_excludes_manager_from_distribution` — passed.
- `tests/test_api.py::test_auto_distribution_fails_when_no_manager_is_available` — passed.
- `tests/test_bitrix_sync.py::test_bitrix_sync_abandons_lead_after_max_attempts` — passed.
- `tests/test_bitrix_sync.py::test_bitrix_sync_throttles_and_batches_create_pending_leads` — passed.
- `tests/test_bitrix_sync.py::test_bitrix_sync_throttles_and_batches_monitor_entities` — passed.
- `tests/test_bitrix_sync.py::test_bitrix_sources_creation_and_lead_to_deal_monitoring` — passed.
- `tests/test_config.py::test_warns_on_default_secrets` — passed.
- `tests/test_config.py::test_no_warning_for_custom_secrets` — passed.
- `tests/test_unified_auth_poc.py::test_one_original_login_unlocks_leadflow_and_planner_identity` — passed.
- `tests/test_unified_auth_poc.py::test_wrong_or_unknown_login_never_gets_cookie_or_probe[manager@testing.example.com-not-the-password]` — passed.
- `tests/test_unified_auth_poc.py::test_wrong_or_unknown_login_never_gets_cookie_or_probe[unknown@testing.example.com-password123]` — passed.
- `tests/test_unified_auth_poc.py::test_inactive_at_login_and_disabled_after_login_deny_both_modules` — passed.
- `tests/test_unified_auth_poc.py::test_forged_or_expired_token_is_rejected[forged.invalid.token]` — passed.
- `tests/test_unified_auth_poc.py::test_forged_or_expired_token_is_rejected[expired]` — passed.
- `tests/test_unified_auth_poc.py::test_manager_cannot_claim_supervisor_or_read_another_identity` — passed.
- `tests/test_unified_auth_poc.py::test_supervisor_is_explicit_and_db_role_changes_apply_immediately` — passed.
- `tests/test_unified_auth_poc.py::test_admin_identity_does_not_grant_planner_supervisor` — passed.
- `tests/test_unified_auth_poc.py::test_no_cookie_and_telegram_initdata_are_not_web_auth` — passed.
- `tests/test_unified_auth_poc.py::test_logout_removes_browser_cookie_but_legacy_token_replay_is_a_known_gap` — passed.
- `tests/test_unified_auth_poc.py::test_auth_responses_and_logs_do_not_reveal_test_secrets` — passed.
- `tests/test_unified_auth_poc.py::test_probe_is_not_registered_in_production_app` — passed.

## Frontend test cases LeadFlow

- `AuthProvider restores the session from the httpOnly cookie via /auth/me on mount` — passed.
- `AuthProvider shows anonymous when there is no valid session` — passed.
- `AuthProvider login stores the user returned by the backend without a second round-trip` — passed.
- `AuthProvider logout clears the local user even if the backend call fails` — passed.
- `StatusBadge renders the Russian label and CSS class for status "pending"` — passed.
- `StatusBadge renders the Russian label and CSS class for status "synced"` — passed.
- `StatusBadge renders the Russian label and CSS class for status "failed"` — passed.
- `StatusBadge renders the Russian label and CSS class for status "abandoned"` — passed.
- `api sends credentials so the httpOnly session cookie is included` — passed.
- `api returns parsed JSON on success` — passed.
- `api returns undefined for 204 responses` — passed.
- `api throws ApiError with the string detail from a plain HTTPException` — passed.
- `api formats a Pydantic validation error array into a readable string` — passed.
- `api unauthenticated redirect redirects to /login on 401 for a regular request` — passed.
- `api unauthenticated redirect does not redirect on 401 from the initial /auth/me check` — passed.
- `dateTime returns a dash for null` — passed.
- `dateTime formats an ISO date string` — passed.
- `roleLabels has a Russian label for every role` — passed.
- `syncLabels has a label for every sync status including abandoned` — passed.

## Новые проверки Planner

- tests.test_unified_auth_boundary.TelegramBoundaryTests.test_leadflow_cookie_cannot_replace_telegram_hmac — OK.
- tests.test_unified_auth_boundary.TelegramBoundaryTests.test_cookie_does_not_elevate_a_valid_telegram_manager — OK.

Прежние188 покрывают bot/distribution/Bitrix mocks/ACL/Telegram HMAC/plans/timers/
goals/import/release/foundation. Полный190 test IDs сохранён в локальном
`test-artifacts/foundation-full-results.json`; предыдущий foundation report содержит
исторический перечень188, не утверждение о текущем production.
