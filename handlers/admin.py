# -*- coding: utf-8 -*-
"""Админ-панель — Router вместо прямой регистрации на глобальном dp (Phase 5 рефакторинга, см.
CLAUDE.md — та же схема, что уже применена к остальным разделам в handlers/*.py). Импортирует
telegram_bot как tb вместо `from telegram_bot import ...`, потому что сам telegram_bot.py
импортирует этот модуль — циклическая связь разрешается тем, что этот импорт стоит ближе к концу
telegram_bot.py, когда все нужные отсюда имена уже определены в его модульном пространстве имён.

Два состояния FSM (ADMIN_PENDING/handle_admin_pending_action и ASSISTANT_PENDING/
handle_assistant_pending_action) и связанные с ними служебные словари (ADMIN_CHANNEL_POST_PREVIEW,
ASSISTANT_DM_REQUESTS, ASSISTANT_PENDING) НАМЕРЕННО остаются в telegram_bot.py, а не переехали
сюда: оба dispatcher'а зарегистрированы через `@dp.message(F.text)` напрямую на dp (не через
Router), и aiogram 3.7 пробует ВСЕ хендлеры, зарегистрированные прямо на корневом Dispatcher, в
порядке регистрации, прежде чем передать событие в любой include_router'нутый саброутер —
независимо от того, где текстуально стоит dp.include_router(...). Если бы эти два dispatcher'а
переехали в Router, они начали бы получать сообщения ПОСЛЕ остальных `@dp.message(...)`
хендлеров, зарегистрированных прямо на dp (включая handle_keyword_search — тот же самый риск,
что и с handle_question_number/handle_keyword_search, см. handlers/biology.py). Поэтому здесь —
только клавиатуры/тексты/callback_query-хендлеры админ-панели и панели помощника; ссылки на
ADMIN_PENDING/ADMIN_CHANNEL_POST_PREVIEW/ASSISTANT_PENDING/ASSISTANT_DM_REQUESTS идут через tb.,
так как эти словари остаются определены в telegram_bot.py."""
import asyncio
import os
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

# ==================== АДМИН-ПАНЕЛЬ ====================

ADMIN_USERLIST_PAGE_SIZE = 25

def parse_channel_post_buttons(raw: str):
    """Разбирает построчный ввод "Текст | Ссылка" в список кнопок.
    Возвращает None, если формат хотя бы одной строки некорректен."""
    buttons = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            return None
        label, url = line.split("|", 1)
        label = label.strip()
        url = url.strip()
        if not label or not url.startswith(("http://", "https://", "tg://")):
            return None
        buttons.append((label, url))
    return buttons or None

def build_channel_post_builder(buttons: list) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for label, url in buttons:
        builder.row(InlineKeyboardButton(text=label, url=url))
    return builder

def build_channel_post_keyboard(buttons: list):
    return build_channel_post_builder(buttons).as_markup() if buttons else None

def get_admin_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📥 Экспорт stats.json", callback_data="admin_export_stats")
    builder.button(text="👥 Список пользователей", callback_data="admin_userlist:0")
    builder.button(text="🔓 Дать доступ по username/ID", callback_data="admin_grant_prompt")
    builder.button(text="🚫 Отозвать доступ по username/ID", callback_data="admin_revoke_prompt")
    builder.button(text="🦴 Дать демо-доступ к Анатомии", callback_data="admin_grant_anatomy_demo_prompt")
    builder.button(text="🦴🚫 Забрать демо-доступ к Анатомии", callback_data="admin_revoke_anatomy_demo_prompt")
    builder.button(text="🧑‍💼 Назначить помощника админа", callback_data="admin_grant_assistant_prompt")
    builder.button(text="🧑‍💼🚫 Снять помощника админа", callback_data="admin_revoke_assistant_prompt")
    builder.button(text="💳 Назначить админа платежей", callback_data="admin_grant_payment_admin_prompt")
    builder.button(text="💳🚫 Снять админа платежей", callback_data="admin_revoke_payment_admin_prompt")
    builder.button(text="✉️ Написать пользователю", callback_data="admin_dm_prompt")
    builder.button(text="⚔️ Битва рефералов", callback_data="admin_battle_menu")
    builder.button(text="💰 Записать донат рублями", callback_data="admin_donation_prompt")
    builder.button(text="💎 Выдать подписку по username/ID", callback_data="admin_subscription_prompt")
    builder.button(text="🎁 Восстановить доступ исчерпавшим (7 дней)", callback_data="admin_restore_access_confirm")
    builder.button(
        text=f"📣 Напомнить о реферале/подписке (<{tb.REFERRAL_FULL_ACCESS_THRESHOLD} реф.)",
        callback_data="admin_referral_reminder_confirm",
    )
    builder.button(
        text=f"🔥 Скидка 10% без рефералов (<{tb.REFERRAL_FULL_ACCESS_THRESHOLD} реф.)",
        callback_data="admin_discount_promo_confirm",
    )
    builder.button(text="📣 Анонсы", callback_data="admin_announcements_menu")
    builder.button(text="📤 Опубликовать пост в канал", callback_data="admin_channel_post_prompt")
    builder.button(text="🔬 Открыть Гистологию всем на 24ч", callback_data="admin_histology_promo_confirm")
    builder.button(text="🎉 Снять все ограничения всем на 24ч", callback_data="admin_global_promo_confirm")
    builder.button(text="🎉 Снять все ограничения всем на 12ч", callback_data="admin_global_promo_12h_confirm")
    builder.button(text="🔒 Вернуть ограничения", callback_data="admin_restore_restrictions_confirm")
    pending_ai_cache = tb.get_pending_ai_cache_count()
    builder.button(
        text=f"🤖 Модерация AI-кэша ({pending_ai_cache})" if pending_ai_cache else "🤖 Модерация AI-кэша",
        callback_data="admin_ai_cache_queue",
    )
    builder.adjust(1)
    return builder.as_markup()

def get_admin_battle_keyboard():
    builder = InlineKeyboardBuilder()
    if tb.is_battle_active():
        builder.button(text="🔄 Обновить", callback_data="admin_battle_menu")
        builder.button(text="📣 Разослать напоминание о битве", callback_data="admin_battle_remind_confirm")
        builder.button(text="🛑 Завершить досрочно", callback_data="admin_battle_end_confirm")
    else:
        builder.button(text="🚀 Начать битву рефералов (неделя)", callback_data="admin_battle_start_confirm")
    battle = tb.stats.get("referral_battle")
    if battle and battle.get("results") is not None:
        builder.button(text="🏁 Итоги последней битвы (для публикации)", callback_data="admin_battle_last_results")
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_battle_text() -> str:
    if tb.is_battle_active():
        battle = tb.stats["referral_battle"]
        remaining = tb.format_time_left(battle["end_ts"] - time.time())
        leaderboard = tb.get_battle_leaderboard()
        lines = [
            f"⚔️ <b>Битва рефералов — идёт!</b>\n{tb.DIVIDER}\n",
            tb.BATTLE_CHANNEL_POSTING_NOTICE,
            "",
            f"⏳ Осталось: <b>{remaining}</b>\n",
        ]
        if leaderboard:
            for i, (uid, diff) in enumerate(leaderboard):
                name = tb.stats["user_names"].get(uid, f"Пользователь {uid}")
                lines.append(f"{tb.battle_place_icon(i)} {name} — <b>{diff}</b>")
        else:
            lines.append("Пока никто не пригласил друзей в рамках битвы.")
        return "\n".join(lines)
    return (
        f"⚔️ <b>Битва рефералов</b>\n{tb.DIVIDER}\n\n"
        "Сейчас битва не идёт.\n\n"
        f"Запусти битву на {tb.format_battle_duration()} — топ-5 пользователей по числу приглашённых друзей за это время "
        f"получат призы:\n\n{tb.format_battle_prizes_block()}\n\n"
        "Всем пользователям бота придёт рассылка с объявлением о старте и правилах."
    )

def get_admin_announcements_keyboard(back_callback: str = "admin_panel"):
    """Подраздел «Анонсы» — все admin_announce_* рассылки собраны сюда с главного экрана
    админ-панели одной кнопкой, чтобы не захламлять его; каждая кнопка ведёт напрямую в свой
    already-existing _confirm-хендлер (см. cb_admin_announce_*_confirm ниже и в telegram_bot.py
    для переклички), сама рассылочная логика не меняется. Доступен и полным админам, и отдельной
    роли «админ платежей» (is_payment_admin) — back_callback параметризован именно поэтому:
    полный админ возвращается в admin_panel, а админ платежей — в свою отдельную panel, см.
    cb_admin_announcements_menu, который выбирает нужное значение."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Оповещение о подписке", callback_data="admin_announce_subscription_confirm")
    builder.button(text="📣 Анонс раздела поддержки", callback_data="admin_announce_support_confirm")
    builder.button(text="📣 Анонс раздела Анатомия", callback_data="admin_announce_anatomy_confirm")
    builder.button(text="📣 Анонс Экзамена (ТЕСТ/теория/практика)", callback_data="admin_announce_anatomy_exam_confirm")
    builder.button(text="📣 Анонс теста по латыни", callback_data="admin_announce_anatomy_latin_confirm")
    builder.button(text="📣 Анонс VMedA AI", callback_data="admin_announce_ai_confirm")
    builder.button(text="📋 Анонс переклички групп", callback_data="admin_announce_rollcall_confirm")
    builder.button(text="🔙 Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()

def get_admin_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel"))
    return builder.as_markup()

def get_admin_stats_keyboard(breaker_tripped: bool):
    """Как get_admin_back_keyboard(), плюс кнопка сброса AI-автовыключателя, когда он сработал —
    единственный способ снова включить AI после срабатывания (см. tb.reset_ai_circuit_breaker)."""
    builder = InlineKeyboardBuilder()
    if breaker_tripped:
        builder.row(InlineKeyboardButton(text="🔓 Сбросить AI-автовыключатель", callback_data="admin_ai_breaker_reset"))
    builder.row(InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel"))
    return builder.as_markup()

def resolve_user_by_username(raw: str):
    """Резолвит введённый админом идентификатор — username (с @ или без) или
    числовой Telegram ID — в (username_или_None, target_id_или_None). ID должен
    принадлежать пользователю, который уже писал боту. username может быть None,
    если пользователь найден по ID, но своего username у него нет."""
    identifier = raw.strip().lstrip("@")
    if identifier.isdigit():
        user_id = int(identifier)
        if user_id in tb.stats["total_users"]:
            return tb.stats["user_username"].get(str(user_id)), user_id
        return None, None
    username = identifier.lower()
    return username, tb.stats["usernames"].get(username)

def format_admin_target_label(username, target_id: int) -> str:
    return f"@{username} (ID {target_id})" if username else f"ID {target_id}"

def format_user_line(user_id: int) -> str:
    uid_str = str(user_id)
    username = tb.stats["user_username"].get(uid_str)
    handle = f"@{username}" if username else "(без username)"
    name = tb.stats["user_names"].get(uid_str, "—")
    refs = len(tb.stats["referrals"].get(uid_str, []))
    granted = " 🔓" if user_id in tb.stats["manual_access_granted"] else ""
    anatomy_demo = " 🦴" if user_id in tb.stats["manual_anatomy_demo_granted"] else ""
    assistant = " 🧑‍💼" if user_id in tb.stats["assistant_admins"] else ""
    payment_admin = " 💳" if user_id in tb.stats["payment_admins"] else ""
    return f"<code>{user_id}</code> — {handle} — {name} — реф: {refs}{granted}{anatomy_demo}{assistant}{payment_admin}"

def get_admin_userlist_page(page: int):
    all_ids = sorted(tb.stats["total_users"])
    total = len(all_ids)
    start = page * ADMIN_USERLIST_PAGE_SIZE
    end = start + ADMIN_USERLIST_PAGE_SIZE
    chunk = all_ids[start:end]
    lines = [f"👥 <b>Пользователи</b> ({total} всего)\n{tb.DIVIDER}"]
    lines.extend(format_user_line(uid) for uid in chunk)
    text = "\n".join(lines)
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_userlist:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_userlist:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel"))
    return text, builder.as_markup()

@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING.pop(callback.from_user.id, None)
    await tb.safe_edit_text(
        callback.message,
        f"🛠 <b>Админ-панель</b>\n{tb.DIVIDER}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=get_admin_menu()
    )

@router.callback_query(F.data == "admin_battle_menu")
async def cb_admin_battle_menu(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_admin_battle_text(),
        parse_mode="HTML",
        reply_markup=get_admin_battle_keyboard()
    )

@router.callback_query(F.data == "admin_announcements_menu")
async def cb_admin_announcements_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not (tb.is_admin(user_id) or tb.is_payment_admin(user_id)):
        await callback.answer()
        return
    await callback.answer()
    back_callback = "admin_panel" if tb.is_admin(user_id) else "payment_admin_panel"
    await tb.safe_edit_text(
        callback.message,
        f"📣 <b>Анонсы</b>\n{tb.DIVIDER}\n\nВыбери, что разослать:",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(back_callback)
    )

@router.callback_query(F.data == "admin_battle_last_results")
async def cb_admin_battle_last_results(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    battle = tb.stats.get("referral_battle")
    results = battle.get("results") if battle else None
    if results is None:
        await callback.answer("Нет сохранённых итогов ни одной завершённой битвы", show_alert=True)
        return
    await callback.answer()
    text = tb.get_battle_results_announcement_text(results)
    await tb.safe_edit_text(
        callback.message,
        f"{text}\n\n{tb.DIVIDER}\n"
        "👆 Текст выше — в том же виде, что уходит пользователям рассылкой. "
        "Скопируй его, чтобы опубликовать отдельно.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_battle_start_confirm")
async def cb_admin_battle_start_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, начать битву на неделю", callback_data="admin_battle_start_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        "⚔️ <b>Подтверди запуск битвы рефералов</b>\n\n"
        f"Битва продлится {tb.format_battle_duration()}, топ-5 по числу новых приглашённых получат призы:\n\n"
        f"{tb.format_battle_prizes_block()}\n\nВсем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "admin_battle_start_go")
async def cb_admin_battle_start_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    if tb.is_battle_active():
        await callback.answer("Битва уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Битва запущена!", show_alert=True)
    tb.start_referral_battle()
    asyncio.create_task(tb._battle_timer(tb.stats["referral_battle"]["end_ts"]))
    asyncio.create_task(tb.announce_battle_start())
    await tb.safe_edit_text(
        callback.message,
        get_admin_battle_text(),
        parse_mode="HTML",
        reply_markup=get_admin_battle_keyboard()
    )

@router.callback_query(F.data == "admin_histology_promo_confirm")
async def cb_admin_histology_promo_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, открыть на 24ч", callback_data="admin_histology_promo_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        "🔬 <b>Подтверди промо-доступ к Гистологии</b>\n\n"
        "Раздел станет бесплатным для всех на 24 часа. После этого доступ вернётся к обычному "
        f"правилу: {tb.REFERRAL_FULL_ACCESS_THRESHOLD} реферала или подписка (как остальные предметы).\n\n"
        "Всем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "admin_histology_promo_go")
async def cb_admin_histology_promo_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    if tb.is_section_promo_active("histology"):
        await callback.answer("Промо уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Гистология открыта для всех на 24 часа!", show_alert=True)
    tb.start_section_promo("histology", tb.HISTOLOGY_PROMO_SECONDS)
    asyncio.create_task(tb.announce_histology_promo_start())
    await tb.safe_edit_text(
        callback.message,
        "✅ Гистология открыта для всех на 24 часа.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_global_promo_confirm")
async def cb_admin_global_promo_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, открыть всё на 24ч", callback_data="admin_global_promo_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        "🎉 <b>Подтверди снятие всех ограничений</b>\n\n"
        "Биология, Физика, Химия и Гистология станут бесплатными для всех пользователей на 24 часа — "
        "без рефералов и подписки. Анатомия (ещё в разработке) и скачивание билетов по биологии "
        "(всегда только по подписке) промо не затрагивает. После 24 часов доступ вернётся к обычным "
        "правилам каждого раздела.\n\n"
        "Всем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "admin_global_promo_go")
async def cb_admin_global_promo_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    if tb.is_section_promo_active("global"):
        await callback.answer("Промо уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Все ограничения сняты на 24 часа!", show_alert=True)
    tb.start_section_promo("global", tb.GLOBAL_PROMO_SECONDS)
    asyncio.create_task(tb.announce_global_promo_start())
    await tb.safe_edit_text(
        callback.message,
        "✅ Все ограничения сняты для всех на 24 часа.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_global_promo_12h_confirm")
async def cb_admin_global_promo_12h_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, открыть всё на 12ч", callback_data="admin_global_promo_12h_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        "🎉 <b>Подтверди снятие всех ограничений на 12ч</b>\n\n"
        "Биология, Физика, Химия и Гистология станут бесплатными для всех пользователей на 12 часов — "
        "без рефералов и подписки. Анатомия (ещё в разработке) и скачивание билетов по биологии "
        "(всегда только по подписке) промо не затрагивает. После 12 часов доступ вернётся к обычным "
        "правилам каждого раздела.\n\n"
        "Всем пользователям придёт рассылка с объявлением.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "admin_global_promo_12h_go")
async def cb_admin_global_promo_12h_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    if tb.is_section_promo_active("global"):
        await callback.answer("Промо уже идёт", show_alert=True)
        return
    await callback.answer("🚀 Все ограничения сняты на 12 часов!", show_alert=True)
    tb.start_section_promo("global", tb.GLOBAL_PROMO_12H_SECONDS)
    asyncio.create_task(tb.announce_global_promo_12h_start())
    await tb.safe_edit_text(
        callback.message,
        "✅ Все ограничения сняты для всех на 12 часов.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_restore_restrictions_confirm")
async def cb_admin_restore_restrictions_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    active = [section for section, until in tb.stats.get("section_promos", {}).items() if time.time() < until]
    if not active:
        await tb.safe_edit_text(
            callback.message,
            "🔒 Сейчас нет активных промо-доступов — возвращать нечего.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard()
        )
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, вернуть ограничения", callback_data="admin_restore_restrictions_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        "🔒 <b>Подтверди возврат ограничений</b>\n\n"
        f"Сейчас активны промо-доступы: {', '.join(active)}. Все они будут закрыты немедленно, доступ "
        "вернётся к обычным правилам каждого раздела.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "admin_restore_restrictions_go")
async def cb_admin_restore_restrictions_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    tb.stats["section_promos"] = {}
    tb.save_stats()
    await callback.answer("🔒 Ограничения возвращены для всех.", show_alert=True)
    await tb.safe_edit_text(
        callback.message,
        "✅ Все активные промо-доступы закрыты, ограничения возвращены.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_battle_end_confirm")
async def cb_admin_battle_end_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, завершить битву", callback_data="admin_battle_end_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        "🛑 <b>Завершить битву досрочно?</b>\n\nПобедители будут определены по текущему рейтингу, "
        "всем пользователям придёт рассылка с итогами.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "admin_battle_end_go")
async def cb_admin_battle_end_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("Битва завершена")
    await tb.resolve_referral_battle()
    await tb.safe_edit_text(
        callback.message,
        get_admin_battle_text(),
        parse_mode="HTML",
        reply_markup=get_admin_battle_keyboard()
    )

@router.callback_query(F.data == "admin_battle_remind_confirm")
async def cb_admin_battle_remind_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    if not tb.is_battle_active():
        await callback.answer("Битва сейчас не идёт", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_battle_remind_go")
    builder.button(text="❌ Отмена", callback_data="admin_battle_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр напоминания</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_battle_remind_broadcast_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_battle_remind_go")
async def cb_admin_battle_remind_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    if not tb.is_battle_active():
        await callback.answer("Битва сейчас не идёт", show_alert=True)
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Битва рефералов", callback_data="referral_battle")
    await tb._broadcast(tb.get_battle_remind_broadcast_text(), builder.as_markup())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Напоминание о битве рефералов отправлено (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_restore_access_confirm")
async def cb_admin_restore_access_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = tb.get_exhausted_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей с исчерпанным доступом", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Восстановить и отправить", callback_data="admin_restore_access_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_access_restored_broadcast_text()}\n\n{tb.DIVIDER}\n"
        f"Доступ будет восстановлен на 7 дней и рассылка отправлена {len(cohort)} пользователям, "
        "у которых закончились бесплатные заходы без рефералов.\n"
        "Правило с рефералами для остальных пользователей не изменится."
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_restore_access_go")
async def cb_admin_restore_access_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = tb.get_exhausted_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей с исчерпанным доступом", show_alert=True)
        return
    await callback.answer("🎁 Восстанавливаю доступ и отправляю рассылку!", show_alert=True)
    expiry = time.time() + tb.TEMP_ACCESS_GRANT_SECONDS
    for uid in cohort:
        tb.stats["temporary_access"][str(uid)] = expiry
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast_to(cohort, tb.get_access_restored_broadcast_text())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Доступ восстановлен на 7 дней, рассылка отправлена (попытка охватить {len(cohort)} пользователей).\n\n"
        "Правило с рефералами (2 друга для доступа навсегда) для остальных не изменилось.",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_referral_reminder_confirm")
async def cb_admin_referral_reminder_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = tb.get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить напоминание", callback_data="admin_referral_reminder_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_referral_reminder_broadcast_text()}\n\n{tb.DIVIDER}\n"
        f"Рассылка уйдёт {len(cohort)} пользователям, у которых меньше "
        f"{tb.REFERRAL_FULL_ACCESS_THRESHOLD} рефералов и нет подписки/ручного/временного доступа. "
        "Никакой доступ не выдаётся — только напоминание пригласить друзей или оформить подписку."
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_referral_reminder_go")
async def cb_admin_referral_reminder_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = tb.get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast_to(cohort, tb.get_referral_reminder_broadcast_text(), tb.get_referral_reminder_broadcast_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Напоминание отправлено (попытка охватить {len(cohort)} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_discount_promo_confirm")
async def cb_admin_discount_promo_confirm(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = tb.get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить рассылку", callback_data="admin_discount_promo_go")
    builder.button(text="❌ Отмена", callback_data="admin_panel")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр рассылки</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_discount_promo_broadcast_text()}\n\n{tb.DIVIDER}\n"
        f"Рассылка уйдёт {len(cohort)} пользователям, у которых меньше "
        f"{tb.REFERRAL_FULL_ACCESS_THRESHOLD} рефералов и нет подписки/ручного/временного доступа. "
        "Кнопки в рассылке ведут прямо на оформление подписки со скидкой."
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_discount_promo_go")
async def cb_admin_discount_promo_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    cohort = tb.get_below_threshold_users()
    if not cohort:
        await callback.answer("Сейчас нет пользователей без бесплатного доступа", show_alert=True)
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast_to(cohort, tb.get_discount_promo_broadcast_text(), tb.get_discount_promo_broadcast_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Рассылка со скидкой отправлена (попытка охватить {len(cohort)} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    total_referrals = sum(len(v) for v in tb.stats["referrals"].values())
    exhausted_free_uses = len(tb.get_exhausted_users())
    below_threshold_count = sum(
        1 for uid in tb.stats["total_users"] if tb.get_referral_count(uid) < tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )

    subs = tb.stats["subscriptions"]
    active_by_tier = {tier_id: 0 for tier_id in tb.SUBSCRIPTION_TIERS}
    active_total = 0
    sub_revenue_stars = 0
    sub_revenue_rubles = 0
    for uid_str, sub in subs.items():
        method = sub.get("method")
        price = sub.get("price", 0)
        if method == "stars":
            sub_revenue_stars += price
        elif method == "rubles":
            sub_revenue_rubles += price
        if tb.has_active_subscription(int(uid_str)):
            active_total += 1
            tier = sub.get("tier")
            if tier in active_by_tier:
                active_by_tier[tier] += 1
    subscription_lines = "\n".join(
        f"  {cfg['emoji']} {cfg['short']}: <b>{active_by_tier[tier_id]}</b>"
        for tier_id, cfg in tb.SUBSCRIPTION_TIERS.items()
    )

    donation_stars_total = tb.stats.get("donations_stars_total", 0)
    donation_stars_count = tb.stats.get("donations_stars_count", 0)
    donation_rubles_total = sum(tb.stats.get("donor_rubles", {}).values())
    donation_rubles_count = len(tb.stats.get("donor_rubles", {}))

    text = (
        f"📊 <b>Статистика бота</b>\n{tb.DIVIDER}\n\n"
        f"👥 Уникальных пользователей: <b>{len(tb.stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{tb.stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(tb.stats['question_opened'].values())}</b>\n"
        f"🎲 Случайных билетов открыто: <b>{tb.stats['random_ticket_used']}</b>\n"
        f"🎲 Случайных вопросов открыто: <b>{tb.stats['random_question_used']}</b>\n"
        f"📢 Рассылок отправлено: <b>{tb.stats.get('broadcast_count', 0)}</b>\n"
        f"🔗 Всего рефералов: <b>{total_referrals}</b>\n"
        f"📉 Меньше {tb.REFERRAL_FULL_ACCESS_THRESHOLD} рефералов: <b>{below_threshold_count}</b>\n"
        f"🔓 Ручных доступов выдано: <b>{len(tb.stats['manual_access_granted'])}</b>\n"
        f"🦴 Демо-доступов к Анатомии выдано: <b>{len(tb.stats['manual_anatomy_demo_granted'])}</b>\n"
        f"🚫 Исчерпали бесплатные заходы без рефералов: <b>{exhausted_free_uses}</b>\n"
        f"🪪 Известно username: <b>{len(tb.stats['usernames'])}</b>\n"
        f"\n💎 <b>Подписки</b>\n"
        f"Всего куплено: <b>{len(subs)}</b>, активных сейчас: <b>{active_total}</b>\n"
        f"{subscription_lines}\n"
        f"\n💰 <b>Платежи</b>\n"
        f"⭐ Донаты звёздами: <b>{donation_stars_total}</b> ({donation_stars_count} платежей)\n"
        f"💵 Донаты рублями: <b>{donation_rubles_total}</b>₽ ({donation_rubles_count} чел.)\n"
        f"⭐ Подписки звёздами: <b>{sub_revenue_stars}</b>\n"
        f"💵 Подписки рублями: <b>{sub_revenue_rubles}</b>₽\n"
        f"{tb.get_ai_cost_stats_block()}\n"
        f"🗄 AI-кэш: <b>{len(tb.stats['ai_answer_cache'])}</b> записей, "
        f"на модерации: <b>{tb.get_pending_ai_cache_count()}</b>"
    )
    breaker_tripped = tb.ai_circuit_breaker_tripped()
    if breaker_tripped:
        windows = tb.stats["ai_cost_windows"]
        text += (
            f"\n\n🚨 <b>AI-автовыключатель сработал</b> — AI отключён для всех пользователей.\n"
            f"За час: ${windows['hour_cost_usd']:.2f} (лимит ${tb.AI_COST_HOUR_LIMIT_USD:.2f}), "
            f"за сутки: ${windows['day_cost_usd']:.2f} (лимит ${tb.AI_COST_DAY_LIMIT_USD:.2f})"
        )
    await tb.safe_edit_text(
        callback.message, text, parse_mode="HTML",
        reply_markup=get_admin_stats_keyboard(breaker_tripped),
    )

@router.callback_query(F.data == "admin_ai_breaker_reset")
async def cb_admin_ai_breaker_reset(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    tb.reset_ai_circuit_breaker()
    await callback.answer("AI-автовыключатель сброшен, AI снова доступен всем.", show_alert=True)
    await cb_admin_stats(callback)

_AI_CACHE_CONFIDENCE_LABEL = {"escalate": "🔴 высокий риск ошибки", "verify": "🟡 стоит проверить внимательнее", "serve": "🟢 без замечаний"}

def get_ai_cache_queue_text(fingerprint: str, entry: dict) -> str:
    subject = entry.get("subject") or "не определён"
    confidence_action = entry.get("confidence_action", "serve")
    confidence_line = _AI_CACHE_CONFIDENCE_LABEL.get(confidence_action, confidence_action)
    reasons = entry.get("confidence_reasons") or []
    reasons_block = ("\n" + "\n".join(f"  • {r}" for r in reasons)) if reasons else ""
    return (
        f"🤖 <b>Модерация AI-кэша</b>\n{tb.DIVIDER}\n\n"
        f"На очереди: <b>{tb.get_pending_ai_cache_count()}</b>\n"
        f"Предмет: <b>{subject}</b>\n"
        f"Автопроверка: {confidence_line}{reasons_block}\n\n"
        f"❓ <b>Вопрос:</b>\n{entry['question_preview']}\n\n"
        f"💬 <b>Сгенерированный ответ:</b>\n{entry['answer']}\n\n"
        "Одобрить — этот ответ будет бесплатно и мгновенно отдаваться любому пользователю, "
        "задавшему точно такой же вопрос (без обращения к модели). Отклонить — ответ не "
        "сохранится в кэше, но при следующем таком же вопросе будет сгенерирован заново и "
        "снова предложен на модерацию."
    )

def get_ai_cache_queue_keyboard(fingerprint: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Одобрить", callback_data=f"admin_ai_cache_approve:{fingerprint}")
    builder.button(text="❌ Отклонить", callback_data=f"admin_ai_cache_reject:{fingerprint}")
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data == "admin_ai_cache_queue")
async def cb_admin_ai_cache_queue(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    fingerprint, entry = tb.get_next_pending_ai_cache_entry()
    if fingerprint is None:
        await tb.safe_edit_text(
            callback.message,
            f"🤖 <b>Модерация AI-кэша</b>\n{tb.DIVIDER}\n\nОчередь пуста — все сгенерированные "
            "ответы уже промодерированы.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard(),
        )
        return
    await tb.safe_edit_text(
        callback.message,
        get_ai_cache_queue_text(fingerprint, entry),
        parse_mode="HTML",
        reply_markup=get_ai_cache_queue_keyboard(fingerprint),
    )

@router.callback_query(F.data.startswith("admin_ai_cache_approve:"))
async def cb_admin_ai_cache_approve(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    fingerprint = callback.data.split(":", 1)[1]
    tb.moderate_ai_cache_entry(fingerprint, approve=True)
    await callback.answer("Одобрено — теперь отдаётся из кэша")
    await cb_admin_ai_cache_queue(callback)

@router.callback_query(F.data.startswith("admin_ai_cache_reject:"))
async def cb_admin_ai_cache_reject(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    fingerprint = callback.data.split(":", 1)[1]
    tb.moderate_ai_cache_entry(fingerprint, approve=False)
    await callback.answer("Отклонено")
    await cb_admin_ai_cache_queue(callback)

@router.callback_query(F.data == "admin_export_stats")
async def cb_admin_export_stats(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    if not os.path.exists(tb.STATS_FILE):
        await callback.message.answer("Файл stats.json ещё не создан.")
        return
    await callback.message.answer_document(
        FSInputFile(tb.STATS_FILE),
        caption=f"📥 Текущий stats.json (снимок на момент запроса, только чтение — сама выгрузка ничего не меняет).\n\n@{tb.BOT_USERNAME}"
    )

@router.callback_query(F.data.startswith("admin_userlist:"))
async def cb_admin_userlist(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    page = int(callback.data.split(":")[1])
    text, kb = get_admin_userlist_page(page)
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data == "admin_grant_prompt")
async def cb_admin_grant_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "grant"}
    await tb.safe_edit_text(
        callback.message,
        "🔓 <b>Выдать доступ</b>\n\nОтправь username пользователя (с @ или без, например <code>@ivanov</code>) "
        "или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_revoke_prompt")
async def cb_admin_revoke_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "revoke"}
    await tb.safe_edit_text(
        callback.message,
        "🚫 <b>Отозвать ручной доступ</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_grant_anatomy_demo_prompt")
async def cb_admin_grant_anatomy_demo_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "grant_anatomy_demo"}
    await tb.safe_edit_text(
        callback.message,
        "🦴 <b>Дать демо-доступ к Анатомии</b>\n\nОтправь username пользователя (с @ или без, например <code>@ivanov</code>) "
        "или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_revoke_anatomy_demo_prompt")
async def cb_admin_revoke_anatomy_demo_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "revoke_anatomy_demo"}
    await tb.safe_edit_text(
        callback.message,
        "🦴🚫 <b>Забрать демо-доступ к Анатомии</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_grant_assistant_prompt")
async def cb_admin_grant_assistant_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "grant_assistant_admin"}
    await tb.safe_edit_text(
        callback.message,
        "🧑‍💼 <b>Назначить помощника админа</b>\n\n"
        "Помощник получит доступ ко всем разделам бота, ограниченную статистику и сможет "
        "писать пользователям — но только с твоего подтверждения на каждое сообщение. "
        "Полных прав админ-панели (выдача доступа, рассылки, подписки) у него не будет.\n\n"
        "Отправь username пользователя (с @ или без, например <code>@ivanov</code>) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_revoke_assistant_prompt")
async def cb_admin_revoke_assistant_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "revoke_assistant_admin"}
    await tb.safe_edit_text(
        callback.message,
        "🧑‍💼🚫 <b>Снять помощника админа</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_grant_payment_admin_prompt")
async def cb_admin_grant_payment_admin_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "grant_payment_admin"}
    await tb.safe_edit_text(
        callback.message,
        "💳 <b>Назначить админа платежей</b>\n\n"
        "Админ платежей сможет подтверждать рублёвые заявки на оплату (те же one-tap кнопки, что "
        "приходят тебе) и рассылать анонсы из подраздела «Анонсы». Остальных прав полной "
        "админ-панели (выдача/отзыв доступа, выдача подписок, статистика) у него не будет — это "
        "отдельная от «помощника» роль.\n\n"
        "Отправь username пользователя (с @ или без, например <code>@ivanov</code>) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_revoke_payment_admin_prompt")
async def cb_admin_revoke_payment_admin_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "revoke_payment_admin"}
    await tb.safe_edit_text(
        callback.message,
        "💳🚫 <b>Снять админа платежей</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_dm_prompt")
async def cb_admin_dm_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "dm_username"}
    await tb.safe_edit_text(
        callback.message,
        "✉️ <b>Личное сообщение</b>\n\nОтправь username пользователя (с @ или без) или его числовой ID "
        "— например, из «👥 Список пользователей»",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_donation_prompt")
async def cb_admin_donation_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "record_donation_username"}
    await tb.safe_edit_text(
        callback.message,
        "💰 <b>Записать пожертвование рублями</b>\n\n"
        "Переводы в рублях идут напрямую в чат с @vmeda_helper, бот их не видит — "
        "запиши сюда вручную, чтобы человек попал в рейтинг донатеров.\n\n"
        "Отправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_subscription_prompt")
async def cb_admin_subscription_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "record_subscription_username"}
    await tb.safe_edit_text(
        callback.message,
        "💎 <b>Выдать подписку</b>\n\n"
        "Для оплат рублями (перевод в чате с @vmeda_helper) подписку нужно включить вручную "
        "после подтверждения оплаты.\n\n"
        "Отправь username пользователя (с @ или без) или его числовой ID",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_announce_support_confirm")
async def cb_admin_announce_support_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_support_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_support_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_announce_support_go")
async def cb_admin_announce_support_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast(tb.get_support_announcement_text(), tb.get_support_announcement_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Анонс раздела поддержки отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(
            "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
        )
    )

@router.callback_query(F.data == "admin_announce_subscription_confirm")
async def cb_admin_announce_subscription_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_subscription_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_subscription_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_announce_subscription_go")
async def cb_admin_announce_subscription_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast(tb.get_subscription_announcement_text(), tb.get_subscription_announcement_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Оповещение о подписке отправлено (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(
            "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
        )
    )

@router.callback_query(F.data == "admin_announce_anatomy_confirm")
async def cb_admin_announce_anatomy_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_anatomy_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_anatomy_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_announce_anatomy_go")
async def cb_admin_announce_anatomy_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast(tb.get_anatomy_announcement_text(), tb.get_anatomy_announcement_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Анонс раздела Анатомия отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(
            "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
        )
    )

@router.callback_query(F.data == "admin_announce_ai_confirm")
async def cb_admin_announce_ai_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    if not tb.ai_provider_available():
        await callback.answer("AI сейчас не настроен (нет ни одного провайдера) — рассылать нечего.", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_ai_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_ai_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_announce_ai_go")
async def cb_admin_announce_ai_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast(tb.get_ai_announcement_text(), tb.get_ai_announcement_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Анонс VMedA AI отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(
            "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
        )
    )

@router.callback_query(F.data == "admin_announce_anatomy_exam_confirm")
async def cb_admin_announce_anatomy_exam_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_anatomy_exam_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_anatomy_exam_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_announce_anatomy_exam_go")
async def cb_admin_announce_anatomy_exam_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast(tb.get_anatomy_exam_announcement_text(), tb.get_anatomy_exam_announcement_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Анонс раздела Экзамен отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(
            "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
        )
    )

@router.callback_query(F.data == "admin_announce_anatomy_latin_confirm")
async def cb_admin_announce_anatomy_latin_confirm(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="admin_announce_anatomy_latin_go")
    builder.button(text="❌ Отмена", callback_data="admin_announcements_menu")
    builder.adjust(1)
    preview = (
        f"👀 <b>Предпросмотр анонса</b>\n{tb.DIVIDER}\n\n"
        f"{tb.get_anatomy_latin_announcement_text()}\n\n{tb.DIVIDER}\n"
        f"Отправить это всем {len(tb.stats['total_users'])} пользователям?"
    )
    await tb.safe_edit_text(callback.message, preview, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_announce_anatomy_latin_go")
async def cb_admin_announce_anatomy_latin_go(callback: CallbackQuery):
    if not (tb.is_admin(callback.from_user.id) or tb.is_payment_admin(callback.from_user.id)):
        await callback.answer()
        return
    await callback.answer("📣 Рассылка запущена!", show_alert=True)
    recipients = len(tb.stats["total_users"])
    tb.stats["broadcast_count"] = tb.stats.get("broadcast_count", 0) + 1
    tb.save_stats()
    await tb._broadcast(tb.get_anatomy_latin_announcement_text(), tb.get_anatomy_latin_announcement_keyboard())
    await tb.safe_edit_text(
        callback.message,
        f"✅ Анонс теста по латыни отправлен (попытка охватить {recipients} пользователей).",
        parse_mode="HTML",
        reply_markup=get_admin_announcements_keyboard(
            "admin_panel" if tb.is_admin(callback.from_user.id) else "payment_admin_panel"
        )
    )

@router.callback_query(F.data == "admin_channel_post_prompt")
async def cb_admin_channel_post_prompt(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ADMIN_PENDING[callback.from_user.id] = {"action": "channel_post_text"}
    await tb.safe_edit_text(
        callback.message,
        f"📤 <b>Пост в канал {tb.CHANNEL_ID}</b>\n{tb.DIVIDER}\n\n"
        "Пришли текст поста (можно с форматированием Telegram — жирный, курсив, ссылки и т.д. "
        "— просто выдели текст и примени стиль перед отправкой).",
        parse_mode="HTML",
        reply_markup=get_admin_back_keyboard()
    )

@router.callback_query(F.data == "admin_channel_post_go")
async def cb_admin_channel_post_go(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    pending = tb.ADMIN_CHANNEL_POST_PREVIEW.pop(callback.from_user.id, None)
    if not pending:
        await callback.answer("Черновик не найден, начни заново.", show_alert=True)
        return
    try:
        await tb.bot.send_message(
            tb.CHANNEL_ID,
            pending["text"],
            parse_mode="HTML",
            reply_markup=build_channel_post_keyboard(pending["buttons"]),
        )
        await callback.answer("✅ Опубликовано!", show_alert=True)
        await tb.safe_edit_text(
            callback.message,
            f"✅ Пост опубликован в {tb.CHANNEL_ID}.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard()
        )
    except Exception:
        tb.logger.exception("Не удалось опубликовать пост в канал %s", tb.CHANNEL_ID)
        await callback.answer()
        await tb.safe_edit_text(
            callback.message,
            "⚠️ <b>Не удалось опубликовать пост.</b>\n\n"
            f"Скорее всего, бот не администратор канала {tb.CHANNEL_ID} или у него нет права "
            "«Публиковать сообщения». Добавь бота в администраторы канала с этим правом и попробуй снова.",
            parse_mode="HTML",
            reply_markup=get_admin_back_keyboard()
        )

@router.callback_query(F.data == "admin_channel_post_cancel")
async def cb_admin_channel_post_cancel(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    tb.ADMIN_CHANNEL_POST_PREVIEW.pop(callback.from_user.id, None)
    await callback.answer("Отменено")
    await tb.safe_edit_text(callback.message, "❌ Публикация отменена.", parse_mode="HTML", reply_markup=get_admin_back_keyboard())


# ==================== ПОМОЩНИК АДМИНИСТРАТОРА ====================

def get_assistant_admin_menu_text() -> str:
    return (
        f"🧑‍💼 <b>Панель помощника</b>\n{tb.DIVIDER}\n\n"
        "Тебе доступна статистика бота и возможность написать пользователю — сообщение "
        "уйдёт только после подтверждения главным админом.\n\nВыбери действие:"
    )

def get_assistant_admin_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="assistant_stats")
    builder.button(text="✉️ Написать пользователю", callback_data="assistant_dm_prompt")
    builder.adjust(1)
    return builder.as_markup()

def get_assistant_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="assistant_panel"))
    return builder.as_markup()

def get_assistant_stats_text() -> str:
    """Та же арифметика, что и в cb_admin_stats, но выводится ровно урезанное подмножество
    строк — без разделов «Подписки»/«Платежи» и без остальной админ-панели."""
    total_referrals = sum(len(v) for v in tb.stats["referrals"].values())
    exhausted_free_uses = len(tb.get_exhausted_users())
    below_threshold_count = sum(
        1 for uid in tb.stats["total_users"] if tb.get_referral_count(uid) < tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )
    return (
        f"📊 <b>Статистика бота</b>\n{tb.DIVIDER}\n\n"
        f"👥 Уникальных пользователей: <b>{len(tb.stats['total_users'])}</b>\n"
        f"▶️ Запусков бота: <b>{tb.stats['start_count']}</b>\n"
        f"❓ Вопросов просмотрено: <b>{sum(tb.stats['question_opened'].values())}</b>\n"
        f"🎲 Случайных билетов открыто: <b>{tb.stats['random_ticket_used']}</b>\n"
        f"🎲 Случайных вопросов открыто: <b>{tb.stats['random_question_used']}</b>\n"
        f"📢 Рассылок отправлено: <b>{tb.stats.get('broadcast_count', 0)}</b>\n"
        f"🔗 Всего рефералов: <b>{total_referrals}</b>\n"
        f"📉 Меньше {tb.REFERRAL_FULL_ACCESS_THRESHOLD} рефералов: <b>{below_threshold_count}</b>\n"
        f"🔓 Ручных доступов выдано: <b>{len(tb.stats['manual_access_granted'])}</b>\n"
        f"🦴 Демо-доступов к Анатомии выдано: <b>{len(tb.stats['manual_anatomy_demo_granted'])}</b>\n"
        f"🚫 Исчерпали бесплатные заходы без рефералов: <b>{exhausted_free_uses}</b>\n"
        f"🪪 Известно username: <b>{len(tb.stats['usernames'])}</b>"
    )

@router.callback_query(F.data == "assistant_panel")
async def cb_assistant_panel(callback: CallbackQuery):
    if not tb.is_assistant_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ASSISTANT_PENDING.pop(callback.from_user.id, None)
    await tb.safe_edit_text(
        callback.message,
        get_assistant_admin_menu_text(),
        parse_mode="HTML",
        reply_markup=get_assistant_admin_menu_keyboard()
    )

@router.callback_query(F.data == "assistant_stats")
async def cb_assistant_stats(callback: CallbackQuery):
    if not tb.is_assistant_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_assistant_stats_text(),
        parse_mode="HTML",
        reply_markup=get_assistant_back_keyboard()
    )

@router.callback_query(F.data == "assistant_dm_prompt")
async def cb_assistant_dm_prompt(callback: CallbackQuery):
    if not tb.is_assistant_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    tb.ASSISTANT_PENDING[callback.from_user.id] = {"action": "dm_username"}
    await tb.safe_edit_text(
        callback.message,
        "✉️ <b>Личное сообщение</b>\n\nОтправь username пользователя (с @ или без) или его "
        "числовой ID. Сообщение будет отправлено только после подтверждения главным админом.",
        parse_mode="HTML",
        reply_markup=get_assistant_back_keyboard()
    )


@router.callback_query(F.data.startswith("assistant_dm_approve:"))
async def cb_assistant_dm_approve(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    req_id = callback.data.split(":", 1)[1]
    req = tb.ASSISTANT_DM_REQUESTS.pop(req_id, None)
    if req is None:
        await callback.answer("Заявка уже обработана (скорее всего, другим админом)", show_alert=True)
        return
    await callback.answer("Подтверждено ✅", show_alert=True)
    try:
        await tb.bot.send_message(
            req["target_id"],
            f"✉️ <b>Личное сообщение от администрации</b>\n{tb.DIVIDER}\n\n{req['text_html']}",
            parse_mode="HTML"
        )
        await tb.safe_edit_text(
            callback.message,
            f"✅ Отправлено {req['target_label']} (от помощника {req['assistant_label']}).",
            parse_mode="HTML"
        )
    except Exception:
        tb.logger.exception("Не удалось отправить согласованное сообщение помощника пользователю %s", req["target_id"])
        await tb.safe_edit_text(
            callback.message,
            f"⚠️ Не удалось отправить сообщение {req['target_label']} — возможно, он заблокировал бота.",
            parse_mode="HTML"
        )
    try:
        await tb.bot.send_message(
            req["assistant_id"],
            f"✅ Твоё сообщение для {req['target_label']} одобрено и отправлено.",
            parse_mode="HTML"
        )
    except Exception:
        tb.logger.exception("Не удалось уведомить помощника %s об одобрении сообщения", req["assistant_id"])

@router.callback_query(F.data.startswith("assistant_dm_reject:"))
async def cb_assistant_dm_reject(callback: CallbackQuery):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer()
        return
    req_id = callback.data.split(":", 1)[1]
    req = tb.ASSISTANT_DM_REQUESTS.pop(req_id, None)
    if req is None:
        await callback.answer("Заявка уже обработана (скорее всего, другим админом)", show_alert=True)
        return
    await callback.answer("Заявка отклонена", show_alert=True)
    await tb.safe_edit_text(
        callback.message,
        f"❌ Отклонено — сообщение для {req['target_label']} от помощника {req['assistant_label']} не отправлено.",
        parse_mode="HTML"
    )
    try:
        await tb.bot.send_message(
            req["assistant_id"],
            f"❌ Твой запрос на сообщение для {req['target_label']} отклонён администратором.",
            parse_mode="HTML"
        )
    except Exception:
        tb.logger.exception("Не удалось уведомить помощника %s об отклонении сообщения", req["assistant_id"])


# ==================== АДМИН ПЛАТЕЖЕЙ ====================
# Третья, отдельная от помощника роль (см. is_payment_admin в services/access.py) — не расширяет
# помощника, потому что у того уже задокументированный, сознательно урезанный контракт (доступ к
# разделам контента + статистика/модерируемое DM, без прав на платежи/рассылки). Админ платежей
# получает ровно две вещи: (1) one-tap подтверждение рублёвых заявок — это push-механизм, кнопка
# приходит прямо в личку через notify_admins_of_payment_request(), отдельного экрана в панели не
# нужно; (2) доступ к подразделу «Анонсы» (см. get_admin_announcements_keyboard, параметризован
# back_callback'ом именно ради этой роли — у неё нет доступа к полной admin_panel).

def get_payment_admin_menu_text() -> str:
    return (
        f"💳 <b>Панель админа платежей</b>\n{tb.DIVIDER}\n\n"
        "Заявки на оплату рублями приходят тебе личным сообщением с кнопкой подтверждения — "
        "открывать эту панель для этого не нужно. Здесь доступна рассылка анонсов.\n\n"
        "Выбери действие:"
    )

def get_payment_admin_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Анонсы", callback_data="admin_announcements_menu")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data == "payment_admin_panel")
async def cb_payment_admin_panel(callback: CallbackQuery):
    if not tb.is_payment_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_payment_admin_menu_text(),
        parse_mode="HTML",
        reply_markup=get_payment_admin_menu_keyboard()
    )
