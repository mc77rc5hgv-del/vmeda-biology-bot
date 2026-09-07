import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import content, schemas
from ..deps import get_current_user_id, get_fresh_bot_module

router = APIRouter(prefix="/api/v1", tags=["subjects"])

# Скоуп этого первого прохода адаптера -- см. docstring web_api/content.py: только "динамические"
# предметы (generated_courses/*.json), не статичные (Физика/Химия/Биология/...).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _not_found(exc: content.ContentNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _bad_quiz_answer(exc: content.InvalidQuizAnswerError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/subjects")
def list_subjects(
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> list[dict]:
    return [content.to_subject_summary(course) for course in tb.DYNAMIC_COURSES]


@router.get("/subjects/{subject_id}")
def get_subject(
    subject_id: str,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    try:
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
        return content.get_material(tb.DYNAMIC_COURSES, subject_id, section_id, item_id)
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/materials/{subject_id}/{section_id}/{item_id}/answer")
def answer_quiz(
    subject_id: str,
    section_id: str,
    item_id: str,
    body: schemas.QuizAnswerRequest,
    _user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> schemas.QuizAnswerResponse:
    """correct_index никогда не приходит в GET /materials -- этот эндпоинт единственный, кто его
    раскрывает, и только после того как пользователь уже выбрал вариант (см. content.py::
    check_quiz_answer)."""
    try:
        result = content.check_quiz_answer(
            tb.DYNAMIC_COURSES, subject_id, section_id, item_id, body.selected_index,
        )
    except content.ContentNotFoundError as exc:
        raise _not_found(exc) from exc
    except content.InvalidQuizAnswerError as exc:
        raise _bad_quiz_answer(exc) from exc
    return schemas.QuizAnswerResponse(**result)


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
        material = content.get_material(tb.DYNAMIC_COURSES, subject_id, section_id, item_id)
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
