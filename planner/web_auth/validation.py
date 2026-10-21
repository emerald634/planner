"""Read-only validation of the frozen foundation design; no migration or repair."""
from .schema import AUTH_OBJECTS, BASELINE_OBJECTS, REGISTRY_DETAILS, objects


class MigrationError(ValueError):
    """Unknown schema or failed integrity/manifest validation, without row data."""


def check_integrity(db):
    if [tuple(row) for row in db.execute("PRAGMA integrity_check")] != [("ok",)]:
        raise MigrationError("SQLite integrity check failed")
    if list(db.execute("PRAGMA foreign_key_check")):
        raise MigrationError("SQLite foreign key check failed")


def validate_schema(db, version):
    if version not in (4, 5) or db.execute("PRAGMA user_version").fetchone()[0] != version:
        raise MigrationError("Unsupported source version")
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
