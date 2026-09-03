from pydantic import BaseModel


class TelegramAuthRequest(BaseModel):
    init_data: str


class TelegramAuthResponse(BaseModel):
    session_token: str
    user_id: int


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
