import json
import unittest
from datetime import date
from zoneinfo import ZoneInfo

import httpx

from bitrix import BitrixClient, BitrixError


def item(number, created="2026-09-20T12:00:00+03:00", stage="MISSED"):
    return {"id": number, "createdTime": created, "stageId": stage}


class BitrixTests(unittest.IsolatedAsyncioTestCase):
    async def run_client(self, handler, operation):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = BitrixClient("https://example.invalid/rest/1/synthetic_test_key/", "MISSED",
                                   ZoneInfo("Europe/Moscow"), http)
            return await operation(client)

    async def test_pagination_and_date_boundaries(self):
        requests = []

        def respond(request):
            data = json.loads(request.content)
            requests.append(data)
            self.assertTrue(request.url.path.endswith("/crm.item.list.json"))
            self.assertEqual(data["entityTypeId"], 1)
            self.assertEqual(data["filter"]["=stageId"], "MISSED")
            self.assertEqual(data["filter"][">=createdTime"], "2026-09-19T00:00:00+03:00")
            self.assertEqual(data["filter"]["<createdTime"], "2026-09-21T00:00:00+03:00")
            if data["start"] == 0:
                return httpx.Response(200, json={"result": {"items": [item(i) for i in range(1, 51)]}, "next": 50})
            return httpx.Response(200, json={"result": {"items": [item(51, "2026-09-19T22:00:00Z"), item(52, "2026-09-19T10:00:00Z")]}})

        counts = await self.run_client(respond, lambda c: c.counts_for_dates([date(2026, 9, 19), date(2026, 9, 20)]))
        self.assertEqual(counts, {date(2026, 9, 19): 1, date(2026, 9, 20): 51})
        self.assertEqual(len(requests), 2)

    async def test_noncontiguous_dates_and_empty_input(self):
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"result": {"items": []}})

        async def operation(client):
            self.assertEqual(await client.counts_for_dates([]), {})
            return await client.counts_for_dates([date(2026, 9, 1), date(2026, 9, 2), date(2020, 1, 1)])

        counts = await self.run_client(respond, operation)
        self.assertEqual(len(requests), 2)
        self.assertEqual(sum(counts.values()), 0)

    async def test_previous_skips_empty_history_and_duplicates(self):
        calls = []

        def respond(request):
            payload = json.loads(request.content)
            calls.append(payload)
            filters = payload["filter"]
            if ">=createdTime" not in filters and filters["<createdTime"].startswith("2026-09-18"):
                records = [item(1, "2026-09-15T12:00:00+03:00")]
            else:
                records = [item(2, "2026-09-10T12:00:00+03:00")]
            return httpx.Response(200, json={"result": {"items": records}})

        found = await self.run_client(respond, lambda c: c.find_previous_nonempty(date(2026, 9, 18), [date(2026, 9, 15)]))
        self.assertEqual(found, (date(2026, 9, 10), 1))
        self.assertEqual(len(calls), 3)

    async def test_no_previous(self):
        found = await self.run_client(lambda r: httpx.Response(200, json={"result": {"items": []}}),
                                      lambda c: c.find_previous_nonempty(date(2026, 9, 18)))
        self.assertIsNone(found)

    async def test_errors_and_invalid_shapes(self):
        responses = [
            httpx.Response(401), httpx.Response(429), httpx.Response(500), httpx.Response(302),
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"error": "INVALID_CREDENTIALS", "error_description": "synthetic_test_key"}),
            httpx.Response(200, json=[]), httpx.Response(200, json={"result": []}),
            httpx.Response(200, json={"result": {"items": "wrong"}}),
            httpx.Response(200, json={"result": {"items": [item(1)]}, "next": 0}),
            httpx.Response(200, json={"result": {"items": [item(1)]}, "next": "50"}),
            httpx.Response(200, json={"result": {"items": []}, "next": 50}),
            httpx.Response(200, json={"result": {"items": [item(1, "2026-09-20T12:00:00")]}}),
            httpx.Response(200, json={"result": {"items": [item(1, "2026-09-21T00:00:00+03:00")]}}),
        ]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(BitrixError) as caught:
                await self.run_client(lambda r: response, lambda c: c.count_for_date(date(2026, 9, 20)))
            self.assertNotIn("synthetic_test_key", str(caught.exception))

    async def test_timeout_and_network_error(self):
        for kind in (httpx.ReadTimeout, httpx.ConnectError):
            def respond(request):
                raise kind("https://example.invalid/rest/1/synthetic_test_key/", request=request)
            with self.assertLogs("bitrix", level="WARNING") as logs, self.assertRaises(BitrixError):
                await self.run_client(respond, lambda c: c.count_for_date(date(2026, 9, 20)))
            self.assertNotIn("synthetic_test_key", " ".join(logs.output))

    async def test_repeated_pages_fail(self):
        def respond(request):
            start = json.loads(request.content)["start"]
            return httpx.Response(200, json={"result": {"items": [item(1)]}, "next": start + 50})
        with self.assertRaises(BitrixError):
            await self.run_client(respond, lambda c: c.count_for_date(date(2026, 9, 20)))

    async def test_multiple_stages_are_one_union_query_across_pages(self):
        calls = []

        def respond(request):
            data = json.loads(request.content)
            calls.append(data)
            self.assertEqual(data["filter"]["@stageId"], ["MISSED", "PROCESSED", "NEW"])
            self.assertNotIn("=stageId", data["filter"])
            if data["start"] == 0:
                return httpx.Response(200, json={"result": {"items": [item(1)]}, "next": 50})
            return httpx.Response(200, json={"result": {"items": [item(1), item(2)]}})

        count = await self.run_client(respond, lambda c: c.count_for_date(
            date(2026, 9, 20), ["MISSED", "PROCESSED", "NEW", "NEW"]))
        self.assertEqual(count, 2)
        self.assertEqual(len(calls), 2)

    async def test_single_alternate_stage_in_previous_search_and_count(self):
        calls = []

        def respond(request):
            data = json.loads(request.content)
            calls.append(data)
            self.assertEqual(data["filter"]["=stageId"], "NEW")
            return httpx.Response(200, json={"result": {"items": [item(1, stage="NEW")]}})

        result = await self.run_client(respond, lambda c: c.find_previous_nonempty(
            date(2026, 9, 21), stage_ids=["NEW"]))
        self.assertEqual(result, (date(2026, 9, 20), 1))
        self.assertEqual(len(calls), 2)

    async def test_stage_breakdown_pages_duplicates_timezone_and_zeros(self):
        def respond(request):
            data = json.loads(request.content)
            self.assertIn("stageId", data["select"])
            if data["start"] == 0:
                return httpx.Response(200, json={"result": {"items": [
                    item(1), item(2, "2026-09-19T22:00:00Z", "NEW")
                ]}, "next": 50})
            return httpx.Response(200, json={"result": {"items": [
                item(2, "2026-09-19T22:00:00Z", "NEW"), item(3, stage="NEW")
            ]}})

        counts = await self.run_client(respond, lambda c: c.counts_by_stage_for_dates(
            [date(2026, 9, 19), date(2026, 9, 20)], ["MISSED", "PROCESSED", "NEW"]))
        self.assertEqual(counts, {
            date(2026, 9, 19): {"MISSED": 0, "PROCESSED": 0, "NEW": 0},
            date(2026, 9, 20): {"MISSED": 1, "PROCESSED": 0, "NEW": 2},
        })

    async def test_invalid_or_unselected_stage_is_not_reported_as_zero(self):
        for stage in (None, "", 42, "UNKNOWN"):
            with self.subTest(stage=stage), self.assertRaises(BitrixError):
                await self.run_client(
                    lambda r: httpx.Response(200, json={"result": {"items": [item(1, stage=stage)]}}),
                    lambda c: c.counts_by_stage_for_dates([date(2026, 9, 20)]))

    async def test_previous_day_retains_breakdown(self):
        counts = await self.run_client(
            lambda r: httpx.Response(200, json={"result": {"items": [item(1), item(2, stage="NEW")]}}),
            lambda c: c.find_previous_nonempty_by_stage(date(2026, 9, 21), stage_ids=["MISSED", "NEW"]))
        self.assertEqual(counts, (date(2026, 9, 20), {"MISSED": 1, "NEW": 1}))
