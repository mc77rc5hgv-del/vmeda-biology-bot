"""aiogram bot for @Vmeda_anatom_bot — launcher and notification channel for the АНАТОМ MiniApp.

Studying happens in the MiniApp (anatomapp.ru, opened inside Telegram). The bot deliberately does
not reimplement any of it; what it owns is the part the app cannot do for itself — putting the
launch button everywhere, reaching students who aren't currently looking at the app, and giving
admins a panel.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
import re


from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, CallbackQuery, Message

import admin
import config
import db
import keyboards as kb
import texts

logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

DEFAULT_TZ = "Europe/Moscow"
DEFAULT_REMINDER_TIME = "19:00"


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def user_display_name(event) -> str:
    user = event.from_user
    return texts.display_name(user.first_name, user.last_name, user.username)


async def register_user(message: Message) -> None:
    async with db.get_session_maker()() as session:
        await db.get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            chat_id=message.chat.id,
        )
        await session.commit()


async def safe_edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    """Edit in place, falling back to a new message when Telegram refuses the edit.

    Telegram rejects an edit whose text and markup are byte-identical to what's already shown,
    and edits fail outright on messages too old to modify. Neither should surface as an error.
    """
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await callback.message.answer(text, reply_markup=reply_markup)
        except Exception:
            logger.exception("Could not deliver screen to user %s", callback.from_user.id)


# ---------------------------------------------------------------- start & launch


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if arg:
        await _confirm_login_code(arg, message)
        return

    await register_user(message)
    # A message carries either an inline or a reply keyboard, never both, so the persistent
    # launcher is installed by its own message before the big inline button.
    await message.answer(
        texts.welcome_text(esc(user_display_name(message))),
        reply_markup=kb.reply_nav(is_admin=admin.is_admin(message.from_user.id)),
    )
    await message.answer("Нажми, чтобы начать 👇", reply_markup=kb.open_app())


async def _confirm_login_code(code: str, message: Message) -> None:
    """Deep-link login started on the website (t.me/<bot>?start=<code>).

    Still used by the browser version of the site — inside the MiniApp, Telegram identifies the
    user through initData instead (see api.auth_telegram_webapp).
    """
    async with db.get_session_maker()() as session:
        login_session = await db.find_login_session(session, code)
        if login_session is None or login_session.expires_at < dt.datetime.now(dt.timezone.utc):
            await message.answer(
                "Ссылка для входа устарела. Открой приложение заново.",
                reply_markup=kb.open_app(),
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
        await session.commit()

    await message.answer(
        "✅ Вход подтверждён!",
        reply_markup=kb.reply_nav(is_admin=admin.is_admin(message.from_user.id)),
    )
    await message.answer("Можно возвращаться в приложение 👇", reply_markup=kb.open_app())


@dp.message(Command("app", "open", "study", "menu"))
async def cmd_app(message: Message) -> None:
    await register_user(message)
    await message.answer(texts.open_app_text(), reply_markup=kb.open_app())


@dp.message(F.text == kb.NAV_ADMIN)
async def nav_admin(message: Message) -> None:
    # A reply button is just text, so anyone could type it — permission is checked here, not by
    # the keyboard that offered it.
    if not admin.is_admin(message.from_user.id):
        raise SkipHandler
    admin.ADMIN_PENDING.pop(message.from_user.id, None)
    await message.answer(ADMIN_PANEL_TITLE, reply_markup=admin.admin_menu_keyboard())


# ---------------------------------------------------------------- reminders


async def _reminder_row(user_id: int):
    async with db.get_session_maker()() as session:
        return await session.get(db.Reminder, user_id)


async def _render_reminders(target, *, edit_callback: CallbackQuery | None = None) -> None:
    user_id = (edit_callback or target).from_user.id
    reminder = await _reminder_row(user_id)
    enabled = bool(reminder and reminder.enabled)
    when = reminder.time.strftime("%H:%M") if reminder else DEFAULT_REMINDER_TIME
    tz = (reminder.tz if reminder else None) or DEFAULT_TZ

    text = texts.reminder_status_text(enabled, when, tz)
    markup = kb.reminder_keyboard(enabled)
    if edit_callback is not None:
        await safe_edit(edit_callback, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@dp.message(Command("reminder"))
async def cmd_reminder(message: Message) -> None:
    await register_user(message)
    await _render_reminders(message)


@dp.message(F.text == kb.NAV_REMINDER)
async def nav_reminder(message: Message) -> None:
    await register_user(message)
    await _render_reminders(message)


@dp.message(Command("reminder_off"))
async def cmd_reminder_off(message: Message) -> None:
    async with db.get_session_maker()() as session:
        reminder = await session.get(db.Reminder, message.from_user.id)
        if reminder is not None:
            reminder.enabled = False
        await session.commit()
    await _render_reminders(message)


@dp.callback_query(F.data == "rem:home")
async def cb_reminders_home(callback: CallbackQuery) -> None:
    await _render_reminders(callback.message, edit_callback=callback)
    await callback.answer()


@dp.callback_query(F.data == "rem:toggle")
async def cb_reminder_toggle(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        await db.get_or_create_user(session, telegram_id=user_id, chat_id=callback.message.chat.id)
        reminder = await session.get(db.Reminder, user_id)
        if reminder is None:
            reminder = db.Reminder(user_id=user_id)
            session.add(reminder)
        reminder.enabled = not reminder.enabled
        enabled = reminder.enabled
        await session.commit()

    await _render_reminders(callback.message, edit_callback=callback)
    await callback.answer("Напоминания включены" if enabled else "Напоминания выключены")


@dp.callback_query(F.data == "rem:time")
async def cb_reminder_time(callback: CallbackQuery) -> None:
    await safe_edit(
        callback,
        "⏰ Пришли время в формате <b>ЧЧ:ММ</b> — например 19:00.",
        kb.reminder_keyboard(True),
    )
    await callback.answer()


@dp.callback_query(F.data == "rem:tz")
async def cb_reminder_tz(callback: CallbackQuery) -> None:
    await safe_edit(
        callback, "🌍 Выбери часовой пояс — по нему приходят напоминания:", kb.timezone_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rem:tz:"))
async def cb_reminder_tz_pick(callback: CallbackQuery) -> None:
    tz = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        await db.get_or_create_user(session, telegram_id=user_id, chat_id=callback.message.chat.id)
        reminder = await session.get(db.Reminder, user_id)
        if reminder is None:
            reminder = db.Reminder(user_id=user_id)
            session.add(reminder)
        reminder.tz = tz
        await db.update_prefs(session, user_id, tz=tz)
        await session.commit()

    await _render_reminders(callback.message, edit_callback=callback)
    await callback.answer(f"Часовой пояс: {tz}")


# ---------------------------------------------------------------- admin


ADMIN_PANEL_TITLE = "⚙️ <b>Админ-панель</b>\n\nВыбери действие:"


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not admin.is_admin(message.from_user.id):
        return
    await message.answer(ADMIN_PANEL_TITLE, reply_markup=kb.reply_nav(is_admin=True))
    await message.answer("Действия:", reply_markup=admin.admin_menu_keyboard())


async def _guard_admin(callback: CallbackQuery) -> bool:
    if not admin.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return False
    # Any panel tap ends whatever input the panel was waiting for, so a half-finished lookup
    # can't swallow the admin's next unrelated message. Handlers needing input set it again
    # right after this guard; drafts are left alone so the confirm button still works.
    admin.ADMIN_PENDING.pop(callback.from_user.id, None)
    return True


@dp.callback_query(F.data == "admin_home")
async def cb_admin_home(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    admin.ADMIN_DRAFTS.pop(callback.from_user.id, None)
    await safe_edit(callback, ADMIN_PANEL_TITLE, admin.admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    async with db.get_session_maker()() as session:
        text = await admin.build_stats_text(session)
    await safe_edit(callback, text, admin.admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_top")
async def cb_admin_top(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    async with db.get_session_maker()() as session:
        text = await admin.build_top_text(session)
    await safe_edit(callback, text, admin.admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_recent")
async def cb_admin_recent(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    async with db.get_session_maker()() as session:
        text = await admin.build_recent_text(session)
    await safe_edit(callback, text, admin.admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data.in_({"admin_broadcast", "admin_broadcast_inactive"}))
async def cb_admin_broadcast(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    cohort = "inactive" if callback.data.endswith("inactive") else "all"
    admin.ADMIN_PENDING[callback.from_user.id] = {"action": "broadcast", "cohort": cohort}

    async with db.get_session_maker()() as session:
        recipients = len(await admin.cohort_chat_ids(session, cohort))

    audience = f"спящим ({admin.INACTIVE_DAYS}+ дней без занятий)" if cohort == "inactive" else "всем"
    await safe_edit(
        callback,
        f"📢 Рассылка {audience}\nПолучателей сейчас: <b>{recipients}</b>\n\n"
        "Пришли текст сообщения — покажу предпросмотр перед отправкой.",
        admin.admin_menu_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_bc_go:"))
async def cb_admin_broadcast_go(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return

    draft = admin.ADMIN_DRAFTS.pop(callback.from_user.id, None)
    if not draft:
        await callback.answer("Черновик устарел — начни заново", show_alert=True)
        await safe_edit(callback, ADMIN_PANEL_TITLE, admin.admin_menu_keyboard())
        return

    await callback.answer("Отправляю…")
    await safe_edit(callback, "📢 Рассылка идёт, это может занять пару минут…", None)

    async with db.get_session_maker()() as session:
        sent, failed = await admin.broadcast_text(bot, session, draft["text"], draft["cohort"])

    await callback.message.answer(
        f"✅ Рассылка завершена\n\nДоставлено: <b>{sent}</b>\nНе доставлено: {failed}"
        + ("\n\n<i>Недоставленные — те, кто заблокировал бота.</i>" if failed else ""),
        reply_markup=admin.admin_menu_keyboard(),
    )


@dp.callback_query(F.data == "admin_lookup")
async def cb_admin_lookup(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    admin.ADMIN_PENDING[callback.from_user.id] = {"action": "lookup"}
    await safe_edit(
        callback,
        "🔍 <b>Поиск пользователя</b>\n\n"
        "Пришли <b>@username</b> или числовой <b>ID</b>.\n\n"
        "<i>Если точного совпадения не будет — покажу похожих.</i>",
        admin.admin_menu_keyboard(),
    )
    await callback.answer()


# ---------------------------------------------------------------- help & free text


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.help_text(config.SUPPORT_URL), reply_markup=kb.open_app())


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


async def _apply_reminder_time(user_id: int, chat_id: int, hour: int, minute: int) -> None:
    async with db.get_session_maker()() as session:
        await db.get_or_create_user(session, telegram_id=user_id, chat_id=chat_id)
        reminder = await session.get(db.Reminder, user_id)
        if reminder is None:
            reminder = db.Reminder(user_id=user_id)
            session.add(reminder)
        reminder.enabled = True
        reminder.time = dt.time(hour, minute)
        await session.commit()


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    user_id = message.from_user.id

    # 1. Admin input first, so an admin isn't hijacked by their own pending prompt.
    if admin.is_admin(user_id) and user_id in admin.ADMIN_PENDING:
        pending = admin.ADMIN_PENDING.pop(user_id)
        action = pending.get("action")

        if action == "broadcast":
            cohort = pending.get("cohort", "all")
            async with db.get_session_maker()() as session:
                recipients = len(await admin.cohort_chat_ids(session, cohort))
            # Never send straight from the compose step: at this scale a mistyped or
            # half-finished message would reach thousands of people irreversibly.
            admin.ADMIN_DRAFTS[user_id] = {"text": message.text, "cohort": cohort}
            await message.answer(
                admin.broadcast_preview_text(message.text, cohort, recipients),
                reply_markup=admin.broadcast_confirm_keyboard(cohort, recipients),
            )
        elif action == "lookup":
            async with db.get_session_maker()() as session:
                text = await admin.build_lookup_result_text(session, message.text.strip())
            # Keep the prompt open: after a candidate list the admin usually looks one of them up.
            admin.ADMIN_PENDING[user_id] = {"action": "lookup"}
            await message.answer(text, reply_markup=admin.admin_menu_keyboard())
        return

    # 2. A bare HH:MM always means "set my reminder".
    match = _TIME_RE.match(message.text.strip())
    if match:
        await _apply_reminder_time(user_id, message.chat.id, int(match.group(1)), int(match.group(2)))
        await _render_reminders(message)
        return

    # 3. Anything else: the bot isn't where studying happens — point at the app.
    await message.answer(
        "Всё обучение — в приложении 👇\n\n"
        "<i>Поиск тем, тесты и карточки внутри него. "
        "А здесь можно настроить напоминания: /reminder</i>",
        reply_markup=kb.open_app(),
    )


# ---------------------------------------------------------------- startup


BOT_COMMANDS = [
    BotCommand(command="app", description="🚀 Открыть АНАТОМ"),
    BotCommand(command="reminder", description="⏰ Напоминания о занятиях"),
    BotCommand(command="help", description="❓ Справка"),
]


async def setup_bot_menu() -> None:
    """Point the ☰ button at the MiniApp and publish the short command list.

    The menu button is the most visible launcher Telegram offers, so it opens the app directly
    rather than listing commands. Best-effort: a transient API error must not stop startup.
    """
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=kb.menu_button())
        logger.info("Menu button points at the MiniApp; %s commands published", len(BOT_COMMANDS))
    except Exception:
        logger.exception("Could not configure the bot menu")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await db.init_models()
    from scheduler import start_scheduler

    start_scheduler(bot)
    await setup_bot_menu()
    logger.info("anatom-bot starting; MiniApp at %s", config.WEBAPP_URL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
