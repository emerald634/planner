# Локальный rollback-кандидат schema5 bridge

Это отдельная версия backend `schema5-compat-v1`, не релиз 2.1.1 и не web-auth.
Развёртывание, миграции production и переключение контейнеров не разрешены.

Из чистого согласованного Git-коммита, с установленным pnpm и полным локальным
кешем зафиксированных frontend-зависимостей:

```powershell
.\.venv\Scripts\python.exe -B deploy/package_release.py --bridge --release-id planner-schema5-bridge-rc1-20261021
```

Создаются новый архив, SHA256 и полный список файлов; существующие файлы не
перезаписываются. Сначала offline/frozen install и production build существующего
Mini App; Node/pnpm не нужны в Docker. Frontend не получает новых функций.
После распаковки: `python -B deploy/release_check.py`. Проверка не открывает базы.

`release-files.json` фиксирует release ID, точный Git SHA, версию bridge,
`supported_planner_schemas=[4,5]`, checksum конкретного schema5 manifest и
`web_auth_enabled=false`. `planner_schema=4` — прежняя цель бизнес-миграций,
**не утверждение фактически установленной версии БД**. Её проверяют отдельно.
Frontend manifest связан с тем же release ID/Git SHA. Манифесты и SHA256 —
контроль целостности, не криптографическая подпись издателя.

В архиве есть весь backend и лишь read-only части web_auth: __init__, schema,
validation. Нет migration.py, password/session policy, login/account-admin,
бота/polling, секретов, SQLite и тестовых данных. Отдельный
`planner/schema5_compatibility.py` — явная capability. Старые профили упаковки
не включают её и web_auth; поэтому пакет профиля 2.1.1 остаётся schema≤4,
а bridge нельзя назвать release ID вида planner-2.1.1-... .

Bridge открывает schema4 без auth-таблиц и без повышения версии. Schema5
проверяется строго по известной структуре/ограничениям/реестру/manifest/FK/
integrity; неизвестная 6, незнакомая или повреждённая 5 отвергаются. Никакого
ремонта, удаления auth-данных, миграции при startup или web-входа нет.

Будущий откат — возврат проверенного bridge на **актуальную schema5**, чтобы
сохранить записи после миграции. Исходный 2.1.1 для этого не пригоден.
Перед production нужны отдельная приёмка DDL, Linux/Python 3.12/Docker smoke,
проверка mounts/UID/GID, свежие сведения о сервере, резервирование и тестовое
восстановление. Backup/verify/restore через `python -m planner.backup` поддерживает
известную schema5; restore только в новый файл, без автоматической миграции.
Возврат старой schema4-копии может потерять видимость новых записей и требует
отдельного плана сохранения/сверки. Данные очереди schema1 не удалять.

Подробные фактические проверки: `SCHEMA5_COMPATIBILITY_REPORT.md` в репозитории.
Наличие архива ещё не доказывает готовность Linux-образа к эксплуатации.
