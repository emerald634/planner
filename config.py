"""Configuration is validated at startup, never at import time."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from access import DEFAULT_ACCESS_PATH, parse_telegram_id


class ConfigError(ValueError):
    """A safe configuration error that never includes parameter values."""


@dataclass(frozen=True)
class Config:
    bot_token: str = field(repr=False)
    bitrix_webhook_url: str = field(repr=False)
    missed_call_stage_id: str
    manager_names: tuple[str, ...]
    allowed_telegram_ids: frozenset[int]
    timezone: ZoneInfo
    admin_telegram_ids: frozenset[int] = frozenset()
    access_db_path: Path = DEFAULT_ACCESS_PATH
    inconvenient_stage_id: str = ""
    unprocessed_stage_id: str = ""
    mini_app_url: str = ""
    distribution_queue_path: Path | None = None
    distribution_confirmer_ids: frozenset[int] = frozenset()
    manager_telegram_ids: tuple[int, ...] = (0, 0, 0)
    planner_active_manager_ids: frozenset[int] = frozenset()

    @property
    def stages(self) -> tuple[tuple[str, str], ...]:
        return (("Недозвоны", self.missed_call_stage_id),
                ("Неудобно говорить", self.inconvenient_stage_id),
                ("Не обработан", self.unprocessed_stage_id))


def _parse_ids(name: str) -> frozenset[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return frozenset()
    try:
        return frozenset(parse_telegram_id(item) for item in raw.split(","))
    except ValueError:
        raise ConfigError(f"{name}: укажите положительные 64-битные целые числа через запятую.") from None


def load_config(env_path: Path | None = None) -> Config:
    load_dotenv(env_path or Path(__file__).with_name(".env"), override=False)
    required = (
        "BOT_TOKEN", "BITRIX_WEBHOOK_URL", "MISSED_CALL_STAGE_ID",
        "MANAGER_1_NAME", "MANAGER_2_NAME", "MANAGER_3_NAME",
    )
    values = {key: os.getenv(key, "").strip() for key in required}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ConfigError("Заполните параметры в .env: " + ", ".join(missing))
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", values["BOT_TOKEN"]):
        raise ConfigError("Проверьте формат BOT_TOKEN в .env.")
    try:
        url = urlsplit(values["BITRIX_WEBHOOK_URL"])
        valid_url = (
            url.scheme == "https" and url.hostname and not url.username
            and not url.password and not url.query and not url.fragment
            and re.fullmatch(r"/rest/[0-9]+/[A-Za-z0-9_-]+/?", url.path)
            and (url.port is None or 0 < url.port < 65536)
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ConfigError("BITRIX_WEBHOOK_URL должен иметь вид https://портал/rest/ID/ключ/.")
    allowed_ids = _parse_ids("ALLOWED_TELEGRAM_IDS")
    admin_ids = _parse_ids("ADMIN_TELEGRAM_IDS")
    names = tuple("Евгений" if values[f"MANAGER_{i}_NAME"].casefold() == "женя"
                  else values[f"MANAGER_{i}_NAME"] for i in range(1, 4))
    if len({name.casefold() for name in names}) != 3:
        raise ConfigError("Имена менеджеров должны отличаться друг от друга.")
    if any(len(name) > 64 or any(ord(char) < 32 for char in name) for name in names):
        raise ConfigError("Имена менеджеров: до 64 символов, без переносов строк.")
    mini_app_url = os.getenv("MINI_APP_URL", "").strip()
    if mini_app_url:
        try:
            mini_url = urlsplit(mini_app_url)
            valid_mini = mini_url.scheme == "https" and mini_url.hostname and not mini_url.username and not mini_url.password and not mini_url.fragment
        except ValueError:
            valid_mini = False
        if not valid_mini:
            raise ConfigError("MINI_APP_URL должен быть HTTPS-адресом приложения.")
    try:
        timezone = ZoneInfo(os.getenv("TIMEZONE", "").strip() or "Europe/Moscow")
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError("Проверьте TIMEZONE и установите зависимости, включая tzdata.") from None
    try:
        manager_ids = tuple(parse_telegram_id(os.environ[f"MANAGER_{i}_TELEGRAM_ID"]) if os.getenv(f"MANAGER_{i}_TELEGRAM_ID", "").strip() else 0 for i in range(1, 4))
    except ValueError:
        raise ConfigError("MANAGER_N_TELEGRAM_ID: укажите положительный Telegram ID.") from None
    if len([x for x in manager_ids if x]) != len({x for x in manager_ids if x}):
        raise ConfigError("Telegram ID менеджеров должны отличаться.")
    return Config(
        bot_token=values["BOT_TOKEN"],
        bitrix_webhook_url=values["BITRIX_WEBHOOK_URL"].rstrip("/") + "/",
        missed_call_stage_id=values["MISSED_CALL_STAGE_ID"],
        manager_names=names,
        allowed_telegram_ids=allowed_ids,
        timezone=timezone,
        admin_telegram_ids=admin_ids,
        access_db_path=Path(os.getenv("ACCESS_DB_PATH", "").strip() or DEFAULT_ACCESS_PATH),
        inconvenient_stage_id=os.getenv("INCONVENIENT_STAGE_ID", "").strip(),
        unprocessed_stage_id=os.getenv("UNPROCESSED_STAGE_ID", "").strip(),
        mini_app_url=mini_app_url,
        distribution_queue_path=Path(os.environ["DISTRIBUTION_QUEUE_PATH"]) if os.getenv("DISTRIBUTION_QUEUE_PATH", "").strip() else None,
        distribution_confirmer_ids=_parse_ids("DISTRIBUTION_CONFIRMER_IDS"),
        manager_telegram_ids=manager_ids,
        planner_active_manager_ids=_parse_ids("PLANNER_ACTIVE_MANAGER_IDS"),
    )
