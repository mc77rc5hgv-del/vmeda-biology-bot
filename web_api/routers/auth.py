from fastapi import APIRouter, HTTPException

from .. import config
from ..auth import InitDataError, verify_telegram_init_data
from ..schemas import TelegramAuthRequest, TelegramAuthResponse
from ..session import create_session_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/telegram", response_model=TelegramAuthResponse)
def auth_telegram(payload: TelegramAuthRequest) -> TelegramAuthResponse:
    """ТЗ §5, шаги 1-7: принимает сырую initData от Mini App, проверяет подпись и свежесть на
    сервере, и ТОЛЬКО после этого извлекает user_id и выдаёт короткоживущую сессию. Ничего из
    payload.init_data не считается доверенным до строки verify_telegram_init_data() ниже."""
    try:
        verified = verify_telegram_init_data(payload.init_data, config.BOT_TOKEN)
    except InitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = verified["user"]
    user_id = user["id"]
    token = create_session_token(user_id, config.SESSION_SECRET)
    return TelegramAuthResponse(
        session_token=token,
        user_id=user_id,
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        username=user.get("username"),
        photo_url=user.get("photo_url"),
    )
