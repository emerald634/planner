# Schema5 compatibility bridge — технический отчёт

Дата: 21.10.2026. Ветка `feature/schema5-compatibility`.
Исходный SHA main: `6501ef264e17f8a8c2ff166515a014c7c843b47c` (PR №5 Merged).
Новый SHA/PR указываются в Git/итоговом сообщении; артефакт ссылается на свой
чистый source commit, а не на последующие уточнения отчёта.

**Результат: локальный bridge-кандидат, не web-auth, не production-релиз.**

## Изменённые файлы

- `planner/store.py`
- `planner/backup.py`
- `planner/schema5_compatibility.py`
- `planner/web_auth/validation.py`
- `planner/web_auth/migration.py`
- `deploy/package_release.py`
- `deploy/release_check.py`
- `tests/run_foundation_checks.py`
- `tests/test_web_auth_migration.py`
- `tests/test_schema5_compatibility.py`
- `tests/test_schema5_release.py`
- `PROJECT_MASTER_KNOWLEDGE.md`
- `WEB_AUTH_NEXT_STAGE.md`
- `WEB_AUTH_ARCHITECTURE.md`
- `SCHEMA5_BRIDGE_RELEASE.md`
- `SCHEMA5_COMPATIBILITY_REPORT.md`

## Store и строгая schema5

SCHEMA_VERSION остаётся **4** как цель прежних бизнес-миграций. Пути 0→1→2→3→4
не изменены. На 4 повторный startup не меняет строки/структуру и не создаёт
web-таблиц. На 5 Store внутри существующей транзакции проверяет явную capability
schema5_compatibility и выполняет read-only validate_schema5, затем return.
Не вызывает migrate_synthetic, не ремонтирует, не снижает user_version, не
пересоздаёт таблицы и не запускает web-auth. Остальные бизнес-методы Store,
planner/api.py, HMAC/ACL, таймерные правила (включая A11) не переписывались.

Валидатор вынесен из web_auth/migration.py в web_auth/validation.py. Старое имя
MigrationError импортируется обратно для совместимости foundation-тестов.
Проверяется фактический user_version; точные sqlite_master объекты включая SQL,
CHECK/UNIQUE/FK/индексы/триггеры; registry 2,3,4,5; details5 с checksum известного
DDL; integrity_check и foreign_key_check. Ошибка завершает startup с rollback
транзакции без автоматического исправления. Более новые 6/999 не допускаются.
DDL и checksum foundation не менялись. schema.py при импорте строит ожидаемый
manifest в отдельной :memory: БД, а не в файле приложения.

Это узнавание конкретного проекта schema5, не всех возможных schema5. При
изменении DDL в будущих auth-PR bridge нужно пересогласовать/перепроверить до
production migration. Физический reset_pending по-прежнему review-only.

## Исторические варианты

Синтетически созданы исходные 0/1/2/3; их поддерживаемые миграции дают точный
BASELINE_OBJECTS schema4. После явной synthetic 4→5 bridge повторно открывает БД,
все старые строки и структуры сохраняются. Различий легитимного SQL manifest
в этих сценариях не найдено; дополнительных «похожих» схем не разрешали.

Статически, без исполнения архивного кода и без открытия SQLite, через AST
сравнен SCHEMA в семи старых локальных source-архивах: 2.1.1 rc1; два stage1
20261013; stage1-production-v2; v3-prebuilt-check; v3-prebuilt; stage2-v1.
Начальный SCHEMA во всех совпал. Это не исследование фактической production
БД и не гарантия отсутствия иных SQL/SQLite-version вариантов на новом VPS.

## Бизнес-функции и сохранение auth

41 прежний testcase API/confirmation/import/sync повторяется в subclass-наборах
с исходной schema5. В каждый fixture заполнены все пять auth-таблиц; после
каждого testcase сверяется их полное содержимое. Некоторые унаследованные
legacy migration-тесты дополнительно создают собственные старые БД; их наличие
не выдаётся за дополнительную API-проверку schema5. Исходные наборы на 4 тоже
выполнены в полной регрессии.

Покрыты HMAC/ACL, manager own/foreign, supervisor, inactive, bot-admin≠supervisor,
CRUD/факт/revision, imported target lock, goal approval, manager confirm,
история, закрытие и immutable report; timer start/pause/resume/finish/reopen и
unique running timer; очередь1/import/repeat/review/initiator/restart/retry.
Функции используют те же Store-правила. Никаких реальных запросов Telegram/CRM.

Web API не добавлен. Cookie без initData даёт 401 на /api/me; /api/web/auth/* и
/api/web/accounts отсутствуют (404). В рабочий bridge-пакет не включены
web_auth models/policy/migration; только __init__, schema, validation. Наличие
credential/session/action данных само по себе web-вход не включает. Auth-таблицы
не удаляются и не очищаются при возврате bridge.

## Полный синтетический сценарий отката

1. Синтетическая 4 со всеми бизнес-сущностями открыта bridge без изменений.
2. Только тест явно выполняет foundation migration, создаёт fake auth-записи.
3. На 5 добавлены новые планы/задачи, подтверждение/согласованная цель, факт,
   комментарии, timer events и закрытый immutable report; отдельный новый таймер
   оставлен работающим.
4. Новый Store открывает **тот же актуальный файл 5**. Все исторические строки
   и новые записи сохранены; доступен новый report/history и работающий таймер.
   Старый schema4 backup не используется. Auth snapshot и user_version=5 неизменны.
5. Через прежний Telegram API после возврата проверены чтение нового плана/отчёта,
   новая запись и HMAC; web login отсутствует.
6. При открытом SQLite-соединении и конкурентных бизнес-записях выполнен SQLite
   Backup API, verify SHA256/FK/integrity, restore в новый каталог. Report/history,
   текущий timer и все auth-таблицы сохранены. В восстановленной 5 выполняется
   новая запись. Повтор restore в существующий файл получает отказ.

Во время конкурентного backup снимок может быть до или после части конкурентных
commit: это консистентный снимок, не обещание включить все будущие записи.
Бизнес-snapshot восстановленного файла сравнивается именно с backup; исходный
файл остаётся актуальным и не перезаписывается.

## Backup API

Поддержка schema1–4 сохранена (отдельные backup/verify/restore проверки всех версий).
На 5 — тот же строгий валидатор, без миграции источника/копии. Неизвестная,
частичная, изменённая и FK-invalid 5 отвергается и Store, и backup. Queue1 и её
функции не менялись, покрыты прежними тестами. SHA256, Backup API, fsync, FK/
integrity и O_EXCL назначения сохранены; live database обычной копией не копируется.
Проверка permissions в Windows моделирует отказ соединения и read-only SQLite,
не доказывает POSIX UID/GID или Docker mount права.

## Проверки

Среда: Windows, Python 3.14.7, SQLite 3.50.4.

```powershell
.\.venv\Scripts\python.exe -B -m tests.run_foundation_checks --bridge
.\.venv\Scripts\python.exe -B -m tests.run_foundation_checks
```

| Категория | Результат |
|---|---|
| Локально: ранний bridge-набор | 53 OK, 11.845 с |
| Локально: полный Python-набор | 241 OK, 31.287 с, без skips/errors/failures |
| Локально: legacy release tests | planner-only 2.1.1 и stage2 сохранены; bridge отличим отдельным ID/profile |
| Локально: extracted synthetic package smoke | Bridge на 4/5 с backup, legacy package отвергает 5; никаких web/migration imports |
| Статически | Архивные SCHEMA, Docker COPY planner включает подпакет; новых deps/маршрутов/изменений HMAC нет |
| Не выполнялись | Linux/WSL/Docker Engine, runtime Python 3.12, реальные WebView/CRM/VPS, OOM/load/power-loss |
| Перед production | Review DDL и bridge; Linux/Python3.12/Docker/mount smoke, свежая сверка VPS, backup/restore trial и отдельное разрешение |

Runner запрещает внешний socket/DNS, рабочие .env и SQLite вне synthetic scratch
(кроме :memory:); все subprocess-тесты исполняют фиксированные import/DB сценарии
на новых временных данных. К production не подключались. Frontend по функционалу
не менялся; локальная production-сборка для архива описывается ниже, browser
сценарии не запускались. Starlette предупреждает о будущем httpx/TestClient
изменении; зависимости из-за этого не менялись. Audit A01–A25 не исправлялись.

## Локальный rollback-артефакт

Профиль `--bridge`, identity `schema5-compat-v1`, release ID
`planner-schema5-bridge-rc1-20261021`. Планируемый архив:
`deployment-artifacts/planner-schema5-bridge-rc1-20261021.tar.gz`.

<!-- ARTIFACT_RESULT_START -->
На момент исходного коммита архив ещё не собран: требуется чистый commit.
После реальной сборки сюда будут добавлены source SHA, SHA256 и результат smoke.
Не считать этот промежуточный статус готовым rollback-артефактом.
<!-- ARTIFACT_RESULT_END -->

Профиль выполняет offline frozen install + pnpm run build без отключения security,
проверяет source hashes/lockfile/production assets, создаёт archive/checksums/file
manifest с Git SHA и отдельной identity; не перезаписывает старые файлы. Внутренний
checker требует полный bridge runtime и согласованные frontend/release metadata.
`planner_schema=4` означает цель бизнес-миграций; `supported_planner_schemas=[4,5]`
— возможности, не свидетельство фактически применённой миграции.

Legacy профили специально не включают schema5_compatibility.py/web_auth. Store
и backup в таком пакете при 5 безопасно отказывают (модуль capability отсутствует),
как прежде. Поэтому не возникает нового bridge под именем 2.1.1. Это явная
capability упаковки, а не env-переключатель авторизации. Bridge требует все read-
only модули в manifest; отсутствие модуля с заново подсчитанными хешами — отказ.
Пакет не содержит bot entrypoint, .env, SQLite, реальных токенов, клиентских данных,
backup архивов или frontend demo/maps. Исходный 2.1.1 архив не пересобирался.

## Известные риски и дальнейший порядок

- Строгий SQL manifest может отвергнуть неизвестный, хотя семантически похожий
  legacy вариант. Не ослаблять его без review; источник production не исследован.
- Startup/backup выполняют integrity/FK scans; фактическая длительность/память
  на большой БД и VPS с 2 ГБ не измерены. Нет новых retries/очисток/фоновых задач.
- DDL всё ещё проект, checksum узкий; будущий auth DDL потребует нового bridge review.
- Это локальный rollback-кандидат с исходниками и готовой статикой, не собранный
  Linux Docker image. До его установки/использования как rollback нужны проверки
  целевой среды и согласование. Docker/Nginx/DNS/контейнеры не менялись.
- При отказе после future migration сохраняют актуальную БД и auth-аудит. Возврат
  старой копии требует отдельного плана сверки новых записей и не является
  основным rollback. Прямого downgrade 5→4 нет.
- Пароли/сессии/HTTP API/CSRF/cookies остаются будущими PR; bridge их не включает.
  Не начинать следующий auth этап автоматически. После PR остановиться на review.

## Точный перечень дополнительных bridge-тестов

Каждый ID ниже прошёл в полном наборе; наследуемые случаи специально повторены
в schema5 fixture, а не засчитаны как новые функции. Старые 188 test IDs доступны
в предыдущем foundation-отчёте; локальный JSON полного прогона хранится в
`test-artifacts/foundation-full-results.json` и не включается в release/Git.

- `tests.test_schema5_compatibility.BridgeBoundaryTests.test_corrupt_file_readonly_connection_and_busy_startup`
- `tests.test_schema5_compatibility.BridgeBoundaryTests.test_schema4_startup_is_noop_and_does_not_load_migration`
- `tests.test_schema5_compatibility.BridgeBoundaryTests.test_supported_historical_paths_have_exact_same_schema4_manifest`
- `tests.test_schema5_compatibility.BridgeBoundaryTests.test_unknown_incomplete_modified_manifest_registry_fk_are_refused_without_repair`
- `tests.test_schema5_compatibility.BridgeBoundaryTests.test_web_disabled_even_with_credentials_cookie_and_valid_telegram`
- `tests.test_schema5_compatibility.BridgeRollbackBackupTests.test_backup_restore_schema1_to4_without_migration`
- `tests.test_schema5_compatibility.BridgeRollbackBackupTests.test_rollback_current_schema5_new_records_auth_and_live_backup_restore`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_concurrent_confirm_only_one_event`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_confirm_own_repeat_preserves_snapshot_time_history_and_role`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_copy_skips_imported_but_keeps_other_tasks`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_disabled_manager_denied_and_other_goals_use_approval`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_execution_and_time_approval_continue_after_confirmation`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_foreign_supervisor_closed_unauthorized_and_old_approve`
- `tests.test_schema5_compatibility.Schema5ConfirmationTests.test_imported_target_all_roles_requests_move_delete_and_forgery`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_approved_and_closed_unchanged_review_not_success`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_authorization_is_explicit_not_manager_or_supervisor_role`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_existing_draft_preserves_tasks`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_failure_mid_import_rolls_back_then_retries`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_inactive_blocks_whole_snapshot`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_migration_failure_rolls_back_schema`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_one_day_conflict_and_concurrent_duplicates`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_queue_cannot_initialize_planner_or_modify_other_database`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_queue_read_missing_never_creates_and_append_only`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_reject_wrong_stage_duplicate_lead_dates_binding_and_counts`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_roundtrip_repeat_restart_and_actual_initiator`
- `tests.test_schema5_compatibility.Schema5ImportTests.test_v2_migration_preserves_data_idempotent_and_backup`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_access_db_unchanged_and_roles_independent`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_closed_report_immutable_and_timers_stopped`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_concurrent_timers_and_stale_revision`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_copy_previous_weekday_resets_fact_and_preserves_lock`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_disabled_employee_and_missing_access_db_fail_closed`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_external_tasks_read_only_no_fake_statistics`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_goal_approval_old_target_and_audit`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_invalid_values_and_task_kind_and_mass_assignment`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_migration_is_idempotent_and_refuses_access_database`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_move_retains_fact_and_is_not_completion`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_no_public_auth_bypass_or_client_roles`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_owner_checks_every_plan_task_report_and_request`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_stale_goal_request_cannot_overwrite_new_supervisor_value`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_supervisor_task_lock_fact_edit_and_rejection`
- `tests.test_schema5_compatibility.Schema5PlannerTests.test_timer_restores_after_new_store_and_prevents_overlap`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_automatic_lifespan_missing_queue_then_recovery`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_bad_record_does_not_block_good_and_state_persisted`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_closed_plan_review_and_inactive_identity_not_exposed`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_commit_before_attempt_status_recovers_on_restart`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_notices_scoped_source_no_lead_ids`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_restart_parallel_and_read_only`
- `tests.test_schema5_compatibility.Schema5SyncTests.test_retry_after_transaction_failure`
- `tests.test_schema5_release.BridgeReleaseTests.test_bridge_metadata_complete_runtime_no_active_auth_and_no_overwrite`
- `tests.test_schema5_release.BridgeReleaseTests.test_disjoint_profile_and_release_ids`
- `tests.test_schema5_release.BridgeReleaseTests.test_extracted_bridge_import_startup_backup_without_migration_module`
- `tests.test_schema5_release.BridgeReleaseTests.test_legacy_profile_omits_bridge_and_rejects_schema5_in_extracted_runtime`
- `tests.test_schema5_release.BridgeReleaseTests.test_rehashed_missing_capability_and_wrong_identity_are_refused`
