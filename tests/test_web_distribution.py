import asyncio
import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from bitrix import Lead
from planner.daily import DailyStore, initialize_daily
from planner.distribution_queue import MOSCOW, DistributionQueue
from planner.store import DomainError
from planner.sync import sync_once
from planner.web_distribution import WebDistribution, initialize_previews


class CRM:
    fail = False
    changed = False

    async def get_leads(self, first, last, stage_ids=None):
        if self.fail:
            raise RuntimeError("unavailable")
        count = (first.toordinal() % 3 + 1) + (1 if self.changed else 0)
        return [
            Lead(
                first.toordinal() * 100 + i,
                datetime(first.year, first.month, first.day, 12, tzinfo=MOSCOW),
                "IN_PROCESS",
            )
            for i in range(count)
        ]

    async def counts_for_dates(self, dates, stage_ids=None):
        return {d: len(await self.get_leads(d, d, stage_ids)) for d in dates}

    async def find_previous_nonempty(self, before, excluded=(), stage_ids=None):
        d = before - timedelta(days=1)
        while d in excluded:
            d -= timedelta(days=1)
        return d, len(await self.get_leads(d, d, stage_ids))


class DistributionWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DailyStore(Path(self.temp.name) / "planner.db")
        self.store.initialize()
        initialize_daily(self.store)
        initialize_previews(self.store)
        self.queue = DistributionQueue(Path(self.temp.name) / "queue.db")
        self.queue.initialize()
        self.crm = CRM()
        self.authorized = {8306778724}
        self.service = WebDistribution(
            self.store, self.queue, self.crm, self.authorized
        )
        with self.store.connection() as db:
            self.a, self.b, self.boss = [
                dict(r) for r in db.execute("SELECT * FROM employees ORDER BY id")
            ]

    def calculate(self, managers=None, stages=None):
        return asyncio.run(
            self.service.calculate(
                self.a, managers or [1, 2], 3, stages or ["IN_PROCESS"]
            )
        )

    def confirm(self, p, index=0):
        return asyncio.run(self.service.confirm(self.a, p["id"], index))

    def test_confirm_selected_variant_import_retry_restart(self):
        p = self.calculate()
        self.assertEqual(list(self.queue.read()), [])
        index = len(p["variants"]) - 1
        saved = self.confirm(p, index)
        self.assertEqual(saved["variant_index"], index)
        self.assertEqual(saved, self.confirm(p, index))
        restarted = WebDistribution(self.store, self.queue, self.crm, self.authorized)
        self.assertEqual(saved, asyncio.run(restarted.confirm(self.a, p["id"], index)))
        sync_once(self.store, self.queue.path, self.authorized)
        sync_once(self.store, self.queue.path, self.authorized)
        for actor in (self.a, self.b):
            plans = self.store.list_plans(actor, actor["id"], saved["workday"])
            self.assertEqual(len(plans), 1)
            plan = self.store.get_plan(actor, plans[0]["id"])
            self.assertEqual(len(plan["tasks"]), 1)
            allocation = next(
                x
                for x in saved["allocations"]
                if x["telegram_id"] == actor["telegram_id"]
            )
            self.assertEqual(plan["tasks"][0]["target"], allocation["count"])

    def test_other_variant_same_day_refused(self):
        p = self.calculate()
        self.confirm(p)
        other = self.calculate()
        with self.assertRaises(DomainError):
            self.confirm(other)
        self.assertEqual(len(list(self.queue.read())), 1)

    def test_permissions_not_all_managers_or_supervisor(self):
        p = self.calculate()
        for actor in (self.b, self.boss):
            with self.assertRaises(DomainError):
                asyncio.run(self.service.confirm(actor, p["id"], 0))
        self.assertEqual(list(self.queue.read()), [])

    def test_changed_data_and_network_do_not_publish(self):
        p = self.calculate()
        self.crm.changed = True
        with self.assertRaises(DomainError):
            self.confirm(p)
        self.crm.changed = False
        self.crm.fail = True
        with self.assertRaises(RuntimeError):
            self.confirm(p)
        self.assertEqual(list(self.queue.read()), [])

    def test_inactive_manager_no_partial_confirmation(self):
        p = self.calculate()
        with self.store.connection(True) as db:
            db.execute("UPDATE employees SET active=0 WHERE id=2")
        with self.assertRaises(DomainError):
            self.confirm(p)
        self.assertEqual(list(self.queue.read()), [])

    def test_multiple_stages_can_calculate_but_not_confirm(self):
        p = self.calculate(stages=["IN_PROCESS", "NEW"])
        with self.assertRaises(DomainError):
            self.confirm(p)

    def test_stale_unknown_and_invalid_variant(self):
        p = self.calculate()
        with self.assertRaises(DomainError):
            self.confirm(p, 99)
        with self.assertRaises(DomainError):
            asyncio.run(self.service.confirm(self.a, str(uuid4()), 0))
        with self.store.connection(True) as db:
            db.execute("UPDATE web_distribution_previews SET created_at=0")
        with self.assertRaises(DomainError):
            self.confirm(p)

    def test_one_manager_and_empty_dates_replacement(self):
        p = self.calculate([1])
        self.assertEqual(len(p["variants"][0]), 1)
        before = p["dates"][0]["day"]
        previous = asyncio.run(
            self.service.previous(
                self.a, before, [d["day"] for d in p["dates"]], ["IN_PROCESS"]
            )
        )
        self.assertLess(previous["day"], before)
        dates = [previous["day"]] + [d["day"] for d in p["dates"][1:]]
        updated = asyncio.run(
            self.service.calculate(self.a, [1], 3, ["IN_PROCESS"], dates)
        )
        self.assertEqual(updated["dates"][0]["day"], previous["day"])

    def test_simultaneous_web_confirm_reuses_original(self):
        p = self.calculate()
        with ThreadPoolExecutor(2) as pool:
            result = list(pool.map(lambda _: self.confirm(p), range(2)))
        self.assertEqual(result[0], result[1])
        self.assertEqual(len(list(self.queue.read())), 1)

    def test_telegram_queue_publish_and_web_share_slot(self):
        p = self.calculate()
        saved = self.confirm(p)
        telegram = copy.deepcopy(saved)
        telegram["distribution_id"] = str(uuid4())
        telegram["variant_id"] = telegram["distribution_id"]
        with self.assertRaises(ValueError):
            self.queue.publish(telegram, self.authorized)
        self.assertEqual(len(list(self.queue.read())), 1)

    def test_simultaneous_telegram_writer_and_web_have_one_winner(self):
        # Build a valid Telegram protocol fixture in a SEPARATE temporary queue.
        p = self.calculate()
        telegram = self.confirm(p)
        telegram = copy.deepcopy(telegram)
        telegram["distribution_id"] = str(uuid4())
        telegram["variant_id"] = telegram["distribution_id"]
        shared = DistributionQueue(Path(self.temp.name) / "shared.db")
        shared.initialize()
        service = WebDistribution(self.store, shared, self.crm, self.authorized)

        def telegram_write():
            try:
                shared.publish(telegram, self.authorized)
                return "won"
            except ValueError:
                return "conflict"

        def web_write():
            try:
                asyncio.run(service.confirm(self.a, p["id"], 0))
                return "won"
            except DomainError:
                return "conflict"

        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(telegram_write)
            b = pool.submit(web_write)
            results = [a.result(), b.result()]
        self.assertEqual(sorted(results), ["conflict", "won"])
        self.assertEqual(len(list(shared.read())), 1)

    def test_missed_call_and_message_required_and_repeat_dedup(self):
        saved = self.confirm(self.calculate())
        sync_once(self.store, self.queue.path, self.authorized)
        plan = self.store.list_plans(self.a, 1, saved["workday"])[0]
        daily = self.store.daily_get(self.a, plan["id"])
        body = {
            "revision": daily["revision"],
            "contracts": 0,
            "indicators": [
                {k: r[k] for k in ("key", "planned", "actual", "morning", "details")}
                for r in daily["indicators"]
            ],
        }
        missed = next(x for x in body["indicators"] if x["key"] == "missed")
        for d in missed["details"]:
            d.pop("created_date", None)
        first = missed["details"][0]
        first["attempts"] = [
            {"id": "a", "time": "10:00", "call": True, "message": False}
        ]
        data = self.store.daily_save(self.a, plan["id"], body)
        self.assertEqual(
            next(x for x in data["indicators"] if x["key"] == "missed")["actual"], 0
        )
        body["revision"] = data["revision"]
        first["attempts"].append(
            {
                "id": "b",
                "time": "15:00",
                "call": True,
                "message": True,
                "connected": True,
            }
        )
        data = self.store.daily_save(self.a, plan["id"], body)
        self.assertEqual(
            next(x for x in data["indicators"] if x["key"] == "missed")["actual"], 1
        )

    def test_confirmed_plan_review_and_manager_history_privacy(self):
        day = datetime.now(MOSCOW).date().isoformat()
        plan = self.store.create_plan(self.a, day)
        self.store.confirm_plan(self.a, plan["id"])
        self.confirm(self.calculate())
        sync_once(self.store, self.queue.path, self.authorized)
        self.assertEqual(self.store.get_plan(self.a, plan["id"])["tasks"], [])
        history = self.service.history(self.a)
        self.assertEqual(history[0]["status"], "review")
        self.assertEqual(len(history[0]["allocations"]), 1)
        self.assertEqual(
            history[0]["allocations"][0]["telegram_id"], self.a["telegram_id"]
        )


if __name__ == "__main__":
    unittest.main()
