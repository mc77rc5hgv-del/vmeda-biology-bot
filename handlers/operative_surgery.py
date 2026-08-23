# -*- coding: utf-8 -*-
"""Раздел «Оперативная хирургия» — top-level предмет, свободный для всех (без реферального гейта
и без подписки, см. CLAUDE.md). Контент — operative_surgery.json v2: полный текст 61 темы
(4 тома, кафедральная программа+учебник ВМедА, источник: "VMEDA Operative Surgery Full Content"
пакет), справочник проекций (6 групп), каталог хирургических инструментов (10 групп),
практические станции (2 группы).

В отличие от версии 1 (23 занятия-заглушки с одним полем summary на занятие), здесь у КАЖДОЙ темы
есть реальный полнотекстовый материал (тема -> подтемы -> текст), автоматически извлечённый
"Быстро повторить" (реальные фразы-акценты из текста — "Запомнить"/"Практическое значение" и
т. п. — не придуманные заново) и, где источник их реально даёт, контрольные вопросы. Источник
даёт вопросы только на двух уровнях: у темы "01. Общая оперативная техника" — свои собственные
(§1.8 исходного материала), и у томов I/II/III — сводные вопросы по всему тому ("Контроль тома");
у тома IV такого списка в источнике нет вообще — честно нет кнопки контроля для этого тома, а не
выдуманные вопросы (тот же принцип "честной неполноты", что и в v1 — см. CLAUDE.md). Ответы на
контрольные вопросы в источнике не даны, поэтому это не quiz с проверкой, а список для
самопроверки перед/после чтения полного материала соответствующей темы/тома.

Импортирует telegram_bot как tb (не `from telegram_bot import ...`) по той же причине, что и
handlers/histology.py — сам telegram_bot.py импортирует этот модуль в самом конце файла, когда
все нужные отсюда имена (OPERATIVE_SURGERY, DIVIDER, safe_edit_text, OH_SEARCH_PENDING,
search_operative_surgery) уже определены в его модульном пространстве имён.

Инструменты (instrument_groups) — единственная грань раздела с фото: список/названия/группы — из
кафедрального экзаменационного альбома ВМедА (11 групп, 97 позиций, включая позднее добавленную
группу «Пластинчатые швы»), но сами ФОТОГРАФИИ, начиная с этого пака, в основном НЕ кафедральные —
94 из 97 это типовые снимки того же инструмента с открытых источников (см. image_source в JSON —
"web" против "reference_album" для тех немногих позиций, где есть настоящий кроп кафедрального
альбома); это осознанный компромисс качества ради полного покрытия, сделанный явно по запросу — см.
честную оговорку в get_oh_instruments_text(). Каждый item — {"name": str, "image": str,
"image_source": "web"|"reference_album"}; `oh_group_has_photos()` решает по группе целиком (все
позиции с фото или ни одной) — показывать ЧАСТИЧНО заполненный фотоальбом с необъяснённым пропуском
было бы хуже, чем честный текстовый список (`get_oh_instrument_group_text` остаётся рабочим
fallback на случай будущей группы/позиции без фото)."""
import json
import math
import os

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

OH_TOPIC_PAGE_SIZE = 10
OH_INSTR_ALBUM_PAGE_SIZE = 10  # sendMediaGroup hard cap — same reasoning as anatomy's ANATOMY_ALBUM_PAGE_SIZE

OH_INSTRUMENTS_IMAGES_DIR = os.path.join(tb.IMAGES_DIR, "operative_surgery", "instruments")
OH_FILE_ID_CACHE_PATH = os.path.join(tb.STATS_DIR, "oh_instrument_file_id_cache.json")


def _load_oh_file_id_cache() -> dict:
    try:
        with open(OH_FILE_ID_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


OH_FILE_ID_CACHE: dict[str, str] = _load_oh_file_id_cache()


def _write_oh_file_id_cache(data: dict) -> None:
    tmp_path = f"{OH_FILE_ID_CACHE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, OH_FILE_ID_CACHE_PATH)


def save_oh_file_id_cache() -> None:
    data = dict(OH_FILE_ID_CACHE)
    future = tb._stats_executor.submit(_write_oh_file_id_cache, data)
    future.add_done_callback(tb._log_stats_write_result)


def _oh_instrument_image_media(item: dict):
    cached = OH_FILE_ID_CACHE.get(item["image"])
    if cached:
        return cached
    return FSInputFile(os.path.join(OH_INSTRUMENTS_IMAGES_DIR, item["image"]))


def _cache_oh_instrument_file_id(item: dict, sent_message) -> bool:
    """Mirrors handlers/anatomy.py's _cache_anatomy_file_id — safe no-op when sent_message has
    no real Telegram .photo (e.g. test mocks)."""
    key = item["image"]
    if key in OH_FILE_ID_CACHE:
        return False
    photo_sizes = getattr(sent_message, "photo", None)
    if not photo_sizes:
        return False
    OH_FILE_ID_CACHE[key] = photo_sizes[-1].file_id
    return True


def oh_group_has_photos(group: dict) -> bool:
    return bool(group["items"]) and all("image" in item for item in group["items"])


def oh_instrument_page_count(n_items: int) -> int:
    return max(1, (n_items + OH_INSTR_ALBUM_PAGE_SIZE - 1) // OH_INSTR_ALBUM_PAGE_SIZE)


def _oh_instrument_media(item: dict) -> InputMediaPhoto:
    return InputMediaPhoto(media=_oh_instrument_image_media(item), caption=item["name"])


async def send_oh_instrument_album(callback: CallbackQuery, group: dict, idx: int, page: int):
    """Sends up to OH_INSTR_ALBUM_PAGE_SIZE instrument photos as one native Telegram album —
    same shape as handlers/anatomy.py's send_anatomy_album (sendMediaGroup can't carry a
    reply_markup, so prev/next/back follow as a separate small text message)."""
    items = group["items"]
    total_pages = oh_instrument_page_count(len(items))
    start = page * OH_INSTR_ALBUM_PAGE_SIZE
    chunk = items[start:start + OH_INSTR_ALBUM_PAGE_SIZE]
    await callback.message.delete()
    cache_changed = False
    if len(chunk) == 1:
        # sendMediaGroup requires 2-10 items — a lone photo must go through answer_photo instead.
        item = chunk[0]
        sent = await callback.message.answer_photo(_oh_instrument_image_media(item), caption=item["name"])
        cache_changed = _cache_oh_instrument_file_id(item, sent)
    else:
        media = [_oh_instrument_media(item) for item in chunk]
        sent_list = await callback.message.answer_media_group(media=media)
        for item, sent in zip(chunk, sent_list or []):
            if _cache_oh_instrument_file_id(item, sent):
                cache_changed = True
    if cache_changed:
        save_oh_file_id_cache()
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"oh:instr_group:{idx}:{page - 1}"))
    if start + OH_INSTR_ALBUM_PAGE_SIZE < len(items):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"oh:instr_group:{idx}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К группам", callback_data="oh:instruments"))
    await callback.message.answer(
        f"🛠 <b>{group['group']}</b> ({page + 1}/{total_pages})", parse_mode="HTML", reply_markup=builder.as_markup()
    )


# ==================== data lookups ====================

def get_oh_topic(topic_id: str):
    for topic in tb.OPERATIVE_SURGERY["topics"]:
        if topic["id"] == topic_id:
            return topic
    return None


def get_oh_volume(volume_id: str):
    for volume in tb.OPERATIVE_SURGERY["volumes"]:
        if volume["id"] == volume_id:
            return volume
    return None


def _oh_topic_back_page(topic: dict) -> int:
    volume = get_oh_volume(topic["volume"])
    idx = volume["topic_ids"].index(topic["id"]) if volume else 0
    return idx // OH_TOPIC_PAGE_SIZE


# ==================== root menu ====================

def get_oh_menu_text() -> str:
    meta = tb.OPERATIVE_SURGERY["meta"]
    n_topics = len(tb.OPERATIVE_SURGERY["topics"])
    n_vol = len(tb.OPERATIVE_SURGERY["volumes"])
    n_proj = sum(len(g["items"]) for g in tb.OPERATIVE_SURGERY["projections"])
    n_instr = sum(len(g["items"]) for g in tb.OPERATIVE_SURGERY["instrument_groups"])
    return (
        f"🔪 <b>Оперативная хирургия</b>\n{tb.DIVIDER}\n\n"
        f"{meta['institution']}\n\n"
        f"📚 {n_topics} тем в {n_vol} томах — полный материал по анатомии → топографии → "
        "хирургическому риску → обоснованию доступа/приёма\n"
        f"📍 {n_proj} проекций сосудов и нервов\n"
        f"🛠 {n_instr} инструментов по группам\n"
        "🎓 Практические станции ВМедА\n\n"
        "Выбери раздел:"
    )


def get_oh_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Темы по томам", callback_data="oh:volumes")
    builder.button(text="📍 Проекции", callback_data="oh:projections")
    builder.button(text="🛠 Хирургические инструменты", callback_data="oh:instruments")
    builder.button(text="🎓 Практические станции", callback_data="oh:stations")
    builder.button(text="🔎 Поиск по ОХ", callback_data="oh:search_prompt")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()


# ==================== volumes ====================

def get_oh_volumes_text() -> str:
    lines = [f"📚 <b>Темы по томам</b>\n{tb.DIVIDER}\n"]
    for v in tb.OPERATIVE_SURGERY["volumes"]:
        lines.append(f"Том {v['id']} — {v['title']} ({len(v['topic_ids'])} тем)")
    return "\n".join(lines)


def get_oh_volumes_keyboard():
    builder = InlineKeyboardBuilder()
    for v in tb.OPERATIVE_SURGERY["volumes"]:
        builder.button(text=f"Том {v['id']} — {v['title']}", callback_data=f"oh:volume:{v['id']}:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


def get_oh_volume_text(volume: dict, page: int) -> str:
    total_pages = max(1, math.ceil(len(volume["topic_ids"]) / OH_TOPIC_PAGE_SIZE))
    return (
        f"📚 <b>Том {volume['id']} — {volume['title']}</b>\n{tb.DIVIDER}\n\n"
        f"{len(volume['topic_ids'])} тем. Страница {page + 1} из {total_pages}."
    )


def get_oh_volume_keyboard(volume: dict, page: int):
    start = page * OH_TOPIC_PAGE_SIZE
    chunk = volume["topic_ids"][start:start + OH_TOPIC_PAGE_SIZE]
    builder = InlineKeyboardBuilder()
    for topic_id in chunk:
        topic = get_oh_topic(topic_id)
        if topic:
            builder.button(text=f"{topic['number']}. {topic['title']}", callback_data=f"oh:topic:{topic_id}")
    builder.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"oh:volume:{volume['id']}:{page - 1}"))
    if start + OH_TOPIC_PAGE_SIZE < len(volume["topic_ids"]):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"oh:volume:{volume['id']}:{page + 1}"))
    if nav:
        builder.row(*nav)
    if volume["control_questions"]:
        builder.row(InlineKeyboardButton(text="📋 Контрольные вопросы тома", callback_data=f"oh:vcontrol:{volume['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 К томам", callback_data="oh:volumes"))
    return builder.as_markup()


def get_oh_volume_control_text(volume: dict) -> str:
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(volume["control_questions"], 1))
    return (
        f"📋 <b>Контрольные вопросы — том {volume['id']}</b>\n{tb.DIVIDER}\n\n{qs}\n\n"
        "Ответы в явном виде не даны — это вопросы для самопроверки, ответ ищи в полном материале "
        "тем этого тома."
    )


def get_oh_volume_control_keyboard(volume_id: str):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К тому", callback_data=f"oh:volume:{volume_id}:0"))
    return builder.as_markup()


# ==================== topic hub ====================

def get_oh_topic_text(topic: dict) -> str:
    intro = topic["subtopics"][0]["text"].split("\n\n")[0]
    return (
        f"🔪 <b>{topic['number']}. {topic['title']}</b>\n{tb.DIVIDER}\n\n"
        f"Том {topic['volume']} · источник: {topic['source']}\n\n{intro}"
    )


def get_oh_topic_keyboard(topic: dict):
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Полный материал", callback_data=f"oh:material:{topic['id']}:0")
    builder.button(text="⚡ Быстро повторить", callback_data=f"oh:quick:{topic['id']}")
    if topic["control_questions"]:
        builder.button(text="❓ Контрольные вопросы", callback_data=f"oh:tcontrol:{topic['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(
        text="🔙 К теме тома", callback_data=f"oh:volume:{topic['volume']}:{_oh_topic_back_page(topic)}"
    ))
    return builder.as_markup()


def get_oh_material_text(topic: dict, page: int) -> str:
    sub = topic["subtopics"][page]
    total = len(topic["subtopics"])
    title_line = f"<b>{sub['title']}</b>\n\n" if sub["title"] and sub["title"] != topic["title"] else ""
    return (
        f"🔪 <b>{topic['number']}. {topic['title']}</b> ({page + 1}/{total})\n{tb.DIVIDER}\n\n"
        f"{title_line}{sub['text']}"
    )


def get_oh_material_keyboard(topic: dict, page: int):
    total = len(topic["subtopics"])
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"oh:material:{topic['id']}:{page - 1}"))
    if page + 1 < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"oh:material:{topic['id']}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К теме", callback_data=f"oh:topic:{topic['id']}"))
    return builder.as_markup()


def get_oh_quick_text(topic: dict) -> str:
    bullets = "\n\n".join(f"• {b}" for b in topic["quick_review"])
    return f"⚡ <b>Быстро повторить — {topic['number']}. {topic['title']}</b>\n{tb.DIVIDER}\n\n{bullets}"


def get_oh_quick_keyboard(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К теме", callback_data=f"oh:topic:{topic_id}"))
    return builder.as_markup()


def get_oh_topic_control_text(topic: dict) -> str:
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(topic["control_questions"], 1))
    return (
        f"❓ <b>Контрольные вопросы — {topic['number']}. {topic['title']}</b>\n{tb.DIVIDER}\n\n{qs}\n\n"
        "Ответы в явном виде не даны — ответ ищи в полном материале темы."
    )


def get_oh_topic_control_keyboard(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К теме", callback_data=f"oh:topic:{topic_id}"))
    return builder.as_markup()


# ==================== instruments ====================

def get_oh_instruments_text() -> str:
    groups = tb.OPERATIVE_SURGERY["instrument_groups"]
    total = sum(len(g["items"]) for g in groups)
    n_with_photos = sum(1 for g in groups if oh_group_has_photos(g))
    photo_note = (
        "У всех есть фото." if n_with_photos == len(groups)
        else f"У {n_with_photos} из {len(groups)} групп уже есть фото, остальные добавляются по мере поступления материала."
    )
    return (
        f"🛠 <b>Хирургические инструменты ВМедА</b>\n{tb.DIVIDER}\n\n"
        f"{total} инструментов по {len(groups)} группам — список и названия из кафедрального "
        f"экзаменационного альбома. {photo_note} Фото — типовые образцы этих инструментов "
        "(кроме отдельных позиций — точных снимков из кафедрального альбома), могут немного "
        "отличаться от конкретного экземпляра на кафедре.\n\nВыбери группу:"
    )


def get_oh_instruments_keyboard():
    builder = InlineKeyboardBuilder()
    for idx, group in enumerate(tb.OPERATIVE_SURGERY["instrument_groups"]):
        photo_mark = "📷 " if oh_group_has_photos(group) else ""
        builder.button(
            text=f"{photo_mark}{group['group']} ({len(group['items'])})", callback_data=f"oh:instr_group:{idx}:0"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


def get_oh_instrument_group_text(idx: int) -> str:
    group = tb.OPERATIVE_SURGERY["instrument_groups"][idx]
    names = "\n".join(f"• {item['name']}" for item in group["items"])
    return f"🛠 <b>{group['group']}</b>\n{tb.DIVIDER}\n\n{names}"


def get_oh_instrument_group_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К группам", callback_data="oh:instruments"))
    return builder.as_markup()


# ==================== projections ====================

def get_oh_projections_text() -> str:
    groups = tb.OPERATIVE_SURGERY["projections"]
    total = sum(len(g["items"]) for g in groups)
    return (
        f"📍 <b>Проекции сосудов и нервов</b>\n{tb.DIVIDER}\n\n"
        f"{total} проекций по {len(groups)} областям.\n\nВыбери область:"
    )


def get_oh_projections_keyboard():
    builder = InlineKeyboardBuilder()
    for idx, group in enumerate(tb.OPERATIVE_SURGERY["projections"]):
        builder.button(text=f"{group['group']} ({len(group['items'])})", callback_data=f"oh:proj_group:{idx}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


def get_oh_projection_group_text(idx: int) -> str:
    group = tb.OPERATIVE_SURGERY["projections"][idx]
    lines = [f"📍 <b>{group['group']}</b>\n{tb.DIVIDER}"]
    for item in group["items"]:
        lines.append(f"\n<b>{item['structure']}</b>\n{item['projection']}")
    return "\n".join(lines)


def get_oh_projection_group_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К областям", callback_data="oh:projections"))
    return builder.as_markup()


# ==================== practical stations ====================

def get_oh_stations_text() -> str:
    groups = tb.OPERATIVE_SURGERY["practical_stations"]
    total = sum(len(g["items"]) for g in groups)
    return (
        f"🎓 <b>Практические станции ВМедА</b>\n{tb.DIVIDER}\n\n"
        f"{total} станций по {len(groups)} группам.\n\nВыбери группу:"
    )


def get_oh_stations_keyboard():
    builder = InlineKeyboardBuilder()
    for idx, group in enumerate(tb.OPERATIVE_SURGERY["practical_stations"]):
        builder.button(text=f"{group['group']} ({len(group['items'])})", callback_data=f"oh:station_group:{idx}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="oh:menu"))
    return builder.as_markup()


def get_oh_station_group_text(idx: int) -> str:
    group = tb.OPERATIVE_SURGERY["practical_stations"][idx]
    items = "\n".join(f"• {item}" for item in group["items"])
    return f"🎓 <b>{group['group']}</b>\n{tb.DIVIDER}\n\n{items}"


def get_oh_station_group_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К группам", callback_data="oh:stations"))
    return builder.as_markup()


# ==================== handlers ====================

@router.callback_query(F.data == "oh:menu")
async def cb_oh_menu(callback: CallbackQuery):
    await callback.answer()
    tb.OH_SEARCH_PENDING.discard(callback.from_user.id)
    await tb.safe_edit_text(callback.message, get_oh_menu_text(), parse_mode="HTML", reply_markup=get_oh_menu_keyboard())


@router.callback_query(F.data == "oh:volumes")
async def cb_oh_volumes(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(callback.message, get_oh_volumes_text(), parse_mode="HTML", reply_markup=get_oh_volumes_keyboard())


@router.callback_query(F.data.startswith("oh:volume:"))
async def cb_oh_volume(callback: CallbackQuery):
    _, _, volume_id, page_s = callback.data.split(":")
    volume = get_oh_volume(volume_id)
    if volume is None:
        await callback.answer("Том не найден", show_alert=True)
        return
    await callback.answer()
    page = int(page_s)
    await tb.safe_edit_text(
        callback.message, get_oh_volume_text(volume, page), parse_mode="HTML",
        reply_markup=get_oh_volume_keyboard(volume, page)
    )


@router.callback_query(F.data.startswith("oh:vcontrol:"))
async def cb_oh_volume_control(callback: CallbackQuery):
    volume_id = callback.data.split(":")[2]
    volume = get_oh_volume(volume_id)
    if volume is None or not volume["control_questions"]:
        await callback.answer("Вопросы не найдены", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_volume_control_text(volume), parse_mode="HTML",
        reply_markup=get_oh_volume_control_keyboard(volume_id)
    )


@router.callback_query(F.data.startswith("oh:topic:"))
async def cb_oh_topic(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_oh_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_topic_text(topic), parse_mode="HTML", reply_markup=get_oh_topic_keyboard(topic)
    )


@router.callback_query(F.data.startswith("oh:material:"))
async def cb_oh_material(callback: CallbackQuery):
    _, _, topic_id, page_s = callback.data.split(":")
    topic = get_oh_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    page = int(page_s)
    if not (0 <= page < len(topic["subtopics"])):
        await callback.answer("Страница не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_material_text(topic, page), parse_mode="HTML",
        reply_markup=get_oh_material_keyboard(topic, page)
    )


@router.callback_query(F.data.startswith("oh:quick:"))
async def cb_oh_quick(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_oh_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_quick_text(topic), parse_mode="HTML", reply_markup=get_oh_quick_keyboard(topic_id)
    )


@router.callback_query(F.data.startswith("oh:tcontrol:"))
async def cb_oh_topic_control(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_oh_topic(topic_id)
    if topic is None or not topic["control_questions"]:
        await callback.answer("Вопросы не найдены", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_topic_control_text(topic), parse_mode="HTML",
        reply_markup=get_oh_topic_control_keyboard(topic_id)
    )


@router.callback_query(F.data == "oh:instruments")
async def cb_oh_instruments(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_instruments_text(), parse_mode="HTML", reply_markup=get_oh_instruments_keyboard()
    )


@router.callback_query(F.data.startswith("oh:instr_group:"))
async def cb_oh_instrument_group(callback: CallbackQuery):
    parts = callback.data.split(":")
    idx = int(parts[2])
    groups = tb.OPERATIVE_SURGERY["instrument_groups"]
    if not (0 <= idx < len(groups)):
        await callback.answer("Группа не найдена", show_alert=True)
        return
    group = groups[idx]
    if oh_group_has_photos(group):
        page = int(parts[3]) if len(parts) > 3 else 0
        if not (0 <= page < oh_instrument_page_count(len(group["items"]))):
            await callback.answer("Страница не найдена", show_alert=True)
            return
        await callback.answer()
        await send_oh_instrument_album(callback, group, idx, page)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_instrument_group_text(idx), parse_mode="HTML",
        reply_markup=get_oh_instrument_group_keyboard()
    )


@router.callback_query(F.data == "oh:projections")
async def cb_oh_projections(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_projections_text(), parse_mode="HTML", reply_markup=get_oh_projections_keyboard()
    )


@router.callback_query(F.data.startswith("oh:proj_group:"))
async def cb_oh_projection_group(callback: CallbackQuery):
    idx = int(callback.data.split(":")[2])
    groups = tb.OPERATIVE_SURGERY["projections"]
    if not (0 <= idx < len(groups)):
        await callback.answer("Группа не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_projection_group_text(idx), parse_mode="HTML",
        reply_markup=get_oh_projection_group_keyboard()
    )


@router.callback_query(F.data == "oh:stations")
async def cb_oh_stations(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_stations_text(), parse_mode="HTML", reply_markup=get_oh_stations_keyboard()
    )


@router.callback_query(F.data.startswith("oh:station_group:"))
async def cb_oh_station_group(callback: CallbackQuery):
    idx = int(callback.data.split(":")[2])
    groups = tb.OPERATIVE_SURGERY["practical_stations"]
    if not (0 <= idx < len(groups)):
        await callback.answer("Группа не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_oh_station_group_text(idx), parse_mode="HTML",
        reply_markup=get_oh_station_group_keyboard()
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
        "Отправь ключевое слово — поищу по темам, инструментам, проекциям и станциям.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
