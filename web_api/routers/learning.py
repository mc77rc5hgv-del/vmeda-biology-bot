from fastapi import APIRouter, Depends

from .. import learning
from ..deps import get_current_user_id
from ..schemas import LearningFlagRequest, LearningMaterialTouchRequest

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])


@router.get("/state")
def state(user_id: int = Depends(get_current_user_id)) -> dict:
    return learning.get_state(user_id)


@router.post("/materials/touch")
def touch(body: LearningMaterialTouchRequest, user_id: int = Depends(get_current_user_id)) -> dict:
    learning.touch_material(user_id, body.model_dump())
    return learning.get_state(user_id)


@router.post("/materials/{subject_id}/{section_id}/{material_id}/completed")
def set_completed(
    subject_id: str, section_id: str, material_id: str, body: LearningFlagRequest,
    user_id: int = Depends(get_current_user_id),
) -> dict:
    learning.set_material_flag(user_id, subject_id, section_id, material_id, "completed", body.value)
    return learning.get_state(user_id)


@router.post("/materials/{subject_id}/{section_id}/{material_id}/favorite")
def set_favorite(
    subject_id: str, section_id: str, material_id: str, body: LearningFlagRequest,
    user_id: int = Depends(get_current_user_id),
) -> dict:
    learning.set_material_flag(user_id, subject_id, section_id, material_id, "favorite", body.value)
    return learning.get_state(user_id)
