"""Серверный расчёт подписки и прав Mini App без доверия к флагам клиента."""
from datetime import datetime, timezone
from pathlib import Path
import time

from services.content_access import (
    EXAM_TRIAL_CLOSED, EXAM_TRIAL_HOURS, EXAM_TRIAL_SUBJECTS,
    can_visit, enter, exam_entitled, trial_active, trial_available, trial_expiry,
)
from services.study_preview import ANATOMY_SAMPLES, HISTOLOGY_SAMPLE, HISTOLOGY_SAMPLE_IMAGE

from services.miniapp_testers import has_test_access
from services.miniapp_policy import full_content_access, promo_active, public_launch, subscription_access, subscription_required

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..deps import get_current_user_id, get_fresh_bot_module
from ..schemas import AccessStatusResponse

router = APIRouter(prefix="/api/v1", tags=["access"])

SUBJECT_IDS = {
    "physics",
    "chemistry",
    "biology",
    "anatomy",
    "histology",
    "latin",
    "law",
    "physiology",
    "operative_surgery",
    "biochemistry",
    "pharmacology",
}
GATED_SUBJECT_IDS = {"physics", "chemistry", "biology"}
MAINTENANCE_SUBJECT_IDS = {"pharmacology"}
MAINTENANCE_REASON = "Раздел временно закрыт на полную переработку материалов и структуры."
PREVIEW_IMAGE_URL = "/api/v1/study-preview/micrograph"


@router.get("/study-preview")
def study_preview(_user_id: int = Depends(get_current_user_id)):
    from services.access import ANATOMY_HISTOLOGY_TIER_ID, ANATOMY_TEST_TIER_ID, SUBSCRIPTION_TIERS

    def offer(tier_id):
        return {"id": tier_id, "price_rub": SUBSCRIPTION_TIERS[tier_id]["price_rub"]}

    return {
        "anatomy": ANATOMY_SAMPLES,
        "histology": {**HISTOLOGY_SAMPLE, "image_url": PREVIEW_IMAGE_URL},
        "bundle": offer(ANATOMY_HISTOLOGY_TIER_ID),
        "test_pass": offer(ANATOMY_TEST_TIER_ID),
    }


@router.get("/study-preview/micrograph")
def study_preview_micrograph(_user_id: int = Depends(get_current_user_id)):
    image = Path(__file__).resolve().parents[2] / "images" / "histology" / HISTOLOGY_SAMPLE_IMAGE
    if not image.is_file():
        raise HTTPException(status_code=404, detail="Учебное изображение не найдено")
    return FileResponse(image, media_type="image/jpeg")


def _subscription_fields(tb, user_id: int) -> tuple[str | None, str | None]:
    sub = tb.get_subscription(user_id)
    if not sub or not tb.has_active_subscription(user_id):
        return None, None
    cfg = tb.SUBSCRIPTION_TIERS.get(sub.get("tier"), {})
    expires = sub.get("expires")
    expires_at = (
        datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()
        if isinstance(expires, (int, float))
        else None
    )
    return cfg.get("title"), expires_at


def _ai_fields(tb, user_id: int) -> tuple[bool, int | None]:
    unlimited = has_test_access(tb, user_id) or tb.has_unlimited_ai(user_id)
    requests_left = None if unlimited else tb.ai_requests_left(user_id)
    return bool(tb.ai_provider_available() and (unlimited or requests_left > 0)), requests_left


def _subject_is_open(tb, user_id: int, subject_id: str) -> bool:
    if _under_maintenance(tb, subject_id):
        return False
    if full_content_access(tb, user_id):
        return True
    if subject_id in EXAM_TRIAL_SUBJECTS and (subject_id != 'anatomy' or public_launch() or trial_active(tb, user_id)):
        return can_visit(tb, user_id, subject_id)
    if public_launch() and subject_id in {'biology', 'physics', 'chemistry', 'anatomy'}:
        return subscription_access(tb, user_id, subject_id)
    if subject_id in GATED_SUBJECT_IDS:
        return can_visit(tb, user_id, subject_id)
    if subject_id == 'anatomy':
        return not tb.anatomy_maintenance_mode_enabled() or tb.is_admin_or_assistant(user_id)
    # У анатомии есть общедоступные модули, а остальные предметы открыты на уровне корня.
    # Более узкие ограничения должны проверяться отдельным section/material gate.
    return True


def _under_maintenance(tb, subject_id: str) -> bool:
    return subject_id != 'anatomy_tests' and tb.dynamic_course_under_maintenance(subject_id) and not promo_active(tb)


def _locked_reason(tb, subject_id: str) -> str:
    if tb.dynamic_course_under_maintenance(subject_id):
        return MAINTENANCE_REASON
    if subject_id == 'anatomy':
        return 'Анатомия временно закрыта на техническую проверку.'
    if subject_id in EXAM_TRIAL_SUBJECTS:
        return EXAM_TRIAL_CLOSED
    return "Нужна подписка, временный доступ или 2 реферала в этом месяце."


@router.get("/subscription", response_model=AccessStatusResponse)
def get_subscription_summary(
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> AccessStatusResponse:
    title, expires_at = _subscription_fields(tb, user_id)
    can_use_ai, requests_left = _ai_fields(tb, user_id)
    return AccessStatusResponse(
        tester_access=has_test_access(tb, user_id),
        promo_access=promo_active(tb),
        can_open_subject=full_content_access(tb, user_id) or tb.has_free_access(user_id),
        can_download=full_content_access(tb, user_id) or tb.biology_tickets_download_ok(user_id),
        can_use_ai=can_use_ai,
        ai_requests_left=requests_left,
        subscription_expires_at=expires_at,
        subscription_title=title,
        locked_reason=None,
    )


@router.get("/access/{subject_id}", response_model=AccessStatusResponse)
def get_subject_access(
    subject_id: str,
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> AccessStatusResponse:
    if subject_id not in SUBJECT_IDS and subject_id not in EXAM_TRIAL_SUBJECTS:
        raise HTTPException(status_code=404, detail="предмет не найден")

    can_open = _subject_is_open(tb, user_id, subject_id)
    exam_scope = subject_id in EXAM_TRIAL_SUBJECTS
    can_start_trial = exam_scope and not can_open and not _under_maintenance(tb, subject_id) and trial_available(tb, user_id)
    expires = trial_expiry(tb, user_id) if exam_scope else 0
    in_trial = can_open and expires > time.time() and not full_content_access(tb, user_id) and not exam_entitled(tb, user_id, subject_id)
    needs_subscription = not exam_scope and subscription_required(tb, user_id, subject_id)
    title, expires_at = _subscription_fields(tb, user_id)
    can_use_ai, requests_left = _ai_fields(tb, user_id)
    can_download = can_open and (full_content_access(tb, user_id) or (
        tb.biology_tickets_download_ok(user_id)
        if subject_id == "biology"
        else subject_id in {"physics", "chemistry"} and tb.has_subject_access(user_id, subject_id)
    ))
    return AccessStatusResponse(
        tester_access=has_test_access(tb, user_id),
        promo_access=promo_active(tb),
        subscription_required=needs_subscription,
        can_open_subject=can_open,
        can_download=can_download,
        can_use_ai=can_use_ai,
        ai_requests_left=requests_left,
        subscription_expires_at=expires_at,
        subscription_title=title,
        locked_reason=None if can_open or can_start_trial else 'Для этого предмета нужна соответствующая подписка.' if needs_subscription else _locked_reason(tb, subject_id),
        trial_available=can_start_trial,
        trial_expires_at=datetime.fromtimestamp(expires, tz=timezone.utc).isoformat() if in_trial else None,
        trial_duration_hours=EXAM_TRIAL_HOURS if exam_scope else None,
    )


@router.post("/access/{subject_id}/enter")
async def enter_subject(subject_id: str, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    if subject_id not in SUBJECT_IDS and subject_id not in EXAM_TRIAL_SUBJECTS:
        raise HTTPException(status_code=404, detail="предмет не найден")
    if _under_maintenance(tb, subject_id):
        raise HTTPException(status_code=503, detail=MAINTENANCE_REASON)
    if full_content_access(tb, user_id) or (public_launch() and subject_id not in EXAM_TRIAL_SUBJECTS):
        decision = {'allowed': _subject_is_open(tb, user_id, subject_id), 'warning': False, 'trial_started': False}
    else:
        decision = enter(tb, user_id, subject_id)
    return {**decision, 'access': get_subject_access(subject_id, user_id, tb).model_dump()}
