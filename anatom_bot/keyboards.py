"""Keyboards. The bot's job is to get students into the MiniApp, so the launch button is the
most prominent element on every screen.

Telegram opens a MiniApp from three different button types, and all three are used here:
`MenuButtonWebApp` (the ☰ next to the input), `KeyboardButton(web_app=…)` (the persistent
keyboard) and `InlineKeyboardButton(web_app=…)` (inside messages). They only work over HTTPS and
only in private chats, which is exactly how this bot is used.
"""

from __future__ import annotations

from typing import Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

import config

OPEN_APP_TEXT = "🚀 Открыть АНАТОМ"
MENU_BUTTON_TEXT = "АНАТОМ"

NAV_APP = "🚀 Открыть АНАТОМ"
NAV_REMINDER = "⏰ Напоминания"
NAV_ADMIN = "⚙️ Админ"

NAV_BUTTONS = (NAV_APP, NAV_REMINDER)
NAV_BUTTONS_ADMIN = NAV_BUTTONS + (NAV_ADMIN,)


def web_app_info() -> WebAppInfo:
    return WebAppInfo(url=config.WEBAPP_URL)


def open_app_button(text: str = OPEN_APP_TEXT) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=web_app_info())


def menu_button() -> MenuButtonWebApp:
    """The ☰ button beside the input field — the most visible launcher Telegram offers."""
    return MenuButtonWebApp(text=MENU_BUTTON_TEXT, web_app=web_app_info())


def open_app(text: str = OPEN_APP_TEXT) -> InlineKeyboardMarkup:
    """A single, full-width launch button — used wherever the whole point is to open the app."""
    return InlineKeyboardMarkup(inline_keyboard=[[open_app_button(text)]])


def with_app(
    rows: Optional[list[list[InlineKeyboardButton]]] = None, text: str = OPEN_APP_TEXT
) -> InlineKeyboardMarkup:
    """Put the launch button first, above whatever else the screen offers."""
    return InlineKeyboardMarkup(inline_keyboard=[[open_app_button(text)], *(rows or [])])


def reply_nav(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Persistent keyboard: launching the app is one tap from anywhere, at any time.

    The admin row is added only for admins, but the handler behind it re-checks permission —
    a reply button is just text and anyone could type it.
    """
    keyboard = [
        [KeyboardButton(text=NAV_APP, web_app=web_app_info())],
        [KeyboardButton(text=NAV_REMINDER)],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text=NAV_ADMIN)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Открой АНАТОМ, чтобы заниматься…",
    )


def reminder_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🔕 Выключить напоминания" if enabled else "🔔 Включить напоминания",
                callback_data="rem:toggle",
            )
        ],
        [InlineKeyboardButton(text="⏰ Изменить время", callback_data="rem:time")],
        [InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="rem:tz")],
    ]
    return with_app(rows)


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
    rows = [[InlineKeyboardButton(text=label, callback_data=f"rem:tz:{tz}")] for label, tz in zones]
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="rem:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
