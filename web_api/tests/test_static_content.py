import pytest

from web_api import static_content
from web_api.content import ContentNotFoundError


class FakeTb:
    """static_content.py принимает "tb-подобный" объект (см. web_api/bot_state.py -- в реальном
    коде это модуль telegram_bot), а не сырые словари напрямую, потому что теперь оно отвечает
    сразу за несколько статичных предметов (Физиология + Оперативная хирургия) и само решает,
    какой атрибут прочитать. Тесты собирают минимальную заглушку с ровно теми двумя атрибутами."""

    def __init__(self, physiology=None, operative_surgery=None):
        self.PHYSIOLOGY = physiology or {}
        self.OPERATIVE_SURGERY = operative_surgery or {}


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


@pytest.fixture
def operative_surgery():
    return {
        "volumes": [
            {"id": "I", "title": "Общая оперативная техника и конечности", "topic_ids": ["01", "02"]},
            {"id": "II", "title": "Голова и шея", "topic_ids": ["12"]},
        ],
        "topics": [
            {
                "id": "01",
                "number": 1,
                "volume": "I",
                "title": "Общая оперативная техника",
                "source": "Практикум ВМедА 2017, стр. 5",
                "subtopics": [
                    {"id": "1.1", "title": "Доступ", "text": "<b>Оперативный доступ</b> — путь к органу."},
                    {"id": "1.2", "title": "Приём", "text": "Основное действие операции."},
                ],
            },
            {
                "id": "02",
                "number": 2,
                "volume": "I",
                "title": "Инструментарий",
                "source": None,
                "subtopics": [{"id": "2.1", "title": "Общие сведения", "text": "Классификация инструментов."}],
            },
            {
                "id": "12",
                "number": 12,
                "volume": "II",
                "title": "Топография шеи",
                "source": "Практикум ВМедА 2017, стр. 40",
                "subtopics": [{"id": "12.1", "title": "Треугольники шеи", "text": "Передний и задний треугольники."}],
            },
        ],
    }


def test_physiology_summary_and_sections_use_real_counts(physiology):
    tb = FakeTb(physiology=physiology)
    detail = static_content.get_subject_detail(tb, "physiology")
    assert detail["title"] == "Нормальная физиология"
    assert [(s["id"], s["kind"]) for s in detail["sections"]] == [
        ("course", "flat"),
        ("boundary-controls", "grouped"),
    ]
    assert detail["sections"][0]["item_count"] == 2
    assert detail["sections"][1]["item_count"] == 3


def test_course_material_keeps_structure_and_navigation(physiology):
    tb = FakeTb(physiology=physiology)
    material = static_content.get_material(tb, "physiology", "course", "01")
    assert material["next_id"] == "02"
    assert material["prev_id"] is None
    assert "<strong>Главное</strong>" in material["content_html"]
    assert "<b>Ионные каналы</b>" in material["content_html"]
    assert material["sources"] == []


def test_boundary_control_is_paginated_and_escapes_plain_text(physiology):
    tb = FakeTb(physiology=physiology)
    group = static_content.get_group_detail(tb, "physiology", "boundary-controls", "rk_01")
    assert len(group["items"]) == 3

    text_page = static_content.get_material(tb, "physiology", "boundary-controls", group["items"][0]["id"])
    image_page = static_content.get_material(tb, "physiology", "boundary-controls", group["items"][1]["id"])
    assert "&lt;не HTML&gt;" in text_page["content_html"]
    assert image_page["media"][0]["path"] == (
        "images/physiology/boundary_controls/rk_01/media/scheme.jpeg"
    )
    assert image_page["group_id"] == "rk_01"


def test_unknown_static_content_is_not_found(physiology):
    tb = FakeTb(physiology=physiology)
    with pytest.raises(ContentNotFoundError):
        static_content.get_subject_detail(tb, "unknown")
    with pytest.raises(ContentNotFoundError):
        static_content.get_group_detail(tb, "physiology", "course", "rk_01")


# ==================== Оперативная хирургия ====================

def test_operative_surgery_summary_and_sections(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    detail = static_content.get_subject_detail(tb, "operative_surgery")
    assert detail["title"] == "Оперативная хирургия"
    assert [(s["id"], s["kind"]) for s in detail["sections"]] == [("volumes", "grouped")]
    assert detail["sections"][0]["item_count"] == 3  # всего тем во всех томах


def test_operative_surgery_volumes_list_as_groups(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    section = static_content.get_section_detail(tb, "operative_surgery", "volumes")
    assert section["kind"] == "grouped"
    assert [(g["id"], g["item_count"]) for g in section["groups"]] == [("I", 2), ("II", 1)]


def test_operative_surgery_volume_group_lists_topics_in_source_order(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    group = static_content.get_group_detail(tb, "operative_surgery", "volumes", "I")
    assert group["title"] == "Общая оперативная техника и конечности"
    assert [item["id"] for item in group["items"]] == ["01", "02"]
    assert group["items"][0]["title"] == "1. Общая оперативная техника"


def test_operative_surgery_material_concatenates_subtopics(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    material = static_content.get_material(tb, "operative_surgery", "volumes", "01")
    assert material["title"] == "1. Общая оперативная техника"
    assert "<strong>Доступ</strong>" in material["content_html"]
    assert "<b>Оперативный доступ</b> — путь к органу." in material["content_html"]
    assert "<strong>Приём</strong>" in material["content_html"]
    assert material["sources"] == ["Практикум ВМедА 2017, стр. 5"]
    assert material["group_id"] == "I"
    assert material["order"] == 1
    assert material["total"] == 2
    assert material["prev_id"] is None
    assert material["next_id"] == "02"


def test_operative_surgery_material_without_source_has_empty_sources(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    material = static_content.get_material(tb, "operative_surgery", "volumes", "02")
    assert material["sources"] == []
    assert material["prev_id"] == "01"
    assert material["next_id"] is None  # последняя тема тома I


def test_operative_surgery_second_volume_is_independent(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    material = static_content.get_material(tb, "operative_surgery", "volumes", "12")
    assert material["group_id"] == "II"
    assert material["order"] == 1
    assert material["total"] == 1
    assert material["prev_id"] is None
    assert material["next_id"] is None


def test_operative_surgery_unknown_topic_not_found(operative_surgery):
    tb = FakeTb(operative_surgery=operative_surgery)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "operative_surgery", "volumes", "nonexistent")


def test_list_subject_summaries_includes_both_when_both_present(physiology, operative_surgery):
    tb = FakeTb(physiology=physiology, operative_surgery=operative_surgery)
    ids = {s["id"] for s in static_content.list_subject_summaries(tb)}
    assert ids == {"physiology", "operative_surgery"}


def test_list_subject_summaries_omits_missing_content():
    tb = FakeTb()  # ни PHYSIOLOGY, ни OPERATIVE_SURGERY не заданы (пустые словари)
    assert static_content.list_subject_summaries(tb) == []
