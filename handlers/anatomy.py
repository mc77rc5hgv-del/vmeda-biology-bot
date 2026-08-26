"""Раздел «Анатомия» — Router вместо прямой регистрации на глобальном dp (Phase 3 рефакторинга,
см. CLAUDE.md — та же схема, что уже применена к Гистологии в handlers/histology.py). Импортирует
telegram_bot как tb вместо `from telegram_bot import ...`, потому что сам telegram_bot.py
импортирует этот модуль (см. блок "АНАТОМИЯ" там) — циклическая связь разрешается тем, что этот
импорт стоит в самом конце telegram_bot.py, когда все нужные отсюда имена (stats, save_stats,
safe_edit_text, ACTIVE_SUBSCRIPTION_TIERS, RANK_MEDALS, donor_display_name,
is_admin_or_assistant, has_subscription_anatomy_access, cheapest_anatomy_tier, STATS_DIR,
CAPTION_LIMIT, _stats_executor, _log_stats_write_result, ANATOMY, ANATOMY_IMAGES_DIR,
ANATOMY_EXAM_TEST_PARTS, ANATOMY_EXAM_THEORY_SECTIONS, ANATOMY_EXAM_PRACTICE_SECTIONS) уже
определены в его модульном пространстве имён — обращения к ним разрешаются во время вызова
хендлера или при импорте этого модуля (модульные константы вроде ANATOMY_FILE_ID_CACHE_PATH),
никогда раньше."""
import json
import os
import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

# ==================== АНАТОМИЯ (В РАЗРАБОТКЕ, ПОКА ДОСТУПНО ТОЛЬКО АДМИНАМ) ====================
ANATOMY_PUBLIC = False  # когда раздел будет готов для всех — переключить на True
ANATOMY_MAINTENANCE_MODE = True  # захардкоженное значение ПО УМОЛЧАНИЮ (используется, пока админ ни разу
# не трогал тумблер в панели) — временное техническое закрытие всего раздела для всех, кроме админов.
# Гейтится в одном месте (cb_anatomy_root), т.к. это единственная точка входа в раздел —
# anatomy_menu/anatomy_exam_menu и всё вложенное (темы, кости, ТЕСТ) достижимы только через него,
# отдельных deep-link'ов в контент нет.

def anatomy_maintenance_mode_enabled() -> bool:
    """Фактическое состояние тех.режима: stats["anatomy_maintenance_override"] (None/True/False) —
    если админ хоть раз переключил тумблер в панели ("🛠 Админ-панель" -> тумблер техрежима
    Анатомии), значение живёт здесь и переживает редеплой без изменения кода; пока override не
    установлен (None — свежая база или ещё не трогали), используется захардкоженный
    ANATOMY_MAINTENANCE_MODE выше как значение по умолчанию."""
    override = tb.stats.get("anatomy_maintenance_override")
    return ANATOMY_MAINTENANCE_MODE if override is None else override

ANATOMY_FLASH_SESSION_SIZE = 10
ANATOMY_MATCH_SESSION_SIZE = 10
ANATOMY_LATIN_SESSION_SIZE = 15
ANATOMY_LATIN_ALL_SESSION_SIZE = 50
ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT = 3800  # запас от лимита Telegram в 4096 символов на сообщение

ANATOMY_FLASH_SESSIONS: dict[int, dict] = {}
ANATOMY_MATCH_SESSIONS: dict[int, dict] = {}
ANATOMY_LATIN_SESSIONS: dict[int, dict] = {}

def anatomy_access_ok(user_id: int) -> bool:
    # Раздел ещё в разработке — глобальное промо ("снять все ограничения") намеренно
    # его не открывает, в отличие от остальных предметов; только явный ANATOMY_PUBLIC,
    # админ/помощник админа, подписка с anatomy=True, либо ручной демо-доступ по username.
    return (
        ANATOMY_PUBLIC
        or tb.is_admin_or_assistant(user_id)
        or tb.has_subscription_anatomy_access(user_id)
        or user_id in tb.stats["manual_anatomy_demo_granted"]
    )

# Free-funnel split: одна половина модулей открыта всем без каких-либо условий (даже без
# рефералов), чтобы привлечь как можно больше пользователей и показать им возможности бота;
# вторая половина остаётся платной — на неё покупают подписку уже вовлечённые пользователи.
# Free-модули выбраны так, чтобы покрыть базовую системную анатомию (скелет, мышцы, органы,
# железы), а платные — самые объёмные/клинически нагруженные разделы (нервная и
# сердечно-сосудистая системы) + бонусный клинический модуль.
ANATOMY_FREE_SECTIONS = {
    "module1_osteology",
    "module2_syndesmology",
    "module3_myology",
    "module4_digestive",
    "module5_respiratory",
    "module6_urogenital",
    "module9_endocrine",
}

def anatomy_section_access_ok(user_id: int, section_key: str) -> bool:
    if section_key in ANATOMY_FREE_SECTIONS:
        return True
    return anatomy_access_ok(user_id)

def get_anatomy_dev_alert_text() -> str:
    # Telegram ограничивает текст всплывающего алерта ~200 символами — показываем только
    # самый дешёвый подходящий тариф, полный список смотрят в «💎 Подписка».
    cheapest = tb.cheapest_anatomy_tier()
    return (
        f"🔒 Этот раздел Анатомии — по подписке от «{cheapest['short']}» "
        f"({cheapest['price_rub']}₽/{cheapest['price_stars']}⭐) — полный список в «💎 Подписка» 💎"
    )

def get_anatomy_topic_data(topic_key: str):
    for section in tb.ANATOMY.values():
        topic = section.get("topics", {}).get(topic_key)
        if topic:
            return topic
    return None

def get_topic_section_key(topic_key: str) -> str:
    for section_key, section in tb.ANATOMY.items():
        if topic_key in section.get("topics", {}):
            return section_key
    return next(iter(tb.ANATOMY), "osteology")

def get_anatomy_locked_text(section_key: str | None = None) -> str:
    tier_lines = " или ".join(
        f"«{cfg['emoji']} {cfg['title']}» ({cfg['price_rub']}₽ / {cfg['price_stars']}⭐)"
        for cfg in tb.ACTIVE_SUBSCRIPTION_TIERS.values() if cfg.get("anatomy")
    )
    section = tb.ANATOMY.get(section_key) if section_key else None
    title = section["title"] if section else "Анатомия"
    free_titles = ", ".join(tb.ANATOMY[k]["title"] for k in tb.ANATOMY if k in ANATOMY_FREE_SECTIONS)
    return (
        f"🦴 <b>{title}</b>\n{tb.DIVIDER}\n\n"
        "🔒 Этот раздел анатомии доступен по подписке.\n\n"
        f"Оформи подписку {tier_lines}, чтобы открыть его.\n\n"
        f"А бесплатно уже сейчас доступны: {free_titles} — загляни в меню «🦴 Анатомия»."
    )

def get_anatomy_locked_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Оформить подписку", callback_data="subscription_menu")
    builder.button(text="🔙 В меню Анатомии", callback_data="anatomy_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_anatomy_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    for section_key, section in tb.ANATOMY.items():
        label = section.get("menu_title", section["title"])
        if not anatomy_section_access_ok(user_id, section_key):
            label = f"🔒 {label}"
        builder.button(text=label, callback_data=f"anatomy_section:{section_key}")
    if get_all_latin_terms():
        builder.button(text="🏛 Тест по латинским терминам", callback_data="anatomy_latin_all_start")
        builder.button(text="🏆 Рейтинг по латыни", callback_data="anatomy_latin_leaderboard")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню Анатомии", callback_data="anatomy_root"))
    return builder.as_markup()

def get_anatomy_section_keyboard(section_key: str):
    section = tb.ANATOMY.get(section_key, {})
    builder = InlineKeyboardBuilder()
    for topic_key, topic in section.get("topics", {}).items():
        builder.button(text=topic.get("menu_title", topic["title"]), callback_data=f"anatomy_topic:{topic_key}")
    if section.get("video"):
        builder.button(text="🎥 Видео", callback_data=f"anatomy_section_video:{section_key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="anatomy_menu"))
    return builder.as_markup()

def get_anatomy_topic_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    if topic and topic.get("bones_list"):
        builder.button(text="🦴 Разбор по каждой кости", callback_data=f"anatomy_bones:{topic_key}")
    builder.button(text="📖 Весь материал подряд", callback_data=f"anatomy_material:{topic_key}:0")
    builder.button(text="🎴 Флэш-карточки (все)", callback_data=f"anatomy_flash_start:{topic_key}")
    builder.button(text="🔗 Сопоставление (все)", callback_data=f"anatomy_match_start:{topic_key}")
    builder.button(text="🧠 Мнемоники (все)", callback_data=f"anatomy_mnemonics:{topic_key}:0")
    if topic and topic.get("latin_terms"):
        builder.button(text="🏛 Тренажёр латинских терминов", callback_data=f"anatomy_latin_start:{topic_key}")
    builder.button(text="🖼 Найди на картинке", callback_data=f"anatomy_picture:{topic_key}")
    if topic and topic.get("atlas_images"):
        builder.button(text="🖼 Атлас (Неттер/Гайворонский)", callback_data=f"anatomy_atlas:{topic_key}:0")
    if topic and topic.get("video"):
        builder.button(text="🎥 Видео", callback_data=f"anatomy_topic_video:{topic_key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_section:{get_topic_section_key(topic_key)}"))
    return builder.as_markup()

# ---- Кости черепа (подразделы по каждой кости) ----
def get_anatomy_bones_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    for bone in topic.get("bones_list", []):
        builder.button(text=f"🦴 {bone['title']}", callback_data=f"anatomy_bone_hub:{topic_key}:{bone['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_bone_title(topic_key: str, bone_id: str) -> str:
    topic = get_anatomy_topic_data(topic_key)
    for bone in topic.get("bones_list", []):
        if bone["id"] == bone_id:
            return bone["title"]
    return bone_id

def get_bone_material_list(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    material_ids = topic.get("bone_material_ids", {}).get(bone_id, [bone_id])
    by_id = {m["id"]: m for m in topic["material"]}
    return [by_id[mid] for mid in material_ids if mid in by_id]

def get_bone_flashcards(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return [fc for fc in topic["flashcards"] if fc.get("bone") == bone_id]

def get_bone_pairs(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    pairs = []
    for s in topic["matching_sets"]:
        pairs.extend(p for p in s["pairs"] if p.get("bone") == bone_id)
    return pairs

def get_bone_mnemonics(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return [mn for mn in topic["mnemonics"] if mn.get("bone") == bone_id]

def get_bone_latin_terms(topic_key: str, bone_id: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return [t for t in topic.get("latin_terms", []) if t.get("bone") == bone_id]

ANATOMY_ATLAS_CREDITS = {"Ф. Неттер, Атлас анатомии человека", "И.В. Гайворонский, Нормальная анатомия человека"}
ANATOMY_ALBUM_PAGE_SIZE = 10  # sendMediaGroup hard cap

def anatomy_page_count(n_images: int) -> int:
    return max(1, (n_images + ANATOMY_ALBUM_PAGE_SIZE - 1) // ANATOMY_ALBUM_PAGE_SIZE)

def get_bone_images(topic_key: str, bone_id: str, kind: str | None = None) -> list:
    """kind=None -> all; 'slides' -> ВМедА lecture-presentation photos; 'atlas' -> Неттер/Гайворонский."""
    topic = get_anatomy_topic_data(topic_key)
    images = topic.get("bone_images", {}).get(bone_id, [])
    if kind == "atlas":
        return [i for i in images if i.get("credit") in ANATOMY_ATLAS_CREDITS]
    if kind == "slides":
        return [i for i in images if i.get("credit") not in ANATOMY_ATLAS_CREDITS]
    return images

def get_anatomy_bone_hub_keyboard(topic_key: str, bone_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Материал", callback_data=f"anatomy_bone_material:{topic_key}:{bone_id}:0")
    if get_bone_images(topic_key, bone_id, kind="slides"):
        builder.button(text="📽 Слайды (презентация)", callback_data=f"anatomy_bone_slides:{topic_key}:{bone_id}:0")
    if get_bone_images(topic_key, bone_id, kind="atlas"):
        builder.button(text="🖼 Атлас (Неттер/Гайворонский)", callback_data=f"anatomy_bone_atlas:{topic_key}:{bone_id}:0")
    builder.button(text="🎴 Флэш-карточки", callback_data=f"anatomy_bone_flash_start:{topic_key}:{bone_id}")
    builder.button(text="🔗 Сопоставление", callback_data=f"anatomy_bone_match_start:{topic_key}:{bone_id}")
    builder.button(text="🧠 Мнемоники", callback_data=f"anatomy_bone_mnemonics:{topic_key}:{bone_id}:0")
    if get_bone_latin_terms(topic_key, bone_id):
        builder.button(text="🏛 Латинские термины", callback_data=f"anatomy_bone_latin_start:{topic_key}:{bone_id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К списку костей", callback_data=f"anatomy_bones:{topic_key}"))
    return builder.as_markup()

def get_anatomy_bone_hub_text(topic_key: str, bone_id: str) -> str:
    title = get_bone_title(topic_key, bone_id)
    n_material = len(get_bone_material_list(topic_key, bone_id))
    n_slides = len(get_bone_images(topic_key, bone_id, kind="slides"))
    n_atlas = len(get_bone_images(topic_key, bone_id, kind="atlas"))
    n_flash = len(get_bone_flashcards(topic_key, bone_id))
    n_pairs = len(get_bone_pairs(topic_key, bone_id))
    n_mnemo = len(get_bone_mnemonics(topic_key, bone_id))
    n_latin = len(get_bone_latin_terms(topic_key, bone_id))
    return (
        f"🦴 <b>{title}</b>\n{tb.DIVIDER}\n\n"
        f"📖 Материал: {n_material} стр.\n"
        f"📽 Слайдов презентации: {n_slides}\n"
        f"🖼 Атлас (Неттер/Гайворонский): {n_atlas}\n"
        f"🎴 Флэш-карточек: {n_flash}\n"
        f"🔗 Пар для сопоставления: {n_pairs}\n"
        f"🧠 Мнемоник: {n_mnemo}\n"
        f"🏛 Латинских терминов: {n_latin}\n\n"
        "Выбери формат подготовки:"
    )

# ---- Кэш Telegram file_id для фото анатомии: без него каждый повторный показ той же
# фотографии заново читает файл с диска и заливает его в Telegram — с кэшем повторные показы
# используют уже загруженный file_id и приходят почти мгновенно.
ANATOMY_FILE_ID_CACHE_PATH = os.path.join(tb.STATS_DIR, "anatomy_file_id_cache.json")

def _load_anatomy_file_id_cache() -> dict:
    try:
        with open(ANATOMY_FILE_ID_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

ANATOMY_FILE_ID_CACHE: dict[str, str] = _load_anatomy_file_id_cache()

def _write_anatomy_file_id_cache(data: dict) -> None:
    tmp_path = f"{ANATOMY_FILE_ID_CACHE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, ANATOMY_FILE_ID_CACHE_PATH)

def save_anatomy_file_id_cache() -> None:
    data = dict(ANATOMY_FILE_ID_CACHE)
    future = tb._stats_executor.submit(_write_anatomy_file_id_cache, data)
    future.add_done_callback(tb._log_stats_write_result)

def _anatomy_image_key(img: dict) -> str:
    return img["url"] if "url" in img else img["path"]

def _anatomy_image_media(img: dict):
    cached = ANATOMY_FILE_ID_CACHE.get(_anatomy_image_key(img))
    if cached:
        return cached
    return img["url"] if "url" in img else FSInputFile(os.path.join(tb.ANATOMY_IMAGES_DIR, img["path"]))

def _cache_anatomy_file_id(img: dict, sent_message) -> bool:
    """Remembers the file_id Telegram assigned on first upload so later sends of the same
    image reuse it instead of re-reading the file from disk. Safe no-op if sent_message
    doesn't carry a real Telegram photo (e.g. test mocks)."""
    key = _anatomy_image_key(img)
    if key in ANATOMY_FILE_ID_CACHE:
        return False
    photo_sizes = getattr(sent_message, "photo", None)
    if not photo_sizes:
        return False
    ANATOMY_FILE_ID_CACHE[key] = photo_sizes[-1].file_id
    return True

def build_input_media_photo(img: dict) -> InputMediaPhoto:
    return InputMediaPhoto(media=_anatomy_image_media(img), caption=f"{img['caption']}\n\nИсточник: {img['credit']}", parse_mode="HTML")

async def send_anatomy_album(callback: CallbackQuery, images: list, page: int, header: str, nav_prefix: str, back_callback: str):
    """Sends up to ANATOMY_ALBUM_PAGE_SIZE photos as one native Telegram album — swipeable
    in-place by the user with no further bot round-trips, unlike the old delete-and-resend
    single-photo carousel. sendMediaGroup itself can't carry a reply_markup, so a separate
    small text message follows with prev/next-page and back buttons."""
    total_pages = anatomy_page_count(len(images))
    start = page * ANATOMY_ALBUM_PAGE_SIZE
    chunk = images[start:start + ANATOMY_ALBUM_PAGE_SIZE]
    await callback.message.delete()
    cache_changed = False
    if len(chunk) == 1:
        # Telegram's sendMediaGroup requires 2-10 items — a lone photo must go through
        # answer_photo instead, or the real API call fails outright.
        img = chunk[0]
        sent = await callback.message.answer_photo(
            _anatomy_image_media(img), caption=f"{img['caption']}\n\nИсточник: {img['credit']}", parse_mode="HTML"
        )
        cache_changed = _cache_anatomy_file_id(img, sent)
    else:
        media = [build_input_media_photo(img) for img in chunk]
        sent_list = await callback.message.answer_media_group(media=media)
        for img, sent in zip(chunk, sent_list or []):
            if _cache_anatomy_file_id(img, sent):
                cache_changed = True
    if cache_changed:
        save_anatomy_file_id_cache()
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Ещё фото", callback_data=f"{nav_prefix}:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Ещё фото ➡️", callback_data=f"{nav_prefix}:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback))
    page_info = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
    await callback.message.answer(f"{header}{page_info}", parse_mode="HTML", reply_markup=builder.as_markup())

# ---- Атлас темы (для тем без разбора по костям — артрология/миология/спланхнология/...) ----
def get_topic_atlas_images(topic_key: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return topic.get("atlas_images", []) if topic else []

# ---- Тренажёр латинских терминов (тест с вариантами: термин -> перевод) ----
def get_topic_latin_terms(topic_key: str) -> list:
    topic = get_anatomy_topic_data(topic_key)
    return topic.get("latin_terms", []) if topic else []

def get_all_latin_terms() -> list:
    """Pools latin_terms across every section/topic in ANATOMY — not a hand-picked
    list, so any future section that adds latin_terms is automatically included."""
    terms = []
    for section in tb.ANATOMY.values():
        for topic in section.get("topics", {}).values():
            terms.extend(topic.get("latin_terms", []))
    return terms

def start_anatomy_latin_session(user_id: int, topic_key: str = None, bone_id: str = None, is_global: bool = False):
    if is_global:
        all_terms = get_all_latin_terms()
        size = min(ANATOMY_LATIN_ALL_SESSION_SIZE, len(all_terms))
        queue_terms = all_terms
    else:
        all_terms = get_topic_latin_terms(topic_key)
        queue_terms = get_bone_latin_terms(topic_key, bone_id) if bone_id else all_terms
        size = min(ANATOMY_LATIN_SESSION_SIZE, len(queue_terms))
    ANATOMY_LATIN_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "bone_id": bone_id,
        "is_global": is_global,
        "all_terms": all_terms,
        "queue": random.sample(queue_terms, size),
        "index": 0,
        "correct": 0,
        "wrong": 0,
        "current_correct_idx": None,
        "current_options": None,
    }

def get_anatomy_latin_keyboard(options: list):
    builder = InlineKeyboardBuilder()
    for i in range(len(options)):
        builder.button(text=str(i + 1), callback_data=f"anatomy_latin_answer:{i}")
    builder.adjust(len(options))
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_latin_stop"))
    return builder.as_markup()

def pick_anatomy_latin_distractors(term: dict, pool: list, count: int = 3) -> list:
    """Prefers distractors from the same bone as the correct term — anatomically
    related structures (e.g. two foramina of the same bone) read as more plausible
    wrong answers than an unrelated term from a completely different bone, making
    the choice harder than picking from the whole pool at random."""
    correct_ru = term["ru"]
    same_bone = [t["ru"] for t in pool if t["ru"] != correct_ru and t.get("bone") and t.get("bone") == term.get("bone")]
    random.shuffle(same_bone)
    distractors = same_bone[:count]
    if len(distractors) < count:
        rest_pool = [t["ru"] for t in pool if t["ru"] != correct_ru and t["ru"] not in distractors]
        distractors += random.sample(rest_pool, min(count - len(distractors), len(rest_pool)))
    return distractors

async def render_anatomy_latin_question(message, user_id: int):
    session = ANATOMY_LATIN_SESSIONS[user_id]
    term = session["queue"][session["index"]]
    correct_ru = term["ru"]
    distractors = pick_anatomy_latin_distractors(term, session["all_terms"])
    options = distractors + [correct_ru]
    random.shuffle(options)
    session["current_correct_idx"] = options.index(correct_ru)
    session["current_options"] = options
    header = "Латинские термины — весь курс анатомии" if session.get("is_global") else "Латинские термины"
    lines = [
        f"🏛 <b>{header} — {session['index'] + 1}/{len(session['queue'])}</b>\n{tb.DIVIDER}\n",
        f"<i>{term['la']}</i>\n",
        "Выбери правильный перевод:",
        "",
    ]
    for i, opt in enumerate(options):
        lines.append(f"{i + 1}. {opt}")
    await tb.safe_edit_text(message, "\n".join(lines), parse_mode="HTML", reply_markup=get_anatomy_latin_keyboard(options))

def record_anatomy_latin_score(user_id: int, correct: int, total: int) -> bool:
    """Updates the user's personal-best result for the global latin test if this run
    is better (higher percent, or same percent on a larger sample). Returns True if
    this run became the new personal best."""
    if total <= 0:
        return False
    uid_str = str(user_id)
    scores = tb.stats.setdefault("anatomy_latin_scores", {})
    prev = scores.get(uid_str)
    percent = correct / total
    is_new_best = True
    if prev:
        prev_percent = prev["best_correct"] / prev["best_total"] if prev["best_total"] else 0
        is_new_best = percent > prev_percent or (percent == prev_percent and total > prev["best_total"])
    entry = scores.setdefault(uid_str, {"best_correct": correct, "best_total": total, "attempts": 0})
    entry["attempts"] = entry.get("attempts", 0) + 1
    if is_new_best:
        entry["best_correct"] = correct
        entry["best_total"] = total
    tb.save_stats()
    return is_new_best

def get_anatomy_latin_leaderboard_text(user_id: int = None) -> str:
    """Full ranking, not just a fixed top-N — includes every scored user, only
    truncating (with a "показаны первые N" note) if the list gets long enough to
    risk Telegram's 4096-char message cap."""
    scores = tb.stats.get("anatomy_latin_scores", {})
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1]["best_correct"] / kv[1]["best_total"] if kv[1]["best_total"] else 0, kv[1]["best_correct"]),
        reverse=True,
    )
    header = f"🏆 <b>Рейтинг по латинским терминам</b>\n{tb.DIVIDER}"
    if not ranked:
        return header + "\n\nПока никто не проходил тест — стань первым! 🏛"
    lines = [header, ""]
    shown_uids = []
    for i, (uid_str, entry) in enumerate(ranked):
        icon = tb.RANK_MEDALS[i] if i < 3 else f"{i + 1}."
        percent = round(100 * entry["best_correct"] / entry["best_total"]) if entry["best_total"] else 0
        row = f"{icon} {tb.donor_display_name(uid_str)} — <b>{entry['best_correct']}/{entry['best_total']}</b> ({percent}%)"
        if len("\n".join([*lines, row])) > ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT:
            break
        lines.append(row)
        shown_uids.append(uid_str)
    if len(shown_uids) < len(ranked):
        lines.append(f"\n… показаны первые {len(shown_uids)} из {len(ranked)}")
    if user_id is not None:
        uid_str = str(user_id)
        if uid_str not in shown_uids and uid_str in scores:
            rank = next(i for i, (u, _) in enumerate(ranked) if u == uid_str) + 1
            entry = scores[uid_str]
            percent = round(100 * entry["best_correct"] / entry["best_total"]) if entry["best_total"] else 0
            lines.append(f"\nТвоё место: <b>#{rank}</b> — {entry['best_correct']}/{entry['best_total']} ({percent}%)")
    return "\n".join(lines)

def get_anatomy_latin_leaderboard_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏛 Пройти тест", callback_data="anatomy_latin_all_start")
    builder.button(text="🔄 Обновить", callback_data="anatomy_latin_leaderboard")
    builder.button(text="🔙 В меню Анатомии", callback_data="anatomy_menu")
    builder.adjust(1)
    return builder.as_markup()

async def render_anatomy_latin_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_LATIN_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    bone_id = session.get("bone_id")
    is_global = session.get("is_global")
    answered = session["correct"] + session["wrong"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Тренажёр пройден!</b>"
    text = (
        f"{title}\n{tb.DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Верно: <b>{session['correct']}</b>\n❌ Неверно: <b>{session['wrong']}</b>"
    )
    builder = InlineKeyboardBuilder()
    if is_global:
        if not aborted and record_anatomy_latin_score(user_id, session["correct"], answered):
            text += "\n\n🎉 Новый личный рекорд!"
        builder.button(text="🔁 Пройти ещё раз", callback_data="anatomy_latin_all_start")
        builder.button(text="🏆 Рейтинг", callback_data="anatomy_latin_leaderboard")
        builder.button(text="🔙 В меню Анатомии", callback_data="anatomy_menu")
    elif bone_id:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_bone_latin_start:{topic_key}:{bone_id}")
        builder.button(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}")
    else:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_latin_start:{topic_key}")
        builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=builder.as_markup())

def get_bone_material_keyboard(topic_key: str, bone_id: str, idx: int):
    pages = get_bone_material_list(topic_key, bone_id)
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_bone_material:{topic_key}:{bone_id}:{idx-1}"))
    if idx < len(pages) - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_bone_material:{topic_key}:{bone_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}"))
    return builder.as_markup()

def get_bone_material_text(topic_key: str, bone_id: str, idx: int) -> str:
    pages = get_bone_material_list(topic_key, bone_id)
    m = pages[idx]
    return f"📖 <b>{m['title']}</b>\n{tb.DIVIDER}\n\n{m['content']}\n\n{tb.DIVIDER}\n{idx + 1}/{len(pages)}"

# ---- Материал ----
def get_anatomy_material_keyboard(topic_key: str, idx: int):
    topic = get_anatomy_topic_data(topic_key)
    material = topic["material"]
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_material:{topic_key}:{idx-1}"))
    if idx < len(material) - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_material:{topic_key}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="📋 Список тем", callback_data=f"anatomy_material_list:{topic_key}"))
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_anatomy_material_text(topic_key: str, idx: int) -> str:
    topic = get_anatomy_topic_data(topic_key)
    material = topic["material"]
    m = material[idx]
    return f"📖 <b>{m['title']}</b>\n{tb.DIVIDER}\n\n{m['content']}\n\n{tb.DIVIDER}\n{idx + 1}/{len(material)}"

def get_anatomy_material_list_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    for i, m in enumerate(topic["material"]):
        builder.button(text=f"{i + 1}. {m['title']}", callback_data=f"anatomy_material:{topic_key}:{i}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

# ---- Флэш-карточки ----
def start_anatomy_flash_session(user_id: int, topic_key: str, bone_id: str = None):
    topic = get_anatomy_topic_data(topic_key)
    if bone_id:
        pool = [i for i, fc in enumerate(topic["flashcards"]) if fc.get("bone") == bone_id]
    else:
        pool = list(range(len(topic["flashcards"])))
    size = min(ANATOMY_FLASH_SESSION_SIZE, len(pool))
    ANATOMY_FLASH_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "bone_id": bone_id,
        "cards": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }

def get_anatomy_flash_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="anatomy_flash_show_answer")
    builder.button(text="🛑 Закончить", callback_data="anatomy_flash_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_anatomy_flash_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Знаю", callback_data="anatomy_flash_know")
    builder.button(text="❌ Не знаю", callback_data="anatomy_flash_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_flash_stop"))
    return builder.as_markup()

def get_anatomy_flash_summary_keyboard(topic_key: str, bone_id: str = None):
    builder = InlineKeyboardBuilder()
    if bone_id:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_bone_flash_start:{topic_key}:{bone_id}")
        builder.button(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}")
    else:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_flash_start:{topic_key}")
        builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    return builder.as_markup()

async def render_anatomy_flash_question(message, user_id: int):
    session = ANATOMY_FLASH_SESSIONS[user_id]
    topic = get_anatomy_topic_data(session["topic_key"])
    total = len(session["cards"])
    card = topic["flashcards"][session["cards"][session["index"]]]
    text = f"🎴 <b>Флэш-карточки — {session['index'] + 1}/{total}</b>\n{tb.DIVIDER}\n\n{card['front']}"
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_question_keyboard())

async def render_anatomy_flash_answer(message, user_id: int):
    session = ANATOMY_FLASH_SESSIONS[user_id]
    topic = get_anatomy_topic_data(session["topic_key"])
    total = len(session["cards"])
    card = topic["flashcards"][session["cards"][session["index"]]]
    text = (
        f"🎴 <b>Флэш-карточки — {session['index'] + 1}/{total}</b>\n{tb.DIVIDER}\n\n"
        f"❓ {card['front']}\n\n💡 {card['back']}\n\n{tb.DIVIDER}\nТы знал(а) ответ?"
    )
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_answer_keyboard())

async def render_anatomy_flash_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_FLASH_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    bone_id = session.get("bone_id")
    answered = session["know"] + session["dont_know"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Карточки пройдены!</b>"
    text = (
        f"{title}\n{tb.DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Знаю: <b>{session['know']}</b>\n❌ Не знаю: <b>{session['dont_know']}</b>"
    )
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_summary_keyboard(topic_key, bone_id))

# ---- Сопоставление (матчинг как тест с вариантами) ----
def get_anatomy_all_pairs(topic_key: str, bone_id: str = None):
    topic = get_anatomy_topic_data(topic_key)
    pairs = []
    for s in topic["matching_sets"]:
        pairs.extend(s["pairs"])
    if bone_id:
        pairs = [p for p in pairs if p.get("bone") == bone_id]
    return pairs

def start_anatomy_match_session(user_id: int, topic_key: str, bone_id: str = None):
    all_pairs = get_anatomy_all_pairs(topic_key)
    queue_pairs = get_anatomy_all_pairs(topic_key, bone_id) if bone_id else all_pairs
    size = min(ANATOMY_MATCH_SESSION_SIZE, len(queue_pairs))
    ANATOMY_MATCH_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "bone_id": bone_id,
        "all_pairs": all_pairs,
        "queue": random.sample(queue_pairs, size),
        "index": 0,
        "correct": 0,
        "wrong": 0,
        "current_correct_idx": None,
        "current_options": None,
    }

def get_anatomy_match_keyboard(options: list):
    builder = InlineKeyboardBuilder()
    for i in range(len(options)):
        builder.button(text=str(i + 1), callback_data=f"anatomy_match_answer:{i}")
    builder.adjust(len(options))
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_match_stop"))
    return builder.as_markup()

async def render_anatomy_match_question(message, user_id: int):
    session = ANATOMY_MATCH_SESSIONS[user_id]
    pair = session["queue"][session["index"]]
    term, correct_def = pair["term"], pair["definition"]
    distractor_pool = [p["definition"] for p in session["all_pairs"] if p["definition"] != correct_def]
    distractors = random.sample(distractor_pool, min(3, len(distractor_pool)))
    options = distractors + [correct_def]
    random.shuffle(options)
    session["current_correct_idx"] = options.index(correct_def)
    session["current_options"] = options
    lines = [
        f"🔗 <b>Сопоставление — {session['index'] + 1}/{len(session['queue'])}</b>\n{tb.DIVIDER}\n",
        f"<b>{term}</b>\n",
        "Выбери правильное соответствие:",
        "",
    ]
    for i, opt in enumerate(options):
        lines.append(f"{i + 1}. {opt}")
    await tb.safe_edit_text(message, "\n".join(lines), parse_mode="HTML", reply_markup=get_anatomy_match_keyboard(options))

async def render_anatomy_match_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_MATCH_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    bone_id = session.get("bone_id")
    answered = session["correct"] + session["wrong"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Сопоставление завершено!</b>"
    text = (
        f"{title}\n{tb.DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Верно: <b>{session['correct']}</b>\n❌ Неверно: <b>{session['wrong']}</b>"
    )
    builder = InlineKeyboardBuilder()
    if bone_id:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_bone_match_start:{topic_key}:{bone_id}")
        builder.button(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}")
    else:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_match_start:{topic_key}")
        builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=builder.as_markup())

# ---- Мнемоники ----
def get_anatomy_mnemonics_keyboard(topic_key: str, idx: int):
    topic = get_anatomy_topic_data(topic_key)
    mnemonics = topic["mnemonics"]
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"anatomy_mnemonics:{topic_key}:{idx-1}"))
    if idx < len(mnemonics) - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"anatomy_mnemonics:{topic_key}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_anatomy_mnemonic_text(topic_key: str, idx: int) -> str:
    topic = get_anatomy_topic_data(topic_key)
    mnemonics = topic["mnemonics"]
    mn = mnemonics[idx]
    return f"🧠 <b>{mn['title']}</b>\n{tb.DIVIDER}\n\n{mn['text']}\n\n{tb.DIVIDER}\n{idx + 1}/{len(mnemonics)}"

def get_bone_mnemonics_keyboard(topic_key: str, bone_id: str, idx: int):
    mnemonics = get_bone_mnemonics(topic_key, bone_id)
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"anatomy_bone_mnemonics:{topic_key}:{bone_id}:{idx-1}"))
    if idx < len(mnemonics) - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"anatomy_bone_mnemonics:{topic_key}:{bone_id}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К кости", callback_data=f"anatomy_bone_hub:{topic_key}:{bone_id}"))
    return builder.as_markup()

def get_bone_mnemonic_text(topic_key: str, bone_id: str, idx: int) -> str:
    mnemonics = get_bone_mnemonics(topic_key, bone_id)
    mn = mnemonics[idx]
    return f"🧠 <b>{mn['title']}</b>\n{tb.DIVIDER}\n\n{mn['text']}\n\n{tb.DIVIDER}\n{idx + 1}/{len(mnemonics)}"

# ---- Хендлеры ----
def get_anatomy_root_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Весь курс анатомии", callback_data="anatomy_menu")
    builder.button(text="🎓 Экзамен", callback_data="anatomy_exam_menu")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_anatomy_maintenance_text() -> str:
    return (
        f"🦴 <b>Анатомия</b>\n{tb.DIVIDER}\n\n"
        "Раздел временно недоступен по техническим причинам. Мы уже работаем над этим — "
        "загляни немного позже."
    )

def get_anatomy_maintenance_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

@router.callback_query(F.data == "anatomy_root")
async def cb_anatomy_root(callback: CallbackQuery):
    await callback.answer()
    if anatomy_maintenance_mode_enabled() and not tb.is_admin_or_assistant(callback.from_user.id):
        await tb.safe_edit_text(
            callback.message,
            get_anatomy_maintenance_text(),
            parse_mode="HTML",
            reply_markup=get_anatomy_maintenance_keyboard()
        )
        return
    await tb.safe_edit_text(
        callback.message,
        f"🦴 <b>Анатомия</b>\n{tb.DIVIDER}\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_anatomy_root_keyboard()
    )

@router.callback_query(F.data == "anatomy_menu")
async def cb_anatomy_menu(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📚 <b>Весь курс анатомии</b>\n{tb.DIVIDER}\n\n"
        "Часть разделов открыта бесплатно для всех, часть — по подписке (отмечены 🔒).\n\n"
        "Выбери подраздел:",
        parse_mode="HTML",
        reply_markup=get_anatomy_menu_keyboard(callback.from_user.id)
    )

def get_anatomy_video_text(entry: dict, title: str) -> str:
    """Экран «🎥 Видео»: ссылка(и) из entry["video"] (строка или список строк) выводится
    обычным текстом, не оборачивается в <a href> — Telegram сам строит превью со встроенным
    плеером YouTube прямо в чате (см. cb_anatomy_section_video/cb_anatomy_topic_video — там же
    не гасится disable_web_page_preview, иначе превью не появится)."""
    video = entry.get("video")
    urls = video if isinstance(video, list) else [video]
    return f"🎥 <b>Видео: {title}</b>\n{tb.DIVIDER}\n\n" + "\n".join(urls)

@router.callback_query(F.data.startswith("anatomy_section:"))
async def cb_anatomy_section(callback: CallbackQuery):
    section_key = callback.data.split(":")[1]
    section = tb.ANATOMY.get(section_key)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    if not anatomy_section_access_ok(callback.from_user.id, section_key):
        await callback.answer()
        await tb.safe_edit_text(
            callback.message,
            get_anatomy_locked_text(section_key),
            parse_mode="HTML",
            reply_markup=get_anatomy_locked_keyboard()
        )
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🦴 <b>{section['title']}</b>\n{tb.DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_anatomy_section_keyboard(section_key)
    )

@router.callback_query(F.data.startswith("anatomy_section_video:"))
async def cb_anatomy_section_video(callback: CallbackQuery):
    section_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, section_key):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    section = tb.ANATOMY.get(section_key)
    if not section or not section.get("video"):
        await callback.answer("Видео не найдено", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_section:{section_key}"))
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_video_text(section, section["title"]),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("anatomy_topic:"))
async def cb_anatomy_topic(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    icon = topic.get("icon", "📚")
    text = (
        f"{icon} <b>{topic['title']}</b>\n{tb.DIVIDER}\n\n"
        f"📖 Материал: {len(topic['material'])} тем\n"
        f"🎴 Флэш-карточек: {len(topic['flashcards'])}\n"
        f"🔗 Пар для сопоставления: {sum(len(s['pairs']) for s in topic['matching_sets'])}\n"
        f"🧠 Мнемоник: {len(topic['mnemonics'])}\n\n"
        "Выбери формат подготовки:"
    )
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_anatomy_topic_keyboard(topic_key))

@router.callback_query(F.data.startswith("anatomy_topic_video:"))
async def cb_anatomy_topic_video(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic.get("video"):
        await callback.answer("Видео не найдено", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_topic:{topic_key}"))
    # видео-ссылка намеренно не оборачивается в <a href>/URL-кнопку и disable_web_page_preview
    # не выставляется — так Telegram сам строит превью со встроенным плеером YouTube прямо в
    # чате, без перехода по ссылке и без скачивания видео ботом.
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_video_text(topic, topic["title"]),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("anatomy_bones:"))
async def cb_anatomy_bones(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🦴 <b>{topic['title']} — по костям</b>\n{tb.DIVIDER}\n\nВыбери кость:",
        parse_mode="HTML",
        reply_markup=get_anatomy_bones_keyboard(topic_key)
    )

@router.callback_query(F.data.startswith("anatomy_bone_hub:"))
async def cb_anatomy_bone_hub(callback: CallbackQuery):
    _, topic_key, bone_id = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_bone_hub_text(topic_key, bone_id),
        parse_mode="HTML",
        reply_markup=get_anatomy_bone_hub_keyboard(topic_key, bone_id)
    )

@router.callback_query(F.data.startswith("anatomy_bone_material:"))
async def cb_anatomy_bone_material(callback: CallbackQuery):
    _, topic_key, bone_id, idx_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    idx = int(idx_s)
    pages = get_bone_material_list(topic_key, bone_id)
    if not pages or not (0 <= idx < len(pages)):
        await callback.answer("Материал не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_bone_material_text(topic_key, bone_id, idx),
        parse_mode="HTML",
        reply_markup=get_bone_material_keyboard(topic_key, bone_id, idx)
    )

@router.callback_query(F.data.startswith("anatomy_bone_slides:"))
async def cb_anatomy_bone_slides(callback: CallbackQuery):
    _, topic_key, bone_id, page_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    page = int(page_s)
    images = get_bone_images(topic_key, bone_id, kind="slides")
    if not images or not (0 <= page < anatomy_page_count(len(images))):
        await callback.answer("Слайдов для этой кости пока нет", show_alert=True)
        return
    await callback.answer()
    title = get_bone_title(topic_key, bone_id)
    await send_anatomy_album(
        callback, images, page,
        header=f"📽 <b>{title} — слайды презентации</b>",
        nav_prefix=f"anatomy_bone_slides:{topic_key}:{bone_id}",
        back_callback=f"anatomy_bone_hub:{topic_key}:{bone_id}",
    )

@router.callback_query(F.data.startswith("anatomy_bone_atlas:"))
async def cb_anatomy_bone_atlas(callback: CallbackQuery):
    _, topic_key, bone_id, page_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    page = int(page_s)
    images = get_bone_images(topic_key, bone_id, kind="atlas")
    if not images or not (0 <= page < anatomy_page_count(len(images))):
        await callback.answer("Атласных иллюстраций для этой кости пока нет", show_alert=True)
        return
    await callback.answer()
    title = get_bone_title(topic_key, bone_id)
    await send_anatomy_album(
        callback, images, page,
        header=f"🖼 <b>{title} — атлас (Неттер/Гайворонский)</b>",
        nav_prefix=f"anatomy_bone_atlas:{topic_key}:{bone_id}",
        back_callback=f"anatomy_bone_hub:{topic_key}:{bone_id}",
    )

@router.callback_query(F.data.startswith("anatomy_atlas:"))
async def cb_anatomy_atlas(callback: CallbackQuery):
    _, topic_key, page_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    page = int(page_s)
    images = get_topic_atlas_images(topic_key)
    if not images or not (0 <= page < anatomy_page_count(len(images))):
        await callback.answer("Фото для этой темы пока нет", show_alert=True)
        return
    await callback.answer()
    title = get_anatomy_topic_data(topic_key).get("title", "")
    await send_anatomy_album(
        callback, images, page,
        header=f"🖼 <b>{title} — атлас (Неттер/Гайворонский)</b>",
        nav_prefix=f"anatomy_atlas:{topic_key}",
        back_callback=f"anatomy_topic:{topic_key}",
    )

@router.callback_query(F.data.startswith("anatomy_bone_flash_start:"))
async def cb_anatomy_bone_flash_start(callback: CallbackQuery):
    _, topic_key, bone_id = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_bone_flashcards(topic_key, bone_id):
        await callback.answer("Карточки для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_flash_session(callback.from_user.id, topic_key, bone_id=bone_id)
    await render_anatomy_flash_question(callback.message, callback.from_user.id)

@router.callback_query(F.data.startswith("anatomy_bone_match_start:"))
async def cb_anatomy_bone_match_start(callback: CallbackQuery):
    _, topic_key, bone_id = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_bone_pairs(topic_key, bone_id):
        await callback.answer("Пары для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_match_session(callback.from_user.id, topic_key, bone_id=bone_id)
    await render_anatomy_match_question(callback.message, callback.from_user.id)

@router.callback_query(F.data.startswith("anatomy_bone_latin_start:"))
async def cb_anatomy_bone_latin_start(callback: CallbackQuery):
    _, topic_key, bone_id = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_bone_latin_terms(topic_key, bone_id):
        await callback.answer("Термины для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_latin_session(callback.from_user.id, topic_key, bone_id=bone_id)
    await render_anatomy_latin_question(callback.message, callback.from_user.id)

@router.callback_query(F.data.startswith("anatomy_bone_mnemonics:"))
async def cb_anatomy_bone_mnemonics(callback: CallbackQuery):
    _, topic_key, bone_id, idx_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    idx = int(idx_s)
    mnemonics = get_bone_mnemonics(topic_key, bone_id)
    if not mnemonics or not (0 <= idx < len(mnemonics)):
        await callback.answer("Мнемоники для этой кости ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_bone_mnemonic_text(topic_key, bone_id, idx),
        parse_mode="HTML",
        reply_markup=get_bone_mnemonics_keyboard(topic_key, bone_id, idx)
    )

@router.callback_query(F.data.startswith("anatomy_material_list:"))
async def cb_anatomy_material_list(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    await callback.answer()
    topic = get_anatomy_topic_data(topic_key)
    await tb.safe_edit_text(
        callback.message,
        f"📋 <b>{topic['title']} — список тем</b>\n{tb.DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_anatomy_material_list_keyboard(topic_key)
    )

@router.callback_query(F.data.startswith("anatomy_material:"))
async def cb_anatomy_material(callback: CallbackQuery):
    _, topic_key, idx_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    idx = int(idx_s)
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not (0 <= idx < len(topic["material"])):
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_material_text(topic_key, idx),
        parse_mode="HTML",
        reply_markup=get_anatomy_material_keyboard(topic_key, idx)
    )

@router.callback_query(F.data.startswith("anatomy_flash_start:"))
async def cb_anatomy_flash_start(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic["flashcards"]:
        await callback.answer("Карточки ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_flash_session(callback.from_user.id, topic_key)
    await render_anatomy_flash_question(callback.message, callback.from_user.id)

@router.callback_query(F.data == "anatomy_flash_show_answer")
async def cb_anatomy_flash_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ANATOMY_FLASH_SESSIONS:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_anatomy_flash_answer(callback.message, user_id)

@router.callback_query(F.data.in_({"anatomy_flash_know", "anatomy_flash_dont_know"}))
async def cb_anatomy_flash_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_FLASH_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "anatomy_flash_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["cards"]):
        await render_anatomy_flash_summary(callback.message, user_id)
    else:
        await render_anatomy_flash_question(callback.message, user_id)

@router.callback_query(F.data == "anatomy_flash_stop")
async def cb_anatomy_flash_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_FLASH_SESSIONS:
        await render_anatomy_flash_summary(callback.message, callback.from_user.id, aborted=True)

@router.callback_query(F.data.startswith("anatomy_match_start:"))
async def cb_anatomy_match_start(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_anatomy_all_pairs(topic_key):
        await callback.answer("Пары ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_match_session(callback.from_user.id, topic_key)
    await render_anatomy_match_question(callback.message, callback.from_user.id)

@router.callback_query(F.data.startswith("anatomy_match_answer:"))
async def cb_anatomy_match_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_MATCH_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    chosen = int(callback.data.split(":")[1])
    correct_idx = session["current_correct_idx"]
    if chosen == correct_idx:
        session["correct"] += 1
        await callback.answer("✅ Верно!")
    else:
        session["wrong"] += 1
        correct_text = session["current_options"][correct_idx]
        await callback.answer(f"❌ Неверно. Правильно: {correct_text}", show_alert=True)
    session["index"] += 1
    if session["index"] >= len(session["queue"]):
        await render_anatomy_match_summary(callback.message, user_id)
    else:
        await render_anatomy_match_question(callback.message, user_id)

@router.callback_query(F.data == "anatomy_match_stop")
async def cb_anatomy_match_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_MATCH_SESSIONS:
        await render_anatomy_match_summary(callback.message, callback.from_user.id, aborted=True)

@router.callback_query(F.data == "anatomy_latin_all_start")
async def cb_anatomy_latin_all_start(callback: CallbackQuery):
    # Глобальный тренажёр всегда бесплатен: сейчас latin_terms есть только у остеологии
    # (module1_osteology), а это свободный модуль — как только платный модуль обзаведётся
    # latin_terms, этот трейнер нужно будет тоже перевести на anatomy_section_access_ok.
    if not get_all_latin_terms():
        await callback.answer("Термины ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_latin_session(callback.from_user.id, is_global=True)
    await render_anatomy_latin_question(callback.message, callback.from_user.id)

@router.callback_query(F.data == "anatomy_latin_leaderboard")
async def cb_anatomy_latin_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_latin_leaderboard_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_anatomy_latin_leaderboard_keyboard()
    )

@router.callback_query(F.data.startswith("anatomy_latin_start:"))
async def cb_anatomy_latin_start(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    if not get_topic_latin_terms(topic_key):
        await callback.answer("Термины ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_latin_session(callback.from_user.id, topic_key)
    await render_anatomy_latin_question(callback.message, callback.from_user.id)

@router.callback_query(F.data.startswith("anatomy_latin_answer:"))
async def cb_anatomy_latin_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_LATIN_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    chosen = int(callback.data.split(":")[1])
    correct_idx = session["current_correct_idx"]
    if chosen == correct_idx:
        session["correct"] += 1
        await callback.answer("✅ Верно!")
    else:
        session["wrong"] += 1
        correct_text = session["current_options"][correct_idx]
        await callback.answer(f"❌ Неверно. Правильно: {correct_text}", show_alert=True)
    session["index"] += 1
    if session["index"] >= len(session["queue"]):
        await render_anatomy_latin_summary(callback.message, user_id)
    else:
        await render_anatomy_latin_question(callback.message, user_id)

@router.callback_query(F.data == "anatomy_latin_stop")
async def cb_anatomy_latin_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_LATIN_SESSIONS:
        await render_anatomy_latin_summary(callback.message, callback.from_user.id, aborted=True)

@router.callback_query(F.data.startswith("anatomy_mnemonics:"))
async def cb_anatomy_mnemonics(callback: CallbackQuery):
    _, topic_key, idx_s = callback.data.split(":")
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    idx = int(idx_s)
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic["mnemonics"] or not (0 <= idx < len(topic["mnemonics"])):
        await callback.answer("Мнемоники ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_mnemonic_text(topic_key, idx),
        parse_mode="HTML",
        reply_markup=get_anatomy_mnemonics_keyboard(topic_key, idx)
    )

@router.callback_query(F.data.startswith("anatomy_picture:"))
async def cb_anatomy_picture(callback: CallbackQuery):
    topic_key = callback.data.split(":")[1]
    if not anatomy_section_access_ok(callback.from_user.id, get_topic_section_key(topic_key)):
        await callback.answer(get_anatomy_dev_alert_text(), show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_topic:{topic_key}"))
    await tb.safe_edit_text(
        callback.message,
        f"🖼 <b>Найди на картинке</b>\n{tb.DIVIDER}\n\n"
        "🚧 Скоро будет добавлено — нужны изображения из атласов Неттера и Гайворонского.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

# ---- Экзамен (Вопросы практики / Вопросы теории / ТЕСТ) ----
# Второй подраздел Анатомии, отдельный от «Весь курс анатомии» — намеренно бесплатен для всех
# независимо от ANATOMY_FREE_SECTIONS/anatomy_access_ok, как и глобальный тест по латыни.
def get_anatomy_exam_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🖐 Вопросы практики", callback_data="anatomy_exam_practice")
    builder.button(text="📖 Вопросы теории", callback_data="anatomy_exam_theory")
    builder.button(text="✅ ТЕСТ", callback_data="anatomy_exam_test_menu")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню Анатомии", callback_data="anatomy_root"))
    return builder.as_markup()

@router.callback_query(F.data == "anatomy_exam_menu")
async def cb_anatomy_exam_menu(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🎓 <b>Экзамен по анатомии</b>\n{tb.DIVIDER}\n\nВыбери формат подготовки:",
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_menu_keyboard()
    )

def get_anatomy_exam_practice_section(section_id: int):
    return next((s for s in tb.ANATOMY_EXAM_PRACTICE_SECTIONS if s["id"] == section_id), None)

def get_anatomy_exam_practice_section_keyboard():
    builder = InlineKeyboardBuilder()
    for section in tb.ANATOMY_EXAM_PRACTICE_SECTIONS:
        count = len(section["questions"])
        prefix = "" if count else "🚧 "
        builder.button(
            text=f"{prefix}{section['title']} ({count})" if count else f"{prefix}{section['title']} — скоро",
            callback_data=f"anatomy_exam_practice_section:{section['id']}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К экзамену", callback_data="anatomy_exam_menu"))
    return builder.as_markup()

@router.callback_query(F.data == "anatomy_exam_practice")
async def cb_anatomy_exam_practice(callback: CallbackQuery):
    await callback.answer()
    total = sum(len(s["questions"]) for s in tb.ANATOMY_EXAM_PRACTICE_SECTIONS)
    await tb.safe_edit_text(
        callback.message,
        f"🖐 <b>Вопросы практики</b>\n{tb.DIVIDER}\n\n"
        f"Официальный перечень вопросов практической части экзамена по анатомии человека "
        f"(лечебное дело), утверждённый кафедрой нормальной анатомии ВМедА — {total} вопросов "
        f"в 4 разделах. К каждому ответу — изображение из атласа Неттера, Гайворонского или "
        f"из открытых источников.\n\nБесплатно для всех, без ограничений.\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_practice_section_keyboard()
    )

def get_anatomy_exam_practice_question_list_keyboard(section_id: int):
    section = get_anatomy_exam_practice_section(section_id)
    builder = InlineKeyboardBuilder()
    for q in section["questions"]:
        label = q["question"] if len(q["question"]) <= 50 else q["question"][:49] + "…"
        builder.button(text=f"{q['num']}. {label}", callback_data=f"anatomy_exam_practice_q:{section_id}:{q['num']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделам", callback_data="anatomy_exam_practice"))
    return builder.as_markup()

@router.callback_query(F.data.startswith("anatomy_exam_practice_section:"))
async def cb_anatomy_exam_practice_section(callback: CallbackQuery):
    section_id = int(callback.data.split(":")[1])
    section = get_anatomy_exam_practice_section(section_id)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    if not section["questions"]:
        await callback.answer("🚧 Этот раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"🖐 <b>{section['title']}</b>\n{tb.DIVIDER}\n\nВыбери вопрос ({len(section['questions'])}):",
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_practice_question_list_keyboard(section_id)
    )

def get_anatomy_exam_practice_question_text(section: dict, num: int) -> str:
    question = next(q for q in section["questions"] if q["num"] == num)
    credits = []
    for img in question["images"]:
        if img["credit"] not in credits:
            credits.append(img["credit"])
    return (
        f"🖐 <b>Вопрос {num}/{len(section['questions'])}</b>\n\n{tb.DIVIDER}\n\n"
        f"<b>{question['question']}</b>\n\n{tb.DIVIDER}\n\n{question['answer']}\n\n"
        f"<i>Источник фото: {'; '.join(credits)}</i>"
    )

def get_anatomy_exam_practice_question_keyboard(section_id: int, num: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if num > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_exam_practice_q:{section_id}:{num - 1}"))
    if num < total:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_exam_practice_q:{section_id}:{num + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="📋 Список вопросов", callback_data=f"anatomy_exam_practice_section:{section_id}"))
    builder.row(InlineKeyboardButton(text="🔙 К разделам", callback_data="anatomy_exam_practice"))
    return builder.as_markup()

@router.callback_query(F.data.startswith("anatomy_exam_practice_q:"))
async def cb_anatomy_exam_practice_question(callback: CallbackQuery):
    _, section_id_raw, num_raw = callback.data.split(":")
    section_id, num = int(section_id_raw), int(num_raw)
    section = get_anatomy_exam_practice_section(section_id)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    question = next((q for q in section["questions"] if q["num"] == num), None)
    if not question:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.answer()

    body = get_anatomy_exam_practice_question_text(section, num)
    keyboard = get_anatomy_exam_practice_question_keyboard(section_id, num, len(section["questions"]))
    images = question["images"]
    await callback.message.delete()

    if len(images) > 1:
        # sendMediaGroup can't carry a reply_markup, so the album is followed by a
        # separate text message with the full Q&A and nav buttons (mirrors send_anatomy_album).
        media = [InputMediaPhoto(media=_anatomy_image_media(img)) for img in images]
        sent_list = await callback.message.answer_media_group(media=media)
        for img, sent in zip(images, sent_list):
            _cache_anatomy_file_id(img, sent)
        await callback.message.answer(body, parse_mode="HTML", reply_markup=keyboard)
        return

    img = images[0]
    photo = _anatomy_image_media(img)

    if len(body) <= tb.CAPTION_LIMIT:
        sent = await callback.message.answer_photo(photo, caption=body, parse_mode="HTML", reply_markup=keyboard)
        _cache_anatomy_file_id(img, sent)
        return

    short_caption = f"<b>{question['question']}</b>"
    if len(short_caption) > tb.CAPTION_LIMIT:
        short_caption = short_caption[:tb.CAPTION_LIMIT - 1] + "…"
    sent = await callback.message.answer_photo(photo, caption=short_caption, parse_mode="HTML")
    _cache_anatomy_file_id(img, sent)
    await callback.message.answer(body, parse_mode="HTML", reply_markup=keyboard)

def get_anatomy_exam_theory_section(section_id: int):
    return next((s for s in tb.ANATOMY_EXAM_THEORY_SECTIONS if s["id"] == section_id), None)

def get_anatomy_exam_theory_section_keyboard():
    builder = InlineKeyboardBuilder()
    for section in tb.ANATOMY_EXAM_THEORY_SECTIONS:
        count = len(section["questions"])
        prefix = "" if count else "🚧 "
        builder.button(
            text=f"{prefix}{section['title']} ({count})" if count else f"{prefix}{section['title']} — скоро",
            callback_data=f"anatomy_exam_theory_section:{section['id']}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К экзамену", callback_data="anatomy_exam_menu"))
    return builder.as_markup()

@router.callback_query(F.data == "anatomy_exam_theory")
async def cb_anatomy_exam_theory(callback: CallbackQuery):
    await callback.answer()
    total = sum(len(s["questions"]) for s in tb.ANATOMY_EXAM_THEORY_SECTIONS)
    await tb.safe_edit_text(
        callback.message,
        f"📖 <b>Вопросы теории</b>\n{tb.DIVIDER}\n\n"
        f"Официальный перечень теоретических вопросов к экзамену по анатомии человека "
        f"(лечебное дело), утверждённый кафедрой нормальной анатомии ВМедА — {total} вопросов "
        f"в 4 разделах. Ответы составлены по учебнику И.В. Гайворонского.\n\n"
        "Бесплатно для всех, без ограничений.\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_theory_section_keyboard()
    )

def get_anatomy_exam_theory_question_list_keyboard(section_id: int):
    section = get_anatomy_exam_theory_section(section_id)
    builder = InlineKeyboardBuilder()
    for q in section["questions"]:
        label = q["question"] if len(q["question"]) <= 50 else q["question"][:49] + "…"
        builder.button(text=f"{q['num']}. {label}", callback_data=f"anatomy_exam_theory_q:{section_id}:{q['num']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделам", callback_data="anatomy_exam_theory"))
    return builder.as_markup()

@router.callback_query(F.data.startswith("anatomy_exam_theory_section:"))
async def cb_anatomy_exam_theory_section(callback: CallbackQuery):
    section_id = int(callback.data.split(":")[1])
    section = get_anatomy_exam_theory_section(section_id)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    if not section["questions"]:
        await callback.answer("🚧 Этот раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        f"📖 <b>{section['title']}</b>\n{tb.DIVIDER}\n\nВыбери вопрос ({len(section['questions'])}):",
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_theory_question_list_keyboard(section_id)
    )

def get_anatomy_exam_theory_question_text(section: dict, num: int) -> str:
    question = next(q for q in section["questions"] if q["num"] == num)
    return (
        f"📖 <b>Вопрос {num}/{len(section['questions'])}</b>\n\n{tb.DIVIDER}\n\n"
        f"<b>{question['question']}</b>\n\n{tb.DIVIDER}\n\n{question['answer']}"
    )

def get_anatomy_exam_theory_question_keyboard(section_id: int, num: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if num > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_exam_theory_q:{section_id}:{num - 1}"))
    if num < total:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_exam_theory_q:{section_id}:{num + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="📋 Список вопросов", callback_data=f"anatomy_exam_theory_section:{section_id}"))
    builder.row(InlineKeyboardButton(text="🔙 К разделам", callback_data="anatomy_exam_theory"))
    return builder.as_markup()

@router.callback_query(F.data.startswith("anatomy_exam_theory_q:"))
async def cb_anatomy_exam_theory_question(callback: CallbackQuery):
    _, section_id_str, num_str = callback.data.split(":")
    section_id, num = int(section_id_str), int(num_str)
    section = get_anatomy_exam_theory_section(section_id)
    if not section or not any(q["num"] == num for q in section["questions"]):
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_exam_theory_question_text(section, num),
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_theory_question_keyboard(section_id, num, len(section["questions"]))
    )

# ---- ТЕСТ: 1040 вопросов официального сборника кафедры нормальной анатомии ВМедА
# (Гайворонский и др., 2021), разбитые на 10 частей — 5 по «Базовой части», 5 по
# «Лечебному делу». Прохождение — полный последовательный прогон всех вопросов части
# (не случайная выборка, в отличие от ANATOMY_LATIN_SESSIONS), с возможностью закончить
# досрочно и посмотреть разбор своих ошибок после завершения.
ANATOMY_EXAM_TEST_SESSIONS: dict[int, dict] = {}
ANATOMY_EXAM_TEST_MISTAKES: dict[int, list] = {}
ANATOMY_EXAM_TEST_OPTION_LETTERS = "абвгд"
ANATOMY_EXAM_FLASH_SIZE = 50
ANATOMY_EXAM_TEST_ALL_QUESTIONS = [q for p in tb.ANATOMY_EXAM_TEST_PARTS for q in p["questions"]]

def get_anatomy_exam_test_part(part_id: int):
    return next((p for p in tb.ANATOMY_EXAM_TEST_PARTS if p["id"] == part_id), None)

# ---- Режим прохождения: обычный (просто для себя) или рейтинговый (результат каждой
# полностью пройденной — не прерванной — части идёт в общий рейтинг всех пользователей,
# накопительно: и число верных ответов, и общее число отвеченных вопросов растут с каждой
# зачтённой частью). Выбор режима — персональная настройка, переключается кнопкой в меню
# ТЕСТа и снимается в момент старта части, чтобы смена режима не задним числом не меняла
# уже идущую сессию.
def get_anatomy_exam_test_mode(user_id: int) -> str:
    return tb.stats.get("anatomy_exam_test_mode", {}).get(str(user_id), "normal")

def set_anatomy_exam_test_mode(user_id: int, mode: str) -> None:
    tb.stats.setdefault("anatomy_exam_test_mode", {})[str(user_id)] = mode
    tb.save_stats()

def record_anatomy_exam_test_score(user_id: int, correct: int, total: int) -> None:
    if total <= 0:
        return
    uid_str = str(user_id)
    scores = tb.stats.setdefault("anatomy_exam_test_scores", {})
    entry = scores.setdefault(uid_str, {"correct": 0, "total": 0, "attempts": 0})
    entry["correct"] += correct
    entry["total"] += total
    entry["attempts"] += 1
    tb.save_stats()

def get_anatomy_exam_test_leaderboard_text(user_id: int = None) -> str:
    scores = tb.stats.get("anatomy_exam_test_scores", {})
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1]["correct"], kv[1]["correct"] / kv[1]["total"] if kv[1]["total"] else 0),
        reverse=True,
    )
    header = f"🏆 <b>Рейтинг по ТЕСТу</b>\n{tb.DIVIDER}"
    if not ranked:
        return header + "\n\nПока никто не проходил части в рейтинговом режиме — стань первым! ✅"
    lines = [header, ""]
    shown_uids = []
    for i, (uid_str, entry) in enumerate(ranked):
        icon = tb.RANK_MEDALS[i] if i < 3 else f"{i + 1}."
        percent = round(100 * entry["correct"] / entry["total"]) if entry["total"] else 0
        row = f"{icon} {tb.donor_display_name(uid_str)} — <b>{entry['correct']}</b> верных ({percent}%, {entry['attempts']} частей)"
        if len("\n".join([*lines, row])) > ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT:
            break
        lines.append(row)
        shown_uids.append(uid_str)
    if len(shown_uids) < len(ranked):
        lines.append(f"\n… показаны первые {len(shown_uids)} из {len(ranked)}")
    if user_id is not None:
        uid_str = str(user_id)
        if uid_str not in shown_uids and uid_str in scores:
            rank = next(i for i, (u, _) in enumerate(ranked) if u == uid_str) + 1
            entry = scores[uid_str]
            percent = round(100 * entry["correct"] / entry["total"]) if entry["total"] else 0
            lines.append(f"\nТвоё место: <b>#{rank}</b> — {entry['correct']} верных ({percent}%)")
    return "\n".join(lines)

def get_anatomy_exam_test_leaderboard_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="anatomy_exam_test_leaderboard")
    builder.button(text="🔙 К тесту", callback_data="anatomy_exam_test_menu")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data == "anatomy_exam_test_leaderboard")
async def cb_anatomy_exam_test_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_exam_test_leaderboard_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_test_leaderboard_keyboard()
    )

# ---- Флэш-тест: 50 случайных вопросов из всего банка (все 10 частей вперемешку),
# всегда засчитывается в личный рекорд при полном прохождении (в отличие от обычных
# частей, тут нет отдельного переключателя режима — засчитывается любое завершённое
# прохождение). Рейтинг — по личному лучшему результату, как у теста по латыни
# (ANATOMY_LATIN_SESSIONS/record_anatomy_latin_score), а не накопительно, как у частей.
def record_anatomy_exam_flash_score(user_id: int, correct: int, total: int) -> bool:
    if total <= 0:
        return False
    uid_str = str(user_id)
    scores = tb.stats.setdefault("anatomy_exam_flash_scores", {})
    prev = scores.get(uid_str)
    percent = correct / total
    is_new_best = True
    if prev:
        prev_percent = prev["best_correct"] / prev["best_total"] if prev["best_total"] else 0
        is_new_best = percent > prev_percent or (percent == prev_percent and total > prev["best_total"])
    entry = scores.setdefault(uid_str, {"best_correct": correct, "best_total": total, "attempts": 0})
    entry["attempts"] = entry.get("attempts", 0) + 1
    if is_new_best:
        entry["best_correct"] = correct
        entry["best_total"] = total
    tb.save_stats()
    return is_new_best

def get_anatomy_exam_flash_leaderboard_text(user_id: int = None) -> str:
    scores = tb.stats.get("anatomy_exam_flash_scores", {})
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1]["best_correct"] / kv[1]["best_total"] if kv[1]["best_total"] else 0, kv[1]["best_correct"]),
        reverse=True,
    )
    header = f"⚡ <b>Рейтинг флэш-теста по анатомии</b>\n{tb.DIVIDER}"
    if not ranked:
        return header + "\n\nПока никто не проходил флэш-тест — стань первым! ⚡"
    lines = [header, ""]
    shown_uids = []
    for i, (uid_str, entry) in enumerate(ranked):
        icon = tb.RANK_MEDALS[i] if i < 3 else f"{i + 1}."
        percent = round(100 * entry["best_correct"] / entry["best_total"]) if entry["best_total"] else 0
        row = f"{icon} {tb.donor_display_name(uid_str)} — <b>{entry['best_correct']}/{entry['best_total']}</b> ({percent}%)"
        if len("\n".join([*lines, row])) > ANATOMY_LATIN_LEADERBOARD_MSG_LIMIT:
            break
        lines.append(row)
        shown_uids.append(uid_str)
    if len(shown_uids) < len(ranked):
        lines.append(f"\n… показаны первые {len(shown_uids)} из {len(ranked)}")
    if user_id is not None:
        uid_str = str(user_id)
        if uid_str not in shown_uids and uid_str in scores:
            rank = next(i for i, (u, _) in enumerate(ranked) if u == uid_str) + 1
            entry = scores[uid_str]
            percent = round(100 * entry["best_correct"] / entry["best_total"]) if entry["best_total"] else 0
            lines.append(f"\nТвоё место: <b>#{rank}</b> — {entry['best_correct']}/{entry['best_total']} ({percent}%)")
    return "\n".join(lines)

def get_anatomy_exam_flash_leaderboard_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Пройти флэш-тест", callback_data="anatomy_exam_test_flash_start")
    builder.button(text="🔄 Обновить", callback_data="anatomy_exam_flash_leaderboard")
    builder.button(text="🔙 К тесту", callback_data="anatomy_exam_test_menu")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data == "anatomy_exam_flash_leaderboard")
async def cb_anatomy_exam_flash_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_exam_flash_leaderboard_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_flash_leaderboard_keyboard()
    )

def get_anatomy_exam_test_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    if get_anatomy_exam_test_mode(user_id) == "rating":
        builder.button(text="🏆 Режим: рейтинговый (нажми для обычного)", callback_data="anatomy_exam_test_mode_toggle")
    else:
        builder.button(text="🎯 Режим: обычный (нажми для рейтингового)", callback_data="anatomy_exam_test_mode_toggle")
    builder.button(text="🏆 Рейтинг", callback_data="anatomy_exam_test_leaderboard")
    builder.button(text="⚡ Флэш-тест (50 случайных вопросов)", callback_data="anatomy_exam_test_flash_start")
    builder.button(text="🏆 Рейтинг флэш-теста", callback_data="anatomy_exam_flash_leaderboard")
    for part in tb.ANATOMY_EXAM_TEST_PARTS:
        builder.button(
            text=f"{part['title']} ({len(part['questions'])} вопр.)",
            callback_data=f"anatomy_exam_test_start:{part['id']}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К экзамену", callback_data="anatomy_exam_menu"))
    return builder.as_markup()

async def render_anatomy_exam_test_menu(message, user_id: int):
    total = sum(len(p["questions"]) for p in tb.ANATOMY_EXAM_TEST_PARTS)
    mode_line = (
        "🏆 Сейчас включён <b>рейтинговый режим</b> — результат каждой полностью пройденной "
        "части идёт в общий рейтинг."
        if get_anatomy_exam_test_mode(user_id) == "rating" else
        "🎯 Сейчас включён <b>обычный режим</b> — проходишь тест для себя, без рейтинга."
    )
    lines = [
        f"✅ <b>ТЕСТ по анатомии</b>\n{tb.DIVIDER}\n",
        "Официальный сборник тестовых вопросов кафедры нормальной анатомии ВМедА "
        f"(Гайворонский и др., 2021) — всего {total} вопросов, разбит на 10 частей.",
        "",
        "Внутри части вопросы идут по порядку, без случайной выборки — можно закончить "
        "досрочно в любой момент и сразу посмотреть разбор своих ошибок.",
        "",
        mode_line,
        "",
        "⚡ <b>Флэш-тест</b> — 50 случайных вопросов вперемешку из всех частей. Каждое "
        "полное прохождение сразу идёт в отдельный рейтинг флэш-теста — независимо от "
        "выбранного выше режима.",
        "",
        "Бесплатно для всех, без ограничений.",
        "",
        "<b>Что охватывает каждая часть:</b>",
    ]
    for part in tb.ANATOMY_EXAM_TEST_PARTS:
        lines.append(f"\n<b>{part['title']}</b>")
        lines.append(part["topics"])
    lines.append("\nВыбери часть:")
    await tb.safe_edit_text(
        message,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_test_menu_keyboard(user_id)
    )

@router.callback_query(F.data == "anatomy_exam_test_menu")
async def cb_anatomy_exam_test_menu(callback: CallbackQuery):
    await callback.answer()
    await render_anatomy_exam_test_menu(callback.message, callback.from_user.id)

@router.callback_query(F.data == "anatomy_exam_test_mode_toggle")
async def cb_anatomy_exam_test_mode_toggle(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_mode = "normal" if get_anatomy_exam_test_mode(user_id) == "rating" else "rating"
    set_anatomy_exam_test_mode(user_id, new_mode)
    await callback.answer("🏆 Рейтинговый режим включён" if new_mode == "rating" else "🎯 Обычный режим включён")
    await render_anatomy_exam_test_menu(callback.message, user_id)

def start_anatomy_exam_test_session(user_id: int, part_id: int) -> bool:
    part = get_anatomy_exam_test_part(part_id)
    if not part:
        return False
    ANATOMY_EXAM_TEST_SESSIONS[user_id] = {
        "part_id": part_id,
        "queue": part["questions"],
        "index": 0,
        "correct": 0,
        "wrong": 0,
        "mistakes": [],
        "is_rating": get_anatomy_exam_test_mode(user_id) == "rating",
        "is_flash": False,
    }
    return True

def start_anatomy_exam_flash_session(user_id: int) -> bool:
    if not ANATOMY_EXAM_TEST_ALL_QUESTIONS:
        return False
    size = min(ANATOMY_EXAM_FLASH_SIZE, len(ANATOMY_EXAM_TEST_ALL_QUESTIONS))
    ANATOMY_EXAM_TEST_SESSIONS[user_id] = {
        "part_id": None,
        "queue": random.sample(ANATOMY_EXAM_TEST_ALL_QUESTIONS, size),
        "index": 0,
        "correct": 0,
        "wrong": 0,
        "mistakes": [],
        "is_rating": False,
        "is_flash": True,
    }
    return True

def get_anatomy_exam_test_keyboard(question: dict):
    builder = InlineKeyboardBuilder()
    for letter in ANATOMY_EXAM_TEST_OPTION_LETTERS:
        if letter in question["options"]:
            builder.button(text=letter, callback_data=f"anatomy_exam_test_answer:{letter}")
    builder.adjust(5)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_exam_test_stop"))
    return builder.as_markup()

async def render_anatomy_exam_test_question(message, user_id: int):
    session = ANATOMY_EXAM_TEST_SESSIONS[user_id]
    question = session["queue"][session["index"]]
    if session.get("is_flash"):
        icon, label = "⚡", "ФЛЭШ-ТЕСТ"
    elif session.get("is_rating"):
        icon, label = "🏆", "ТЕСТ"
    else:
        icon, label = "🎯", "ТЕСТ"
    lines = [
        f"{icon} <b>{label} — вопрос {session['index'] + 1}/{len(session['queue'])}</b>\n{tb.DIVIDER}\n",
        f"{question['question']}\n",
    ]
    for letter in ANATOMY_EXAM_TEST_OPTION_LETTERS:
        if letter in question["options"]:
            lines.append(f"{letter}) {question['options'][letter]}")
    await tb.safe_edit_text(
        message, "\n".join(lines), parse_mode="HTML",
        reply_markup=get_anatomy_exam_test_keyboard(question)
    )

def get_anatomy_exam_test_mistake_text(mistake: dict, idx: int, total: int) -> str:
    lines = [
        f"❌ <b>Разбор ошибок — {idx + 1}/{total}</b>\n{tb.DIVIDER}\n",
        f"{mistake['question']}\n",
    ]
    for letter in ANATOMY_EXAM_TEST_OPTION_LETTERS:
        if letter not in mistake["options"]:
            continue
        marker = ""
        if letter == mistake["correct"]:
            marker = " ✅"
        elif letter == mistake["chosen"]:
            marker = " ❌ (твой ответ)"
        lines.append(f"{letter}) {mistake['options'][letter]}{marker}")
    return "\n".join(lines)

def get_anatomy_exam_test_mistake_keyboard(part_id: int, idx: int, total: int, is_flash: bool = False):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"anatomy_exam_test_mistakes:{idx - 1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="➡️ Следующая", callback_data=f"anatomy_exam_test_mistakes:{idx + 1}"))
    if nav:
        builder.row(*nav)
    if is_flash:
        builder.row(InlineKeyboardButton(text="🔁 Пройти ещё раз", callback_data="anatomy_exam_test_flash_start"))
    else:
        builder.row(InlineKeyboardButton(text="🔁 Пройти часть ещё раз", callback_data=f"anatomy_exam_test_start:{part_id}"))
    builder.row(InlineKeyboardButton(text="🔙 К списку частей", callback_data="anatomy_exam_test_menu"))
    return builder.as_markup()

async def render_anatomy_exam_test_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_EXAM_TEST_SESSIONS.pop(user_id, None)
    if not session:
        return
    answered = session["correct"] + session["wrong"]
    total = len(session["queue"])
    percent = round(100 * session["correct"] / answered) if answered else 0
    title = "🛑 <b>Тест прерван</b>" if aborted else "🏁 <b>Тест завершён!</b>"
    text = (
        f"{title}\n{tb.DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b> из {total}\n"
        f"✅ Верно: <b>{session['correct']}</b>\n"
        f"❌ Неверно: <b>{session['wrong']}</b>"
        + (f" ({percent}%)" if answered else "")
    )
    is_rating = session.get("is_rating", False)
    is_flash = session.get("is_flash", False)
    if is_flash:
        if not aborted and answered:
            is_new_best = record_anatomy_exam_flash_score(user_id, session["correct"], answered)
            text += "\n\n⚡ Результат добавлен в рейтинг флэш-теста." + (
                " 🎉 Это твой новый личный рекорд!" if is_new_best else ""
            )
        elif aborted:
            text += "\n\n⚠️ Флэш-тест не пройден до конца — в рейтинг не засчитано."
    elif is_rating and not aborted and answered:
        record_anatomy_exam_test_score(user_id, session["correct"], answered)
        text += "\n\n🏆 Результат добавлен в общий рейтинг."
    elif is_rating and aborted:
        text += (
            "\n\n⚠️ Часть не пройдена до конца — в рейтинг не засчитано "
            "(в рейтинговом режиме учитываются только полностью пройденные части)."
        )
    builder = InlineKeyboardBuilder()
    part_id = session["part_id"]
    if is_flash:
        builder.button(text="🔁 Пройти ещё раз", callback_data="anatomy_exam_test_flash_start")
    else:
        builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_exam_test_start:{part_id}")
    if session["mistakes"]:
        ANATOMY_EXAM_TEST_MISTAKES[user_id] = {"part_id": part_id, "is_flash": is_flash, "mistakes": session["mistakes"]}
        builder.button(text=f"❌ Разбор ошибок ({len(session['mistakes'])})", callback_data="anatomy_exam_test_mistakes:0")
    if is_flash:
        builder.button(text="🏆 Рейтинг флэш-теста", callback_data="anatomy_exam_flash_leaderboard")
    elif is_rating:
        builder.button(text="🏆 Рейтинг", callback_data="anatomy_exam_test_leaderboard")
    builder.button(text="🔙 К списку частей", callback_data="anatomy_exam_test_menu")
    builder.adjust(1)
    await tb.safe_edit_text(message, text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("anatomy_exam_test_start:"))
async def cb_anatomy_exam_test_start(callback: CallbackQuery):
    part_id = int(callback.data.split(":")[1])
    if not start_anatomy_exam_test_session(callback.from_user.id, part_id):
        await callback.answer("Часть не найдена", show_alert=True)
        return
    await callback.answer()
    await render_anatomy_exam_test_question(callback.message, callback.from_user.id)

@router.callback_query(F.data == "anatomy_exam_test_flash_start")
async def cb_anatomy_exam_test_flash_start(callback: CallbackQuery):
    if not start_anatomy_exam_flash_session(callback.from_user.id):
        await callback.answer("Вопросы не найдены", show_alert=True)
        return
    await callback.answer()
    await render_anatomy_exam_test_question(callback.message, callback.from_user.id)

@router.callback_query(F.data.startswith("anatomy_exam_test_answer:"))
async def cb_anatomy_exam_test_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_EXAM_TEST_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    chosen = callback.data.split(":")[1]
    question = session["queue"][session["index"]]
    correct = question["correct"]
    if chosen == correct:
        session["correct"] += 1
        await callback.answer("✅ Верно!")
    else:
        session["wrong"] += 1
        session["mistakes"].append({
            "question": question["question"],
            "options": question["options"],
            "correct": correct,
            "chosen": chosen,
        })
        correct_text = question["options"].get(correct, "")
        await callback.answer(f"❌ Неверно. Правильно: {correct}) {correct_text}", show_alert=True)
    session["index"] += 1
    if session["index"] >= len(session["queue"]):
        await render_anatomy_exam_test_summary(callback.message, user_id)
    else:
        await render_anatomy_exam_test_question(callback.message, user_id)

@router.callback_query(F.data == "anatomy_exam_test_stop")
async def cb_anatomy_exam_test_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_EXAM_TEST_SESSIONS:
        await render_anatomy_exam_test_summary(callback.message, callback.from_user.id, aborted=True)

@router.callback_query(F.data.startswith("anatomy_exam_test_mistakes:"))
async def cb_anatomy_exam_test_mistakes(callback: CallbackQuery):
    user_id = callback.from_user.id
    record = ANATOMY_EXAM_TEST_MISTAKES.get(user_id)
    if not record:
        await callback.answer("Ошибок нет или список устарел", show_alert=True)
        return
    mistakes = record["mistakes"]
    idx = int(callback.data.split(":")[1])
    if not (0 <= idx < len(mistakes)):
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message,
        get_anatomy_exam_test_mistake_text(mistakes[idx], idx, len(mistakes)),
        parse_mode="HTML",
        reply_markup=get_anatomy_exam_test_mistake_keyboard(
            record["part_id"], idx, len(mistakes), record.get("is_flash", False)
        )
    )

