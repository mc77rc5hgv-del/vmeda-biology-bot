import os
import random

from services.miniapp_testers import has_test_access

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import content, schemas, static_content, attempt_tokens
from services.content_access import can_visit
from ..deps import get_current_user_id, get_fresh_bot_module

router = APIRouter(prefix="/api/v1", tags=["subjects"])

# Динамические предметы идут через content.py; постепенно подключаемые статичные — через
# static_content.py. Маршруты остаются едиными для клиента.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAINTENANCE_REASON = (
    "Раздел временно закрыт на полную переработку материалов и структуры. "
    "Он вернётся после повторной проверки качества."
)


def _check_subject_maintenance(tb, subject_id: str) -> None:
    if tb.dynamic_course_under_maintenance(subject_id):
        raise HTTPException(status_code=503, detail=MAINTENANCE_REASON)


def _with_maintenance(tb, summary: dict) -> dict:
    if tb.dynamic_course_under_maintenance(summary.get("id")):
        return {**summary, "maintenance": True, "maintenance_reason": MAINTENANCE_REASON}
    return summary


def _not_found(exc: content.ContentNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _bad_quiz_answer(exc: content.InvalidQuizAnswerError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


ANATOMY_EXAM_OPTION_LETTERS = "абвгд"


def _histology_stats(tb, user_id: int) -> dict:
    from .. import learning
    if os.environ.get('BOT_SYNC_MODE') == 'owner':
        from services.histology_sync import summary
        return summary(tb, user_id)
    total = sum(len(group.get('specimens', [])) for group in tb.HISTOLOGY.values())
    return learning.get_histology_stats(user_id, total)


def _histology_specimen_by_id(tb, specimen_id: str) -> tuple[str, dict, dict] | None:
    for group_id, group in tb.HISTOLOGY.items():
        for specimen in group.get("specimens", []):
            if specimen.get("id") == specimen_id:
                return group_id, group, specimen
    return None


def _histology_specimen_payload(group_id: str, group: dict, specimen: dict) -> dict:
    return {
        "id": specimen["id"],
        "number": specimen["number"],
        "title": specimen["title"],
        "stain": specimen.get("stain"),
        "magnification": specimen.get("magnification"),
        "group_id": group_id,
        "group_title": group.get("title", ""),
        "image_count": len(specimen.get("images", [])),
        "practical_available": bool(specimen.get("guess_image")),
    }


def _histology_practical_pool(tb, scope: str, user_id: int) -> list[tuple[str, dict, dict]]:

    mistake_ids = set(_histology_stats(tb, user_id)['mistake_ids']) if scope == "mistakes" else None
    pool = []
    for group_id, group in tb.HISTOLOGY.items():
        if scope not in {"all", "mistakes"} and scope != group_id:
            continue
        for specimen in group.get("specimens", []):
            if not specimen.get("guess_image"):
                continue
            if mistake_ids is not None and specimen["id"] not in mistake_ids:
                continue
            pool.append((group_id, group, specimen))
    return pool


@router.get("/histology/exam/catalog")
def get_histology_exam_catalog(
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    _check_histology_access(tb, user_id)
    groups = []
    for group_id, group in tb.HISTOLOGY.items():
        specimens = [
            _histology_specimen_payload(group_id, group, specimen)
            for specimen in group.get("specimens", [])
        ]
        groups.append({
            "id": group_id,
            "title": group.get("title", ""),
            "menu_title": group.get("menu_title", group.get("title", "")),
            "specimens": specimens,
        })
    return {"title": "ЭКЗАМЕН", "total_specimens": sum(len(g["specimens"]) for g in groups), "groups": groups}


@router.get("/histology/exam/stats")
def get_histology_exam_stats(
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:

    _check_histology_access(tb, user_id)
    return _histology_stats(tb, user_id)


@router.get("/histology/exam/specimens/{specimen_id}")
def get_histology_exam_specimen(
    specimen_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    """Полная карточка препарата для отдельного микроскопического просмотрщика.

    Координатные метки берём только из банка, если они были проверены редактором. Пустой
    список означает, что клиент показывает исходные стрелки на микрофотографии, но не
    выдумывает поверх изображения новые анатомические ориентиры.
    """
    _check_histology_access(tb, user_id)
    found = _histology_specimen_by_id(tb, specimen_id)
    if found is None:
        raise HTTPException(status_code=404, detail="препарат не найден")
    group_id, group, specimen = found
    media_base = f"/api/v1/materials/histology/specimens/{specimen_id}/media"
    return {
        **_histology_specimen_payload(group_id, group, specimen),
        "protocol": specimen.get("protocol", ""),
        "images": [f"{media_base}/{index}" for index, _ in enumerate(specimen.get("images", []))],
        "image_guides": specimen.get("image_guides", []),
        "metadata_note": specimen.get("metadata_note", ""),
        "sources": specimen.get("sources", []),
        "markers": specimen.get("markers", []),
    }


@router.get("/histology/exam/practical")
def get_histology_practical_questions(
    scope: str = "all",
    limit: int = 10,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    _check_histology_access(tb, user_id)
    if not 1 <= limit <= 30:
        raise HTTPException(status_code=400, detail="число препаратов должно быть от 1 до 30")
    if scope not in {'all', 'mistakes'} and scope not in tb.HISTOLOGY:
        raise HTTPException(status_code=400, detail='Неизвестный режим зачёта')
    pool = _histology_practical_pool(tb, scope, user_id)
    if not pool:
        return []
    picked = random.sample(pool, min(limit, len(pool)))
    attempts = [attempt_tokens.issue(user_id, specimen['id'], scope) for _, _, specimen in picked]
    return [
        {
            'attempt_id': attempts[index],
            "id": specimen["id"],
            "position": index + 1,
            "image_url": f"/api/v1/histology/exam/specimens/{specimen['id']}/guess-image",
        }
        for index, (_, _, specimen) in enumerate(picked)
    ]


@router.get("/histology/exam/specimens/{specimen_id}/guess-image")
def get_histology_guess_image(
    specimen_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
):
    _check_histology_access(tb, user_id)
    found = _histology_specimen_by_id(tb, specimen_id)
    if found is None:
        raise HTTPException(status_code=404, detail="препарат не найден")
    _, _, specimen = found
    guess_image = specimen.get("guess_image")
    if not guess_image:
        raise HTTPException(status_code=404, detail="изображение для зачёта не подготовлено")
    path = os.path.join(REPO_ROOT, "images", "histology", guess_image)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="файл микрофотографии не найден")
    return FileResponse(path)


@router.post("/histology/exam/specimens/{specimen_id}/reveal")
def reveal_histology_practical_answer(
    specimen_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    _check_histology_access(tb, user_id)
    found = _histology_specimen_by_id(tb, specimen_id)
    if found is None:
        raise HTTPException(status_code=404, detail="препарат не найден")
    group_id, group, specimen = found
    return {
        **_histology_specimen_payload(group_id, group, specimen),
        "protocol": specimen.get("protocol", ""),
    }


@router.post("/histology/exam/specimens/{specimen_id}/grade")
def grade_histology_practical_answer(
    specimen_id: str,
    body: schemas.HistologyPracticalGradeRequest,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    from .. import learning

    _check_histology_access(tb, user_id)
    if _histology_specimen_by_id(tb, specimen_id) is None:
        raise HTTPException(status_code=404, detail="препарат не найден")
    if os.environ.get('BOT_SYNC_MODE') == 'owner' or body.attempt_id:
        attempt_tokens.verify(body.attempt_id, user_id, specimen_id, body.scope)
    learning.record_histology_attempt(user_id, specimen_id, body.known, body.scope, event_id=body.attempt_id)
    return _histology_stats(tb, user_id)


def _anatomy_exam_question_by_num(tb, question_num: int) -> dict | None:
    for part in tb.ANATOMY_EXAM_TEST_PARTS:
        for question in part.get("questions", []):
            if question.get("num") == question_num:
                return question
    return None


def _anatomy_exam_public_question(question: dict) -> dict:
    """Question payload without the answer key; the key is disclosed only after an answer."""
    letters = [letter for letter in ANATOMY_EXAM_OPTION_LETTERS if letter in question["options"]]
    return {
        "id": str(question["num"]),
        "num": question["num"],
        "question": question["question"],
        "option_letters": letters,
        "options": [question["options"][letter] for letter in letters],
    }


@router.get("/anatomy/exam/parts")
def get_anatomy_exam_parts(
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    """The exam bank is free, mirroring the Telegram bot's dedicated exam section."""
    return [
        {
            "id": part["id"],
            "title": part["title"],
            "topics": part.get("topics", ""),
            "question_count": len(part.get("questions", [])),
        }
        for part in tb.ANATOMY_EXAM_TEST_PARTS
    ]


@router.get("/anatomy/exam/parts/{part_id}/questions")
def get_anatomy_exam_part_questions(
    part_id: int,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    part = next((part for part in tb.ANATOMY_EXAM_TEST_PARTS if part["id"] == part_id), None)
    if part is None:
        raise HTTPException(status_code=404, detail="часть теста не найдена")
    return [_anatomy_exam_public_question(question) for question in part["questions"]]


@router.get("/anatomy/exam/flash")
def get_anatomy_exam_flash_questions(
    limit: int = 50,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="число вопросов должно быть от 1 до 100")
    questions = [question for part in tb.ANATOMY_EXAM_TEST_PARTS for question in part["questions"]]
    picked = random.sample(questions, min(limit, len(questions)))
    return [_anatomy_exam_public_question(question) for question in picked]


@router.post("/anatomy/exam/questions/{question_num}/answer")
def answer_anatomy_exam_question(
    question_num: int,
    body: schemas.AnatomyExamAnswerRequest,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> schemas.AnatomyExamAnswerResponse:
    question = _anatomy_exam_question_by_num(tb, question_num)
    if question is None:
        raise HTTPException(status_code=404, detail="вопрос не найден")
    letters = [letter for letter in ANATOMY_EXAM_OPTION_LETTERS if letter in question["options"]]
    if not 0 <= body.selected_index < len(letters):
        raise HTTPException(status_code=400, detail="некорректный вариант ответа")
    correct_letter = question["correct"]
    correct_index = letters.index(correct_letter)
    return schemas.AnatomyExamAnswerResponse(
        correct=body.selected_index == correct_index,
        correct_index=correct_index,
        correct_letter=correct_letter,
        correct_text=question["options"][correct_letter],
        explanation=tb.ANATOMY_EXAM_TEST_EXPLANATIONS.get(
            str(question_num), "Правильный вариант соответствует ключу тестового банка."
        ),
    )


# ==================== Гейт Анатомии ====================
# В отличие от Физиологии/Оперативной хирургии (полностью бесплатные в самом боте — см.
# static_content.py), Анатомия внутри бота гейтится ПО МОДУЛЯМ (ANATOMY_FREE_SECTIONS) и общим
# тех.режимом (anatomy_maintenance_mode_enabled) — см. handlers/anatomy.py. static_content.py
# остаётся чистой функцией формы контента (как и для двух других предметов), а проверка прав
# живёт здесь, потому что только здесь есть user_id (Depends(get_current_user_id)). "group_id" в
# разделе "course" Анатомии — это ключ модуля (напр. "module1_osteology"), ровно тот же, что
# принимает anatomy_section_access_ok на боте.


def _anatomy_maintenance_locked_reason(tb, user_id: int) -> str | None:
    if tb.anatomy_maintenance_mode_enabled() and not (tb.is_admin_or_assistant(user_id) or has_test_access(tb, user_id)):
        # Тот же текст, что показывает боту get_anatomy_maintenance_text(), без HTML-обёртки —
        # раздел временно закрыт технически, это не платный гейт.
        return (
            "Раздел временно недоступен по техническим причинам. "
            "Мы уже работаем над этим — загляни немного позже."
        )
    return None


def _anatomy_module_locked_reason(tb, user_id: int, module_key: str) -> str | None:
    maintenance_reason = _anatomy_maintenance_locked_reason(tb, user_id)
    if maintenance_reason is not None:
        return maintenance_reason
    module_key = static_content.anatomy_miniapp.GROUPS.get(module_key, {}).get("permission_key", module_key)
    if has_test_access(tb, user_id) or tb.anatomy_section_access_ok(user_id, module_key):
        return None
    cheapest = tb.cheapest_anatomy_tier()
    return (
        f"Этот раздел анатомии доступен по подписке от «{cheapest['short']}» "
        f"({cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐)."
    )


def _annotate_anatomy_groups(tb, user_id: int, section: dict) -> dict:
    if section.get("id") == static_content.ANATOMY_SECTION_ID:
        for group in section.get("groups", []):
            reason = _anatomy_module_locked_reason(tb, user_id, group["id"])
            group["locked"] = reason is not None
            group["locked_reason"] = reason
    return section


def _check_anatomy_material_access(tb, user_id: int, section_id: str, item_id: str) -> None:
    if section_id != static_content.ANATOMY_SECTION_ID:
        raise HTTPException(status_code=404, detail=f"раздел {section_id!r} не найден в анатомии")
    imported = static_content.anatomy_miniapp.TOPICS.get(item_id)
    module_key = imported["module_id"] if imported else None
    for candidate_key, module in tb.ANATOMY.items():
        if item_id in module.get("topics", {}):
            module_key = candidate_key
            break
    if module_key is None:
        raise HTTPException(status_code=404, detail=f"тема {item_id!r} не найдена в анатомии")
    reason = _anatomy_module_locked_reason(tb, user_id, module_key)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)


def _get_material_data(tb, user_id: int, subject_id: str, section_id: str, item_id: str) -> dict:
    _check_subject_maintenance(tb, subject_id)
    if subject_id == static_content.ANATOMY_ID:
        _check_anatomy_material_access(tb, user_id, section_id, item_id)
    if subject_id == static_content.HISTOLOGY_ID:
        _check_histology_access(tb, user_id)
    if subject_id == static_content.BIOLOGY_ID:
        _check_biology_access(tb, user_id)
    if subject_id == static_content.CHEMISTRY_ID:
        if section_id in static_content.CHEMISTRY_TICKET_SECTION_IDS:
            _check_chemistry_tickets_access(tb, user_id)
        else:
            _check_chemistry_access(tb, user_id)
    if subject_id == static_content.PHYSICS_ID:
        _check_physics_access(tb, user_id)
    if subject_id in static_content.SUPPORTED_SUBJECT_IDS:
        return static_content.get_material(tb, subject_id, section_id, item_id)
    return content.get_material(tb.DYNAMIC_COURSES, subject_id, section_id, item_id)


# ==================== Гейт Гистологии ====================
# В отличие от Анатомии (гейт ПО МОДУЛЯМ), у Гистологии в самом боте один гейт на ВЕСЬ раздел
# сразу (см. handlers/histology.py::histology_access_ok -- пробный период 7 дней с момента
# первого визита, ИЛИ подписка, ИЛИ 2 реферала в этом месяце, ИЛИ активное промо секции/глобальное
# промо) -- поэтому здесь один флаг на весь предмет, а не по группам-диагностикам, как у Анатомии.
# Используем ЧИСТЫЙ предикат histology_access_ok(user_id), а не стейтфул histology_gate_ok(callback)
# -- та же причина, что уже объясняет routers/access.py::_subject_is_open (docstring там): read-only
# API не должно выдавать пробный доступ как побочный эффект простого GET-запроса.


def _histology_locked_reason(tb, user_id: int) -> str | None:
    if has_test_access(tb, user_id) or tb.histology_access_ok(user_id):
        return None
    cheapest = tb.cheapest_histology_tier()
    return (
        "Гистология открывается пробным доступом (при первом визите в разделе бота), подпиской "
        f"от «{cheapest['short']}» ({cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐) или "
        "двумя рефералами в этом месяце."
    )


def _check_histology_access(tb, user_id: int) -> None:
    reason = _histology_locked_reason(tb, user_id)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)


def _annotate_histology_groups(tb, user_id: int, section: dict) -> dict:
    if section.get("id") == static_content.HISTOLOGY_SECTION_ID:
        reason = _histology_locked_reason(tb, user_id)
        for group in section.get("groups", []):
            group["locked"] = reason is not None
            group["locked_reason"] = reason
    return section


# ==================== Гейт Биологии ====================
# Биология гейтится ровно так же, как Физика/Химия -- общим реферальным middleware бота
# (referral_gate_middleware -> has_subject_access(user_id, "biology")), см. CLAUDE.md "Access
# control". Тоже один флаг на весь предмет, как у Гистологии (не по билетам отдельно) -- но, в
# отличие от Гистологии, у Биологии ДВА раздела разной формы: "tickets" (группированный -- список
# билетов виден всем, как список диагностик у Гистологии) и "questions" (плоский -- сам список из
# 185 заголовков вопросов уже является содержательной утечкой контента зачёта, скрывать за
# "именами групп" здесь нечего, поэтому при отсутствии доступа весь раздел "questions" отдаёт 403
# целиком, а не список с locked=true на каждом элементе).


def _biology_locked_reason(tb, user_id: int) -> str | None:
    if has_test_access(tb, user_id) or can_visit(tb, user_id, "biology"):
        return None
    cheapest = tb.cheapest_gated3_tier()
    return (
        f"Биология открывается подпиской от «{cheapest['short']}» "
        f"({cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐) или двумя рефералами в этом месяце."
    )


def _check_biology_access(tb, user_id: int) -> None:
    reason = _biology_locked_reason(tb, user_id)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)


def _annotate_biology_section(tb, user_id: int, section: dict) -> dict:
    if section.get("id") == static_content.BIOLOGY_TICKETS_SECTION_ID:
        reason = _biology_locked_reason(tb, user_id)
        for group in section.get("groups", []):
            group["locked"] = reason is not None
            group["locked_reason"] = reason
    return section


# ==================== Гейт Химии ====================
# Теория/Задачи/Лабораторные гейтятся ровно как Биология/Физика -- has_subject_access. Билеты
# (theory_tickets/practice_tickets) поверх этого ужесточены отдельным, более строгим предикатом
# chemistry_tickets_access_ok (не считает ручной/временный доступ и промо-акции достаточными --
# см. handlers/chemistry.py и docstring static_content.py). Два плоских раздела (theory, labs)
# без группового слоя гейтятся целиком, как "questions" у Биологии; практика билетов (тоже
# плоский) -- так же, только строгим предикатом.


def _chemistry_locked_reason(tb, user_id: int) -> str | None:
    if has_test_access(tb, user_id) or can_visit(tb, user_id, "chemistry"):
        return None
    cheapest = tb.cheapest_gated3_tier()
    return (
        f"Химия открывается подпиской от «{cheapest['short']}» "
        f"({cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐) или двумя рефералами в этом месяце."
    )


def _chemistry_tickets_locked_reason(tb, user_id: int) -> str | None:
    if has_test_access(tb, user_id) or tb.chemistry_tickets_access_ok(user_id):
        return None
    return (
        "Билеты по химии закрыты дополнительным условием: нужно 2 реферала в этом месяце или "
        "подписка от 89₽ -- обычного доступа к Химии для билетов недостаточно."
    )


def _check_chemistry_access(tb, user_id: int) -> None:
    reason = _chemistry_locked_reason(tb, user_id)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)


def _check_chemistry_tickets_access(tb, user_id: int) -> None:
    reason = _chemistry_tickets_locked_reason(tb, user_id)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)


def _annotate_chemistry_section(tb, user_id: int, section: dict) -> dict:
    section_id = section.get("id")
    if section_id == static_content.CHEMISTRY_TASKS_SECTION_ID:
        reason = _chemistry_locked_reason(tb, user_id)
    elif section_id == static_content.CHEMISTRY_THEORY_TICKETS_SECTION_ID:
        reason = _chemistry_tickets_locked_reason(tb, user_id)
    else:
        return section
    for group in section.get("groups", []):
        group["locked"] = reason is not None
        group["locked_reason"] = reason
    return section


# ==================== Гейт Физики ====================
# Все семь разделов гейтятся ОДНИМ и тем же has_subject_access(user_id, "physics") -- в отличие от
# Химии, у Физики нет отдельного более строгого гейта на билеты (см. docstring раздела "Физика" в
# static_content.py и handlers/physics.py). Три плоских раздела (test/grade45/extra) без группового
# слоя 403-ят раздел целиком (сами заголовки вопросов уже содержательны -- та же логика, что у
# "questions" Биологии и "theory"/"labs" Химии); четыре группированных (tasks/task_tickets/
# theory_tickets/test_tickets) показывают список групп всем, помечая locked -- "hide vs relabel".


def _physics_locked_reason(tb, user_id: int) -> str | None:
    if has_test_access(tb, user_id) or can_visit(tb, user_id, "physics"):
        return None
    cheapest = tb.cheapest_gated3_tier()
    return (
        f"Физика открывается подпиской от «{cheapest['short']}» "
        f"({cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐) или двумя рефералами в этом месяце."
    )


def _check_physics_access(tb, user_id: int) -> None:
    reason = _physics_locked_reason(tb, user_id)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)


def _annotate_physics_section(tb, user_id: int, section: dict) -> dict:
    if section.get("id") in (
        static_content.PHYSICS_TASKS_SECTION_ID,
        static_content.PHYSICS_TASK_TICKETS_SECTION_ID,
        static_content.PHYSICS_THEORY_TICKETS_SECTION_ID,
        static_content.PHYSICS_TEST_TICKETS_SECTION_ID,
    ):
        reason = _physics_locked_reason(tb, user_id)
        for group in section.get("groups", []):
            group["locked"] = reason is not None
            group["locked_reason"] = reason
    return section


@router.get("/subjects")
def list_subjects(
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    return [
        *[_with_maintenance(tb, content.to_subject_summary(course)) for course in tb.DYNAMIC_COURSES],
        *static_content.list_subject_summaries(tb),
    ]


@router.get("/subjects/{subject_id}")
def get_subject(
    subject_id: str,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
        if subject_id in static_content.SUPPORTED_SUBJECT_IDS:
            return static_content.get_subject_detail(tb, subject_id)
        return _with_maintenance(tb, content.get_subject_detail(tb.DYNAMIC_COURSES, subject_id))
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/subjects/{subject_id}/sections/{section_id}")
def get_section(
    subject_id: str,
    section_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    _check_subject_maintenance(tb, subject_id)
    try:
        if subject_id in static_content.SUPPORTED_SUBJECT_IDS:
            section = static_content.get_section_detail(tb, subject_id, section_id)
        else:
            section = content.get_section_detail(tb.DYNAMIC_COURSES, subject_id, section_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc
    if subject_id == static_content.ANATOMY_ID:
        # Список модулей виден всем (названия модулей не секрет — та же логика, что у
        # get_anatomy_menu_keyboard в боте: платные модули помечены, а не скрыты, см. "hide vs
        # relabel" в CLAUDE.md), только сами темы/материал внутри платного модуля закрыты (see
        # get_group/get_material ниже).
        section = _annotate_anatomy_groups(tb, user_id, section)
    if subject_id == static_content.HISTOLOGY_ID:
        # Список диагностик виден всем -- гейт применяется одинаково ко всем группам сразу
        # (см. _annotate_histology_groups), а не по отдельным группам, как у Анатомии.
        section = _annotate_histology_groups(tb, user_id, section)
    if subject_id == static_content.BIOLOGY_ID:
        if section_id == static_content.BIOLOGY_QUESTIONS_SECTION_ID:
            # Плоский раздел -- сами заголовки 185 вопросов уже содержательны, прятать их
            # позади "названий групп" здесь не за чем (см. docstring гейта Биологии выше).
            _check_biology_access(tb, user_id)
        else:
            section = _annotate_biology_section(tb, user_id, section)
    if subject_id == static_content.CHEMISTRY_ID:
        if section_id in (static_content.CHEMISTRY_THEORY_SECTION_ID, static_content.CHEMISTRY_LABS_SECTION_ID):
            _check_chemistry_access(tb, user_id)
        elif section_id == static_content.CHEMISTRY_PRACTICE_TICKETS_SECTION_ID:
            _check_chemistry_tickets_access(tb, user_id)
        else:
            section = _annotate_chemistry_section(tb, user_id, section)
    if subject_id == static_content.PHYSICS_ID:
        if section_id in static_content.PHYSICS_FLAT_SECTION_IDS:
            # Плоские разделы (test/grade45/extra) -- сами заголовки вопросов уже содержательны,
            # прятать их позади "названий групп" здесь не за чем (см. docstring гейта Физики выше).
            _check_physics_access(tb, user_id)
        else:
            section = _annotate_physics_section(tb, user_id, section)
    return section


@router.get("/subjects/{subject_id}/sections/{section_id}/groups/{group_id}")
def get_group(
    subject_id: str,
    section_id: str,
    group_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    _check_subject_maintenance(tb, subject_id)
    if subject_id == static_content.ANATOMY_ID and section_id == static_content.ANATOMY_SECTION_ID:
        if group_id not in tb.ANATOMY and group_id not in static_content.anatomy_miniapp.GROUPS:
            raise HTTPException(status_code=404, detail=f"модуль {group_id!r} не найден в анатомии")
        reason = _anatomy_module_locked_reason(tb, user_id, group_id)
        if reason is not None:
            raise HTTPException(status_code=403, detail=reason)
    if subject_id == static_content.HISTOLOGY_ID and section_id == static_content.HISTOLOGY_SECTION_ID:
        if group_id not in tb.HISTOLOGY:
            raise HTTPException(status_code=404, detail=f"диагностика {group_id!r} не найдена в гистологии")
        _check_histology_access(tb, user_id)
    if subject_id == static_content.BIOLOGY_ID and section_id == static_content.BIOLOGY_TICKETS_SECTION_ID:
        if not any(t["num"] == group_id for t in tb.TICKETS):
            raise HTTPException(status_code=404, detail=f"билет {group_id!r} не найден в биологии")
        _check_biology_access(tb, user_id)
    if subject_id == static_content.CHEMISTRY_ID:
        if section_id == static_content.CHEMISTRY_TASKS_SECTION_ID:
            if group_id not in tb.CHEMISTRY_TASKS:
                raise HTTPException(status_code=404, detail=f"тема {group_id!r} не найдена в задачах по химии")
            _check_chemistry_access(tb, user_id)
        elif section_id == static_content.CHEMISTRY_THEORY_TICKETS_SECTION_ID:
            if group_id not in tb.CHEMISTRY_THEORY_TICKETS:
                raise HTTPException(status_code=404, detail=f"билет {group_id!r} не найден в билетах теории химии")
            _check_chemistry_tickets_access(tb, user_id)
    if subject_id == static_content.PHYSICS_ID:
        physics_group_banks = {
            static_content.PHYSICS_TASKS_SECTION_ID: (tb.PHYSICS_TASKS, "тема", "задачах по физике"),
            static_content.PHYSICS_TASK_TICKETS_SECTION_ID: (
                tb.PHYSICS_TASK_TICKETS, "билет", "билетах с задачами физики",
            ),
            static_content.PHYSICS_THEORY_TICKETS_SECTION_ID: (
                tb.PHYSICS_THEORY_TICKETS, "билет", "билетах теории физики",
            ),
            static_content.PHYSICS_TEST_TICKETS_SECTION_ID: (
                tb.PHYSICS_TEST_TICKETS, "билет", "тестовых билетах физики",
            ),
        }
        bank = physics_group_banks.get(section_id)
        if bank is not None:
            data, noun, location = bank
            if group_id not in data:
                raise HTTPException(status_code=404, detail=f"{noun} {group_id!r} не найден в {location}")
            _check_physics_access(tb, user_id)
    try:
        if subject_id in static_content.SUPPORTED_SUBJECT_IDS:
            return static_content.get_group_detail(tb, subject_id, section_id, group_id)
        return content.get_group_detail(tb.DYNAMIC_COURSES, subject_id, section_id, group_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/materials/{subject_id}/{section_id}/{item_id}")
def get_material(
    subject_id: str,
    section_id: str,
    item_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
        return _get_material_data(tb, user_id, subject_id, section_id, item_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/materials/{subject_id}/{section_id}/{item_id}/answer")
def answer_quiz(
    subject_id: str,
    section_id: str,
    item_id: str,
    body: schemas.QuizAnswerRequest,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> schemas.QuizAnswerResponse:
    """correct_index никогда не приходит в GET /materials -- этот эндпоинт единственный, кто его
    раскрывает, и только после того как пользователь уже выбрал вариант (см. content.py::
    check_quiz_answer)."""
    _check_subject_maintenance(tb, subject_id)
    try:
        result = content.check_quiz_answer(
            tb.DYNAMIC_COURSES, subject_id, section_id, item_id, body.selected_index,
        )
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc
    except content.InvalidQuizAnswerError as exc:
        raise _bad_quiz_answer(exc) from exc
    from .. import learning
    learning.record_quiz_attempt(user_id, subject_id, section_id, item_id, result["correct"])
    return schemas.QuizAnswerResponse(**result)


@router.get("/materials/{subject_id}/{section_id}/{item_id}/media/{media_index}")
def get_material_media(
    subject_id: str,
    section_id: str,
    item_id: str,
    media_index: int,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> FileResponse:
    """Файл всегда резолвится через путь, который УЖЕ лежит в проверенном содержимом
    generated_courses/*.json (см. content.py) -- клиент передаёт только индекс в списке media
    этого урока, никогда сырой путь на диске. Дополнительно проверяем, что итоговый абсолютный
    путь остаётся внутри репозитория (defense in depth -- content-контент сегодня доверенный, но
    цена проверки нулевая, а её отсутствие было бы тихим допущением, которое легко сломать
    неаккуратной правкой JSON в будущем)."""
    try:
        material = _get_material_data(tb, user_id, subject_id, section_id, item_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc

    media_list = material.get("media", [])
    if media_index < 0 or media_index >= len(media_list):
        raise HTTPException(status_code=404, detail="медиафайл с таким индексом не найден")

    relative_path = media_list[media_index]["path"]
    absolute_path = os.path.normpath(os.path.join(REPO_ROOT, relative_path))
    if not absolute_path.startswith(REPO_ROOT + os.sep):
        raise HTTPException(status_code=400, detail="некорректный путь к медиафайлу")
    if not os.path.isfile(absolute_path):
        raise HTTPException(status_code=404, detail="файл отсутствует на диске")
    return FileResponse(absolute_path)
