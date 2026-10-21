"""Read-only post-deployment checks. Never migrates or seeds any database."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

from .backup import read_only, validate
from .store import EMPLOYEE_BINDINGS


def check(access_path: Path, planner_path: Path | None, admin_ids: set[int]):
    access = read_only(access_path)
    try:
        access.execute("SELECT 1 FROM allowed_users LIMIT 1").fetchone()
        result = {"access_db_readable": True, "access_journal_mode": access.execute("PRAGMA journal_mode").fetchone()[0]}
        if planner_path is None:
            return result
        if planner_path.resolve() == access_path.resolve() or planner_path.samefile(access_path):
            raise ValueError("Базы доступа и планировщика совпадают.")
        planner = read_only(planner_path)
        planner.row_factory = sqlite3.Row
        try:
            # sqlite3.Row equality differs from tuples used by integrity validation.
            planner.row_factory = None
            validate(planner)
            planner.row_factory = sqlite3.Row
            result["schema_version"] = planner.execute("PRAGMA user_version").fetchone()[0]
            result["employees"] = []
            valid = True
            for telegram_id, bitrix_id, name, role in EMPLOYEE_BINDINGS:
                row = planner.execute("SELECT * FROM employees WHERE telegram_id=?", (telegram_id,)).fetchone()
                binding_ok = bool(row and row["bitrix_id"] == bitrix_id and row["role"] == role and row["active"])
                allowed = telegram_id in admin_ids or access.execute("SELECT 1 FROM allowed_users WHERE telegram_id=?", (telegram_id,)).fetchone() is not None
                result["employees"].append({"name": name, "binding_ok": binding_ok, "bot_access": allowed})
                valid = valid and binding_ok and allowed
            result["ready"] = valid
            return result
        finally:
            planner.close()
    finally:
        access.close()


def main():
    parser = argparse.ArgumentParser(description="Проверка путей, ролей и доступа только для чтения")
    parser.add_argument("--access-only", action="store_true")
    args = parser.parse_args()
    try:
        access = Path(os.environ["ACCESS_DB_PATH"])
        planner = None if args.access_only else Path(os.environ["PLANNER_DB_PATH"])
        admins = {int(i.strip()) for i in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if i.strip()}
        result = check(access, planner, admins)
        print(json.dumps(result, ensure_ascii=False))
        if result.get("ready") is False:
            raise SystemExit(1)
    except (OSError, sqlite3.Error, ValueError, KeyError):
        raise SystemExit("Проверка не пройдена: проверьте настроенные пути, права и схему БД. Данные не изменены.") from None


if __name__ == "__main__":
    main()
