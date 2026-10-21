"""Explicit migration for synthetic test connections only; no CLI/startup integration.

No path/env is accepted. Calling this on application data is NOT authorized.
The old Store deliberately continues to reject schema5.
"""
import sqlite3
from collections.abc import Callable

from .schema import (AUTH_OBJECTS, BASELINE_OBJECTS, DDL, REGISTRY_DETAILS,
                     TARGET_VERSION, objects)


class MigrationError(ValueError):
    """Unknown schema or failed integrity/manifest validation, without row data."""


def check_integrity(db):
    if [tuple(row) for row in db.execute("PRAGMA integrity_check")] != [("ok",)]:
        raise MigrationError("SQLite integrity check failed")
    if list(db.execute("PRAGMA foreign_key_check")):
        raise MigrationError("SQLite foreign key check failed")


def validate_schema(db, version):
    expected = BASELINE_OBJECTS if version == 4 else tuple(sorted(
        BASELINE_OBJECTS + AUTH_OBJECTS, key=lambda row: (row[0], row[1])))
    if objects(db) != expected:
        raise MigrationError("Unknown schema structure")
    rows = list(db.execute("SELECT version FROM schema_migrations ORDER BY version"))
    if [row[0] for row in rows] != ([2, 3, 4] if version == 4 else [2, 3, 4, 5]):
        raise MigrationError("Unknown migration registry")
    if version == 5:
        row = db.execute("SELECT details FROM schema_migrations WHERE version=5").fetchone()
        if row is None or row[0] != REGISTRY_DETAILS:
            raise MigrationError("Unknown schema5 manifest")
    check_integrity(db)


def migrate_synthetic(db: sqlite3.Connection, *, applied_at: int,
                      checkpoint: Callable[[str], None] | None = None) -> bool:
    """Return True for 4→5, False for a validated no-op; rollback any precommit error.

    Caller owns a synthetic connection and its busy timeout. Checkpoints are for
    deterministic test failure/crash injection, never an application plugin hook.
    """
    if type(applied_at) is not int or applied_at < 0:
        raise MigrationError("Invalid migration timestamp")
    if db.in_transaction:
        raise MigrationError("Connection already has a transaction")
    db.execute("PRAGMA foreign_keys=ON")
    if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise MigrationError("Foreign keys must be enabled")

    def step(name):
        if checkpoint is not None:
            checkpoint(name)

    try:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (4, TARGET_VERSION):
            raise MigrationError("Unsupported source version")
        validate_schema(db, version)
        step("validated")
        if version == TARGET_VERSION:
            db.execute("COMMIT")
            return False
        for index, statement in enumerate(DDL):
            db.execute(statement)
            step(f"ddl:{index}")
        db.execute("INSERT INTO schema_migrations(version,applied_at,details) VALUES(5,?,?)",
                   (applied_at, REGISTRY_DETAILS))
        step("registry")
        db.execute("PRAGMA user_version=5")
        step("version")
        validate_schema(db, 5)
        step("before_commit")
        db.execute("COMMIT")
        return True
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
