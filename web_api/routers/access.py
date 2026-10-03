"""Серверный расчёт подписки и прав Mini App без доверия к флагам клиента."""
from datetime import datetime, timezone

from services.content_access import can_visit, enter, trial_available

from fastapi import APIRouter, Depends, HTTPException

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
    unlimited = tb.has_unlimited_ai(user_id)
    requests_left = None if unlimited else tb.ai_requests_left(user_id)
    return bool(tb.ai_provider_available() and (unlimited or requests_left > 0)), requests_left


def _subject_is_open(tb, user_id: int, subject_id: str) -> bool:
    if tb.dynamic_course_under_maintenance(subject_id):
        return False
    if subject_id in GATED_SUBJECT_IDS:
        return can_visit(tb, user_id, subject_id)
    if subject_id == "histology":
        # В отличие от Telegram-хендлера, read-only API не выдаёт пробную неделю как побочный
        # эффект GET-запроса; он лишь отражает уже существующий пробный/постоянный доступ.
        return tb.histology_access_ok(user_id)
    if subject_id == 'anatomy':
        return not tb.anatomy_maintenance_mode_enabled() or tb.is_admin_or_assistant(user_id)
    # У анатомии есть общедоступные модули, а остальные предметы открыты на уровне корня.
    # Более узкие ограничения должны проверяться отдельным section/material gate.
    return True


def _locked_reason(tb, subject_id: str) -> str:
    if tb.dynamic_course_under_maintenance(subject_id):
        return MAINTENANCE_REASON
    if subject_id == 'anatomy':
        return 'Анатомия временно закрыта на техническую проверку.'
    if subject_id == "histology":
        return "Нужен действующий пробный доступ, подписка или 2 реферала в этом месяце."
    return "Нужна подписка, временный доступ или 2 реферала в этом месяце."


@router.get("/subscription", response_model=AccessStatusResponse)
def get_subscription_summary(
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> AccessStatusResponse:
    title, expires_at = _subscription_fields(tb, user_id)
    can_use_ai, requests_left = _ai_fields(tb, user_id)
    return AccessStatusResponse(
        can_open_subject=tb.has_free_access(user_id),
        can_download=tb.biology_tickets_download_ok(user_id),
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
    if subject_id not in SUBJECT_IDS:
        raise HTTPException(status_code=404, detail="предмет не найден")

    can_open = _subject_is_open(tb, user_id, subject_id)
    title, expires_at = _subscription_fields(tb, user_id)
    can_use_ai, requests_left = _ai_fields(tb, user_id)
    can_download = (
        tb.biology_tickets_download_ok(user_id)
        if subject_id == "biology"
        else subject_id in {"physics", "chemistry"} and tb.has_subject_access(user_id, subject_id)
    )
    return AccessStatusResponse(
        can_open_subject=can_open,
        can_download=can_download,
        can_use_ai=can_use_ai,
        ai_requests_left=requests_left,
        subscription_expires_at=expires_at,
        subscription_title=title,
        locked_reason=None if can_open else _locked_reason(tb, subject_id),
        trial_available=subject_id == "histology" and not can_open and trial_available(tb, user_id),
    )


@router.post("/access/{subject_id}/enter")
async def enter_subject(subject_id: str, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    if subject_id not in SUBJECT_IDS:
        raise HTTPException(status_code=404, detail="предмет не найден")
    if tb.dynamic_course_under_maintenance(subject_id):
        raise HTTPException(status_code=503, detail=MAINTENANCE_REASON)
    decision = enter(tb, user_id, subject_id)
    return {**decision, 'access': get_subject_access(subject_id, user_id, tb).model_dump()}
