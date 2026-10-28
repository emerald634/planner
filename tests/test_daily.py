import json
import tempfile
import unittest
from pathlib import Path

from planner.daily import DailyInput, DailyStore, initialize_daily
from planner.store import DomainError, Store


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DailyStore(Path(self.temp.name) / "planner.db")
        self.store.initialize()
        initialize_daily(self.store)
        with self.store.connection() as db:
            self.manager = dict(
                db.execute("SELECT * FROM employees WHERE id=1").fetchone()
            )
            self.other = dict(
                db.execute("SELECT * FROM employees WHERE id=2").fetchone()
            )
            self.boss = dict(
                db.execute("SELECT * FROM employees WHERE id=3").fetchone()
            )
        self.plan = self.store.create_plan(self.manager, "2026-10-20")

    def body(self, data=None):
        data = data or self.store.daily_get(self.manager, self.plan["id"])
        return {
            "revision": data["revision"],
            "contracts": data["contracts"],
            "indicators": [
                {k: r[k] for k in ("key", "planned", "actual", "morning", "details")}
                for r in data["indicators"]
            ],
        }

    def test_eight_norms_reload_week_and_audit(self):
        body = self.body()
        body["indicators"][0]["actual"] = 43
        body["contracts"] = 1
        saved = self.store.daily_save(self.manager, self.plan["id"], body)
        self.assertEqual(len(saved["indicators"]), 8)
        self.assertEqual(
            self.store.get_plan(self.boss, self.plan["id"])["daily"]["indicators"][0][
                "actual"
            ],
            43,
        )
        self.assertEqual(
            self.store.weekly(self.manager, 1, "2026-10-21")["totals"]["contracts"], 1
        )
        self.assertEqual(
            self.store.history(self.manager, self.plan["id"])[-1]["action"],
            "daily_saved",
        )

    def test_permissions_revision_and_closed(self):
        body = self.body()
        with self.assertRaises(DomainError):
            self.store.daily_get(self.other, self.plan["id"])
        with self.assertRaises(DomainError):
            self.store.daily_save(self.other, self.plan["id"], body)
        self.store.daily_save(self.manager, self.plan["id"], body)
        with self.assertRaises(DomainError):
            self.store.daily_save(self.manager, self.plan["id"], body)
        report = self.store.close_plan(self.manager, self.plan["id"])
        self.assertIn("daily", report)
        with self.assertRaises(DomainError):
            self.store.daily_save(self.boss, self.plan["id"], self.body())
        self.assertEqual(self.store.report(self.manager, self.plan["id"]), report)

    def test_approval_preserves_snapshot_and_fact(self):
        self.store.confirm_plan(self.manager, self.plan["id"])
        before = self.store.get_plan(self.manager, self.plan["id"])["initial_snapshot"]
        body = self.body()
        body["indicators"][0]["actual"] = 20
        self.store.daily_save(self.manager, self.plan["id"], body)
        self.assertEqual(
            self.store.get_plan(self.manager, self.plan["id"])["initial_snapshot"],
            before,
        )
        body = self.body()
        body["indicators"][1]["planned"] = 99
        self.store.daily_save(self.manager, self.plan["id"], body)
        body = self.body()
        body["indicators"][1]["planned"] = 98
        with self.assertRaises(DomainError):
            self.store.daily_save(self.manager, self.plan["id"], body)

    def test_additive_migration_repeat_and_old_report(self):
        report = self.store.close_plan(self.manager, self.plan["id"])
        with self.store.connection() as db:
            before = db.execute("SELECT snapshot FROM reports").fetchone()[0]
        initialize_daily(self.store)
        with self.store.connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(
                db.execute("SELECT snapshot FROM reports").fetchone()[0], before
            )
        self.assertEqual(json.loads(before), report)

    def test_forged_import_and_duplicate_clients(self):
        body = self.body()
        body["indicators"][2]["planned"] = 1
        with self.assertRaises(DomainError):
            self.store.daily_save(self.manager, self.plan["id"], body)
        body = self.body()
        row = body["indicators"][3]
        row["details"] = [
            {"id": "a", "client": "A", "done": True, "result": "Консультация"},
            {"id": "a", "client": "A"},
        ]
        with self.assertRaises(ValueError):
            DailyInput.model_validate(body)

    def test_original_schema4_report_preserved_by_extension(self):
        original = Store(Path(self.temp.name) / "old.db")
        original.initialize()
        plan = original.create_plan(self.manager, "2026-10-19")
        before = original.close_plan(self.manager, plan["id"])
        self.assertNotIn("daily", before)
        extended = DailyStore(original.path)
        initialize_daily(extended)
        self.assertEqual(extended.report(self.manager, plan["id"]), before)

    def test_migration_rollback_and_retry(self):
        import sqlite3
        from contextlib import contextmanager

        original = Store(Path(self.temp.name) / "migration.db")
        original.initialize()

        class Interrupted(DailyStore):
            @contextmanager
            def connection(inner, write=False):
                with super().connection(write) as db:
                    db.set_authorizer(
                        lambda action, name, *rest: (
                            sqlite3.SQLITE_DENY
                            if action == sqlite3.SQLITE_CREATE_TABLE
                            and name == "daily_records"
                            else sqlite3.SQLITE_OK
                        )
                    )
                    yield db

        with self.assertRaises(sqlite3.DatabaseError):
            initialize_daily(Interrupted(original.path))
        with original.connection() as db:
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='daily_extension'"
                ).fetchone()
            )
        initialize_daily(DailyStore(original.path))

    def test_detail_fact_must_match_completed_clients(self):
        body = self.body()
        row = body["indicators"][3]
        row["actual"] = 1
        with self.assertRaises(ValueError):
            DailyInput.model_validate(body)


if __name__ == "__main__":
    unittest.main()
