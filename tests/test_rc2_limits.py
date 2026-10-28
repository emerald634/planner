import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from planner.daily import DailyStore
from planner.daily_crm import ReadOnlyCRM, SourceUnavailable
from planner.server_migration import migrate_server


class RC2LimitsTests(unittest.TestCase):
    def test_page_ceiling_with_small_responses(self):
        calls = []

        def handle(request):
            start = json.loads(request.content)["start"]
            calls.append(start)
            return httpx.Response(
                200, json={"result": {"items": [{"id": start + 1}]}, "next": start + 1}
            )

        with self.assertRaises(SourceUnavailable):
            self.gateway(handle).pages("crm.item.list", {}, "items")
        self.assertEqual(len(calls), 200)

    def gateway(self, callback):
        client = httpx.Client(transport=httpx.MockTransport(callback))
        self.addCleanup(client.close)
        return ReadOnlyCRM("https://synthetic.invalid", client)

    def test_aggregate_bytes_across_small_pages_rejected(self):
        calls = []

        def handle(request):
            start = json.loads(request.content)["start"]
            calls.append(start)
            return httpx.Response(
                200,
                json={
                    "result": {"items": [{"id": start + 1, "unused": "x" * 1200}]},
                    "next": start + 1,
                },
            )

        gateway = self.gateway(handle)
        with (
            patch("planner.daily_crm.MAX_SOURCE_BYTES", 3000),
            self.assertRaises(SourceUnavailable),
        ):
            gateway.pages("crm.item.list", {}, "items")
        self.assertEqual(len(calls), 3)

    def test_many_pages_dedup_and_only_safe_fields(self):
        def handle(request):
            start = json.loads(request.content)["start"]
            rows = [
                {"id": i, "title": "synthetic", "unused": "sensitive" * 50}
                for i in range(start + 1, start + 101)
            ]
            body = {"result": {"items": rows + rows}}
            if start < 1900:
                body["next"] = start + 100
            return httpx.Response(200, json=body)

        rows = self.gateway(handle).pages("crm.item.list", {}, "items")
        self.assertEqual(len(rows), 2000)
        self.assertTrue(all(set(row) == {"id", "title"} for row in rows))
        self.assertLess(len(json.dumps(rows)), 100000)

    def test_conflict_in_discarded_field_still_refused(self):
        def handle(request):
            start = json.loads(request.content)["start"]
            return httpx.Response(
                200,
                json={
                    "result": {"items": [{"id": 1, "unused": start}]},
                    **({"next": 1} if start == 0 else {}),
                },
            )

        with self.assertRaises(SourceUnavailable):
            self.gateway(handle).pages("crm.item.list", {}, "items")

    def test_wrong_owner_after_many_valid_rows_refuses_entire_source(self):
        rows = [
            {"id": i, "assignedById": 460, "createdTime": "2026-10-28T10:00:00+03:00"}
            for i in range(1, 101)
        ]
        rows[-1]["assignedById"] = 110
        with self.assertRaises(SourceUnavailable):
            self.gateway(
                lambda r: httpx.Response(200, json={"result": {"items": rows}})
            ).source("leads", {"bitrix_id": 460}, "2026-10-28")

    def test_large_pages_stop_before_third_full_payload(self):
        calls = []

        def handle(request):
            start = json.loads(request.content)["start"]
            calls.append(start)
            return httpx.Response(
                200,
                json={
                    "result": {"items": [{"id": start + 1, "unused": "x" * 1_500_000}]},
                    "next": start + 1,
                },
            )

        with (
            patch("planner.daily_crm.MAX_SOURCE_BYTES", 2_500_000),
            self.assertRaises(SourceUnavailable),
        ):
            self.gateway(handle).pages("crm.item.list", {}, "items")
        self.assertEqual(len(calls), 2)

    def test_closed_daily_reads_snapshot_not_mutable_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStore(Path(tmp) / "planner.db")
            store.initialize()
            migrate_server(store)
            actor = store.actor(8306778724)
            plan = store.create_plan(actor, "2026-10-28")
            report = store.close_plan(actor, plan["id"])
            with patch.object(
                store, "daily_detail", side_effect=AssertionError("Mutable path")
            ):
                self.assertEqual(store.daily_get(actor, plan["id"]), report["daily"])
            self.assertEqual(store.report(actor, plan["id"]), report)
