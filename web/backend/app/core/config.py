import logging
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.runtime_secrets import settings_arguments

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_name: str = "Lead Distribution API"
    api_prefix: str = "/api/v1"
    database_url: str = Field(default="sqlite:///./lead_distribution.db", repr=False)
    jwt_secret: str = Field(default="local-development-secret-change-me-32-bytes", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    frontend_url: str = "http://localhost:5173"
    public_app_url: str = "http://localhost:5173"
    first_admin_email: str = "admin@example.com"
    first_admin_password: str = Field(default="", repr=False)
    bitrix24_webhook_url: str | None = Field(default=None, repr=False)
    bitrix_source_sync_interval_seconds: int = 86400
    bitrix_entity_poll_interval_seconds: int = 60
    telegram_bot_token: str | None = Field(default=None, repr=False)
    distribution_timezone: str = "Europe/Moscow"
    distribution_switch_time: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    cookie_secure: bool = True
    session_environment: Literal["production", "local"] = "production"

    @model_validator(mode="after")
    def session_security(self):
        urls = [urlsplit(self.public_app_url), urlsplit(self.frontend_url)]
        if self.session_environment == "local":
            if any(u.hostname not in {"localhost", "127.0.0.1", "::1"} for u in urls):
                raise ValueError("Local session mode requires loopback application URLs")
        else:
            if not self.cookie_secure or any(
                u.scheme != "https"
                or not u.hostname
                or u.hostname in {"localhost", "127.0.0.1", "::1"}
                for u in urls
            ):
                raise ValueError("Production sessions require Secure cookies and HTTPS origins")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("Production sessions require PostgreSQL")
            if self.first_admin_password and len(self.first_admin_password) < 16:
                raise ValueError("Explicit bootstrap password must have at least16 characters")
            if not os.environ.get("WORKSPACE_RUNTIME") == "1" and not self.first_admin_password:
                raise ValueError("Production bootstrap password must be explicitly configured")
        return self

    @property
    def session_cookie_name(self) -> str:
        return (
            "__Host-leadflow_session"
            if self.session_environment == "production"
            else "leadflow_local_session"
        )


@lru_cache
def get_settings() -> Settings:
    return (
        Settings(_env_file=None, **settings_arguments())
        if os.environ.get("WORKSPACE_RUNTIME") == "1"
        else Settings()
    )


def warn_if_insecure_defaults(config: Settings) -> None:
    defaults = Settings.model_fields
    if config.jwt_secret == defaults["jwt_secret"].default:
        logger.warning(
            "JWT_SECRET использует значение по умолчанию из репозитория — "
            "замените его перед деплоем в продакшн"
        )
    if config.first_admin_password == defaults["first_admin_password"].default:
        logger.warning(
            "FIRST_ADMIN_PASSWORD использует значение по умолчанию из репозитория — "
            "замените его перед деплоем в продакшн"
        )


settings = get_settings()
