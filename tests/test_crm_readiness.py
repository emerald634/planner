import json
import tempfile
import unittest
from pathlib import Path

import httpx
from planner.daily import DailyStore
from planner.daily_crm import ReadOnlyCRM, SourceUnavailable
from planner.server_migration import migrate_server, save_observation


class CRMReadinessTests(unittest.TestCase):
    def client(self, payload):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        )
        self.addCleanup(client.close)
        return ReadOnlyCRM("https://synthetic.invalid/rest/x", client)

    def test_malformed_records_types(self):
        for value in (None, 1, "bad", [], True):
            with self.subTest(value=value), self.assertRaises(SourceUnavailable):
                self.client({"result": {"items": [value]}}).pages(
                    "crm.item.list", {}, "items"
                )

    def test_malformed_envelopes(self):
        for value in (None, [], {}, {"result": []}, {"result": {"items": None}}):
            with self.subTest(value=value), self.assertRaises(SourceUnavailable):
                self.client(value).pages("crm.item.list", {}, "items")

    def test_owner_types_never_coerce_to_another_employee(self):
        for value in (True, 1.2, None, {}, "1x"):
            gateway = self.client(
                {
                    "result": {
                        "items": [
                            {
                                "id": 1,
                                "assignedById": value,
                                "createdTime": "2026-10-28T12:00:00+03:00",
                            }
                        ]
                    }
                }
            )
            with self.subTest(value=value), self.assertRaises(SourceUnavailable):
                gateway.source("leads", {"bitrix_id": 1}, "2026-10-28")

    def test_timeout_and_oversized_body(self):
        c = httpx.Client(
            transport=httpx.MockTransport(
                lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("synthetic"))
            )
        )
        self.addCleanup(c.close)
        with self.assertRaises(SourceUnavailable):
            ReadOnlyCRM("https://synthetic.invalid", c).pages(
                "crm.item.list", {}, "items"
            )
        c2 = httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"x" * 2_000_001)
            )
        )
        self.addCleanup(c2.close)
        with self.assertRaises(SourceUnavailable):
            ReadOnlyCRM("https://synthetic.invalid", c2).pages(
                "crm.item.list", {}, "items"
            )
        with self.assertRaises(SourceUnavailable):
            self.client({}).pages("crm.item.list", {}, "items", deadline=0.001)

    def test_conflicting_duplicate_refused(self):
        with self.assertRaises(SourceUnavailable):
            self.client(
                {
                    "result": {
                        "items": [{"id": 1, "title": "A"}, {"id": 1, "title": "B"}]
                    }
                }
            ).pages("crm.item.list", {}, "items")

    def test_scoped_projection_and_no_quality_claims(self):
        gateway = self.client(
            {
                "result": [
                    {
                        "ID": 1,
                        "PORTAL_USER_ID": 1,
                        "CALL_TYPE": 1,
                        "CALL_START_DATE": "2026-10-28T12:00:00+03:00",
                        "SECRET_FIELD": "must not escape",
                    }
                ]
            }
        )
        rows = gateway.source("calls", {"bitrix_id": 1}, "2026-10-28")
        self.assertEqual(rows, [{"id": "1", "title": ""}])
        self.assertNotIn("SECRET", json.dumps(rows))

    def test_observations_never_overwrite_saved_manual_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStore(Path(tmp) / "planner.db")
            store.initialize()
            migrate_server(store)
            actor = store.actor(8306778724)
            plan = store.create_plan(actor, "2026-10-28")
            observation = {
                "key": "calls",
                "name": "Calls",
                "status": "verified",
                "updated_at": __import__("time").time(),
                "items": [{"id": "1"}],
                "projection": {"calls.actual": 7},
            }
            save_observation(store, actor, plan["id"], "calls", observation, {"calls"})
            data = store.daily_get(actor, plan["id"])
            self.assertEqual(data["indicators"][0]["actual"], 7)
            body = {
                "revision": 0,
                "contracts": 0,
                "indicators": [
                    {
                        k: r[k]
                        for k in ("key", "planned", "actual", "morning", "details")
                    }
                    for r in data["indicators"]
                ],
            }
            body["indicators"][0]["actual"] = 11
            store.daily_save(actor, plan["id"], body)
            observation["projection"]["calls.actual"] = 100
            save_observation(store, actor, plan["id"], "calls", observation, {"calls"})
            self.assertEqual(
                store.daily_get(actor, plan["id"])["indicators"][0]["actual"], 11
            )
            save_observation(
                store,
                actor,
                plan["id"],
                "calls",
                {
                    "status": "unavailable",
                    "updated_at": 0,
                    "projection": {},
                    "items": None,
                },
                set(),
            )
            self.assertEqual(
                store.daily_get(actor, plan["id"])["indicators"][0]["actual"], 11
            )

    def test_migration_idempotence_and_old_report_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStore(Path(tmp) / "planner.db")
            store.initialize()
            actor = store.actor(8306778724)
            plan = store.create_plan(actor, "2026-10-20")
            report = store.close_plan(actor, plan["id"])
            migrate_server(store)
            migrate_server(store)
            self.assertEqual(store.report(actor, plan["id"]), report)
            with store.connection() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)

    def test_online_copy_keeps_source_and_checks_preservation(self):
        import hashlib

        from planner.migration_copy import prepare_copy

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = DailyStore(root / "source.db")
            store.initialize()
            actor = store.actor(8306778724)
            store.create_plan(actor, "2026-10-20")
            before = hashlib.sha256(store.path.read_bytes()).hexdigest()
            result = prepare_copy(store.path, root / "copy.db")
            self.assertEqual(result["integrity"], "ok")
            self.assertEqual(
                hashlib.sha256(store.path.read_bytes()).hexdigest(), before
            )
            with self.assertRaises(ValueError):
                prepare_copy(store.path, root / "copy.db")

    def test_compatible_core_store_close_keeps_new_daily_report(self):
        from planner.store import Store

        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStore(Path(tmp) / "planner.db")
            store.initialize()
            migrate_server(store)
            actor = store.actor(8306778724)
            plan = store.create_plan(actor, "2026-10-20")
            data = store.daily_get(actor, plan["id"])
            body = {
                "revision": 0,
                "contracts": 0,
                "indicators": [
                    {
                        k: r[k]
                        for k in ("key", "planned", "actual", "morning", "details")
                    }
                    for r in data["indicators"]
                ],
            }
            body["indicators"][0]["actual"] = 18
            store.daily_save(actor, plan["id"], body)
            legacy = Store(store.path)
            report = legacy.close_plan(actor, plan["id"])
            self.assertEqual(report["daily"]["indicators"][0]["actual"], 18)
            self.assertEqual(legacy.report(actor, plan["id"]), report)

    def test_server_extension_ddl_failure_rolls_back_then_retries(self):
        import sqlite3
        from contextlib import contextmanager

        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStore(Path(tmp) / "planner.db")
            store.initialize()

            class Failing(DailyStore):
                @contextmanager
                def connection(self, write=False):
                    with super().connection(write) as db:
                        db.set_authorizer(
                            lambda action, name, *rest: (
                                sqlite3.SQLITE_DENY
                                if action == sqlite3.SQLITE_CREATE_TABLE
                                and name == "crm_observations"
                                else sqlite3.SQLITE_OK
                            )
                        )
                        yield db

            with self.assertRaises(sqlite3.DatabaseError):
                migrate_server(Failing(store.path))
            with store.connection() as db:
                self.assertIsNone(
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='daily_records'"
                    ).fetchone()
                )
            migrate_server(store)
            migrate_server(store)

    def test_auto_seed_is_frozen_before_approval_and_close(self):
        import time

        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStore(Path(tmp) / "planner.db")
            store.initialize()
            migrate_server(store)
            actor = store.actor(8306778724)
            plan = store.create_plan(actor, "2026-10-20")
            observation = {
                "key": "calls",
                "status": "verified",
                "items": [],
                "projection": {"calls.actual": 7},
                "updated_at": time.time(),
            }
            save_observation(store, actor, plan["id"], "calls", observation, {"calls"})
            self.assertEqual(
                store.daily_get(actor, plan["id"])["indicators"][0]["actual"], 7
            )
            confirmed = store.confirm_plan(actor, plan["id"])
            self.assertEqual(confirmed["daily"]["indicators"][0]["actual"], 7)
            observation["projection"]["calls.actual"] = 100
            save_observation(store, actor, plan["id"], "calls", observation, {"calls"})
            self.assertEqual(
                store.close_plan(actor, plan["id"])["daily"]["indicators"][0]["actual"],
                7,
            )


if __name__ == "__main__":
    unittest.main()
