"""Контент-адаптер для 'динамических' предметов (generated_courses/*.json, загруженных в
telegram_bot.DYNAMIC_COURSES) -- превращает реальную структуру курса в JSON, который отдаёт API.

Сознательно НЕ покрывает статичные предметы (Физика/Химия/Биология/Анатомия/Гистология/
Физиология/Оперативная хирургия) -- у каждого своя, непохожая на остальные схема (см. отчёт
аудита Этапа 1), адаптер под каждую -- отдельная задача. Это первый проход, скоуп -- только
Биохимия и Фармакология (уже почти в форме контентного контракта из ТЗ §14) плюс Латынь/
Правоведение бесплатно, раз они устроены той же схемой.

Работает с ЧИСТЫМИ данными (список courses, как он выглядит в telegram_bot.DYNAMIC_COURSES) --
не импортирует telegram_bot и не знает про FastAPI, поэтому тестируется без тяжёлого импорта
бота, тем же способом, что auth.py/session.py.

Важное честное упрощение (не искажение): секция с "группами" (сегодня — только у Фармакологии,
раздел "course" с 6 группами и почти 1200 уроками, см. handlers/dynamic_courses.py) возвращает
ДВЕ РАЗНЫЕ формы в зависимости от того, что реально есть в данных -- kind="grouped" с списком
групп, или kind="flat" с прямым списком уроков -- а не насильно сплющивается в один список,
чтобы не потерять реальную структуру курса."""


class ContentNotFoundError(Exception):
    """Предмет/раздел/группа/урок с таким id не существует."""


def find_dynamic_course(dynamic_courses: list, subject_id: str) -> tuple[int, dict]:
    for index, course in enumerate(dynamic_courses):
        if course.get("id") == subject_id:
            return index, course
    raise ContentNotFoundError(f"предмет {subject_id!r} не найден")


def _find_section(course: dict, section_id: str) -> dict:
    for section in course.get("sections", []):
        if section.get("id") == section_id:
            return section
    raise ContentNotFoundError(f"раздел {section_id!r} не найден в предмете {course.get('id')!r}")


def _section_item_count(section: dict) -> int:
    if "groups" in section:
        return sum(len(g.get("lessons", [])) for g in section["groups"])
    return len(section.get("lessons", []))


def to_subject_summary(course: dict) -> dict:
    return {
        "id": course["id"],
        "title": course["title"],
        "emoji": course.get("emoji", "📚"),
        "description": course.get("description"),
        "course": course.get("course", 2),
        "has_ai": bool(course.get("ai_mode")),
    }


def to_subject_detail(course: dict) -> dict:
    summary = to_subject_summary(course)
    summary["sections"] = [
        {
            "id": section["id"],
            "title": section["title"],
            "item_count": _section_item_count(section),
            "kind": "grouped" if "groups" in section else "flat",
        }
        for section in course.get("sections", [])
    ]
    return summary


def get_subject_detail(dynamic_courses: list, subject_id: str) -> dict:
    _, course = find_dynamic_course(dynamic_courses, subject_id)
    return to_subject_detail(course)


def get_section_detail(dynamic_courses: list, subject_id: str, section_id: str) -> dict:
    _, course = find_dynamic_course(dynamic_courses, subject_id)
    section = _find_section(course, section_id)
    if "groups" in section:
        return {
            "id": section["id"],
            "title": section["title"],
            "kind": "grouped",
            "groups": [
                {"id": g.get("id", str(i)), "title": g["title"], "item_count": len(g.get("lessons", []))}
                for i, g in enumerate(section["groups"])
            ],
        }
    lessons = section.get("lessons", [])
    total = len(lessons)
    return {
        "id": section["id"],
        "title": section["title"],
        "kind": "flat",
        "items": [
            {"id": lesson["id"], "title": lesson["title"], "order": i + 1, "total": total}
            for i, lesson in enumerate(lessons)
        ],
    }


def get_group_detail(dynamic_courses: list, subject_id: str, section_id: str, group_id: str) -> dict:
    _, course = find_dynamic_course(dynamic_courses, subject_id)
    section = _find_section(course, section_id)
    for group in section.get("groups", []):
        if group.get("id") == group_id or group.get("title") == group_id:
            lessons = group.get("lessons", [])
            total = len(lessons)
            return {
                "id": group.get("id", group_id),
                "title": group["title"],
                "items": [
                    {"id": lesson["id"], "title": lesson["title"], "order": i + 1, "total": total}
                    for i, lesson in enumerate(lessons)
                ],
            }
    raise ContentNotFoundError(f"группа {group_id!r} не найдена в разделе {section_id!r}")


def _lesson_to_material(
    lesson: dict, order: int, total: int, *, show_sources: bool, group_id: str | None,
    prev_id: str | None, next_id: str | None,
) -> dict:
    return {
        "id": lesson["id"],
        "title": lesson["title"],
        "content_html": lesson["content"],
        "sources": lesson.get("sources", []) if show_sources else [],
        "order": order,
        "total": total,
        "group_id": group_id,
        # Реальные id уроков (напр. "core_p1_1") не образуют предсказуемую числовую
        # последовательность вроде mock-материалов (см. lib/mockData.ts на фронте, где id ==
        # order) -- фронт не может вычислить "следующий" id сам, поэтому он приходит готовым
        # здесь же (null на границах раздела/группы).
        "prev_id": prev_id,
        "next_id": next_id,
        "media": [
            {"path": m["path"], "caption": m.get("caption", "")}
            for m in lesson.get("media", [])
        ],
    }


def get_material(dynamic_courses: list, subject_id: str, section_id: str, item_id: str) -> dict:
    """Ищет урок по item_id внутри раздела -- НЕ требует знать заранее, плоский раздел или с
    группами (URL-контракт одинаковый в обоих случаях, см. docstring модуля): если в разделе есть
    группы, ищет по всем группам подряд (id урока уникален в пределах раздела -- проверено на
    реальных данных Фармакологии, 1174 из 1174 уникальны)."""
    _, course = find_dynamic_course(dynamic_courses, subject_id)
    section = _find_section(course, section_id)
    show_sources = course.get("show_sources", True)

    if "groups" in section:
        for group in section["groups"]:
            lessons = group.get("lessons", [])
            for i, lesson in enumerate(lessons):
                if lesson["id"] == item_id:
                    prev_id = lessons[i - 1]["id"] if i > 0 else None
                    next_id = lessons[i + 1]["id"] if i + 1 < len(lessons) else None
                    return _lesson_to_material(
                        lesson, i + 1, len(lessons), show_sources=show_sources, group_id=group.get("id"),
                        prev_id=prev_id, next_id=next_id,
                    )
        raise ContentNotFoundError(f"урок {item_id!r} не найден в разделе {section_id!r}")

    lessons = section.get("lessons", [])
    for i, lesson in enumerate(lessons):
        if lesson["id"] == item_id:
            prev_id = lessons[i - 1]["id"] if i > 0 else None
            next_id = lessons[i + 1]["id"] if i + 1 < len(lessons) else None
            return _lesson_to_material(
                lesson, i + 1, len(lessons), show_sources=show_sources, group_id=None,
                prev_id=prev_id, next_id=next_id,
            )
    raise ContentNotFoundError(f"урок {item_id!r} не найден в разделе {section_id!r}")
