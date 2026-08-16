"""Раздел «Гистология» — Router вместо прямой регистрации на глобальном dp (Phase 3 рефакторинга,
см. CLAUDE.md). Импортирует telegram_bot как tb вместо `from telegram_bot import ...`, потому что
сам telegram_bot.py импортирует этот модуль (см. блок "ГИСТОЛОГИЯ" там) — циклическая связь
разрешается тем, что этот импорт стоит в самом конце telegram_bot.py, когда все нужные отсюда
имена (stats, save_stats, safe_edit_text, DIVIDER, REFERRAL_*, TEMP_ACCESS_GRANT_SECONDS,
is_admin_or_assistant, is_section_promo_active, has_subscription_histology_access,
get_referral_count, cheapest_histology_tier, _broadcast, HISTOLOGY, HISTOLOGY_IMAGES_DIR) уже
определены в его модульном пространстве имён — обращения к ним разрешаются во время вызова
хендлера, не во время импорта этого файла."""
import os
import random
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

HISTOLOGY_PUBLIC = False  # когда раздел будет готов для всех — переключить на True
HISTOLOGY_PROMO_SECONDS = 24 * 60 * 60
HISTOLOGY_WARNING_THRESHOLD = tb.REFERRAL_WARNING_THRESHOLD  # 3 предупреждения, как у Биологии/Физики/Химии
HISTOLOGY_WARNING_COOLDOWN_SECONDS = tb.REFERRAL_WARNING_COOLDOWN_SECONDS  # не чаще раза в 4ч

def get_histology_temp_expiry(user_id: int) -> float:
    return tb.stats["histology_temp_access"].get(str(user_id), 0)

def has_histology_temp_access(user_id: int) -> bool:
    return time.time() < get_histology_temp_expiry(user_id)

def histology_permanently_unlocked(user_id: int) -> bool:
    """Доступ, не зависящий от тающего пробного окна (в отличие от has_histology_temp_access)."""
    return (
        HISTOLOGY_PUBLIC or tb.is_admin_or_assistant(user_id)
        or tb.is_section_promo_active("histology") or tb.is_section_promo_active("global")
        or tb.has_subscription_histology_access(user_id)
        or tb.get_referral_count(user_id) >= tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )

def histology_access_ok(user_id: int) -> bool:
    return histology_permanently_unlocked(user_id) or has_histology_temp_access(user_id)

async def histology_gate_ok(callback: CallbackQuery) -> bool:
    """Единый шлюз для контента гистологии — как у Биологии/Физики/Химии, только пробное окно
    без рефералов/подписки ограничено неделей, а не только числом предупреждений:
    1) первый визит — молча выдаём неделю пробного доступа (TEMP_ACCESS_GRANT_SECONDS);
    2) дальше — до HISTOLOGY_WARNING_THRESHOLD (3) предупреждений с кулдауном между ними;
    3) блок наступает по любому из двух условий: предупреждения исчерпаны ИЛИ неделя истекла —
       и снимается только рефералами (REFERRAL_FULL_ACCESS_THRESHOLD) или подпиской.
    Возвращает True, если хендлер должен продолжить (и сам обязан вызвать callback.answer()).
    Возвращает False, если гейт уже сам ответил на callback и отредактировал сообщение."""
    user_id = callback.from_user.id
    user_id_str = str(user_id)

    if histology_permanently_unlocked(user_id):
        return True

    if not has_histology_temp_access(user_id) and user_id_str not in tb.stats["histology_warnings"]:
        tb.stats["histology_temp_access"][user_id_str] = time.time() + tb.TEMP_ACCESS_GRANT_SECONDS
        tb.save_stats()
        return True

    entry = tb.stats["histology_warnings"].get(user_id_str, {"count": 0, "last_warn_at": 0})

    if not has_histology_temp_access(user_id) or entry["count"] >= HISTOLOGY_WARNING_THRESHOLD:
        await callback.answer("🚨 Гистология закрыта — пригласи друзей или оформи подписку!", show_alert=True)
        await tb.safe_edit_text(
            callback.message,
            get_histology_locked_text(),
            parse_mode="HTML",
            reply_markup=get_histology_locked_keyboard()
        )
        return False

    now = time.time()
    if now - entry.get("last_warn_at", 0) >= HISTOLOGY_WARNING_COOLDOWN_SECONDS:
        entry["count"] += 1
        entry["last_warn_at"] = now
        tb.stats["histology_warnings"][user_id_str] = entry
        tb.save_stats()
        remaining = HISTOLOGY_WARNING_THRESHOLD - entry["count"]
        days_left = max(int((get_histology_temp_expiry(user_id) - now) // 86400), 0)
        cheapest_histology = tb.cheapest_histology_tier()
        price_rub = cheapest_histology["price_rub"]
        price_stars = cheapest_histology["price_stars"]
        if remaining > 0:
            warn_text = (
                "⚠️❗️ <b>Гистология скоро закроется!</b> ❗️⚠️\n\n"
                f"Бесплатный пробный доступ действует ещё примерно <b>{days_left} дн.</b> Пригласи "
                f"{tb.REFERRAL_FULL_ACCESS_THRESHOLD} друзей или оформи подписку от <b>{price_rub}₽ / {price_stars}⭐</b> — "
                "и раздел останется открытым навсегда."
            )
        else:
            warn_text = (
                "🚨‼️ <b>ПОСЛЕДНЕЕ ПРЕДУПРЕЖДЕНИЕ!</b> ‼️🚨\n\n"
                f"В следующий раз доступ к Гистологии закроется, если не пригласишь "
                f"{tb.REFERRAL_FULL_ACCESS_THRESHOLD} друзей или не оформишь подписку от "
                f"<b>{price_rub}₽ / {price_stars}⭐</b>."
            )
        try:
            await callback.message.answer(warn_text, parse_mode="HTML", reply_markup=get_histology_locked_keyboard())
        except Exception:
            tb.logger.exception("Не удалось отправить предупреждение о гистологии пользователю %s", user_id)

    return True

def get_histology_specimen(diag_key: str, spec_id: str):
    diag = tb.HISTOLOGY.get(diag_key)
    if not diag:
        return None
    for spec in diag["specimens"]:
        if spec["id"] == spec_id:
            return spec
    return None

def get_histology_locked_text() -> str:
    cheapest = tb.cheapest_histology_tier()
    return (
        f"🔬 <b>Гистология</b>\n{tb.DIVIDER}\n\n"
        "✅ Раздел уже полностью готов и проработан: все микрофотографии и "
        "протоколы-описания взяты именно с препаратов академии, а содержание "
        "сверено с преподавателями.\n\n"
        f"Открывается бесплатно — как Биология, Физика и Химия — после "
        f"<b>{tb.REFERRAL_FULL_ACCESS_THRESHOLD}</b> приглашённых друзей, либо сразу по подписке от "
        f"<b>{cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐</b> "
        f"(тариф «{cheapest['title']}») и выше.\n\n"
        f"Новым пользователям раздел открыт бесплатно на пробный период (до недели)."
    )

def get_histology_locked_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Пригласить друзей", callback_data="referral_info")
    builder.button(text="💎 Оформить подписку", callback_data="subscription_menu")
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

async def announce_histology_promo_start() -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔬 Гистология", callback_data="histology_menu")
    text = (
        "🔬🎉 <b>ГИСТОЛОГИЯ ОТКРЫТА ДЛЯ ВСЕХ!</b> 🎉🔬\n"
        f"{tb.DIVIDER}\n\n"
        "На <b>24 часа</b> раздел «Гистология» — все препараты, микрофотографии и разборы — "
        "доступен абсолютно бесплатно, без рефералов и подписки.\n\n"
        f"После этого доступ, как обычно: {tb.REFERRAL_FULL_ACCESS_THRESHOLD} реферала или подписка.\n\n"
        "Успей посмотреть, пока открыто! 🚀"
    )
    await tb._broadcast(text, builder.as_markup())

def get_histology_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for diag_key, diag in tb.HISTOLOGY.items():
        builder.button(text=diag.get("menu_title", diag["title"]), callback_data=f"histology_topic:{diag_key}")
    builder.button(text="🎯 Угадай препарат (все разделы)", callback_data="histology_guess_start:all")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_histology_topic_text(diag_key: str) -> str:
    diag = tb.HISTOLOGY[diag_key]
    n = len(diag["specimens"])
    total = diag.get("total_official")
    progress = f"{n}" if not total or n >= total else f"{n} из {total}"
    note = "" if not total or n >= total else "\n\nОстальные препараты добавим по мере поступления презентаций."
    return (
        f"🔬 <b>{diag['title']}</b>\n{tb.DIVIDER}\n\n"
        f"Препаратов доступно: <b>{progress}</b>{note}\n\n"
        "Выбери препарат:"
    )

def get_histology_topic_keyboard(diag_key: str):
    diag = tb.HISTOLOGY[diag_key]
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Угадай препарат", callback_data=f"histology_guess_start:{diag_key}")
    for spec in diag["specimens"]:
        builder.button(text=f"№{spec['number']}. {spec['title']}", callback_data=f"histology_specimen:{diag_key}:{spec['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="histology_menu"))
    return builder.as_markup()

def get_histology_specimen_text(diag_key: str, spec_id: str) -> str:
    spec = get_histology_specimen(diag_key, spec_id)
    lines = [f"🔬 <b>№{spec['number']}. {spec['title']}</b>\n{tb.DIVIDER}\n"]
    if spec.get("stain"):
        lines.append(f"Окраска: {spec['stain']}")
    if spec.get("magnification"):
        lines.append(f"Увеличение: {spec['magnification']}")
    lines.append("")
    lines.append(spec["protocol"] or "Протокол-описание пока не добавлено.")
    return "\n".join(lines)

def get_histology_specimen_keyboard(diag_key: str, spec_id: str):
    spec = get_histology_specimen(diag_key, spec_id)
    builder = InlineKeyboardBuilder()
    n_img = len(spec.get("images", []))
    if n_img:
        builder.button(text=f"🖼 Микрофото ({n_img})", callback_data=f"histology_img:{diag_key}:{spec_id}:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку препаратов", callback_data=f"histology_topic:{diag_key}"))
    return builder.as_markup()

def get_histology_image_keyboard(diag_key: str, spec_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"histology_img:{diag_key}:{spec_id}:{idx-1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"histology_img:{diag_key}:{spec_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К препарату", callback_data=f"histology_specimen:{diag_key}:{spec_id}"))
    return builder.as_markup()

async def render_histology_image(callback: CallbackQuery, diag_key: str, spec_id: str, idx: int):
    spec = get_histology_specimen(diag_key, spec_id)
    images = spec.get("images", [])
    caption = f"🔬 №{spec['number']}. {spec['title']}\n\n{idx + 1}/{len(images)}"
    keyboard = get_histology_image_keyboard(diag_key, spec_id, idx, len(images))
    photo = FSInputFile(os.path.join(tb.HISTOLOGY_IMAGES_DIR, images[idx]))
    await callback.message.delete()
    await callback.message.answer_photo(photo, caption=caption, reply_markup=keyboard)

@router.callback_query(F.data == "histology_menu")
async def cb_histology_menu(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🔬 <b>Гистология</b>\n{tb.DIVIDER}\n\nВыбери диагностику:",
        parse_mode="HTML",
        reply_markup=get_histology_menu_keyboard()
    )

@router.callback_query(F.data.startswith("histology_topic:"))
async def cb_histology_topic(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    diag_key = callback.data.split(":")[1]
    if diag_key not in tb.HISTOLOGY:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_histology_topic_text(diag_key),
        parse_mode="HTML",
        reply_markup=get_histology_topic_keyboard(diag_key)
    )

@router.callback_query(F.data.startswith("histology_specimen:"))
async def cb_histology_specimen(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, diag_key, spec_id = callback.data.split(":")
    spec = get_histology_specimen(diag_key, spec_id)
    if not spec:
        await callback.answer("Препарат не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_histology_specimen_text(diag_key, spec_id),
        parse_mode="HTML",
        reply_markup=get_histology_specimen_keyboard(diag_key, spec_id)
    )

@router.callback_query(F.data.startswith("histology_img:"))
async def cb_histology_img(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, diag_key, spec_id, idx_s = callback.data.split(":")
    idx = int(idx_s)
    spec = get_histology_specimen(diag_key, spec_id)
    images = spec.get("images", []) if spec else []
    if not images or not (0 <= idx < len(images)):
        await callback.answer("Фото для этого препарата пока нет", show_alert=True)
        return
    await callback.answer()
    await render_histology_image(callback, diag_key, spec_id, idx)

# ---- Угадай препарат ----
HISTOLOGY_GUESS_SESSION_SIZE = 10
HISTOLOGY_GUESS_SESSIONS: dict[int, dict] = {}

def get_histology_guess_pool(scope: str):
    # only specimens with a verified label-free "guess_image" are eligible --
    # many source slides bake the answer or structure labels into every available
    # photo, so those specimens are deliberately left out of this mode.
    if scope == "all":
        return [(diag_key, spec["id"]) for diag_key, diag in tb.HISTOLOGY.items()
                 for spec in diag["specimens"] if spec.get("guess_image")]
    diag = tb.HISTOLOGY.get(scope)
    if not diag:
        return []
    return [(scope, spec["id"]) for spec in diag["specimens"] if spec.get("guess_image")]

def start_histology_guess_session(user_id: int, scope: str) -> bool:
    pool = get_histology_guess_pool(scope)
    if not pool:
        return False
    size = min(HISTOLOGY_GUESS_SESSION_SIZE, len(pool))
    HISTOLOGY_GUESS_SESSIONS[user_id] = {
        "scope": scope,
        "items": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }
    return True

def get_histology_guess_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="histology_guess_show_answer")
    builder.button(text="🛑 Закончить", callback_data="histology_guess_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_histology_guess_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Угадал(а)", callback_data="histology_guess_know")
    builder.button(text="❌ Не угадал(а)", callback_data="histology_guess_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="histology_guess_stop"))
    return builder.as_markup()

def get_histology_guess_summary_keyboard(scope: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data=f"histology_guess_start:{scope}")
    if scope == "all":
        builder.button(text="🔙 К разделу", callback_data="histology_menu")
    else:
        builder.button(text="🔙 К разделу", callback_data=f"histology_topic:{scope}")
    builder.adjust(1)
    return builder.as_markup()

async def render_histology_guess_question(callback: CallbackQuery, user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    total = len(session["items"])
    diag_key, spec_id = session["items"][session["index"]]
    spec = get_histology_specimen(diag_key, spec_id)
    caption = f"🎯 Угадай препарат — {session['index'] + 1}/{total}\n\nЧто это за препарат?"
    photo = FSInputFile(os.path.join(tb.HISTOLOGY_IMAGES_DIR, spec["guess_image"]))
    await callback.message.delete()
    sent = await callback.message.answer_photo(photo, caption=caption, reply_markup=get_histology_guess_question_keyboard())
    session["msg"] = sent

async def render_histology_guess_answer(user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    total = len(session["items"])
    diag_key, spec_id = session["items"][session["index"]]
    spec = get_histology_specimen(diag_key, spec_id)
    lines = [f"🎯 Угадай препарат — {session['index'] + 1}/{total}", "", f"№{spec['number']}. {spec['title']}"]
    if spec.get("stain"):
        lines.append(f"Окраска: {spec['stain']}")
    if spec.get("magnification"):
        lines.append(f"Увеличение: {spec['magnification']}")
    lines.append("")
    lines.append("Ты угадал(а)?")
    await session["msg"].edit_caption(caption="\n".join(lines), reply_markup=get_histology_guess_answer_keyboard())

async def render_histology_guess_summary(user_id: int, aborted: bool = False):
    session = HISTOLOGY_GUESS_SESSIONS.pop(user_id, None)
    if not session:
        return
    scope = session["scope"]
    answered = session["know"] + session["dont_know"]
    title = "🛑 Прервано" if aborted else "🏁 Препараты закончились!"
    caption = (
        f"{title}\n\n"
        f"Отвечено: {answered}\n✅ Угадано: {session['know']}\n❌ Не угадано: {session['dont_know']}"
    )
    await session["msg"].edit_caption(caption=caption, reply_markup=get_histology_guess_summary_keyboard(scope))

@router.callback_query(F.data.startswith("histology_guess_start:"))
async def cb_histology_guess_start(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    scope = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    if not start_histology_guess_session(user_id, scope):
        await callback.answer("Препаратов пока нет", show_alert=True)
        return
    await callback.answer()
    await render_histology_guess_question(callback, user_id)

@router.callback_query(F.data == "histology_guess_show_answer")
async def cb_histology_guess_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in HISTOLOGY_GUESS_SESSIONS:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_histology_guess_answer(user_id)

@router.callback_query(F.data.in_({"histology_guess_know", "histology_guess_dont_know"}))
async def cb_histology_guess_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = HISTOLOGY_GUESS_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "histology_guess_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["items"]):
        await render_histology_guess_summary(user_id)
    else:
        await render_histology_guess_question(callback, user_id)

@router.callback_query(F.data == "histology_guess_stop")
async def cb_histology_guess_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in HISTOLOGY_GUESS_SESSIONS:
        await render_histology_guess_summary(callback.from_user.id, aborted=True)
