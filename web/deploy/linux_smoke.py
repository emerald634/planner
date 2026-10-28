"""Run only in an isolated review container. Never reads real env/CRM/DB files."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path


def main():
    assert os.name == "posix", "Linux/UID smoke, not a substitute Windows run"
    from planner.daily import DailyStore
    from planner.distribution_queue import DistributionQueue
    from planner.read_only import ReadOnlyQueue, ReadOnlyStore
    from planner.server_migration import migrate_server

    for variable in ("SMOKE_RO_QUEUE", "SMOKE_RO_PLANNER"):
        path = Path(os.environ[variable]).resolve(strict=True)
        try:
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE must_be_readonly(value INTEGER)")
        except sqlite3.OperationalError as error:
            assert error.sqlite_errorcode == sqlite3.SQLITE_READONLY, (
                "Wrong failure, not a RO mount proof"
            )
        else:
            raise AssertionError("Kernel read-only mount is missing")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = DailyStore(root / "planner.db")
        store.initialize()
        migrate_server(store)
        migrate_server(store)
        queue = DistributionQueue(root / "queue.db")
        queue.initialize()
        actor = store.actor(8306778724)
        plan = store.create_plan(actor, "2026-10-20")
        assert len(store.daily_get(actor, plan["id"])["indicators"]) == 8
        report = store.close_plan(actor, plan["id"])
        assert store.report(actor, plan["id"]) == report
        try:
            ReadOnlyQueue(queue.path).publish({}, set())
        except PermissionError:
            pass
        else:
            raise AssertionError("RO queue wrote")
        try:
            with ReadOnlyStore(store.path).connection(True):
                pass
        except PermissionError:
            pass
        else:
            raise AssertionError("Writer changed Planner")
        with sqlite3.connect(queue.path) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    print(
        json.dumps(
            {
                "linux_smoke": "passed",
                "uid": os.getuid(),
                "gid": os.getgid(),
                "synthetic_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
