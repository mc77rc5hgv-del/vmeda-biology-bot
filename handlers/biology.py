"""Раздел «Биология» — Router вместо прямой регистрации на глобальном dp (Phase 3 рефакторинга,
см. CLAUDE.md — та же схема, что уже применена к Гистологии/Анатомии/Физике/Химии). Импортирует
telegram_bot как tb вместо `from telegram_bot import ...` — циклическая связь разрешается тем, что
этот импорт стоит в самом конце telegram_bot.py, когда все нужные отсюда имена (stats, save_stats,
safe_edit_text, send_answer, is_subscribed, is_ticket_visible, QUESTIONS, TICKETS_DICT,
VISIBLE_TICKETS, VISIBLE_TICKET_NUMS, ACTIVE_SUBSCRIPTION_TIERS, BOT_USERNAME,
biology_tickets_download_ok, build_biology_tickets_file, get_question_answer_keyboard,
get_question_page_keyboard, get_ticket_questions_keyboard) уже определены в его модульном
пространстве имён.

Билеты, вопросы, режим опроса (флэш-карточки) и главное меню Биологии — всё с уникальными
callback_data-фильтрами (безопасно для порядка маршрутизации). ВСЁ ЕЩЁ не перенесено:
`handle_question_number` (обработчик @dp.message(F.text.isdigit()) — поиск вопроса по номеру,
введённому текстом) и `handle_keyword_search` (@dp.message(F.text) — поиск по ключевым словам)
остаются в telegram_bot.py: они физически перемешаны с другими @dp.message(F.text)-хендлерами
(AI, админ-пендинг), чьё поведение зависит от ОТНОСИТЕЛЬНОГО ПОРЯДКА регистрации на dp через
SkipHandler — dp всегда сначала пробует хендлеры, зарегистрированные напрямую на нём, и только
потом сабраутеры, независимо от того, где стоит dp.include_router(). Перенос этих двух хендлеров
сдвинул бы их приоритет и реально изменил бы, какой хендлер первым перехватывает сообщение —
поэтому вместе с ними остаются и клавиатурные билдеры, которые им нужны (get_search_results_keyboard,
get_question_answer_keyboard, get_question_page_keyboard, get_ticket_questions_keyboard)."""
import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

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

# ==================== БИОЛОГИЯ — ГЛАВНОЕ МЕНЮ ====================
def get_biology_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Билеты", callback_data="menu_tickets")
    builder.button(text="📝 Вопросы", callback_data="menu_questions")
    builder.button(text="🎯 Опрос (10 вопросов)", callback_data="quiz_start")
    builder.button(text="📄 Все билеты (текстовый файл)", callback_data="download_biology_tickets")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

# ==================== БИОЛОГИЯ — РЕЖИМ ОПРОСА (ФЛЭШ-КАРТОЧКИ) ====================
QUIZ_SESSION_SIZE = 10
QUIZ_SESSIONS: dict[int, dict] = {}

def get_quiz_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="quiz_show_answer")
    builder.button(text="🛑 Закончить опрос", callback_data="quiz_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_quiz_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Знаю", callback_data="quiz_know")
    builder.button(text="❌ Не знаю", callback_data="quiz_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить опрос", callback_data="quiz_stop"))
    return builder.as_markup()

def get_quiz_summary_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data="quiz_start")
    builder.button(text="🔙 К биологии", callback_data="menu_biology")
    builder.adjust(1)
    return builder.as_markup()

def start_quiz_session(user_id: int):
    pool = list(tb.QUESTIONS.keys())
    size = min(QUIZ_SESSION_SIZE, len(pool))
    QUIZ_SESSIONS[user_id] = {
        "questions": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }

async def render_quiz_question(message, user_id: int):
    session = QUIZ_SESSIONS[user_id]
    total = len(session["questions"])
    q_num = session["questions"][session["index"]]
    q = tb.QUESTIONS[q_num]
    text = (
        f"🎯 <b>Опрос — вопрос {session['index'] + 1}/{total}</b>\n{tb.DIVIDER}\n\n"
        f"<b>{q['title']}</b>"
    )
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_quiz_question_keyboard())

async def render_quiz_answer(message, user_id: int):
    session = QUIZ_SESSIONS[user_id]
    total = len(session["questions"])
    q_num = session["questions"][session["index"]]
    q = tb.QUESTIONS[q_num]
    header = f"🎯 <b>Опрос — вопрос {session['index'] + 1}/{total}</b>"
    body = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}\n\n{tb.DIVIDER}\nТы знал(а) ответ?"
    short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>"
    await tb.send_answer(message, body, short_caption, q, get_quiz_answer_keyboard(), edit=True)

async def render_quiz_summary(message, user_id: int, aborted: bool = False):
    session = QUIZ_SESSIONS.pop(user_id, None)
    if not session:
        await tb.safe_edit_text(
            message,
            f"🧬 <b>Биология</b>\n{tb.DIVIDER}\n\nВыбери формат подготовки:",
            parse_mode="HTML",
            reply_markup=get_biology_menu()
        )
        return
    answered = session["know"] + session["dont_know"]
    title = "🛑 <b>Опрос прерван</b>" if aborted else "🏁 <b>Опрос завершён!</b>"
    text = (
        f"{title}\n{tb.DIVIDER}\n\n"
        f"Отвечено вопросов: <b>{answered}</b>\n"
        f"✅ Знаю: <b>{session['know']}</b>\n"
        f"❌ Не знаю: <b>{session['dont_know']}</b>"
    )
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_quiz_summary_keyboard())

def get_ticket_keyboard():
    builder = InlineKeyboardBuilder()
    for num in tb.VISIBLE_TICKET_NUMS:
        builder.button(text=f"🟢 {num}", callback_data=f"ticket:{num}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="🎲 Случайный билет", callback_data="random_ticket"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_biology"))
    return builder.as_markup()

def get_questions_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Страница 1 (1-50)", callback_data="qpage:1")
    builder.button(text="📄 Страница 2 (51-100)", callback_data="qpage:2")
    builder.button(text="📄 Страница 3 (101-150)", callback_data="qpage:3")
    builder.button(text="📄 Страница 4 (151-185)", callback_data="qpage:4")
    builder.button(text="🎲 Случайный вопрос", callback_data="question_random")
    builder.button(text="🔢 Ввести номер вручную", callback_data="question_by_number")
    builder.button(text="🔍 Поиск по ключевым словам", callback_data="question_search")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_biology"))
    return builder.as_markup()

# ==================== БИОЛОГИЯ — ХЕНДЛЕРЫ МЕНЮ / ОПРОСА ====================
@router.callback_query(F.data == "menu_biology")
async def cb_menu_biology(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🧬 <b>Биология</b>\n{tb.DIVIDER}\n\nВыбери формат подготовки:",
        parse_mode="HTML",
        reply_markup=get_biology_menu()
    )

def get_biology_tickets_locked_text() -> str:
    tier_lines = "\n".join(
        f"«{cfg['emoji']} {cfg['title']}» ({cfg['price_rub']}₽ / {cfg['price_stars']}⭐)"
        for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values() if cfg.get("biology_download")
    )
    return (
        f"📄 <b>Билеты по биологии — файл с ответами</b>\n{tb.DIVIDER}\n\n"
        "Скачивание готового файла со всеми вопросами и ответами доступно по подписке:\n\n"
        f"{tier_lines}\n\n"
        "Само прохождение билетов и вопросов в боте остаётся доступным как обычно — "
        "подписка нужна только для скачивания файла."
    )

def get_biology_tickets_locked_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Оформить подписку", callback_data="subscription_menu")
    builder.button(text="🔙 Назад к Биологии", callback_data="menu_biology")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data == "download_biology_tickets")
async def cb_download_biology_tickets(callback: CallbackQuery):
    if not tb.biology_tickets_download_ok(callback.from_user.id):
        await callback.answer()
        await tb.safe_edit_text(
            callback.message,
            get_biology_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=get_biology_tickets_locked_keyboard()
        )
        return
    await callback.answer()
    await callback.message.answer_document(
        tb.build_biology_tickets_file(),
        caption=f"📄 Все билеты по биологии — вопросы и ответы.\n\n@{tb.BOT_USERNAME}"
    )

@router.callback_query(F.data == "quiz_start")
async def cb_quiz_start(callback: CallbackQuery):
    if not tb.QUESTIONS:
        await callback.answer("Вопросы ещё не загружены", show_alert=True)
        return
    await callback.answer()
    start_quiz_session(callback.from_user.id)
    await render_quiz_question(callback.message, callback.from_user.id)

@router.callback_query(F.data == "quiz_show_answer")
async def cb_quiz_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in QUIZ_SESSIONS:
        await callback.answer("Сессия опроса истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_quiz_answer(callback.message, user_id)

@router.callback_query(F.data.in_({"quiz_know", "quiz_dont_know"}))
async def cb_quiz_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = QUIZ_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия опроса истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "quiz_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["questions"]):
        await render_quiz_summary(callback.message, user_id)
    else:
        await render_quiz_question(callback.message, user_id)

@router.callback_query(F.data == "quiz_stop")
async def cb_quiz_stop(callback: CallbackQuery):
    await callback.answer()
    await render_quiz_summary(callback.message, callback.from_user.id, aborted=True)

@router.callback_query(F.data == "menu_tickets")
async def cb_menu_tickets(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📘 <b>Билеты — Биология</b>\n{tb.DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=get_ticket_keyboard()
    )

@router.callback_query(F.data == "menu_questions")
async def cb_menu_questions(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📝 <b>Вопросы — Биология</b>\n{tb.DIVIDER}\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=get_questions_main_menu()
    )

