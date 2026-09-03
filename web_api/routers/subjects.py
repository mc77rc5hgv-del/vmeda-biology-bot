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


def _get_material_data(tb, subject_id: str, section_id: str, item_id: str) -> dict:
    if subject_id == static_content.PHYSIOLOGY_ID:
        return static_content.get_material(tb.PHYSIOLOGY, subject_id, section_id, item_id)
    return content.get_material(tb.DYNAMIC_COURSES, subject_id, section_id, item_id)


@router.get("/subjects")
def list_subjects(
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    return [
        *[content.to_subject_summary(course) for course in tb.DYNAMIC_COURSES],
        *static_content.list_subject_summaries(tb.PHYSIOLOGY),
    ]


@router.get("/subjects/{subject_id}")
def get_subject(
    subject_id: str,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
        if subject_id == static_content.PHYSIOLOGY_ID:
            return static_content.get_subject_detail(tb.PHYSIOLOGY, subject_id)
        return content.get_subject_detail(tb.DYNAMIC_COURSES, subject_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/subjects/{subject_id}/sections/{section_id}")
def get_section(
    subject_id: str,
    section_id: str,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
        if subject_id == static_content.PHYSIOLOGY_ID:
            return static_content.get_section_detail(tb.PHYSIOLOGY, subject_id, section_id)
        return content.get_section_detail(tb.DYNAMIC_COURSES, subject_id, section_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/subjects/{subject_id}/sections/{section_id}/groups/{group_id}")
def get_group(
    subject_id: str,
    section_id: str,
    group_id: str,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
        if subject_id == static_content.PHYSIOLOGY_ID:
            return static_content.get_group_detail(tb.PHYSIOLOGY, subject_id, section_id, group_id)
        return content.get_group_detail(tb.DYNAMIC_COURSES, subject_id, section_id, group_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/materials/{subject_id}/{section_id}/{item_id}")
def get_material(
    subject_id: str,
    section_id: str,
    item_id: str,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
        return _get_material_data(tb, subject_id, section_id, item_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/materials/{subject_id}/{section_id}/{item_id}/media/{media_index}")
def get_material_media(
    subject_id: str,
    section_id: str,
    item_id: str,
    media_index: int,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> FileResponse:
    """Файл всегда резолвится через путь, который УЖЕ лежит в проверенном содержимом
    generated_courses/*.json (см. content.py) -- клиент передаёт только индекс в списке media
    этого урока, никогда сырой путь на диске. Дополнительно проверяем, что итоговый абсолютный
    путь остаётся внутри репозитория (defense in depth -- content-контент сегодня доверенный, но
    цена проверки нулевая, а её отсутствие было бы тихим допущением, которое легко сломать
    неаккуратной правкой JSON в будущем)."""
    try:
        material = _get_material_data(tb, subject_id, section_id, item_id)
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
