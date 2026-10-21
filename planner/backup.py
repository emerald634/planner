"""SQLite Backup API, checksums, and restore into a NEW file only.

Does not read .env, run migrations, or start a bot. No automatic schedule.
"""
import argparse
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def read_only(path: Path):
    path = path.resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.execute("PRAGMA query_only=ON")
    return connection


def validate(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (1, 2, 3, 4):
        raise ValueError("Неизвестная версия базы планировщика.")
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"employees", "plans", "tasks", "audit", "reports", "goal_requests"} <= tables:
        raise ValueError("Это не база планировщика.")
    if version >= 3 and not {"distributions", "distribution_tasks", "distribution_leads", "system_audit"} <= tables:
        raise ValueError("Неполная схема распределений планировщика.")
    if version == 4 and "import_attempts" not in tables:
        raise ValueError("Неполная схема синхронизации.")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Проверка целостности базы не пройдена.")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Нарушены связи базы.")


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_queue(connection):
    from .distribution_queue import validate as validate_snapshot
    import json
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("Неизвестная схема очереди.")
    if [r[1] for r in connection.execute("PRAGMA table_info(confirmations)")] != ["distribution_id", "workday", "payload", "sha256"]:
        raise ValueError("Это не очередь распределений.")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Нарушена целостность очереди.")
    for identifier, day, payload, checksum in connection.execute("SELECT distribution_id,workday,payload,sha256 FROM confirmations"):
        value = json.loads(payload)
        if value['distribution_id'] != identifier or value['workday'] != day or validate_snapshot(value) != checksum:
            raise ValueError("Нарушена целостность снимка очереди.")


def copy_database(source: Path, target: Path, kind="planner"):
    # O_EXCL prevents accidentally replacing an existing live database or backup.
    src = read_only(source)
    created = False
    dst = None
    try:
        (validate_queue if kind == "queue" else validate)(src)
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        created = True
        dst = sqlite3.connect(target)
        src.backup(dst, pages=256, sleep=0.1)
        (validate_queue if kind == "queue" else validate)(dst)
        dst.close()
        dst = None
        with target.open("r+b") as stream:
            os.fsync(stream.fileno())
    except BaseException:
        if dst is not None:
            dst.close()
        if created:
            target.unlink(missing_ok=True)
        raise
    finally:
        src.close()


def create_backup(database: Path, directory: Path, kind="planner") -> Path:
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Каталог резервных копий не найден.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"{kind}-{stamp}-{uuid4().hex[:8]}.db"
    copy_database(database, target, kind)
    checksum = target.with_suffix(".db.sha256")
    fd = os.open(checksum, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(f"{digest(target)}  {target.name}\n")
    return target


def verify_backup(backup: Path, kind="planner"):
    backup = backup.resolve(strict=True)
    checksum = backup.with_suffix(".db.sha256").read_text(encoding="ascii").split()
    if len(checksum) != 2 or checksum[1] != backup.name or checksum[0] != digest(backup):
        raise ValueError("Контрольная сумма копии не совпадает.")
    connection = read_only(backup)
    try:
        (validate_queue if kind == "queue" else validate)(connection)
    finally:
        connection.close()


def restore_backup(backup: Path, directory: Path, kind="planner") -> Path:
    verify_backup(backup, kind)
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Каталог восстановления не найден.")
    target = directory / ("confirmations.db" if kind == "queue" else "planner.db")
    copy_database(backup, target, kind)
    return target


def main():
    parser = argparse.ArgumentParser(description="Резервное копирование планировщика без изменения исходной БД")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("create")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--directory", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--directory", type=Path, required=True)
    for command in (backup, verify, restore):
        command.add_argument("--kind", choices=("planner", "queue"), default="planner")
    args = parser.parse_args()
    try:
        if args.command == "create":
            print("Создана копия:", create_backup(args.database, args.directory, args.kind).name)
        elif args.command == "verify":
            verify_backup(args.backup, args.kind)
            print("Целостность и SHA256 подтверждены.")
        else:
            restore_backup(args.backup, args.directory, args.kind)
            print("База восстановлена в новый файл; исходные данные не перезаписаны.")
    except (OSError, sqlite3.Error, ValueError):
        raise SystemExit("Операция не выполнена. Проверьте пути, права, свободное место и целостность копии. Существующие файлы не перезаписаны.") from None


if __name__ == "__main__":
    main()
