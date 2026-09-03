from pydantic import BaseModel


class TelegramAuthRequest(BaseModel):
    init_data: str


class TelegramAuthResponse(BaseModel):
    """first_name/last_name/username/photo_url приходят из ТОЛЬКО ЧТО провалидированной initData
    (auth.verify_telegram_init_data), не из stats.json -- Telegram передаёт их заново при каждом
    открытии Mini App, так что это самые свежие данные о пользователе, какие вообще бывают,
    точнее того, что бот успел записать при последнем /start. MeResponse (см. ниже) намеренно НЕ
    дублирует эти поля -- она читает состояние доступа/рефералов из stats.json и вызывается
    отдельно, без initData под рукой; фронт берёт профиль отсюда (из ответа на аутентификацию),
    а /api/v1/me -- только для того, что реально живёт в stats.json."""
    session_token: str
    user_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None


class MeResponse(BaseModel):
    """См. ТЗ §16 -- все поля здесь СЧИТАЕТ backend через уже существующие предикаты бота
    (services.access, реэкспортированные на telegram_bot), фронт их только показывает."""
    user_id: int
    first_name: str | None
    username: str | None
    referral_count: int
    referral_count_this_month: int
    has_free_access: bool
    has_active_subscription: bool
    subscription_tier_title: str | None
    is_admin: bool


class AccessStatusResponse(BaseModel):
    """Права и лимиты уже рассчитаны сервером; клиент не выводит их из названия тарифа."""
    can_open_subject: bool
    can_download: bool
    can_use_ai: bool
    ai_requests_left: int | None
    subscription_expires_at: str | None
    subscription_title: str | None
    locked_reason: str | None
