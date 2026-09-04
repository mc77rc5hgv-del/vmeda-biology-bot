import pytest

from web_api import static_content
from web_api.content import ContentNotFoundError


class FakeTb:
    """static_content.py принимает "tb-подобный" объект (см. web_api/bot_state.py -- в реальном
    коде это модуль telegram_bot), а не сырые словари напрямую, потому что теперь оно отвечает
    сразу за несколько статичных предметов (Физиология + Оперативная хирургия + Анатомия +
    Гистология + Биология + Химия) и само решает, какой атрибут прочитать. Тесты собирают
    минимальную заглушку с ровно этими атрибутами -- гейты доступа (Анатомия: модуль
    бесплатный/платный, тех.режим; Гистология/Биология/Химия: пробный период/подписка/рефералы)
    сюда НЕ входят, они живут в web_api/routers/subjects.py (см. test_subjects_integration.py и
    test_access.py) и требуют user_id, которого у чистых функций формы контента здесь нет."""

    def __init__(
        self, physiology=None, operative_surgery=None, anatomy=None, histology=None,
        tickets=None, questions=None,
        chemistry_theory=None, chemistry_tasks=None, chemistry_labs=None,
        chemistry_theory_tickets=None, chemistry_practice_tickets=None,
    ):
        self.PHYSIOLOGY = physiology or {}
        self.OPERATIVE_SURGERY = operative_surgery or {}
        self.ANATOMY = anatomy or {}
        self.HISTOLOGY = histology or {}
        self.TICKETS = tickets or []
        self.QUESTIONS = questions or {}
        self.CHEMISTRY_THEORY = chemistry_theory or {}
        self.CHEMISTRY_TASKS = chemistry_tasks or {}
        self.CHEMISTRY_LABS = chemistry_labs or {}
        self.CHEMISTRY_THEORY_TICKETS = chemistry_theory_tickets or {}
        self.CHEMISTRY_PRACTICE_TICKETS = chemistry_practice_tickets or {}


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


# ==================== Биология ====================
# TICKETS -- список (не dict, в отличие от всех остальных подключённых предметов), QUESTIONS --
# dict "1".."185" в порядке вставки. Гейт доступа (has_subject_access, тот же реферальный
# middleware, что у Физики/Химии) сюда намеренно НЕ входит -- эти функции чистые над формой
# контента, гейт живёт в routers/subjects.py и покрыт test_subjects_integration.py.

@pytest.fixture
def tickets():
    return [
        {
            "num": "1A",
            "title": "Билет №1",
            "questions": [
                {"num": 1, "title": "Вопрос 1.1", "answer": "<b>Ответ</b> на первый вопрос."},
                {"num": 2, "title": "Вопрос 1.2", "answer": "Ответ на второй вопрос."},
            ],
        },
        {
            "num": "2A",
            "title": "Билет №2",
            "questions": [
                {"num": 1, "title": "Вопрос 2.1", "answer": "Ответ билета два."},
            ],
        },
    ]


@pytest.fixture
def questions():
    return {
        "1": {"title": "Первый вопрос зачёта", "answer": "Обычный текст без HTML <не тег>."},
        "2": {"title": "Второй вопрос зачёта", "answer": "Второй ответ."},
    }


def test_biology_summary_and_sections(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    detail = static_content.get_subject_detail(tb, "biology")
    assert detail["title"] == "Биология"
    assert detail["sections"] == [
        {"id": "tickets", "title": "Билеты", "item_count": 3, "kind": "grouped"},
        {"id": "questions", "title": "Вопросы", "item_count": 2, "kind": "flat"},
    ]


def test_biology_tickets_section_lists_tickets_as_groups(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    section = static_content.get_section_detail(tb, "biology", "tickets")
    assert section["kind"] == "grouped"
    assert [(g["id"], g["title"], g["item_count"]) for g in section["groups"]] == [
        ("1A", "Билет №1", 2),
        ("2A", "Билет №2", 1),
    ]


def test_biology_questions_section_is_flat_in_bank_order(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    section = static_content.get_section_detail(tb, "biology", "questions")
    assert section["kind"] == "flat"
    assert [(i["id"], i["title"], i["order"], i["total"]) for i in section["items"]] == [
        ("1", "Первый вопрос зачёта", 1, 2),
        ("2", "Второй вопрос зачёта", 2, 2),
    ]


def test_biology_ticket_group_lists_questions_with_composite_ids(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    group = static_content.get_group_detail(tb, "biology", "tickets", "1A")
    assert group["title"] == "Билет №1"
    assert [item["id"] for item in group["items"]] == ["1A_1", "1A_2"]
    assert group["items"][0]["title"] == "Вопрос 1.1"


def test_biology_ticket_question_material_keeps_html_untouched(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    material = static_content.get_material(tb, "biology", "tickets", "1A_1")
    assert material["title"] == "Вопрос 1.1"
    assert material["content_html"] == "<b>Ответ</b> на первый вопрос."  # не эскейпится -- уже HTML
    assert material["sources"] == []
    assert material["group_id"] == "1A"
    assert material["order"] == 1
    assert material["total"] == 2
    assert material["prev_id"] is None
    assert material["next_id"] == "1A_2"


def test_biology_ticket_question_material_last_in_ticket_has_no_next(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    material = static_content.get_material(tb, "biology", "tickets", "1A_2")
    assert material["prev_id"] == "1A_1"
    assert material["next_id"] is None


def test_biology_second_ticket_is_independent(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    material = static_content.get_material(tb, "biology", "tickets", "2A_1")
    assert material["group_id"] == "2A"
    assert material["order"] == 1
    assert material["total"] == 1
    assert material["prev_id"] is None
    assert material["next_id"] is None


def test_biology_question_bank_material_escapes_plain_text(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    material = static_content.get_material(tb, "biology", "questions", "1")
    assert material["title"] == "Первый вопрос зачёта"
    assert material["content_html"] == "<p>Обычный текст без HTML &lt;не тег&gt;.</p>"
    assert material["group_id"] is None
    assert material["prev_id"] is None
    assert material["next_id"] == "2"


def test_biology_unknown_ticket_question_not_found(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "biology", "tickets", "99A_1")


def test_biology_unknown_bank_question_not_found(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "biology", "questions", "999")


def test_biology_unknown_ticket_group_not_found(tickets, questions):
    tb = FakeTb(tickets=tickets, questions=questions)
    with pytest.raises(ContentNotFoundError):
        static_content.get_group_detail(tb, "biology", "tickets", "99A")


def test_list_subject_summaries_includes_biology_when_tickets_or_questions_present(tickets):
    tb = FakeTb(tickets=tickets)
    ids = {s["id"] for s in static_content.list_subject_summaries(tb)}
    assert ids == {"biology"}


# ==================== Химия ====================
# Пять банков разной формы: THEORY/PRACTICE_TICKETS -- dict "1".."N" -> {title, content}, flat;
# TASKS/THEORY_TICKETS -- dict -> {title, ...вложенный список}, grouped; LABS -- {"labs": [...]}
# (единственный банк, обёрнутый в объект, а не голый dict/список). Гейт доступа (обычный +
# усиленный chemistry_tickets_access_ok для билетов) сюда намеренно НЕ входит -- см. docstring
# static_content.py и test_subjects_integration.py.

@pytest.fixture
def chemistry_theory():
    return {
        "1": {"title": "Тема 1", "content": "<b>Растворы</b> — гомогенные системы."},
        "2": {"title": "Тема 2", "content": "Вторая тема."},
    }


@pytest.fixture
def chemistry_tasks():
    return {
        "1": {
            "title": "Концентрации растворов",
            "intro": "Вступление без HTML.",
            "formulas": "<b>Формулы:</b> C = n/V.",
            "tasks": [
                {"num": 1, "title": "Задача 1.1", "condition": "Дано: <опасный> текст.", "solution": "<b>Решение 1.</b>"},
                {"num": 2, "title": "Задача 1.2", "condition": "Условие 2.", "solution": "<b>Решение 2.</b>"},
            ],
        },
        "2": {
            "title": "Тема без задач формул",
            "intro": "",
            "formulas": "",
            "tasks": [
                {"num": 1, "title": "Задача 2.1", "condition": "Условие.", "solution": "Решение без HTML."},
            ],
        },
    }


@pytest.fixture
def chemistry_labs():
    return {
        "section": "Химия",
        "description": "desc",
        "labs": [
            {
                "number": 1,
                "title": "Лабораторная работа 1",
                "theme": "Хроматография",
                "condition": "Условие лабораторной <опасное>.",
                "experiments": [
                    {
                        "name": "Опыт 1",
                        "description": "Описание опыта.",
                        "mechanism": "Адсорбционный",
                        "technique": "",
                        "sorbent": "Бумага",
                        "eluent": "Вода",
                        "procedure": "Ход работы опыта.",
                    },
                ],
                "calculations": "Rf = l/L",
                "summary": "<b>Вывод:</b> метод сработал.",
            },
            {
                "number": 2,
                "title": "Лабораторная работа 2",
                "theme": "Титрование",
                "condition": "Условие 2.",
                "titrant": "HCl",
                "indicator": "Фенолфталеин",
                "procedure": "Методика титрования.",
                "calculations": "V·C = const",
                "summary": "<b>Вывод 2.</b>",
            },
        ],
    }


@pytest.fixture
def chemistry_theory_tickets():
    return {
        "1": {
            "title": "Билет №1",
            "questions": [
                {"title": "Вопрос 1.1", "answer": "<b>Ответ 1.1.</b>"},
                {"title": "Вопрос 1.2", "answer": "<b>Ответ 1.2.</b>"},
            ],
        },
        "2": {
            "title": "Билет №2",
            "questions": [{"title": "Вопрос 2.1", "answer": "<b>Ответ 2.1.</b>"}],
        },
    }


@pytest.fixture
def chemistry_practice_tickets():
    return {
        "1": {"title": "Билет №1 (практика)", "content": "<b>Условие:</b> задача практики."},
        "2": {"title": "Билет №2 (практика)", "content": "Условие 2."},
    }


def _chemistry_tb(chemistry_theory=None, chemistry_tasks=None, chemistry_labs=None,
                   chemistry_theory_tickets=None, chemistry_practice_tickets=None):
    return FakeTb(
        chemistry_theory=chemistry_theory, chemistry_tasks=chemistry_tasks, chemistry_labs=chemistry_labs,
        chemistry_theory_tickets=chemistry_theory_tickets, chemistry_practice_tickets=chemistry_practice_tickets,
    )


def test_chemistry_summary_and_sections(
    chemistry_theory, chemistry_tasks, chemistry_labs, chemistry_theory_tickets, chemistry_practice_tickets,
):
    tb = _chemistry_tb(chemistry_theory, chemistry_tasks, chemistry_labs, chemistry_theory_tickets, chemistry_practice_tickets)
    detail = static_content.get_subject_detail(tb, "chemistry")
    assert detail["title"] == "Химия"
    sections = {s["id"]: s for s in detail["sections"]}
    assert sections["theory"] == {"id": "theory", "title": "Теория", "item_count": 2, "kind": "flat"}
    assert sections["tasks"] == {"id": "tasks", "title": "Задачи", "item_count": 5, "kind": "grouped"}  # 2 formulas + 3 tasks
    assert sections["labs"] == {"id": "labs", "title": "Лабораторные", "item_count": 2, "kind": "flat"}
    assert sections["theory_tickets"] == {
        "id": "theory_tickets", "title": "Билеты теории", "item_count": 3, "kind": "grouped",
    }
    assert sections["practice_tickets"] == {
        "id": "practice_tickets", "title": "Билеты практики", "item_count": 2, "kind": "flat",
    }


def test_chemistry_theory_material_trusts_html(chemistry_theory):
    tb = _chemistry_tb(chemistry_theory=chemistry_theory)
    material = static_content.get_material(tb, "chemistry", "theory", "1")
    assert material["title"] == "Тема 1"
    assert material["content_html"] == "<b>Растворы</b> — гомогенные системы."
    assert material["prev_id"] is None
    assert material["next_id"] == "2"


def test_chemistry_tasks_group_lists_formulas_card_first(chemistry_tasks):
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    group = static_content.get_group_detail(tb, "chemistry", "tasks", "1")
    assert group["title"] == "Концентрации растворов"
    assert [item["id"] for item in group["items"]] == ["1_formulas", "1_1", "1_2"]
    assert group["items"][0]["title"] == "📐 Формулы и алгоритм"


def test_chemistry_formulas_material_escapes_intro_trusts_formulas(chemistry_tasks):
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    material = static_content.get_material(tb, "chemistry", "tasks", "1_formulas")
    assert "Вступление без HTML." in material["content_html"]
    assert "<b>Формулы:</b> C = n/V." in material["content_html"]
    assert material["group_id"] == "1"
    assert material["prev_id"] is None
    assert material["next_id"] == "1_1"


def test_chemistry_task_material_escapes_condition_trusts_solution(chemistry_tasks):
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    material = static_content.get_material(tb, "chemistry", "tasks", "1_1")
    assert "&lt;опасный&gt;" in material["content_html"]  # condition эскейпится
    assert "<b>Решение 1.</b>" in material["content_html"]  # solution -- уже HTML
    assert material["prev_id"] == "1_formulas"
    assert material["next_id"] == "1_2"


def test_chemistry_task_material_last_item_has_no_next(chemistry_tasks):
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    material = static_content.get_material(tb, "chemistry", "tasks", "1_2")
    assert material["next_id"] is None


def test_chemistry_topic_without_formulas_still_has_formulas_card(chemistry_tasks):
    """intro/formulas пустые у темы 2 -- карточка "Формулы и алгоритм" всё равно существует
    (честно, просто с пустым content_html), не пропадает из списка."""
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    material = static_content.get_material(tb, "chemistry", "tasks", "2_formulas")
    assert material["content_html"] == ""
    assert material["next_id"] == "2_1"


def test_chemistry_lab_material_renders_experiments_and_trusts_summary(chemistry_labs):
    tb = _chemistry_tb(chemistry_labs=chemistry_labs)
    material = static_content.get_material(tb, "chemistry", "labs", "1")
    assert material["title"] == "Лабораторная работа 1"
    assert "&lt;опасное&gt;" in material["content_html"]  # condition эскейпится
    assert "<strong>Опыт 1</strong>" in material["content_html"]
    assert "Описание опыта." in material["content_html"]
    assert "<b>Вывод:</b> метод сработал." in material["content_html"]  # summary -- уже HTML
    assert material["prev_id"] is None
    assert material["next_id"] == "2"


def test_chemistry_lab_without_experiments_still_renders(chemistry_labs):
    tb = _chemistry_tb(chemistry_labs=chemistry_labs)
    material = static_content.get_material(tb, "chemistry", "labs", "2")
    assert "Методика титрования." in material["content_html"]
    assert material["prev_id"] == "1"
    assert material["next_id"] is None


def test_chemistry_theory_ticket_group_and_material(chemistry_theory, chemistry_theory_tickets):
    tb = _chemistry_tb(chemistry_theory=chemistry_theory, chemistry_theory_tickets=chemistry_theory_tickets)
    group = static_content.get_group_detail(tb, "chemistry", "theory_tickets", "1")
    assert group["title"] == "Билет №1"
    assert [item["id"] for item in group["items"]] == ["1_0", "1_1"]

    material = static_content.get_material(tb, "chemistry", "theory_tickets", "1_0")
    assert material["title"] == "Вопрос 1.1"
    assert material["content_html"] == "<b>Ответ 1.1.</b>"
    assert material["group_id"] == "1"
    assert material["prev_id"] is None
    assert material["next_id"] == "1_1"


def test_chemistry_practice_ticket_material_trusts_html(chemistry_theory, chemistry_practice_tickets):
    tb = _chemistry_tb(chemistry_theory=chemistry_theory, chemistry_practice_tickets=chemistry_practice_tickets)
    material = static_content.get_material(tb, "chemistry", "practice_tickets", "1")
    assert material["content_html"] == "<b>Условие:</b> задача практики."
    assert material["group_id"] is None
    assert material["next_id"] == "2"


def test_chemistry_unknown_theory_topic_not_found(chemistry_theory):
    tb = _chemistry_tb(chemistry_theory=chemistry_theory)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "chemistry", "theory", "99")


def test_chemistry_unknown_task_not_found(chemistry_tasks):
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "chemistry", "tasks", "99_1")


def test_chemistry_unknown_lab_not_found(chemistry_labs):
    tb = _chemistry_tb(chemistry_labs=chemistry_labs)
    with pytest.raises(ContentNotFoundError):
        static_content.get_material(tb, "chemistry", "labs", "99")


def test_chemistry_unknown_task_group_not_found(chemistry_tasks):
    tb = _chemistry_tb(chemistry_tasks=chemistry_tasks)
    with pytest.raises(ContentNotFoundError):
        static_content.get_group_detail(tb, "chemistry", "tasks", "99")


def test_list_subject_summaries_includes_chemistry_when_theory_present(chemistry_theory):
    tb = _chemistry_tb(chemistry_theory=chemistry_theory)
    ids = {s["id"] for s in static_content.list_subject_summaries(tb)}
    assert ids == {"chemistry"}
