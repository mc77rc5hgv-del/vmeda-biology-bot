"""aiogram bot: /start /study /progress /review /streak /reminder /help.

Talks to Postgres directly through db.py (same DB as the FastAPI process in api.py).
"""

from __future__ import annotations

import datetime as dt
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from state_logic import (
    format_daily_reminder_text,
    format_streak_warning_text,
    topics_due_for_review,
)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


def webapp_keyboard(text: str = "Открыть АНАТОМ") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=config.WEBAPP_URL)]])


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    code = command.args
    if code:
        await _confirm_login_code(code, message)
        return

    await message.answer(
        "👋 Привет! Я бот АНАТОМ — вход и напоминания для веб-приложения по нормальной анатомии.\n\n"
        "Учёба, тесты и атлас — на сайте. Здесь ты найдёшь быструю сводку прогресса и напоминания "
        "о повторении.",
        reply_markup=webapp_keyboard(),
    )


async def _confirm_login_code(code: str, message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            login_session = await db.find_login_session(session, code)
            if login_session is None or login_session.expires_at < dt.datetime.now(dt.timezone.utc):
                await message.answer(
                    "Ссылка для входа устарела. Вернись на сайт и запроси новую кнопку входа через Telegram."
                )
                return

            await db.get_or_create_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                chat_id=message.chat.id,
            )
            login_session.status = "confirmed"
            login_session.user_id = message.from_user.id

    await message.answer(
        "✅ Вход подтверждён! Возвращайся на сайт — там уже подхватится твой аккаунт.",
        reply_markup=webapp_keyboard(),
    )


@dp.message(Command("study"))
async def cmd_study(message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        state = await db.get_state(session, message.from_user.id)
    due = topics_due_for_review(state)
    await message.answer(
        f"сегодня к повторению: {due} {_topics_word(due)}",
        reply_markup=webapp_keyboard(),
    )


@dp.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        state = await db.get_state(session, message.from_user.id)

    xp = state.get("xp", 0)
    streak = state.get("streak", 0)
    progress = state.get("progress") or {}
    passed = sum(
        1 for entry in progress.values() if isinstance(entry, dict) and (entry.get("percent") or 0) >= 90
    )
    accuracies = [
        entry.get("accuracy")
        for entry in progress.values()
        if isinstance(entry, dict) and isinstance(entry.get("accuracy"), (int, float))
    ]
    avg_accuracy = round(sum(accuracies) / len(accuracies), 1) if accuracies else None

    lines = [
        "📊 Твой прогресс",
        f"XP: {xp}",
        f"Серия: {streak} 🔥",
        f"Сдано тем: {passed}",
    ]
    if avg_accuracy is not None:
        lines.append(f"Средняя точность: {avg_accuracy}%")
    await message.answer("\n".join(lines), reply_markup=webapp_keyboard())


@dp.message(Command("review"))
async def cmd_review(message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        state = await db.get_state(session, message.from_user.id)
    due = topics_due_for_review(state)
    await message.answer(format_daily_reminder_text(due), reply_markup=webapp_keyboard())


@dp.message(Command("streak"))
async def cmd_streak(message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        state = await db.get_state(session, message.from_user.id)

    streak = state.get("streak", 0)
    text = f"🔥 Текущая серия: {streak} {_days_word(streak)}"
    if streak and not state.get("dayDone", False):
        text += f"\n\n{format_streak_warning_text(streak)}"
    await message.answer(text, reply_markup=webapp_keyboard())


@dp.message(Command("reminder"))
async def cmd_reminder(message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        reminder = await session.get(db.Reminder, message.from_user.id)

    if reminder is None or not reminder.enabled:
        await message.answer(
            "🔕 Напоминания сейчас выключены.\n\n"
            "Отправь время в формате ЧЧ:ММ (например 19:00), чтобы включить ежедневное напоминание."
        )
    else:
        await message.answer(
            f"🔔 Напоминания включены на {reminder.time.strftime('%H:%M')} ({reminder.tz}).\n\n"
            "Отправь новое время ЧЧ:ММ, чтобы изменить, или /reminder_off, чтобы выключить."
        )


@dp.message(Command("reminder_off"))
async def cmd_reminder_off(message: Message) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            reminder = await session.get(db.Reminder, message.from_user.id)
            if reminder is not None:
                reminder.enabled = False
    await message.answer("🔕 Напоминания выключены.")


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dp.message(F.text.regexp(_TIME_RE.pattern))
async def set_reminder_time(message: Message) -> None:
    match = _TIME_RE.match(message.text.strip())
    if not match:
        return
    hour, minute = int(match.group(1)), int(match.group(2))

    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            reminder = await session.get(db.Reminder, message.from_user.id)
            if reminder is None:
                await db.get_or_create_user(
                    session,
                    telegram_id=message.from_user.id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    chat_id=message.chat.id,
                )
                reminder = await session.get(db.Reminder, message.from_user.id)
            reminder.enabled = True
            reminder.time = dt.time(hour, minute)

    await message.answer(f"✅ Готово! Буду напоминать каждый день в {hour:02d}:{minute:02d}.")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — открыть АНАТОМ\n"
        "/study — сколько тем ждут повторения\n"
        "/progress — уровень, XP, серия, точность\n"
        "/review — темы к интервальному повторению\n"
        "/streak — текущая серия дней\n"
        "/reminder — настроить ежедневное напоминание\n"
        f"/help — эта справка\n\nПоддержка: {config.SUPPORT_URL}"
    )


def _topics_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "тема"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "темы"
    return "тем"


def _days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


async def main() -> None:
    await db.init_models()
    from scheduler import start_scheduler

    start_scheduler(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
