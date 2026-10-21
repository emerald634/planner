import asyncio
import sqlite3
import time
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import tarfile
import json

from fastapi.testclient import TestClient
from tests import test_bot_confirmation as bot_base
from tests.test_planner import TOKEN, signed
from planner.settings import Settings
from planner.api import create_app
from planner.backup import create_backup, verify_backup, restore_backup
from planner.distribution_queue import DistributionQueue
from tests.test_distribution_import import snapshot
from planner.store import Store, SCHEMA, EMPLOYEE_BINDINGS
from deploy.package_release import package, ROOT
from deploy.release_check import check


class CompleteChainTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = bot_base.BotConfirmationTests.asyncSetUp
    asyncTearDown = bot_base.BotConfirmationTests.asyncTearDown
    state = bot_base.BotConfirmationTests.state
    send = bot_base.BotConfirmationTests.send
    click = bot_base.BotConfirmationTests.click
    callback_update = bot_base.BotConfirmationTests.callback_update
    result = bot_base.BotConfirmationTests.result

    async def test_bot_to_automatic_import_two_confirmations_and_reports(self):
        await self.result()
        await self.click('next')
        await self.click('confirm_distribution')
        for tg in (8306778724, 7939114214, 1073597301):
            self.access.add_user(tg, 123)
        path = Path(self.temp_dir.name) / 'full-chain.db'
        settings = Settings(TOKEN, path, self.access.path, distribution_queue=self.queue.path, distribution_confirmer_ids=frozenset({123}), distribution_poll_seconds=0.03)
        # The explicit test confirmer needs an identity for source provenance.
        store = Store(path)
        store.initialize()
        with store.connection(True) as db:
            db.execute("INSERT INTO employees(telegram_id,name,role) VALUES(123,'Тестовый инициатор','supervisor')")
        with TestClient(create_app(settings)) as client:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                with store.connection() as db:
                    if db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 2:
                        break
                await asyncio.sleep(0.03)
            else:
                self.fail('missing automatic import')
            for tg in (8306778724, 7939114214):
                headers = {'Authorization': 'tma ' + signed(tg)}
                plan = client.get('/api/plans', headers=headers).json()[0]
                approved = client.post(f"/api/plans/{plan['id']}/confirm", headers=headers)
                self.assertEqual(approved.status_code, 200)
            visible = client.get('/api/plans', headers={'Authorization':'tma '+signed(1073597301)}).json()
            self.assertEqual([p['status'] for p in visible], ['approved','approved'])
            for tg in (8306778724, 7939114214):
                headers = {'Authorization': 'tma ' + signed(tg)}
                plan = client.get('/api/plans', headers=headers).json()[0]
                approved = client.get(f"/api/plans/{plan['id']}", headers=headers)
                task = approved.json()['tasks'][0]
                endpoint = f"/api/tasks/{task['id']}"
                self.assertEqual(client.post(endpoint+'/timer', headers=headers, json={'action':'start'}).status_code, 200)
                stopped = client.post(endpoint+'/timer', headers=headers, json={'action':'stop'}).json()
                self.assertEqual(client.patch(endpoint, headers=headers, json={'revision':stopped['revision'],'actual_value':task['target'],'comment':'Тест','result':'Готово','status':'done'}).status_code, 200)
                self.assertEqual(client.post(f"/api/plans/{plan['id']}/close",headers=headers).status_code, 200)
            plans = client.get('/api/plans', headers={'Authorization':'tma '+signed(1073597301)}).json()
            self.assertEqual([p['status'] for p in plans], ['closed','closed'])
        with Store(path).connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 2)


class ReleaseTests(unittest.TestCase):
    def test_v2_live_backup_migration_preserves_every_existing_entity(self):
        from planner.store import today
        from datetime import date, timedelta
        with TemporaryDirectory() as temp:
            root = Path(temp)
            path = root/'legacy.db'
            with closing(sqlite3.connect(path)) as db, db:
                for sql in SCHEMA:
                    db.execute(sql)
                db.executemany('INSERT INTO employees(telegram_id,bitrix_id,name,role) VALUES(?,?,?,?)', EMPLOYEE_BINDINGS)
                db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL,details TEXT NOT NULL)')
                db.execute("INSERT INTO schema_migrations VALUES(2,1,'{}')")
                db.execute('PRAGMA user_version=2')
            old = Store(path)
            actor = old.actor(8306778724)
            boss = old.actor(1073597301)
            plan = old.create_plan(actor,today())
            task = old.add_task(actor,plan['id'],{'title':'Существующая цель','description':'Сохранить','kind':'quantitative','target':10,'planned_minutes':40})
            old.approve_plan(boss,plan['id'])
            old.patch_task(actor,task['id'],{'revision':1,'actual_value':3,'comment':'Комментарий','result':'Результат'})
            old.request_goal(actor,task['id'],{'field':'target','proposed':20,'reason':'Ожидает решения'})
            old.timer(actor,task['id'],'start')
            yesterday = (date.fromisoformat(today())-timedelta(days=1)).isoformat()
            closed = old.create_plan(actor,yesterday)
            old.add_task(actor,closed['id'],{'title':'Архивная','description':'','kind':'general','target':None,'planned_minutes':5})
            old.close_plan(actor,closed['id'])
            tables = ('employees','plans','tasks','goal_requests','audit','reports')
            with old.connection() as db:
                original = {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in tables}
            backup = create_backup(path,root)
            destination = root/'copy'
            destination.mkdir()
            migrated = Store(restore_backup(backup,destination))
            migrated.initialize()
            migrated.initialize()
            with migrated.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
                for table, rows in original.items():
                    actual = [dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY 1')]
                    if table == 'tasks':
                        for row in actual:
                            self.assertEqual(row.pop('creation_actor'),'employee')
                    self.assertEqual(actual,rows,table)
            with old.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)

    def test_queue_backup_live_connection_roundtrip(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            queue = DistributionQueue(root/'queue.db')
            queue.initialize()
            queue.publish(snapshot(), {8306778724})
            with closing(sqlite3.connect(queue.path)) as live:
                live.execute('SELECT * FROM confirmations').fetchall()
                live.execute('BEGIN IMMEDIATE')
                backup = create_backup(queue.path, root, 'queue')
                live.rollback()
            verify_backup(backup, 'queue')
            destination = root/'restore'
            destination.mkdir()
            restored = restore_backup(backup,destination,'queue')
            self.assertEqual(list(queue.read()),list(DistributionQueue(restored).read()))
            with self.assertRaises(FileExistsError):
                restore_backup(backup,destination,'queue')

    def test_stage2_archive_integrity_no_secrets_or_databases(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root/'stage2.tar.gz'
            with patch('deploy.package_release.build_frontend'):
                package(ROOT, archive, stage2=True)
            with tarfile.open(archive) as stream:
                stream.extractall(root/'release',filter='data')
            self.assertGreater(check(root/'release'), 20)
