import os
import sqlite3
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from access import AccessStore
from deploy.package_release import ROOT, package
from planner.api import create_app
from planner.backup import create_backup, restore_backup, verify_backup
from planner.ops import check
from planner.settings import Settings
from planner.store import EMPLOYEE_BINDINGS, SCHEMA, Store, today
from tests.test_planner import MANAGER, SUPERVISOR, TOKEN, signed

YANA = 7939114214


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.access = AccessStore(self.root / "access.db")
        self.access.initialize([MANAGER, YANA, SUPERVISOR])
        self.store = Store(self.root / "planner.db")
        self.store.initialize()

    def old_store(self):
        store = Store(self.root / "version1.db")
        with store.connection(True) as db:
            for sql in SCHEMA:
                db.execute(sql)
            db.executemany("INSERT INTO employees(telegram_id,bitrix_id,name,role) VALUES(?,?,?,?)", [
                (MANAGER, 460, "Вячеслав", "manager"), (None, 110, "Яна", "manager"),
                (SUPERVISOR, None, "Руководитель", "supervisor")])
            db.execute("PRAGMA user_version=1")
        return store

    def task_and_report(self, store):
        user = store.actor(MANAGER)
        plan = store.create_plan(user, today())
        store.add_task(user, plan["id"], {"title": "Сохранённая задача", "description": "", "kind": "general", "planned_minutes": 40, "target": None})
        return store.close_plan(user, plan["id"])

    def test_all_three_signed_employees_and_separate_bot_admin_role(self):
        settings = Settings(TOKEN, self.store.path, self.access.path, frozenset({MANAGER}), static_dir=self.root / "missing")
        with TestClient(create_app(settings)) as client:
            for tg, bitrix, name, role in EMPLOYEE_BINDINGS:
                with self.subTest(name=name):
                    response = client.get("/api/me", headers={"Authorization": "tma " + signed(tg)})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual((response.json()["user"]["role"], response.json()["user"]["bitrix_id"]), (role, bitrix))
                    self.assertEqual(response.json()["workday"], {"start": "10:00", "end": "19:00", "timezone": "Europe/Moscow", "reminders_enabled": False})
            self.assertEqual(client.get("/api/employees", headers={"Authorization": "tma " + signed(MANAGER)}).status_code, 403)

    def test_no_time_lock_after_19_or_extra_reminder_subscriptions(self):
        user = self.store.actor(MANAGER)
        plan = self.store.create_plan(user, today())
        with patch("planner.store.time.time", return_value=1791914400):
            task = self.store.add_task(user, plan["id"], {"title": "Вечерняя правка", "description": "", "kind": "general", "planned_minutes": 20, "target": None})
            updated = self.store.patch_task(user, task["id"], {"revision": 1, "comment": "После 19:00"})
            self.assertEqual(updated["comment"], "После 19:00")
        self.assertEqual(self.access.list_reminders(), [])

    def test_v1_migration_fills_yana_once_preserves_history_and_custom_data(self):
        store = self.old_store()
        report = self.task_and_report(store)
        with store.connection(True) as db:
            db.execute("UPDATE employees SET name='Яна — сохранённое имя',active=0 WHERE bitrix_id=110")
            old_audit = [tuple(r) for r in db.execute("SELECT * FROM audit")]
        store.initialize()
        store.initialize()
        with store.connection() as db:
            yana = db.execute("SELECT * FROM employees WHERE bitrix_id=110").fetchone()
            self.assertEqual((yana["telegram_id"], yana["name"], yana["active"]), (YANA, "Яна — сохранённое имя", 0))
            self.assertEqual(db.execute("SELECT count(*) FROM employees").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], 3)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(old_audit, [tuple(r) for r in db.execute("SELECT * FROM audit")])
        self.assertEqual(report, store.report(store.actor(MANAGER), report["id"]))

    def test_new_planner_file_is_private_on_posix(self):
        if os.name == "posix":
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_nonempty_binding_not_overwritten_and_detected_by_checks(self):
        store = self.old_store()
        with store.connection(True) as db:
            db.execute("UPDATE employees SET telegram_id=999999 WHERE bitrix_id=110")
        store.initialize()
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT telegram_id FROM employees WHERE bitrix_id=110").fetchone()[0], 999999)
        result = check(self.access.path, store.path, {MANAGER})
        self.assertFalse(result["ready"])
        self.assertFalse(result["employees"][1]["binding_ok"])

    def test_conflicting_binding_rolls_back_entire_migration(self):
        store = self.old_store()
        with store.connection(True) as db:
            db.execute("INSERT INTO employees(telegram_id,bitrix_id,name,role) VALUES(?,999,'Другой','manager')", (YANA,))
        with self.assertRaises(RuntimeError):
            store.initialize()
        with store.connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT telegram_id FROM employees WHERE bitrix_id=110").fetchone()[0])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())
            self.assertEqual(db.execute("SELECT count(*) FROM employees").fetchone()[0], 4)

    def test_backup_roundtrip_report_history_persistence_and_no_overwrite(self):
        report = self.task_and_report(self.store)
        self.assertEqual(report, Store(self.store.path).report(self.store.actor(MANAGER), report["id"]))
        backups = self.root / "backups"
        backups.mkdir()
        before = self.store.path.read_bytes()
        backup = create_backup(self.store.path, backups)
        verify_backup(backup)
        self.assertEqual(self.store.path.read_bytes(), before)
        restored = self.root / "restored"
        restored.mkdir()
        target = restore_backup(backup, restored)
        fresh = Store(target)
        self.assertEqual(report, fresh.report(fresh.actor(MANAGER), report["id"]))
        self.assertEqual(self.store.history(self.store.actor(MANAGER), report["id"]), fresh.history(fresh.actor(MANAGER), report["id"]))
        old = target.read_bytes()
        with self.assertRaises(FileExistsError):
            restore_backup(backup, restored)
        self.assertEqual(old, target.read_bytes())

    def test_tampered_backup_or_access_database_cannot_be_restored(self):
        backup = create_backup(self.store.path, self.root)
        with backup.open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaises(ValueError):
            verify_backup(backup)
        before = self.access.path.read_bytes()
        with self.assertRaises(ValueError):
            create_backup(self.access.path, self.root)
        self.assertEqual(before, self.access.path.read_bytes())

    def test_readonly_checks_and_readiness_failure_no_file_creation(self):
        before = self.access.path.read_bytes()
        result = check(self.access.path, self.store.path, {MANAGER})
        self.assertTrue(result["ready"])
        self.assertEqual(self.access.path.read_bytes(), before)
        app = create_app(Settings(TOKEN, self.store.path, self.access.path, static_dir=self.root / "missing"))
        with TestClient(app) as client:
            self.assertEqual(client.get("/healthz").json(), {"status": "ok"})
            self.access.path.unlink()
            self.assertEqual(client.get("/healthz").status_code, 503)
            self.assertFalse(self.access.path.exists())

    def test_production_requires_static_build_and_no_demo_auth_mode(self):
        app = create_app(Settings(TOKEN, self.store.path, self.access.path, static_dir=self.root / "missing", production=True))
        with self.assertRaises(RuntimeError), TestClient(app):
            pass
        with TestClient(create_app(Settings(TOKEN, self.store.path, self.access.path))) as client:
            self.assertEqual(client.get("/api/me?demo=1&role=supervisor&user_id=8306778724").status_code, 401)
            self.assertEqual(client.get("/preview.html").status_code, 404)

    def test_source_release_never_contains_secrets_databases_or_bot_entry(self):
        archive = self.root / "release.tar.gz"
        with patch("deploy.package_release.build_frontend"):
            package(ROOT, archive)
        with tarfile.open(archive) as stream:
            names = stream.getnames()
        for needed in ("planner/api.py", "planner/backup.py", "compose.planner.yaml", "miniapp/pnpm-lock.yaml", "deploy/planner-compose.sh"):
            self.assertIn(needed, names)
        self.assertIn("miniapp/dist/index.html", names)
        self.assertIn("frontend-build.json", names)
        self.assertFalse(any(n.startswith("miniapp/src/") or n.endswith(".map") for n in names))
        for name in names:
            self.assertNotIn("node_modules", name)
            self.assertNotIn(".env", name.split('/'))
            self.assertFalse(name.endswith((".db", ".db-wal", ".db-shm")))
        for forbidden in ("bot.py", "compose.yaml", "Dockerfile", "miniapp/preview.html", "miniapp/src/demo.tsx"):
            self.assertNotIn(forbidden, names)
        with self.assertRaises(FileExistsError):
            package(ROOT, archive)

    def test_packaged_production_serves_assets_requires_auth_and_rejects_tampering(self):
        archive = self.root / "production.tar.gz"
        with patch("deploy.package_release.build_frontend"):
            package(ROOT, archive)
        release = self.root / "release"
        with tarfile.open(archive) as stream:
            stream.extractall(release, filter="data")
        settings = Settings(TOKEN, self.store.path, self.access.path,
                            static_dir=release / "miniapp/dist", production=True)
        with TestClient(create_app(settings)) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/api/me?demo=1&role=supervisor").status_code, 401)
            self.assertEqual(client.get("/preview.html").status_code, 404)
            self.assertEqual(client.get("/frontend-build.json").status_code, 404)
            self.assertEqual(client.get("/api/me", headers={"Authorization": "tma " + signed(YANA)}).status_code, 200)
        asset = next((settings.static_dir / "assets").glob("*.js"))
        asset.write_text("tampered", encoding="utf-8")
        with self.assertRaises(RuntimeError), TestClient(create_app(settings)):
            pass
