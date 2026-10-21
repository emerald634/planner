# Отчёт: локальный web-auth-foundation

Дата: 21.10.2026. Ветка `feature/web-auth-foundation`.
Исходная main: `50ec7e8b909a6a5522a80eba08f8f31e3ce39c1b` — принятый PR №4.
Новый commit SHA и ссылка PR фиксируются в итоговом сообщении/самом PR после commit.
**Foundation реализован; рабочая web-авторизация и compatibility bridge отсутствуют.**

## Что реализовано

- Замороженные dataclasses Employee/Credential/Session/PasswordAction и закрытые enums.
  Нет доверенной роли в сессии, Telegram ID/ACL в web-модели или password verifier.
- Чистые policy: login/session eligibility, owner/supervisor scope, reauth prerequisite,
  foreground/background visit, reset transitions, purpose/expiry/replay/version checks.
  Время передаётся явно. 90 дней абсолютно / 30 дней без посещений, отказ на границе.
- Проект пяти auth-таблиц с PK/UNIQUE/FK/CHECK/индексами. Предлагаемый reset_pending
  плюс NULL password_hash и увеличение credential_version — решение для review,
  не окончательно принятая production-схема. Роли остаются в employees.
- Явная migrate_synthetic(connection, applied_at=..., checkpoint=...) без путей/env/CLI.
  Frozen schema4 manifest из вновь созданной synthetic БД; строгая проверка SQL-структуры,
  registry, integrity и FK. BEGIN IMMEDIATE, отдельные execute DDL, явные SQL COMMIT/
  ROLLBACK (включая autocommit=True), user_version и manifest одной транзакцией.
  Валидная schema5 — no-op, неизвестная/частичная/изменённая — отказ без ремонта.
- Синтетический transaction reference model сброса/погашения/выдачи сессии — **только
  в tests/web_auth_fixtures.py**. Моделирует устаревший результат verifier версией,
  не проверяет настоящий пароль и не является login-сервисом. Данные и секреты вымышлены.

Manifest checksum проекта auth DDL: `46f93cd3a01f628d45850103ae652db73f449543ee4fedbb69e5179077406187`.

## Изменённые файлы

- `planner/web_auth/__init__.py`
- `planner/web_auth/models.py`
- `planner/web_auth/policy.py`
- `planner/web_auth/schema.py`
- `planner/web_auth/migration.py`
- `tests/web_auth_fixtures.py`
- `tests/test_web_auth_foundation.py`
- `tests/test_web_auth_schema.py`
- `tests/test_web_auth_migration.py`
- `tests/run_foundation_checks.py`
- `PROJECT_MASTER_KNOWLEDGE.md`
- `WEB_AUTH_NEXT_STAGE.md`
- `WEB_AUTH_ARCHITECTURE.md`
- `WEB_AUTH_FOUNDATION_SPEC.md`
- `WEB_AUTH_FOUNDATION_REPORT.md`

Дополнительный `tests/run_foundation_checks.py` сверх исходного списка необходим
для воспроизводимого безопасного запуска общей регрессии. Других отклонений от
структуры модулей нет. Документы обновлены, поскольку PR №4 уже Merged; история
прежних решений сохранена. PROJECT_AUDIT.md не переписывался.

## Проверки и воспроизведение

Среда: Windows, Python 3.14.7, SQLite 3.50.4.
Без установки зависимостей, реальных токенов и внешней сети.

```powershell
.\.venv\Scripts\python.exe -B -m tests.run_foundation_checks --new
.\.venv\Scripts\python.exe -B -m tests.run_foundation_checks
```

| Итоговый запуск | Результат |
|---|---|
| Новые foundation suites | 35 OK, 1.835 с, без пропусков |
| Полный Python-набор | 188 OK, 21.733 с, без пропусков; прежние 153 + новые 35 |
| TypeScript / frontend build / browser | Не запускались; frontend не изменён |
| Docker / Linux / Ubuntu / реальная CRM | Не запускались, не подключались |
| git diff --check | Без ошибок; повторяется перед commit |
| Защищённые файлы | SHA256 девяти прежних .env/баз/архивов совпали; без открытия SQLite |
| Python 3.12 | AST grammar новых файлов проверена; настоящий runtime 3.12 не запускался |

Runner удаляет secret-like env в своём процессе, запрещает чтение рабочих .env,
внешние socket/DNS и SQLite вне временного test-artifacts/foundation-temp либо :memory:.
Read-only SQLite file: URI декодируется и проверяется по тому же пути; рабочие БД
не разрешены. Это дополнительная защита локальных тестов, не security boundary
для недоверенного кода. Дочерние процессы исполняют только фиксированные скрипты
synthetic migration/crash и import probe, без сети/секретов/production startup.
JSON с полным перечнем test IDs сохранён локально в игнорируемых
`test-artifacts/foundation-new-results.json` и `test-artifacts/foundation-full-results.json`.
Ни эти временные данные, ни логи/БД в Git не включаются.

Ранние прогоны не засчитываются: первый выявил запрет допустимых SQLite URI
в новом runner; при усилении новых DDL CHECK был обнаружен изменённый новый
baseline manifest. Исправлены только новые файлы, ожидаемая schema4 повторно
зафиксирована из чистой synthetic БД. Прогон с перенаправлением вывода завис
и был прерван; итоговые команды выше прошли без перенаправления. Незелёные
прогоны не выдаются за регрессию действующего бизнес-кода или успешные проверки.
Starlette вывел предупреждение о будущем отказе от httpx в TestClient;
зависимости по этому поводу не менялись.

## Миграция, rollback, конкуренция и сохранность

- Проверены 14 DDL statements и 18 checkpoint-точек: validated, каждый DDL,
  registry, version, before_commit. KeyboardInterrupt в каждой точке откатывает
  всю транзакцию: schema4, registry 2–4 и бизнес-данные остаются прежними.
- Отдельный процесс аварийно завершён до commit: reopen восстанавливает schema4.
  Аварийное завершение после commit: reopen видит полную schema5. Это тест process
  crash на Windows, не доказательство устойчивости диска при отключении питания.
- Два подключения в потоках и два отдельных процесса-мигратора: один True,
  второй валидированный no-op False, одна registry-строка версии 5.
- SQLITE_BUSY при занятой write lock: ограниченный отказ без частичного изменения;
  после освобождения lock повтор успешен. Timeout задаёт вызывающее тестовое соединение,
  не скрытая production-настройка.
- Повтор после успешной миграции и reopen сохраняет исходные applied_at/manifest.
  Включены sqlite3.Row и autocommit=True. Уже открытая caller-транзакция отвергается.
- Старый Store остаётся SCHEMA_VERSION=4, работает с 4 и по-прежнему отвергает 5.
  Отдельный import probe подтверждает, что planner.api не импортирует web_auth.
- Fixture содержит draft/approved/closed, задачи, работающий таймер, факт/комментарии,
  отчёт, goal_requests, audit/system_audit, distribution/tasks/leads/import_attempts,
  inactive сотрудника и прежний schema_migrations. Снимки всех старых таблиц
  сравнивают **полное содержимое**, колонки, SQL, FK и индексы/триггеры. Из прежних
  таблиц разрешена лишь новая registry-строка 5; все прочие строки неизменны.
  Autoincrement sequences в schema4 отсутствуют; будущие изменения baseline
  требуют отдельного review. Никакой рабочей БД или её копии в fixtures нет.

## Проверенные границы reset

Сразу после reset старый hash отсутствует, credential pending, все прежние
сессии отозваны; старый proof_version и pending login запрещены. Expiry кода
не восстанавливает вход. Повторный reset отзывает прежний код; использованный
код не погашается повторно, два конкурентных погашения дают один успех.
Сбой reset/redeem до commit полностью откатывает состояние/сессии/коды.
Проверены login до reset, конкурентные запросы и отложенный proof старой версии:
после reset commit нет живых старых сессий. Новый opaque hash разрешает модельный
вход лишь после корректного погашения при сохранённых active/role условиях.
Во всех транзакционных reset-тестах полный snapshot бизнес-данных неизменен.
Telegram HMAC/ACL не менялись и покрыты прежним полным regression-набором.

Реальный password verifier, HTTP-гонки, Secure cookie, CSRF, доставка кода,
проверка введённого пароля руководителя и протокол настоящего посещения здесь
**не реализованы/не проверены**. Булев reauth input в policy не является доказательством
пароля. Нельзя подключать reference model или fake hash markers к приложению.

## Отдельный следующий этап: schema5-compatibility

Технический план сохранён в WEB_AUTH_FOUNDATION_SPEC.md §6:

1. После review foundation и нового разрешения — отдельная ветка/PR bridge.
2. Проверять только известные schema4 и schema5 с manifest/FK/integrity; schema6,
   повреждённая/незнакомая 5 — отказ. Не снимать guard произвольных версий.
3. На 4 не создавать auth-таблицы при startup; на 5 не включать web-auth.
4. На synthetic 4 и 5 проверить прежние Telegram CRUD, импорт, таймеры, цели,
   закрытие дня и отчёты. Проверить 4 → 5 → новые бизнес-записи → возврат bridge
   с актуальной 5 без потери этих записей, backup/restore с активными соединениями.
5. Только после этого сохранить проверенный bridge artifact/SHA. Отдельно проверить
   Linux/Docker/UID/GID/mounts, Python 3.12, packaging подпакета и отказ web-доступа.
6. Auth API и тем более production-миграция — отдельные будущие решения после
   backup/restore trial. Исходный 2.1.1 не является откатным образом для schema5.

Foundation **готов к review**, после приёмки можно разрешить schema5-compatibility.
Это не production-ready web auth и не разрешение начать bridge автоматически.

## Открытые решения и ограничения

- DDL/reset_pending+NULL hash/version и строгий frozen SQL manifest пока review-only.
  Семантически эквивалентный, но иной SQL-формат/добавочный индекс сейчас отклоняется;
  совместимость с конкретным legacy baseline требует bridge review, не ослабления
  проверки вслепую. Не утверждены production миграция и recovery.
- Логин уже предполагается нормализованным: нормализация/Unicode/casefold ещё
  не выбраны. Нет неявного password hashing или небезопасного fallback.
- Rate/concurrency/retention, hash library/параметры, RAM на VPS, ограничение тела,
  bootstrap/recovery, доставка приглашений, reauth protocol и visit protocol открыты.
  Invitation TTL передаётся явно; утверждён только reset TTL 30 минут.
- Общие данные/активность/роли читаются вызывающим кодом актуально; policy-объект
  не является долговечным кешем identity. Будущие API должны повторять проверки
  внутри транзакции и проверять владение/closed/revision прежними Store-правилами.
- Миграция принимает явно переданное соединение без production entrypoint; ручное
  применение к реальному файлу технически возможно, но запрещено. В данной работе
  открывались только synthetic пути под scratch; рабочие БД не открывались SQLite.
- Нет Linux/Python 3.12/Docker/браузерных/нагрузочных/power-loss результатов; пакеты,
  сервер и конфигурации не менялись. Существующий релиз/архив не создавался заново.

## Полный перечень выполненных тестов

Каждый test ID ниже завершился OK в итоговом полном прогоне; subTest-варианты
(включая 18 точек rollback) входят в соответствующий test ID, отдельно в 188 не считаются.

### tests.test_access — 8 OK

- `tests.test_access.AccessTests.test_add_and_check_user`
- `tests.test_access.AccessTests.test_admin_access_independent_of_table`
- `tests.test_access.AccessTests.test_concurrent_duplicate_add`
- `tests.test_access.AccessTests.test_id_parser`
- `tests.test_access.AccessTests.test_invalid_ids_and_sql_input_are_rejected`
- `tests.test_access.AccessTests.test_remove_existing_and_missing_user`
- `tests.test_access.AccessTests.test_repeated_add_preserves_metadata`
- `tests.test_access.AccessTests.test_seed_import_on_each_start_and_persistence`

### tests.test_bitrix — 12 OK

- `tests.test_bitrix.BitrixTests.test_errors_and_invalid_shapes`
- `tests.test_bitrix.BitrixTests.test_invalid_or_unselected_stage_is_not_reported_as_zero`
- `tests.test_bitrix.BitrixTests.test_multiple_stages_are_one_union_query_across_pages`
- `tests.test_bitrix.BitrixTests.test_no_previous`
- `tests.test_bitrix.BitrixTests.test_noncontiguous_dates_and_empty_input`
- `tests.test_bitrix.BitrixTests.test_pagination_and_date_boundaries`
- `tests.test_bitrix.BitrixTests.test_previous_day_retains_breakdown`
- `tests.test_bitrix.BitrixTests.test_previous_skips_empty_history_and_duplicates`
- `tests.test_bitrix.BitrixTests.test_repeated_pages_fail`
- `tests.test_bitrix.BitrixTests.test_single_alternate_stage_in_previous_search_and_count`
- `tests.test_bitrix.BitrixTests.test_stage_breakdown_pages_duplicates_timezone_and_zeros`
- `tests.test_bitrix.BitrixTests.test_timeout_and_network_error`

### tests.test_bot — 27 OK

- `tests.test_bot.BotTests.test_access_for_messages_and_callbacks`
- `tests.test_bot.BotTests.test_add_remove_commands_take_effect_without_restart`
- `tests.test_bot.BotTests.test_admin_command_does_not_reset_manual_date_flow`
- `tests.test_bot.BotTests.test_admin_commands_are_denied_for_every_non_admin`
- `tests.test_bot.BotTests.test_admin_has_access_without_database_row`
- `tests.test_bot.BotTests.test_all_empty_and_continue_without_replacement`
- `tests.test_bot.BotTests.test_all_selected_stages_used_for_replacements`
- `tests.test_bot.BotTests.test_bitrix_failure_can_be_retried`
- `tests.test_bot.BotTests.test_cannot_remove_self_or_other_admin_even_if_stored`
- `tests.test_bot.BotTests.test_complete_flow_alternatives_and_reset`
- `tests.test_bot.BotTests.test_database_failure_denies_access_and_hides_details`
- `tests.test_bot.BotTests.test_empty_day_previous_replacement`
- `tests.test_bot.BotTests.test_group_ignores_chatter_and_separates_topics`
- `tests.test_bot.BotTests.test_group_manual_date_only_accepts_own_prompt_reply`
- `tests.test_bot.BotTests.test_group_sessions_and_foreign_buttons`
- `tests.test_bot.BotTests.test_invalid_admin_command_arguments`
- `tests.test_bot.BotTests.test_long_user_list_fits_telegram_messages`
- `tests.test_bot.BotTests.test_manager_selection_and_empty_selection`
- `tests.test_bot.BotTests.test_manual_rejects_invalid_duplicate_today_and_zero`
- `tests.test_bot.BotTests.test_multiple_missing_days_and_skip_remaining`
- `tests.test_bot.BotTests.test_planner_link_only_in_private_chat_and_keeps_flow`
- `tests.test_bot.BotTests.test_reminder_subscriptions_and_shared_button`
- `tests.test_bot.BotTests.test_removed_seed_user_is_denied_until_reimport`
- `tests.test_bot.BotTests.test_select_single_stage_and_new_period`
- `tests.test_bot.BotTests.test_stage_breakdown_in_result_and_alternatives`
- `tests.test_bot.BotTests.test_stale_concurrent_clicks_and_session_isolation`
- `tests.test_bot.BotTests.test_users_sorted_deduplicated_and_marked`

### tests.test_bot_confirmation — 10 OK

- `tests.test_bot_confirmation.BotConfirmationTests.test_changed_counts_and_bitrix_failure_then_retry`
- `tests.test_bot_confirmation.BotConfirmationTests.test_duplicate_leads_with_unchanged_count_rejected`
- `tests.test_bot_confirmation.BotConfirmationTests.test_inactive_selection_creates_no_partial_distribution`
- `tests.test_bot_confirmation.BotConfirmationTests.test_other_and_mixed_stages_never_publish`
- `tests.test_bot_confirmation.BotConfirmationTests.test_parallel_clicks_and_other_variant_one_day`
- `tests.test_bot_confirmation.BotConfirmationTests.test_permissions_button_hidden_and_forged_callback_denied`
- `tests.test_bot_confirmation.BotConfirmationTests.test_queue_failure_retry_and_committed_ack_failure`
- `tests.test_bot_confirmation.BotConfirmationTests.test_selected_variant_only_and_repeated_callback`
- `tests.test_bot_confirmation.BotConfirmationTests.test_stale_button_and_foreign_menu`
- `tests.test_bot_confirmation.BotConfirmationTests.test_writer_initializes_queue_on_start_without_crm_or_polling`

### tests.test_config — 9 OK

- `tests.test_config.ConfigTests.test_custom_database_path`
- `tests.test_config.ConfigTests.test_distribution_capabilities_are_explicit_and_ids_validated`
- `tests.test_config.ConfigTests.test_invalid_values_are_not_echoed`
- `tests.test_config.ConfigTests.test_log_redaction`
- `tests.test_config.ConfigTests.test_mini_app_is_optional_and_requires_https`
- `tests.test_config.ConfigTests.test_missing_values`
- `tests.test_config.ConfigTests.test_multiple_admins_and_empty_seed`
- `tests.test_config.ConfigTests.test_stages_and_manager_rename`
- `tests.test_config.ConfigTests.test_valid_default_timezone_and_no_secrets_in_repr`

### tests.test_distribution — 8 OK

- `tests.test_distribution.DateTests.test_all_periods_and_leap_day`
- `tests.test_distribution.DateTests.test_manual_date`
- `tests.test_distribution.DateTests.test_moscow_midnight_and_year_boundary`
- `tests.test_distribution.DistributionTests.test_alternatives_and_permutations`
- `tests.test_distribution.DistributionTests.test_empty`
- `tests.test_distribution.DistributionTests.test_invalid_input`
- `tests.test_distribution.DistributionTests.test_large_periods`
- `tests.test_distribution.DistributionTests.test_required_scenarios`

### tests.test_distribution_import — 12 OK

- `tests.test_distribution_import.ImportTests.test_approved_and_closed_unchanged_review_not_success`
- `tests.test_distribution_import.ImportTests.test_authorization_is_explicit_not_manager_or_supervisor_role`
- `tests.test_distribution_import.ImportTests.test_existing_draft_preserves_tasks`
- `tests.test_distribution_import.ImportTests.test_failure_mid_import_rolls_back_then_retries`
- `tests.test_distribution_import.ImportTests.test_inactive_blocks_whole_snapshot`
- `tests.test_distribution_import.ImportTests.test_migration_failure_rolls_back_schema`
- `tests.test_distribution_import.ImportTests.test_one_day_conflict_and_concurrent_duplicates`
- `tests.test_distribution_import.ImportTests.test_queue_cannot_initialize_planner_or_modify_other_database`
- `tests.test_distribution_import.ImportTests.test_queue_read_missing_never_creates_and_append_only`
- `tests.test_distribution_import.ImportTests.test_reject_wrong_stage_duplicate_lead_dates_binding_and_counts`
- `tests.test_distribution_import.ImportTests.test_roundtrip_repeat_restart_and_actual_initiator`
- `tests.test_distribution_import.ImportTests.test_v2_migration_preserves_data_idempotent_and_backup`

### tests.test_frontend_release — 4 OK

- `tests.test_frontend_release.FrontendReleaseTests.test_build_failure_creates_no_archive`
- `tests.test_frontend_release.FrontendReleaseTests.test_manifest_detects_tampering`
- `tests.test_frontend_release.FrontendReleaseTests.test_rejects_demo_maps_missing_and_secrets`
- `tests.test_frontend_release.FrontendReleaseTests.test_release_manifest_matches_packaged_assets`

### tests.test_hotfix_compatibility — 1 OK

- `tests.test_hotfix_compatibility.HotfixRoleCompatibilityTests.test_two_supervisors_and_two_managers_have_independent_access`

### tests.test_hotfix_release — 10 OK

- `tests.test_hotfix_release.HotfixReleaseTests.test_build_keeps_locked_dev_tools_without_disabling_security`
- `tests.test_hotfix_release.HotfixReleaseTests.test_existing_artifacts_are_not_overwritten`
- `tests.test_hotfix_release.HotfixReleaseTests.test_invalid_build_never_publishes_artifact`
- `tests.test_hotfix_release.HotfixReleaseTests.test_lockfile_hash_checked_even_if_outer_manifest_updated`
- `tests.test_hotfix_release.HotfixReleaseTests.test_planner_release_identity_sidecars_and_no_bot_or_web`
- `tests.test_hotfix_release.HotfixReleaseTests.test_rehashed_manifest_cannot_mix_frontend_identity`
- `tests.test_hotfix_release.HotfixReleaseTests.test_requires_committed_sources`
- `tests.test_hotfix_release.HotfixReleaseTests.test_requires_identity_and_disjoint_profiles`
- `tests.test_hotfix_release.HotfixReleaseTests.test_two_release_ids_remain_independent`
- `tests.test_hotfix_release.HotfixReleaseTests.test_unknown_profiles_and_journals_rejected`

### tests.test_plan_confirmation — 7 OK

- `tests.test_plan_confirmation.ConfirmationTests.test_concurrent_confirm_only_one_event`
- `tests.test_plan_confirmation.ConfirmationTests.test_confirm_own_repeat_preserves_snapshot_time_history_and_role`
- `tests.test_plan_confirmation.ConfirmationTests.test_copy_skips_imported_but_keeps_other_tasks`
- `tests.test_plan_confirmation.ConfirmationTests.test_disabled_manager_denied_and_other_goals_use_approval`
- `tests.test_plan_confirmation.ConfirmationTests.test_execution_and_time_approval_continue_after_confirmation`
- `tests.test_plan_confirmation.ConfirmationTests.test_foreign_supervisor_closed_unauthorized_and_old_approve`
- `tests.test_plan_confirmation.ConfirmationTests.test_imported_target_all_roles_requests_move_delete_and_forgery`

### tests.test_planner — 17 OK

- `tests.test_planner.AuthTests.test_invalid_missing_duplicate_expired_future_or_forged_identity`
- `tests.test_planner.AuthTests.test_valid_signature_and_unicode`
- `tests.test_planner.PlannerTests.test_access_db_unchanged_and_roles_independent`
- `tests.test_planner.PlannerTests.test_closed_report_immutable_and_timers_stopped`
- `tests.test_planner.PlannerTests.test_concurrent_timers_and_stale_revision`
- `tests.test_planner.PlannerTests.test_copy_previous_weekday_resets_fact_and_preserves_lock`
- `tests.test_planner.PlannerTests.test_disabled_employee_and_missing_access_db_fail_closed`
- `tests.test_planner.PlannerTests.test_external_tasks_read_only_no_fake_statistics`
- `tests.test_planner.PlannerTests.test_goal_approval_old_target_and_audit`
- `tests.test_planner.PlannerTests.test_invalid_values_and_task_kind_and_mass_assignment`
- `tests.test_planner.PlannerTests.test_migration_is_idempotent_and_refuses_access_database`
- `tests.test_planner.PlannerTests.test_move_retains_fact_and_is_not_completion`
- `tests.test_planner.PlannerTests.test_no_public_auth_bypass_or_client_roles`
- `tests.test_planner.PlannerTests.test_owner_checks_every_plan_task_report_and_request`
- `tests.test_planner.PlannerTests.test_stale_goal_request_cannot_overwrite_new_supervisor_value`
- `tests.test_planner.PlannerTests.test_supervisor_task_lock_fact_edit_and_rejection`
- `tests.test_planner.PlannerTests.test_timer_restores_after_new_store_and_prevents_overlap`

### tests.test_planner_production — 12 OK

- `tests.test_planner_production.ProductionTests.test_all_three_signed_employees_and_separate_bot_admin_role`
- `tests.test_planner_production.ProductionTests.test_backup_roundtrip_report_history_persistence_and_no_overwrite`
- `tests.test_planner_production.ProductionTests.test_conflicting_binding_rolls_back_entire_migration`
- `tests.test_planner_production.ProductionTests.test_new_planner_file_is_private_on_posix`
- `tests.test_planner_production.ProductionTests.test_no_time_lock_after_19_or_extra_reminder_subscriptions`
- `tests.test_planner_production.ProductionTests.test_nonempty_binding_not_overwritten_and_detected_by_checks`
- `tests.test_planner_production.ProductionTests.test_packaged_production_serves_assets_requires_auth_and_rejects_tampering`
- `tests.test_planner_production.ProductionTests.test_production_requires_static_build_and_no_demo_auth_mode`
- `tests.test_planner_production.ProductionTests.test_readonly_checks_and_readiness_failure_no_file_creation`
- `tests.test_planner_production.ProductionTests.test_source_release_never_contains_secrets_databases_or_bot_entry`
- `tests.test_planner_production.ProductionTests.test_tampered_backup_or_access_database_cannot_be_restored`
- `tests.test_planner_production.ProductionTests.test_v1_migration_fills_yana_once_preserves_history_and_custom_data`

### tests.test_release_stage2 — 4 OK

- `tests.test_release_stage2.CompleteChainTests.test_bot_to_automatic_import_two_confirmations_and_reports`
- `tests.test_release_stage2.ReleaseTests.test_queue_backup_live_connection_roundtrip`
- `tests.test_release_stage2.ReleaseTests.test_stage2_archive_integrity_no_secrets_or_databases`
- `tests.test_release_stage2.ReleaseTests.test_v2_live_backup_migration_preserves_every_existing_entity`

### tests.test_reminders — 5 OK

- `tests.test_reminders.ReminderTests.test_forbidden_and_network_failure_do_not_flood`
- `tests.test_reminders.ReminderTests.test_late_start_does_not_send_afternoon_prompt`
- `tests.test_reminders.ReminderTests.test_moscow_time_daily_claim_and_restart`
- `tests.test_reminders.ReminderTests.test_revoked_user_and_opt_out_persist`
- `tests.test_reminders.ReminderTests.test_toggle_does_not_reset_delivery_claim`

### tests.test_sync — 7 OK

- `tests.test_sync.SyncTests.test_automatic_lifespan_missing_queue_then_recovery`
- `tests.test_sync.SyncTests.test_bad_record_does_not_block_good_and_state_persisted`
- `tests.test_sync.SyncTests.test_closed_plan_review_and_inactive_identity_not_exposed`
- `tests.test_sync.SyncTests.test_commit_before_attempt_status_recovers_on_restart`
- `tests.test_sync.SyncTests.test_notices_scoped_source_no_lead_ids`
- `tests.test_sync.SyncTests.test_restart_parallel_and_read_only`
- `tests.test_sync.SyncTests.test_retry_after_transaction_failure`

### tests.test_web_auth_foundation — 12 OK

- `tests.test_web_auth_foundation.FoundationPolicyTests.test_30_day_boundary_short_idle_and_background`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_absolute_90_day_boundary_and_visit_cannot_extend_it`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_closed_states_types_and_immutability`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_complete_reset_once_and_repeat_reset_invalidates_old_action`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_current_employee_and_credential_activity_and_binding`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_current_role_changes_permissions_without_session_role_cache`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_invitation_is_distinct_and_requires_explicit_lifetime`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_reset_cannot_reenable_inactive_account_or_change_employee`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_reset_pending_invalidates_hash_sessions_and_expiry_does_not_restore_login`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_revocation_version_binding_and_future_timestamps_fail_closed`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_supervisor_scope_and_reauthentication`
- `tests.test_web_auth_foundation.FoundationPolicyTests.test_web_identity_has_no_telegram_acl_or_admin_role`

### tests.test_web_auth_migration — 18 OK

- `tests.test_web_auth_migration.MigrationTests.test_additive_migration_preserves_every_old_value_and_object_and_reopens`
- `tests.test_web_auth_migration.MigrationTests.test_busy_lock_refuses_safely_then_retry_succeeds`
- `tests.test_web_auth_migration.MigrationTests.test_failure_at_every_step_rolls_back_ddl_registry_version_and_data`
- `tests.test_web_auth_migration.MigrationTests.test_modified_schema4_and_damaged_schema5_are_not_repaired`
- `tests.test_web_auth_migration.MigrationTests.test_preexisting_transaction_and_foreign_key_corruption`
- `tests.test_web_auth_migration.MigrationTests.test_process_crash_before_commit_and_durability_after_commit`
- `tests.test_web_auth_migration.MigrationTests.test_row_factory_explicit_autocommit_and_no_entrypoint_import`
- `tests.test_web_auth_migration.MigrationTests.test_store_stays_schema4_and_refuses_schema5`
- `tests.test_web_auth_migration.MigrationTests.test_two_competing_migrators_serialize_to_one_commit`
- `tests.test_web_auth_migration.MigrationTests.test_two_process_migrators_share_the_sqlite_write_lock`
- `tests.test_web_auth_migration.MigrationTests.test_unknown_versions_are_refused_without_any_change`
- `tests.test_web_auth_migration.ResetTransactionTests.test_expired_code_cannot_restore_old_login`
- `tests.test_web_auth_migration.ResetTransactionTests.test_failed_reset_and_failed_redeem_roll_back_whole_transition`
- `tests.test_web_auth_migration.ResetTransactionTests.test_login_reset_race_both_orders_and_stale_verifier_result`
- `tests.test_web_auth_migration.ResetTransactionTests.test_manager_cannot_reset_other_accounts`
- `tests.test_web_auth_migration.ResetTransactionTests.test_old_hash_sessions_and_login_are_immediately_invalid_and_new_login_restores`
- `tests.test_web_auth_migration.ResetTransactionTests.test_repeat_reset_invalidates_previous_code`
- `tests.test_web_auth_migration.ResetTransactionTests.test_two_redeemers_consume_once`

### tests.test_web_auth_schema — 5 OK

- `tests.test_web_auth_schema.SchemaTests.test_action_uniqueness_fk_purpose_and_one_time_constraints`
- `tests.test_web_auth_schema.SchemaTests.test_closed_audit_and_attempt_enums_and_actor_foreign_keys`
- `tests.test_web_auth_schema.SchemaTests.test_credential_unique_fk_state_hash_and_version`
- `tests.test_web_auth_schema.SchemaTests.test_indexes_fk_integrity_and_no_cascade_or_role_copy`
- `tests.test_web_auth_schema.SchemaTests.test_session_unique_fk_hash_and_time_constraints`
