import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import content, static_content
from ..deps import get_current_user_id, get_fresh_bot_module

router = APIRouter(prefix="/api/v1", tags=["subjects"])

# Динамические предметы идут через content.py; постепенно подключаемые статичные — через
# static_content.py. Маршруты остаются едиными для клиента.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _not_found(exc: content.ContentNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


# ==================== Гейт Анатомии ====================
# В отличие от Физиологии/Оперативной хирургии (полностью бесплатные в самом боте — см.
# static_content.py), Анатомия внутри бота гейтится ПО МОДУЛЯМ (ANATOMY_FREE_SECTIONS) и общим
# тех.режимом (anatomy_maintenance_mode_enabled) — см. handlers/anatomy.py. static_content.py
# остаётся чистой функцией формы контента (как и для двух других предметов), а проверка прав
# живёт здесь, потому что только здесь есть user_id (Depends(get_current_user_id)). "group_id" в
# разделе "course" Анатомии — это ключ модуля (напр. "module1_osteology"), ровно тот же, что
# принимает anatomy_section_access_ok на боте.


def _anatomy_maintenance_locked_reason(tb, user_id: int) -> str | None:
    if tb.anatomy_maintenance_mode_enabled() and not tb.is_admin_or_assistant(user_id):
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
    if tb.anatomy_section_access_ok(user_id, module_key):
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
    module_key = None
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
    if tb.histology_access_ok(user_id):
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
    if tb.has_subject_access(user_id, "biology"):
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
    if tb.has_subject_access(user_id, "chemistry"):
        return None
    cheapest = tb.cheapest_gated3_tier()
    return (
        f"Химия открывается подпиской от «{cheapest['short']}» "
        f"({cheapest['price_rub']}₽ / {cheapest['price_stars']}⭐) или двумя рефералами в этом месяце."
    )


def _chemistry_tickets_locked_reason(tb, user_id: int) -> str | None:
    if tb.chemistry_tickets_access_ok(user_id):
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
    if tb.has_subject_access(user_id, "physics"):
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
        *[content.to_subject_summary(course) for course in tb.DYNAMIC_COURSES],
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
        return content.get_subject_detail(tb.DYNAMIC_COURSES, subject_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/subjects/{subject_id}/sections/{section_id}")
def get_section(
    subject_id: str,
    section_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
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
    if subject_id == static_content.ANATOMY_ID and section_id == static_content.ANATOMY_SECTION_ID:
        if group_id not in tb.ANATOMY:
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
