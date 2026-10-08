import asyncio
import os

from fastapi import APIRouter, Depends

from .. import learning
from ..deps import get_current_user_id, get_fresh_bot_module
from ..schemas import DashboardStatsResponse, LearningFlagRequest, LearningMaterialTouchRequest, LearningNavigationRequest

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])


@router.get("/state")
async def state(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)) -> dict:
    result = await asyncio.to_thread(learning.get_state, user_id)
    from services.histology_sync import summary
    result['histology'] = await asyncio.to_thread(summary, tb, user_id)
    baseline = tb.stats.get('histology_learning', {}).get(str(user_id), {})
    result['quiz_attempts'] += baseline.get('attempts', 0)
    result['quiz_correct'] += baseline.get('known', 0)
    from services.learning_view import merge
    result = merge(tb, user_id, result)
    return result


@router.get("/dashboard", response_model=DashboardStatsResponse)
async def dashboard(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)) -> DashboardStatsResponse:
    combined = await state(user_id, tb)
    result = await asyncio.to_thread(learning.get_dashboard, user_id)
    completed, correct, attempts = combined['completed_total'], combined['quiz_correct'], combined['quiz_attempts']
    result['xp'] = completed * 40 + correct * 20 + (attempts - correct) * 5
    denominator = max(result.get('curriculum_total', 0), completed, 1)
    # Native physiology can exist without a touched SQLite material.
    if combined['completed_by_subject'].get('physiology'):
        denominator = max(denominator, len(tb.PHYSIOLOGY.get('topics', [])))
    completion = completed / denominator * 100
    result['readiness_percent'] = round(completion * .4 + correct / attempts * 100 * .6) if attempts else round(completion)
    return DashboardStatsResponse(**result)


@router.post('/navigation')
async def navigation(body: LearningNavigationRequest, user_id: int = Depends(get_current_user_id)):
    import re
    from fastapi import HTTPException
    if not re.fullmatch(r'/(?:subjects/[a-z_-]+(?:/sections/[\w-]+(?:/groups/[\w-]+)?)?|materials/[a-z_-]+/[\w-]+/[\w-]+|tests/[a-z_-]+|histology/(?:exam|specimens/[\w-]+))', body.path):
        raise HTTPException(422, 'Некорректный учебный экран')
    return await asyncio.to_thread(learning.set_navigation, user_id, body.path)


@router.post("/materials/touch")
async def touch(body: LearningMaterialTouchRequest, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)) -> dict:
    material = _check_material(tb, user_id, body.subject_id, body.section_id, body.material_id)
    payload = {**body.model_dump(), 'material_title': material['title'], 'material_order': material.get('order', 1), 'total_in_section': material.get('total', 1)}
    await asyncio.to_thread(learning.touch_material, user_id, payload)
    return await state(user_id, tb)


@router.post("/materials/{subject_id}/{section_id}/{material_id}/completed")
async def set_completed(
    subject_id: str, section_id: str, material_id: str, body: LearningFlagRequest,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    _check_material(tb, user_id, subject_id, section_id, material_id)
    await asyncio.to_thread(learning.set_material_flag, user_id, subject_id, section_id, material_id, "completed", body.value)
    if os.environ.get('BOT_SYNC_MODE') == 'owner' and (subject_id, section_id) == ('physiology', 'course'):
        tb.stats.setdefault('physiology_completion_overrides', {}).setdefault(str(user_id), {})[material_id] = body.value
        tb.save_stats()
    return await state(user_id, tb)


@router.post("/materials/{subject_id}/{section_id}/{material_id}/favorite")
async def set_favorite(
    subject_id: str, section_id: str, material_id: str, body: LearningFlagRequest,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> dict:
    _check_material(tb, user_id, subject_id, section_id, material_id)
    await asyncio.to_thread(learning.set_material_flag, user_id, subject_id, section_id, material_id, "favorite", body.value)
    if os.environ.get('BOT_SYNC_MODE') == 'owner' and (subject_id, section_id) == ('physiology', 'course'):
        if tb.phys_is_favorite(user_id, material_id) != body.value:
            tb.phys_toggle_favorite(user_id, material_id)
        tb.stats.setdefault('physiology_favorite_overrides', {}).setdefault(str(user_id), {})[material_id] = body.value
        tb.save_stats()
    return await state(user_id, tb)


def _check_material(tb, user_id, subject_id, section_id, material_id):
    from ..content import ContentNotFoundError
    from .subjects import _get_material_data
    from fastapi import HTTPException
    try:
        return _get_material_data(tb, user_id, subject_id, section_id, material_id)
    except ContentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
