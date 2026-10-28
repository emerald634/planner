"""Synthetic configuration for direct pytest/CI before application imports.

Use tools/run_session_checks.py for additional external-network/file-DB guards.
"""

import os
import secrets

os.environ.update(
    DATABASE_URL="sqlite://",
    SESSION_ENVIRONMENT="local",
    COOKIE_SECURE="false",
    JWT_SECRET=secrets.token_urlsafe(48),
    FIRST_ADMIN_PASSWORD="synthetic-bootstrap-never-run",
    TELEGRAM_BOT_TOKEN="",
    BITRIX24_WEBHOOK_URL="",
)
