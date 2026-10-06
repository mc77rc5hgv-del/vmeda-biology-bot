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
import asyncio
import uuid
import random
import time
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()


async def _learning_call(function, *args):
    if os.environ.get("BOT_SYNC_MODE") == "owner":
        return await asyncio.to_thread(function, *args)
    return function(*args)


HISTOLOGY_PUBLIC = False  # когда раздел будет готов для всех — переключить на True
HISTOLOGY_PROMO_SECONDS = 24 * 60 * 60
HISTOLOGY_WARNING_THRESHOLD = tb.REFERRAL_WARNING_THRESHOLD  # 3 предупреждения, как у Биологии/Физики/Химии
HISTOLOGY_WARNING_COOLDOWN_SECONDS = tb.REFERRAL_WARNING_COOLDOWN_SECONDS  # не чаще раза в 4ч

def get_histology_temp_expiry(user_id: int) -> float:
    return tb.stats["histology_temp_access"].get(str(user_id), 0)

def has_histology_temp_access(user_id: int) -> bool:
    return time.time() < get_histology_temp_expiry(user_id)

def histology_permanently_unlocked(user_id: int) -> bool:
    """Доступ, не зависящий от тающего пробного окна (в отличие от has_histology_temp_access) —
    имя осталось от старой (разовой навсегда) модели рефералов; сейчас реферальная ветка сама по
    себе ЕЖЕМЕСЯЧНО обновляемая (см. tb.get_referral_count_this_month), просто в контрасте с
    неделей пробного доступа она по-прежнему "не временная"."""
    return (
        HISTOLOGY_PUBLIC or tb.is_admin_or_assistant(user_id)
        or tb.is_section_promo_active("histology") or tb.is_section_promo_active("global")
        or tb.has_subscription_histology_access(user_id)
        or tb.get_referral_count_this_month(user_id) >= tb.REFERRAL_FULL_ACCESS_THRESHOLD
    )

def histology_access_ok(user_id: int) -> bool:
    if histology_permanently_unlocked(user_id):
        return True
    warnings = tb.stats['histology_warnings'].get(str(user_id), {})
    return has_histology_temp_access(user_id) and warnings.get('count', 0) < HISTOLOGY_WARNING_THRESHOLD

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
    from services.content_access import enter
    decision = enter(tb, user_id, 'histology')
    if not decision['allowed']:
        await callback.answer("🚨 Гистология закрыта — пригласи друзей или оформи подписку!", show_alert=True)
        await tb.safe_edit_text(
            callback.message,
            get_histology_locked_text(),
            parse_mode="HTML",
            reply_markup=get_histology_locked_keyboard()
        )
        return False

    now = time.time()
    if decision['warning']:
        remaining = decision['warnings_remaining']
        days_left = max(int((get_histology_temp_expiry(user_id) - now) // 86400), 0)
        cheapest_histology = tb.cheapest_histology_tier()
        price_rub = cheapest_histology["price_rub"]
        price_stars = cheapest_histology["price_stars"]
        if remaining > 0:
            warn_text = (
                "⚠️❗️ <b>Гистология скоро закроется!</b> ❗️⚠️\n\n"
                f"Бесплатный пробный доступ действует ещё примерно <b>{days_left} дн.</b> Пригласи "
                f"{tb.REFERRAL_FULL_ACCESS_THRESHOLD} друзей в этом месяце или оформи подписку от "
                f"<b>{price_rub}₽ / {price_stars}⭐</b> — и раздел откроется (рефералами — доступ "
                "нужно будет подтверждать новыми друзьями каждый месяц)."
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
        "Микрофотографии, учебные схемы, описания и ориентиры для подготовки "
        "к распознаванию препаратов. Пояснения к каждому кадру помогают "
        "сопоставить изображение с теорией.\n\n"
        f"Открывается бесплатно — как Биология, Физика и Химия — после "
        f"<b>{tb.REFERRAL_FULL_ACCESS_THRESHOLD}</b> приглашённых друзей в этом месяце, либо сразу по подписке от "
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
        f"После этого доступ, как обычно: {tb.REFERRAL_FULL_ACCESS_THRESHOLD} реферала в этом месяце или подписка.\n\n"
        "Успей посмотреть, пока открыто! 🚀"
    )
    await tb._broadcast(text, builder.as_markup())

def get_histology_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎓 Практический зачёт · 10", callback_data="histology_guess_start:all")
    builder.button(text="🩺 Работа над ошибками", callback_data="histology_guess_start:mistakes")
    builder.button(text="📊 Моя статистика", callback_data="histology_stats")
    for diag_key, diag in tb.HISTOLOGY.items():
        builder.button(text=diag.get("menu_title", diag["title"]), callback_data=f"histology_topic:{diag_key}")
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
    lines = [f"🔬 <b>№{spec['number']}. {escape(spec['title'])}</b>\n{tb.DIVIDER}\n"]
    if spec.get("stain"):
        lines.append(f"Окраска исходного препарата: {escape(spec['stain'])}")
    if spec.get("magnification"):
        lines.append(f"Увеличение исходного препарата: {escape(str(spec['magnification']))}")
    if spec.get("metadata_note"):
        lines.append(escape(spec["metadata_note"]))
    lines.append("")
    lines.append(escape(spec["protocol"] or "Протокол-описание пока не добавлено."))
    sources = spec.get("sources", [])
    if sources:
        lines.append("\nУчебные источники:")
        lines.extend(f'<a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a>'
                     for source in sources)
    return "\n".join(lines)

def get_histology_specimen_keyboard(diag_key: str, spec_id: str):
    spec = get_histology_specimen(diag_key, spec_id)
    builder = InlineKeyboardBuilder()
    n_img = len(spec.get("images", []))
    if n_img:
        builder.button(text=f"🖼 Изображения ({n_img})", callback_data=f"histology_img:{diag_key}:{spec_id}:0")
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
    from services.histology_content import image_caption
    caption = f"🔬 №{spec['number']}. " + image_caption(spec, idx) + f"\n\n{idx + 1}/{len(images)}"
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
        f"🔬 <b>Гистология · ЭКЗАМЕН</b>\n{tb.DIVIDER}\n\n"
        "Здесь связаны протоколы, микрофотографии, практический зачёт, работа над ошибками и статистика.\n\n"
        "Выбери режим или раздел каталога:",
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

# ---- ЭКЗАМЕН: практический зачёт, ошибки и статистика ----
HISTOLOGY_GUESS_SESSION_SIZE = 10
HISTOLOGY_GUESS_SESSIONS: dict[int, dict] = {}


def get_histology_learning(user_id: int) -> dict:
    if os.environ.get('BOT_SYNC_MODE') == 'owner':
        from services.histology_sync import entry
        return entry(tb, user_id)
    key = str(user_id)
    entry = tb.stats.setdefault("histology_learning", {}).setdefault(key, {})
    entry.setdefault("attempts", 0)
    entry.setdefault("known", 0)
    entry.setdefault("wrong", 0)
    entry.setdefault("mistakes", [])
    entry.setdefault("mastered", [])
    return entry


def record_histology_result(user_id: int, specimen_id: str, known: bool, event_id: str | None = None) -> dict:
    if os.environ.get('BOT_SYNC_MODE') == 'owner':
        from web_api import learning
        learning.record_histology_attempt(user_id, specimen_id, known, event_id=event_id or uuid.uuid4().hex)
        return {}
    entry = get_histology_learning(user_id)
    entry["attempts"] += 1
    if known:
        entry["known"] += 1
        if specimen_id in entry["mistakes"]:
            entry["mistakes"].remove(specimen_id)
        if specimen_id not in entry["mastered"]:
            entry["mastered"].append(specimen_id)
    else:
        entry["wrong"] += 1
        if specimen_id not in entry["mistakes"]:
            entry["mistakes"].append(specimen_id)
    tb.save_stats()
    return entry


def get_histology_stats_text(user_id: int) -> str:
    entry = get_histology_learning(user_id)
    attempts = entry["attempts"]
    accuracy = round(entry["known"] / attempts * 100) if attempts else 0
    return (
        f"📊 <b>Статистика · Гистология</b>\n{tb.DIVIDER}\n\n"
        f"Всего попыток: <b>{attempts}</b>\n"
        f"Узнано правильно: <b>{entry['known']}</b>\n"
        f"Ошибок: <b>{entry['wrong']}</b>\n"
        f"Точность: <b>{accuracy}%</b>\n"
        f"Освоено препаратов: <b>{len(entry['mastered'])} из 71</b>\n"
        f"В активной работе над ошибками: <b>{len(entry['mistakes'])}</b>"
    )

def get_histology_guess_pool(scope: str):
    # only specimens with a verified label-free "guess_image" are eligible --
    # many source slides bake the answer or structure labels into every available
    # photo, so those specimens are deliberately left out of this mode.
    if scope == "all":
        return [(diag_key, spec["id"]) for diag_key, diag in tb.HISTOLOGY.items()
                 for spec in diag["specimens"] if spec.get("guess_image")]
    if scope == "mistakes":
        # user-specific filtering is done in start_histology_guess_session, where user_id exists.
        return [(diag_key, spec["id"]) for diag_key, diag in tb.HISTOLOGY.items()
                for spec in diag["specimens"] if spec.get("guess_image")]
    diag = tb.HISTOLOGY.get(scope)
    if not diag:
        return []
    return [(scope, spec["id"]) for spec in diag["specimens"] if spec.get("guess_image")]

def start_histology_guess_session(user_id: int, scope: str) -> bool:
    pool = get_histology_guess_pool(scope)
    if scope == "mistakes":
        mistake_ids = set(get_histology_learning(user_id)["mistakes"])
        pool = [(diag_key, spec_id) for diag_key, spec_id in pool if spec_id in mistake_ids]
    if not pool:
        return False
    size = min(HISTOLOGY_GUESS_SESSION_SIZE, len(pool))
    HISTOLOGY_GUESS_SESSIONS[user_id] = {
        'id': uuid.uuid4().hex[:12],
        "scope": scope,
        "items": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }
    return True

def get_histology_guess_question_keyboard(session=None):
    builder = InlineKeyboardBuilder()
    suffix = f":{session['id']}:{session['index']}" if session else ''
    builder.button(text="🙈 Показать ответ", callback_data="histology_guess_show_answer" + suffix)
    builder.button(text="🛑 Закончить", callback_data="histology_guess_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_histology_guess_answer_keyboard(session=None):
    builder = InlineKeyboardBuilder()
    suffix = f":{session['id']}:{session['index']}" if session else ''
    builder.button(text="✅ Угадал(а)", callback_data="histology_guess_know" + suffix)
    builder.button(text="❌ Не угадал(а)", callback_data="histology_guess_dont_know" + suffix)
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="histology_guess_stop"))
    return builder.as_markup()

def get_histology_guess_summary_keyboard(scope: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data=f"histology_guess_start:{scope}")
    if scope in {"all", "mistakes"}:
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
    mode = "Работа над ошибками" if session["scope"] == "mistakes" else "Практический зачёт"
    caption = f"🎓 {mode} — {session['index'] + 1}/{total}\n\nЧто это за препарат?"
    photo = FSInputFile(os.path.join(tb.HISTOLOGY_IMAGES_DIR, spec["guess_image"]))
    await callback.message.delete()
    sent = await callback.message.answer_photo(photo, caption=caption, reply_markup=get_histology_guess_question_keyboard(session))
    session["msg"] = sent

async def render_histology_guess_answer(user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    total = len(session["items"])
    diag_key, spec_id = session["items"][session["index"]]
    spec = get_histology_specimen(diag_key, spec_id)
    lines = [f"🎓 Практический зачёт — {session['index'] + 1}/{total}", "", f"№{spec['number']}. {spec['title']}"]
    if spec.get("stain"):
        lines.append(f"Окраска: {spec['stain']}")
    if spec.get("magnification"):
        lines.append(f"Увеличение: {spec['magnification']}")
    lines.append("")
    lines.append("Ты угадал(а)?")
    await session["msg"].edit_caption(caption="\n".join(lines), reply_markup=get_histology_guess_answer_keyboard(session))

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
    if not await _learning_call(start_histology_guess_session, user_id, scope):
        message = "Ошибок для повторения пока нет" if scope == "mistakes" else "Препаратов пока нет"
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    await render_histology_guess_question(callback, user_id)

@router.callback_query(F.data.startswith("histology_guess_show_answer:"))
async def cb_histology_guess_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = HISTOLOGY_GUESS_SESSIONS.get(user_id)
    fields = callback.data.split(':')
    if not session or len(fields) != 3 or fields[1:] != [session['id'], str(session['index'])] or session.get('saving') or session['index'] >= len(session['items']):
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await render_histology_guess_answer(user_id)
    await callback.answer()

@router.callback_query(F.data.startswith('histology_guess_know:') | F.data.startswith('histology_guess_dont_know:'))
async def cb_histology_guess_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = HISTOLOGY_GUESS_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    fields = callback.data.split(':')
    if len(fields) != 3 or fields[1] != session.get('id') or fields[2] != str(session['index']) or session.get('saving'):
        await callback.answer('Этот ответ уже обработан или вопрос устарел')
        return
    session['saving'] = True
    diag_key, spec_id = session["items"][session["index"]]
    known = fields[0] == "histology_guess_know"
    try:
        await _learning_call(record_histology_result, user_id, spec_id, known, f"bot:{session['id']}:{session['index']}")
        if known:
            session["know"] += 1
        else:
            session["dont_know"] += 1
        session["index"] += 1
    except Exception:
        tb.logger.exception('Не удалось сохранить попытку гистологии')
        await callback.answer('Ответ пока не сохранён. Повтори нажатие.', show_alert=True)
        return
    finally:
        session['saving'] = False
    await callback.answer()
    if HISTOLOGY_GUESS_SESSIONS.get(user_id) is not session:
        return
    if session["index"] >= len(session["items"]):
        await render_histology_guess_summary(user_id)
    else:
        await render_histology_guess_question(callback, user_id)

@router.callback_query(F.data == "histology_guess_stop")
async def cb_histology_guess_stop(callback: CallbackQuery):
    session = HISTOLOGY_GUESS_SESSIONS.get(callback.from_user.id)
    if session and session.get('saving'):
        await callback.answer('Дождись сохранения ответа')
        return
    await callback.answer()
    if callback.from_user.id in HISTOLOGY_GUESS_SESSIONS:
        await render_histology_guess_summary(callback.from_user.id, aborted=True)


@router.callback_query(F.data == "histology_stats")
async def cb_histology_stats(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    if (await _learning_call(get_histology_learning, callback.from_user.id))["mistakes"]:
        builder.button(text="🩺 Повторить ошибки", callback_data="histology_guess_start:mistakes")
    builder.button(text="🎓 Практический зачёт", callback_data="histology_guess_start:all")
    builder.button(text="🔙 К экзамену", callback_data="histology_menu")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        await _learning_call(get_histology_stats_text, callback.from_user.id),
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
