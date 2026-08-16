"""Раздел «Физика» (тестовая часть, билеты всех видов, задачи по темам) — Router вместо прямой
регистрации на глобальном dp (Phase 3 рефакторинга, см. CLAUDE.md — та же схема, что у Гистологии/
Анатомии/Биологии). Импортирует telegram_bot как tb — циклическая связь разрешается тем, что этот
импорт стоит там же, где раньше стояла эта секция (см. блок "ФИЗИКА" в telegram_bot.py), когда все
нужные отсюда имена уже определены в его модульном пространстве имён.

Узкий срез, как и с Биологией: сюда вынесены только сами callback_query-хендлеры (все с
уникальными фильтрами, безопасно для порядка dp — здесь нет ни одного @dp.message). Клавиатурные
билдеры (get_physics_menu, get_physics_tickets_menu и т.д., секция "ФИЗИКА" в начале файла) НЕ
перенесены — они используются и хендлерами отсюда, и cb_menu_physics/download_physics_* (которые
остаются в telegram_bot.py), так что их разумнее оставить на месте и обращаться к ним как tb.*."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

# ==================== ФИЗИКА ====================
@router.callback_query(F.data == "physics_tickets")
async def cb_physics_tickets(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📘 <b>Билеты по физике</b>\n{tb.DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_tickets_menu()
    )

@router.callback_query(F.data == "physics_theory_tickets")
async def cb_physics_theory_tickets(callback: CallbackQuery):
    await callback.answer()
    if not tb.PHYSICS_THEORY_TICKETS:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="physics_tickets"))
        await tb.safe_edit_text(
            callback.message,
            f"📖 <b>Билеты теоретической части</b>\n{tb.DIVIDER}\n\n🚧 Скоро будут добавлены!",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        return
    await tb.safe_edit_text(
        callback.message,
        f"📖 <b>Билеты теоретической части</b>\n{tb.DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_theory_tickets_keyboard()
    )

@router.callback_query(F.data.startswith("phys_theory_ticket:"))
async def cb_phys_theory_ticket(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = tb.PHYSICS_THEORY_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    await tb.safe_edit_text(
        callback.message,
        f"📖 <b>{ticket['title']}</b>\n{tb.DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_theory_ticket_detail_keyboard(num)
    )

@router.callback_query(F.data.startswith("phys_theory_q:"))
async def cb_phys_theory_question(callback: CallbackQuery):
    await callback.answer()
    _, num, idx_s = callback.data.split(":")
    idx = int(idx_s)
    ticket = tb.PHYSICS_THEORY_TICKETS.get(num)
    if not ticket or idx >= len(ticket["questions"]):
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    q = ticket["questions"][idx]
    header = f"📖 <b>{ticket['title']} — Вопрос {idx + 1}</b>"
    body = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    await tb.safe_edit_text(callback.message, body, parse_mode="HTML", reply_markup=tb.get_physics_theory_question_keyboard(num, idx))

@router.callback_query(F.data == "physics_test_tickets")
async def cb_physics_test_tickets(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📝 <b>Тестовые билеты</b>\n{tb.DIVIDER}\n\nВыбери вариант:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_test_tickets_keyboard()
    )

@router.callback_query(F.data.startswith("phys_test_ticket:"))
async def cb_phys_test_ticket(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = tb.PHYSICS_TEST_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    lines = [f"📄 <b>{ticket['title']}</b>", tb.DIVIDER]
    for question in ticket["questions"]:
        lines.append(f"\n<b>{question['num']}.</b> {question['text']}")
        for letter, option in question["options"].items():
            marker = "✅ " if letter == question["correct"] else ""
            lines.append(f"{marker}{letter}) {option}")
    text = "\n".join(lines)
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_test_ticket_detail_keyboard(num))

@router.callback_query(F.data.startswith("phys_test_ticket_tasks:"))
async def cb_phys_test_ticket_tasks(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = tb.PHYSICS_TEST_TICKETS.get(num)
    if not ticket or not ticket.get("tasks"):
        await callback.answer("Задачи не найдены", show_alert=True)
        return
    text = f"🧮 <b>{ticket['title']} — Часть 2. Задачи</b>\n{tb.DIVIDER}\n\nВыбери задачу:"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_test_ticket_task_list_keyboard(num))

@router.callback_query(F.data.startswith("phys_test_ticket_task_show:"))
async def cb_phys_test_ticket_task_show(callback: CallbackQuery):
    await callback.answer()
    _, num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    ticket = tb.PHYSICS_TEST_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    task = next((t for t in ticket.get("tasks", []) if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>{ticket['title']} — Задача №{task['num']}</b> — {task.get('title', '')}\n{tb.DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await tb.safe_edit_text(
        callback.message, text, parse_mode="HTML",
        reply_markup=tb.get_physics_test_ticket_task_detail_keyboard(num, task_num)
    )

@router.callback_query(F.data == "physics_task_tickets")
async def cb_physics_task_tickets(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🧮 <b>Билеты с задачами</b>\n{tb.DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_task_tickets_keyboard()
    )

@router.callback_query(F.data.startswith("phys_task_ticket:"))
async def cb_phys_task_ticket(callback: CallbackQuery):
    await callback.answer()
    num = callback.data.split(":")[1]
    ticket = tb.PHYSICS_TASK_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    text = f"🧮 <b>{ticket['title']}</b>\n{tb.DIVIDER}\n\nВыбери задачу:"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_task_ticket_list_keyboard(num))

@router.callback_query(F.data.startswith("phys_task_ticket_show:"))
async def cb_phys_task_ticket_show(callback: CallbackQuery):
    await callback.answer()
    _, num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    ticket = tb.PHYSICS_TASK_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    task = next((t for t in ticket.get("tasks", []) if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>{ticket['title']} — Задача №{task['num']}</b> — {task.get('title', '')}\n{tb.DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await tb.safe_edit_text(
        callback.message, text, parse_mode="HTML",
        reply_markup=tb.get_physics_task_ticket_detail_keyboard(num, task_num)
    )

@router.callback_query(F.data == "physics_test")
async def cb_physics_test(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📝 <b>Тестовая часть — Физика</b>\n{tb.DIVIDER}\n\nВыбери страницу:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_test_pages()
    )

@router.callback_query(F.data.startswith("physics_page:"))
async def cb_physics_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📄 <b>Физика — Страница {page}</b>\n{tb.DIVIDER}",
        parse_mode="HTML",
        reply_markup=tb.get_physics_question_keyboard(page)
    )

@router.callback_query(F.data.startswith("physics_q:"))
async def cb_physics_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in tb.PHYSICS_QUESTIONS:
        q = tb.PHYSICS_QUESTIONS[q_num]
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{tb.DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{q.get('title', '')}</b>"
        await tb.send_answer(callback.message, body, short_caption, q, tb.get_physics_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

@router.callback_query(F.data == "physics_grade45")
async def cb_physics_grade45(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"❓ <b>(60 вопросов) на 4/5</b>\n{tb.DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_grade45_keyboard()
    )

@router.callback_query(F.data.startswith("physics45_q:"))
async def cb_physics_grade45_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in tb.PHYSICS_GRADE45_QUESTIONS:
        q = tb.PHYSICS_GRADE45_QUESTIONS[q_num]
        header = f"❓ <b>Вопрос {q_num}</b>"
        body = f"{header}\n{tb.DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{q.get('title', '')}</b>"
        await tb.send_answer(callback.message, body, short_caption, q, tb.get_physics_grade45_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

@router.callback_query(F.data == "physics_extra")
async def cb_physics_extra(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"⭐ <b>Доп. вопросы от преподавателей</b>\n{tb.DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_extra_keyboard()
    )

@router.callback_query(F.data.startswith("physics_extra_q:"))
async def cb_physics_extra_question(callback: CallbackQuery):
    await callback.answer()
    q_num = callback.data.split(":")[1]
    if q_num in tb.PHYSICS_EXTRA_QUESTIONS:
        q = tb.PHYSICS_EXTRA_QUESTIONS[q_num]
        header = "⭐ <b>Доп. вопрос от преподавателей</b>"
        body = f"{header}\n{tb.DIVIDER}\n\n<b>{q.get('title', '')}</b>\n\n{q.get('answer', '')}"
        short_caption = f"{header}\n{tb.DIVIDER}\n\n<b>{q.get('title', '')}</b>"
        await tb.send_answer(callback.message, body, short_caption, q, tb.get_physics_extra_answer_keyboard(q_num), edit=True)
    else:
        await callback.answer("Вопрос пока не добавлен в файл", show_alert=True)

# ==================== ФИЗИКА - ЗАДАЧИ ====================
@router.callback_query(F.data == "physics_tasks")
async def cb_physics_tasks(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🧮 <b>Задачи по физике</b>\n{tb.DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=tb.get_physics_tasks_topics_keyboard()
    )

@router.callback_query(F.data.startswith("phystask_topic:"))
async def cb_phystask_topic(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = tb.PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = (
        f"📂 <b>{topic['title']}</b>\n{tb.DIVIDER}\n\n"
        f"{topic.get('intro', '')}\n\n"
        f"Всего типовых задач: {len(topic['tasks'])}"
    )
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_task_topic_keyboard(topic_num))

@router.callback_query(F.data.startswith("phystask_formulas:"))
async def cb_phystask_formulas(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = tb.PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📂 <b>{topic['title']}</b>\n{tb.DIVIDER}\n\n{topic['formulas']}"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_formulas_keyboard(topic_num))

@router.callback_query(F.data.startswith("phystask_list:"))
async def cb_phystask_list(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = tb.PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📋 <b>{topic['title']} — список задач</b>\n{tb.DIVIDER}\n\nВыбери задачу:"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_task_list_keyboard(topic_num))

@router.callback_query(F.data.startswith("phystask_show:"))
async def cb_phystask_show(callback: CallbackQuery):
    await callback.answer()
    _, topic_num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    topic = tb.PHYSICS_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    task = next((t for t in topic["tasks"] if t["num"] == task_num), None)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = (
        f"📝 <b>Задача №{task['num']}</b> — {task.get('title', '')}\n{tb.DIVIDER}\n\n"
        f"<b>Условие:</b>\n<i>{task['condition']}</i>\n\n"
        f"<b>Решение:</b>\n{task['solution']}"
    )
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_physics_task_detail_keyboard(topic_num, task_num))

