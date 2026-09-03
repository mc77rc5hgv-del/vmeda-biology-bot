from fastapi import APIRouter, Depends

from ..deps import get_current_user_id, get_fresh_bot_module
from ..schemas import MeResponse

router = APIRouter(prefix="/api/v1", tags=["me"])


@router.get("/me", response_model=MeResponse)
def get_me(
    user_id: int = Depends(get_current_user_id),
    tb=Depends(get_fresh_bot_module),
) -> MeResponse:
    """Первый настоящий read-only эндпоинт (Этап 3 ТЗ) -- НИЧЕГО здесь не замокано: user_id уже
    прошёл проверку initData (см. routers/auth.py), а все поля ответа читаются через ТЕ ЖЕ самые
    функции, которые использует сам бот (services.access, реэкспортированные на telegram_bot),
    а не переизобретены заново. Работает и для пользователя, которого бот никогда раньше не
    видел, -- has_free_access()/get_referral_count() и т.п. безопасно возвращают "нет доступа"/0
    через .get(...) с дефолтом, а не падают на неизвестном user_id."""
    uid_str = str(user_id)
    sub = tb.stats["subscriptions"].get(uid_str)
    tier_title = None
    if sub and tb.has_active_subscription(user_id):
        tier_cfg = tb.SUBSCRIPTION_TIERS.get(sub.get("tier"))
        tier_title = tier_cfg["title"] if tier_cfg else None

    return MeResponse(
        user_id=user_id,
        first_name=tb.stats.get("user_names", {}).get(uid_str),
        username=tb.stats.get("user_username", {}).get(uid_str),
        referral_count=tb.get_referral_count(user_id),
        referral_count_this_month=tb.get_referral_count_this_month(user_id),
        has_free_access=tb.has_free_access(user_id),
        has_active_subscription=tb.has_active_subscription(user_id),
        subscription_tier_title=tier_title,
        is_admin=tb.is_admin(user_id),
    )
