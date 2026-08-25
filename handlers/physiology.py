# -*- coding: utf-8 -*-
"""Раздел «🧠 Нормальная физиология» — top-level предмет, свободный для всех (без реферального
гейта и без подписки, тот же выбор, что и для Оперативной хирургии — см. CLAUDE.md). Контент —
physiology.json: 23 темы, полностью и только по присланным пользовательским источникам («Том 1
1.pdf», «Том 2 1.pdf», «Физа учебник.pdf»), без единого добавленного извне медицинского факта.

Data model (см. scratchpad-парсер, не в репозитории — тот же принцип ETL-скрипта "не хранить в
репо", что у Operative Surgery): каждая тема — {topic_id, order, title, short_title, source_file,
source_pages, source_text, what_to_know[], definitions[{term,text}], mechanisms[{name,intro,
steps[]}], cause_effect[], regulation[], comparisons[{caption,headers[],rows[{aspect,values[]}]}],
remember[], confusions[], quick_review[], control_questions[], sections[{heading,text}],
deepening[{heading,text}]}. `sections` — единственное поле сверх исходно запрошенного набора:
полнотекстовая, ничего-не-теряющая развёртка темы по её собственным ### подзаголовкам, нужна
потому что многие темы (11-23) не следуют канонической схеме "что нужно знать/определения/
механизм/..." — у них просто идут доменные подзаголовки («Оптическая система», «Сетчатка», ...),
и без sections эта содержательная часть терялась бы. Читать конспект" всегда рендерит из sections
(гарантия полноты), "Учить по шагам" использует специализированные поля там, где они реально
заполнены исходником — пустой массив просто не даёт карточку этого типа, а не выдуманный текст.

Банк вопросов (quiz_questions, топ-уровень JSON) собран ОДИН РАЗ на этапе подготовки датасета
(не генерируется по запросу через модель) из уже распарсенных структурных полей — definitions/
mechanisms/cause_effect/comparisons — и НИКОГДА не изобретает новый факт: каждый вопрос проверяет
факт, уже присутствующий в датасете, а каждый дистрактор — реальный факт про ДРУГОЙ термин/шаг/
тему (правдоподобный, но однозначно неверный в данном контексте, не выдуманный). Темы, где ни
одного структурного поля не заполнено (только "06"/"07" из 23 — см. CLAUDE.md), честно не имеют
проверочных вопросов вовсе — самопроверка для них идёт только через control_questions без ответа
(источник не даёт готового ключа, поэтому это открытый список для самоконтроля, не quiz с
проверкой — тот же принцип, что и "Контрольные вопросы" в Operative Surgery).

Импортирует telegram_bot как tb по той же причине, что и остальные поздно подключаемые модули —
см. handlers/operative_surgery.py, тот же паттерн один в один.

**Рубежные контроли** (`physiology.json["boundary_controls"]`, top-level ключ отдельно от `topics`)
— 11 реальных рубежных контролей кафедры, импортированных из присланного пользователем архива
(DOCX -> markdown, извлечение "direct_docx_xml_no_ocr_no_paraphrase", т.е. текст скопирован из
XML документа напрямую, без OCR и без парафраза). Каждый control — `{control_id, order, title,
blocks[]}`, где `blocks` — упорядоченный поток узлов `{type: "text"|"image"|"table", ...,
provenance}` строго в порядке исходного документа (`ordering: "document_body_order"` в
manifest.json источника) — ни один узел не объединяется и не переставляется вручную: граница
"абзаца" в blocks 1:1 совпадает с границей исходного DOCX-параграфа (подтверждено сверкой:
100% текстовое совпадение содержимого blocks с content.md построчно на этапе импорта). `image`
узлы резолвятся из `{{IMAGE:NNN}}`-плейсхолдеров через `manifest.json` конкретного control_id —
никогда не переиспользуются между темами и не схлопываются при повторении. `table` узлы — редкий
кастомный формат источника ("### Таблица N" + "**Строка N**" + "- **Ячейка N:** значение",
только в rk_04, 4 таблицы) распарсен в `{caption, rows: [[cell, ...], ...]}`; редкий артефакт
экстракции, где к последней строке таблицы приклеена следующая фраза без пустой строки-разделителя,
не отбрасывается, а выносится отдельным text-узлом сразу после таблицы — весь текст источника
сохранён, просто не притворяется ячейкой. Каждый узел несёт `provenance` (`control_id,
source_docx, source_sha256, location`, для image ещё и `sha256` самого файла) — используется
только как внутренние метаданные для трассируемости, НИКОГДА не рендерится пользователю (ни как
"Источник:", ни как имя файла) — тот же принцип, что и убранные по прямому запросу пользователя
цитаты в остальной части раздела. Заголовок/источник-цитата DOCX (`# Рубежный контроль N` и
`> Исходный файл: ...`) отброшены при парсинге как структурный boilerplate, не как контент.
Картинки лежат в `images/physiology/boundary_controls/rk_NN/media/...` (repo-конвенция
`images/<subject>/...`, а не `bot_path` из manifest.json источника, который предполагал другую,
несуществующую в этом репо раскладку `content/physiology/...`) — каждый файл сверен по SHA-256
с manifest.json перед копированием. `build_rk_pages(blocks)` жадно группирует подряд идущие
text/table-узлы в одну Telegram-страницу (до ~3500 символов, разбивка только по границам узлов,
никогда не разрывая один узел) — image-узел всегда открывает свою отдельную страницу, поэтому
картинка остаётся ровно между теми же соседними текстовыми блоками, что и в исходнике.
`PHYS_RK_FILE_ID_CACHE` — тот же паттерн, что `ANATOMY_FILE_ID_CACHE`/`OH_FILE_ID_CACHE`: кэширует
Telegram `file_id` после первой загрузки, повторные показы не перезаливают файл с диска."""
import html
import json
import math
import os
import random
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import telegram_bot as tb

router = Router()

PHYS_TOPIC_PAGE_SIZE = 8
PHYS_QUIZ_SESSION_SIZE = 8
PHYS_SRS_STAGE_DAYS = [1, 3, 7, 14, 30]  # transparent, hand-tunable — not claimed to be an
# "optimal" spaced-repetition algorithm, just: new/failed -> soon, streak of successes -> longer
PHYS_MASTERY_MASTERED_THRESHOLD = 85

# in-memory session engines, same shape as ANATOMY_LATIN_SESSIONS/HISTOLOGY_GUESS_SESSIONS —
# dict[int user_id -> session dict], popped on completion/abort
PHYS_QUIZ_SESSIONS: dict = {}


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


# ==================== data lookups ====================

def get_phys_topic(topic_id: str):
    for t in tb.PHYSIOLOGY["topics"]:
        if t["topic_id"] == topic_id:
            return t
    return None


def phys_topic_ids_in_order():
    return [t["topic_id"] for t in tb.PHYSIOLOGY["topics"]]


def get_phys_topic_quiz_pool(topic_id: str):
    return [q for q in tb.PHYSIOLOGY["quiz_questions"] if q["topic_id"] == topic_id]


def _phys_topic_back_page(topic_id: str) -> int:
    ids = phys_topic_ids_in_order()
    idx = ids.index(topic_id) if topic_id in ids else 0
    return idx // PHYS_TOPIC_PAGE_SIZE


# ==================== progress / mastery / favorites / SRS ====================
# stats["physiology_progress"][uid][topic_id] = {opened_at, completed_cards, total_cards,
# correct_answers, total_answers, mechanism_correct, mechanism_total, last_score, best_score,
# mastery, last_studied_at, next_review_at, review_stage}
# stats["physiology_favorites"][uid] = {"topics": [topic_id, ...]} — single source of truth for
# favorites (not duplicated into the progress record, to avoid two places disagreeing)

def _phys_progress_all(user_id: int) -> dict:
    return tb.stats["physiology_progress"].setdefault(str(user_id), {})


def get_phys_progress(user_id: int, topic_id: str) -> dict:
    return _phys_progress_all(user_id).get(topic_id, {})


def _phys_progress_entry(user_id: int, topic_id: str) -> dict:
    all_p = _phys_progress_all(user_id)
    entry = all_p.setdefault(topic_id, {
        "opened_at": None, "completed_cards": 0, "total_cards": 0,
        "correct_answers": 0, "total_answers": 0,
        "mechanism_correct": 0, "mechanism_total": 0,
        "last_score": None, "best_score": None, "mastery": 0,
        "last_studied_at": None, "next_review_at": None, "review_stage": 0,
    })
    return entry


def phys_mark_opened(user_id: int, topic_id: str, total_cards: int) -> None:
    entry = _phys_progress_entry(user_id, topic_id)
    if entry["opened_at"] is None:
        entry["opened_at"] = time.time()
    entry["total_cards"] = max(entry["total_cards"], total_cards)
    entry["last_studied_at"] = time.time()
    tb.save_stats()


def phys_mark_card_done(user_id: int, topic_id: str) -> None:
    entry = _phys_progress_entry(user_id, topic_id)
    entry["completed_cards"] = min(entry["total_cards"] or 999, entry["completed_cards"] + 1)
    entry["last_studied_at"] = time.time()
    _phys_recalc_mastery(entry)
    tb.save_stats()


def _phys_recalc_mastery(entry: dict) -> None:
    card_ratio = (entry["completed_cards"] / entry["total_cards"]) if entry["total_cards"] else 0.0
    quiz_ratio = (entry["correct_answers"] / entry["total_answers"]) if entry["total_answers"] else 0.0
    mech_ratio = (entry["mechanism_correct"] / entry["mechanism_total"]) if entry["mechanism_total"] else 0.0
    mastery = 0.4 * card_ratio + 0.4 * quiz_ratio + 0.2 * mech_ratio
    entry["mastery"] = round(mastery * 100)


def phys_record_quiz_answer(user_id: int, topic_id: str, qtype: str, correct: bool) -> None:
    entry = _phys_progress_entry(user_id, topic_id)
    entry["total_answers"] += 1
    if correct:
        entry["correct_answers"] += 1
    if qtype in ("next_step", "cause_effect"):
        entry["mechanism_total"] += 1
        if correct:
            entry["mechanism_correct"] += 1
    entry["last_studied_at"] = time.time()
    _phys_recalc_mastery(entry)
    tb.save_stats()


def phys_record_quiz_session_complete(user_id: int, topic_id: str, correct: int, total: int) -> None:
    """Called once per fully-completed (not aborted) quiz session — updates last/best score and
    advances the minimal transparent SRS schedule (see PHYS_SRS_STAGE_DAYS)."""
    entry = _phys_progress_entry(user_id, topic_id)
    score = (correct / total) if total else 0.0
    entry["last_score"] = round(score * 100)
    if entry["best_score"] is None or score * 100 > entry["best_score"]:
        entry["best_score"] = round(score * 100)
    if score >= 0.6:
        entry["review_stage"] = min(entry["review_stage"] + 1, len(PHYS_SRS_STAGE_DAYS) - 1)
    else:
        entry["review_stage"] = 0
    days = PHYS_SRS_STAGE_DAYS[entry["review_stage"]]
    entry["next_review_at"] = time.time() + days * 86400
    tb.save_stats()


def phys_topic_status(user_id: int, topic_id: str) -> str:
    """not_started | learning | studied | needs_review | mastered — derived, never stored, so it
    can never drift out of sync with the underlying counters."""
    entry = get_phys_progress(user_id, topic_id)
    if not entry or entry.get("opened_at") is None:
        return "not_started"
    if entry.get("next_review_at") and entry["next_review_at"] <= time.time():
        return "needs_review"
    if entry.get("mastery", 0) >= PHYS_MASTERY_MASTERED_THRESHOLD and entry.get("total_answers"):
        return "mastered"
    total_cards = entry.get("total_cards") or 0
    if total_cards and entry.get("completed_cards", 0) >= total_cards:
        return "studied"
    return "learning"


PHYS_STATUS_ICONS = {
    "not_started": "⚪", "learning": "🟡", "studied": "🟢", "mastered": "🏆", "needs_review": "🔁",
}


def phys_favorites(user_id: int) -> list:
    return tb.stats["physiology_favorites"].setdefault(str(user_id), {"topics": []})["topics"]


def phys_is_favorite(user_id: int, topic_id: str) -> bool:
    return topic_id in phys_favorites(user_id)


def phys_toggle_favorite(user_id: int, topic_id: str) -> bool:
    favs = phys_favorites(user_id)
    if topic_id in favs:
        favs.remove(topic_id)
        added = False
    else:
        favs.append(topic_id)
        added = True
    tb.save_stats()
    return added


# ==================== step-card assembly ("Учить по шагам") ====================
# Каждая тема собирается в динамический список карточек — только из реально заполненных полей,
# пустой раздел темы просто не даёт карточки этого типа (никогда не показывается пустая "болванка").

def build_phys_learn_cards(topic: dict) -> list:
    cards = []
    if topic["what_to_know"]:
        cards.append({"kind": "what_to_know", "title": "📌 Что нужно знать"})
    for i, d in enumerate(topic["definitions"]):
        cards.append({"kind": "definition", "title": "📖 Ключевое определение", "idx": i})
    for i, m in enumerate(topic["mechanisms"]):
        cards.append({"kind": "mechanism", "title": f"📋 {m['name'] or 'Механизм'}", "idx": i})
    if topic["cause_effect"]:
        cards.append({"kind": "cause_effect", "title": "🔗 Причинно-следственные связи"})
    if topic["regulation"]:
        cards.append({"kind": "regulation", "title": "⚙️ Регуляция"})
    for i, c in enumerate(topic["comparisons"]):
        cards.append({"kind": "comparison", "title": f"📊 {c['caption']}", "idx": i})
    if topic["remember"]:
        cards.append({"kind": "remember", "title": "💡 Главное запомнить"})
    if topic["confusions"]:
        cards.append({"kind": "confusions", "title": "⚠️ Частые путаницы"})
    quiz_pool = get_phys_topic_quiz_pool(topic["topic_id"])
    if quiz_pool:
        # a short mini-check every ~3rd card, interleaved after this point (index computed at
        # render time from the base list length, so it stays stable regardless of quiz pool size)
        cards.append({"kind": "minicheck", "title": "❓ Мини-проверка"})
    return cards


def render_phys_learn_card(topic: dict, card: dict) -> str:
    header = f"🧠 <b>{esc(topic['title'])}</b>\n{tb.DIVIDER}\n\n{card['title']}\n\n"
    kind = card["kind"]
    if kind == "what_to_know":
        body = "\n".join(f"• {esc(x)}" for x in topic["what_to_know"])
    elif kind == "definition":
        d = topic["definitions"][card["idx"]]
        body = f"<b>{esc(d['term'])}</b> — {d['text']}"
    elif kind == "mechanism":
        m = topic["mechanisms"][card["idx"]]
        intro = f"{esc(m['intro'])}\n\n" if m.get("intro") else ""
        steps = "\n".join(f"{i}. {esc(s)}" for i, s in enumerate(m["steps"], 1))
        body = f"{intro}{steps}"
    elif kind == "cause_effect":
        body = "\n".join(f"• {esc(x)}" for x in topic["cause_effect"])
    elif kind == "regulation":
        body = "\n".join(f"• {esc(x)}" for x in topic["regulation"])
    elif kind == "comparison":
        body = render_phys_comparison_body(topic["comparisons"][card["idx"]])
    elif kind == "remember":
        body = "\n".join(f"<i>{esc(x)}</i>" for x in topic["remember"])
    elif kind == "confusions":
        body = "\n".join(f"• {esc(x)}" for x in topic["confusions"])
    elif kind == "minicheck":
        body = "Сейчас будет один короткий вопрос по этой теме — жми «➡️ Вопрос»."
    else:
        body = ""
    return header + body


def get_phys_learn_keyboard(topic_id: str, idx: int, total: int, card_kind: str):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"phys:learn:{topic_id}:{idx - 1}"))
    if card_kind == "minicheck":
        nav.append(InlineKeyboardButton(text="➡️ Вопрос", callback_data=f"phys:mini:{topic_id}:{idx}"))
    else:
        builder.row(InlineKeyboardButton(text="Понятно ✅", callback_data=f"phys:learn_ok:{topic_id}:{idx}"))
        if idx + 1 < total:
            nav.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"phys:learn:{topic_id}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🏠 В тему", callback_data=f"phys:topic:{topic_id}"))
    return builder.as_markup()


# ==================== comparison rendering (shared by learn-card + dedicated screen) ====================

def render_phys_comparison_body(cmp_: dict) -> str:
    headers = cmp_["headers"]
    if len(headers) != 2:
        lines = [f"<b>{esc(cmp_['caption'])}</b>"]
        for row in cmp_["rows"]:
            vals = "; ".join(esc(v) for v in row["values"])
            lines.append(f"• <b>{esc(row['aspect'])}:</b> {vals}")
        return "\n".join(lines)
    left_h, right_h = headers
    left_lines = [f"📊 <b>{esc(left_h).upper()}</b>"]
    right_lines = [f"⚡ <b>{esc(right_h).upper()}</b>"]
    for row in cmp_["rows"]:
        if len(row["values"]) != 2:
            continue
        left_lines.append(f"• {esc(row['aspect'])}: {esc(row['values'][0])}")
        right_lines.append(f"• {esc(row['aspect'])}: {esc(row['values'][1])}")
    return "\n".join(left_lines) + "\n\n↕️\n\n" + "\n".join(right_lines)


# ==================== menu ====================

def get_phys_menu_text(user_id: int) -> str:
    topics = tb.PHYSIOLOGY["topics"]
    statuses = [phys_topic_status(user_id, t["topic_id"]) for t in topics]
    studied = sum(1 for s in statuses if s in ("studied", "mastered", "needs_review"))
    mastered = sum(1 for s in statuses if s == "mastered")
    needs_review = sum(1 for s in statuses if s == "needs_review")
    return (
        f"🧠 <b>НОРМАЛЬНАЯ ФИЗИОЛОГИЯ</b>\n{tb.DIVIDER}\n\n"
        f"Полный курс VMEDA\n{len(topics)} тем • от клетки до тканевого дыхания\n\n"
        f"📚 Изучено: {studied} / {len(topics)}\n"
        f"🟢 Освоено: {mastered} / {len(topics)}\n"
        f"🔁 Требуют повторения: {needs_review}\n\n"
        "Выбери режим:"
    )


def get_phys_menu_keyboard(user_id: int):
    any_started = any(
        phys_topic_status(user_id, t["topic_id"]) != "not_started" for t in tb.PHYSIOLOGY["topics"]
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Все темы", callback_data="phys:topics:0")
    continue_label = "🧠 Продолжить обучение" if any_started else "🧠 Начать обучение"
    builder.button(text=continue_label, callback_data="phys:continue")
    builder.button(text="⚡ Быстрый повтор", callback_data="phys:qpick:0")
    builder.button(text="🎯 Проверить себя", callback_data="phys:zpick:0")
    builder.button(text="📋 Рубежные контроли", callback_data="phys:rk_menu")
    builder.button(text="🔎 Поиск", callback_data="phys:search_prompt")
    builder.button(text="⭐ Избранное", callback_data="phys:favorites")
    builder.button(text="📊 Мой прогресс", callback_data="phys:progress")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))
    return builder.as_markup()


def phys_next_topic_for_continue(user_id: int) -> str:
    """First topic that's needs_review, else first not_started/learning, else just topic 1."""
    ids = phys_topic_ids_in_order()
    for tid in ids:
        if phys_topic_status(user_id, tid) == "needs_review":
            return tid
    for tid in ids:
        if phys_topic_status(user_id, tid) in ("not_started", "learning"):
            return tid
    return ids[0]


# ==================== topics list ====================

def get_phys_topics_text(page: int) -> str:
    topics = tb.PHYSIOLOGY["topics"]
    total_pages = max(1, math.ceil(len(topics) / PHYS_TOPIC_PAGE_SIZE))
    return f"📚 <b>ТЕМЫ КУРСА</b>\nСтраница {page + 1} / {total_pages}"


def get_phys_topics_keyboard(page: int, user_id: int, target: str = "topic"):
    """target: 'topic' -> phys:topic:{id} (default topic card); 'quick' -> phys:quick:{id};
    'quiz' -> phys:quiz_start:{id} — same list, different tap destination, for the "pick a topic
    for quick review / for a quiz" entry points off the main menu."""
    topics = tb.PHYSIOLOGY["topics"]
    start = page * PHYS_TOPIC_PAGE_SIZE
    chunk = topics[start:start + PHYS_TOPIC_PAGE_SIZE]
    builder = InlineKeyboardBuilder()
    for t in chunk:
        icon = PHYS_STATUS_ICONS[phys_topic_status(user_id, t["topic_id"])]
        dest = {"topic": "topic", "quick": "quick", "quiz": "quiz_start"}[target]
        builder.button(text=f"{icon} {t['order']}. {t['short_title']}", callback_data=f"phys:{dest}:{t['topic_id']}")
    builder.adjust(1)
    nav = []
    back_prefix = {"topic": "topics", "quick": "qpick", "quiz": "zpick"}[target]
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"phys:{back_prefix}:{page - 1}"))
    if start + PHYS_TOPIC_PAGE_SIZE < len(topics):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"phys:{back_prefix}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🏠 Меню физиологии", callback_data="phys:menu"))
    return builder.as_markup()


# ==================== topic card ====================

def get_phys_topic_text(topic: dict, user_id: int) -> str:
    status = phys_topic_status(user_id, topic["topic_id"])
    status_label = {
        "not_started": "не начата", "learning": "изучается", "studied": "изучена",
        "mastered": "освоена", "needs_review": "пора повторить",
    }[status]
    if topic["what_to_know"]:
        bullets = "\n".join(f"• {esc(x)}" for x in topic["what_to_know"][:6])
    else:
        bullets = "\n".join(f"• {esc(s['heading'])}" for s in topic["sections"][:6] if s["heading"])
    return (
        f"🧠 ТЕМА {topic['order']}\n<b>{esc(topic['title']).upper()}</b>\n{tb.DIVIDER}\n\n"
        f"📌 Что изучим:\n{bullets}\n\n"
        f"{PHYS_STATUS_ICONS[status]} Статус: {status_label}"
    )


def get_phys_topic_keyboard(topic: dict, user_id: int, back_page: int = None):
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 Учить по шагам", callback_data=f"phys:learn:{topic['topic_id']}:0")
    builder.button(text="📖 Читать конспект", callback_data=f"phys:read:{topic['topic_id']}:0")
    builder.button(text="⚡ Повторить быстро", callback_data=f"phys:quick:{topic['topic_id']}")
    builder.button(text="🎯 Проверить себя", callback_data=f"phys:quiz_start:{topic['topic_id']}")
    if topic["cause_effect"] or topic["mechanisms"]:
        builder.button(text="🔗 Причинные цепочки", callback_data=f"phys:chains:{topic['topic_id']}:0")
    if topic["comparisons"]:
        builder.button(text="📊 Таблицы и сравнения", callback_data=f"phys:cmp:{topic['topic_id']}:0")
    fav_label = "⭐ Убрать из избранного" if phys_is_favorite(user_id, topic["topic_id"]) else "⭐ В избранное"
    builder.button(text=fav_label, callback_data=f"phys:fav_toggle:{topic['topic_id']}")
    builder.adjust(1)
    page = back_page if back_page is not None else _phys_topic_back_page(topic["topic_id"])
    builder.row(InlineKeyboardButton(text="⬅️ К темам", callback_data=f"phys:topics:{page}"))
    return builder.as_markup()


# ==================== reading mode ====================

def get_phys_read_text(topic: dict, idx: int) -> str:
    sec = topic["sections"][idx]
    total = len(topic["sections"])
    heading_line = f"<b>{esc(sec['heading'])}</b>\n\n" if sec["heading"] else ""
    text = sec["text"] or "(раздел пуст)"
    if len(text) > 3800:
        text = text[:3800].rsplit("\n\n", 1)[0] + "…"
    return f"📖 <b>{esc(topic['title'])}</b> ({idx + 1}/{total})\n{tb.DIVIDER}\n\n{heading_line}{text}"


def get_phys_read_keyboard(topic_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"phys:read:{topic_id}:{idx - 1}"))
    if idx + 1 < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"phys:read:{topic_id}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🏠 В тему", callback_data=f"phys:topic:{topic_id}"))
    return builder.as_markup()


# ==================== quick review ====================

def get_phys_quick_text(topic: dict) -> str:
    suть = topic["quick_review"][0] if topic["quick_review"] else (topic["remember"][0] if topic["remember"] else "")
    if topic["cause_effect"]:
        chain = topic["cause_effect"][0]
    elif topic["mechanisms"]:
        chain = " → ".join(topic["mechanisms"][0]["steps"][:4])
    else:
        chain = ""
    must_name = topic["what_to_know"][:3] or [d["term"] for d in topic["definitions"][:3]]
    confusions = topic["confusions"][:2]
    cq = topic["control_questions"][0] if topic["control_questions"] else ""
    lines = [f"⚡ <b>ТЕМА ЗА 3 МИНУТЫ</b>\n{tb.DIVIDER}\n"]
    if suть:
        lines.append(f"🎯 Суть:\n{esc(suть)}\n")
    if chain:
        lines.append(f"🔗 Главная цепочка:\n{esc(chain)}\n")
    if must_name:
        lines.append("📌 Обязательно назвать:\n" + "\n".join(f"• {esc(x)}" for x in must_name) + "\n")
    if confusions:
        lines.append("⚠️ Не перепутать:\n" + "\n".join(f"• {esc(x)}" for x in confusions) + "\n")
    if cq:
        lines.append(f"❓ Проверь себя:\n{esc(cq)}")
    return "\n".join(lines)


def get_phys_quick_keyboard(topic_id: str):
    builder = InlineKeyboardBuilder()
    if get_phys_topic_quiz_pool(topic_id):
        builder.button(text="🎯 Мини-вопрос", callback_data=f"phys:mini:{topic_id}:0")
    builder.button(text="🧠 Учить по шагам", callback_data=f"phys:learn:{topic_id}:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К теме", callback_data=f"phys:topic:{topic_id}"))
    return builder.as_markup()


# ==================== causal chains ====================

def build_phys_chains(topic: dict) -> list:
    """Each chain is {"caption": str, "steps": [str]} — combines cause_effect arrow-lines
    (each already a full A -> B -> C chain) with mechanism step sequences."""
    chains = []
    for ce in topic["cause_effect"]:
        parts = [p.strip().rstrip(".") for p in ce.split("→")]
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            chains.append({"caption": "Причинно-следственная связь", "steps": parts})
    for m in topic["mechanisms"]:
        if m["steps"]:
            chains.append({"caption": m["name"] or "Механизм", "steps": m["steps"]})
    return chains


def get_phys_chain_text(topic: dict, idx: int, chains: list) -> str:
    chain = chains[idx]
    body = f"\n{esc('↓')}\n".join(esc(s) for s in chain["steps"])
    return (
        f"🔗 <b>ПРИЧИННАЯ ЦЕПОЧКА</b> ({idx + 1}/{len(chains)})\n{tb.DIVIDER}\n\n"
        f"<i>{esc(chain['caption'])}</i>\n\n{body}"
    )


def get_phys_chain_keyboard(topic_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"phys:chains:{topic_id}:{idx - 1}"))
    if idx + 1 < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"phys:chains:{topic_id}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К теме", callback_data=f"phys:topic:{topic_id}"))
    return builder.as_markup()


# ==================== comparisons screen ====================

def get_phys_cmp_text(topic: dict, idx: int) -> str:
    total = len(topic["comparisons"])
    body = render_phys_comparison_body(topic["comparisons"][idx])
    return f"📊 <b>{esc(topic['title'])}</b> ({idx + 1}/{total})\n{tb.DIVIDER}\n\n{body}"


def get_phys_cmp_keyboard(topic_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"phys:cmp:{topic_id}:{idx - 1}"))
    if idx + 1 < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"phys:cmp:{topic_id}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К теме", callback_data=f"phys:topic:{topic_id}"))
    return builder.as_markup()


# ==================== quiz engine ====================

def start_phys_quiz_session(user_id: int, topic_id: str) -> bool:
    pool = get_phys_topic_quiz_pool(topic_id)
    if not pool:
        return False
    size = min(PHYS_QUIZ_SESSION_SIZE, len(pool))
    queue = random.sample(pool, size)
    PHYS_QUIZ_SESSIONS[user_id] = {
        "topic_id": topic_id, "queue": queue, "index": 0, "correct": 0, "wrong": 0,
    }
    return True


def render_phys_quiz_question(session: dict) -> str:
    q = session["queue"][session["index"]]
    total = len(session["queue"])
    options = "\n".join(f"{i}. {esc(o)}" for i, o in enumerate(q["options"], 1))
    return (
        f"🎯 <b>Вопрос {session['index'] + 1}/{total}</b>\n{tb.DIVIDER}\n\n"
        f"{esc(q['prompt'])}\n\n{options}"
    )


def get_phys_quiz_question_keyboard(topic_id: str, options: list):
    builder = InlineKeyboardBuilder()
    for i in range(len(options)):
        builder.button(text=str(i + 1), callback_data=f"phys:quiz_answer:{i}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="phys:quiz_stop"))
    return builder.as_markup()


def render_phys_quiz_answer(q: dict, chosen_idx: int) -> str:
    chosen = q["options"][chosen_idx]
    correct = chosen == q["correct_answer"]
    verdict = "✅ Верно" if correct else "❌ Неверно"
    lines = [f"{verdict}\n{tb.DIVIDER}\n", f"Правильно:\n{esc(q['correct_answer'])}\n"]
    if q.get("explanation"):
        lines.append(f"Почему:\n{esc(q['explanation'])}")
    return "\n".join(lines)


def get_phys_quiz_answer_keyboard(is_last: bool):
    builder = InlineKeyboardBuilder()
    if is_last:
        builder.button(text="🏁 Итоги", callback_data="phys:quiz_next")
    else:
        builder.button(text="➡️ Следующий вопрос", callback_data="phys:quiz_next")
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="phys:quiz_stop"))
    return builder.as_markup()


def get_phys_quiz_summary_text(session: dict, aborted: bool) -> str:
    total_answered = session["correct"] + session["wrong"]
    header = "🛑 Прервано" if aborted else "🏁 Вопросы закончились!"
    pct = round(100 * session["correct"] / total_answered) if total_answered else 0
    return (
        f"{header}\n{tb.DIVIDER}\n\n"
        f"Правильно: {session['correct']} из {total_answered} ({pct}%)"
    )


def get_phys_quiz_summary_keyboard(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data=f"phys:quiz_start:{topic_id}")
    builder.button(text="🔙 К теме", callback_data=f"phys:topic:{topic_id}")
    builder.adjust(1)
    return builder.as_markup()


async def finish_phys_quiz(callback: CallbackQuery, aborted: bool):
    user_id = callback.from_user.id
    session = PHYS_QUIZ_SESSIONS.pop(user_id, None)
    if session is None:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    total_answered = session["correct"] + session["wrong"]
    if not aborted and total_answered > 0:
        phys_record_quiz_session_complete(user_id, session["topic_id"], session["correct"], total_answered)
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_quiz_summary_text(session, aborted), parse_mode="HTML",
        reply_markup=get_phys_quiz_summary_keyboard(session["topic_id"])
    )


# ==================== favorites / progress / sources (static-ish screens) ====================

def get_phys_favorites_text(user_id: int) -> str:
    favs = phys_favorites(user_id)
    if not favs:
        return f"⭐ <b>Избранное</b>\n{tb.DIVIDER}\n\nПока пусто — добавляй темы кнопкой «⭐ В избранное» на экране темы."
    lines = [f"⭐ <b>Избранное</b>\n{tb.DIVIDER}\n"]
    for tid in favs:
        t = get_phys_topic(tid)
        if t:
            lines.append(f"• {t['order']}. {esc(t['short_title'])}")
    return "\n".join(lines)


def get_phys_favorites_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    for tid in phys_favorites(user_id):
        t = get_phys_topic(tid)
        if t:
            builder.button(text=f"{t['order']}. {t['short_title']}", callback_data=f"phys:topic:{tid}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🏠 Меню физиологии", callback_data="phys:menu"))
    return builder.as_markup()


def get_phys_progress_text(user_id: int) -> str:
    topics = tb.PHYSIOLOGY["topics"]
    by_status = {}
    for t in topics:
        s = phys_topic_status(user_id, t["topic_id"])
        by_status.setdefault(s, []).append(t)
    lines = [f"📊 <b>Мой прогресс</b>\n{tb.DIVIDER}\n"]
    order = ["mastered", "studied", "needs_review", "learning", "not_started"]
    labels = {
        "mastered": "🏆 Освоено", "studied": "🟢 Изучено", "needs_review": "🔁 Пора повторить",
        "learning": "🟡 В процессе", "not_started": "⚪ Не начато",
    }
    for key in order:
        n = len(by_status.get(key, []))
        lines.append(f"{labels[key]}: {n}")
    all_p = _phys_progress_all(user_id)
    total_answers = sum(e.get("total_answers", 0) for e in all_p.values())
    correct_answers = sum(e.get("correct_answers", 0) for e in all_p.values())
    if total_answers:
        pct = round(100 * correct_answers / total_answers)
        lines.append(f"\n🎯 Точность по всем вопросам: {correct_answers}/{total_answers} ({pct}%)")
    review_due = by_status.get("needs_review", [])
    if review_due:
        lines.append("\n🔁 Пора повторить:\n" + "\n".join(f"• {esc(t['short_title'])}" for t in review_due[:8]))
    return "\n".join(lines)


def get_phys_progress_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏠 Меню физиологии", callback_data="phys:menu"))
    return builder.as_markup()


# ==================== search ====================

def search_physiology(query: str, limit: int = 8):
    q = query.strip().lower()
    if not q:
        return []
    hits = []
    for t in tb.PHYSIOLOGY["topics"]:
        if q in t["title"].lower():
            hits.append(t)
            continue
        if any(q in x.lower() for x in t["what_to_know"]):
            hits.append(t)
            continue
        if any(q in d["term"].lower() or q in d["text"].lower() for d in t["definitions"]):
            hits.append(t)
            continue
        if any(q in s["heading"].lower() or q in s["text"].lower() for s in t["sections"]):
            hits.append(t)
    return hits[:limit]


# ==================== рубежные контроли ====================
# Чисто просмотровый раздел (не quiz/SRS/mastery — за пределами того, что реально запрошено):
# 11 реальных рубежных контролей кафедры, каждый — упорядоченный поток text/image/table узлов
# (см. docstring модуля выше про импорт/provenance/раскладку картинок). "Читать" здесь означает
# буквально то же самое, что "Читать конспект" у обычных тем — постранично, без вываливания
# всего материала одним сообщением.

PHYS_RK_PAGE_CHAR_BUDGET = 3500
PHYS_RK_IMAGES_DIR = os.path.join(tb.IMAGES_DIR, "physiology", "boundary_controls")


def get_rk_control(control_id: str):
    for c in tb.PHYSIOLOGY.get("boundary_controls", []):
        if c["control_id"] == control_id:
            return c
    return None


def rk_control_ids_in_order():
    return [c["control_id"] for c in tb.PHYSIOLOGY.get("boundary_controls", [])]


def render_rk_table_block(block: dict) -> str:
    lines = [f"<b>{block['caption']}</b>"]
    for row in block["rows"]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def build_rk_pages(blocks: list) -> list:
    """Жадно группирует подряд идущие text/table-узлы в одну страницу (до
    PHYS_RK_PAGE_CHAR_BUDGET символов) — разбивка только по границе узла (= границе исходного
    DOCX-абзаца), один узел никогда не разрезается. image-узел всегда открывает свою отдельную
    страницу (Telegram не может прикрепить фото к уже отправленному текстовому сообщению), так
    что картинка остаётся ровно между теми же соседними текстовыми блоками, что и в исходнике."""
    pages = []
    current_parts: list = []
    current_len = 0

    def flush():
        nonlocal current_len
        if current_parts:
            pages.append({"kind": "text", "text": "\n\n".join(current_parts)})
            current_parts.clear()
            current_len = 0

    for block in blocks:
        if block["type"] == "image":
            flush()
            pages.append({"kind": "image", "path": block["path"]})
            continue
        piece = block["text"] if block["type"] == "text" else render_rk_table_block(block)
        if current_parts and current_len + 2 + len(piece) > PHYS_RK_PAGE_CHAR_BUDGET:
            flush()
        current_parts.append(piece)
        current_len += len(piece) + 2
    flush()
    return pages


# Кэш Telegram file_id для картинок рубежных контролей — тот же паттерн, что
# ANATOMY_FILE_ID_CACHE/OH_FILE_ID_CACHE (см. CLAUDE.md): без него каждый повторный показ той же
# картинки заново читает файл с диска и заливает в Telegram.
PHYS_RK_FILE_ID_CACHE_PATH = os.path.join(tb.STATS_DIR, "physiology_rk_file_id_cache.json")


def _load_phys_rk_file_id_cache() -> dict:
    try:
        with open(PHYS_RK_FILE_ID_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


PHYS_RK_FILE_ID_CACHE: dict = _load_phys_rk_file_id_cache()


def _write_phys_rk_file_id_cache(data: dict) -> None:
    tmp_path = f"{PHYS_RK_FILE_ID_CACHE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, PHYS_RK_FILE_ID_CACHE_PATH)


def save_phys_rk_file_id_cache() -> None:
    data = dict(PHYS_RK_FILE_ID_CACHE)
    future = tb._stats_executor.submit(_write_phys_rk_file_id_cache, data)
    future.add_done_callback(tb._log_stats_write_result)


def _phys_rk_image_media(path: str):
    cached = PHYS_RK_FILE_ID_CACHE.get(path)
    if cached:
        return cached
    return FSInputFile(os.path.join(PHYS_RK_IMAGES_DIR, path))


def _cache_phys_rk_file_id(path: str, sent_message) -> bool:
    if path in PHYS_RK_FILE_ID_CACHE:
        return False
    photo_sizes = getattr(sent_message, "photo", None)
    if not photo_sizes:
        return False
    PHYS_RK_FILE_ID_CACHE[path] = photo_sizes[-1].file_id
    save_phys_rk_file_id_cache()
    return True


def get_rk_menu_text() -> str:
    n = len(tb.PHYSIOLOGY.get("boundary_controls", []))
    return f"📋 <b>РУБЕЖНЫЕ КОНТРОЛИ</b>\n{tb.DIVIDER}\n\n{n} рубежных контролей кафедры. Выбери номер:"


def get_rk_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for c in tb.PHYSIOLOGY.get("boundary_controls", []):
        builder.button(text=f"📋 {c['title']}", callback_data=f"phys:rk:{c['control_id']}:0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🏠 Меню физиологии", callback_data="phys:menu"))
    return builder.as_markup()


def get_rk_page_keyboard(control_id: str, idx: int, total: int):
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"phys:rk:{control_id}:{idx - 1}"))
    if idx + 1 < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"phys:rk:{control_id}:{idx + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К рубежам", callback_data="phys:rk_menu"))
    return builder.as_markup()


async def send_rk_page(callback: CallbackQuery, control: dict, idx: int, pages: list):
    """Рендерит страницу idx (0-based) — текстовую (edit/answer) или фото (delete+answer_photo,
    тот же приём, что и другие фото-карусели раздела — см. CLAUDE.md, "hand-roll delete-and-
    resend on ⬅️/➡️"; edit_text не умеет превратить текстовое сообщение в фото и обратно)."""
    page = pages[idx]
    keyboard = get_rk_page_keyboard(control["control_id"], idx, len(pages))
    await callback.message.delete()
    if page["kind"] == "image":
        sent = await callback.message.answer_photo(
            _phys_rk_image_media(page["path"]), reply_markup=keyboard
        )
        _cache_phys_rk_file_id(page["path"], sent)
        return
    header = f"📋 <b>{esc(control['title'])}</b> ({idx + 1}/{len(pages)})\n{tb.DIVIDER}\n\n"
    await callback.message.answer(header + page["text"], parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "phys:rk_menu")
async def cb_phys_rk_menu(callback: CallbackQuery):
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_rk_menu_text(), parse_mode="HTML",
        reply_markup=get_rk_menu_keyboard()
    )


@router.callback_query(F.data.startswith("phys:rk:"))
async def cb_phys_rk_page(callback: CallbackQuery):
    parts = callback.data.split(":")
    control_id, idx = parts[2], int(parts[3])
    control = get_rk_control(control_id)
    if control is None:
        await callback.answer("Рубежный контроль не найден", show_alert=True)
        return
    pages = build_rk_pages(control["blocks"])
    if not (0 <= idx < len(pages)):
        await callback.answer("Страница не найдена", show_alert=True)
        return
    await callback.answer()
    await send_rk_page(callback, control, idx, pages)


# ==================== handlers ====================

@router.callback_query(F.data == "phys:menu")
async def cb_phys_menu(callback: CallbackQuery):
    await callback.answer()
    tb.PHYS_SEARCH_PENDING.discard(callback.from_user.id)
    user_id = callback.from_user.id
    await tb.safe_edit_text(
        callback.message, get_phys_menu_text(user_id), parse_mode="HTML",
        reply_markup=get_phys_menu_keyboard(user_id)
    )


@router.callback_query(F.data == "phys:continue")
async def cb_phys_continue(callback: CallbackQuery):
    user_id = callback.from_user.id
    topic_id = phys_next_topic_for_continue(user_id)
    topic = get_phys_topic(topic_id)
    await callback.answer()
    phys_mark_opened(user_id, topic_id, len(build_phys_learn_cards(topic)))
    await tb.safe_edit_text(
        callback.message, get_phys_topic_text(topic, user_id), parse_mode="HTML",
        reply_markup=get_phys_topic_keyboard(topic, user_id)
    )


@router.callback_query(F.data.startswith("phys:topics:"))
async def cb_phys_topics(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_topics_text(page), parse_mode="HTML",
        reply_markup=get_phys_topics_keyboard(page, callback.from_user.id, target="topic")
    )


@router.callback_query(F.data.startswith("phys:qpick:"))
async def cb_phys_qpick(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, "⚡ <b>Быстрый повтор — выбери тему</b>\n" + tb.DIVIDER, parse_mode="HTML",
        reply_markup=get_phys_topics_keyboard(page, callback.from_user.id, target="quick")
    )


@router.callback_query(F.data.startswith("phys:zpick:"))
async def cb_phys_zpick(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, "🎯 <b>Проверить себя — выбери тему</b>\n" + tb.DIVIDER, parse_mode="HTML",
        reply_markup=get_phys_topics_keyboard(page, callback.from_user.id, target="quiz")
    )


@router.callback_query(F.data.startswith("phys:topic:"))
async def cb_phys_topic(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    user_id = callback.from_user.id
    phys_mark_opened(user_id, topic_id, len(build_phys_learn_cards(topic)))
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_topic_text(topic, user_id), parse_mode="HTML",
        reply_markup=get_phys_topic_keyboard(topic, user_id)
    )


@router.callback_query(F.data.startswith("phys:fav_toggle:"))
async def cb_phys_fav_toggle(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    user_id = callback.from_user.id
    added = phys_toggle_favorite(user_id, topic_id)
    await callback.answer("Добавлено в избранное" if added else "Убрано из избранного")
    await tb.safe_edit_text(
        callback.message, get_phys_topic_text(topic, user_id), parse_mode="HTML",
        reply_markup=get_phys_topic_keyboard(topic, user_id)
    )


@router.callback_query(F.data.startswith("phys:learn:"))
async def cb_phys_learn(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, idx = parts[2], int(parts[3])
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    cards = build_phys_learn_cards(topic)
    if not (0 <= idx < len(cards)):
        await callback.answer("Карточка не найдена", show_alert=True)
        return
    user_id = callback.from_user.id
    phys_mark_opened(user_id, topic_id, len(cards))
    await callback.answer()
    card = cards[idx]
    await tb.safe_edit_text(
        callback.message, render_phys_learn_card(topic, card), parse_mode="HTML",
        reply_markup=get_phys_learn_keyboard(topic_id, idx, len(cards), card["kind"])
    )


@router.callback_query(F.data.startswith("phys:learn_ok:"))
async def cb_phys_learn_ok(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, idx = parts[2], int(parts[3])
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    cards = build_phys_learn_cards(topic)
    user_id = callback.from_user.id
    phys_mark_card_done(user_id, topic_id)
    await callback.answer("Отмечено ✅")
    next_idx = idx + 1
    if next_idx >= len(cards):
        await tb.safe_edit_text(
            callback.message, get_phys_topic_text(topic, user_id), parse_mode="HTML",
            reply_markup=get_phys_topic_keyboard(topic, user_id)
        )
        return
    card = cards[next_idx]
    await tb.safe_edit_text(
        callback.message, render_phys_learn_card(topic, card), parse_mode="HTML",
        reply_markup=get_phys_learn_keyboard(topic_id, next_idx, len(cards), card["kind"])
    )


@router.callback_query(F.data.startswith("phys:read:"))
async def cb_phys_read(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, idx = parts[2], int(parts[3])
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    if not (0 <= idx < len(topic["sections"])):
        await callback.answer("Страница не найдена", show_alert=True)
        return
    phys_mark_opened(callback.from_user.id, topic_id, len(build_phys_learn_cards(topic)))
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_read_text(topic, idx), parse_mode="HTML",
        reply_markup=get_phys_read_keyboard(topic_id, idx, len(topic["sections"]))
    )


@router.callback_query(F.data.startswith("phys:quick:"))
async def cb_phys_quick(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_quick_text(topic), parse_mode="HTML",
        reply_markup=get_phys_quick_keyboard(topic_id)
    )


@router.callback_query(F.data.startswith("phys:chains:"))
async def cb_phys_chains(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, idx = parts[2], int(parts[3])
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    chains = build_phys_chains(topic)
    if not chains or not (0 <= idx < len(chains)):
        await callback.answer("Цепочки не найдены", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_chain_text(topic, idx, chains), parse_mode="HTML",
        reply_markup=get_phys_chain_keyboard(topic_id, idx, len(chains))
    )


@router.callback_query(F.data.startswith("phys:cmp:"))
async def cb_phys_cmp(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, idx = parts[2], int(parts[3])
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    if not topic["comparisons"] or not (0 <= idx < len(topic["comparisons"])):
        await callback.answer("Сравнения не найдены", show_alert=True)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_cmp_text(topic, idx), parse_mode="HTML",
        reply_markup=get_phys_cmp_keyboard(topic_id, idx, len(topic["comparisons"]))
    )


@router.callback_query(F.data.startswith("phys:quiz_start:"))
async def cb_phys_quiz_start(callback: CallbackQuery):
    topic_id = callback.data.split(":")[2]
    topic = get_phys_topic(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    user_id = callback.from_user.id
    if not start_phys_quiz_session(user_id, topic_id):
        await callback.answer(
            "Для этой темы пока нет вопросов — исходник не даёт достаточно структурированных "
            "фактов для честного банка вопросов. Загляни в «❓ Контрольные вопросы» на экране темы.",
            show_alert=True
        )
        return
    session = PHYS_QUIZ_SESSIONS[user_id]
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, render_phys_quiz_question(session), parse_mode="HTML",
        reply_markup=get_phys_quiz_question_keyboard(topic_id, session["queue"][0]["options"])
    )


@router.callback_query(F.data.startswith("phys:quiz_answer:"))
async def cb_phys_quiz_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = PHYS_QUIZ_SESSIONS.get(user_id)
    if session is None:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    chosen_idx = int(callback.data.split(":")[2])
    q = session["queue"][session["index"]]
    if not (0 <= chosen_idx < len(q["options"])):
        await callback.answer("Некорректный ответ", show_alert=True)
        return
    correct = q["options"][chosen_idx] == q["correct_answer"]
    if correct:
        session["correct"] += 1
    else:
        session["wrong"] += 1
    phys_record_quiz_answer(user_id, session["topic_id"], q["type"], correct)
    await callback.answer("✅ Верно!" if correct else "❌ Неверно")
    is_last = session["index"] + 1 >= len(session["queue"])
    await tb.safe_edit_text(
        callback.message, render_phys_quiz_answer(q, chosen_idx), parse_mode="HTML",
        reply_markup=get_phys_quiz_answer_keyboard(is_last)
    )


@router.callback_query(F.data == "phys:quiz_next")
async def cb_phys_quiz_next(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = PHYS_QUIZ_SESSIONS.get(user_id)
    if session is None:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    session["index"] += 1
    if session["index"] >= len(session["queue"]):
        await finish_phys_quiz(callback, aborted=False)
        return
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, render_phys_quiz_question(session), parse_mode="HTML",
        reply_markup=get_phys_quiz_question_keyboard(session["topic_id"], session["queue"][session["index"]]["options"])
    )


@router.callback_query(F.data == "phys:quiz_stop")
async def cb_phys_quiz_stop(callback: CallbackQuery):
    await finish_phys_quiz(callback, aborted=True)


@router.callback_query(F.data.startswith("phys:mini:"))
async def cb_phys_mini(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, back_idx = parts[2], int(parts[3])
    pool = get_phys_topic_quiz_pool(topic_id)
    if not pool:
        await callback.answer("Вопросов пока нет", show_alert=True)
        return
    q = random.choice(pool)
    await callback.answer()
    options = "\n".join(f"{i}. {esc(o)}" for i, o in enumerate(q["options"], 1))
    text = f"❓ <b>Мини-проверка</b>\n{tb.DIVIDER}\n\n{esc(q['prompt'])}\n\n{options}"
    # stash the question on the fly via callback_data-encoded index into the pool is unsafe (pool
    # order isn't stable across requests) — instead re-derive by matching question_id in the answer handler
    builder = InlineKeyboardBuilder()
    for i, opt in enumerate(q["options"]):
        builder.button(text=str(i + 1), callback_data=f"phys:mini_answer:{topic_id}:{back_idx}:{q['question_id']}:{i}")
    builder.adjust(4)
    await tb.safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("phys:mini_answer:"))
async def cb_phys_mini_answer(callback: CallbackQuery):
    parts = callback.data.split(":")
    topic_id, question_id, chosen_idx = parts[2], parts[4], int(parts[5])
    q = next((x for x in tb.PHYSIOLOGY["quiz_questions"] if x["question_id"] == question_id), None)
    topic = get_phys_topic(topic_id)
    if q is None or topic is None:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    correct = q["options"][chosen_idx] == q["correct_answer"]
    phys_record_quiz_answer(callback.from_user.id, topic_id, q["type"], correct)
    await callback.answer("✅ Верно!" if correct else "❌ Неверно")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏠 В тему", callback_data=f"phys:topic:{topic_id}"))
    await tb.safe_edit_text(
        callback.message, render_phys_quiz_answer(q, chosen_idx), parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "phys:favorites")
async def cb_phys_favorites(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_favorites_text(user_id), parse_mode="HTML",
        reply_markup=get_phys_favorites_keyboard(user_id)
    )


@router.callback_query(F.data == "phys:progress")
async def cb_phys_progress(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()
    await tb.safe_edit_text(
        callback.message, get_phys_progress_text(user_id), parse_mode="HTML",
        reply_markup=get_phys_progress_keyboard()
    )


@router.callback_query(F.data == "phys:search_prompt")
async def cb_phys_search_prompt(callback: CallbackQuery):
    await callback.answer()
    tb.PHYS_SEARCH_PENDING.add(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data="phys:menu"))
    await tb.safe_edit_text(
        callback.message,
        f"🔎 <b>Поиск по Нормальной физиологии</b>\n{tb.DIVIDER}\n\n"
        "Отправь ключевое слово — поищу по темам, определениям и содержанию.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
