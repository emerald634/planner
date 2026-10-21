import sqlite3
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from planner.store import SCHEMA_VERSION, Store
from planner.web_auth.migration import MigrationError, migrate_synthetic
from planner.web_auth.policy import login_allowed
from planner.web_auth.schema import DDL, REGISTRY_DETAILS, objects
from tests.web_auth_fixtures import (NEW_HASH, NOW, business_snapshot, connect,
    create_schema4, issue_session_model, load_credential,
    redeem_model, reset_model, seed_auth)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="web-auth-migration-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.db"
        create_schema4(self.path)

    def db(self, timeout=1):
        db = connect(self.path, timeout)
        self.addCleanup(db.close)
        return db

    def test_additive_migration_preserves_every_old_value_and_object_and_reopens(self):
        db = self.db()
        before = business_snapshot(db)
        self.assertTrue(migrate_synthetic(db, applied_at=NOW))
        self.assertEqual(business_snapshot(db), before)
        self.assertFalse(migrate_synthetic(db, applied_at=NOW+1))
        self.assertEqual(business_snapshot(db), before)
        self.assertEqual(db.execute("SELECT applied_at,details FROM schema_migrations WHERE version=5").fetchone(), (NOW, REGISTRY_DETAILS))
        reopened = self.db()
        self.assertFalse(migrate_synthetic(reopened, applied_at=NOW+2))
        self.assertEqual(business_snapshot(reopened), before)
        for table, snapshot in before[1].items():
            self.assertTrue(snapshot["rows"], table)

    def test_store_stays_schema4_and_refuses_schema5(self):
        Store(self.path).initialize()
        self.assertEqual(SCHEMA_VERSION, 4)
        db = self.db()
        migrate_synthetic(db, applied_at=NOW)
        with self.assertRaisesRegex(RuntimeError, "более новой"):
            Store(self.path).initialize()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)

    def test_row_factory_explicit_autocommit_and_no_entrypoint_import(self):
        # Connection.commit() is a no-op with autocommit=True on Python 3.12+.
        db = sqlite3.connect(self.path, autocommit=True)
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        self.assertTrue(migrate_synthetic(db, applied_at=NOW))
        self.assertFalse(db.in_transaction)
        self.assertEqual(self.db().execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertFalse(migrate_synthetic(db, applied_at=NOW))
        probe = subprocess.run([sys.executable, "-B", "-c",
            "import sys; import planner.api; assert not any(n.startswith('planner.web_auth') for n in sys.modules)"],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_unknown_versions_are_refused_without_any_change(self):
        db = self.db()
        for version in (0, 3, 6, 999):
            db.execute(f"PRAGMA user_version={version}")
            before = objects(db), business_snapshot(db)
            with self.assertRaises(MigrationError):
                migrate_synthetic(db, applied_at=NOW)
            self.assertEqual((objects(db), business_snapshot(db)), before)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], version)

    def test_modified_schema4_and_damaged_schema5_are_not_repaired(self):
        db = self.db()
        db.execute("DROP INDEX tasks_plan")
        with self.assertRaises(MigrationError):
            migrate_synthetic(db, applied_at=NOW)
        db.execute("CREATE INDEX tasks_plan ON tasks(plan_id)")
        migrate_synthetic(db, applied_at=NOW)
        with db:
            db.execute("UPDATE schema_migrations SET details='unknown' WHERE version=5")
        with self.assertRaises(MigrationError):
            migrate_synthetic(db, applied_at=NOW)
        with db:
            db.execute("UPDATE schema_migrations SET details=? WHERE version=5", (REGISTRY_DETAILS,))
        db.execute("DROP INDEX web_sessions_expiry")
        with self.assertRaises(MigrationError):
            migrate_synthetic(db, applied_at=NOW)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='web_sessions_expiry'").fetchone())

    def test_preexisting_transaction_and_foreign_key_corruption(self):
        db = self.db()
        db.execute("BEGIN")
        with self.assertRaises(MigrationError):
            migrate_synthetic(db, applied_at=NOW)
        self.assertTrue(db.in_transaction)
        db.rollback()
        db.execute("PRAGMA foreign_keys=OFF")
        with db:
            db.execute("UPDATE tasks SET created_by=999 WHERE id=1")
        with self.assertRaisesRegex(MigrationError, "foreign key"):
            migrate_synthetic(db, applied_at=NOW)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)

    def test_failure_at_every_step_rolls_back_ddl_registry_version_and_data(self):
        db = self.db()
        before = objects(db), business_snapshot(db)
        stages = ["validated", *(f"ddl:{i}" for i in range(len(DDL))), "registry", "version", "before_commit"]
        for stage in stages:
            with self.subTest(stage=stage):
                def fail(name):
                    if name == stage:
                        raise KeyboardInterrupt("synthetic fault")
                with self.assertRaises(KeyboardInterrupt):
                    migrate_synthetic(db, applied_at=NOW, checkpoint=fail)
                self.assertFalse(db.in_transaction)
                self.assertEqual((objects(db), business_snapshot(db)), before)
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertTrue(migrate_synthetic(db, applied_at=NOW))

    def test_process_crash_before_commit_and_durability_after_commit(self):
        before = business_snapshot(self.db())
        code = """
import os, sqlite3, sys
from planner.web_auth.migration import migrate_synthetic
db=sqlite3.connect(sys.argv[1])
def crash(stage):
    if stage == 'before_commit': os._exit(73)
migrate_synthetic(db, applied_at=10000, checkpoint=crash if sys.argv[2]=='before' else None)
os._exit(74)
"""
        for phase, exitcode in (("before", 73), ("after", 74)):
            result = subprocess.run([sys.executable, "-B", "-c", code, str(self.path), phase],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, exitcode, result.stderr)
            db = self.db()
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4 if phase == "before" else 5)
            self.assertEqual(business_snapshot(db), before)
        self.assertFalse(migrate_synthetic(self.db(), applied_at=NOW))

    def test_two_competing_migrators_serialize_to_one_commit(self):
        barrier = threading.Barrier(2)
        def run():
            db = connect(self.path, timeout=5)
            try:
                barrier.wait(timeout=5)
                return migrate_synthetic(db, applied_at=NOW)
            finally:
                db.close()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.db().execute("SELECT count(*) FROM schema_migrations WHERE version=5").fetchone()[0], 1)

    def test_two_process_migrators_share_the_sqlite_write_lock(self):
        code = """
import sqlite3, sys
from planner.web_auth.migration import migrate_synthetic
sys.stdin.readline()
db=sqlite3.connect(sys.argv[1],timeout=10)
try:
    print(int(migrate_synthetic(db,applied_at=10000)),flush=True)
finally:
    db.close()
"""
        children = []
        try:
            for _ in range(2):
                child = subprocess.Popen([sys.executable, "-B", "-c", code, str(self.path)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                children.append(child)
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda child: child.communicate("go\n", timeout=20), children))
            self.assertEqual([child.returncode for child in children], [0, 0], results)
            self.assertEqual(sorted(output.strip() for output, _ in results), ["0", "1"])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)


    def test_busy_lock_refuses_safely_then_retry_succeeds(self):
        lock = self.db()
        lock.execute("BEGIN IMMEDIATE")
        db = self.db(timeout=0.01)
        with self.assertRaises(sqlite3.OperationalError):
            migrate_synthetic(db, applied_at=NOW)
        self.assertFalse(db.in_transaction)
        lock.rollback()
        self.assertTrue(migrate_synthetic(db, applied_at=NOW))


class ResetTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="web-auth-reset-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.db"
        create_schema4(self.path)
        db = connect(self.path)
        try:
            migrate_synthetic(db, applied_at=NOW)
            seed_auth(db)
            self.business = business_snapshot(db)
        finally:
            db.close()

    def tearDown(self):
        db = connect(self.path)
        try:
            self.assertEqual(business_snapshot(db), self.business)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            db.close()

    def credential(self):
        db = connect(self.path)
        try:
            return load_credential(db)
        finally:
            db.close()

    def test_old_hash_sessions_and_login_are_immediately_invalid_and_new_login_restores(self):
        reset_model(self.path, "code")
        self.assertIsNone(self.credential().password_hash)
        self.assertFalse(issue_session_model(self.path, 1, "stale"))
        self.assertFalse(issue_session_model(self.path, 2, "pending"))
        db = connect(self.path)
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM web_sessions WHERE revoked_at IS NULL").fetchone()[0], 0)
        finally:
            db.close()
        self.assertTrue(redeem_model(self.path, "code"))
        self.assertEqual(self.credential().password_hash, NEW_HASH)
        self.assertTrue(issue_session_model(self.path, 3, "new"))
        self.assertFalse(redeem_model(self.path, "code"))

    def test_expired_code_cannot_restore_old_login(self):
        reset_model(self.path, "code")
        self.assertFalse(redeem_model(self.path, "code", now=NOW+1801))
        self.assertFalse(issue_session_model(self.path, 1, "old", now=NOW+1802))
        self.assertFalse(issue_session_model(self.path, 2, "pending", now=NOW+1802))

    def test_repeat_reset_invalidates_previous_code(self):
        reset_model(self.path, "first")
        reset_model(self.path, "second", now=NOW+2)
        self.assertFalse(redeem_model(self.path, "first"))
        self.assertTrue(redeem_model(self.path, "second"))

    def test_failed_reset_and_failed_redeem_roll_back_whole_transition(self):
        def fail():
            raise RuntimeError("synthetic fault")
        original = self.credential()
        with self.assertRaises(RuntimeError):
            reset_model(self.path, "failed", fault=fail)
        self.assertEqual(self.credential(), original)
        self.assertTrue(issue_session_model(self.path, 1, "still-original"))
        reset_model(self.path, "good", now=NOW+3)
        with self.assertRaises(RuntimeError):
            redeem_model(self.path, "good", now=NOW+4, fault=fail)
        self.assertIsNone(self.credential().password_hash)
        self.assertTrue(redeem_model(self.path, "good", now=NOW+4))

    def test_manager_cannot_reset_other_accounts(self):
        with self.assertRaises(PermissionError):
            reset_model(self.path, "denied", supervisor_id=2)
        self.assertTrue(login_allowed(employee_from_model(), self.credential()))

    def test_login_reset_race_both_orders_and_stale_verifier_result(self):
        # Proof is a version captured before a future real verifier. No mock password login.
        stale_proof = self.credential().version
        self.assertTrue(issue_session_model(self.path, stale_proof, "login-before-reset", now=NOW))
        barrier = threading.Barrier(2)
        def login():
            barrier.wait(timeout=5)
            return issue_session_model(self.path, stale_proof, "racing-login", now=NOW+1)
        def reset():
            barrier.wait(timeout=5)
            reset_model(self.path, "code", now=NOW+1)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(login)
            second = pool.submit(reset)
            first.result(timeout=10)
            second.result(timeout=10)
        self.assertFalse(issue_session_model(self.path, stale_proof, "delayed-login"))
        db = connect(self.path)
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM web_sessions WHERE revoked_at IS NULL").fetchone()[0], 0)
        finally:
            db.close()

    def test_two_redeemers_consume_once(self):
        reset_model(self.path, "code")
        barrier = threading.Barrier(2)
        def redeem():
            barrier.wait(timeout=5)
            return redeem_model(self.path, "code")
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: redeem(), range(2))), [False, True])


def employee_from_model():
    from planner.web_auth.models import Employee, Role
    return Employee(1, Role.MANAGER, True)
