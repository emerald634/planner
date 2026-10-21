import asyncio
import sqlite3
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetMe, SendMessage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, Update, User

from access import AccessStore
from bitrix import BitrixClient, BitrixError, USER_ERROR
from bot import ADMIN_ONLY, Flow, NO_ACCESS, NO_ALTERNATIVES, create_dispatcher, users_messages
from config import Config
from distribution import previous_days


class FakeTelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.messages = {}
        self.sequence = 100

    async def close(self):
        pass

    async def stream_content(self, url, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, GetMe):
            return User(id=bot.id, is_bot=True, first_name="Bot", username="test_bot")
        if not isinstance(method, (SendMessage, EditMessageText)):
            raise AssertionError(f"Unexpected Telegram method: {type(method).__name__}")
        self.sequence += 1
        message_id = method.message_id if isinstance(method, EditMessageText) else self.sequence
        message = Message(
            message_id=message_id, date=datetime.now(timezone.utc),
            chat=Chat(id=int(method.chat_id), type="supergroup" if int(method.chat_id) < 0 else "private"),
            from_user=User(id=bot.id, is_bot=True, first_name="Bot"),
            text=method.text,
            reply_markup=method.reply_markup if isinstance(method.reply_markup, InlineKeyboardMarkup) else None,
            message_thread_id=getattr(method, "message_thread_id", None),
            is_topic_message=bool(getattr(method, "message_thread_id", None)),
        )
        self.messages[(int(method.chat_id), message_id)] = message
        return message


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = Config("123456:synthetic_test_token", "https://example.invalid/rest/1/test_key/",
                             "MISSED", ("Иван", "Анна", "Сергей"), frozenset({123, 456}),
                             ZoneInfo("Europe/Moscow"), admin_telegram_ids=frozenset({777, 888}),
                             inconvenient_stage_id="PROCESSED", unprocessed_stage_id="NEW")
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.access = AccessStore(Path(self.temp_dir.name) / "test_access.db")
        await asyncio.to_thread(self.access.initialize, self.config.allowed_telegram_ids)
        self.http = FakeTelegramSession()
        self.bot = Bot(self.config.bot_token, session=self.http)
        self.bitrix = AsyncMock(spec=BitrixClient)
        self.days = previous_days(3, self.config.timezone)
        self.bitrix.counts_for_dates.return_value = dict.fromkeys(self.days, 10)
        self.dp = create_dispatcher(self.config, self.bitrix, self.access)
        self.sequence = 0

    async def asyncTearDown(self):
        await self.dp.fsm.close()
        await self.bot.session.close()

    def state(self, user=123, chat=None, thread=None):
        return self.dp.fsm.get_context(bot=self.bot, chat_id=chat or user, user_id=user, thread_id=thread)

    async def send(self, text, user=123, chat=None, thread=None, reply=None):
        self.sequence += 1
        message = Message(message_id=self.sequence, date=datetime.now(timezone.utc),
                          chat=Chat(id=chat or user, type="supergroup" if chat else "private"),
                          from_user=User(id=user, is_bot=False, first_name="User"), text=text,
                          message_thread_id=thread, is_topic_message=bool(thread), reply_to_message=reply)
        await self.dp.feed_update(self.bot, Update(update_id=self.sequence, message=message))

    async def callback_update(self, action, user=123, chat=None, thread=None):
        data = await self.state(user, chat, thread).get_data()
        message = self.http.messages[(chat or user, data["message_id"])]
        if thread:
            message = message.model_copy(update={"message_thread_id": thread, "is_topic_message": True})
        self.sequence += 1
        return Update(update_id=self.sequence, callback_query=CallbackQuery(
            id=str(self.sequence), from_user=User(id=user, is_bot=False, first_name="User"),
            chat_instance="test", message=message, data=f"{data['revision']}:{action}"))

    async def click(self, action, user=123, chat=None, thread=None):
        await self.dp.feed_update(self.bot, await self.callback_update(action, user, chat, thread))

    async def begin(self):
        await self.send("/start")
        await self.click("new")
        await self.click("continue")
        await self.click("stages_done")

    async def current_message(self):
        data = await self.state().get_data()
        return self.http.messages[(123, data["message_id"])]

    async def test_complete_flow_alternatives_and_reset(self):
        await self.begin()
        await self.click("period:3")
        self.assertEqual(await self.state().get_state(), Flow.result.state)
        first = (await self.current_message()).text
        self.assertIn("Всего недозвонов: 30", first)
        await self.click("next")
        self.assertNotEqual(first, (await self.current_message()).text)
        await self.click("next")
        self.assertEqual(self.http.calls[-1].text, NO_ALTERNATIVES)
        self.bitrix.counts_for_dates.assert_awaited_once()
        await self.click("new")
        data = await self.state().get_data()
        self.assertNotIn("variants", data)
        self.assertNotIn("counts", data)
        self.assertEqual(await self.state().get_state(), Flow.managers.state)

    async def test_planner_link_only_in_private_chat_and_keeps_flow(self):
        await self.send("/plan")
        self.assertIn("ещё не подключён", self.http.calls[-1].text)
        self.config = replace(self.config, mini_app_url="https://planner.example.com/")
        await self.dp.fsm.close()
        self.dp = create_dispatcher(self.config, self.bitrix, self.access)
        await self.begin()
        before = await self.state().get_state()
        await self.send("/plan")
        self.assertEqual(await self.state().get_state(), before)
        self.assertEqual(self.http.calls[-1].reply_markup.inline_keyboard[0][0].web_app.url, "https://planner.example.com/")
        await self.send("/start")
        self.assertIsNotNone((await self.current_message()).reply_markup.inline_keyboard[-1][0].web_app)
        await self.send("/start", chat=-100123)
        data = await self.state(chat=-100123).get_data()
        markup = self.http.messages[(-100123, data["message_id"])].reply_markup
        self.assertTrue(all(button.web_app is None for row in markup.inline_keyboard for button in row))
        await self.send("/plan", chat=-100123)
        self.assertIn("личный чат", self.http.calls[-1].text)

    async def test_manager_selection_and_empty_selection(self):
        await self.send("/start")
        await self.click("new")
        for i in range(3):
            await self.click(f"manager:{i}")
        await self.click("continue")
        self.assertIn("хотя бы одного", self.http.calls[-1].text)
        self.assertEqual(await self.state().get_state(), Flow.managers.state)
        await self.click("manager:1")
        await self.click("continue")
        await self.click("stages_done")
        await self.click("period:3")
        self.assertEqual(len((await self.state().get_data())["variants"]), 1)
        self.assertIn("👤 Анна", (await self.current_message()).text)

    async def test_empty_day_previous_replacement(self):
        self.bitrix.counts_for_dates.return_value = dict(zip(self.days, [10, 0, 20]))
        replacement = self.days[0] - timedelta(days=3)
        self.bitrix.find_previous_nonempty.return_value = (replacement, 15)
        await self.begin()
        await self.click("period:3")
        self.assertEqual(await self.state().get_state(), Flow.empty_days.state)
        self.assertIn(self.days[1].strftime("%d.%m.%Y"), (await self.current_message()).text)
        await self.click("previous")
        counts = (await self.state().get_data())["counts"]
        self.assertNotIn(self.days[1], counts)
        self.assertEqual(counts[replacement], 15)
        self.assertEqual(await self.state().get_state(), Flow.result.state)

    async def test_manual_rejects_invalid_duplicate_today_and_zero(self):
        self.bitrix.counts_for_dates.return_value = dict(zip(self.days, [10, 0, 20]))
        self.bitrix.count_for_date.side_effect = [0, 30]
        await self.begin()
        await self.click("period:3")
        await self.click("manual")
        for text in ["31.02", datetime.now(self.config.timezone).strftime("%d.%m.%Y"), self.days[0].strftime("%d.%m.%Y")]:
            await self.send(text)
        self.bitrix.count_for_date.assert_not_awaited()
        replacement = self.days[0] - timedelta(days=30)
        await self.send(replacement.strftime("%d.%m.%Y"))
        self.assertEqual(await self.state().get_state(), Flow.manual_date.state)
        await self.send((replacement - timedelta(days=1)).strftime("%d.%m.%Y"))
        self.assertEqual(await self.state().get_state(), Flow.result.state)
        self.assertEqual(sum((await self.state().get_data())["counts"].values()), 60)

    async def test_all_empty_and_continue_without_replacement(self):
        self.bitrix.counts_for_dates.return_value = dict.fromkeys(self.days, 0)
        self.bitrix.find_previous_nonempty.return_value = None
        await self.begin()
        await self.click("period:3")
        await self.click("previous")
        self.assertIn("не найдено", (await self.current_message()).text)
        await self.click("skip")
        self.assertIn("Нет непустых дат", (await self.current_message()).text)
        self.assertEqual((await self.state().get_data())["variants"], [])

    async def test_multiple_missing_days_and_skip_remaining(self):
        self.bitrix.counts_for_dates.return_value = dict(zip(self.days, [0, 0, 20]))
        self.bitrix.find_previous_nonempty.return_value = (self.days[0] - timedelta(days=1), 15)
        await self.begin()
        await self.click("period:3")
        await self.click("previous")
        self.assertEqual(await self.state().get_state(), Flow.empty_days.state)
        self.assertIn("Не хватает непустых дат: 1", (await self.current_message()).text)
        await self.click("skip")
        self.assertIn("Всего недозвонов: 35", (await self.current_message()).text)

    async def test_bitrix_failure_can_be_retried(self):
        self.bitrix.counts_for_dates.side_effect = [BitrixError(), dict.fromkeys(self.days, 10)]
        await self.begin()
        await self.click("period:3")
        self.assertIn(USER_ERROR, self.http.calls[-1].text)
        self.assertEqual(await self.state().get_state(), Flow.period.state)
        await self.click("period:3")
        self.assertEqual(await self.state().get_state(), Flow.result.state)

    async def test_access_for_messages_and_callbacks(self):
        await self.send("/start", user=999)
        self.assertEqual(self.http.calls[-1].text, NO_ACCESS)
        await self.send("/start")
        update = await self.callback_update("new")
        update = update.model_copy(update={"callback_query": update.callback_query.model_copy(update={
            "from_user": User(id=999, is_bot=False, first_name="Unauthorized"),
        })})
        await self.dp.feed_update(self.bot, update)
        self.assertEqual(self.http.calls[-1].text, NO_ACCESS)
        self.bitrix.counts_for_dates.assert_not_awaited()

    async def test_stale_concurrent_clicks_and_session_isolation(self):
        await self.begin()
        update = await self.callback_update("period:3")
        await asyncio.gather(self.dp.feed_update(self.bot, update), self.dp.feed_update(self.bot, update))
        self.bitrix.counts_for_dates.assert_awaited_once()
        self.assertIn("устарела", self.http.calls[-1].text)
        await self.send("/start", user=456)
        await self.click("new", user=456)
        self.assertEqual(await self.state(456).get_state(), Flow.managers.state)
        self.assertEqual(await self.state(123).get_state(), Flow.result.state)

    async def test_admin_has_access_without_database_row(self):
        self.assertFalse(self.access.contains(777))
        await self.send("/start", user=777)
        await self.click("new", user=777)
        await self.click("continue", user=777)
        await self.click("stages_done", user=777)
        await self.click("period:3", user=777)
        self.assertEqual(await self.state(777).get_state(), Flow.result.state)

    async def test_admin_commands_are_denied_for_every_non_admin(self):
        for user in (123, 999):
            for command in ("/adduser 555", "/removeuser 456", "/users", "/adduser@test_bot 555"):
                with self.subTest(user=user, command=command):
                    await self.send(command, user=user)
                    self.assertEqual(self.http.calls[-1].text, ADMIN_ONLY)
        self.assertEqual(self.access.list_users(), [123, 456])

    async def test_add_remove_commands_take_effect_without_restart(self):
        with self.assertLogs("bot", level="INFO") as logs:
            await self.send("/adduser 555", user=777)
            self.assertEqual(self.http.calls[-1].text, "✅ Доступ добавлен.\n\nTelegram ID: 555")
            await self.send("/adduser 555", user=777)
            self.assertEqual(self.http.calls[-1].text, "ℹ️ Пользователь 555 уже имеет доступ.")
            await self.send("/start", user=555)
            self.assertEqual(self.http.calls[-1].text, "Распределение недозвонов")
            callback = await self.callback_update("new", user=555)
            await self.send("/removeuser 555", user=777)
            self.assertEqual(self.http.calls[-1].text, "✅ Доступ удалён.\n\nTelegram ID: 555")
        self.assertIn("Admin 777 added user 555", "\n".join(logs.output))
        self.assertIn("Admin 777 removed user 555", "\n".join(logs.output))
        await self.dp.feed_update(self.bot, callback)
        self.assertEqual(self.http.calls[-1].text, NO_ACCESS)
        await self.send("/start", user=555)
        self.assertEqual(self.http.calls[-1].text, NO_ACCESS)
        await self.send("/removeuser 555", user=777)
        self.assertEqual(self.http.calls[-1].text, "ℹ️ Пользователь 555 не найден в списке доступа.")

    async def test_removed_seed_user_is_denied_until_reimport(self):
        await self.send("/removeuser 123", user=777)
        await self.send("/start", user=123)
        self.assertEqual(self.http.calls[-1].text, NO_ACCESS)
        await asyncio.to_thread(self.access.initialize, self.config.allowed_telegram_ids)
        await self.send("/start", user=123)
        self.assertEqual(self.http.calls[-1].text, "Распределение недозвонов")

    async def test_cannot_remove_self_or_other_admin_even_if_stored(self):
        self.access.add_user(888)
        for user in (777, 888):
            await self.send(f"/removeuser {user}", user=777)
            self.assertEqual(self.http.calls[-1].text, "⛔ Нельзя удалить администратора через эту команду.")
            await self.send(f"/adduser {user}", user=777)
            self.assertEqual(self.http.calls[-1].text, f"ℹ️ Пользователь {user} уже имеет доступ.")
        self.assertTrue(self.access.contains(888))
        self.assertFalse(self.access.contains(777))

    async def test_invalid_admin_command_arguments(self):
        original = self.access.list_users()
        for name in ("adduser", "removeuser"):
            for args in ("", "0", "-1", "+1", "1.5", "abc", "123 456", "١٢٣", str(2**63), "9" * 100):
                with self.subTest(command=name, args=args):
                    await self.send(f"/{name} {args}", user=777)
                    self.assertEqual(self.http.calls[-1].text,
                                     f"Использование:\n/{name} TELEGRAM_ID\n\nПример:\n/{name} 123456789")
        self.assertEqual(self.access.list_users(), original)

    async def test_users_sorted_deduplicated_and_marked(self):
        self.access.add_user(777)
        await self.send("/users", user=777)
        self.assertEqual(self.http.calls[-1].text,
                         "👥 Пользователи с доступом\n\n• 123\n• 456\n• 777 — администратор\n"
                         "• 888 — администратор\n\nВсего: 4")

    async def test_long_user_list_fits_telegram_messages(self):
        chunks = users_messages(list(range(1, 2001)), frozenset({777}))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.encode('utf-16-le')) // 2 <= 4096 for chunk in chunks))
        rows = [line for chunk in chunks for line in chunk.splitlines() if line.startswith("•")]
        self.assertEqual(len(rows), 2000)
        self.assertEqual(rows[776], "• 777 — администратор")
        self.assertIn("Всего: 2000", chunks[-1])

    async def test_admin_command_does_not_reset_manual_date_flow(self):
        self.bitrix.counts_for_dates.return_value = dict(zip(self.days, [10, 0, 20]))
        await self.send("/start", user=777)
        for action in ("new", "continue", "stages_done", "period:3", "manual"):
            await self.click(action, user=777)
        original = await self.state(777).get_data()
        await self.send("/adduser@test_bot 555", user=777)
        self.assertTrue(self.access.contains(555))
        self.assertEqual(await self.state(777).get_state(), Flow.manual_date.state)
        self.assertEqual(await self.state(777).get_data(), original)

    async def test_database_failure_denies_access_and_hides_details(self):
        with patch.object(self.access, "contains", side_effect=sqlite3.OperationalError("sensitive detail")):
            await self.send("/start")
            self.assertEqual(self.http.calls[-1].text, "Не удалось проверить или изменить доступ. Попробуйте позже.")
            self.assertEqual(await self.state().get_data(), {})
            await self.send("/start", user=777)
            self.assertEqual(self.http.calls[-1].text, "Распределение недозвонов")
        with patch.object(self.access, "add_user", side_effect=sqlite3.OperationalError("sensitive detail")):
            await self.send("/adduser 555", user=777)
            self.assertEqual(self.http.calls[-1].text, "Не удалось проверить или изменить доступ. Попробуйте позже.")
        self.assertFalse(self.access.contains(555))

    async def test_select_single_stage_and_new_period(self):
        await self.send("/start")
        for action in ("new", "continue", "stage:0"):
            await self.click(action)
        await self.click("stages_done")
        self.assertIn("хотя бы одну стадию", self.http.calls[-1].text)
        for action in ("stage:2", "stages_done"):
            await self.click(action)
        days = previous_days(15, self.config.timezone)
        self.bitrix.counts_for_dates.return_value = dict.fromkeys(days, 10)
        await self.click("period:15")
        self.bitrix.counts_for_dates.assert_awaited_once_with(days, stage_ids=("NEW",))
        self.assertEqual(await self.state().get_state(), Flow.result.state)
        self.assertIn("Всего лидов: 150", (await self.current_message()).text)
        self.assertIn("Стадии: Не обработан", (await self.current_message()).text)
        await self.click("next")
        self.assertIn("Стадии: Не обработан", (await self.current_message()).text)

    async def test_all_selected_stages_used_for_replacements(self):
        await self.send("/start")
        for action in ("new", "continue", "stage:1", "stage:2", "stages_done"):
            await self.click(action)
        self.bitrix.counts_by_stage_for_dates.return_value = {
            day: {"MISSED": 0, "PROCESSED": 0, "NEW": 0} for day in self.days}
        self.bitrix.find_previous_nonempty_by_stage.return_value = None
        await self.click("period:3")
        await self.click("previous")
        self.assertEqual(self.bitrix.find_previous_nonempty_by_stage.call_args.kwargs["stage_ids"], ("MISSED", "PROCESSED", "NEW"))
        await self.click("manual")
        day = self.days[0] - timedelta(days=1)
        self.bitrix.counts_by_stage_for_dates.return_value = {day: {"MISSED": 3, "PROCESSED": 0, "NEW": 6}}
        await self.send(day.strftime("%d.%m.%Y"))
        self.bitrix.counts_by_stage_for_dates.assert_awaited_with([day], stage_ids=("MISSED", "PROCESSED", "NEW"))
        previous = day - timedelta(days=1)
        self.bitrix.find_previous_nonempty_by_stage.return_value = (previous, {"MISSED": 0, "PROCESSED": 2, "NEW": 1})
        await self.click("previous")
        await self.click("skip")
        result = (await self.current_message()).text
        self.assertIn(f"{day:%d.%m.%Y} — недозвоны 3, неудобно говорить 0, не обработан 6", result)
        self.assertIn(f"{previous:%d.%m.%Y} — недозвоны 0, неудобно говорить 2, не обработан 1", result)
        self.assertIn("Всего лидов: 12", result)

    async def test_stage_breakdown_in_result_and_alternatives(self):
        await self.send("/start")
        for action in ("new", "continue", "stage:2", "stages_done"):
            await self.click(action)
        self.bitrix.counts_by_stage_for_dates.return_value = {
            day: {"MISSED": 3, "NEW": 6} for day in self.days}
        await self.click("period:3")
        for action in (None, "next"):
            if action:
                await self.click(action)
            result = (await self.current_message()).text
            for day in self.days:
                self.assertIn(f"{day:%d.%m.%Y} — недозвоны 3, не обработан 6", result)
            self.assertNotIn("неудобно говорить", result.lower())
            self.assertIn("Всего лидов: 27", result)
        self.bitrix.counts_by_stage_for_dates.assert_awaited_once_with(self.days, stage_ids=("MISSED", "NEW"))
        self.bitrix.counts_for_dates.assert_not_awaited()

    async def test_group_sessions_and_foreign_buttons(self):
        chat = -100123
        await self.send("/start@test_bot", chat=chat)
        await self.click("new", chat=chat)
        update = await self.callback_update("continue", chat=chat)
        other = update.model_copy(update={"callback_query": update.callback_query.model_copy(update={
            "from_user": User(id=456, is_bot=False, first_name="Other"),
        })})
        await self.dp.feed_update(self.bot, other)
        self.assertIn("другому пользователю", self.http.calls[-1].text)
        self.assertEqual(await self.state(chat=chat).get_state(), Flow.managers.state)
        await self.send("/start", user=456, chat=chat)
        for action in ("continue", "stages_done", "period:3"):
            await self.click(action, chat=chat)
        self.assertEqual(await self.state(chat=chat).get_state(), Flow.result.state)
        self.assertIsNone(await self.state().get_state())
        await self.click("new", user=456, chat=chat)
        self.assertEqual(await self.state(456, chat).get_state(), Flow.managers.state)
        self.assertEqual(await self.state(chat=chat).get_state(), Flow.result.state)
        await self.send("/users", user=777, chat=chat)
        self.assertIn("только в личном чате", self.http.calls[-1].text)

    async def test_group_manual_date_only_accepts_own_prompt_reply(self):
        chat = -100123
        self.bitrix.counts_for_dates.return_value = dict(zip(self.days, [10, 0, 20]))
        self.bitrix.count_for_date.return_value = 10
        await self.send("/start", chat=chat)
        for action in ("new", "continue", "stages_done", "period:3", "manual"):
            await self.click(action, chat=chat)
        data = await self.state(chat=chat).get_data()
        prompt = self.http.messages[(chat, data["manual_prompt_id"])]
        day = (self.days[0] - timedelta(days=1)).strftime("%d.%m.%Y")
        await self.send(day, chat=chat)
        await self.send(day, chat=chat, user=456, reply=prompt)
        self.bitrix.count_for_date.assert_not_awaited()
        await self.send("31.02", chat=chat, reply=prompt)
        data = await self.state(chat=chat).get_data()
        prompt = self.http.messages[(chat, data["manual_prompt_id"])]
        await self.send(day, chat=chat, reply=prompt)
        self.assertEqual(await self.state(chat=chat).get_state(), Flow.result.state)

    async def test_group_ignores_chatter_and_separates_topics(self):
        chat = -100123
        await self.send("hello", chat=chat, user=999)
        self.assertEqual(self.http.calls, [])
        await self.send("/start", chat=chat, thread=10)
        await self.send("/start", chat=chat, thread=20)
        await self.click("new", chat=chat, thread=10)
        self.assertEqual(await self.state(chat=chat, thread=10).get_state(), Flow.managers.state)
        self.assertIsNone(await self.state(chat=chat, thread=20).get_state())

    async def test_reminder_subscriptions_and_shared_button(self):
        chat = -100123
        await self.send("/reminders_on", chat=chat)
        self.assertEqual(self.http.calls[-1].text, ADMIN_ONLY)
        await self.send("/reminders_on@test_bot", chat=chat, user=777)
        self.assertIn((chat, 0, 777), self.access.list_reminders())
        await self.send("/start")
        self.assertIn((123, 0, 123), self.access.list_reminders())
        await self.send("/reminders_off")
        await self.send("/start")
        self.assertNotIn((123, 0, 123), self.access.list_reminders())
        reminder = Message(message_id=900, chat=Chat(id=chat, type="supergroup"),
                           date=datetime.now(timezone.utc), from_user=User(id=self.bot.id, is_bot=True, first_name="Bot"))
        for user in (123, 456):
            self.sequence += 1
            await self.dp.feed_update(self.bot, Update(update_id=self.sequence, callback_query=CallbackQuery(
                id=str(self.sequence), from_user=User(id=user, is_bot=False, first_name="User"),
                chat_instance="test", message=reminder, data="reminder:new")))
            data = await self.state(user, chat).get_data()
            self.assertEqual(data["selected_stages"], [0])
            self.assertNotEqual(data["message_id"], 900)
        await self.send("/reminders_off", chat=chat, user=777)
        self.assertNotIn((chat, 0, 777), self.access.list_reminders())
