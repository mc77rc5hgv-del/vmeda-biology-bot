# -*- coding: utf-8 -*-
"""Раздел «Оперативная хирургия» — новый top-level предмет, свободный для всех (без реферального
гейта и без подписки, см. CLAUDE.md). Контент — operative_surgery.json: 23 занятия кафедральной
программы ВМедА, справочник проекций, каталог хирургических инструментов по группам.

Раздел сознательно НЕ полный: у каждого занятия реально заполнено только поле "summary" (сводка
под кнопкой "🎯 Что нужно знать") — остальные 12 граней карточки (ориентиры/слои/сосуды/фасции/
доступы/операции/инструменты/ошибки/мнемоники/контрольные вопросы/ответ за 2 минуты), которые
описаны в исходном ТЗ, пока не имеют реального материала (у самих исходников — Практикум ВМедА,
Николаев, альбом инструментов — в распоряжении есть только номера страниц, не текст). Кнопки для
всех граней тем не менее показываются (см. "hide vs relabel" в CLAUDE.md — не прятать точки входа),
но ведут на честный экран "материал ещё не добавлен", а не на выдуманный контент.

Импортирует telegram_bot как tb (не `from telegram_bot import ...`) по той же причине, что и
handlers/histology.py — сам telegram_bot.py импортирует этот модуль в самом конце файла, когда
все нужные отсюда имена (OPERATIVE_SURGERY, DIVIDER, safe_edit_text, OH_SEARCH_PENDING,
search_operative_surgery, html) уже определены в его модульном пространстве имён."""
import math

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

OH_CURRICULUM_PAGE_SIZE = 10

# (ключ в JSON-записи занятия, подпись кнопки) — порядок совпадает с исходным ТЗ. "must_know"
# показывается СРАЗУ на экране занятия (не отдельной кнопкой) — это единственная грань, где есть
# реальный текст (entry["summary"]), поэтому в списке кнопок ниже её нет.
OH_FACET_BUTTONS = [
    ("landmarks", "🧭 Ориентиры и границы"),
    ("layers", "🧱 Слои"),
    ("vessels_nerves", "🩸 Сосуды и нервы"),
    ("fascia_spaces", "🧩 Фасции и клетчаточные пространства"),
    ("projections_note", "📍 Проекции"),
    ("approaches", "✂️ Доступы"),
    ("operations", "🔪 Операции и приёмы"),
    ("instruments_note", "🛠 Инструменты"),
    ("pitfalls", "⚠️ Опасные места и ошибки"),
    ("mnemonics", "🧠 Как запомнить"),
    ("control_questions", "❓ Контрольные вопросы"),
    ("quick_answer", "⚡ Ответ за 2 минуты"),
]
OH_FACET_LABELS = dict(OH_FACET_BUTTONS)


def get_oh_lesson(lesson_id: str):
    for entry in tb.OPERATIVE_SURGERY["curriculum"]:
        if entry["id"] == lesson_id:
            return entry
    return None


def get_oh_menu_text() -> str:
    meta = tb.OPERATIVE_SURGERY["meta"]
    n_lessons = len(tb.OPERATIVE_SURGERY["curriculum"])
    n_proj = len(tb.OPERATIVE_SURGERY["projections"])
    n_instr = sum(len(g["items"]) for g in tb.OPERATIVE_SURGERY["instrument_groups"])
    return (
        f"🔪 <b>Оперативная хирургия</b>\n{tb.DIVIDER}\n\n"
        f"{meta['institution']}\n\n"
        f"📅 {n_lessons} занятий кафедральной программы\n"
        f"📍 {n_proj} проекций сосудов/нервов\n"
        f"🛠 {n_instr} инструментов по группам\n\n"
        "Раздел новый и наполняется постепенно — у каждого занятия пока готова только общая "
        "сводка «🎯 Что нужно знать», остальные разделы карточки добавляются по мере готовности "
        "материала.\n\nВыбери раздел:"
    )


def get_oh_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Занятия по программе ВМедА", callback_data="oh:curriculum:0")
    builder.button(text="📍 Проекции", callback_data="oh:projections")
    builder.button(text="🛠 Хирургические инструменты", callback_data="oh:instruments")
    builder.button(text="🔎 Поиск по ОХ", callback_data="oh:search_prompt")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()


def get_oh_curriculum_text(page: int) -> str:
    lessons = tb.OPERATIVE_SURGERY["curriculum"]
    total_pages = max(1, math.ceil(len(lessons) / OH_CURRICULUM_PAGE_SIZE))
    return (
        f"📅 <b>Занятия по программе ВМедА</b>\n{tb.DIVIDER}\n\n"
        f"Кафедральная программа, {len(lessons)} занятий. Страница {page + 1} из {total_pages}.\n"
        "🔁 — итоговое занятие (повторение)."
    )


def get_oh_curriculum_keyboard(page: int):
    lessons = tb.OPERATIVE_SURGERY["curriculum"]
    start = page * OH_CURRICULUM_PAGE_SIZE
    chunk = lessons[start:start + OH_CURRICULUM_PAGE_SIZE]
    builder = InlineKeyboardBuilder()
    for entry in chunk:
        prefix = "🔁 " if entry["is_review"] else ""
        builder.button(text=f"{prefix}{entry['id']}. {entry['title']}", callback_data=f"oh:lesson:{entry['id']}")
    builder.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"oh:curriculum:{page - 1}"))
    if start + OH_CURRICULUM_PAGE_SIZE < len(lessons):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"oh:curriculum:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


def _oh_lesson_back_page(lesson_id: str) -> int:
    return (int(lesson_id) - 1) // OH_CURRICULUM_PAGE_SIZE


def get_oh_lesson_text(entry: dict) -> str:
    pages = ", ".join(str(p) for p in entry["source_pages"])
    header = f"🔪 <b>{entry['id']}. {entry['title']}</b>\n{tb.DIVIDER}\n\nИсточник: {entry['source']}, стр. {pages}\n"
    if entry["is_review"]:
        return f"{header}\n🔁 {entry['review_note']}"
    return f"{header}\n🎯 <b>Что нужно знать</b>\n\n{entry['summary']}"


def get_oh_lesson_keyboard(entry: dict):
    builder = InlineKeyboardBuilder()
    if not entry["is_review"]:
        for key, label in OH_FACET_BUTTONS:
            builder.button(text=label, callback_data=f"oh:facet:{entry['id']}:{key}")
        builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К занятиям", callback_data=f"oh:curriculum:{_oh_lesson_back_page(entry['id'])}"))
    return builder.as_markup()


def get_oh_facet_text(entry: dict, key: str) -> str:
    label = OH_FACET_LABELS.get(key, key)
    value = entry.get(key)
    header = f"{label}\n{tb.DIVIDER}\n\n{entry['id']}. {entry['title']}\n\n"
    if value:
        return header + (value if isinstance(value, str) else "\n".join(f"• {v}" for v in value))
    return (
        header + "🚧 Материал по этому пункту ещё не добавлен — раздел наполняется постепенно.\n\n"
        "Уже доступно: 🎯 «Что нужно знать» — общая сводка по теме на экране занятия."
    )


def get_oh_facet_keyboard(lesson_id: str):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К занятию", callback_data=f"oh:lesson:{lesson_id}"))
    return builder.as_markup()


def get_oh_instruments_text() -> str:
    groups = tb.OPERATIVE_SURGERY["instrument_groups"]
    total = sum(len(g["items"]) for g in groups)
    return (
        f"🛠 <b>Хирургические инструменты ВМедА</b>\n{tb.DIVIDER}\n\n"
        f"{total} инструментов по {len(groups)} группам — из кафедрального экзаменационного "
        "альбома. Фото и описание назначения добавляются постепенно, пока доступны названия "
        "по группам.\n\nВыбери группу:"
    )


def get_oh_instruments_keyboard():
    builder = InlineKeyboardBuilder()
    for idx, group in enumerate(tb.OPERATIVE_SURGERY["instrument_groups"]):
        builder.button(text=f"{group['group']} ({len(group['items'])})", callback_data=f"oh:instr_group:{idx}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


def get_oh_instrument_group_text(idx: int) -> str:
    group = tb.OPERATIVE_SURGERY["instrument_groups"][idx]
    names = "\n".join(f"• {item['name']}" for item in group["items"])
    return (
        f"🛠 <b>{group['group']}</b>\n{tb.DIVIDER}\n\n{names}\n\n"
        "Фото и назначение для этой группы пока не добавлены."
    )


def get_oh_instrument_group_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К группам", callback_data="oh:instruments"))
    return builder.as_markup()


def get_oh_projections_text() -> str:
    lines = [f"📍 <b>Проекции — быстрый справочник</b>\n{tb.DIVIDER}"]
    for p in tb.OPERATIVE_SURGERY["projections"]:
        lines.append(f"\n<b>{p['structure']}</b>\n{p['projection']}")
    return "\n".join(lines)


def get_oh_projections_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


@router.callback_query(F.data == "oh:menu")
async def cb_oh_menu(callback: CallbackQuery):
    await callback.answer()
    tb.OH_SEARCH_PENDING.discard(callback.from_user.id)
    await tb.safe_edit_text(callback.message, get_oh_menu_text(), parse_mode="HTML", reply_markup=get_oh_menu_keyboard())


@router.callback_query(F.data.startswith("oh:curriculum:"))
async def cb_oh_curriculum(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_curriculum_text(page), parse_mode="HTML", reply_markup=get_oh_curriculum_keyboard(page)
    )


@router.callback_query(F.data.startswith("oh:lesson:"))
async def cb_oh_lesson(callback: CallbackQuery):
    lesson_id = callback.data.split(":")[2]
    entry = get_oh_lesson(lesson_id)
    if entry is None:
        await callback.answer("Занятие не найдено", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_lesson_text(entry), parse_mode="HTML", reply_markup=get_oh_lesson_keyboard(entry)
    )


@router.callback_query(F.data.startswith("oh:facet:"))
async def cb_oh_facet(callback: CallbackQuery):
    _, _, lesson_id, key = callback.data.split(":")
    entry = get_oh_lesson(lesson_id)
    if entry is None:
        await callback.answer("Занятие не найдено", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_facet_text(entry, key), parse_mode="HTML", reply_markup=get_oh_facet_keyboard(lesson_id)
    )


@router.callback_query(F.data == "oh:instruments")
async def cb_oh_instruments(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_instruments_text(), parse_mode="HTML", reply_markup=get_oh_instruments_keyboard()
    )


@router.callback_query(F.data.startswith("oh:instr_group:"))
async def cb_oh_instrument_group(callback: CallbackQuery):
    idx = int(callback.data.split(":")[2])
    groups = tb.OPERATIVE_SURGERY["instrument_groups"]
    if not (0 <= idx < len(groups)):
        await callback.answer("Группа не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_instrument_group_text(idx), parse_mode="HTML", reply_markup=get_oh_instrument_group_keyboard()
    )


@router.callback_query(F.data == "oh:projections")
async def cb_oh_projections(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_projections_text(), parse_mode="HTML", reply_markup=get_oh_projections_keyboard()
    )


@router.callback_query(F.data == "oh:search_prompt")
async def cb_oh_search_prompt(callback: CallbackQuery):
    await callback.answer()
    tb.OH_SEARCH_PENDING.add(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    await tb.safe_edit_text(
        callback.message,
        f"🔎 <b>Поиск по Оперативной хирургии</b>\n{tb.DIVIDER}\n\n"
        "Отправь ключевое слово — поищу по занятиям, инструментам и проекциям.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
