"""aiogram bot: rich menu mirroring anatomapp.ru's course structure + admin panel.

Talks to Postgres directly through db.py (same DB as the FastAPI process in api.py).
"""

from __future__ import annotations

import datetime as dt
import re

from aiogram import Bot, Dispatcher, F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import admin
import config
import db
from modules import MODULES_BY_ID
from state_logic import (
    favorite_labels,
    format_streak_warning_text,
    module_progress,
    section_progress,
    topics_due_for_review,
)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

WEBAPP_BUTTON_TEXT = "🌐 Открыть АНАТОМ"


def webapp_keyboard(text: str = WEBAPP_BUTTON_TEXT) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=config.WEBAPP_URL)]])


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📚 Модули", callback_data="menu:modules"),
                InlineKeyboardButton(text="📊 Прогресс", callback_data="menu:progress"),
            ],
            [
                InlineKeyboardButton(text="🔁 Повторить", callback_data="menu:review"),
                InlineKeyboardButton(text="⭐ Избранное", callback_data="menu:favorites"),
            ],
            [
                InlineKeyboardButton(text="🔥 Серия", callback_data="menu:streak"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
            ],
            [InlineKeyboardButton(text=WEBAPP_BUTTON_TEXT, url=config.WEBAPP_URL)],
        ]
    )


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")]]
    )


def modules_list_keyboard(state: dict) -> InlineKeyboardMarkup:
    rows = []
    for row in module_progress(state):
        text = f"{row['icon']} {row['title']} — {row['passed']}/{row['total']} ({row['pct']}%)"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"menu:module:{row['id']}")])
    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    code = command.args
    if code:
        await _confirm_login_code(code, message)
        return

    await message.answer(
        "👋 Привет! Я бот АНАТОМ — вход и напоминания для веб-приложения по нормальной анатомии.\n\n"
        "Учёба, тесты и атлас — на сайте. Здесь ты найдёшь прогресс по модулям, темы к повторению, "
        "избранное и напоминания.",
        reply_markup=main_menu_keyboard(),
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


@dp.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())


async def _get_state_for(user_id: int) -> dict:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        return await db.get_state(session, user_id)


def _modules_overview_text() -> str:
    return "📚 Модули курса — нажми на модуль, чтобы увидеть разбивку по разделам:"


def _module_detail_text(module_id: str, state: dict) -> str:
    module = MODULES_BY_ID.get(module_id)
    title = module.title if module else module_id
    icon = module.icon if module else ""
    lines = [f"{icon} {title}"]
    sections = section_progress(state, module_id)
    if not sections:
        lines.append("Разделы для этого модуля пока не описаны.")
    for sec in sections:
        lines.append(f"{sec['icon']} {sec['name']} — {sec['passed']}/{sec['total']} ({sec['pct']}%)")
    return "\n".join(lines)


def _progress_text(state: dict) -> str:
    xp = state.get("xp", 0)
    streak = state.get("streak", 0)
    day_done = state.get("dayDone", 0)
    day_goal = state.get("dayGoal", 20)

    lines = ["📊 Твой прогресс", f"XP: {xp}", f"Серия: {streak} 🔥", f"Сегодня: {day_done}/{day_goal}", ""]
    total_passed = total_topics = 0
    for row in module_progress(state):
        lines.append(f"{row['icon']} {row['title']}: {row['passed']}/{row['total']} ({row['pct']}%)")
        total_passed += row["passed"]
        total_topics += row["total"]
    if total_topics:
        overall_pct = round(total_passed / total_topics * 100)
        lines.append("")
        lines.append(f"Итого по курсу: {total_passed}/{total_topics} ({overall_pct}%)")
    return "\n".join(lines)


def _review_text(state: dict) -> str:
    due = topics_due_for_review(state)
    if not due:
        return "🔁 Сейчас нет тем к повторению — всё свежее! Загляни позже."
    lines = [f"🔁 К повторению: {len(due)} {_topics_word(len(due))}", ""]
    for entry in due[:10]:
        overdue = entry["overdue_days"]
        overdue_text = f" (просрочено {overdue} дн.)" if overdue > 0 else ""
        lines.append(f"• {entry['label']}{overdue_text}")
    if len(due) > 10:
        lines.append(f"…и ещё {len(due) - 10}")
    return "\n".join(lines)


def _favorites_text(state: dict) -> str:
    labels = favorite_labels(state)
    if not labels:
        return "⭐ Пока нет избранных тем — отмечай их звёздочкой на сайте."
    lines = ["⭐ Избранные темы:", ""]
    lines.extend(f"• {label}" for label in labels[:20])
    if len(labels) > 20:
        lines.append(f"…и ещё {len(labels) - 20}")
    return "\n".join(lines)


def _streak_text(state: dict) -> str:
    streak = state.get("streak", 0)
    day_done = state.get("dayDone", 0)
    day_goal = state.get("dayGoal", 20)
    text = f"🔥 Текущая серия: {streak} {_days_word(streak)}\nСегодня пройдено: {day_done}/{day_goal}"
    if streak and day_done < day_goal:
        text += f"\n\n{format_streak_warning_text(streak)}"
    return text


async def _settings_keyboard(user_id: int, state: dict) -> InlineKeyboardMarkup:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        reminder = await session.get(db.Reminder, user_id)
    reminder_on = bool(reminder and reminder.enabled)
    term_lang = state.get("termLang", "ru")

    rows = [
        [
            InlineKeyboardButton(
                text=f"🔔 Напоминания: {'вкл' if reminder_on else 'выкл'}",
                callback_data="menu:toggle_reminders",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🌐 Язык терминов: {term_lang.upper()}",
                callback_data="menu:toggle_termlang",
            )
        ],
        [InlineKeyboardButton(text="⬅ В меню", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _settings_text(reminder_on: bool) -> str:
    if reminder_on:
        return "⚙️ Настройки\n\nНапоминания включены. Чтобы изменить время, отправь ЧЧ:ММ следующим сообщением."
    return "⚙️ Настройки\n\nЧтобы включить ежедневное напоминание, отправь время в формате ЧЧ:ММ (например 19:00)."


@dp.callback_query(F.data == "menu:home")
async def cb_menu_home(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "menu:modules")
async def cb_menu_modules(callback: CallbackQuery) -> None:
    state = await _get_state_for(callback.from_user.id)
    await callback.message.edit_text(_modules_overview_text(), reply_markup=modules_list_keyboard(state))
    await callback.answer()


@dp.callback_query(F.data.startswith("menu:module:"))
async def cb_menu_module_detail(callback: CallbackQuery) -> None:
    module_id = callback.data.removeprefix("menu:module:")
    state = await _get_state_for(callback.from_user.id)
    await callback.message.edit_text(
        _module_detail_text(module_id, state),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅ К модулям", callback_data="menu:modules")],
                [InlineKeyboardButton(text=WEBAPP_BUTTON_TEXT, url=config.WEBAPP_URL)],
            ]
        ),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:progress")
async def cb_menu_progress(callback: CallbackQuery) -> None:
    state = await _get_state_for(callback.from_user.id)
    await callback.message.edit_text(_progress_text(state), reply_markup=back_to_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "menu:review")
async def cb_menu_review(callback: CallbackQuery) -> None:
    state = await _get_state_for(callback.from_user.id)
    await callback.message.edit_text(_review_text(state), reply_markup=back_to_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "menu:favorites")
async def cb_menu_favorites(callback: CallbackQuery) -> None:
    state = await _get_state_for(callback.from_user.id)
    await callback.message.edit_text(_favorites_text(state), reply_markup=back_to_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "menu:streak")
async def cb_menu_streak(callback: CallbackQuery) -> None:
    state = await _get_state_for(callback.from_user.id)
    await callback.message.edit_text(_streak_text(state), reply_markup=back_to_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    state = await _get_state_for(callback.from_user.id)
    keyboard = await _settings_keyboard(callback.from_user.id, state)
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        reminder = await session.get(db.Reminder, callback.from_user.id)
    await callback.message.edit_text(
        _settings_text(bool(reminder and reminder.enabled)), reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:toggle_reminders")
async def cb_toggle_reminders(callback: CallbackQuery) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            reminder = await session.get(db.Reminder, callback.from_user.id)
            if reminder is None:
                await db.get_or_create_user(
                    session,
                    telegram_id=callback.from_user.id,
                    username=callback.from_user.username,
                    first_name=callback.from_user.first_name,
                    chat_id=callback.message.chat.id,
                )
                reminder = await session.get(db.Reminder, callback.from_user.id)
            reminder.enabled = not reminder.enabled
            new_state = reminder.enabled

    state = await _get_state_for(callback.from_user.id)
    keyboard = await _settings_keyboard(callback.from_user.id, state)
    await callback.message.edit_text(_settings_text(new_state), reply_markup=keyboard)
    await callback.answer("Напоминания включены" if new_state else "Напоминания выключены")


@dp.callback_query(F.data == "menu:toggle_termlang")
async def cb_toggle_termlang(callback: CallbackQuery) -> None:
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        # Read autobegins the transaction — no session.begin() here (see api.put_state).
        state = await db.get_state(session, callback.from_user.id)
        state["termLang"] = "en" if state.get("termLang", "ru") == "ru" else "ru"
        await db.get_or_create_user(session, telegram_id=callback.from_user.id)
        await db.put_state(session, callback.from_user.id, state)
        reminder = await session.get(db.Reminder, callback.from_user.id)
        reminder_on = bool(reminder and reminder.enabled)
        await session.commit()

    keyboard = await _settings_keyboard(callback.from_user.id, state)
    await callback.message.edit_text(_settings_text(reminder_on), reply_markup=keyboard)
    await callback.answer(f"Язык терминов: {state['termLang'].upper()}")


@dp.message(Command("study"))
async def cmd_study(message: Message) -> None:
    state = await _get_state_for(message.from_user.id)
    due = topics_due_for_review(state)
    await message.answer(
        f"сегодня к повторению: {len(due)} {_topics_word(len(due))}",
        reply_markup=main_menu_keyboard(),
    )


@dp.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    state = await _get_state_for(message.from_user.id)
    await message.answer(_progress_text(state), reply_markup=main_menu_keyboard())


@dp.message(Command("review"))
async def cmd_review(message: Message) -> None:
    state = await _get_state_for(message.from_user.id)
    await message.answer(_review_text(state), reply_markup=main_menu_keyboard())


@dp.message(Command("streak"))
async def cmd_streak(message: Message) -> None:
    state = await _get_state_for(message.from_user.id)
    await message.answer(_streak_text(state), reply_markup=main_menu_keyboard())


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


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not admin.is_admin(message.from_user.id):
        return
    await message.answer("⚙️ Админ-панель", reply_markup=admin.admin_menu_keyboard())


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery) -> None:
    if not admin.is_admin(callback.from_user.id):
        await callback.answer()
        return
    session_maker = db.get_session_maker()
    async with session_maker() as session:
        text = await admin.build_stats_text(session)
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery) -> None:
    if not admin.is_admin(callback.from_user.id):
        await callback.answer()
        return
    admin.ADMIN_PENDING[callback.from_user.id] = "broadcast"
    await callback.message.answer("Пришлите текст рассылки следующим сообщением.")
    await callback.answer()


@dp.callback_query(F.data == "admin_lookup")
async def cb_admin_lookup(callback: CallbackQuery) -> None:
    if not admin.is_admin(callback.from_user.id):
        await callback.answer()
        return
    admin.ADMIN_PENDING[callback.from_user.id] = "lookup"
    await callback.message.answer("Пришлите Telegram ID пользователя.")
    await callback.answer()


@dp.message(F.text)
async def handle_admin_pending(message: Message) -> None:
    user_id = message.from_user.id
    if not admin.is_admin(user_id) or user_id not in admin.ADMIN_PENDING:
        raise SkipHandler

    action = admin.ADMIN_PENDING.pop(user_id)
    session_maker = db.get_session_maker()

    if action == "broadcast":
        async with session_maker() as session:
            sent, failed = await admin.broadcast_text(bot, session, message.text)
        await message.answer(f"Разослано: {sent}, ошибок: {failed}")
    elif action == "lookup":
        target_raw = message.text.strip()
        if not target_raw.isdigit():
            await message.answer("ID должен быть числом.")
            return
        async with session_maker() as session:
            text = await admin.build_user_summary_text(session, int(target_raw))
        await message.answer(text)


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
        "/start — открыть меню\n"
        "/menu — главное меню (модули, прогресс, повторение, избранное, настройки)\n"
        "/study — сколько тем ждут повторения\n"
        "/progress — прогресс по модулям, XP, серия\n"
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
