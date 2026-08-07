"""aiogram bot for @Vmeda_anatom_bot — study, progress and motivation for anatomapp.ru.

Talks to Postgres directly through db.py (same database as the FastAPI process in api.py), and
writes study results into the *same* state blob the website uses, so progress made here shows up
there and vice versa.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
import re
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    MenuButtonCommands,
    Message,
)

import achievements
import admin
import config
import content
import db
import keyboards as kb
import quiz
import texts
from modules import MODULES_BY_ID, PASS_THRESHOLD
from progress import apply_session_result
from state_logic import favorite_labels, module_progress, section_progress, topics_due_for_review

logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Free-text prompts awaiting the user's next message: user_id -> {"kind": ..., ...}
PENDING_INPUT: dict[int, dict[str, Any]] = {}


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


# ---------------------------------------------------------------- helpers


async def load_state(user_id: int) -> dict[str, Any]:
    async with db.get_session_maker()() as session:
        return await db.get_state(session, user_id)


async def load_state_and_prefs(user_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    async with db.get_session_maker()() as session:
        return await db.get_state(session, user_id), await db.get_prefs(session, user_id)


async def save_state(user_id: int, state: dict[str, Any]) -> None:
    async with db.get_session_maker()() as session:
        await db.get_or_create_user(session, telegram_id=user_id)
        await db.put_state(session, user_id, state)
        await session.commit()


async def register_user(message: Message, **extra: Any) -> None:
    async with db.get_session_maker()() as session:
        await db.get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            chat_id=message.chat.id,
            **extra,
        )
        await session.commit()


async def safe_edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    """Edit in place, falling back to a new message when Telegram refuses the edit.

    Telegram rejects an edit whose text and markup are byte-identical to what's already shown
    (common when a user re-taps the same menu button), and edits fail outright on messages the
    bot can no longer modify. Neither should surface as an error to the student.
    """
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await callback.message.answer(text, reply_markup=reply_markup)
        except Exception:
            logger.exception("Could not deliver screen to user %s", callback.from_user.id)


def passed_keys(state: dict[str, Any]) -> set[str]:
    return {
        key
        for key, entry in (state.get("progress") or {}).items()
        if isinstance(entry, dict) and (entry.get("bestPct") or 0) >= PASS_THRESHOLD
    }


def user_display_name(message_or_cb) -> str:
    user = message_or_cb.from_user
    return texts.display_name(user.first_name, user.last_name, user.username)


# ---------------------------------------------------------------- /start & deep links


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()

    if arg.startswith("ref"):
        await _handle_referral(message, arg[3:])
    elif arg:
        await _confirm_login_code(arg, message)
        return
    else:
        await register_user(message)

    # A message carries either the inline keyboard or the reply keyboard, never both, so the
    # persistent navigation is installed by its own short message first.
    await message.answer(
        f"👋 Привет, {esc(user_display_name(message))}!\n\n"
        "Я бот <b>АНАТОМ</b> — учись прямо здесь: тесты, флеш-карточки и латинские термины "
        "по всему курсу нормальной анатомии. Прогресс общий с сайтом: где бы ты ни занимался, "
        "XP, серия и повторения синхронизируются.",
        reply_markup=kb.reply_nav(is_admin=admin.is_admin(message.from_user.id)),
    )
    await message.answer("Выбери, с чего начать:", reply_markup=kb.main_menu())


async def _handle_referral(message: Message, raw_id: str) -> None:
    inviter_id: Optional[int] = None
    if raw_id.isdigit():
        inviter_id = int(raw_id)

    await register_user(message)
    if not inviter_id or inviter_id == message.from_user.id:
        return

    async with db.get_session_maker()() as session:
        prefs = await db.get_prefs(session, message.from_user.id)
        # First inviter wins, and only for someone who hasn't studied here before — otherwise
        # an existing student could be "claimed" by re-opening someone's link.
        if prefs.get("referred_by"):
            return
        state = await db.get_state(session, message.from_user.id)
        if int(state.get("xp") or 0) > 0:
            return
        inviter = await session.get(db.User, inviter_id)
        if inviter is None:
            return
        await db.update_prefs(session, message.from_user.id, referred_by=str(inviter_id))
        count = await db.count_referrals(session, inviter_id)
        inviter_chat = inviter.chat_id
        await session.commit()

    if inviter_chat:
        try:
            await bot.send_message(
                inviter_chat,
                f"🤝 По твоей ссылке присоединился новый студент! Всего приглашено: {count}",
            )
        except Exception:
            logger.info("Could not notify inviter %s", inviter_id)


async def _confirm_login_code(code: str, message: Message) -> None:
    async with db.get_session_maker()() as session:
        login_session = await db.find_login_session(session, code)
        if login_session is None or login_session.expires_at < dt.datetime.now(dt.timezone.utc):
            await message.answer(
                "Ссылка для входа устарела. Вернись на сайт и запроси новую кнопку входа через Telegram.",
                reply_markup=kb.webapp_keyboard(),
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
        "✅ Вход подтверждён! Возвращайся на сайт — там уже подхватится твой аккаунт.",
        reply_markup=kb.main_menu(),
    )


# ---------------------------------------------------------------- navigation


@dp.callback_query(F.data == "menu:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@dp.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery) -> None:
    quiz.end_session(callback.from_user.id)
    PENDING_INPUT.pop(callback.from_user.id, None)
    await safe_edit(callback, "🏠 <b>Главное меню</b>\n\nВыбери раздел:", kb.main_menu())
    await callback.answer()


@dp.callback_query(F.data == "menu:learn")
async def cb_learn(callback: CallbackQuery) -> None:
    await safe_edit(
        callback,
        texts.course_overview_text() + "\n\nВыбери модуль или режим:",
        kb.learn_menu_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("menu:module:"))
async def cb_module(callback: CallbackQuery) -> None:
    module_id = callback.data.split(":")[2]
    state = await load_state(callback.from_user.id)
    module = MODULES_BY_ID.get(module_id)
    if module is None:
        await callback.answer("Модуль не найден")
        return

    lines = [f"{module.icon} <b>{esc(module.title)}</b>", ""]
    for section in section_progress(state, module_id):
        lines.append(
            f"{section['icon']} {esc(section['name'])} — {section['passed']}/{section['total']} "
            f"({section['pct']}%)"
        )
    lines += ["", f"Тем в модуле: {len(content.topics_of(module_id))}"]
    await safe_edit(callback, "\n".join(lines), kb.module_actions_keyboard(module_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("menu:topics:"))
async def cb_topics(callback: CallbackQuery) -> None:
    _, _, module_id, page_raw = callback.data.split(":")
    page = int(page_raw)
    state = await load_state(callback.from_user.id)
    topics = content.topics_of(module_id)
    module = MODULES_BY_ID.get(module_id)
    title = module.title if module else module_id

    await safe_edit(
        callback,
        f"📋 <b>{esc(title)}</b> — выбери тему\n(✅ отмечены сданные)",
        kb.topics_keyboard(module_id, topics, page, passed_keys(state)),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("menu:topic:"))
async def cb_topic(callback: CallbackQuery) -> None:
    _, _, module_id, num_raw = callback.data.split(":")
    topic_num = int(num_raw)
    topic = content.get_topic(module_id, topic_num)
    if topic is None:
        await callback.answer("Тема не найдена")
        return

    state = await load_state(callback.from_user.id)
    entry = (state.get("progress") or {}).get(f"{module_id}:{topic_num}") or {}
    best = entry.get("bestPct") or 0

    lines = [f"<b>{esc(topic.get('name', ''))}</b>"]
    if topic.get("lat"):
        lines.append(f"<i>{esc(topic['lat'])}</i>")
    lines += [
        "",
        f"🃏 Карточек: {len(topic.get('cards', []))}",
        f"🏛 Терминов: {len(topic.get('pairs', []))}",
        f"📝 Вопросов: {len(topic.get('tests', []))}",
    ]
    if entry:
        status = "✅ сдана" if best >= PASS_THRESHOLD else "📖 в процессе"
        lines += ["", f"Твой результат: {best}% — {status}"]
    await safe_edit(callback, "\n".join(lines), kb.topic_actions_keyboard(module_id, topic_num))
    await callback.answer()


@dp.callback_query(F.data == "menu:progress")
async def cb_progress(callback: CallbackQuery) -> None:
    state = await load_state(callback.from_user.id)
    await safe_edit(
        callback,
        _progress_text(state),
        kb.back_home([[InlineKeyboardButton(text="📈 Подробная статистика", callback_data="menu:stats")]]),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:stats")
async def cb_stats(callback: CallbackQuery) -> None:
    state = await load_state(callback.from_user.id)
    await safe_edit(callback, texts.stats_text(state), kb.back_home())
    await callback.answer()


@dp.callback_query(F.data == "menu:profile")
async def cb_profile(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        state = await db.get_state(session, user_id)
        prefs = await db.get_prefs(session, user_id)
        referrals = await db.count_referrals(session, user_id)

    await safe_edit(
        callback,
        texts.profile_text(state, prefs, name=esc(user_display_name(callback)), referrals=referrals),
        kb.back_home(
            [
                [InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:badges")],
                [InlineKeyboardButton(text="⭐ Избранное", callback_data="menu:favorites")],
            ]
        ),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:badges")
async def cb_badges(callback: CallbackQuery) -> None:
    state = await load_state(callback.from_user.id)
    await safe_edit(callback, achievements.format_badges_text(state), kb.back_home())
    await callback.answer()


@dp.callback_query(F.data == "menu:favorites")
async def cb_favorites(callback: CallbackQuery) -> None:
    state = await load_state(callback.from_user.id)
    labels = favorite_labels(state)
    if not labels:
        text = "⭐ Пока нет избранных тем — отмечай их звёздочкой на сайте, они появятся здесь."
    else:
        shown = [f"• {esc(label)}" for label in labels[:20]]
        text = "⭐ <b>Избранные темы</b>\n\n" + "\n".join(shown)
        if len(labels) > 20:
            text += f"\n…и ещё {len(labels) - 20}"
    await safe_edit(callback, text, kb.back_home())
    await callback.answer()


@dp.callback_query(F.data == "menu:leaderboard")
async def cb_leaderboard(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        top = await db.top_users_by_xp(session, limit=texts.MAX_LEADERBOARD_ROWS)
        rank, xp, total = await db.user_rank_by_xp(session, user_id)

    await safe_edit(callback, texts.leaderboard_text(top, rank, xp, total, user_id), kb.back_home())
    await callback.answer()


@dp.callback_query(F.data == "menu:term")
async def cb_term(callback: CallbackQuery) -> None:
    await safe_edit(callback, texts.term_of_the_day_text(), kb.back_home())
    await callback.answer()


@dp.callback_query(F.data == "menu:review")
async def cb_review(callback: CallbackQuery) -> None:
    state = await load_state(callback.from_user.id)
    due = topics_due_for_review(state)
    await safe_edit(callback, _review_text(due), kb.review_keyboard(bool(due)))
    await callback.answer()


@dp.callback_query(F.data == "menu:exam")
async def cb_exam(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    state, prefs = await load_state_and_prefs(user_id)
    PENDING_INPUT[user_id] = {"kind": "exam_date"}
    await safe_edit(
        callback,
        texts.exam_plan_text(prefs, state)
        + "\n\n<i>Отправь дату сообщением (ДД.ММ.ГГГГ), чтобы задать или изменить её.</i>",
        kb.back_home(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:search")
async def cb_search(callback: CallbackQuery) -> None:
    PENDING_INPUT[callback.from_user.id] = {"kind": "search"}
    await safe_edit(
        callback,
        "🔍 <b>Поиск темы</b>\n\nОтправь название или латинский термин — например «череп», "
        "«сердце», «cranium».",
        kb.back_home(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:invite")
async def cb_invite(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        referrals = await db.count_referrals(session, user_id)

    link = f"https://t.me/{config.BOT_USERNAME}?start=ref{user_id}"
    await safe_edit(
        callback,
        "🤝 <b>Пригласи однокурсников</b>\n\n"
        "Учиться вместе проще: делись ссылкой, следите за прогрессом друг друга в рейтинге.\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Уже присоединилось: <b>{referrals}</b>",
        kb.back_home(),
    )
    await callback.answer()


# ---------------------------------------------------------------- settings


async def _render_settings(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        state = await db.get_state(session, user_id)
        prefs = await db.get_prefs(session, user_id)
        reminder = await session.get(db.Reminder, user_id)

    reminder_on = bool(reminder and reminder.enabled)
    when = reminder.time.strftime("%H:%M") if reminder else "19:00"
    tz = (reminder.tz if reminder else None) or prefs.get("tz") or "Europe/Moscow"

    lines = [
        "⚙️ <b>Настройки</b>",
        "",
        f"🔔 Напоминания: {'включены' if reminder_on else 'выключены'}",
        f"⏰ Время: {when} ({tz})",
        f"🎯 Цель дня: {state.get('dayGoal', 20)} вопросов",
    ]
    await safe_edit(
        callback,
        "\n".join(lines),
        kb.settings_keyboard(
            reminder_on,
            state.get("termLang", "ru"),
            not prefs.get("digest_opt_out"),
            not prefs.get("term_of_day_opt_out"),
        ),
    )


@dp.callback_query(F.data == "menu:settings")
async def cb_settings(callback: CallbackQuery) -> None:
    await _render_settings(callback)
    await callback.answer()


@dp.callback_query(F.data == "set:reminders")
async def cb_set_reminders(callback: CallbackQuery) -> None:
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

    await _render_settings(callback)
    await callback.answer("Напоминания включены" if enabled else "Напоминания выключены")


@dp.callback_query(F.data == "set:termlang")
async def cb_set_termlang(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        state = await db.get_state(session, user_id)
        state["termLang"] = "en" if state.get("termLang", "ru") == "ru" else "ru"
        await db.get_or_create_user(session, telegram_id=user_id)
        await db.put_state(session, user_id, state)
        await session.commit()

    await _render_settings(callback)
    await callback.answer(f"Язык терминов: {state['termLang'].upper()}")


@dp.callback_query(F.data == "set:digest")
async def cb_set_digest(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        prefs = await db.get_prefs(session, user_id)
        new_value = not prefs.get("digest_opt_out")
        await db.update_prefs(session, user_id, digest_opt_out=new_value)
        await session.commit()

    await _render_settings(callback)
    await callback.answer("Итоги недели выключены" if new_value else "Итоги недели включены")


@dp.callback_query(F.data == "set:termday")
async def cb_set_termday(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        prefs = await db.get_prefs(session, user_id)
        new_value = not prefs.get("term_of_day_opt_out")
        await db.update_prefs(session, user_id, term_of_day_opt_out=new_value)
        await session.commit()

    await _render_settings(callback)
    await callback.answer("Термин дня выключен" if new_value else "Термин дня включён")


@dp.callback_query(F.data == "set:time")
async def cb_set_time(callback: CallbackQuery) -> None:
    PENDING_INPUT[callback.from_user.id] = {"kind": "reminder_time"}
    await safe_edit(
        callback,
        "⏰ Отправь время ежедневного напоминания в формате <b>ЧЧ:ММ</b> — например 19:00.",
        kb.back_home(),
    )
    await callback.answer()


@dp.callback_query(F.data == "set:tz")
async def cb_set_tz(callback: CallbackQuery) -> None:
    await safe_edit(callback, "🌍 Выбери часовой пояс — по нему приходят напоминания:", kb.timezone_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("set:tzpick:"))
async def cb_set_tz_pick(callback: CallbackQuery) -> None:
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

    await _render_settings(callback)
    await callback.answer(f"Часовой пояс: {tz}")


@dp.callback_query(F.data == "set:goal")
async def cb_set_goal(callback: CallbackQuery) -> None:
    await safe_edit(
        callback, "🎯 Сколько вопросов в день ты хочешь проходить?", kb.goal_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("set:goalpick:"))
async def cb_set_goal_pick(callback: CallbackQuery) -> None:
    goal = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    async with db.get_session_maker()() as session:
        state = await db.get_state(session, user_id)
        state["dayGoal"] = goal
        await db.get_or_create_user(session, telegram_id=user_id)
        await db.put_state(session, user_id, state)
        await session.commit()

    await _render_settings(callback)
    await callback.answer(f"Цель дня: {goal}")


# ---------------------------------------------------------------- study sessions


async def _send_current_item(target: Message, session: quiz.QuizSession, *, edit: bool = False) -> None:
    item = session.current()
    if item is None:
        return

    header = f"{quiz.MODE_TITLES.get(session.mode, '📝')} · {session.index + 1}/{session.total}"
    if session.topic_name:
        header += f"\n<i>{esc(session.topic_name[:60])}</i>"

    if session.mode == "flash":
        body = f"{header}\n\n<b>{esc(item.get('front', ''))}</b>"
        markup = kb.flash_reveal_keyboard()
    else:
        options = "\n".join(
            f"{index + 1}. {esc(text)}" for index, text in enumerate(item.get("options", []))
        )
        prompt = item.get("q", "")
        if session.mode == "match":
            body = f"{header}\n\nЧто означает <b><i>{esc(prompt)}</i></b>?\n\n{options}"
        else:
            body = f"{header}\n\n<b>{esc(prompt)}</b>\n\n{options}"
        markup = kb.quiz_options_keyboard(item.get("options", []))

    if edit:
        try:
            await target.edit_text(body, reply_markup=markup)
            return
        except Exception:
            # Edit can fail on an unchanged body or a message too old to modify — fall through
            # and post a fresh one rather than dropping the question.
            logger.debug("Falling back to a new message for the next item", exc_info=True)
    await target.answer(body, reply_markup=markup)


async def _finish_session(
    user_id: int, session: quiz.QuizSession, message: Message, repeat_callback: Optional[str]
) -> None:
    quiz.end_session(user_id)

    if session.index == 0:
        await message.answer("Сессия закрыта — ни одного ответа не засчитано.", reply_markup=kb.main_menu())
        return

    async with db.get_session_maker()() as db_session:
        state = await db.get_state(db_session, user_id)
        new_state, summary = apply_session_result(
            state,
            mode=session.mode,
            module_id=session.module_id,
            topic_num=session.topic_num,
            topic_name=session.topic_name,
            reward_keys=session.reward_keys,
            correct=session.correct,
            total=session.index,  # only what was actually answered
            wrong_items=session.wrong,
            solved_mistakes=session.solved if session.mode == "mistakes" else None,
        )
        prefs = await db.get_prefs(db_session, user_id)
        fresh_badges = achievements.newly_earned(new_state, prefs.get("announced_badges") or [])
        if fresh_badges:
            announced = list(prefs.get("announced_badges") or [])
            announced += [badge.code for badge in fresh_badges]
            await db.update_prefs(db_session, user_id, announced_badges=announced)

        await db.get_or_create_user(db_session, telegram_id=user_id)
        await db.put_state(db_session, user_id, new_state)
        await db_session.commit()

    await message.answer(
        texts.session_result_text(summary, quiz.MODE_TITLES.get(session.mode, "Сессия")),
        reply_markup=kb.after_session_keyboard(repeat_callback),
    )

    for badge in fresh_badges:
        await message.answer(
            f"🎉 Новое достижение!\n\n{badge.icon} <b>{esc(badge.title)}</b>\n{esc(badge.description)}",
            reply_markup=kb.webapp_keyboard(),
        )


def _repeat_callback(session: quiz.QuizSession) -> Optional[str]:
    if session.mode == "blitz":
        return "learn:blitz"
    if session.mode == "mistakes":
        return "learn:mistakes"
    if session.module_id and session.topic_num is not None:
        prefix = {"test": "learn:test", "flash": "learn:flash", "match": "learn:terms"}.get(session.mode)
        if prefix:
            return f"{prefix}:{session.module_id}:{session.topic_num}"
    return None


async def _start_and_show(callback: CallbackQuery, session: Optional[quiz.QuizSession], empty_msg: str) -> None:
    if session is None:
        await callback.answer(empty_msg, show_alert=True)
        return
    await safe_edit(callback, "Готовлю вопросы…", None)
    await _send_current_item(callback.message, session)
    await callback.answer()


@dp.callback_query(F.data.startswith("learn:test:"))
async def cb_learn_test(callback: CallbackQuery) -> None:
    _, _, module_id, num_raw = callback.data.split(":")
    session = quiz.start_test(callback.from_user.id, module_id, int(num_raw))
    await _start_and_show(callback, session, "Для этой темы пока нет вопросов")


@dp.callback_query(F.data.startswith("learn:modtest:"))
async def cb_learn_module_test(callback: CallbackQuery) -> None:
    module_id = callback.data.split(":")[2]
    session = quiz.start_test(callback.from_user.id, module_id, None)
    await _start_and_show(callback, session, "В модуле пока нет вопросов")


@dp.callback_query(F.data.startswith("learn:flash:"))
async def cb_learn_flash(callback: CallbackQuery) -> None:
    _, _, module_id, num_raw = callback.data.split(":")
    session = quiz.start_flash(callback.from_user.id, module_id, int(num_raw))
    await _start_and_show(callback, session, "Для этой темы пока нет карточек")


@dp.callback_query(F.data.startswith("learn:terms:"))
async def cb_learn_terms(callback: CallbackQuery) -> None:
    _, _, module_id, num_raw = callback.data.split(":")
    session = quiz.start_terms(callback.from_user.id, module_id, int(num_raw))
    await _start_and_show(callback, session, "Для этой темы пока нет терминов")


@dp.callback_query(F.data.startswith("learn:modterms:"))
async def cb_learn_module_terms(callback: CallbackQuery) -> None:
    module_id = callback.data.split(":")[2]
    session = quiz.start_terms(callback.from_user.id, module_id, None)
    await _start_and_show(callback, session, "В модуле пока нет терминов")


@dp.callback_query(F.data == "learn:terms_all")
async def cb_learn_terms_all(callback: CallbackQuery) -> None:
    session = quiz.start_terms(callback.from_user.id)
    await _start_and_show(callback, session, "Термины пока недоступны")


@dp.callback_query(F.data == "learn:blitz")
async def cb_learn_blitz(callback: CallbackQuery) -> None:
    session = quiz.start_blitz(callback.from_user.id)
    await _start_and_show(callback, session, "Вопросы пока недоступны")


@dp.callback_query(F.data == "learn:mistakes")
async def cb_learn_mistakes(callback: CallbackQuery) -> None:
    state = await load_state(callback.from_user.id)
    session = quiz.start_mistakes(callback.from_user.id, state)
    await _start_and_show(
        callback, session, "Ошибок нет — отличная работа! Порешай тесты, чтобы было что разбирать."
    )


@dp.callback_query(F.data == "learn:review")
async def cb_learn_review(callback: CallbackQuery) -> None:
    """Start a test on the most overdue topic that's due for spaced review."""
    state = await load_state(callback.from_user.id)
    due = topics_due_for_review(state)
    if not due:
        await callback.answer("Сейчас нечего повторять", show_alert=True)
        return

    for entry in due:
        module_id, _, num_raw = entry["key"].partition(":")
        if not num_raw.isdigit():
            continue
        session = quiz.start_test(callback.from_user.id, module_id, int(num_raw))
        if session:
            await _start_and_show(callback, session, "Нет вопросов")
            return
    await callback.answer("Для этих тем нет вопросов в боте", show_alert=True)


@dp.callback_query(F.data == "quiz:reveal")
async def cb_quiz_reveal(callback: CallbackQuery) -> None:
    session = quiz.get_session(callback.from_user.id)
    if session is None or session.finished:
        await callback.answer("Сессия завершена")
        return

    item = session.current() or {}
    session.revealed = True
    body = (
        f"{quiz.MODE_TITLES['flash']} · {session.index + 1}/{session.total}\n\n"
        f"<b>{esc(item.get('front', ''))}</b>\n\n"
        f"💡 {esc(item.get('back', ''))}"
    )
    try:
        await callback.message.edit_text(body, reply_markup=kb.flash_grade_keyboard())
    except Exception:
        await callback.message.answer(body, reply_markup=kb.flash_grade_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("quiz:flash:"))
async def cb_quiz_flash_grade(callback: CallbackQuery) -> None:
    session = quiz.get_session(callback.from_user.id)
    if session is None or session.finished:
        await callback.answer("Сессия завершена")
        return

    quiz.answer_flash(session, callback.data.endswith(":1"))
    await callback.answer()
    if session.finished:
        await _finish_session(callback.from_user.id, session, callback.message, _repeat_callback(session))
    else:
        await _send_current_item(callback.message, session, edit=True)


@dp.callback_query(F.data.startswith("quiz:ans:"))
async def cb_quiz_answer(callback: CallbackQuery) -> None:
    session = quiz.get_session(callback.from_user.id)
    if session is None or session.finished:
        await callback.answer("Сессия завершена")
        return

    chosen = int(callback.data.split(":")[2])
    is_correct, item = quiz.answer_choice(session, chosen)
    options = item.get("options", [])
    correct_index = item.get("correct", 0)
    correct_text = options[correct_index] if 0 <= correct_index < len(options) else ""

    if is_correct:
        verdict = "✅ <b>Верно!</b>"
    else:
        chosen_text = options[chosen] if 0 <= chosen < len(options) else ""
        verdict = (
            f"❌ <b>Неверно.</b>\nТы выбрал: {esc(chosen_text)}\n"
            f"Правильный ответ: <b>{esc(correct_text)}</b>"
        )

    prompt = item.get("q", "")
    body = f"{esc(prompt)}\n\n{verdict}\n\nСчёт: {session.correct}/{session.index}"
    try:
        await callback.message.edit_text(body, reply_markup=kb.next_question_keyboard())
    except Exception:
        await callback.message.answer(body, reply_markup=kb.next_question_keyboard())
    await callback.answer("Верно!" if is_correct else "Неверно")

    if session.finished:
        await _finish_session(callback.from_user.id, session, callback.message, _repeat_callback(session))


@dp.callback_query(F.data == "quiz:next")
async def cb_quiz_next(callback: CallbackQuery) -> None:
    session = quiz.get_session(callback.from_user.id)
    if session is None or session.finished:
        await callback.answer("Сессия завершена")
        return
    await _send_current_item(callback.message, session, edit=True)
    await callback.answer()


@dp.callback_query(F.data == "quiz:stop")
async def cb_quiz_stop(callback: CallbackQuery) -> None:
    session = quiz.get_session(callback.from_user.id)
    if session is None:
        await callback.answer("Сессия уже завершена")
        await safe_edit(callback, "🏠 <b>Главное меню</b>", kb.main_menu())
        return
    await callback.answer("Сессия завершена")
    await _finish_session(callback.from_user.id, session, callback.message, _repeat_callback(session))


# ---------------------------------------------------------------- commands


def _progress_text(state: dict[str, Any]) -> str:
    xp = int(state.get("xp") or 0)
    level_no, level_title, _, _ = achievements.level_for_xp(xp)
    lines = [
        "📊 <b>Твой прогресс</b>",
        "",
        f"⭐ XP: {xp} · уровень {level_no} ({level_title})",
        f"🔥 Серия: {state.get('streak', 0)}",
        f"🎯 Сегодня: {state.get('dayDone', 0)}/{state.get('dayGoal', 20)}",
        "",
    ]
    total_passed = total_topics = 0
    for row in module_progress(state):
        lines.append(
            f"{row['icon']} {esc(row['title'])}: {row['passed']}/{row['total']} "
            f"{texts.progress_bar(row['pct'], 8)} {row['pct']}%"
        )
        total_passed += row["passed"]
        total_topics += row["total"]
    if total_topics:
        overall = round(total_passed / total_topics * 100)
        lines += ["", f"<b>Итого: {total_passed}/{total_topics} ({overall}%)</b>"]
    return "\n".join(lines)


def _review_text(due: list[dict[str, Any]]) -> str:
    if not due:
        return "🔁 <b>Повторение</b>\n\nСейчас нет тем к повторению — всё свежее! Загляни позже."
    lines = [
        f"🔁 <b>К повторению: {len(due)}</b> {texts.plural(len(due), 'тема', 'темы', 'тем')}",
        "",
    ]
    for entry in due[:10]:
        overdue = entry["overdue_days"]
        suffix = f" · просрочено {overdue} дн." if overdue > 0 else ""
        lines.append(f"• {esc(entry['label'])}{suffix}")
    if len(due) > 10:
        lines.append(f"…и ещё {len(due) - 10}")
    return "\n".join(lines)


@dp.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await register_user(message)
    # Re-install the persistent navigation here too: it is the recovery path for anyone who
    # hid or cleared it, and for users who started the bot before it existed.
    await message.answer(
        "Навигация включена 👇",
        reply_markup=kb.reply_nav(is_admin=admin.is_admin(message.from_user.id)),
    )
    await message.answer("🏠 <b>Главное меню</b>", reply_markup=kb.main_menu())


@dp.message(Command("study"))
async def cmd_study(message: Message) -> None:
    await message.answer(texts.course_overview_text(), reply_markup=kb.learn_menu_keyboard())


@dp.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    state = await load_state(message.from_user.id)
    await message.answer(_progress_text(state), reply_markup=kb.main_menu())


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    state = await load_state(message.from_user.id)
    await message.answer(texts.stats_text(state), reply_markup=kb.main_menu())


@dp.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    user_id = message.from_user.id
    async with db.get_session_maker()() as session:
        state = await db.get_state(session, user_id)
        prefs = await db.get_prefs(session, user_id)
        referrals = await db.count_referrals(session, user_id)
    await message.answer(
        texts.profile_text(state, prefs, name=esc(user_display_name(message)), referrals=referrals),
        reply_markup=kb.main_menu(),
    )


@dp.message(Command("top"))
async def cmd_top(message: Message) -> None:
    user_id = message.from_user.id
    async with db.get_session_maker()() as session:
        top = await db.top_users_by_xp(session, limit=texts.MAX_LEADERBOARD_ROWS)
        rank, xp, total = await db.user_rank_by_xp(session, user_id)
    await message.answer(texts.leaderboard_text(top, rank, xp, total, user_id), reply_markup=kb.main_menu())


@dp.message(Command("review"))
async def cmd_review(message: Message) -> None:
    state = await load_state(message.from_user.id)
    due = topics_due_for_review(state)
    await message.answer(_review_text(due), reply_markup=kb.review_keyboard(bool(due)))


@dp.message(Command("blitz"))
async def cmd_blitz(message: Message) -> None:
    session = quiz.start_blitz(message.from_user.id)
    if session is None:
        await message.answer("Вопросы пока недоступны.", reply_markup=kb.webapp_keyboard())
        return
    await _send_current_item(message, session)


@dp.message(Command("term"))
async def cmd_term(message: Message) -> None:
    await message.answer(texts.term_of_the_day_text(), reply_markup=kb.main_menu())


@dp.message(Command("streak"))
async def cmd_streak(message: Message) -> None:
    state = await load_state(message.from_user.id)
    streak = int(state.get("streak") or 0)
    text = (
        f"🔥 Текущая серия: <b>{streak}</b> {texts.plural(streak, 'день', 'дня', 'дней')}\n"
        f"Сегодня пройдено: {state.get('dayDone', 0)}/{state.get('dayGoal', 20)}"
    )
    await message.answer(text, reply_markup=kb.main_menu())


@dp.message(Command("exam"))
async def cmd_exam(message: Message) -> None:
    state, prefs = await load_state_and_prefs(message.from_user.id)
    PENDING_INPUT[message.from_user.id] = {"kind": "exam_date"}
    await message.answer(
        texts.exam_plan_text(prefs, state) + "\n\n<i>Отправь дату сообщением (ДД.ММ.ГГГГ).</i>",
        reply_markup=kb.webapp_keyboard(),
    )


@dp.message(Command("invite"))
async def cmd_invite(message: Message) -> None:
    user_id = message.from_user.id
    async with db.get_session_maker()() as session:
        referrals = await db.count_referrals(session, user_id)
    link = f"https://t.me/{config.BOT_USERNAME}?start=ref{user_id}"
    await message.answer(
        f"🤝 Твоя ссылка для друзей:\n<code>{link}</code>\n\nУже присоединилось: <b>{referrals}</b>",
        reply_markup=kb.webapp_keyboard(),
    )


@dp.message(Command("reminder"))
async def cmd_reminder(message: Message) -> None:
    async with db.get_session_maker()() as session:
        reminder = await session.get(db.Reminder, message.from_user.id)
    if reminder is None or not reminder.enabled:
        await message.answer(
            "🔕 Напоминания выключены.\n\nОтправь время в формате ЧЧ:ММ (например 19:00), чтобы включить.",
            reply_markup=kb.webapp_keyboard(),
        )
    else:
        await message.answer(
            f"🔔 Напоминания включены на {reminder.time.strftime('%H:%M')} ({reminder.tz}).\n\n"
            "Отправь новое время ЧЧ:ММ, чтобы изменить, или /reminder_off, чтобы выключить.",
            reply_markup=kb.webapp_keyboard(),
        )


@dp.message(Command("reminder_off"))
async def cmd_reminder_off(message: Message) -> None:
    async with db.get_session_maker()() as session:
        reminder = await session.get(db.Reminder, message.from_user.id)
        if reminder is not None:
            reminder.enabled = False
        await session.commit()
    await message.answer("🔕 Напоминания выключены.", reply_markup=kb.webapp_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Команды бота АНАТОМ</b>\n\n"
        "/menu — главное меню\n"
        "/study — учиться: модули, темы, режимы\n"
        "/blitz — быстрый тест по всему курсу\n"
        "/review — темы к повторению\n"
        "/progress — прогресс по модулям\n"
        "/stats — подробная статистика\n"
        "/profile — профиль и уровень\n"
        "/top — рейтинг студентов\n"
        "/term — латинский термин дня\n"
        "/streak — серия дней\n"
        "/exam — обратный отсчёт до экзамена\n"
        "/invite — пригласить друзей\n"
        "/reminder — напоминания\n"
        "/help — эта справка\n\n"
        f"Поддержка: {config.SUPPORT_URL}",
        reply_markup=kb.main_menu(),
    )


# ---------------------------------------------------------------- admin


ADMIN_PANEL_TITLE = "⚙️ <b>Админ-панель</b>\n\nВыбери действие:"


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not admin.is_admin(message.from_user.id):
        return
    # Re-send the nav so the admin picks up the ⚙️ button the first time they open the panel.
    await message.answer(ADMIN_PANEL_TITLE, reply_markup=kb.reply_nav(is_admin=True))
    await message.answer("Действия:", reply_markup=admin.admin_menu_keyboard())


async def _guard_admin(callback: CallbackQuery) -> bool:
    if not admin.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return False
    # Any panel tap ends whatever input the panel was waiting for, so a half-finished lookup
    # can't swallow the admin's next unrelated message. Handlers that need input set it again
    # right after this guard; drafts are left alone so the confirm button still works.
    admin.ADMIN_PENDING.pop(callback.from_user.id, None)
    return True


@dp.callback_query(F.data == "admin_home")
async def cb_admin_home(callback: CallbackQuery) -> None:
    if not await _guard_admin(callback):
        return
    admin.ADMIN_PENDING.pop(callback.from_user.id, None)
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

    audience = (
        f"спящим ({admin.INACTIVE_DAYS}+ дней без занятий)" if cohort == "inactive" else "всем"
    )
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

    cohort = draft["cohort"]
    await callback.answer("Отправляю…")
    await safe_edit(callback, "📢 Рассылка идёт, это может занять пару минут…", None)

    async with db.get_session_maker()() as session:
        sent, failed = await admin.broadcast_text(bot, session, draft["text"], cohort)

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
        "<i>Если точного совпадения не будет — покажу похожих. "
        "ID также видно в списках «Топ-10» и «Новые».</i>",
        admin.admin_menu_keyboard(),
    )
    await callback.answer()


# ------------------------------------------------- persistent navigation buttons
#
# These must be registered before the catch-all text handler below, which treats anything it
# receives as a topic search — otherwise tapping a nav button would search for its own label.


@dp.message(F.text == kb.NAV_ADMIN)
async def nav_admin(message: Message) -> None:
    # A reply button is just text, so anyone could type this — permission is checked here, not
    # by the keyboard that offered it.
    if not admin.is_admin(message.from_user.id):
        raise SkipHandler
    PENDING_INPUT.pop(message.from_user.id, None)
    await message.answer(ADMIN_PANEL_TITLE, reply_markup=admin.admin_menu_keyboard())


@dp.message(F.text == kb.NAV_MENU)
async def nav_menu(message: Message) -> None:
    PENDING_INPUT.pop(message.from_user.id, None)
    await message.answer("🏠 <b>Главное меню</b>", reply_markup=kb.main_menu())


@dp.message(F.text == kb.NAV_LEARN)
async def nav_learn(message: Message) -> None:
    PENDING_INPUT.pop(message.from_user.id, None)
    await message.answer(texts.course_overview_text(), reply_markup=kb.learn_menu_keyboard())


@dp.message(F.text == kb.NAV_BLITZ)
async def nav_blitz(message: Message) -> None:
    PENDING_INPUT.pop(message.from_user.id, None)
    session = quiz.start_blitz(message.from_user.id)
    if session is None:
        await message.answer("Вопросы пока недоступны.", reply_markup=kb.webapp_keyboard())
        return
    await _send_current_item(message, session)


@dp.message(F.text == kb.NAV_REVIEW)
async def nav_review(message: Message) -> None:
    PENDING_INPUT.pop(message.from_user.id, None)
    state = await load_state(message.from_user.id)
    due = topics_due_for_review(state)
    await message.answer(_review_text(due), reply_markup=kb.review_keyboard(bool(due)))


@dp.message(F.text == kb.NAV_PROGRESS)
async def nav_progress(message: Message) -> None:
    PENDING_INPUT.pop(message.from_user.id, None)
    state = await load_state(message.from_user.id)
    await message.answer(
        _progress_text(state),
        reply_markup=kb.back_home(
            [[InlineKeyboardButton(text="📈 Подробная статистика", callback_data="menu:stats")]]
        ),
    )


@dp.message(F.text == kb.NAV_SITE)
async def nav_site(message: Message) -> None:
    PENDING_INPUT.pop(message.from_user.id, None)
    await message.answer(
        "🌐 <b>АНАТОМ</b> — полная версия\n\n"
        "Теория, атлас, разбор тем и все тренировки. Прогресс общий с ботом: "
        "продолжишь ровно с того места, где остановился.",
        reply_markup=kb.webapp_keyboard(),
    )


# ---------------------------------------------------------------- free text


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DATE_RE = re.compile(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$")


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

    # 1. Admin flows take precedence so an admin isn't hijacked by their own pending prompt.
    if admin.is_admin(user_id) and user_id in admin.ADMIN_PENDING:
        pending_admin = admin.ADMIN_PENDING.pop(user_id)
        action = pending_admin.get("action")

        if action == "broadcast":
            cohort = pending_admin.get("cohort", "all")
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

    pending = PENDING_INPUT.get(user_id)
    raw = message.text.strip()

    # 2. A bare HH:MM always means "set my reminder", prompted or not.
    time_match = _TIME_RE.match(raw)
    if time_match:
        PENDING_INPUT.pop(user_id, None)
        await _apply_reminder_time(user_id, message.chat.id, int(time_match.group(1)), int(time_match.group(2)))
        await message.answer(
            f"✅ Буду напоминать каждый день в {time_match.group(1).zfill(2)}:{time_match.group(2)}.",
            reply_markup=kb.main_menu(),
        )
        return

    if pending and pending.get("kind") == "exam_date":
        date_match = _DATE_RE.match(raw)
        if date_match:
            day, month, year = (int(part) for part in date_match.groups())
            try:
                exam_date = dt.date(year, month, day)
            except ValueError:
                await message.answer("Такой даты не существует. Формат: ДД.ММ.ГГГГ")
                return
            PENDING_INPUT.pop(user_id, None)
            async with db.get_session_maker()() as session:
                await db.update_prefs(session, user_id, exam_date=exam_date.isoformat())
                state = await db.get_state(session, user_id)
                prefs = await db.get_prefs(session, user_id)
                await session.commit()
            await message.answer(texts.exam_plan_text(prefs, state), reply_markup=kb.main_menu())
            return

    # 3. Anything else is treated as a topic search — the most useful default for a bare message.
    PENDING_INPUT.pop(user_id, None)
    results = content.search_topics(raw)
    if not results:
        await message.answer(
            "Ничего не нашёл по этому запросу.\n\n"
            "Попробуй другое слово — например «череп», «сердце» или латинский термин.",
            reply_markup=kb.main_menu(),
        )
        return

    await message.answer(
        f"🔍 Нашёл {len(results)} {texts.plural(len(results), 'тему', 'темы', 'тем')} по запросу "
        f"«{esc(raw)}»:",
        reply_markup=kb.search_results_keyboard(results),
    )


BOT_COMMANDS = [
    BotCommand(command="menu", description="🏠 Главное меню"),
    BotCommand(command="study", description="🎓 Учиться: модули и темы"),
    BotCommand(command="blitz", description="⚡ Блиц по всему курсу"),
    BotCommand(command="review", description="🔁 Темы к повторению"),
    BotCommand(command="progress", description="📊 Прогресс по модулям"),
    BotCommand(command="stats", description="📈 Подробная статистика"),
    BotCommand(command="profile", description="👤 Профиль и уровень"),
    BotCommand(command="top", description="🏆 Рейтинг студентов"),
    BotCommand(command="term", description="📖 Латинский термин дня"),
    BotCommand(command="streak", description="🔥 Серия дней"),
    BotCommand(command="exam", description="🎓 Отсчёт до экзамена"),
    BotCommand(command="invite", description="🤝 Пригласить друга"),
    BotCommand(command="reminder", description="⏰ Напоминания"),
    BotCommand(command="help", description="❓ Справка"),
]


async def setup_bot_menu() -> None:
    """Fill the ☰ menu next to the input field with the command list.

    Both calls are best-effort: a transient Telegram error here must not stop the bot from
    starting, and the menu simply keeps whatever it had.
    """
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Command menu published (%s commands)", len(BOT_COMMANDS))
    except Exception:
        logger.exception("Could not publish the command menu")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await db.init_models()
    from scheduler import start_scheduler

    start_scheduler(bot)
    await setup_bot_menu()
    logger.info(
        "anatom-bot starting; content: %s", content.counts() if content.has_content() else "MISSING"
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
