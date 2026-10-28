# API и авторизация

Web prefix /api/v1: auth/login, logout, me, csrf, visit; users/leads/sources/stats; planner/me/employees/plans/tasks/requests/distributions, daily/weekly/source endpoints и distribution calculate/previous/confirm/history. Полный контракт — decorators в web/backend/app/api и workspace/routes.py/application.py. Старый Mini App /api контракт в planner/api.py использует Telegram initData, не web cookie.

WebSessions:90 дней абсолютный срок,30 дней без foreground посещения; digest cookie, auth_version/revoke/logout. Visible heartbeat не продлевает абсолютный срок. Secure HttpOnly cookies, точный HTTPS Origin/Host; session-bound HMAC CSRF для всех mutations, включая login/logout. Deadline frontend15с включая JSON.

WorkspaceLink — явный уникальный user→employee mapping; active и role сверяются на API. Manager только своё, supervisor отдел в пределах Store. LeadFlow admin не становится Planner supervisor. Confirm требует отдельный grant И allowlist, не всех managers. Telegram ACL отдельно в старом боте.

DSN — DATABASE_URL_FILE, owner-only regular file, не inline secret в compose/env. WORKSPACE_RUNTIME=1 отключает dotenv; bootstrap запрещён. WORKSPACE_CONFIG_FILE — private JSON со ссылками на csrf/web/bot keys. Web не читает bot key. Writer требует разные purpose keys и повторно проверяет canonical session либо доверенную bot identity. Не выводить env/config/key/DSN в логи.

Recovery create_readonly_app: POST только точные login/logout/visit, остальные mutations503; importer выключен. Существующие цели/imported counts/закрытые дни защищены сервером независимо от UI.
