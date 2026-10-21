from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from distribution import PERIODS


def _keyboard(revision: str, rows: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"{revision}:{action}")]
        for text, action in rows
    ])


def main_menu(revision: str, mini_app_url: str = "") -> InlineKeyboardMarkup:
    menu = _keyboard(revision, [("📊 Распределить недозвоны", "new")])
    if mini_app_url:
        menu.inline_keyboard.append([InlineKeyboardButton(text="🗓 Мой план дня", web_app=WebAppInfo(url=mini_app_url))])
    return menu


def managers_menu(revision: str, names: Sequence[str], selected: Sequence[int]) -> InlineKeyboardMarkup:
    rows = [(f"{'☑️' if i in selected else '⬜'} {name}", f"manager:{i}")
            for i, name in enumerate(names)]
    return _keyboard(revision, rows + [("Продолжить", "continue")])


def periods_menu(revision: str) -> InlineKeyboardMarkup:
    return _keyboard(revision, [(f"{n} {'дня' if n < 5 else 'дней'}", f"period:{n}")
                                for n in PERIODS] + [("🔄 Новое распределение", "new")])


def stages_menu(revision: str, stages: Sequence[tuple[str, str]], selected: Sequence[int]) -> InlineKeyboardMarkup:
    rows = [(f"{'☑️' if i in selected else '⬜'} {label}" + (" (не настроено)" if not stage_id else ""),
             f"stage:{i}") for i, (label, stage_id) in enumerate(stages)]
    return _keyboard(revision, rows + [("Продолжить", "stages_done"), ("🔄 Новое распределение", "new")])


def reminder_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📊 Распределить недозвоны", callback_data="reminder:new"),
    ]])


def empty_days_menu(revision: str) -> InlineKeyboardMarkup:
    return _keyboard(revision, [
        ("➕ Добавить предыдущий день", "previous"),
        ("📅 Выбрать другую дату", "manual"),
        ("Продолжить без замены", "skip"),
        ("🔄 Новое распределение", "new"),
    ])


def results_menu(revision: str, has_result: bool = True, can_confirm: bool = False) -> InlineKeyboardMarkup:
    rows = [("🔀 Другой результат", "next")] if has_result else []
    if has_result and can_confirm:
        rows.insert(0, ("✅ Подтвердить распределение", "confirm_distribution"))
    return _keyboard(revision, rows + [("🔄 Новое распределение", "new")])
