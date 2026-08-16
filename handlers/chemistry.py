"""Раздел «Химия» (теория с навигацией, билеты, задачи, лабораторные работы) — Router вместо
прямой регистрации на глобальном dp (Phase 3 рефакторинга, см. CLAUDE.md — та же схема, что у
Гистологии/Анатомии/Биологии/Физики). Импортирует telegram_bot как tb — циклическая связь
разрешается тем, что этот импорт стоит там же, где раньше стояла эта секция.

Узкий срез, как и с Биологией/Физикой: только сами callback_query-хендлеры (все с уникальными
фильтрами, безопасно для порядка dp — здесь нет ни одного @dp.message). Клавиатурные билдеры и
`chemistry_tickets_access_ok` (секция "ХИМИЯ" в начале файла) НЕ перенесены — используются и
хендлерами отсюда, и cb_menu_chemistry/download_chemistry_*, которые остаются в telegram_bot.py."""
from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

# ==================== ХИМИЯ - ТЕОРИЯ (С НАВИГАЦИЕЙ) ====================
@router.callback_query(F.data == "chemistry_theory")
async def cb_chemistry_theory(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📚 <b>Теория по химии</b>\n{tb.DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_theory_list()
    )

@router.callback_query(F.data.startswith("chem_theory:"))
async def cb_show_theory_topic(callback: CallbackQuery):
    await callback.answer()
    num = int(callback.data.split(":")[1])
    topic = tb.CHEMISTRY_THEORY.get(str(num))
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📖 <b>{topic['title']}</b>\n{tb.DIVIDER}\n\n{topic['content']}"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_theory_navigation(num))

@router.callback_query(F.data == "chemistry_theory_list")
async def cb_theory_list(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📚 <b>Теория по химии</b>\n{tb.DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_theory_list()
    )

# ==================== ХИМИЯ - БИЛЕТЫ ====================
@router.callback_query(F.data == "chemistry_tickets")
async def cb_chemistry_tickets(callback: CallbackQuery):
    await callback.answer()
    if not tb.chemistry_tickets_access_ok(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            tb.get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=tb.get_chemistry_tickets_locked_keyboard()
        )
        return
    await tb.safe_edit_text(
        callback.message,
        f"🎫 <b>Билеты по химии</b>\n{tb.DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_tickets_menu()
    )

@router.callback_query(F.data == "chem_theory_tickets")
async def cb_chem_theory_tickets(callback: CallbackQuery):
    await callback.answer()
    if not tb.chemistry_tickets_access_ok(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            tb.get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=tb.get_chemistry_tickets_locked_keyboard()
        )
        return
    await tb.safe_edit_text(
        callback.message,
        f"📖 <b>Билеты теории</b>\n{tb.DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_theory_tickets_keyboard()
    )

@router.callback_query(F.data.startswith("chem_theory_ticket:"))
async def cb_chem_theory_ticket(callback: CallbackQuery):
    await callback.answer()
    if not tb.chemistry_tickets_access_ok(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            tb.get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=tb.get_chemistry_tickets_locked_keyboard()
        )
        return
    num = callback.data.split(":")[1]
    ticket = tb.CHEMISTRY_THEORY_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    await tb.safe_edit_text(
        callback.message,
        f"📖 <b>{ticket['title']}</b>\n{tb.DIVIDER}\n\nВыбери вопрос:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_theory_ticket_detail_keyboard(num)
    )

@router.callback_query(F.data.startswith("chem_theory_q:"))
async def cb_chem_theory_question(callback: CallbackQuery):
    await callback.answer()
    if not tb.chemistry_tickets_access_ok(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            tb.get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=tb.get_chemistry_tickets_locked_keyboard()
        )
        return
    _, num, idx_s = callback.data.split(":")
    idx = int(idx_s)
    ticket = tb.CHEMISTRY_THEORY_TICKETS.get(num)
    if not ticket or idx >= len(ticket["questions"]):
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    q = ticket["questions"][idx]
    header = f"📖 <b>{ticket['title']} — Вопрос {idx + 1}</b>"
    body = f"{header}\n{tb.DIVIDER}\n\n<b>{q['title']}</b>\n\n{q['answer']}"
    await tb.safe_edit_text(callback.message, body, parse_mode="HTML", reply_markup=tb.get_chemistry_theory_question_keyboard(num, idx))

@router.callback_query(F.data == "chem_practice_tickets")
async def cb_chem_practice_tickets(callback: CallbackQuery):
    await callback.answer()
    if not tb.chemistry_tickets_access_ok(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            tb.get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=tb.get_chemistry_tickets_locked_keyboard()
        )
        return
    await tb.safe_edit_text(
        callback.message,
        f"🧮 <b>Билеты практики</b>\n{tb.DIVIDER}\n\nВыбери билет:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_practice_tickets_keyboard()
    )

@router.callback_query(F.data.startswith("chem_practice_ticket:"))
async def cb_chem_practice_ticket(callback: CallbackQuery):
    await callback.answer()
    if not tb.chemistry_tickets_access_ok(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            tb.get_chemistry_tickets_locked_text(),
            parse_mode="HTML",
            reply_markup=tb.get_chemistry_tickets_locked_keyboard()
        )
        return
    num = callback.data.split(":")[1]
    ticket = tb.CHEMISTRY_PRACTICE_TICKETS.get(num)
    if not ticket:
        await callback.answer("Билет не найден", show_alert=True)
        return
    text = f"🧮 <b>{ticket['title']}</b>\n{tb.DIVIDER}\n\n{ticket['content']}"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_chemistry_practice_ticket_keyboard())

# ==================== ХИМИЯ - ЗАДАЧИ ====================
@router.callback_query(F.data == "chemistry_tasks")
async def cb_chemistry_tasks(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📝 <b>Задачи по химии</b>\n{tb.DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=tb.get_chemistry_tasks_topics_keyboard()
    )

@router.callback_query(F.data.startswith("chemtask_topic:"))
async def cb_chemtask_topic(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = tb.CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = (
        f"📂 <b>{topic['title']}</b>\n{tb.DIVIDER}\n\n"
        f"{topic.get('intro', '')}\n\n"
        f"Всего типовых задач: {len(topic['tasks'])}"
    )
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_chemistry_task_topic_keyboard(topic_num))

@router.callback_query(F.data.startswith("chemtask_formulas:"))
async def cb_chemtask_formulas(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = tb.CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📂 <b>{topic['title']}</b>\n{tb.DIVIDER}\n\n{topic['formulas']}"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_chemistry_formulas_keyboard(topic_num))

@router.callback_query(F.data.startswith("chemtask_list:"))
async def cb_chemtask_list(callback: CallbackQuery):
    await callback.answer()
    topic_num = callback.data.split(":")[1]
    topic = tb.CHEMISTRY_TASKS.get(topic_num)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    text = f"📋 <b>{topic['title']} — список задач</b>\n{tb.DIVIDER}\n\nВыбери задачу:"
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_chemistry_task_list_keyboard(topic_num))

@router.callback_query(F.data.startswith("chemtask_show:"))
async def cb_chemtask_show(callback: CallbackQuery):
    await callback.answer()
    _, topic_num, task_num_s = callback.data.split(":")
    task_num = int(task_num_s)
    topic = tb.CHEMISTRY_TASKS.get(topic_num)
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
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=tb.get_chemistry_task_detail_keyboard(topic_num, task_num))

# ==================== ХИМИЯ - ЛАБОРАТОРНЫЕ РАБОТЫ ====================
@router.callback_query(F.data == "chemistry_labs")
async def cb_chemistry_labs(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🧪 <b>Лабораторные работы по химии</b>\n{tb.DIVIDER}\n\nВыбери лабораторную работу:",
        parse_mode="HTML",
        reply_markup=tb.get_labs_keyboard()
    )

@router.callback_query(F.data.startswith("lab:"))
async def cb_show_lab(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in tb.CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab:
        await callback.answer("Лабораторная работа не найдена", show_alert=True)
        return
    text = (
        f"🧪 <b>Лабораторная работа {lab['number']}</b>\n"
        f"{tb.DIVIDER}\n\n"
        f"<b>Тема:</b> {lab.get('theme', '')}\n\n"
        f"<b>Условие:</b>\n{lab.get('condition', '')}"
    )
    builder = InlineKeyboardBuilder()
    if lab.get("experiments"):
        builder.button(text="🔬 Опыты", callback_data=f"lab_exp:{lab_num}")
    if lab.get("calculations"):
        builder.button(text="📐 Расчёты", callback_data=f"lab_calc:{lab_num}")
    if lab.get("summary"):
        builder.button(text="📝 Кратко (конспект)", callback_data=f"lab_summary:{lab_num}")
    builder.button(text="🔙 Назад к лабам", callback_data="chemistry_labs")
    builder.adjust(1)
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("lab_summary:"))
async def cb_lab_summary(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in tb.CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab or not lab.get("summary"):
        await callback.answer("Конспект не найден", show_alert=True)
        return
    text = f"📝 <b>Кратко — Лабораторная работа {lab_num}</b>\n{tb.DIVIDER}\n\n{lab['summary']}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("lab_exp:"))
async def cb_lab_experiments(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in tb.CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab or not lab.get("experiments"):
        await callback.answer("Опыты не найдены", show_alert=True)
        return
    text = f"🔬 <b>Опыты — Лабораторная работа {lab_num}</b>\n{tb.DIVIDER}\n\n"
    for exp in lab["experiments"]:
        text += f"<b>{exp.get('name', '')}</b>\n{exp.get('description', '')}\n\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("lab_calc:"))
async def cb_lab_calculations(callback: CallbackQuery):
    await callback.answer()
    lab_num = int(callback.data.split(":")[1])
    lab = next((entry for entry in tb.CHEMISTRY_LABS["labs"] if entry["number"] == lab_num), None)
    if not lab or not lab.get("calculations"):
        await callback.answer("Расчёты не найдены", show_alert=True)
        return
    text = f"📐 <b>Расчёты — Лабораторная работа {lab_num}</b>\n{tb.DIVIDER}\n\n{lab['calculations']}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"lab:{lab_num}")
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())

