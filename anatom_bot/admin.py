"""Minimal admin panel: /admin command, stats, broadcast, user lookup by ID."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

import config
import db

# user_id -> pending action ("broadcast" | "lookup"), mirrors telegram_bot.py's ADMIN_PENDING pattern.
ADMIN_PENDING: dict[int, str] = {}

BROADCAST_DELAY_SECONDS = 0.05


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🔍 Найти пользователя по ID", callback_data="admin_lookup")],
        ]
    )


async def build_stats_text(session: AsyncSession) -> str:
    total_users = await db.count_users(session)
    reminders_on = await db.count_reminders_enabled(session)
    return (
        "📊 Статистика АНАТОМ-бота\n\n"
        f"Пользователей: {total_users}\n"
        f"С включёнными напоминаниями: {reminders_on}"
    )


async def build_user_summary_text(session: AsyncSession, target_id: int) -> str:
    record = await db.get_user_full(session, target_id)
    if record is None:
        return f"Пользователь {target_id} не найден в базе."

    user = record["user"]
    state = record["state"]
    reminder = record["reminder"]

    name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
    username = f"@{user.username}" if user.username else "—"
    reminder_text = "выключены"
    if reminder is not None and reminder.enabled:
        reminder_text = f"{reminder.time.strftime('%H:%M')} ({reminder.tz})"

    lines = [
        f"👤 {name} ({username})",
        f"ID: {user.id}",
        f"Регистрация: {user.created_at:%Y-%m-%d %H:%M}",
        f"XP: {state.get('xp', 0)}",
        f"Серия: {state.get('streak', 0)}",
        f"Напоминания: {reminder_text}",
    ]
    return "\n".join(lines)


async def broadcast_text(bot: Bot, session: AsyncSession, text: str) -> tuple[int, int]:
    chat_ids = await db.list_chat_ids(session)
    sent = failed = 0
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY_SECONDS)
    return sent, failed
