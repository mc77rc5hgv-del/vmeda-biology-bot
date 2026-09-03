import pytest

from web_api import static_content
from web_api.content import ContentNotFoundError


@pytest.fixture
def physiology():
    return {
        "topics": [
            {
                "topic_id": "01",
                "title": "Мембрана",
                "sections": [{"heading": "Главное", "text": "<b>Ионные каналы</b>"}],
                "deepening": [{"heading": "Проверка", "text": "Почему возникает потенциал?"}],
            },
            {"topic_id": "02", "title": "Синапс", "sections": [], "deepening": []},
        ],
        "boundary_controls": [
            {
                "control_id": "rk_01",
                "title": "Рубежный контроль 1",
                "blocks": [
                    {"type": "text", "text": "Вопрос <не HTML>"},
                    {"type": "image", "path": "rk_01/media/scheme.jpeg"},
                    {"type": "table", "caption": "Таблица", "rows": [["A", "B"], ["1", "2"]]},
                ],
            }
        ],
    }


def test_physiology_summary_and_sections_use_real_counts(physiology):
    detail = static_content.get_subject_detail(physiology, "physiology")
    assert detail["title"] == "Нормальная физиология"
    assert [(s["id"], s["kind"]) for s in detail["sections"]] == [
        ("course", "flat"),
        ("boundary-controls", "grouped"),
    ]
    assert detail["sections"][0]["item_count"] == 2
    assert detail["sections"][1]["item_count"] == 3


def test_course_material_keeps_structure_and_navigation(physiology):
    material = static_content.get_material(physiology, "physiology", "course", "01")
    assert material["next_id"] == "02"
    assert material["prev_id"] is None
    assert "<strong>Главное</strong>" in material["content_html"]
    assert "<b>Ионные каналы</b>" in material["content_html"]
    assert material["sources"] == []


def test_boundary_control_is_paginated_and_escapes_plain_text(physiology):
    group = static_content.get_group_detail(physiology, "physiology", "boundary-controls", "rk_01")
    assert len(group["items"]) == 3

    text_page = static_content.get_material(
        physiology, "physiology", "boundary-controls", group["items"][0]["id"]
    )
    image_page = static_content.get_material(
        physiology, "physiology", "boundary-controls", group["items"][1]["id"]
    )
    assert "&lt;не HTML&gt;" in text_page["content_html"]
    assert image_page["media"][0]["path"] == (
        "images/physiology/boundary_controls/rk_01/media/scheme.jpeg"
    )
    assert image_page["group_id"] == "rk_01"


def test_unknown_static_content_is_not_found(physiology):
    with pytest.raises(ContentNotFoundError):
        static_content.get_subject_detail(physiology, "unknown")
    with pytest.raises(ContentNotFoundError):
        static_content.get_group_detail(physiology, "physiology", "course", "rk_01")
