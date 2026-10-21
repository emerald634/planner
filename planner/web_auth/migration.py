"""Explicit migration for synthetic test connections only; no CLI/startup integration.

No path/env is accepted. Calling this on application data is NOT authorized.
The old Store deliberately continues to reject schema5.
"""
import sqlite3
from collections.abc import Callable

from .schema import DDL, REGISTRY_DETAILS, TARGET_VERSION
from .validation import MigrationError, validate_schema


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
