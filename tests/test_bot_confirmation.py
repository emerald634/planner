import asyncio
import sqlite3
import unittest
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch

from tests import test_bot as baseline
from bitrix import Lead, BitrixError
from bot import create_dispatcher
from planner.distribution_queue import DistributionQueue


class BotConfirmationTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = baseline.BotTests.asyncTearDown
    state = baseline.BotTests.state
    send = baseline.BotTests.send
    click = baseline.BotTests.click
    callback_update = baseline.BotTests.callback_update
    current_message = baseline.BotTests.current_message

    async def asyncSetUp(self):
        await baseline.BotTests.asyncSetUp(self)
        await self.dp.fsm.close()
        self.queue = DistributionQueue(Path(self.temp_dir.name) / "distribution.db")
        self.config = replace(self.config, missed_call_stage_id="IN_PROCESS",
            manager_names=("Вячеслав", "Яна", "Евгений"), manager_telegram_ids=(8306778724, 7939114214, 0),
            distribution_queue_path=self.queue.path, distribution_confirmer_ids=frozenset({123}),
            planner_active_manager_ids=frozenset({8306778724, 7939114214}))
        self.dp = create_dispatcher(self.config, self.bitrix, self.access)
        async def leads(first, last, stage_ids=None):
            return [Lead(first.toordinal() * 100 + i, datetime.combine(first, time(12), self.config.timezone), "IN_PROCESS") for i in range(10)]
        self.bitrix.get_leads.side_effect = leads

    async def result(self, include_inactive=False, user=123):
        await self.send("/start", user=user)
        await self.click("new", user=user)
        if not include_inactive:
            await self.click("manager:2", user=user)
        await self.click("continue", user=user)
        await self.click("stages_done", user=user)
        await self.click("period:3", user=user)

    def rows(self):
        return list(self.queue.read()) if self.queue.path.exists() else []

    async def test_selected_variant_only_and_repeated_callback(self):
        await self.result()
        await self.click("next")
        self.assertEqual(self.rows(), [])
        data = await self.state().get_data()
        update = await self.callback_update("confirm_distribution")
        await self.dp.feed_update(self.bot, update)
        row = self.rows()[0]
        self.assertEqual(row["variant_index"], data["variant_index"])
        self.assertEqual(row["total"], 30)
        expected = data["variants"][data["variant_index"]]
        self.assertEqual([a["dates"] for a in row["allocations"]], [[d.isoformat() for d, _ in a.days] for a in expected.allocations])
        self.assertEqual({a["telegram_id"] for a in row["allocations"]}, {8306778724, 7939114214})
        calls = self.bitrix.get_leads.await_count
        await self.dp.feed_update(self.bot, update)
        self.assertEqual(self.bitrix.get_leads.await_count, calls)
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("уже подтверждено", self.http.calls[-1].text)

    async def test_parallel_clicks_and_other_variant_one_day(self):
        await self.result()
        updates = [await self.callback_update("confirm_distribution") for _ in range(2)]
        await asyncio.gather(*(self.dp.feed_update(self.bot, u) for u in updates))
        self.assertEqual(len(self.rows()), 1)
        await self.click("next")
        await self.click("confirm_distribution")
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("уже подтверждено другое", self.http.calls[-1].text)

    async def test_permissions_button_hidden_and_forged_callback_denied(self):
        await self.result(user=456)
        data = await self.state(456).get_data()
        message = self.http.messages[(456, data["message_id"])]
        self.assertFalse(any("confirm_distribution" in b.callback_data for row in message.reply_markup.inline_keyboard for b in row))
        await self.click("confirm_distribution", user=456)
        self.assertEqual(self.rows(), [])
        self.assertIn("Нет права", self.http.calls[-1].text)

    async def test_stale_button_and_foreign_menu(self):
        await self.result()
        old = await self.callback_update("confirm_distribution")
        await self.click("next")
        await self.dp.feed_update(self.bot, old)
        self.assertEqual(self.rows(), [])
        self.assertIn("устарела", self.http.calls[-1].text)

    async def test_inactive_selection_creates_no_partial_distribution(self):
        await self.result(include_inactive=True)
        await self.click("confirm_distribution")
        self.assertEqual(self.rows(), [])
        self.bitrix.get_leads.assert_not_awaited()
        self.assertIn("без активной привязки", self.http.calls[-1].text)

    async def test_changed_counts_and_bitrix_failure_then_retry(self):
        await self.result()
        original = self.bitrix.get_leads.side_effect
        self.bitrix.get_leads.side_effect = BitrixError()
        await self.click("confirm_distribution")
        self.assertEqual(self.rows(), [])
        self.assertIn("Bitrix24 недоступен", self.http.calls[-1].text)
        async def fewer(*args, **kwargs):
            return (await original(*args, **kwargs))[:-1]
        self.bitrix.get_leads.side_effect = fewer
        await self.click("confirm_distribution")
        self.assertEqual(self.rows(), [])
        self.bitrix.get_leads.side_effect = original
        await self.click("confirm_distribution")
        self.assertEqual(len(self.rows()), 1)

    async def test_duplicate_leads_with_unchanged_count_rejected(self):
        await self.result()
        original = self.bitrix.get_leads.side_effect
        async def duplicate(*args, **kwargs):
            rows = await original(*args, **kwargs)
            rows[-1] = rows[0]
            return rows
        self.bitrix.get_leads.side_effect = duplicate
        await self.click("confirm_distribution")
        self.assertEqual(self.rows(), [])

    async def test_queue_failure_retry_and_committed_ack_failure(self):
        await self.result()
        with patch.object(DistributionQueue, "publish", side_effect=sqlite3.OperationalError()):
            await self.click("confirm_distribution")
        self.assertEqual(self.rows(), [])
        self.assertIn("очередь", self.http.calls[-1].text)
        real = DistributionQueue.publish
        def commit_then_fail(queue, *args):
            real(queue, *args)
            raise sqlite3.OperationalError()
        with patch.object(DistributionQueue, "publish", commit_then_fail):
            await self.click("confirm_distribution")
        self.assertEqual(len(self.rows()), 1)
        await self.click("confirm_distribution")
        self.assertEqual(len(self.rows()), 1)

    async def test_other_and_mixed_stages_never_publish(self):
        await self.result()
        for stages in (("NEW",), ("IN_PROCESS", "NEW")):
            await self.state().update_data(stage_ids=stages)
            await self.click("confirm_distribution")
            self.assertEqual(self.rows(), [])

    async def test_writer_initializes_queue_on_start_without_crm_or_polling(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from bot import main
        configured = replace(self.config, access_db_path=self.access.path)
        dispatcher = SimpleNamespace(start_polling=AsyncMock(), resolve_used_update_types=lambda: [])
        with patch('bot.load_config', return_value=configured), patch('bot.Bot', return_value=self.bot), patch('bot.create_dispatcher', return_value=dispatcher), patch('bot.reminder_loop', new=AsyncMock()):
            await main()
        self.assertTrue(self.queue.path.exists())
        self.assertEqual(self.rows(), [])
