import os
import html

from fastapi import APIRouter, HTTPException

from .. import config
from ..auth import InitDataError, verify_telegram_init_data
from ..deps import ensure_miniapp_access
from ..schemas import TelegramAuthRequest, TelegramAuthResponse
from ..session import create_session_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/telegram", response_model=TelegramAuthResponse)
async def auth_telegram(payload: TelegramAuthRequest) -> TelegramAuthResponse:
    """ТЗ §5, шаги 1-7: принимает сырую initData от Mini App, проверяет подпись и свежесть на
    сервере, и ТОЛЬКО после этого извлекает user_id и выдаёт короткоживущую сессию. Ничего из
    payload.init_data не считается доверенным до строки verify_telegram_init_data() ниже."""
    try:
        verified = verify_telegram_init_data(payload.init_data, config.BOT_TOKEN)
    except InitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = verified["user"]
    user_id = user["id"]
    ensure_miniapp_access(user_id)
    if os.environ.get('BOT_SYNC_MODE') == 'owner':
        from ..bot_state import get_bot_module
        tb = get_bot_module()
        # Add newly authenticated identities; never replace existing usernames or names.
        if user_id not in tb.stats['total_users']:
            tb.stats['total_users'].add(user_id)
            name = ' '.join(value for value in [user.get('first_name'), user.get('last_name')] if value)
            tb.stats['user_names'].setdefault(str(user_id), html.escape(name) or f'Пользователь {user_id}')
            username = (user.get('username') or '').strip().lower()
            if username:
                tb.stats['user_username'].setdefault(str(user_id), username)
                tb.stats['usernames'].setdefault(username, user_id)
            tb.save_stats()
    token = create_session_token(user_id, config.SESSION_SECRET)
    return TelegramAuthResponse(
        session_token=token,
        user_id=user_id,
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        username=user.get("username"),
        photo_url=user.get("photo_url"),
    )
