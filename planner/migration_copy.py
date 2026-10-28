"""SQLite online backup then migration on a NEW copy, with preservation checks."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .daily import DailyStore
from .server_migration import migrate_server


def fingerprints(connection):
    result = {}
    for (name,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall():
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [
            r[1] for r in connection.execute("PRAGMA table_info(" + quoted + ")")
        ]
        order = ",".join('"' + c.replace('"', '""') + '"' for c in columns)
        digest = hashlib.sha256()
        for row in connection.execute("SELECT * FROM " + quoted + " ORDER BY " + order):
            digest.update(
                json.dumps(list(row), ensure_ascii=False, default=str).encode()
            )
            digest.update(b"\n")
        result[name] = digest.hexdigest()
    return result


def prepare_copy(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    if (
        not destination.is_absolute()
        or destination.exists()
        or destination.is_symlink()
        or source == destination.resolve()
    ):
        raise ValueError(
            "New absolute destination required; never overwrite a database"
        )
    if not destination.parent.is_dir():
        raise ValueError("Create a dedicated review directory first")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with (
        closing(
            sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as original,
        closing(sqlite3.connect(destination)) as copied,
    ):
        original.backup(copied)
        before = fingerprints(copied)
    store = DailyStore(destination)
    migrate_server(store)
    with store.connection() as db:
        after = fingerprints(db)
        if any(after.get(k) != v for k, v in before.items()):
            raise ValueError("Existing rows changed")
        if (
            db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or db.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("Copy verification failed")
    return {
        "source_open_mode": "ro",
        "destination": str(destination),
        "preserved_tables": len(before),
        "integrity": "ok",
        "core_schema": 4,
        "extension": "crm_observations/1",
    }
