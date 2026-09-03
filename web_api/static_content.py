"""Адаптер статичных предметов к общему контентному контракту Mini App.

Подключаются постепенно (см. отчёт аудита Этапа 1 — у каждого статичного предмета своя,
непохожая на остальные схема, общего адаптера для всех сразу нет и не планируется). Каждый
подключённый предмет — это НЕ весь объём контента бота по этому предмету, а осознанно
ограниченный, но честный срез: то же соотношение, что и у Биохимии/Фармакологии/Латыни/
Правоведения через content.py — реальный текст, ничего не придумано, но не 1:1 копия
навигации бота (у бота, например, тема Оперативной хирургии режется на постранично пролистываемые
подтемы под лимит сообщения Telegram — у Mini App лимита сообщения нет, поэтому тема отдаётся
одной страницей).

Подключены: «Нормальная физиология» (23 темы курса + 11 рубежных контролей), «Оперативная
хирургия» (61 тема в 4 томах — БЕЗ инструментов/проекций/станций/контрольных вопросов, это
отдельная задача на будущее) и «Анатомия» (107 тем в 10 модулях — только непрерывный текст
material[], БЕЗ флеш-карточек/сопоставления/мнемоник/картиночных тестов/разбора по костям/атласа/
латинских терминов/экзаменационных банков — те же "честный срез" резоны, что и у Оперативной
хирургии; см. SUPPORTED_SUBJECT_IDS ниже).

В отличие от Физиологии/Оперативной хирургии (полностью бесплатные разделы бота — см. CLAUDE.md),
Анатомия внутри бота гейтится по модулям (ANATOMY_FREE_SECTIONS) и общим тех.режимом
(anatomy_maintenance_mode_enabled) — этот модуль сам НИЧЕГО не проверяет (остаётся чистой функцией
формы контента над tb.ANATOMY, как и остальные два предмета), проверка прав живёт в
web_api/routers/subjects.py (см. _anatomy_module_access_ok там), у которого есть доступ к user_id."""
from html import escape

from .content import ContentNotFoundError

PHYSIOLOGY_ID = "physiology"
OPERATIVE_SURGERY_ID = "operative_surgery"
ANATOMY_ID = "anatomy"
SUPPORTED_SUBJECT_IDS = {PHYSIOLOGY_ID, OPERATIVE_SURGERY_ID, ANATOMY_ID}
ANATOMY_SECTION_ID = "course"

PHYSIOLOGY_PAGE_CHAR_BUDGET = 6_000


def list_subject_summaries(tb) -> list[dict]:
    summaries = []
    if tb.PHYSIOLOGY:
        summaries.append({
            "id": PHYSIOLOGY_ID,
            "title": "Нормальная физиология",
            "emoji": "🫀",
            "description": "Структурированный курс, тесты и рубежные контроли",
            "course": 2,
            "has_ai": True,
        })
    if tb.OPERATIVE_SURGERY:
        summaries.append({
            "id": OPERATIVE_SURGERY_ID,
            "title": "Оперативная хирургия",
            "emoji": "🔪",
            "description": "61 тема в 4 томах — топографическая анатомия и оперативная техника",
            "course": 2,
            "has_ai": True,
        })
    if tb.ANATOMY:
        summaries.append({
            "id": ANATOMY_ID,
            "title": "Анатомия",
            "emoji": "🦴",
            "description": "107 тем в 10 модулях — часть открыта всем, часть по подписке",
            "course": 1,
            "has_ai": True,
        })
    return summaries


def _summary_by_id(tb, subject_id: str) -> dict:
    for summary in list_subject_summaries(tb):
        if summary["id"] == subject_id:
            return summary
    raise ContentNotFoundError(f"статичный предмет {subject_id!r} не найден")


def get_subject_detail(tb, subject_id: str) -> dict:
    summary = _summary_by_id(tb, subject_id)
    if subject_id == ANATOMY_ID:
        total_topics = sum(len(module.get("topics", {})) for module in tb.ANATOMY.values())
        summary["sections"] = [
            {"id": ANATOMY_SECTION_ID, "title": "Курс", "item_count": total_topics, "kind": "grouped"},
        ]
        return summary

    if subject_id == PHYSIOLOGY_ID:
        physiology = tb.PHYSIOLOGY
        summary["sections"] = [
            {
                "id": "course",
                "title": "Курс",
                "item_count": len(physiology.get("topics", [])),
                "kind": "flat",
            },
            {
                "id": "boundary-controls",
                "title": "Рубежные контроли",
                "item_count": sum(
                    len(_boundary_control_pages(control))
                    for control in physiology.get("boundary_controls", [])
                ),
                "kind": "grouped",
            },
        ]
        return summary

    # operative_surgery
    oh = tb.OPERATIVE_SURGERY
    summary["sections"] = [
        {
            "id": "volumes",
            "title": "Тома",
            "item_count": len(oh.get("topics", [])),
            "kind": "grouped",
        },
    ]
    return summary


def get_section_detail(tb, subject_id: str, section_id: str) -> dict:
    _summary_by_id(tb, subject_id)  # бросает ContentNotFoundError на неизвестный subject_id

    if subject_id == ANATOMY_ID:
        if section_id != ANATOMY_SECTION_ID:
            raise ContentNotFoundError(f"раздел {section_id!r} не найден в анатомии")
        return {
            "id": section_id,
            "title": "Курс",
            "kind": "grouped",
            "groups": [
                {"id": module_key, "title": module["title"], "item_count": len(module.get("topics", {}))}
                for module_key, module in tb.ANATOMY.items()
            ],
        }

    if subject_id == PHYSIOLOGY_ID:
        physiology = tb.PHYSIOLOGY
        if section_id == "course":
            topics = physiology.get("topics", [])
            total = len(topics)
            return {
                "id": section_id,
                "title": "Курс",
                "kind": "flat",
                "items": [
                    {"id": topic["topic_id"], "title": topic["title"], "order": index + 1, "total": total}
                    for index, topic in enumerate(topics)
                ],
            }
        if section_id == "boundary-controls":
            return {
                "id": section_id,
                "title": "Рубежные контроли",
                "kind": "grouped",
                "groups": [
                    {
                        "id": control["control_id"],
                        "title": control["title"],
                        "item_count": len(_boundary_control_pages(control)),
                    }
                    for control in physiology.get("boundary_controls", [])
                ],
            }
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в физиологии")

    # operative_surgery
    if section_id != "volumes":
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в оперативной хирургии")
    return {
        "id": section_id,
        "title": "Тома",
        "kind": "grouped",
        "groups": [
            {"id": volume["id"], "title": volume["title"], "item_count": len(volume.get("topic_ids", []))}
            for volume in tb.OPERATIVE_SURGERY.get("volumes", [])
        ],
    }


def get_group_detail(tb, subject_id: str, section_id: str, group_id: str) -> dict:
    _summary_by_id(tb, subject_id)

    if subject_id == ANATOMY_ID:
        if section_id != ANATOMY_SECTION_ID:
            raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
        module = tb.ANATOMY.get(group_id)
        if module is None:
            raise ContentNotFoundError(f"модуль {group_id!r} не найден в анатомии")
        topics = module.get("topics", {})
        total = len(topics)
        return {
            "id": group_id,
            "title": module["title"],
            "items": [
                {"id": topic_key, "title": topic["title"], "order": index + 1, "total": total}
                for index, (topic_key, topic) in enumerate(topics.items())
            ],
        }

    if subject_id == PHYSIOLOGY_ID:
        if section_id != "boundary-controls":
            raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
        control = _find_physiology_control(tb.PHYSIOLOGY, group_id)
        pages = _boundary_control_pages(control)
        total = len(pages)
        return {
            "id": group_id,
            "title": control["title"],
            "items": [
                {"id": page["id"], "title": page["title"], "order": index + 1, "total": total}
                for index, page in enumerate(pages)
            ],
        }

    # operative_surgery
    if section_id != "volumes":
        raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
    volume = _find_oh_volume(tb.OPERATIVE_SURGERY, group_id)
    topics = _oh_volume_topics(tb.OPERATIVE_SURGERY, volume)
    total = len(topics)
    return {
        "id": volume["id"],
        "title": volume["title"],
        "items": [
            {"id": topic["id"], "title": f"{topic['number']}. {topic['title']}", "order": index + 1, "total": total}
            for index, topic in enumerate(topics)
        ],
    }


def get_material(tb, subject_id: str, section_id: str, item_id: str) -> dict:
    _summary_by_id(tb, subject_id)

    if subject_id == ANATOMY_ID:
        return _anatomy_material(tb.ANATOMY, section_id, item_id)
    if subject_id == PHYSIOLOGY_ID:
        return _physiology_material(tb.PHYSIOLOGY, section_id, item_id)
    return _operative_surgery_material(tb.OPERATIVE_SURGERY, section_id, item_id)


# ==================== Нормальная физиология ====================

def _physiology_material(physiology: dict, section_id: str, item_id: str) -> dict:
    if section_id == "course":
        topics = physiology.get("topics", [])
        for index, topic in enumerate(topics):
            if topic.get("topic_id") == item_id:
                return {
                    "id": item_id,
                    "title": topic["title"],
                    "content_html": _physiology_topic_html(topic),
                    "sources": [],
                    "order": index + 1,
                    "total": len(topics),
                    "group_id": None,
                    "prev_id": topics[index - 1]["topic_id"] if index > 0 else None,
                    "next_id": topics[index + 1]["topic_id"] if index + 1 < len(topics) else None,
                    "media": [],
                }
        raise ContentNotFoundError(f"тема {item_id!r} не найдена в физиологии")

    if section_id == "boundary-controls":
        for control in physiology.get("boundary_controls", []):
            pages = _boundary_control_pages(control)
            for index, page in enumerate(pages):
                if page["id"] == item_id:
                    return {
                        **page,
                        "sources": [],
                        "order": index + 1,
                        "total": len(pages),
                        "group_id": control["control_id"],
                        "prev_id": pages[index - 1]["id"] if index > 0 else None,
                        "next_id": pages[index + 1]["id"] if index + 1 < len(pages) else None,
                    }
        raise ContentNotFoundError(f"страница {item_id!r} не найдена в рубежных контролях")

    raise ContentNotFoundError(f"раздел {section_id!r} не найден в физиологии")


def _find_physiology_control(physiology: dict, control_id: str) -> dict:
    for control in physiology.get("boundary_controls", []):
        if control.get("control_id") == control_id:
            return control
    raise ContentNotFoundError(f"рубежный контроль {control_id!r} не найден")


def _physiology_topic_html(topic: dict) -> str:
    parts = []
    for section in [*topic.get("sections", []), *topic.get("deepening", [])]:
        heading = escape(str(section.get("heading", "Раздел")))
        body = str(section.get("text", "")).strip()
        if body:
            parts.extend((f"<p><strong>{heading}</strong></p>", f"<p>{body}</p>"))
    return "\n".join(parts)


def _table_text(block: dict) -> str:
    lines = [str(block.get("caption", "Таблица"))]
    lines.extend(" | ".join(str(cell) for cell in row) for row in block.get("rows", []))
    return "\n".join(lines)


def _boundary_control_pages(control: dict) -> list[dict]:
    pages: list[dict] = []
    text_parts: list[str] = []
    text_length = 0

    def flush_text() -> None:
        nonlocal text_parts, text_length
        if not text_parts:
            return
        pages.append({"content_html": f"<p>{escape(chr(10).join(text_parts))}</p>", "media": []})
        text_parts = []
        text_length = 0

    for block in control.get("blocks", []):
        block_type = block.get("type")
        if block_type == "image":
            flush_text()
            relative_path = str(block.get("path", ""))
            pages.append(
                {
                    "content_html": "<p>Учебная схема к рубежному контролю.</p>",
                    "media": [
                        {
                            "path": f"images/physiology/boundary_controls/{relative_path}",
                            "caption": "Учебная схема",
                        }
                    ],
                }
            )
            continue
        piece = str(block.get("text", "")) if block_type == "text" else _table_text(block)
        if text_parts and text_length + len(piece) + 2 > PHYSIOLOGY_PAGE_CHAR_BUDGET:
            flush_text()
        text_parts.append(piece)
        text_length += len(piece) + 2
    flush_text()

    total = len(pages)
    for index, page in enumerate(pages):
        page["id"] = f"{control['control_id']}_page_{index + 1}"
        page["title"] = f"{control['title']} — часть {index + 1} из {total}"
    return pages


# ==================== Оперативная хирургия ====================
# Подключён только раздел «Тома» (61 тема, реальный текст subtopics). instrument_groups/
# projections/practical_stations/control_questions НЕ подключены в этом заходе -- честный срез,
# не весь объём бота по этому предмету (см. docstring модуля).

def _find_oh_volume(oh: dict, volume_id: str) -> dict:
    for volume in oh.get("volumes", []):
        if volume.get("id") == volume_id:
            return volume
    raise ContentNotFoundError(f"том {volume_id!r} не найден в оперативной хирургии")


def _oh_topics_by_id(oh: dict) -> dict[str, dict]:
    return {topic["id"]: topic for topic in oh.get("topics", [])}


def _oh_volume_topics(oh: dict, volume: dict) -> list[dict]:
    """Порядок берётся из volume["topic_ids"] (собственный порядок источника), а не из фильтрации
    topics по полю volume -- volumes[].topic_ids это явный, авторский порядок тем внутри тома."""
    topics_by_id = _oh_topics_by_id(oh)
    return [topics_by_id[tid] for tid in volume.get("topic_ids", []) if tid in topics_by_id]


def _oh_topic_html(topic: dict) -> str:
    parts = []
    for subtopic in topic.get("subtopics", []):
        heading = escape(str(subtopic.get("title", "")))
        body = str(subtopic.get("text", "")).strip()
        if body:
            parts.extend((f"<p><strong>{heading}</strong></p>", f"<p>{body}</p>"))
    return "\n".join(parts)


def _operative_surgery_material(oh: dict, section_id: str, item_id: str) -> dict:
    if section_id != "volumes":
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в оперативной хирургии")

    topics_by_id = _oh_topics_by_id(oh)
    topic = topics_by_id.get(item_id)
    if topic is None:
        raise ContentNotFoundError(f"тема {item_id!r} не найдена в оперативной хирургии")
    volume = _find_oh_volume(oh, topic["volume"])
    siblings = _oh_volume_topics(oh, volume)
    index = next(i for i, t in enumerate(siblings) if t["id"] == item_id)

    return {
        "id": item_id,
        "title": f"{topic['number']}. {topic['title']}",
        "content_html": _oh_topic_html(topic),
        "sources": [topic["source"]] if topic.get("source") else [],
        "order": index + 1,
        "total": len(siblings),
        "group_id": volume["id"],
        "prev_id": siblings[index - 1]["id"] if index > 0 else None,
        "next_id": siblings[index + 1]["id"] if index + 1 < len(siblings) else None,
        "media": [],
    }


# ==================== Анатомия ====================
# Подключён только раздел «Курс» (107 тем в 10 модулях, реальный текст topic["material"]).
# flashcards/matching_sets/mnemonics/picture_quiz/bones_list (разбор по костям)/bone_images/
# atlas_images/latin_terms/экзаменационные банки (ТЕСТ, практика, теория) НЕ подключены в этом
# заходе — честный срез, не весь объём бота по этому предмету (см. docstring модуля). Права
# доступа (модуль бесплатный/по подписке, тех.режим) здесь НЕ проверяются — см. docstring модуля.

ANATOMY_EMPTY_MATERIAL_NOTE = "<p>Материал по этой теме пока не добавлен.</p>"


def _anatomy_find_topic(anatomy: dict, topic_id: str) -> tuple[str, dict, dict]:
    """Возвращает (module_key, module, topic). ANATOMY — dict секций -> dict тем (не список), тема
    ищется перебором модулей — то же самое, что делает handlers/anatomy.py::get_anatomy_topic_data,
    просто с модулем в возврате (он нужен и здесь, и в web_api/routers/subjects.py для гейта)."""
    for module_key, module in anatomy.items():
        topic = module.get("topics", {}).get(topic_id)
        if topic is not None:
            return module_key, module, topic
    raise ContentNotFoundError(f"тема {topic_id!r} не найдена в анатомии")


def _anatomy_topic_html(topic: dict) -> str:
    material = topic.get("material") or []
    parts = []
    for entry in material:
        title = entry.get("title")
        body = str(entry.get("content", "")).strip()
        if not body:
            continue
        if title:
            parts.append(f"<p><strong>{escape(str(title))}</strong></p>")
        parts.append(f"<p>{body}</p>")
    return "\n".join(parts) if parts else ANATOMY_EMPTY_MATERIAL_NOTE


def _anatomy_material(anatomy: dict, section_id: str, item_id: str) -> dict:
    if section_id != ANATOMY_SECTION_ID:
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в анатомии")

    module_key, module, topic = _anatomy_find_topic(anatomy, item_id)
    topics = module.get("topics", {})
    topic_keys = list(topics.keys())
    index = topic_keys.index(item_id)

    return {
        "id": item_id,
        "title": topic["title"],
        "content_html": _anatomy_topic_html(topic),
        "sources": [],
        "order": index + 1,
        "total": len(topic_keys),
        "group_id": module_key,
        "prev_id": topic_keys[index - 1] if index > 0 else None,
        "next_id": topic_keys[index + 1] if index + 1 < len(topic_keys) else None,
        "media": [],
    }
