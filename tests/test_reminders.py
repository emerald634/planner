import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage

from access import AccessStore
from config import Config
from reminders import send_due_reminders


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.access = AccessStore(Path(self.directory.name) / "access.db")
        self.access.initialize([123, 456])
        self.config = Config("123456:synthetic_token", "https://example.invalid/rest/1/key/", "MISSED",
                             ("a", "b", "c"), frozenset({123, 456}), ZoneInfo("Europe/Moscow"),
                             admin_telegram_ids=frozenset({777}))
        self.bot = AsyncMock(spec=Bot)
        self.access.ensure_private_reminders([123, 456, 777])
        self.access.set_reminder(-100123, 10, 777, True)

    async def test_moscow_time_daily_claim_and_restart(self):
        await send_due_reminders(self.bot, self.access, self.config, datetime(2026, 9, 28, 6, 59, tzinfo=timezone.utc))
        self.bot.send_message.assert_not_awaited()
        now = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)
        await asyncio.gather(send_due_reminders(self.bot, self.access, self.config, now),
                             send_due_reminders(self.bot, self.access, self.config, now))
        self.assertEqual(self.bot.send_message.await_count, 4)
        calls = self.bot.send_message.call_args_list
        self.assertEqual({call.args[0] for call in calls}, {-100123, 123, 456, 777})
        group = next(call for call in calls if call.args[0] < 0)
        self.assertEqual(group.kwargs["message_thread_id"], 10)
        self.assertEqual(group.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "reminder:new")
        restarted = AccessStore(self.access.path)
        restarted.initialize()
        restarted.ensure_private_reminders([123, 456, 777])
        await send_due_reminders(self.bot, restarted, self.config, now)
        self.assertEqual(self.bot.send_message.await_count, 4)
        await send_due_reminders(self.bot, restarted, self.config, datetime(2026, 9, 29, 7, tzinfo=timezone.utc))
        self.assertEqual(self.bot.send_message.await_count, 8)

    async def test_revoked_user_and_opt_out_persist(self):
        self.access.remove_user(123)
        self.access.set_reminder(456, 0, 456, False)
        self.access.ensure_private_reminders([456])
        self.access.set_reminder(-100999, 0, 123, True)
        await send_due_reminders(self.bot, self.access, self.config, datetime(2026, 9, 28, 7, tzinfo=timezone.utc))
        self.assertEqual({call.args[0] for call in self.bot.send_message.call_args_list}, {777, -100123})

    async def test_late_start_does_not_send_afternoon_prompt(self):
        for hour, minute in ((6, 0), (7, 10), (8, 0), (15, 0)):
            await send_due_reminders(self.bot, self.access, self.config,
                                     datetime(2026, 9, 28, hour, minute, tzinfo=timezone.utc))
        self.bot.send_message.assert_not_awaited()

    async def test_forbidden_and_network_failure_do_not_flood(self):
        self.bot.send_message.side_effect = TelegramForbiddenError(
            method=SendMessage(chat_id=123, text="test"), message="Forbidden")
        now = datetime(2026, 9, 28, 7, tzinfo=timezone.utc)
        await send_due_reminders(self.bot, self.access, self.config, now)
        self.assertNotIn((-100123, 10, 777), self.access.list_reminders())
        self.assertIn((123, 0, 123), self.access.list_reminders())
        self.assertEqual(self.bot.send_message.await_count, 4)
        await send_due_reminders(self.bot, self.access, self.config, now)
        self.assertEqual(self.bot.send_message.await_count, 4)
        self.bot.send_message.side_effect = TelegramNetworkError(
            method=SendMessage(chat_id=123, text="test"), message="synthetic secret")
        with self.assertLogs("reminders", level="WARNING") as logs:
            await send_due_reminders(self.bot, self.access, self.config, datetime(2026, 9, 29, 7, tzinfo=timezone.utc))
        self.assertNotIn("synthetic secret", " ".join(logs.output))

    async def test_toggle_does_not_reset_delivery_claim(self):
        self.assertTrue(self.access.claim_reminder(123, 0, "2026-09-28"))
        self.access.set_reminder(123, 0, 123, False)
        self.access.set_reminder(123, 0, 123, True)
        self.assertFalse(self.access.claim_reminder(123, 0, "2026-09-28"))
