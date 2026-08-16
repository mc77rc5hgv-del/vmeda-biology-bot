"""Раздел «Биология» (билеты + вопросы) — Router вместо прямой регистрации на глобальном dp
(Phase 3 рефакторинга, см. CLAUDE.md — та же схема, что уже применена к Гистологии и Анатомии).
Импортирует telegram_bot как tb вместо `from telegram_bot import ...` — циклическая связь
разрешается тем, что этот импорт стоит в самом конце telegram_bot.py, когда все нужные отсюда
имена (stats, save_stats, safe_edit_text, send_answer, is_subscribed, is_ticket_visible,
QUESTIONS, TICKETS_DICT, VISIBLE_TICKETS, get_ticket_questions_keyboard,
get_question_answer_keyboard, get_question_page_keyboard) уже определены в его модульном
пространстве имён.

ВАЖНО — узкий срез, а не весь раздел «Биология»: сюда вынесены только билеты и вопросы (секции
"БИОЛОГИЯ — БИЛЕТЫ"/"БИОЛОГИЯ — ВОПРОСЫ" в исходном файле), все с уникальными callback_data-
фильтрами (безопасно для порядка маршрутизации). Режим опроса (флэш-карточки, quiz_start и т.д.)
и `handle_question_number` (обработчик @dp.message(F.text.isdigit()) — поиск вопроса по номеру,
введённому текстом) сознательно ОСТАВЛЕНЫ в telegram_bot.py: они физически перемешаны с общим
меню/навигацией и другими @dp.message(F.text)-хендлерами (AI, админ-пендинг, поиск по ключевым
словам), чьё поведение зависит от ОТНОСИТЕЛЬНОГО ПОРЯДКА регистрации на dp через SkipHandler —
перенос `handle_question_number` в отдельный Router сдвинул бы его ПОСЛЕ них (сначала всегда
пробуются хендлеры, зарегистрированные напрямую на dp, и только потом — сабраутеры), что реально
изменило бы, какой хендлер первым перехватывает цифровое сообщение. Трогать это — отдельная,
более рискованная задача, не в этом срезе."""
import random

from aiogram import F, Router
from aiogram.types import CallbackQuery

import telegram_bot as tb

router = Router()

# ==================== БИОЛОГИЯ — БИЛЕТЫ ====================
@router.callback_query(F.data == "random_ticket")
async def cb_random_ticket(callback: CallbackQuery):
    if not await tb.is_subscribed(callback.from_user.id):
        await callback.answer("Сначала подпишись на канал!", show_alert=True)
        return
    if not tb.VISIBLE_TICKETS:
        await callback.answer("Билеты пока не загружены", show_alert=True)
        return
    await callback.answer()
    tb.stats["random_ticket_used"] += 1
    tb.save_stats()
    ticket = random.choice(tb.VISIBLE_TICKETS)
    await show_ticket(callback.message, ticket)

@router.callback_query(F.data.startswith("ticket:"))
async def cb_ticket(callback: CallbackQuery):
    await callback.answer()
    ticket_num = callback.data.split(":")[1]
    if ticket_num in tb.TICKETS_DICT and tb.is_ticket_visible(ticket_num):
        await show_ticket(callback.message, tb.TICKETS_DICT[ticket_num])
    else:
        await callback.answer("Билет не найден", show_alert=True)

async def show_ticket(message, ticket: dict):
    ticket_num = ticket.get("num", "?")
    questions = ticket.get("questions", [])
    lines = [f"📘 <b>Билет {ticket_num}</b>", tb.DIVIDER, ""]
    for q in questions:
        lines.append(f"<b>{q.get('num')}.</b> {q.get('title', '')}")
        lines.append("")
    lines.append("👇 Нажми на номер вопроса, чтобы увидеть ответ:")
    text = "\n".join(lines)
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=tb.get_ticket_questions_keyboard(str(ticket_num)))

@router.callback_query(F.data.startswith("ticket_q:"))
async def cb_ticket_question(callback: CallbackQuery):
    await callback.answer()
    _, ticket_num, q_num = callback.data.split(":")
    ticket = tb.TICKETS_DICT.get(ticket_num, {})
    questions = ticket.get("questions", [])
    question = next((q for q in questions if str(q.get("num")) == q_num), None)
    if question:
        header = f"❓ <b>Вопрос {q_num}</b> · Билет {ticket_num}"
        body = f"{header}\n{tb.DIVIDER}\n\n<b>{question['title']}</b>\n\n{question['answer']}"
        short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{question['title']}</b>"
        keyboard = tb.get_ticket_questions_keyboard(ticket_num)
        await tb.send_answer(callback.message, body, short_caption, question, keyboard, edit=True)
    else:
        await callback.answer("Вопрос не найден", show_alert=True)

# ==================== БИОЛОГИЯ — ВОПРОСЫ ====================
@router.callback_query(F.data.startswith("qpage:"))
async def cb_question_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📄 <b>Вопросы — Страница {page}</b>\n{tb.DIVIDER}",
        parse_mode="HTML",
        reply_markup=tb.get_question_page_keyboard(page)
    )

@router.callback_query(F.data.startswith("q:"))
async def cb_show_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in tb.QUESTIONS:
        tb.stats["question_opened"][q_num] = tb.stats["question_opened"].get(q_num, 0) + 1
        tb.save_stats()
        q = tb.QUESTIONS[q_num]
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
        short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>"
        await tb.send_answer(callback.message, body, short_caption, q, tb.get_question_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос не найден", show_alert=True)

@router.callback_query(F.data == "question_random")
async def cb_question_random(callback: CallbackQuery):
    if not tb.QUESTIONS:
        await callback.answer("Вопросы ещё не загружены", show_alert=True)
        return
    await callback.answer()
    tb.stats["random_question_used"] += 1
    q_num = random.choice(list(tb.QUESTIONS.keys()))
    tb.stats["question_opened"][q_num] = tb.stats["question_opened"].get(q_num, 0) + 1
    tb.save_stats()
    q = tb.QUESTIONS[q_num]
    header = f"❓ <b>Вопрос {q_num}</b>"
    body = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>"
    await tb.send_answer(callback.message, body, short_caption, q, tb.get_question_answer_keyboard(q_num), edit=True)

@router.callback_query(F.data == "question_by_number")
async def cb_question_by_number(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🔢 <b>Поиск вопроса по номеру</b>\n{tb.DIVIDER}\n\nВведи номер вопроса (от 1 до 185):",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "question_search")
async def cb_question_search(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🔍 <b>Поиск по ключевым словам</b>\n{tb.DIVIDER}\n\n"
        "Напиши слово или часть слова (например: <i>плазмодий</i>) — "
        "покажу все вопросы, где оно встречается, вместе с падежами и склонениями.",
        parse_mode="HTML"
    )
