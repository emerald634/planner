"""Bridge regressions on synthetic data only; no working web auth or network."""
import json
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from access import AccessStore
from planner.api import create_app
from planner.backup import create_backup, restore_backup, verify_backup, validate
from planner.distribution_import import MIGRATION
from planner.settings import Settings
from planner.store import Store, SCHEMA, EMPLOYEE_BINDINGS, SCHEMA_VERSION
from planner.web_auth.migration import migrate_synthetic
from planner.web_auth.schema import BASELINE_OBJECTS, REGISTRY_DETAILS, objects
from tests import test_planner as baseline
from tests import test_plan_confirmation as confirmation
from tests import test_distribution_import as imports
from tests import test_sync as sync
from tests.web_auth_fixtures import (NOW, business_snapshot, connect, create_schema4,
                                     digest, seed_auth)


def auth_snapshot(db):
    return {name: list(db.execute(f'SELECT * FROM "{name}" ORDER BY 1')) for name, in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'web_%'")}


def seed_all_auth(db):
    seed_auth(db)
    with db:
        db.execute("INSERT INTO web_password_actions(token_hash,credential_id,credential_version,purpose,issued_by,issued_at,expires_at) VALUES(?,1,1,'reset',3,?,?)", (digest('unused-code'), NOW, NOW+1800))
        db.execute("INSERT INTO web_login_attempts VALUES(1,'synthetic-login','synthetic-source',1,'denied')")
        db.execute("INSERT INTO web_auth_audit VALUES(1,'login_denied','system',NULL,1,1,'synthetic-correlation')")


class OnSchema5:
    def setUp(self):
        super().setUp()
        with closing(connect(self.store.path)) as db:
            migrate_synthetic(db, applied_at=NOW)
            seed_all_auth(db)
            self.original_auth = auth_snapshot(db)
        Store(self.store.path).initialize()

    def tearDown(self):
        with closing(connect(self.store.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
            self.assertEqual(auth_snapshot(db), self.original_auth)


class Schema5PlannerTests(OnSchema5, baseline.PlannerTests):
    pass


class Schema5ConfirmationTests(OnSchema5, confirmation.ConfirmationTests):
    pass


class Schema5ImportTests(OnSchema5, imports.ImportTests):
    pass


class Schema5SyncTests(OnSchema5, sync.SyncTests):
    pass


class BridgeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='bridge-boundary-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'synthetic.db'
        create_schema4(self.path)

    def test_schema4_startup_is_noop_and_does_not_load_migration(self):
        with closing(connect(self.path)) as db:
            original = business_snapshot(db), objects(db)
        with patch('planner.web_auth.migration.migrate_synthetic', side_effect=AssertionError('must not migrate')):
            for _ in range(2):
                Store(self.path).initialize()
        with closing(connect(self.path)) as db:
            self.assertEqual((business_snapshot(db), objects(db)), original)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
        self.assertEqual(SCHEMA_VERSION, 4)

    def test_supported_historical_paths_have_exact_same_schema4_manifest(self):
        for version in (0, 1, 2, 3):
            with self.subTest(version=version):
                path = self.root/f'legacy-{version}.db'
                if version:
                    with closing(connect(path)) as db, db:
                        for sql in SCHEMA:
                            db.execute(sql)
                        db.executemany('INSERT INTO employees(telegram_id,bitrix_id,name,role) VALUES(?,?,?,?)', EMPLOYEE_BINDINGS)
                        if version >= 2:
                            db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL,details TEXT NOT NULL)')
                            db.execute("INSERT INTO schema_migrations VALUES(2,1,'{}')")
                        if version == 3:
                            for sql in MIGRATION:
                                db.execute(sql)
                            db.execute("INSERT INTO schema_migrations VALUES(3,1,'{}')")
                        db.execute(f'PRAGMA user_version={version}')
                Store(path).initialize()
                with closing(connect(path)) as db:
                    self.assertEqual(objects(db), BASELINE_OBJECTS)
                    before = business_snapshot(db)
                    migrate_synthetic(db, applied_at=NOW)
                Store(path).initialize()
                with closing(connect(path)) as db:
                    self.assertEqual(business_snapshot(db), before)

    def test_unknown_incomplete_modified_manifest_registry_fk_are_refused_without_repair(self):
        mutations = {
            'schema6': 'PRAGMA user_version=6',
            'unknown': 'PRAGMA user_version=999',
            'missing-table': 'DROP TABLE web_auth_audit',
            'ddl': 'ALTER TABLE web_credentials ADD COLUMN unexpected TEXT',
            'missing-manifest': 'DELETE FROM schema_migrations WHERE version=5',
            'wrong-manifest': "UPDATE schema_migrations SET details='{}' WHERE version=5",
            'registry': 'DELETE FROM schema_migrations WHERE version=3',
            'fk': "INSERT INTO web_credentials VALUES(1,999,'orphan','opaque',1,'ready',1,1,1)",
            'partial': 'PRAGMA user_version=5',
        }
        for name, mutation in mutations.items():
            path = self.root/f'{name}.db'
            create_schema4(path)
            with closing(connect(path)) as db:
                if name != 'partial':
                    migrate_synthetic(db, applied_at=NOW)
                db.execute('PRAGMA foreign_keys=OFF')
                with db:
                    db.execute(mutation)
                old = list(db.iterdump())
            with self.subTest(case=name), self.assertRaises((ValueError, RuntimeError, sqlite3.Error)):
                Store(path).initialize()
            with closing(connect(path)) as db:
                self.assertEqual(list(db.iterdump()), old)
                with self.assertRaises((ValueError, sqlite3.Error)):
                    validate(db)
            with self.subTest(backup_case=name), self.assertRaises((ValueError, sqlite3.Error)):
                create_backup(path,self.root)

    def test_corrupt_file_readonly_connection_and_busy_startup(self):
        corrupt = self.root/'corrupt.db'
        corrupt.write_bytes(b'not a sqlite database')
        with self.assertRaises(sqlite3.DatabaseError):
            Store(corrupt).initialize()
        with closing(connect(self.path)) as db:
            migrate_synthetic(db, applied_at=NOW)
        # Portable permission-denial simulation, not a claim about POSIX UID/GID.
        with patch('planner.store.sqlite3.connect', side_effect=PermissionError('synthetic permission denial')):
            with self.assertRaises(PermissionError):
                Store(self.path).initialize()
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as ro:
            validate(ro)
            ro.execute('BEGIN')
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("UPDATE plans SET status='draft'")
            ro.rollback()
        with closing(connect(self.path)) as lock:
            lock.execute('BEGIN IMMEDIATE')
            original = sqlite3.connect
            def bounded(*args, **kwargs):
                kwargs['timeout'] = 0.01
                return original(*args, **kwargs)
            with patch('planner.store.sqlite3.connect', side_effect=bounded):
                with self.assertRaises(sqlite3.OperationalError):
                    Store(self.path).initialize()
            lock.rollback()
        Store(self.path).initialize()

    def test_web_disabled_even_with_credentials_cookie_and_valid_telegram(self):
        with closing(connect(self.path)) as db:
            migrate_synthetic(db, applied_at=NOW)
            seed_all_auth(db)
            before = auth_snapshot(db)
        access = AccessStore(self.root/'access.db')
        access.initialize([101,102,103,999])
        settings = Settings(baseline.TOKEN,self.path,access.path,frozenset({999}),static_dir=self.root/'missing')
        with TestClient(create_app(settings)) as client:
            client.cookies.set('__Host-planner_session', 'synthetic-not-a-session')
            self.assertEqual(client.get('/api/me').status_code,401)
            for endpoint in ('login','logout','me','password','reset','csrf'):
                self.assertEqual(client.post('/api/web/auth/'+endpoint,json={}).status_code,404)
            self.assertEqual(client.get('/api/web/accounts').status_code,404)
            for user in (101,102,103):
                self.assertEqual(client.get('/api/me',headers={'Authorization':'tma '+baseline.signed(user)}).status_code,200)
            self.assertEqual(client.get('/api/me',headers={'Authorization':'tma '+baseline.signed(999)}).status_code,403)
        with closing(connect(self.path)) as db:
            self.assertEqual(auth_snapshot(db),before)


class BridgeRollbackBackupTests(unittest.TestCase):
    def test_rollback_current_schema5_new_records_auth_and_live_backup_restore(self):
        with TemporaryDirectory(prefix='bridge-rollback-') as directory:
            root = Path(directory)
            path = root/'synthetic.db'
            create_schema4(path)
            store = Store(path)
            store.initialize()
            with closing(connect(path)) as db:
                historical = business_snapshot(db)
                migrate_synthetic(db, applied_at=NOW)
                seed_all_auth(db)
                old_auth = auth_snapshot(db)
            store.initialize()
            actor = store.actor(102)
            supervisor = store.actor(103)
            clock = patch('planner.store.today', return_value='2099-02-01')
            current_day = clock.start()
            self.addCleanup(clock.stop)
            new = store.create_plan(actor,'2099-02-01')
            values = dict(title='Synthetic new task',description='',kind='quantitative',planned_minutes=30,target=10)
            task = store.add_task(actor,new['id'],values)
            store.confirm_plan(actor,new['id'])
            request = store.request_goal(actor,task['id'],dict(field='target',proposed=12,reason='Synthetic approval'))
            store.decide(supervisor,request['id'],'approved','Synthetic decision')
            store.patch_task(actor,task['id'],dict(revision=2,actual_value=5,comment='Synthetic comment',result='Synthetic result'))
            store.timer(actor,task['id'],'start')
            store.timer(actor,task['id'],'pause')
            store.timer(actor,task['id'],'start')
            store.timer(actor,task['id'],'finish')
            store.close_plan(actor,new['id'])
            # A separate running timer must survive returning to the bridge.
            current_day.return_value = '2099-02-02'
            running = store.create_plan(actor,'2099-02-02')
            active = store.add_task(actor,running['id'],values)
            store.timer(actor,active['id'],'start')
            with closing(connect(path)) as db:
                current = business_snapshot(db)
            returned = Store(path)
            returned.initialize()  # same current schema5, never an old backup
            self.assertEqual(returned.report(actor,new['id'])['status'],'closed')
            self.assertTrue(returned.history(actor,new['id']))
            with closing(connect(path)) as db:
                self.assertEqual(business_snapshot(db),current)
                self.assertEqual(auth_snapshot(db),old_auth)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)
                for table, data in historical[1].items():
                    # Rows intentionally touched by normal execution (timer/employee plan)
                    # are in new plans only; all historical rows must still exist.
                    for row in data['rows']:
                        self.assertIn(row, business_snapshot(db)[1][table]['rows'])
            access=AccessStore(root/'access.db'); access.initialize([101,102,103])
            with TestClient(create_app(Settings(baseline.TOKEN,path,access.path,static_dir=root/'missing'))) as client:
                headers={'Authorization':'tma '+baseline.signed(102)}
                self.assertEqual(client.get(f'/api/plans/{new["id"]}',headers=headers).status_code,200)
                self.assertEqual(client.get(f'/api/plans/{new["id"]}/report',headers=headers).json(),returned.report(actor,new['id']))
                self.assertEqual(client.post('/api/plans',headers=headers,json={'day':'2099-05-01'}).status_code,201)
                self.assertEqual(client.get('/api/me').status_code,401)
                self.assertEqual(client.post('/api/web/auth/login',json={}).status_code,404)
            backup_dir=root/'backups'; backup_dir.mkdir()
            gate=threading.Event()
            def writer():
                gate.wait(5)
                for index in range(5):
                    Store(path).create_plan(actor,f'2099-03-{index+1:02d}')
            with closing(connect(path)) as live, ThreadPoolExecutor(1) as pool:
                live.execute('SELECT * FROM plans').fetchall()  # active connection
                pending=pool.submit(writer)
                gate.set()
                backup=create_backup(path,backup_dir)
                pending.result(timeout=10)
            verify_backup(backup)
            target=root/'restored'; target.mkdir()
            restored=restore_backup(backup,target)
            restored_store=Store(restored); restored_store.initialize()
            self.assertEqual(restored_store.report(actor,new['id']),returned.report(actor,new['id']))
            self.assertEqual(restored_store.history(actor,new['id']),returned.history(actor,new['id']))
            with closing(connect(restored)) as db, closing(connect(backup)) as copy:
                self.assertEqual(business_snapshot(db),business_snapshot(copy))
                self.assertEqual(auth_snapshot(db),old_auth)
                self.assertIsNotNone(db.execute('SELECT timer_started FROM tasks WHERE id=?',(active['id'],)).fetchone()[0])
            restored_store.create_plan(actor,'2099-04-01')
            with self.assertRaises(FileExistsError):
                restore_backup(backup,target)

    def test_backup_restore_schema1_to4_without_migration(self):
        for version in (1,2,3,4):
            with self.subTest(version=version), TemporaryDirectory(prefix='bridge-backup-') as directory:
                root=Path(directory); path=root/'synthetic.db'
                # Build supported historical schema without opening a newer Store.
                with closing(connect(path)) as db, db:
                    for sql in SCHEMA:
                        db.execute(sql)
                    if version>=2:
                        db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL,details TEXT NOT NULL)')
                        db.execute("INSERT INTO schema_migrations VALUES(2,1,'{}')")
                    if version>=3:
                        for sql in MIGRATION: db.execute(sql)
                        db.execute("INSERT INTO schema_migrations VALUES(3,1,'{}')")
                    if version==4:
                        db.execute("CREATE TABLE import_attempts(id TEXT PRIMARY KEY,status TEXT NOT NULL CHECK(status IN ('imported','review','error')),attempts INTEGER NOT NULL,last_attempt INTEGER NOT NULL,error_code TEXT NOT NULL)")
                        db.execute("INSERT INTO schema_migrations VALUES(4,1,'{}')")
                    db.execute(f'PRAGMA user_version={version}')
                copy=create_backup(path,root);verify_backup(copy)
                target=root/'restore';target.mkdir();restored=restore_backup(copy,target)
                with closing(connect(restored)) as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],version)
