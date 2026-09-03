import pytest

from web_api.content import (
    ContentNotFoundError,
    find_dynamic_course,
    get_group_detail,
    get_material,
    get_section_detail,
    get_subject_detail,
)

FIXTURE_COURSES = [
    {
        "id": "biochemistry",
        "course": 2,
        "title": "Биохимия",
        "emoji": "🧫",
        "description": "Полный курс биохимии",
        "sections": [
            {
                "id": "core_course",
                "title": "Основной курс",
                "lessons": [
                    {"id": "core_p1_1", "title": "Тема 1", "content": "<b>Текст 1</b>", "sources": ["учебник, стр. 1"]},
                    {"id": "core_p2_1", "title": "Тема 2", "content": "<b>Текст 2</b>", "sources": ["учебник, стр. 2"],
                     "media": [{"path": "images/biochemistry/p2.jpg", "caption": "Схема"}]},
                ],
            },
        ],
    },
    {
        "id": "pharmacology",
        "course": 2,
        "title": "Фармакология",
        "emoji": "💊",
        "ai_mode": "pharmacology",
        "show_sources": False,
        "sections": [
            {
                "id": "course",
                "title": "Курс",
                "groups": [
                    {
                        "id": "foundations",
                        "title": "Общая фармакология",
                        "lessons": [
                            {"id": "found_1", "title": "Введение", "content": "<b>Введение</b>", "sources": ["секретный источник"]},
                        ],
                    },
                    {
                        "id": "drug_groups",
                        "title": "Группы препаратов",
                        "lessons": [
                            {"id": "dg_1", "title": "Антибиотики", "content": "<b>Антибиотики</b>"},
                            {"id": "dg_2", "title": "Анальгетики", "content": "<b>Анальгетики</b>"},
                        ],
                    },
                ],
            },
        ],
    },
]


def test_find_dynamic_course():
    index, course = find_dynamic_course(FIXTURE_COURSES, "pharmacology")
    assert index == 1
    assert course["title"] == "Фармакология"


def test_find_dynamic_course_not_found():
    with pytest.raises(ContentNotFoundError):
        find_dynamic_course(FIXTURE_COURSES, "nonexistent")


def test_subject_detail_flat_section():
    detail = get_subject_detail(FIXTURE_COURSES, "biochemistry")
    assert detail["title"] == "Биохимия"
    assert detail["has_ai"] is False
    assert len(detail["sections"]) == 1
    section = detail["sections"][0]
    assert section["kind"] == "flat"
    assert section["item_count"] == 2


def test_subject_detail_grouped_section():
    detail = get_subject_detail(FIXTURE_COURSES, "pharmacology")
    assert detail["has_ai"] is True
    section = detail["sections"][0]
    assert section["kind"] == "grouped"
    assert section["item_count"] == 3  # 1 + 2 lessons across both groups


def test_section_detail_flat():
    section = get_section_detail(FIXTURE_COURSES, "biochemistry", "core_course")
    assert section["kind"] == "flat"
    assert [item["id"] for item in section["items"]] == ["core_p1_1", "core_p2_1"]
    assert section["items"][0]["order"] == 1
    assert section["items"][0]["total"] == 2


def test_section_detail_grouped():
    section = get_section_detail(FIXTURE_COURSES, "pharmacology", "course")
    assert section["kind"] == "grouped"
    assert [g["id"] for g in section["groups"]] == ["foundations", "drug_groups"]
    assert section["groups"][1]["item_count"] == 2


def test_group_detail():
    group = get_group_detail(FIXTURE_COURSES, "pharmacology", "course", "drug_groups")
    assert group["title"] == "Группы препаратов"
    assert [item["id"] for item in group["items"]] == ["dg_1", "dg_2"]


def test_group_detail_not_found():
    with pytest.raises(ContentNotFoundError):
        get_group_detail(FIXTURE_COURSES, "pharmacology", "course", "nonexistent")


def test_material_flat_section_includes_sources_and_media():
    material = get_material(FIXTURE_COURSES, "biochemistry", "core_course", "core_p2_1")
    assert material["title"] == "Тема 2"
    assert material["content_html"] == "<b>Текст 2</b>"
    assert material["sources"] == ["учебник, стр. 2"]
    assert material["order"] == 2
    assert material["total"] == 2
    assert material["group_id"] is None
    assert material["media"] == [{"path": "images/biochemistry/p2.jpg", "caption": "Схема"}]


def test_material_grouped_section_finds_across_groups():
    """item_id уникален в пределах раздела -- не нужно знать group_id заранее (см. docstring
    get_material в content.py)."""
    material = get_material(FIXTURE_COURSES, "pharmacology", "course", "dg_1")
    assert material["title"] == "Антибиотики"
    assert material["group_id"] == "drug_groups"
    assert material["order"] == 1
    assert material["total"] == 2


def test_material_respects_show_sources_false():
    """У Фармакологии show_sources=False -- источники не должны утекать в ответ API, даже если
    они есть в исходных данных (см. handlers/dynamic_courses.py: та же логика на стороне бота)."""
    material = get_material(FIXTURE_COURSES, "pharmacology", "course", "found_1")
    assert material["sources"] == []


def test_material_not_found():
    with pytest.raises(ContentNotFoundError):
        get_material(FIXTURE_COURSES, "biochemistry", "core_course", "nonexistent")


def test_material_wrong_section_not_found():
    with pytest.raises(ContentNotFoundError):
        get_section_detail(FIXTURE_COURSES, "biochemistry", "nonexistent_section")
