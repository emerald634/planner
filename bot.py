"""Telegram UI and per-user FSM. Run with: python bot.py."""

import asyncio
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import date, datetime, timedelta
from secrets import token_hex
from typing import Any
from uuid import uuid4, uuid5, UUID
from planner.distribution_queue import DistributionQueue, BINDINGS, MOSCOW, validate

import httpx
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject, WebAppInfo

import keyboards
from access import AccessStore, parse_telegram_id
from bitrix import BitrixClient, BitrixError, USER_ERROR
from config import Config, ConfigError, load_config
from distribution import PERIODS, Distribution, best_distributions, parse_manual_date, previous_days
from reminders import reminder_loop

logger = logging.getLogger(__name__)
NO_ACCESS = "У вас нет доступа к этому боту."
ADMIN_ONLY = "⛔ Эта команда доступна только администратору."
ADMIN_COMMANDS = ("adduser", "removeuser", "users")
NO_ALTERNATIVES = "Других сопоставимых вариантов распределения не найдено."


class Flow(StatesGroup):
    managers = State()
    stages = State()
    period = State()
    empty_days = State()
    manual_date = State()
    result = State()


class AccessAndErrorsMiddleware(BaseMiddleware):
    def __init__(self, config: Config, access: AccessStore) -> None:
        self.config = config
        self.access = access

    async def __call__(self, handler: Callable[..., Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return None
        message = event.message if isinstance(event, CallbackQuery) else event
        try:
            return await self._handle(handler, event, data)
        except sqlite3.Error as exc:
            logger.error("Access database operation failed: %s", type(exc).__name__)
            text = "Не удалось проверить или изменить доступ. Попробуйте позже."
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(message, Message):
                await message.answer(text)
        except BitrixError:
            if isinstance(message, Message):
                await message.answer(USER_ERROR + " Можно повторить действие в последнем меню.")
        except Exception as exc:
            logger.error("Telegram handler failed: %s", type(exc).__name__)
            if isinstance(message, Message):
                await message.answer("Не удалось выполнить действие. Попробуйте ещё раз или отправьте /start.")
        return None

    async def _handle(self, handler: Callable[..., Awaitable[Any]],
                      event: Message | CallbackQuery, data: dict[str, Any]) -> Any:
        message = event.message if isinstance(event, CallbackQuery) else event
        if not isinstance(message, Message) or message.chat.type not in {"private", "group", "supergroup"}:
            return None
        if isinstance(event, Message):
            text = event.text or event.caption or ""
            command_name = text.split(maxsplit=1)[0].split("@", 1)[0] if text.strip() else ""
            if message.chat.type != "private":
                if event.sender_chat is not None:
                    return None
                if not text.startswith("/"):
                    session = await data["state"].get_data()
                    if (data.get("raw_state") != Flow.manual_date.state or not message.reply_to_message
                            or message.reply_to_message.message_id != session.get("manual_prompt_id")):
                        return None
            if command_name in {f"/{name}" for name in ADMIN_COMMANDS}:
                if event.from_user is None or event.from_user.id not in self.config.admin_telegram_ids:
                    await event.answer(ADMIN_ONLY)
                    return None
                if message.chat.type != "private":
                    await event.answer("Команды управления пользователями доступны только в личном чате с ботом.")
                    return None
        if event.from_user is None or not await asyncio.to_thread(
            self.access.has_access, event.from_user.id, self.config.admin_telegram_ids,
        ):
            if isinstance(event, CallbackQuery):
                await event.answer(NO_ACCESS, show_alert=True)
            else:
                await event.answer(NO_ACCESS)
            return None
        if isinstance(event, CallbackQuery):
            if event.data == "reminder:new":
                return await handler(event, data)
            session = await data["state"].get_data()
            revision = (event.data or "").split(":", 1)[0]
            if revision.split(".", 1)[0] != str(event.from_user.id):
                await event.answer("Эти кнопки принадлежат другому пользователю. Начните свой сценарий командой /start.", show_alert=True)
                return None
            if revision != session.get("revision") or message.message_id != session.get("message_id"):
                await event.answer("Эта кнопка устарела. Используйте последнее меню или /start.", show_alert=True)
                return None
        return await handler(event, data)


def users_messages(users: list[int], admin_ids: frozenset[int]) -> list[str]:
    ids = sorted(set(users) | admin_ids)
    lines = ["👥 Пользователи с доступом", ""]
    lines += [f"• {user_id}" + (" — администратор" if user_id in admin_ids else "") for user_id in ids]
    lines += ["", f"Всего: {len(ids)}"]
    chunks: list[str] = []
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3500:
            chunks.append(chunk.rstrip())
            chunk = ""
        chunk += line + "\n"
    chunks.append(chunk.rstrip())
    return chunks


async def manage_users(message: Message, command: CommandObject,
                       config: Config, access: AccessStore) -> None:
    if command.command == "users":
        if command.args:
            await message.answer("Использование:\n/users")
            return
        users = await asyncio.to_thread(access.list_users)
        for text in users_messages(users, config.admin_telegram_ids):
            await message.answer(text)
        return
    try:
        user_id = parse_telegram_id(command.args or "")
    except ValueError:
        await message.answer(f"Использование:\n/{command.command} TELEGRAM_ID\n\n"
                             f"Пример:\n/{command.command} 123456789")
        return
    if command.command == "adduser":
        if user_id in config.admin_telegram_ids or not await asyncio.to_thread(
            access.add_user, user_id, message.from_user.id,
        ):
            await message.answer(f"ℹ️ Пользователь {user_id} уже имеет доступ.")
            return
        logger.info("Admin %s added user %s", message.from_user.id, user_id)
        await asyncio.to_thread(access.ensure_private_reminders, [user_id])
        await message.answer(f"✅ Доступ добавлен.\n\nTelegram ID: {user_id}")
    elif command.command == "removeuser":
        if user_id in config.admin_telegram_ids:
            await message.answer("⛔ Нельзя удалить администратора через эту команду.")
            return
        if not await asyncio.to_thread(access.remove_user, user_id):
            await message.answer(f"ℹ️ Пользователь {user_id} не найден в списке доступа.")
            return
        logger.info("Admin %s removed user %s", message.from_user.id, user_id)
        await message.answer(f"✅ Доступ удалён.\n\nTelegram ID: {user_id}")


async def show(target: Message | CallbackQuery, state: FSMContext, text: str,
               keyboard: Callable[[str], InlineKeyboardMarkup]) -> None:
    revision = f"{state.key.user_id}.{token_hex(4)}"
    markup = keyboard(revision)
    if isinstance(target, CallbackQuery) and isinstance(target.message, Message):
        message = await target.message.edit_text(text, reply_markup=markup)
    elif isinstance(target, Message):
        message = await target.answer(text, reply_markup=markup)
    else:
        return
    if isinstance(message, Message):
        await state.update_data(revision=revision, message_id=message.message_id)


async def start(message: Message, state: FSMContext, access: AccessStore, config: Config) -> None:
    if message.chat.type == "private":
        await asyncio.to_thread(access.ensure_private_reminders, [message.from_user.id])
    await state.clear()
    url = config.mini_app_url if message.chat.type == "private" else ""
    await show(message, state, "Распределение недозвонов", lambda rev: keyboards.main_menu(rev, url))


async def open_planner(message: Message, config: Config) -> None:
    if message.chat.type != "private":
        await message.answer("Откройте личный чат с ботом и отправьте /plan.")
    elif not config.mini_app_url:
        await message.answer("Планировщик ещё не подключён. Обратитесь к руководителю.")
    else:
        await message.answer("Ваш рабочий день — в планировщике.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗓 Открыть план дня", web_app=WebAppInfo(url=config.mini_app_url)),
        ]]))


async def configure_reminders(message: Message, command: CommandObject,
                              config: Config, access: AccessStore) -> None:
    if message.chat.type != "private" and message.from_user.id not in config.admin_telegram_ids:
        await message.answer(ADMIN_ONLY)
        return
    if command.args:
        await message.answer(f"Использование:\n/{command.command}")
        return
    enabled = command.command == "reminders_on"
    await asyncio.to_thread(access.set_reminder, message.chat.id,
                            message.message_thread_id if message.is_topic_message else 0,
                            message.from_user.id, enabled)
    await message.answer("🔔 Напоминания включены: каждый день в 10:00 по Москве в этом чате."
                         if enabled else "🔕 Напоминания в этом чате выключены.")


async def new_distribution(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(Flow.managers)
    await state.update_data(selected=[0, 1, 2], selected_stages=[0])
    target = callback.message if callback.data == "reminder:new" else callback
    await show(target, state, "Выберите менеджеров:",
               lambda rev: keyboards.managers_menu(rev, config.manager_names, [0, 1, 2]))


async def toggle_manager(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    index = int((callback.data or "").rsplit(":", 1)[1])
    if index not in range(3):
        await callback.answer("Неизвестный менеджер.")
        return
    await callback.answer()
    selected = set((await state.get_data())["selected"])
    selected.symmetric_difference_update({index})
    await state.update_data(selected=sorted(selected))
    await show(callback, state, "Выберите менеджеров:",
               lambda rev: keyboards.managers_menu(rev, config.manager_names, sorted(selected)))


async def choose_stages(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    if not (await state.get_data())["selected"]:
        await callback.answer("Выберите хотя бы одного менеджера.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(Flow.stages)
    selected = (await state.get_data())["selected_stages"]
    await show(callback, state, "Выберите одну или несколько стадий:",
               lambda rev: keyboards.stages_menu(rev, config.stages, selected))


async def toggle_stage(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    index = int((callback.data or "").rsplit(":", 1)[1])
    if index not in range(len(config.stages)) or not config.stages[index][1]:
        await callback.answer("Эта стадия пока не настроена. Администратору нужно указать её STATUS_ID в .env.", show_alert=True)
        return
    await callback.answer()
    selected = set((await state.get_data())["selected_stages"])
    selected.symmetric_difference_update({index})
    await state.update_data(selected_stages=sorted(selected))
    await show(callback, state, "Выберите одну или несколько стадий:",
               lambda rev: keyboards.stages_menu(rev, config.stages, sorted(selected)))


async def choose_period(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    selected = (await state.get_data())["selected_stages"]
    if not selected:
        await callback.answer("Выберите хотя бы одну стадию.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(stage_ids=tuple(config.stages[i][1] for i in selected),
                            stage_names=tuple(config.stages[i][0] for i in selected))
    await state.set_state(Flow.period)
    await show(callback, state, "Выберите период. Отсчёт начинается со вчерашнего дня.", keyboards.periods_menu)


async def load_period(callback: CallbackQuery, state: FSMContext,
                      config: Config, bitrix: BitrixClient) -> None:
    days = int((callback.data or "").rsplit(":", 1)[1])
    if days not in PERIODS:
        await callback.answer("Выберите период: 3, 4, 5, 6, 7, 10 или 15 дней.")
        return
    await callback.answer("Получаю данные из Bitrix24…")
    dates = previous_days(days, config.timezone)
    data = await state.get_data()
    stage_counts = {}
    if len(data["stage_ids"]) > 1:
        stage_counts = await bitrix.counts_by_stage_for_dates(dates, stage_ids=data["stage_ids"])
        counts = {day: sum(values.values()) for day, values in stage_counts.items()}
    else:
        counts = await bitrix.counts_for_dates(dates, stage_ids=data["stage_ids"])
    await state.update_data(
        stage_counts=stage_counts,
        target_count=days, counts={day: count for day, count in counts.items() if count},
        empty_dates=[day for day, count in counts.items() if not count], search_before=min(dates),
    )
    await after_dates_changed(callback, state, config)


async def show_empty_days(target: Message | CallbackQuery, state: FSMContext, notice: str = "") -> None:
    data = await state.get_data()
    counts = data["counts"]
    lines = [notice] if notice else []
    lines += ["Пустые даты исходного периода исключены:",
              ", ".join(day.strftime("%d.%m.%Y") for day in data["empty_dates"]), "",
              "Стадии: " + ", ".join(data["stage_names"]), "Даты с лидами:"]
    lines += [f"{day:%d.%m.%Y} — {count}" for day, count in sorted(counts.items())] or ["Пока нет."]
    lines += ["", f"Не хватает непустых дат: {data['target_count'] - len(counts)}.",
              "Добавьте замену или продолжите без неё."]
    await state.set_state(Flow.empty_days)
    await show(target, state, "\n".join(lines), keyboards.empty_days_menu)


async def after_dates_changed(target: Message | CallbackQuery, state: FSMContext,
                              config: Config, notice: str = "") -> None:
    data = await state.get_data()
    if len(data["counts"]) == data["target_count"]:
        await finish(target, state, config, notice)
    else:
        await show_empty_days(target, state, notice)


async def previous_day(callback: CallbackQuery, state: FSMContext,
                       config: Config, bitrix: BitrixClient) -> None:
    await callback.answer("Ищу предыдущий день с лидами…")
    data = await state.get_data()
    before = data["search_before"]
    multiple_stages = len(data["stage_ids"]) > 1
    search = bitrix.find_previous_nonempty_by_stage if multiple_stages else bitrix.find_previous_nonempty
    found = await search(before, excluded=data["counts"], stage_ids=data["stage_ids"])
    if found is None:
        await show_empty_days(callback, state, "Более ранних дат с лидами выбранных стадий не найдено.")
        return
    day, count = found
    stage_counts = dict(data["stage_counts"])
    if multiple_stages:
        stage_counts[day] = count
        count = sum(count.values())
    counts = dict(data["counts"])
    counts[day] = count
    await state.update_data(counts=counts, stage_counts=stage_counts, search_before=day)
    notice = f"Добавлена дата {day:%d.%m.%Y} — {count}."
    if before - day > timedelta(days=1):
        notice += " Пустые и уже выбранные даты при поиске пропущены."
    await after_dates_changed(callback, state, config, notice)


async def request_manual_date(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Flow.manual_date)
    await show(callback, state, "Введите дату: ДД.ММ.ГГГГ или ДД.ММ.\n"
               "Без года используется текущий год. Сегодняшние и будущие даты не учитываются.",
               keyboards.empty_days_menu)
    if isinstance(callback.message, Message) and callback.message.chat.type != "private":
        prompt = await callback.message.answer(
            f"{callback.from_user.full_name}, ответьте на это сообщение датой ДД.ММ.ГГГГ или ДД.ММ.",
            reply_markup=ForceReply(input_field_placeholder="ДД.ММ.ГГГГ"),
        )
        await state.update_data(manual_prompt_id=prompt.message_id)


async def manual_date(message: Message, state: FSMContext,
                      config: Config, bitrix: BitrixClient) -> None:
    try:
        day = parse_manual_date(message.text or "", datetime.now(config.timezone).date())
    except ValueError as exc:
        await manual_date_error(message, state, str(exc))
        return
    data = await state.get_data()
    if day in data["counts"]:
        await manual_date_error(message, state, "Эта дата уже добавлена. Выберите другую.")
        return
    stage_counts = dict(data["stage_counts"])
    if len(data["stage_ids"]) > 1:
        breakdown = await bitrix.counts_by_stage_for_dates([day], stage_ids=data["stage_ids"])
        stage_counts[day] = breakdown[day]
        count = sum(breakdown[day].values())
    else:
        count = await bitrix.count_for_date(day, stage_ids=data["stage_ids"])
    if count == 0:
        await manual_date_error(message, state, f"{day:%d.%m.%Y} — 0 лидов выбранных стадий. Дата исключена. "
                                 "Введите другую дату или используйте кнопки последнего меню.")
        return
    counts = dict(data["counts"])
    counts[day] = count
    await state.update_data(counts=counts, stage_counts=stage_counts)
    await after_dates_changed(message, state, config, f"Добавлена дата {day:%d.%m.%Y} — {count}.")


async def manual_date_error(message: Message, state: FSMContext, text: str) -> None:
    group = message.chat.type != "private"
    reply = await message.answer(text, reply_markup=ForceReply() if group else None)
    if group:
        await state.update_data(manual_prompt_id=reply.message_id)


def format_result(result: Distribution, index: int, count: int,
                  stage_names: tuple[str, ...] = ("Недозвоны",),
                  stage_ids: tuple[str, ...] = (),
                  stage_counts: dict[date, dict[str, int]] | None = None) -> str:
    dates = sorted(day for allocation in result.allocations for day, _ in allocation.days)
    period = f"{dates[0]:%d.%m.%Y}–{dates[-1]:%d.%m.%Y}" if len(dates) > 1 else f"{dates[0]:%d.%m.%Y}"
    missed_only = stage_names == ("Недозвоны",)
    lines = ["📊 Распределение недозвонов" if missed_only else "📊 Распределение лидов",
             "Стадии: " + ", ".join(stage_names), "", "Период:", period,
             "Учитываются только даты, перечисленные ниже.", "",
             f"Всего {'недозвонов' if missed_only else 'лидов'}: {result.total}"]
    for allocation in result.allocations:
        lines += ["", f"👤 {allocation.manager}"]
        for day, number in allocation.days:
            if len(stage_names) > 1:
                details = ", ".join(
                    f"{name.lower()} {stage_counts[day][stage_id]}"
                    for name, stage_id in zip(stage_names, stage_ids, strict=True)
                )
                lines.append(f"{day:%d.%m.%Y} — {details}")
            else:
                lines.append(f"{day:%d.%m.%Y} — {number}")
        if not allocation.days:
            lines.append("Нет назначенных дат.")
        lines.append(f"Итого: {allocation.total}")
    lines += ["", f"Разница нагрузки: {result.spread}", f"Вариант {index + 1} из {count}"]
    return "\n".join(lines)


async def finish(target: Message | CallbackQuery, state: FSMContext,
                 config: Config, notice: str = "") -> None:
    data = await state.get_data()
    managers = [config.manager_names[index] for index in data["selected"]]
    variants = await asyncio.to_thread(best_distributions, data["counts"], managers)
    await state.update_data(variants=variants, variant_index=0, distribution_session=str(uuid4()))
    await state.set_state(Flow.result)
    text = format_result(variants[0], 0, len(variants), data["stage_names"],
                         data["stage_ids"], data["stage_counts"]) if variants else "Нет непустых дат для распределения."
    if notice:
        text = notice + "\n\n" + text
    await show(target, state, text, lambda rev: keyboards.results_menu(rev, bool(variants),
               data["stage_ids"] == ("IN_PROCESS",) and state.key.user_id in config.distribution_confirmer_ids and (config.distribution_queue_path is not None or config.queue_writer_socket is not None)))


async def skip_empty(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    await callback.answer()
    await finish(callback, state, config)


async def next_result(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    data = await state.get_data()
    index = data["variant_index"] + 1
    variants = data["variants"]
    if index >= len(variants):
        await callback.answer(NO_ALTERNATIVES, show_alert=True)
        return
    await callback.answer()
    await show(callback, state, format_result(variants[index], index, len(variants), data["stage_names"],
                                             data["stage_ids"], data["stage_counts"]), lambda rev: keyboards.results_menu(rev, True,
                                             data["stage_ids"] == ("IN_PROCESS",) and callback.from_user.id in config.distribution_confirmer_ids and (config.distribution_queue_path is not None or config.queue_writer_socket is not None)))
    await state.update_data(variant_index=index)


async def confirm_distribution(callback: CallbackQuery, state: FSMContext, config: Config, bitrix: BitrixClient) -> None:
    data = await state.get_data()
    if callback.from_user.id not in config.distribution_confirmer_ids:
        await callback.answer("Нет права подтверждать распределение.", show_alert=True)
        return
    if data.get("stage_ids") != ("IN_PROCESS",) or (config.distribution_queue_path is None and config.queue_writer_socket is None):
        await callback.answer("Подтверждение доступно только для недозвонов IN_PROCESS при настроенной очереди.", show_alert=True)
        return
    await callback.answer("Проверяю актуальные недозвоны…")
    result = data["variants"][data["variant_index"]]
    identifier = str(uuid5(UUID(data["distribution_session"]), str(data["variant_index"])))
    queue = None
    try:
        if config.queue_writer_socket is not None:
            from planner.queue_broker import BrokerQueue
            from planner.runtime_files import secret_file
            queue = BrokerQueue(config.queue_writer_socket,secret_file(config.queue_writer_key_file),callback.from_user.id)
        else:
            queue = DistributionQueue(config.distribution_queue_path)
        await asyncio.to_thread(queue.initialize)
        existing = await asyncio.to_thread(queue.find, identifier)
        if existing is not None:
            await callback.message.answer(confirmation_summary(existing, repeated=True))
            return
        mapped = []
        selected = sorted(data["selected"])
        for allocation in result.allocations:
            index = next(i for i in selected if config.manager_names[i] == allocation.manager)
            tg = config.manager_telegram_ids[index]
            if tg not in BINDINGS or tg not in config.planner_active_manager_ids:
                await callback.message.answer("В варианте есть сотрудник без активной привязки Mini App. Ничего не сохранено. Выберите только действующих менеджеров и начните новое распределение.")
                return
            mapped.append((allocation, tg))
        allocations = []
        seen_ids, seen_dates = set(), set()
        for allocation, tg in mapped:
            items = []
            dates = []
            for day, expected in allocation.days:
                if day in seen_dates:
                    raise ValueError("Пересечение дат между менеджерами.")
                seen_dates.add(day)
                dates.append(day.isoformat())
                leads = await bitrix.get_leads(day, day, stage_ids=("IN_PROCESS",))
                if len(leads) != expected:
                    raise ValueError("Количество лидов изменилось.")
                for lead in leads:
                    if lead.id in seen_ids or lead.stage_id != "IN_PROCESS" or lead.created_at.astimezone(MOSCOW).date() != day:
                        raise ValueError("Некорректные или повторяющиеся лиды.")
                    seen_ids.add(lead.id)
                    items.append({"id": lead.id, "created_date": day.isoformat(), "stage_id": lead.stage_id})
            allocations.append({"telegram_id": tg, "bitrix_id": BINDINGS[tg], "name": allocation.manager,
                                "dates": dates, "leads": sorted(items, key=lambda lead: lead["id"]), "count": len(items)})
        now = datetime.now(MOSCOW)
        snapshot = {"schema": 1, "distribution_id": identifier, "workday": now.date().isoformat(),
                    "confirmed_at": now.isoformat(), "confirmed_by": callback.from_user.id,
                    "variant_index": data["variant_index"], "variant_id": identifier,
                    "stage_id": "IN_PROCESS", "allocations": allocations, "total": len(seen_ids)}
        validate(snapshot)
        await asyncio.to_thread(queue.publish, snapshot, config.distribution_confirmer_ids)
    except BitrixError:
        await callback.message.answer("Bitrix24 недоступен. Распределение не сохранено. Повторите подтверждение или нажмите «Новое распределение».")
        return
    except (sqlite3.Error, OSError):
        await callback.message.answer("Не удалось проверить или записать очередь. Подтверждение пока не установлено. Повторите нажатие: повтор не создаст дубликат.")
        return
    except ValueError:
        await callback.message.answer("Данные изменились, обнаружен конфликт или на сегодня уже подтверждено другое распределение. Новая запись не создана. Нажмите «Новое распределение» для обновления расчёта.")
        return
    finally:
        if queue is not None and hasattr(queue,'close'):
            queue.close()
    await callback.message.answer(confirmation_summary(snapshot))


def confirmation_summary(snapshot, repeated=False):
    lines = [("✅ Распределение уже подтверждено" if repeated else "✅ Распределение подтверждено"),
             "Дата: " + datetime.fromisoformat(snapshot["confirmed_at"]).astimezone(MOSCOW).strftime("%d.%m.%Y"),
             f"Вариант: {snapshot['variant_index'] + 1}"]
    for item in snapshot["allocations"]:
        lines.append(f"{item['name']}: {item['count']} недозвонов; даты: " + (", ".join(item["dates"]) or "нет назначенных дат"))
    lines.append(f"Всего: {snapshot['total']}. Сохранено в очередь; импорт в планы выполняется отдельно.")
    return "\n".join(lines)


async def unknown_message(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer("Используйте кнопки последнего меню или отправьте /start.")


async def unknown_callback(callback: CallbackQuery) -> None:
    await callback.answer("Используйте последнее меню или отправьте /start.", show_alert=True)


def create_dispatcher(config: Config, bitrix: BitrixClient, access: AccessStore) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation(),
                    fsm_strategy=FSMStrategy.USER_IN_TOPIC,
                    config=config, bitrix=bitrix, access=access)
    router = Router()
    guard = AccessAndErrorsMiddleware(config, access)
    router.message.outer_middleware(guard)
    router.callback_query.outer_middleware(guard)
    router.message.register(manage_users, Command(*ADMIN_COMMANDS))
    router.message.register(open_planner, Command("plan"))
    router.message.register(configure_reminders, Command("reminders_on", "reminders_off"))
    router.message.register(start, CommandStart())
    router.callback_query.register(new_distribution, F.data.endswith(":new"))
    router.callback_query.register(toggle_manager, Flow.managers, F.data.contains(":manager:"))
    router.callback_query.register(choose_stages, Flow.managers, F.data.endswith(":continue"))
    router.callback_query.register(toggle_stage, Flow.stages, F.data.contains(":stage:"))
    router.callback_query.register(choose_period, Flow.stages, F.data.endswith(":stages_done"))
    router.callback_query.register(load_period, Flow.period, F.data.contains(":period:"))
    replace_states = StateFilter(Flow.empty_days, Flow.manual_date)
    router.callback_query.register(previous_day, replace_states, F.data.endswith(":previous"))
    router.callback_query.register(request_manual_date, replace_states, F.data.endswith(":manual"))
    router.callback_query.register(skip_empty, replace_states, F.data.endswith(":skip"))
    router.callback_query.register(next_result, Flow.result, F.data.endswith(":next"))
    router.callback_query.register(confirm_distribution, Flow.result, F.data.endswith(":confirm_distribution"))
    router.message.register(manual_date, Flow.manual_date)
    router.message.register(unknown_message)
    router.callback_query.register(unknown_callback)
    dp.include_router(router)
    return dp


class SafeFormatter(logging.Formatter):
    def __init__(self, config: Config) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self._secrets = (config.bot_token, config.bitrix_webhook_url,
                         config.bitrix_webhook_url.rstrip("/").rsplit("/", 1)[-1])

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            text = text.replace(secret, "[секрет скрыт]")
        return re.sub(r"https?://[^\s<>\"']+", "[URL скрыт]", text)


async def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(config))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("httpx", "httpcore", "aiohttp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        access = AccessStore(config.access_db_path)
        await asyncio.to_thread(access.initialize, config.allowed_telegram_ids)
        users = await asyncio.to_thread(access.list_users)
        await asyncio.to_thread(access.ensure_private_reminders, set(users) | config.admin_telegram_ids)
        if config.distribution_queue_path and config.distribution_confirmer_ids and config.queue_writer_socket is None:
            try:
                # Writer startup also recovers a hot DELETE journal after a crash.
                await asyncio.to_thread(DistributionQueue(config.distribution_queue_path).initialize)
            except (sqlite3.Error, OSError, ValueError):
                logger.warning("Distribution queue initialization unavailable; confirmation will retry")
        async with httpx.AsyncClient() as client, Bot(config.bot_token) as telegram:
            bitrix = BitrixClient(config.bitrix_webhook_url, config.missed_call_stage_id,
                                  config.timezone, client)
            dp = create_dispatcher(config, bitrix, access)
            reminder_task = asyncio.create_task(reminder_loop(telegram, access, config))
            try:
                await dp.start_polling(telegram, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False)
            finally:
                reminder_task.cancel()
                with suppress(asyncio.CancelledError):
                    await reminder_task
    except sqlite3.Error as exc:
        logger.error("Access database initialization failed: %s", type(exc).__name__)
        raise SystemExit("Не удалось открыть базу доступа. Проверьте ACCESS_DB_PATH и права на папку базы.") from None
    except Exception as exc:
        logger.error("Bot stopped: %s", type(exc).__name__)
        raise SystemExit("Не удалось запустить бота. Проверьте настройки и доступ к Telegram.") from None


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
