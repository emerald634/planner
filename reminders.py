"""Daily Moscow-time prompts, with subscriptions and delivery claims in SQLite."""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from access import AccessStore
from config import Config
from keyboards import reminder_menu

logger = logging.getLogger(__name__)
MOSCOW = ZoneInfo("Europe/Moscow")


async def send_due_reminders(bot: Bot, access: AccessStore, config: Config,
                             now: datetime | None = None) -> None:
    current = (now or datetime.now(MOSCOW)).astimezone(MOSCOW)
    if current.hour != 10 or current.minute >= 10:
        return
    for chat_id, thread_id, enabled_by in await asyncio.to_thread(access.list_reminders):
        permitted = (enabled_by in config.admin_telegram_ids if chat_id < 0 else
                     await asyncio.to_thread(access.has_access, enabled_by, config.admin_telegram_ids))
        if not permitted:
            continue
        if not await asyncio.to_thread(access.claim_reminder, chat_id, thread_id, current.date().isoformat()):
            continue
        try:
            await bot.send_message(
                chat_id, "Доброе утро! Пора распределить «Недозвоны».\nНажмите кнопку, чтобы начать.",
                message_thread_id=thread_id or None, reply_markup=reminder_menu(),
            )
        except TelegramForbiddenError:
            if chat_id < 0:
                await asyncio.to_thread(access.set_reminder, chat_id, thread_id, enabled_by, False)
            logger.warning("Reminder unavailable: bot has no access to chat %s", chat_id)
        except Exception as exc:
            # Claim before sending prevents duplicate prompts after a process restart.
            # An ambiguous network failure is not retried automatically that day.
            logger.warning("Reminder failed for chat %s: %s", chat_id, type(exc).__name__)


async def reminder_loop(bot: Bot, access: AccessStore, config: Config) -> None:
    while True:
        try:
            await send_due_reminders(bot, access, config)
        except Exception as exc:
            logger.error("Reminder scheduler failed: %s", type(exc).__name__)
        await asyncio.sleep(30)
