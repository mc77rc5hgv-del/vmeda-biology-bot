"""Admin panel: stats, broadcast, user lookup, leaderboard — for ADMIN_IDS only."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
import content
import db
import texts
from achievements import level_for_xp
from state_logic import module_progress

logger = logging.getLogger(__name__)

# user_id -> pending action ("broadcast" | "lookup"); mirrors the main bot's ADMIN_PENDING pattern.
ADMIN_PENDING: dict[int, str] = {}

BROADCAST_DELAY_SECONDS = 0.05  # ~20 msg/s — under Telegram's ~30/s bulk ceiling


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

    now = dt.datetime.now(dt.timezone.utc)
    day_ago = now - dt.timedelta(days=1)
    week_ago = now - dt.timedelta(days=7)

    new_day = await session.scalar(
        select(func.count()).select_from(db.User).where(db.User.created_at >= day_ago)
    )
    new_week = await session.scalar(
        select(func.count()).select_from(db.User).where(db.User.created_at >= week_ago)
    )
    active_week = await session.scalar(
        select(func.count()).select_from(db.UserState).where(db.UserState.updated_at >= week_ago)
    )
    with_chat = await session.scalar(
        select(func.count()).select_from(db.User).where(db.User.chat_id.is_not(None))
    )

    rows = await db.top_users_by_xp(session, limit=5)
    stats = content.counts()

    lines = [
        "📊 <b>Статистика АНАТОМ-бота</b>",
        "",
        f"👥 Пользователей: <b>{total_users}</b>",
        f"   из них доступны для сообщений: {with_chat}",
        f"📈 Новых за сутки: {new_day} · за неделю: {new_week}",
        f"⚡ Активны за неделю: {active_week}",
        f"🔔 С напоминаниями: {reminders_on}",
        "",
        f"📚 Контент: {stats['topics']} тем · {stats['cards']} карточек · "
        f"{stats['pairs']} терминов · {stats['tests']} вопросов",
    ]

    if rows:
        lines += ["", "<b>Топ-5 по XP:</b>"]
        for index, row in enumerate(rows, start=1):
            name = texts.display_name(row.get("first_name"), row.get("last_name"), row.get("username"))
            lines.append(f"{index}. {name} — {row['xp']} XP")
    return "\n".join(lines)


async def build_user_summary_text(session: AsyncSession, target_id: int) -> str:
    record = await db.get_user_full(session, target_id)
    if record is None:
        return f"Пользователь {target_id} не найден в базе."

    user = record["user"]
    state = record["state"]
    reminder = record["reminder"]
    prefs = user.prefs or {}

    name = texts.display_name(user.first_name, user.last_name, user.username)
    username = f"@{user.username}" if user.username else "—"
    xp = int(state.get("xp") or 0)
    level_no, level_title, _, _ = level_for_xp(xp)

    reminder_text = "выключены"
    if reminder is not None and reminder.enabled:
        reminder_text = f"{reminder.time.strftime('%H:%M')} ({reminder.tz})"

    rows = module_progress(state)
    passed = sum(row["passed"] for row in rows)
    total = sum(row["total"] for row in rows)
    referrals = await db.count_referrals(session, target_id)

    lines = [
        f"👤 <b>{name}</b> ({username})",
        f"ID: <code>{user.id}</code>",
        f"Регистрация: {user.created_at:%d.%m.%Y %H:%M}",
        "",
        f"⭐ XP: {xp} · уровень {level_no} ({level_title})",
        f"🔥 Серия: {state.get('streak', 0)}",
        f"📚 Пройдено: {passed}/{total}",
        f"❌ Ошибок: {len(state.get('mistakes') or [])}",
        f"🔔 Напоминания: {reminder_text}",
        f"🤝 Приглашено: {referrals}",
    ]
    if prefs.get("exam_date"):
        lines.append(f"🎓 Экзамен: {prefs['exam_date']}")
    if prefs.get("referred_by"):
        lines.append(f"👋 Пришёл по приглашению: {prefs['referred_by']}")
    return "\n".join(lines)


async def broadcast_text(bot: Bot, session: AsyncSession, text: str) -> tuple[int, int]:
    """Send `text` to every reachable chat, paced to stay inside Telegram's rate limits."""
    chat_ids = await db.list_chat_ids(session)
    sent = failed = 0

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, text)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            try:
                await bot.send_message(chat_id, text)
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            # Blocked the bot / deleted the chat — routine at this scale.
            failed += 1
        except Exception:
            logger.exception("Broadcast failed for chat_id=%s", chat_id)
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY_SECONDS)

    return sent, failed
