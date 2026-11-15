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
from services import histology_content, histology_exam
from services.telegram_ui import safe_delete_message

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

def get_histology_specimen(diag_key: str, spec_id: str, exam: bool = False):
    bank = histology_content.exam_groups(tb.HISTOLOGY) if exam else tb.HISTOLOGY
    diag = bank.get(diag_key)
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

def _menu(rows, back):
    builder = InlineKeyboardBuilder()
    for label, data in rows:
        builder.button(text=label, callback_data=data)
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=back))
    return builder.as_markup()


def get_histology_menu_keyboard():
    return _menu([("Экзамен", "histology_exam"), ("ДИАГНОСТИКИ", "histology_diagnostics")], "back_to_main")


def get_histology_exam_keyboard():
    return _menu([
        ("Препараты", "histology_exam_specimens"),
        ("Тесты", "histology_tests"),
        ("Теоретические вопросы", "histology_theory"),
        ("УГАДАЙ ПРЕПАРАТ", "histology_guess_menu"),
    ], "histology_menu")


def get_histology_catalog_keyboard(exam: bool = False):
    suffix = ":exam" if exam else ""
    bank = histology_content.exam_groups(tb.HISTOLOGY) if exam else tb.HISTOLOGY
    return _menu([
        (diag.get("menu_title", diag["title"]), f"histology_topic:{key}{suffix}")
        for key, diag in bank.items()
    ], "histology_exam" if exam else "histology_menu")


def get_histology_topic_text(diag_key: str, exam: bool = False) -> str:
    bank = histology_content.exam_groups(tb.HISTOLOGY) if exam else tb.HISTOLOGY
    diag = bank[diag_key]
    n = len(diag["specimens"])
    total = diag.get("total_official") if not exam else n
    progress = f"{n}" if not total or n >= total else f"{n} из {total}"
    note = "" if not total or n >= total else "\n\nОстальные препараты добавим по мере поступления презентаций."
    return (
        f"🔬 <b>{diag['title']}</b>\n{tb.DIVIDER}\n\n"
        f"Препаратов доступно: <b>{progress}</b>{note}\n\n"
        "Выбери препарат:"
    )

def get_histology_topic_keyboard(diag_key: str, exam: bool = False):
    suffix = ":exam" if exam else ""
    bank = histology_content.exam_groups(tb.HISTOLOGY) if exam else tb.HISTOLOGY
    diag = bank[diag_key]
    builder = InlineKeyboardBuilder()
    if not exam and get_histology_guess_pool(diag_key):
        builder.button(text="🎯 Угадай препарат", callback_data=f"histology_guess_start:{diag_key}")
    for spec in diag["specimens"]:
        builder.button(text=f"№{spec['number']}. {spec['title']}", callback_data=f"histology_specimen:{diag_key}:{spec['id']}{suffix}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(
        text="🔙 К списку", callback_data="histology_exam_specimens" if exam else "histology_diagnostics"
    ))
    return builder.as_markup()

def get_histology_specimen_text(diag_key: str, spec_id: str, exam: bool = False) -> str:
    spec = get_histology_specimen(diag_key, spec_id, exam)
    lines = [f"🔬 <b>№{spec['number']}. {escape(spec['title'])}</b>\n{tb.DIVIDER}\n"]
    if spec.get("stain"):
        lines.append(f"Окраска исходного препарата: {escape(spec['stain'])}")
    if spec.get("magnification"):
        lines.append(f"Увеличение исходного препарата: {escape(str(spec['magnification']))}")
    if spec.get("metadata_note"):
        lines.append(escape(spec["metadata_note"]))
    lines.append("")
    lines.append(escape(spec["protocol"] or "Протокол-описание пока не добавлено."))
    return "\n".join(lines)

def get_histology_specimen_keyboard(diag_key: str, spec_id: str, exam: bool = False):
    suffix = ":exam" if exam else ""
    spec = get_histology_specimen(diag_key, spec_id, exam)
    builder = InlineKeyboardBuilder()
    n_img = len(spec.get("images", []))
    if n_img:
        builder.button(text=f"🖼 Изображения ({n_img})", callback_data=f"histology_img:{diag_key}:{spec_id}:0{suffix}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку препаратов", callback_data=f"histology_topic:{diag_key}{suffix}"))
    return builder.as_markup()

def get_histology_image_keyboard(diag_key: str, spec_id: str, idx: int, total: int, exam: bool = False):
    suffix = ":exam" if exam else ""
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"histology_img:{diag_key}:{spec_id}:{idx-1}{suffix}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"histology_img:{diag_key}:{spec_id}:{idx+1}{suffix}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К препарату", callback_data=f"histology_specimen:{diag_key}:{spec_id}{suffix}"))
    return builder.as_markup()

async def render_histology_image(callback: CallbackQuery, diag_key: str, spec_id: str, idx: int,
                                 exam: bool = False):
    spec = get_histology_specimen(diag_key, spec_id, exam)
    images = spec.get("images", [])
    from services.histology_content import image_caption
    caption = f"🔬 №{spec['number']}. " + image_caption(spec, idx) + f"\n\n{idx + 1}/{len(images)}"
    keyboard = get_histology_image_keyboard(diag_key, spec_id, idx, len(images), exam)
    photo = FSInputFile(os.path.join(tb.HISTOLOGY_IMAGES_DIR, images[idx]))
    await callback.message.answer_photo(photo, caption=caption, reply_markup=keyboard)
    await safe_delete_message(callback.message)

@router.callback_query(F.data == "histology_menu")
async def cb_histology_menu(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🔬 <b>Гистология</b>\n{tb.DIVIDER}",
        parse_mode="HTML",
        reply_markup=get_histology_menu_keyboard(),
    )


@router.callback_query(F.data == "histology_exam")
async def cb_histology_exam(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    await callback.answer()
    await tb.safe_edit_text(callback.message, "🎓 Экзамен по гистологии", reply_markup=get_histology_exam_keyboard())


@router.callback_query(F.data.in_({"histology_exam_specimens", "histology_diagnostics"}))
async def cb_histology_catalog(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    exam = callback.data == "histology_exam_specimens"
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, f"🔬 Экзаменационные препараты · {len(histology_content.exam_specimens())}" if exam else "🔬 ДИАГНОСТИКИ",
        reply_markup=get_histology_catalog_keyboard(exam),
    )


@router.callback_query(F.data == "histology_guess_menu")
async def cb_histology_guess_menu(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    await callback.answer()
    count = len(get_histology_guess_pool("all"))
    await tb.safe_edit_text(callback.message, f"🎯 УГАДАЙ ПРЕПАРАТ\n\nВ базе: {count} экзаменационных препаратов", reply_markup=_menu([
        ("Начать · 10 микрофотографий", "histology_guess_start:all"),
        ("Работа над ошибками", "histology_guess_start:mistakes"),
        ("Моя статистика", "histology_stats"),
    ], "histology_exam"))


@router.callback_query(F.data.startswith("histology_topic:"))
async def cb_histology_topic(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, diag_key, *context = callback.data.split(":")
    exam = context == ["exam"]
    bank = histology_content.exam_groups(tb.HISTOLOGY) if exam else tb.HISTOLOGY
    if diag_key not in bank:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_histology_topic_text(diag_key, exam),
        parse_mode="HTML",
        reply_markup=get_histology_topic_keyboard(diag_key, exam)
    )

@router.callback_query(F.data.startswith("histology_specimen:"))
async def cb_histology_specimen(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, diag_key, spec_id, *context = callback.data.split(":")
    exam = context == ["exam"]
    spec = get_histology_specimen(diag_key, spec_id, exam)
    if not spec:
        await callback.answer("Препарат не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_histology_specimen_text(diag_key, spec_id, exam),
        parse_mode="HTML",
        reply_markup=get_histology_specimen_keyboard(diag_key, spec_id, exam)
    )

@router.callback_query(F.data.startswith("histology_img:"))
async def cb_histology_img(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, diag_key, spec_id, idx_s, *context = callback.data.split(":")
    idx = int(idx_s)
    exam = context == ["exam"]
    spec = get_histology_specimen(diag_key, spec_id, exam)
    images = spec.get("images", []) if spec else []
    if not images or not (0 <= idx < len(images)):
        await callback.answer("Фото для этого препарата пока нет", show_alert=True)
        return
    await callback.answer()
    await render_histology_image(callback, diag_key, spec_id, idx, exam)

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
    exam_ids = histology_content.exam_specimens().keys()
    attempts = entry["attempts"]
    accuracy = round(entry["known"] / attempts * 100) if attempts else 0
    return (
        f"📊 <b>Статистика · Гистология</b>\n{tb.DIVIDER}\n\n"
        f"Всего попыток: <b>{attempts}</b>\n"
        f"Узнано правильно: <b>{entry['known']}</b>\n"
        f"Ошибок: <b>{entry['wrong']}</b>\n"
        f"Точность: <b>{accuracy}%</b>\n"
        f"Освоено препаратов: <b>{len(exam_ids & entry['mastered'])} из {len(exam_ids)}</b>\n"
        f"В активной работе над ошибками: <b>{len(exam_ids & entry['mistakes'])}</b>"
    )

def get_histology_guess_pool(scope: str):
    return [
        (diag_key, spec["id"])
        for diag_key, diag in histology_content.exam_groups(tb.HISTOLOGY).items()
        if scope in {"all", "mistakes", diag_key}
        for spec in diag["specimens"]
        if spec.get("guess_image")
    ]

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
        builder.button(text="🔙 К тренажёру", callback_data="histology_guess_menu")
    else:
        builder.button(text="🔙 К разделу", callback_data=f"histology_topic:{scope}")
    builder.adjust(1)
    return builder.as_markup()

async def render_histology_guess_question(callback: CallbackQuery, user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    if session.get("rendering"):
        return
    session["rendering"] = True
    try:
        total = len(session["items"])
        index = session["index"]
        diag_key, spec_id = session["items"][index]
        spec = get_histology_specimen(diag_key, spec_id, exam=True)
        mode = "Работа над ошибками" if session["scope"] == "mistakes" else "Практический зачёт"
        caption = f"🎓 {mode} — {index + 1}/{total}\n\nЧто это за препарат?"
        photo = FSInputFile(os.path.join(tb.HISTOLOGY_IMAGES_DIR, spec["guess_image"]))
        sent = await callback.message.answer_photo(photo, caption=caption, reply_markup=get_histology_guess_question_keyboard(session))
        session["msg"] = sent
        session["displayed_index"] = index
        session["delivery_failed"] = False
        await safe_delete_message(callback.message)
    except BaseException:
        session["delivery_failed"] = session.get("displayed_index") != session["index"]
        raise
    finally:
        session["rendering"] = False

async def render_histology_guess_answer(user_id: int):
    session = HISTOLOGY_GUESS_SESSIONS[user_id]
    total = len(session["items"])
    diag_key, spec_id = session["items"][session["index"]]
    spec = get_histology_specimen(diag_key, spec_id, exam=True)
    lines = [f"🎓 Практический зачёт — {session['index'] + 1}/{total}", "", f"№{spec['number']}. {spec['title']}"]
    if spec.get("stain"):
        lines.append(f"Окраска: {spec['stain']}")
    if spec.get("guess_image_note"):
        lines.append(spec["guess_image_note"])
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
    if session.get('rendering'):
        await callback.answer('Показываю текущий препарат…')
        return
    # A previous answer can be durable even if sending the next photo failed.
    # Retrying its old button resumes delivery, never records the answer again.
    if (len(fields) == 3 and fields[1] == session.get('id') and fields[2].isdigit()
            and int(fields[2]) < session['index'] < len(session['items'])
            and session.get('delivery_failed') and not session.get('saving')):
        await callback.answer('Ответ сохранён. Показываю следующий препарат.')
        await render_histology_guess_question(callback, user_id)
        return
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
    builder.button(text="🔙 К тренажёру", callback_data="histology_guess_menu")
    builder.adjust(1)
    await tb.safe_edit_text(
        callback.message,
        await _learning_call(get_histology_stats_text, callback.from_user.id),
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )



@router.callback_query(F.data.regexp(r"^histology_theory(?::\d{1,3})?$"))
async def cb_histology_theory(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, _, number = callback.data.partition(":")
    sections = histology_exam.theory_catalog()
    section = next((s for s in sections if str(s["id"]) == number), None)
    if number and section is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    if section is None:
        title = "Теоретические вопросы"
        rows = [(s["title"], f"histology_theory:{s['id']}") for s in sections]
        back = "histology_exam"
    else:
        title = section["title"]
        rows = [(f"{q['number']}. {q['title'][:65]}", f"histology_theory_q:{q['number']}:{section['id']}")
                for q in section["questions"]]
        back = "histology_theory"
    await tb.safe_edit_text(callback.message, escape(title), reply_markup=_menu(rows, back))


@router.callback_query(F.data.regexp(r"^histology_theory_q:\d{1,3}:\d{1,3}$"))
async def cb_histology_theory_answer(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    _, number, section = callback.data.split(":")
    question = histology_exam.theory_questions().get(int(number))
    if question is None:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.answer()
    paragraphs = [f"<b>{escape(p['label'])}</b> {escape(p['text'])}" for p in question["paragraphs"]]
    title = f"<b>{number}. {escape(question['title'])}</b>"
    await tb.safe_edit_text(
        callback.message, "\n\n".join([title, *paragraphs]), parse_mode="HTML",
        reply_markup=_menu([], f"histology_theory:{section}"),
    )


_TEST_SESSIONS: dict[int, dict] = {}
_TEST_LETTERS = "АБВГ"


def _test_text(question):
    lines = [f"<b>{escape(question['question'])}</b>", ""]
    lines.extend(f"{letter}. {escape(option)}" for letter, option in zip(_TEST_LETTERS, question["options"]))
    return "\n".join(lines)


def _test_explanation(question):
    answer = histology_exam.review_answer(question)
    option = answer["correct_option"]
    source = answer["source_correct_option"]
    lines = []
    if option is None:
        lines.append("<b>Спорное задание. Балл не начисляется.</b>")
    else:
        lines.append(f"<b>Учебный ответ — {_TEST_LETTERS[option - 1]}.</b>")
    if source != option:
        lines.append(f"Ключ в сборнике — {_TEST_LETTERS[source - 1]}.")
    lines.append(escape(answer["explanation"]))
    return "\n".join(lines)


async def _render_test_question(message, session):
    index = session["index"]
    questions = session["questions"]
    q = questions[index]
    suffix = f"{session['id']}:{index}"
    title = f"Вопрос {index + 1} из {len(questions)}"
    text = f"{title}\n\n{_test_text(q)}"
    markup = InlineKeyboardBuilder()
    selected = session["answers"].get(index)
    if selected is None:
        markup.row(*[
            InlineKeyboardButton(text=letter, callback_data=f"histology_test_pick:{suffix}:{i}")
            for i, letter in enumerate(_TEST_LETTERS, 1)
        ])
    else:
        choice = _TEST_LETTERS[selected - 1]
        answer = q["correct_option"]
        verdict = "" if answer is None else (" Верно." if selected == answer else " Неверно.")
        text += f"\n\nТвой ответ — {choice}.{verdict}\n\n{_test_explanation(q)}"
        label = "Показать результат" if index + 1 == len(questions) else "Следующий вопрос →"
        markup.row(InlineKeyboardButton(text=label, callback_data=f"histology_test_next:{suffix}"))
    if index > 0:
        markup.row(InlineKeyboardButton(text="← Предыдущий вопрос", callback_data=f"histology_test_prev:{suffix}"))
    markup.row(InlineKeyboardButton(text="К меню тестов", callback_data="histology_tests"))
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=markup.as_markup())


@router.callback_query(
    F.data.in_({"histology_tests", "histology_test_topics"})
    | F.data.regexp(r"^histology_test_start(?::[a-z0-9-]+)?$")
)
async def cb_histology_tests(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    user_id = callback.from_user.id
    if callback.data.startswith("histology_test_start"):
        module_id = callback.data.partition(":")[2] or None
        try:
            questions = histology_exam.start_test(module_id)
        except KeyError:
            await callback.answer("Тема не найдена", show_alert=True)
            return
        session = {
            "id": uuid.uuid4().hex[:12], "index": 0, "answers": {},
            "questions": questions, "module_id": module_id,
        }
        _TEST_SESSIONS[user_id] = session
        await callback.answer()
        await _render_test_question(callback.message, session)
        return

    await callback.answer()
    if callback.data == "histology_test_topics":
        rows = [(m["title"], f"histology_test_topic:{m['id']}") for m in histology_exam.test_topics()]
        await tb.safe_edit_text(callback.message, "Выбери тему теста", reply_markup=_menu(rows, "histology_tests"))
    else:
        _TEST_SESSIONS.pop(user_id, None)
        size = histology_exam.test_bank()["exam_rules"]["questions_per_attempt"]
        rows = [(f"Случайный тест · {size} вопросов", "histology_test_start"), ("Тесты по темам", "histology_test_topics")]
        await tb.safe_edit_text(callback.message, "Тесты по гистологии", reply_markup=_menu(rows, "histology_exam"))


@router.callback_query(F.data.regexp(r"^histology_test_(?:pick|next|prev):[a-f0-9]{12}:\d{1,2}(?::[1-4])?$"))
async def cb_histology_test_session(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    action, ident, raw_index, *selected = callback.data.split(":")
    index = int(raw_index)
    user_id = callback.from_user.id
    session = _TEST_SESSIONS.get(user_id)
    if session is None or session["id"] != ident or session["index"] != index:
        await callback.answer("Эта кнопка больше не активна")
        return
    answers = session["answers"]
    questions = session["questions"]
    if action == "histology_test_pick" and selected and index not in answers:
        answers[index] = int(selected[0])
    elif action == "histology_test_prev" and index > 0 and not selected:
        session["index"] -= 1
    elif action == "histology_test_next" and index in answers and not selected:
        if index + 1 == len(questions):
            _TEST_SESSIONS.pop(user_id, None)
            scored = sum(q["correct_option"] is not None for q in questions)
            correct = sum(q["correct_option"] == answers[i] for i, q in enumerate(questions))
            result = f"Верных ответов: {correct} из {scored}"
            restart = "histology_test_start"
            if session["module_id"] is None:
                result += f"\nОценка: {histology_exam.exam_grade(correct)}"
            else:
                restart += f":{session['module_id']}"
                if scored != len(questions):
                    result += f"\nСпорных заданий без балла: {len(questions) - scored}"
            await callback.answer()
            await tb.safe_edit_text(
                callback.message, result, reply_markup=_menu([("Пройти ещё раз", restart)], "histology_tests")
            )
            return
        session["index"] += 1
    else:
        await callback.answer("Эта кнопка больше не активна")
        return
    await callback.answer()
    await _render_test_question(callback.message, session)


@router.callback_query(F.data.regexp(r"^histology_test_topic:[a-z0-9-]+$"))
async def cb_histology_test_topic(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    module_id = callback.data.partition(":")[2]
    topic = next((m for m in histology_exam.test_topics() if m["id"] == module_id), None)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    rows = [(f"Начать тест · вопросов: {topic['question_count']}", f"histology_test_start:{module_id}")]
    await tb.safe_edit_text(callback.message, escape(topic["title"]), reply_markup=_menu(rows, "histology_test_topics"))


@router.callback_query(F.data.regexp(r"^histology_test_review:\d{1,3}$"))
async def cb_histology_test_review(callback: CallbackQuery):
    if not await histology_gate_ok(callback):
        return
    number = int(callback.data.partition(":")[2])
    q = histology_exam.test_questions().get(f"histology-2019-{number:03d}")
    if q is None:
        await callback.answer("Задание не найдено", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, f"{_test_text(q)}\n\n{_test_explanation(q)}", parse_mode="HTML",
        reply_markup=_menu([], f"histology_test_topic:{q['module_id']}"),
    )
