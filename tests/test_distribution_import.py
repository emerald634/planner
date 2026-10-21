import copy
import sqlite3
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from planner.distribution_queue import DistributionQueue, validate
from planner.distribution_import import import_once, import_snapshot
from planner.store import Store, EMPLOYEE_BINDINGS, SCHEMA
from planner.backup import create_backup, restore_backup

V = 8306778724
Y = 7939114214
S = 1073597301
AUTHORIZED = {V}  # Supervisor capability must be separately granted.


def snapshot():
    return {"schema": 1, "distribution_id": str(uuid4()), "workday": "2026-10-13",
            "confirmed_at": "2026-10-13T10:00:00+03:00", "confirmed_by": V,
            "variant_index": 2, "variant_id": "selected-variant-3", "stage_id": "IN_PROCESS", "total": 2,
            "allocations": [
                {"telegram_id": V, "bitrix_id": 460, "name": "Вячеслав", "dates": ["2026-10-12"], "count": 1,
                 "leads": [{"id": 10, "created_date": "2026-10-12", "stage_id": "IN_PROCESS"}]},
                {"telegram_id": Y, "bitrix_id": 110, "name": "Яна", "dates": ["2026-10-11"], "count": 1,
                 "leads": [{"id": 20, "created_date": "2026-10-11", "stage_id": "IN_PROCESS"}]}]}


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "planner.db")
        self.store.initialize()
        self.queue = DistributionQueue(self.root / "queue.db")
        self.queue.initialize()
        self.value = snapshot()

    def count(self, table):
        with self.store.connection() as db:
            return db.execute("SELECT count(*) FROM " + table).fetchone()[0]

    def test_roundtrip_repeat_restart_and_actual_initiator(self):
        self.assertTrue(self.queue.publish(self.value, AUTHORIZED))
        self.assertFalse(self.queue.publish(self.value, AUTHORIZED))
        before = self.queue.path.read_bytes()
        self.assertEqual(import_once(self.store, self.queue, AUTHORIZED)[0]["status"], "imported")
        import_once(Store(self.store.path), DistributionQueue(self.queue.path), AUTHORIZED)
        self.assertEqual(self.queue.path.read_bytes(), before)
        self.assertEqual(self.count("tasks"), 2)
        self.assertEqual(self.count("distributions"), 1)
        self.assertEqual(self.count("distribution_leads"), 2)
        with self.store.connection() as db:
            tasks = db.execute("SELECT * FROM tasks ORDER BY id").fetchall()
            for task in tasks:
                self.assertEqual((task["target"], task["locked"], task["creation_actor"]), (1, 1, "system"))
                actor = self.store.actor(V if task["employee_id"] == self.store.actor(V)["id"] else Y)
                history = self.store.history(actor, task["plan_id"])
                self.assertEqual(history[0]["actor_name"], "Система")
                self.assertIsNone(history[0]["actor_id"])
                self.assertEqual(history[0]["after_json"]["confirmed_by_telegram_id"], V)

    def test_authorization_is_explicit_not_manager_or_supervisor_role(self):
        for tg in (Y, S):
            value = copy.deepcopy(self.value)
            value["confirmed_by"] = tg
            with self.assertRaises(PermissionError):
                self.queue.publish(value, AUTHORIZED)
            with self.assertRaises(PermissionError):
                import_snapshot(self.store, value, AUTHORIZED)
        self.value["confirmed_by"] = S
        self.queue.publish(self.value, {S})
        self.assertEqual(import_snapshot(self.store, self.value, {S})["status"], "imported")

    def test_one_day_conflict_and_concurrent_duplicates(self):
        with ThreadPoolExecutor(2) as pool:
            result = list(pool.map(lambda _: self.queue.publish(self.value, AUTHORIZED), range(2)))
        self.assertEqual(sorted(result), [False, True])
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: import_snapshot(self.store, self.value, AUTHORIZED), range(2)))
        self.assertEqual(self.count("tasks"), 2)
        other = snapshot()
        with self.assertRaises(ValueError):
            self.queue.publish(other, AUTHORIZED)
        with self.assertRaises(ValueError):
            import_snapshot(self.store, other, AUTHORIZED)

    def test_reject_wrong_stage_duplicate_lead_dates_binding_and_counts(self):
        mutations = [lambda v: v.update(stage_id="NEW"),
                     lambda v: v["allocations"][1]["leads"][0].update(id=10),
                     lambda v: v["allocations"][1].update(dates=["2026-10-12"]),
                     lambda v: v["allocations"][0].update(bitrix_id=110),
                     lambda v: v["allocations"][0].update(count=2)]
        for mutate in mutations:
            value = copy.deepcopy(self.value)
            mutate(value)
            with self.assertRaises(ValueError):
                validate(value)
        self.assertEqual(self.count("tasks"), 0)

    def test_existing_draft_preserves_tasks(self):
        user = self.store.actor(V)
        plan = self.store.create_plan(user, self.value["workday"])
        task = self.store.add_task(user, plan["id"], {"title": "Существующая", "description": "", "kind": "general", "planned_minutes": 15, "target": None})
        import_snapshot(self.store, self.value, AUTHORIZED)
        self.assertEqual(self.count("plans"), 2)
        with self.store.connection() as db:
            self.assertEqual(dict(db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()), task)

    def test_approved_and_closed_unchanged_review_not_success(self):
        for status in ("approved", "closed"):
            with self.subTest(status=status), TemporaryDirectory() as temp:
                store = Store(Path(temp) / "p.db")
                store.initialize()
                user = store.actor(V)
                plan = store.create_plan(user, self.value["workday"])
                if status == "approved":
                    store.approve_plan(store.actor(S), plan["id"])
                else:
                    store.close_plan(user, plan["id"])
                before = store.get_plan(user, plan["id"])
                result = import_snapshot(store, self.value, AUTHORIZED)
                self.assertEqual(result["status"], "review")
                after = store.get_plan(user, plan["id"])
                before.pop("server_time")
                after.pop("server_time")
                self.assertEqual(before, after)

    def test_inactive_blocks_whole_snapshot(self):
        with self.store.connection(True) as db:
            db.execute("UPDATE employees SET active=0 WHERE telegram_id=?", (Y,))
        result = import_snapshot(self.store, self.value, AUTHORIZED)
        self.assertEqual(result["status"], "review")
        self.assertEqual(self.count("tasks"), 0)
        self.assertEqual(self.count("plans"), 0)

    def test_failure_mid_import_rolls_back_then_retries(self):
        self.queue.publish(self.value, AUTHORIZED)
        with self.store.connection(True) as db:
            db.execute("CREATE TRIGGER simulated_failure BEFORE INSERT ON tasks WHEN NEW.employee_id=2 BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            import_once(self.store, self.queue, AUTHORIZED)
        for table in ("tasks", "plans", "distributions", "system_audit", "distribution_tasks", "distribution_leads"):
            self.assertEqual(self.count(table), 0)
        with self.store.connection(True) as db:
            db.execute("DROP TRIGGER simulated_failure")
        self.assertEqual(import_once(Store(self.store.path), self.queue, AUTHORIZED)[0]["status"], "imported")

    def test_queue_read_missing_never_creates_and_append_only(self):
        missing = DistributionQueue(self.root / "missing.db")
        with self.assertRaises(FileNotFoundError):
            list(missing.read())
        self.assertFalse(missing.path.exists())
        self.queue.publish(self.value, AUTHORIZED)
        with closing(sqlite3.connect(self.queue.path)) as db, db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM confirmations")
        if os.name == "posix":
            self.assertEqual(self.queue.path.stat().st_mode & 0o777, 0o600)

    def test_queue_cannot_initialize_planner_or_modify_other_database(self):
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            DistributionQueue(self.store.path).initialize()
        self.assertEqual(before, self.store.path.read_bytes())

    def test_migration_failure_rolls_back_schema(self):
        path = self.root / "v2-fault.db"
        with closing(sqlite3.connect(path)) as db, db:
            for sql in SCHEMA:
                db.execute(sql)
            db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL,details TEXT NOT NULL)")
            db.execute("PRAGMA user_version=2")
        with patch("planner.distribution_import.MIGRATION", ("CREATE TABLE transient_test(id INTEGER)", "INVALID SQL")):
            with self.assertRaises(sqlite3.Error):
                Store(path).initialize()
        with Store(path).connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='transient_test'").fetchone())

    def test_v2_migration_preserves_data_idempotent_and_backup(self):
        path = self.root / "old.db"
        with closing(sqlite3.connect(path)) as db, db:
            for sql in SCHEMA:
                db.execute(sql)
            db.executemany("INSERT INTO employees(telegram_id,bitrix_id,name,role) VALUES(?,?,?,?)", EMPLOYEE_BINDINGS)
            db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL,details TEXT NOT NULL)")
            db.execute("PRAGMA user_version=2")
        store = Store(path)
        store.initialize()
        store.initialize()
        import_snapshot(store, self.value, AUTHORIZED)
        backup = create_backup(path, self.root)
        destination = self.root / "restore"
        destination.mkdir()
        restored = restore_backup(backup, destination)
        with Store(restored).connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT count(*) FROM distribution_leads").fetchone()[0], 2)
