import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from access import DEFAULT_ACCESS_PATH, parse_telegram_id

ROOT = Path(__file__).resolve().parent.parent
WORKDAY = {"start": "10:00", "end": "19:00", "timezone": "Europe/Moscow", "reminders_enabled": False}


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    database: Path = ROOT / "planner.db"
    access_database: Path = DEFAULT_ACCESS_PATH
    bot_admin_ids: frozenset[int] = frozenset()
    init_data_max_age: int = 43200
    static_dir: Path = ROOT / "miniapp" / "dist"
    production: bool = False
    distribution_queue: Path | None = None
    distribution_confirmer_ids: frozenset[int] = frozenset()
    distribution_poll_seconds: float = 30


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Заполните BOT_TOKEN в существующем .env.")
    database = Path(os.getenv("PLANNER_DB_PATH") or ROOT / "planner.db").resolve()
    access = Path(os.getenv("ACCESS_DB_PATH") or DEFAULT_ACCESS_PATH).resolve()
    if database == access or (database.exists() and access.exists() and database.samefile(access)):
        raise ValueError("База планировщика должна отличаться от базы доступа.")
    admins = frozenset(parse_telegram_id(i) for i in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if i.strip())
    return Settings(token, database, access, admins, production=os.getenv("PLANNER_ENV", "").strip() == "production",
                    distribution_queue=Path(os.environ["DISTRIBUTION_QUEUE_PATH"]) if os.getenv("DISTRIBUTION_QUEUE_PATH", "").strip() else None,
                    distribution_confirmer_ids=frozenset(parse_telegram_id(i) for i in os.getenv("DISTRIBUTION_CONFIRMER_IDS", "").split(",") if i.strip()))
