"""Local access list. Call SQLite operations through asyncio.to_thread in the bot."""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_ACCESS_PATH = Path(__file__).with_name("access.db")
MAX_TELEGRAM_ID = 2**63 - 1


def parse_telegram_id(value: str) -> int:
    value = value.strip()
    if not value or not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise ValueError("Telegram ID должен быть положительным целым числом.")
    telegram_id = int(value)
    if not 0 < telegram_id <= MAX_TELEGRAM_ID:
        raise ValueError("Telegram ID должен помещаться в положительное 64-битное целое число.")
    return telegram_id


def _validate_id(telegram_id: int) -> None:
    if type(telegram_id) is not int or not 0 < telegram_id <= MAX_TELEGRAM_ID:
        raise ValueError("Недопустимый Telegram ID.")


class AccessStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, initial_ids: Iterable[int] = ()) -> None:
        ids = sorted(set(initial_ids))
        for telegram_id in ids:
            _validate_id(telegram_id)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS allowed_users (
                    telegram_id INTEGER PRIMARY KEY CHECK (telegram_id > 0),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    added_by INTEGER CHECK (added_by > 0)
                )
            """)
            connection.executemany(
                "INSERT OR IGNORE INTO allowed_users (telegram_id) VALUES (?)",
                [(telegram_id,) for telegram_id in ids],
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL DEFAULT 0,
                    enabled_by INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_attempt_date TEXT,
                    PRIMARY KEY (chat_id, thread_id)
                )
            """)

    def contains(self, telegram_id: int) -> bool:
        _validate_id(telegram_id)
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM allowed_users WHERE telegram_id = ?", (telegram_id,),
            ).fetchone() is not None

    def has_access(self, telegram_id: int, admin_ids: frozenset[int]) -> bool:
        return telegram_id in admin_ids or self.contains(telegram_id)

    def add_user(self, telegram_id: int, added_by: int | None = None) -> bool:
        _validate_id(telegram_id)
        if added_by is not None:
            _validate_id(added_by)
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO allowed_users (telegram_id, added_by) VALUES (?, ?)",
                (telegram_id, added_by),
            )
            return cursor.rowcount == 1

    def remove_user(self, telegram_id: int) -> bool:
        _validate_id(telegram_id)
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM allowed_users WHERE telegram_id = ?", (telegram_id,))
            return cursor.rowcount == 1

    def list_users(self) -> list[int]:
        with self._connection() as connection:
            return [row[0] for row in connection.execute(
                "SELECT telegram_id FROM allowed_users ORDER BY telegram_id",
            )]

    def set_reminder(self, chat_id: int, thread_id: int, user_id: int, enabled: bool) -> None:
        with self._connection() as connection:
            connection.execute("""
                INSERT INTO reminders (chat_id, thread_id, enabled_by, enabled) VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, thread_id) DO UPDATE SET
                    enabled_by = excluded.enabled_by, enabled = excluded.enabled
            """, (chat_id, thread_id, user_id, int(enabled)))

    def ensure_private_reminders(self, user_ids: Iterable[int]) -> None:
        with self._connection() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO reminders (chat_id, enabled_by) VALUES (?, ?)",
                [(user_id, user_id) for user_id in set(user_ids)],
            )

    def list_reminders(self) -> list[tuple[int, int, int]]:
        with self._connection() as connection:
            return connection.execute(
                "SELECT chat_id, thread_id, enabled_by FROM reminders WHERE enabled = 1 ORDER BY chat_id, thread_id",
            ).fetchall()

    def claim_reminder(self, chat_id: int, thread_id: int, day: str) -> bool:
        with self._connection() as connection:
            return connection.execute("""
                UPDATE reminders SET last_attempt_date = ?
                WHERE chat_id = ? AND thread_id = ? AND enabled = 1
                    AND (last_attempt_date IS NULL OR last_attempt_date < ?)
            """, (day, chat_id, thread_id, day)).rowcount == 1
