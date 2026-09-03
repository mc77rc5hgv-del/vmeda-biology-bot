import pytest

from web_api import static_content
from web_api.content import ContentNotFoundError


class FakeTb:
    """static_content.py принимает "tb-подобный" объект (см. web_api/bot_state.py -- в реальном
    коде это модуль telegram_bot), а не сырые словари напрямую, потому что теперь оно отвечает
    сразу за несколько статичных предметов (Физиология + Оперативная хирургия + Анатомия +
    Гистология) и само решает, какой атрибут прочитать. Тесты собирают минимальную заглушку с
    ровно этими четырьмя атрибутами -- гейты доступа (Анатомия: модуль бесплатный/платный,
    тех.режим; Гистология: пробный период/подписка/рефералы) сюда НЕ входят, они живут в
    web_api/routers/subjects.py (см. test_subjects_integration.py и test_access.py) и требуют
    user_id, которого у чистых функций формы контента здесь нет."""

    def __init__(self, physiology=None, operative_surgery=None, anatomy=None, histology=None):
        self.PHYSIOLOGY = physiology or {}
        self.OPERATIVE_SURGERY = operative_surgery or {}
        self.ANATOMY = anatomy or {}
        self.HISTOLOGY = histology or {}


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
    tb = FakeTb()  # ни PHYSIOLOGY, ни OPERATIVE_SURGERY, ни ANATOMY не заданы (пустые словари)
    assert static_content.list_subject_summaries(tb) == []


# ==================== Анатомия ====================
# ANATOMY -- dict СЕКЦИЙ (не список, в отличие от OPERATIVE_SURGERY["topics"]) -> dict тем -- см.
# docstring static_content.py и handlers/anatomy.py::get_anatomy_topic_data. Гейт доступа
# (ANATOMY_FREE_SECTIONS/anatomy_maintenance_mode_enabled) сюда намеренно НЕ входит -- эти функции
# чистые над формой контента, гейт живёт в routers/subjects.py и покрыт test_subjects_integration.py.

@pytest.fixture
def anatomy():
    return {
        "module1_osteology": {
            "title": "Остеология",
            "topics": {
                "cranium_intro": {
                    "title": "Общая характеристика черепа",
                    "material": [
                        {"id": "general", "title": "Общее", "content": "<b>Череп</b> — скелет головы."},
                        {"id": "detail", "title": "Детали", "content": "Два отдела: мозговой и лицевой."},
                    ],
                },
                "empty_stub": {
                    "title": "Тема-заглушка без контента",
                    "material": [],
                },
            },
        },
        "module7_nervous": {
            "title": "Нервная система",
            "topics": {
                "brain_intro": {"title": "Общий план строения мозга", "material": [
                    {"id": "p1", "title": None, "content": "Головной мозг располагается в полости черепа."},
                ]},
            },
        },
    }


def test_anatomy_summary_and_sections_use_real_counts(anatomy):
    tb = FakeTb(anatomy=anatomy)
    detail = static_content.get_subject_detail(tb, "anatomy")
    assert detail["title"] == "Анатомия"
    assert detail["sections"] == [
        {"id": "course", "title": "Курс", "item_count": 3, "kind": "grouped"},
    ]


def test_anatomy_course_section_lists_modules_as_groups(anatomy):
    tb = FakeTb(anatomy=anatomy)
    section = static_content.get_section_detail(tb, "anatomy", "course")
    assert section["kind"] == "grouped"
    assert [(g["id"], g["title"], g["item_count"]) for g in section["groups"]] == [
        ("module1_osteology", "Остеология", 2),
        ("module7_nervous", "Нервная система", 1),
    ]


def test_anatomy_module_group_lists_topics_in_source_order(anatomy):
    tb = FakeTb(anatomy=anatomy)
    group = static_content.get_group_detail(tb, "anatomy", "course", "module1_osteology")
    assert group["title"] == "Остеология"
    assert [item["id"] for item in group["items"]] == ["cranium_intro", "empty_stub"]
    assert group["items"][0]["order"] == 1
    assert group["items"][0]["total"] == 2


def test_anatomy_material_concatenates_entries_with_headings(anatomy):
    tb = FakeTb(anatomy=anatomy)
    material = static_content.get_material(tb, "anatomy", "course", "cranium_intro")
    assert material["title"] == "Общая характеристика черепа"
    assert "<strong>Общее</strong>" in material["content_html"]
    assert "<b>Череп</b> — скелет головы." in material["content_html"]
    assert "<strong>Детали</strong>" in material["content_html"]
    assert material["sources"] == []
    assert material["group_id"] == "module1_osteology"
    assert material["order"] == 1
    assert material["total"] == 2
    assert material["prev_id"] is None
    assert material["next_id"] == "empty_stub"


def test_anatomy_material_without_title_skips_heading(anatomy):
    tb = FakeTb(anatomy=anatomy)
    material = static_content.get_material(tb, "anatomy", "course", "brain_intro")
    assert "<strong>" not in material["content_html"]
    assert "Головной мозг располагается в полости черепа." in material["content_html"]
    assert material["prev_id"] is None
    assert material["next_id"] is None  # единственная тема своего модуля


def test_anatomy_empty_material_gets_honest_placeholder_not_fabricated_text(anatomy):
    """37 из 107 реальных тем анатомии не имеют material -- см. отчёт по данным. Плейсхолдер
    должен быть честным UI-текстом ("материал не добавлен"), а не выдуманным содержанием."""
    tb = FakeTb(anatomy=anatomy)
    material = static_content.get_material(tb, "anatomy", "course", "empty_stub")
    assert material["content_html"] == static_content.ANATOMY_EMPTY_MATERIAL_NOTE
    assert material["prev_id"] == "cranium_intro"
    assert material["next_id"] is None


def test_anatomy_unknown_topic_not_found(anatomy):
    tb = FakeTb(anatomy=anatomy)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "anatomy", "course", "nonexistent")


def test_anatomy_unknown_module_not_found(anatomy):
    tb = FakeTb(anatomy=anatomy)
    with pytest.raises(ContentNotFoundError):
        static_content.get_group_detail(tb, "anatomy", "course", "module99_missing")


def test_list_subject_summaries_includes_anatomy_when_present(anatomy):
    tb = FakeTb(anatomy=anatomy)
    ids = {s["id"] for s in static_content.list_subject_summaries(tb)}
    assert ids == {"anatomy"}


# ==================== Гистология ====================
# HISTOLOGY -- dict диагностик (не список) -> список specimens (не dict, в отличие от тем
# Анатомии) -- см. docstring static_content.py и отчёт по данным (5 диагностик, 71 препарат).
# Гейт доступа (пробный период/подписка/рефералы) сюда намеренно НЕ входит -- эти функции чистые
# над формой контента, гейт живёт в routers/subjects.py и покрыт test_subjects_integration.py.

@pytest.fixture
def histology():
    return {
        "diagnostika_1": {
            "number": 1,
            "title": "Диагностика №1: Цитология",
            "menu_title": "1️⃣ Цитология",
            "total_official": 2,
            "specimens": [
                {
                    "id": "d1_01",
                    "number": 1,
                    "title": "Жировые включения в клетках печени",
                    "stain": "Осмиевая кислота и сафранин",
                    "magnification": "400",
                    "protocol": "Первый абзац протокола.\n\nВторой абзац протокола.",
                    "images": ["diagnostika_1/d1_01/1.jpg", "diagnostika_1/d1_01/2.jpg"],
                    "guess_image": "diagnostika_1/d1_01/1.jpg",
                },
                {
                    "id": "d1_02",
                    "number": 2,
                    "title": "Митоз в корешке лука",
                    "stain": "Железный гематоксилин",
                    "magnification": "400",
                    "protocol": "Единственный абзац без картинок.",
                    "images": [],
                    "guess_image": None,
                },
            ],
        },
        "diagnostika_2": {
            "number": 2,
            "title": "Диагностика №2: Ткани",
            "menu_title": "2️⃣ Ткани",
            "total_official": 1,
            "specimens": [
                {
                    "id": "d2_01",
                    "number": 1,
                    "title": "Многослойный эпителий",
                    "stain": "Гематоксилин-эозин",
                    "magnification": "100",
                    "protocol": "Описание эпителия.",
                    "images": ["diagnostika_2/d2_01/1.jpg"],
                    "guess_image": "diagnostika_2/d2_01/1.jpg",
                },
            ],
        },
    }


def test_histology_summary_and_sections(histology):
    tb = FakeTb(histology=histology)
    detail = static_content.get_subject_detail(tb, "histology")
    assert detail["title"] == "Гистология"
    assert detail["sections"] == [
        {"id": "specimens", "title": "Препараты", "item_count": 3, "kind": "grouped"},
    ]


def test_histology_specimens_section_lists_diagnostics_as_groups(histology):
    tb = FakeTb(histology=histology)
    section = static_content.get_section_detail(tb, "histology", "specimens")
    assert section["kind"] == "grouped"
    assert [(g["id"], g["title"], g["item_count"]) for g in section["groups"]] == [
        ("diagnostika_1", "Диагностика №1: Цитология", 2),
        ("diagnostika_2", "Диагностика №2: Ткани", 1),
    ]


def test_histology_diagnostic_group_lists_specimens_in_source_order(histology):
    tb = FakeTb(histology=histology)
    group = static_content.get_group_detail(tb, "histology", "specimens", "diagnostika_1")
    assert group["title"] == "Диагностика №1: Цитология"
    assert [item["id"] for item in group["items"]] == ["d1_01", "d1_02"]
    assert group["items"][0]["title"] == "Жировые включения в клетках печени"


def test_histology_material_includes_stain_magnification_and_images(histology):
    tb = FakeTb(histology=histology)
    material = static_content.get_material(tb, "histology", "specimens", "d1_01")
    assert material["title"] == "Жировые включения в клетках печени"
    assert "<strong>Окраска:</strong> Осмиевая кислота и сафранин" in material["content_html"]
    assert "<strong>Увеличение:</strong> ×400" in material["content_html"]
    assert "Первый абзац протокола." in material["content_html"]
    assert "Второй абзац протокола." in material["content_html"]
    assert material["sources"] == []
    assert material["group_id"] == "diagnostika_1"
    assert material["order"] == 1
    assert material["total"] == 2
    assert material["prev_id"] is None
    assert material["next_id"] == "d1_02"
    assert material["media"] == [
        {"path": "images/histology/diagnostika_1/d1_01/1.jpg", "caption": "Жировые включения в клетках печени"},
        {"path": "images/histology/diagnostika_1/d1_01/2.jpg", "caption": "Жировые включения в клетках печени"},
    ]


def test_histology_specimen_without_images_has_empty_media(histology):
    tb = FakeTb(histology=histology)
    material = static_content.get_material(tb, "histology", "specimens", "d1_02")
    assert material["media"] == []
    assert material["prev_id"] == "d1_01"
    assert material["next_id"] is None


def test_histology_second_diagnostic_is_independent(histology):
    tb = FakeTb(histology=histology)
    material = static_content.get_material(tb, "histology", "specimens", "d2_01")
    assert material["group_id"] == "diagnostika_2"
    assert material["order"] == 1
    assert material["total"] == 1
    assert material["prev_id"] is None
    assert material["next_id"] is None


def test_histology_unknown_specimen_not_found(histology):
    tb = FakeTb(histology=histology)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "histology", "specimens", "nonexistent")


def test_histology_unknown_diagnostic_not_found(histology):
    tb = FakeTb(histology=histology)
    with pytest.raises(ContentNotFoundError):
        static_content.get_group_detail(tb, "histology", "specimens", "diagnostika_99")


def test_list_subject_summaries_includes_histology_when_present(histology):
    tb = FakeTb(histology=histology)
    ids = {s["id"] for s in static_content.list_subject_summaries(tb)}
    assert ids == {"histology"}


def test_list_subject_summaries_includes_all_four_when_all_present(physiology, operative_surgery, anatomy, histology):
    tb = FakeTb(physiology=physiology, operative_surgery=operative_surgery, anatomy=anatomy, histology=histology)
    ids = {s["id"] for s in static_content.list_subject_summaries(tb)}
    assert ids == {"physiology", "operative_surgery", "anatomy", "histology"}
