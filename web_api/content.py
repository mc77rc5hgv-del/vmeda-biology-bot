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


class InvalidQuizAnswerError(Exception):
    """Урок существует, но не является тестом с вариантами ответа, либо selected_index вне
    диапазона доступных вариантов -- отдельно от ContentNotFoundError, потому что это не "ничего
    не найдено" (404), а некорректный запрос к существующему уроку (400)."""


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
    quiz = lesson.get("quiz")
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
        # Только options -- НИКОГДА correct_index здесь: клиент не должен получить правильный
        # ответ раньше, чем реально ответит (тот же принцип, что уже используют MCQ-сессии бота
        # -- ANATOMY_LATIN_SESSIONS/ANATOMY_EXAM_TEST_SESSIONS никогда не кладут верный вариант в
        # исходящую клавиатуру, только в серверную сессию). Проверка ответа -- через отдельный
        # check_quiz_answer(), см. ниже. Урок без сохранённого quiz (ещё не проверен вручную,
        # см. commit message) отдаёт quiz: null -- фронт рендерит его как обычный текстовый
        # материал, без интерактивности, а не с угаданным/непроверенным "правильным" ответом.
        "quiz": {"options": quiz["options"]} if quiz else None,
    }


def _find_lesson_in_section(section: dict, item_id: str):
    """Возвращает (lesson, index, lessons, group_id) или None -- ищет по всем группам подряд,
    если у раздела есть группы (id урока уникален в пределах раздела -- проверено на реальных
    данных Фармакологии, 1174 из 1174 уникальны), иначе по плоскому списку. Общая логика поиска
    для get_material() и check_quiz_answer(), чтобы не дублировать обход groups/lessons трижды."""
    if "groups" in section:
        for group in section["groups"]:
            lessons = group.get("lessons", [])
            for i, lesson in enumerate(lessons):
                if lesson["id"] == item_id:
                    return lesson, i, lessons, group.get("id")
        return None
    lessons = section.get("lessons", [])
    for i, lesson in enumerate(lessons):
        if lesson["id"] == item_id:
            return lesson, i, lessons, None
    return None


def get_material(dynamic_courses: list, subject_id: str, section_id: str, item_id: str) -> dict:
    """Ищет урок по item_id внутри раздела -- НЕ требует знать заранее, плоский раздел или с
    группами (URL-контракт одинаковый в обоих случаях, см. docstring модуля)."""
    _, course = find_dynamic_course(dynamic_courses, subject_id)
    section = _find_section(course, section_id)
    show_sources = course.get("show_sources", True)

    found = _find_lesson_in_section(section, item_id)
    if found is None:
        raise ContentNotFoundError(f"урок {item_id!r} не найден в разделе {section_id!r}")
    lesson, i, lessons, group_id = found
    prev_id = lessons[i - 1]["id"] if i > 0 else None
    next_id = lessons[i + 1]["id"] if i + 1 < len(lessons) else None
    return _lesson_to_material(
        lesson, i + 1, len(lessons), show_sources=show_sources, group_id=group_id,
        prev_id=prev_id, next_id=next_id,
    )


def check_quiz_answer(
    dynamic_courses: list, subject_id: str, section_id: str, item_id: str, selected_index: int,
) -> dict:
    """Правильный ответ (correct_index) никогда не уходит клиенту заранее (см. _lesson_to_material)
    -- проверка всегда идёт через этот эндпоинт, так же как бот проверяет ответ на сервере в
    ANATOMY_LATIN_SESSIONS/ANATOMY_EXAM_TEST_SESSIONS, а не полагается на клиента. Возвращает
    {"correct": bool, "correct_index": int} -- верный индекс раскрывается только сейчас, уже
    после того как пользователь ответил."""
    _, course = find_dynamic_course(dynamic_courses, subject_id)
    section = _find_section(course, section_id)
    found = _find_lesson_in_section(section, item_id)
    if found is None:
        raise ContentNotFoundError(f"урок {item_id!r} не найден в разделе {section_id!r}")
    lesson = found[0]
    quiz = lesson.get("quiz")
    if not quiz:
        raise InvalidQuizAnswerError(f"урок {item_id!r} не является тестом с вариантами ответа")
    correct_index = quiz["correct_index"]
    if not (0 <= selected_index < len(quiz["options"])):
        raise InvalidQuizAnswerError(f"selected_index {selected_index} вне диапазона вариантов")
    return {"correct": selected_index == correct_index, "correct_index": correct_index}
