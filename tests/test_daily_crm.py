import unittest

import httpx
from planner.daily_crm import HOT_STAGES, ReadOnlyCRM, SourceUnavailable


class CRMReadTests(unittest.TestCase):
    def gateway(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return ReadOnlyCRM("https://synthetic.invalid/rest/test", client)

    def test_write_method_rejected_without_request(self):
        calls = []
        g = self.gateway(lambda r: calls.append(r))
        with self.assertRaises(SourceUnavailable):
            g.pages("crm.lead.update", {}, None)
        self.assertEqual(calls, [])

    def test_pagination_dedup_and_bad_cursor(self):
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={"result": {"items": [{"id": 1}, {"id": 2}]}, "next": 50}
                if len(calls) == 1
                else {"result": {"items": [{"id": 2}, {"id": 3}]}},
            )

        self.assertEqual(
            len(self.gateway(handle).pages("crm.item.list", {}, "items")), 3
        )
        bad = self.gateway(
            lambda r: httpx.Response(
                200, json={"result": {"items": [{"id": 1}]}, "next": 0}
            )
        )
        with self.assertRaises(SourceUnavailable):
            bad.pages("crm.item.list", {}, "items")

    def test_error_is_safe_not_zero(self):
        g = self.gateway(
            lambda r: httpx.Response(200, json={"error": "secret error detail"})
        )
        with self.assertRaises(SourceUnavailable) as e:
            g.source("calls", {"bitrix_id": 1}, "2026-10-28")
        self.assertNotIn("secret", str(e.exception))

    def test_wrong_owner_and_hot_category_rejected(self):
        g = self.gateway(
            lambda r: httpx.Response(
                200,
                json={
                    "result": {
                        "items": [
                            {
                                "id": 1,
                                "assignedById": 2,
                                "categoryId": 2,
                                "stageId": HOT_STAGES[0],
                            }
                        ]
                    }
                },
            )
        )
        with self.assertRaises(SourceUnavailable):
            g.source("deals", {"bitrix_id": 1}, "2026-10-28")


if __name__ == "__main__":
    unittest.main()
