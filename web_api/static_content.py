"""Адаптер статичных предметов к общему контентному контракту Mini App.

Первым подключён предмет «Нормальная физиология»: 23 структурированные темы и 11 рубежных
контролей. Большие рубежи режутся на небольшие страницы, а изображения остаются отдельными
защищёнными media-ресурсами.
"""
from html import escape

from .content import ContentNotFoundError

PHYSIOLOGY_ID = "physiology"
PHYSIOLOGY_PAGE_CHAR_BUDGET = 6_000


def list_subject_summaries(physiology: dict) -> list[dict]:
    if not physiology:
        return []
    return [
        {
            "id": PHYSIOLOGY_ID,
            "title": "Нормальная физиология",
            "emoji": "🫀",
            "description": "Структурированный курс, тесты и рубежные контроли",
            "course": 2,
            "has_ai": True,
        }
    ]


def get_subject_detail(physiology: dict, subject_id: str) -> dict:
    _require_physiology(subject_id)
    summary = list_subject_summaries(physiology)[0]
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


def get_section_detail(physiology: dict, subject_id: str, section_id: str) -> dict:
    _require_physiology(subject_id)
    if section_id == "course":
        topics = physiology.get("topics", [])
        total = len(topics)
        return {
            "id": section_id,
            "title": "Курс",
            "kind": "flat",
            "items": [
                {
                    "id": topic["topic_id"],
                    "title": topic["title"],
                    "order": index + 1,
                    "total": total,
                }
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


def get_group_detail(physiology: dict, subject_id: str, section_id: str, group_id: str) -> dict:
    _require_physiology(subject_id)
    if section_id != "boundary-controls":
        raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
    control = _find_control(physiology, group_id)
    pages = _boundary_control_pages(control)
    total = len(pages)
    return {
        "id": group_id,
        "title": control["title"],
        "items": [
            {
                "id": page["id"],
                "title": page["title"],
                "order": index + 1,
                "total": total,
            }
            for index, page in enumerate(pages)
        ],
    }


def get_material(physiology: dict, subject_id: str, section_id: str, item_id: str) -> dict:
    _require_physiology(subject_id)
    if section_id == "course":
        topics = physiology.get("topics", [])
        for index, topic in enumerate(topics):
            if topic.get("topic_id") == item_id:
                return {
                    "id": item_id,
                    "title": topic["title"],
                    "content_html": _topic_html(topic),
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


def _require_physiology(subject_id: str) -> None:
    if subject_id != PHYSIOLOGY_ID:
        raise ContentNotFoundError(f"статичный предмет {subject_id!r} не найден")


def _find_control(physiology: dict, control_id: str) -> dict:
    for control in physiology.get("boundary_controls", []):
        if control.get("control_id") == control_id:
            return control
    raise ContentNotFoundError(f"рубежный контроль {control_id!r} не найден")


def _topic_html(topic: dict) -> str:
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
