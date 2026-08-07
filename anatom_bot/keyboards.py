"""Inline keyboards. Kept apart from bot.py so the callback-data vocabulary is visible in one file.

Callback naming: "<area>:<action>[:<args>]" — `menu:` navigation, `learn:` study entry points,
`quiz:` in-session actions, `set:` settings, `admin_` the admin panel (unprefixed for history).
"""

from __future__ import annotations

from typing import Any, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from modules import MODULES, SECTIONS_BY_MODULE

WEBAPP_BUTTON_TEXT = "🌐 Открыть АНАТОМ"
PAGE_SIZE = 8


def _webapp_button(text: str = WEBAPP_BUTTON_TEXT) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=config.WEBAPP_URL)


def with_site(rows: list[list[InlineKeyboardButton]], text: str = WEBAPP_BUTTON_TEXT) -> InlineKeyboardMarkup:
    """Append the site link as the last row of any keyboard.

    Driving students to the web app is the bot's main job, so the link is present on *every*
    screen rather than only in the main menu — it is always the last row so it never displaces
    the buttons a student is actually aiming for.
    """
    return InlineKeyboardMarkup(inline_keyboard=[*rows, [_webapp_button(text)]])


def webapp_keyboard(text: str = WEBAPP_BUTTON_TEXT) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_webapp_button(text)]])


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎓 Учиться", callback_data="menu:learn"),
                InlineKeyboardButton(text="⚡ Блиц", callback_data="learn:blitz"),
            ],
            [
                InlineKeyboardButton(text="🔁 Повторить", callback_data="menu:review"),
                InlineKeyboardButton(text="❌ Мои ошибки", callback_data="learn:mistakes"),
            ],
            [
                InlineKeyboardButton(text="📊 Прогресс", callback_data="menu:progress"),
                InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:leaderboard"),
            ],
            [
                InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
                InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:badges"),
            ],
            [
                InlineKeyboardButton(text="🔍 Поиск темы", callback_data="menu:search"),
                InlineKeyboardButton(text="📖 Термин дня", callback_data="menu:term"),
            ],
            [
                InlineKeyboardButton(text="🎓 Экзамен", callback_data="menu:exam"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
            ],
            [_webapp_button()],
        ]
    )


def back_home(extra_rows: Optional[list[list[InlineKeyboardButton]]] = None) -> InlineKeyboardMarkup:
    rows = list(extra_rows or [])
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    return with_site(rows)


def modules_keyboard(rows_progress: list[dict[str, Any]], action: str) -> InlineKeyboardMarkup:
    """One row per module. `action` decides where a tap goes (browse vs. pick-a-topic)."""
    rows = []
    for row in rows_progress:
        text = f"{row['icon']} {row['title']} · {row['passed']}/{row['total']}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"{action}:{row['id']}")])
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    return with_site(rows)


def module_actions_keyboard(module_id: str) -> InlineKeyboardMarkup:
    return with_site(
        [
            [InlineKeyboardButton(text="📝 Тест по модулю", callback_data=f"learn:modtest:{module_id}")],
            [InlineKeyboardButton(text="🏛 Латынь модуля", callback_data=f"learn:modterms:{module_id}")],
            [InlineKeyboardButton(text="📋 Выбрать тему", callback_data=f"menu:topics:{module_id}:0")],
            [InlineKeyboardButton(text="⬅ К модулям", callback_data="menu:learn")],
        ],
        "📖 Читать теорию на сайте",
    )


def topics_keyboard(
    module_id: str, topics: list[dict[str, Any]], page: int, passed_keys: set[str]
) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    chunk = topics[start : start + PAGE_SIZE]
    rows = []
    for topic in chunk:
        mark = "✅ " if f"{module_id}:{topic['num']}" in passed_keys else ""
        title = topic.get("name", "")
        label = f"{mark}{topic['num']}. {title[:40]}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"menu:topic:{module_id}:{topic['num']}")]
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅", callback_data=f"menu:topics:{module_id}:{page - 1}"))
    total_pages = max(1, -(-len(topics) // PAGE_SIZE))
    nav.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="menu:noop")
    )
    if start + PAGE_SIZE < len(topics):
        nav.append(InlineKeyboardButton(text="➡", callback_data=f"menu:topics:{module_id}:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅ К модулю", callback_data=f"menu:module:{module_id}")])
    return with_site(rows)


def topic_actions_keyboard(module_id: str, topic_num: int) -> InlineKeyboardMarkup:
    suffix = f"{module_id}:{topic_num}"
    return with_site(
        [
            [InlineKeyboardButton(text="📝 Тест", callback_data=f"learn:test:{suffix}")],
            [InlineKeyboardButton(text="🃏 Флеш-карточки", callback_data=f"learn:flash:{suffix}")],
            [InlineKeyboardButton(text="🏛 Латинские термины", callback_data=f"learn:terms:{suffix}")],
            [InlineKeyboardButton(text="⬅ К темам", callback_data=f"menu:topics:{module_id}:0")],
        ],
        "📖 Теория и атлас на сайте",
    )


def quiz_options_keyboard(options: list[str], *, show_stop: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{index + 1}. {text[:60]}", callback_data=f"quiz:ans:{index}")]
        for index, text in enumerate(options)
    ]
    if show_stop:
        rows.append([InlineKeyboardButton(text="🛑 Закончить", callback_data="quiz:stop")])
    return with_site(rows)


def flash_reveal_keyboard() -> InlineKeyboardMarkup:
    return with_site(
        [
            [InlineKeyboardButton(text="👁 Показать ответ", callback_data="quiz:reveal")],
            [InlineKeyboardButton(text="🛑 Закончить", callback_data="quiz:stop")],
        ]
    )


def flash_grade_keyboard() -> InlineKeyboardMarkup:
    return with_site(
        [
            [
                InlineKeyboardButton(text="✅ Знал", callback_data="quiz:flash:1"),
                InlineKeyboardButton(text="❌ Не знал", callback_data="quiz:flash:0"),
            ],
            [InlineKeyboardButton(text="🛑 Закончить", callback_data="quiz:stop")],
        ]
    )


def next_question_keyboard() -> InlineKeyboardMarkup:
    return with_site(
        [
            [InlineKeyboardButton(text="➡ Дальше", callback_data="quiz:next")],
            [InlineKeyboardButton(text="🛑 Закончить", callback_data="quiz:stop")],
        ]
    )


def after_session_keyboard(repeat_callback: Optional[str] = None) -> InlineKeyboardMarkup:
    rows = []
    if repeat_callback:
        rows.append([InlineKeyboardButton(text="🔄 Ещё раз", callback_data=repeat_callback)])
    rows.append([InlineKeyboardButton(text="🎓 Другой режим", callback_data="menu:learn")])
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    # Right after a result is the moment a student is most likely to want the full material.
    return with_site(rows, "📖 Разобрать тему на сайте")


def learn_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{m.icon} {m.title}", callback_data=f"menu:module:{m.id}")]
        for m in MODULES
    ]
    rows.append(
        [
            InlineKeyboardButton(text="⚡ Блиц по курсу", callback_data="learn:blitz"),
            InlineKeyboardButton(text="🏛 Вся латынь", callback_data="learn:terms_all"),
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    return with_site(rows, "📖 Весь курс на сайте")


def settings_keyboard(reminder_on: bool, term_lang: str, digest_on: bool, term_day_on: bool) -> InlineKeyboardMarkup:
    return with_site(
        [
            [
                InlineKeyboardButton(
                    text=f"🔔 Напоминания: {'вкл' if reminder_on else 'выкл'}",
                    callback_data="set:reminders",
                )
            ],
            [InlineKeyboardButton(text="⏰ Время напоминания", callback_data="set:time")],
            [InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="set:tz")],
            [
                InlineKeyboardButton(
                    text=f"🌐 Язык терминов: {term_lang.upper()}", callback_data="set:termlang"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📬 Итоги недели: {'вкл' if digest_on else 'выкл'}", callback_data="set:digest"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📖 Термин дня: {'вкл' if term_day_on else 'выкл'}", callback_data="set:termday"
                )
            ],
            [InlineKeyboardButton(text="🎯 Цель дня", callback_data="set:goal")],
            [InlineKeyboardButton(text="🤝 Пригласить друга", callback_data="menu:invite")],
            [InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")],
        ]
    )


def timezone_keyboard() -> InlineKeyboardMarkup:
    """Russian time zones by UTC offset — covers where these students actually are."""
    zones = [
        ("Калининград (UTC+2)", "Europe/Kaliningrad"),
        ("Москва, СПб (UTC+3)", "Europe/Moscow"),
        ("Самара (UTC+4)", "Europe/Samara"),
        ("Екатеринбург (UTC+5)", "Asia/Yekaterinburg"),
        ("Омск (UTC+6)", "Asia/Omsk"),
        ("Красноярск (UTC+7)", "Asia/Krasnoyarsk"),
        ("Иркутск (UTC+8)", "Asia/Irkutsk"),
        ("Якутск (UTC+9)", "Asia/Yakutsk"),
        ("Владивосток (UTC+10)", "Asia/Vladivostok"),
        ("Магадан (UTC+11)", "Asia/Magadan"),
        ("Камчатка (UTC+12)", "Asia/Kamchatka"),
    ]
    rows = [[InlineKeyboardButton(text=label, callback_data=f"set:tzpick:{tz}")] for label, tz in zones]
    rows.append([InlineKeyboardButton(text="⬅ К настройкам", callback_data="menu:settings")])
    return with_site(rows)


def goal_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="10", callback_data="set:goalpick:10"),
            InlineKeyboardButton(text="20", callback_data="set:goalpick:20"),
            InlineKeyboardButton(text="30", callback_data="set:goalpick:30"),
            InlineKeyboardButton(text="50", callback_data="set:goalpick:50"),
        ],
        [InlineKeyboardButton(text="⬅ К настройкам", callback_data="menu:settings")],
    ]
    return with_site(rows)


def review_keyboard(has_due: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_due:
        rows.append([InlineKeyboardButton(text="▶️ Начать повторение", callback_data="learn:review")])
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    return with_site(rows)


def search_results_keyboard(results: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{item['topic']['num']}. {item['topic'].get('name', '')[:44]}",
                callback_data=f"menu:topic:{item['module_id']}:{item['num']}",
            )
        ]
        for item in results
    ]
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    return with_site(rows, "📖 Найти на сайте")


def sections_hint(module_id: str) -> str:
    parts = SECTIONS_BY_MODULE.get(module_id, [])
    return "\n".join(f"{icon} {name} (темы {lo}–{hi})" for name, icon, lo, hi in parts)
