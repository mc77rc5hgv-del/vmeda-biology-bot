"""Scheduled pushes: daily reminders, streak rescue, term of the day, win-back, weekly digest.

Runs inside the bot process (started from bot.main) since it needs the live Bot to send.

Everything that fans out to many users goes through `_broadcast`, which paces sends: Telegram
caps bulk delivery around 30 messages/second and answers overruns with 429 + retry_after. At a
few thousand students an unpaced loop would get the bot throttled within the first second.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import zoneinfo
from typing import Any, Awaitable, Callable, Iterable, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

import config
import db
import keyboards as kb
import texts
from state_logic import is_inactive, is_streak_at_risk, topics_due_for_review
from texts import (
    format_daily_reminder_text,
    format_inactivity_text,
    format_streak_warning_text,
)

logger = logging.getLogger(__name__)

STREAK_PROTECTION_HOUR_LOCAL = 20
INACTIVITY_CHECK_HOUR_UTC = 10
TERM_OF_DAY_HOUR_LOCAL = 9
DIGEST_HOUR_UTC = 9
DIGEST_WEEKDAY = 6  # Sunday (APScheduler: 0=Mon)

SEND_DELAY_SECONDS = 0.05  # ~20 msg/s, comfortably under Telegram's bulk limit


async def _send(bot: Bot, chat_id: Optional[int], text: str, **kwargs: Any) -> bool:
    if not chat_id:
        return False
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except TelegramRetryAfter as exc:
        # Respect the server's own backoff, then make one more attempt.
        await asyncio.sleep(exc.retry_after + 1)
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except Exception:
            logger.warning("Give up on chat_id=%s after retry_after", chat_id)
            return False
    except TelegramForbiddenError:
        # User blocked the bot or deleted the chat — expected at scale, not worth a traceback.
        logger.info("Chat %s is unreachable (blocked/deleted)", chat_id)
        return False
    except Exception:
        logger.exception("Failed to send to chat_id=%s", chat_id)
        return False


async def _broadcast(bot: Bot, targets: Iterable[tuple[Optional[int], str]]) -> int:
    """Fan out with the site link attached — a push is the moment a student is most likely to
    open the app, so every one of them carries the call to action."""
    markup = kb.open_app()
    sent = 0
    for chat_id, text in targets:
        if await _send(bot, chat_id, text, reply_markup=markup):
            sent += 1
        await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent


def _local_now(tz_name: Optional[str], now_utc: dt.datetime) -> dt.datetime:
    try:
        return now_utc.astimezone(zoneinfo.ZoneInfo(tz_name or "Europe/Moscow"))
    except Exception:
        return now_utc


async def _guarded(name: str, job: Callable[[], Awaitable[None]]) -> None:
    """Never let one failing job kill the scheduler thread or hide its cause."""
    try:
        await job()
    except Exception:
        logger.exception("Scheduled job %s failed", name)


# ---------------------------------------------------------------- jobs


async def run_daily_reminders(bot: Bot) -> None:
    """Every minute: send each user's reminder when their *local* clock matches their setting."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    async with db.get_session_maker()() as session:
        result = await session.execute(select(db.Reminder).where(db.Reminder.enabled.is_(True)))
        reminders = result.scalars().all()

        due_now = []
        for reminder in reminders:
            local_now = _local_now(reminder.tz, now_utc)
            if (local_now.hour, local_now.minute) != (reminder.time.hour, reminder.time.minute):
                continue
            if reminder.last_sent is not None:
                last_local = _local_now(reminder.tz, reminder.last_sent)
                if last_local.date() == local_now.date():
                    continue
            due_now.append(reminder)

        payloads: list[tuple[Optional[int], str]] = []
        for reminder in due_now:
            user = await session.get(db.User, reminder.user_id)
            state = await db.get_state(session, reminder.user_id)
            due = topics_due_for_review(state)
            payloads.append((user.chat_id if user else None, format_daily_reminder_text(len(due))))
            reminder.last_sent = now_utc
        await session.commit()

    if payloads:
        sent = await _broadcast(bot, payloads)
        logger.info("Daily reminders: %s/%s sent", sent, len(payloads))


async def run_streak_protection(bot: Bot) -> None:
    """Hourly: nudge users whose local evening arrived while their streak is still unprotected."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    payloads: list[tuple[Optional[int], str]] = []

    async with db.get_session_maker()() as session:
        for user, state in await db.list_users_with_state(session):
            prefs = user.prefs or {}
            local_now = _local_now(prefs.get("tz"), now_utc)
            if local_now.hour != STREAK_PROTECTION_HOUR_LOCAL:
                continue
            if not is_streak_at_risk(state, today=local_now.date()):
                continue
            payloads.append((user.chat_id, format_streak_warning_text(int(state.get("streak") or 0))))

    if payloads:
        sent = await _broadcast(bot, payloads)
        logger.info("Streak protection: %s/%s sent", sent, len(payloads))


async def run_term_of_the_day(bot: Bot) -> None:
    """Hourly: deliver the day's Latin term to users whose local morning just started."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    text = texts.term_of_the_day_text()
    payloads: list[tuple[Optional[int], str]] = []

    async with db.get_session_maker()() as session:
        for user, _state in await db.list_users_with_state(session):
            prefs = user.prefs or {}
            if prefs.get("term_of_day_opt_out"):
                continue
            local_now = _local_now(prefs.get("tz"), now_utc)
            if local_now.hour != TERM_OF_DAY_HOUR_LOCAL:
                continue
            payloads.append((user.chat_id, text))

    if payloads:
        sent = await _broadcast(bot, payloads)
        logger.info("Term of the day: %s/%s sent", sent, len(payloads))


async def run_inactivity_winback(bot: Bot) -> None:
    """Daily: nudge students who haven't opened the app in INACTIVITY_THRESHOLD_DAYS."""
    payloads: list[tuple[Optional[int], str]] = []
    async with db.get_session_maker()() as session:
        for user, state in await db.list_users_with_state(session):
            if is_inactive(state, threshold_days=config.INACTIVITY_THRESHOLD_DAYS):
                payloads.append((user.chat_id, format_inactivity_text(state.get("lastTopic"))))

    if payloads:
        sent = await _broadcast(bot, payloads)
        logger.info("Win-back: %s/%s sent", sent, len(payloads))


async def run_weekly_digest(bot: Bot) -> None:
    """Weekly: personal summary of the last 7 days, skipped for users with no activity."""
    payloads: list[tuple[Optional[int], str]] = []
    async with db.get_session_maker()() as session:
        for user, state in await db.list_users_with_state(session):
            if (user.prefs or {}).get("digest_opt_out"):
                continue
            name = texts.display_name(user.first_name, user.last_name, user.username)
            digest = texts.weekly_digest_text(state, name=name)
            if digest:
                payloads.append((user.chat_id, digest))

    if payloads:
        sent = await _broadcast(bot, payloads)
        logger.info("Weekly digest: %s/%s sent", sent, len(payloads))


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    def add(job_id: str, func, **trigger) -> None:
        # Must be a real `async def`: APScheduler only awaits jobs it detects as coroutine
        # functions. A plain lambda returning a coroutine is called synchronously, so the job
        # would silently never run ("coroutine was never awaited").
        async def job(_func=func, _name=job_id) -> None:
            await _guarded(_name, lambda: _func(bot))

        job.__name__ = f"job_{job_id}"
        scheduler.add_job(
            job,
            "cron",
            id=job_id,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
            **trigger,
        )

    add("daily_reminders", run_daily_reminders, minute="*")
    # Hourly so each timezone gets hit at its own local hour.
    add("streak_protection", run_streak_protection, minute=5)
    add("term_of_the_day", run_term_of_the_day, minute=10)
    add("inactivity_winback", run_inactivity_winback, hour=INACTIVITY_CHECK_HOUR_UTC, minute=15)
    add("weekly_digest", run_weekly_digest, day_of_week=DIGEST_WEEKDAY, hour=DIGEST_HOUR_UTC, minute=30)

    scheduler.start()
    logger.info("Scheduler started with %s jobs", len(scheduler.get_jobs()))
    return scheduler
