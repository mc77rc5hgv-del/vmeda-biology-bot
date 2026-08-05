"""APScheduler cron jobs: daily reminder, streak protection, inactivity win-back.

Runs inside the bot process (started from bot.py's main()) since it needs the live Bot
instance to actually send messages.
"""

from __future__ import annotations

import datetime as dt
import logging
import zoneinfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

import config
import db
from state_logic import (
    format_daily_reminder_text,
    format_inactivity_text,
    format_streak_warning_text,
    is_inactive,
    is_streak_at_risk,
    topics_due_for_review,
)

logger = logging.getLogger(__name__)

STREAK_PROTECTION_HOUR = 20  # local (per-user tz) hour to send the evening streak warning
INACTIVITY_CHECK_HOUR_UTC = 10  # once-a-day sweep for the 14-day win-back message


async def _send(bot: Bot, chat_id: int | None, text: str) -> None:
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        logger.exception("Failed to send reminder to chat_id=%s", chat_id)


async def run_daily_reminders(bot: Bot) -> None:
    """Fires every minute; sends each user's configured reminder once their local time matches."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        result = await session.execute(select(db.Reminder).where(db.Reminder.enabled.is_(True)))
        reminders = result.scalars().all()

        for reminder in reminders:
            try:
                local_now = now_utc.astimezone(zoneinfo.ZoneInfo(reminder.tz))
            except Exception:
                local_now = now_utc

            if (local_now.hour, local_now.minute) != (reminder.time.hour, reminder.time.minute):
                continue
            if reminder.last_sent is not None and reminder.last_sent.date() == local_now.date():
                continue

            user = await session.get(db.User, reminder.user_id)
            state = await db.get_state(session, reminder.user_id)
            due = topics_due_for_review(state)
            await _send(bot, user.chat_id if user else None, format_daily_reminder_text(due))
            reminder.last_sent = now_utc

        await session.commit()


async def run_streak_protection(bot: Bot) -> None:
    """Fires once a day around the evening; warns users whose streak is about to break."""
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        result = await session.execute(select(db.User))
        users = result.scalars().all()
        for user in users:
            state = await db.get_state(session, user.id)
            if is_streak_at_risk(state):
                await _send(bot, user.chat_id, format_streak_warning_text(state.get("streak", 0)))


async def run_inactivity_winback(bot: Bot) -> None:
    """Fires once a day; nudges users who haven't opened the app in INACTIVITY_THRESHOLD_DAYS."""
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        result = await session.execute(select(db.User))
        users = result.scalars().all()
        for user in users:
            state = await db.get_state(session, user.id)
            if is_inactive(state, threshold_days=config.INACTIVITY_THRESHOLD_DAYS):
                await _send(bot, user.chat_id, format_inactivity_text(state.get("lastTopic")))


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_daily_reminders, "cron", minute="*", args=[bot], id="daily_reminders")
    scheduler.add_job(
        run_streak_protection,
        "cron",
        hour=STREAK_PROTECTION_HOUR,
        minute=0,
        args=[bot],
        id="streak_protection",
    )
    scheduler.add_job(
        run_inactivity_winback,
        "cron",
        hour=INACTIVITY_CHECK_HOUR_UTC,
        minute=0,
        args=[bot],
        id="inactivity_winback",
    )
    scheduler.start()
    return scheduler
