import asyncio
import copy
import json
import sqlite3
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

from fastapi.testclient import TestClient
from planner.api import create_app
from planner.settings import Settings
from planner.store import Store
from planner.sync import sync_once, sync_loop, distribution_notices
from tests import test_distribution_import as base
from tests.test_planner import TOKEN, signed
from access import AccessStore


class SyncTests(unittest.TestCase):
    setUp = base.ImportTests.setUp

    def test_restart_parallel_and_read_only(self):
        self.queue.publish(self.value, base.AUTHORIZED)
        before = self.queue.path.read_bytes()
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: sync_once(Store(self.store.path), self.queue.path, base.AUTHORIZED), range(2)))
        sync_once(Store(self.store.path), self.queue.path, base.AUTHORIZED)
        self.assertEqual(before, self.queue.path.read_bytes())
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM distributions').fetchone()[0], 1)

    def test_bad_record_does_not_block_good_and_state_persisted(self):
        with closing(sqlite3.connect(self.queue.path)) as db, db:
            db.execute("INSERT INTO confirmations VALUES('bad','2026-10-12','invalid-json','bad')")
        self.queue.publish(self.value, base.AUTHORIZED)
        self.assertEqual(sync_once(self.store, self.queue.path, base.AUTHORIZED), ['error', 'imported'])
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM import_attempts WHERE id='bad'").fetchone()[0], 'error')
        sync_once(self.store, self.queue.path, base.AUTHORIZED)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT attempts FROM import_attempts WHERE id='bad'").fetchone()[0], 2)

    def test_retry_after_transaction_failure(self):
        self.queue.publish(self.value, base.AUTHORIZED)
        with self.store.connection(True) as db:
            db.execute("CREATE TRIGGER failing BEFORE INSERT ON tasks BEGIN SELECT RAISE(ABORT,'fault'); END")
        self.assertEqual(sync_once(self.store, self.queue.path, base.AUTHORIZED), ['error'])
        with self.store.connection(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM distributions').fetchone()[0], 0)
            db.execute('DROP TRIGGER failing')
        self.assertEqual(sync_once(self.store, self.queue.path, base.AUTHORIZED), ['imported'])

    def test_notices_scoped_source_no_lead_ids(self):
        manager = self.store.actor(base.V)
        plan = self.store.create_plan(manager, self.value['workday'])
        self.store.approve_plan(self.store.actor(base.S), plan['id'])
        self.queue.publish(self.value, base.AUTHORIZED)
        sync_once(self.store, self.queue.path, base.AUTHORIZED)
        own = distribution_notices(self.store, manager)
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]['status'], 'review')
        self.assertEqual(own[0]['reason'], 'plan_already_confirmed_or_closed')
        supervisor = distribution_notices(self.store, self.store.actor(base.S))
        self.assertEqual(len(supervisor), 2)
        self.assertNotIn('leads', json.dumps(supervisor))
        access = AccessStore(self.root / 'access.db')
        access.initialize([base.V, base.Y, base.S])
        with TestClient(create_app(Settings(TOKEN, self.store.path, access.path))) as client:
            self.assertEqual(client.get('/api/distributions').status_code, 401)
            response = client.get('/api/distributions?employee_id=2', headers={'Authorization': 'tma ' + signed(base.V)})
            self.assertEqual(response.status_code, 403)
        yana = self.store.actor(base.Y)
        p = self.store.list_plans(yana)[0]
        task = self.store.get_plan(yana, p['id'])['tasks'][0]
        self.assertEqual(task['distribution_source']['name'], 'Утреннее распределение')
        self.assertEqual(task['distribution_source']['count'], 1)

    def test_automatic_lifespan_missing_queue_then_recovery(self):
        access = AccessStore(self.root / 'access.db')
        access.initialize([base.V])
        path = self.root / 'late.db'
        settings = Settings(TOKEN, self.store.path, access.path, distribution_queue=path,
                            distribution_confirmer_ids=frozenset(base.AUTHORIZED), distribution_poll_seconds=0.03)
        with TestClient(create_app(settings)) as client:
            self.assertEqual(client.get('/healthz').status_code, 200)
            self.assertFalse(path.exists())
            queue = base.DistributionQueue(path)
            queue.initialize()
            queue.publish(self.value, base.AUTHORIZED)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                with self.store.connection() as db:
                    if db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 2:
                        break
                time.sleep(0.03)
            else:
                self.fail('automatic import did not recover')

    def test_closed_plan_review_and_inactive_identity_not_exposed(self):
        manager = self.store.actor(base.V)
        plan = self.store.create_plan(manager, self.value['workday'])
        report = self.store.close_plan(manager, plan['id'])
        self.queue.publish(self.value, base.AUTHORIZED)
        sync_once(self.store, self.queue.path, base.AUTHORIZED)
        self.assertEqual(self.store.report(manager, plan['id']), report)
        self.assertEqual(distribution_notices(self.store, manager)[0]['status'], 'review')
        with self.store.connection(True) as db:
            db.execute('UPDATE employees SET telegram_id=999 WHERE id=?', (manager['id'],))
        self.assertEqual(distribution_notices(self.store, self.store.actor(999)), [])
        notices = distribution_notices(self.store, self.store.actor(base.S))
        self.assertTrue(any(n['employee_name'] == 'Привязка сотрудников требует проверки' for n in notices))

    def test_commit_before_attempt_status_recovers_on_restart(self):
        self.queue.publish(self.value, base.AUTHORIZED)
        from planner.distribution_import import import_snapshot
        import_snapshot(self.store, self.value, base.AUTHORIZED)
        with self.store.connection(True) as db:
            db.execute("INSERT INTO import_attempts VALUES(?,'error',1,1,'record_failed')", (self.value['distribution_id'],))
        sync_once(Store(self.store.path), self.queue.path, base.AUTHORIZED)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM import_attempts').fetchone()[0], 'imported')
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 2)
