from fastapi import Header, HTTPException

from . import bot_state, config
from .session import SessionTokenError, verify_session_token


def get_current_user_id(authorization: str | None = Header(default=None)) -> int:
    """Каждый защищённый эндпоинт объявляет `user_id: int = Depends(get_current_user_id)` --
    единственный способ узнать, кто спрашивает. Никогда не читай user_id из query-параметра или
    тела запроса напрямую (см. ТЗ §5/§16 -- "нельзя доверять данным от клиента"): он приходит
    ИСКЛЮЧИТЕЛЬНО из уже провалидированного session-токена."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="нет Bearer-токена в заголовке Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = verify_session_token(token, config.SESSION_SECRET)
    except SessionTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    ensure_miniapp_access(user_id)
    return user_id


def ensure_miniapp_access(user_id: int) -> None:
    """Временный серверный beta-gate. Проверяется и при входе, и на каждом запросе, поэтому
    ранее выданный токен не позволяет пережить переключение public -> admin_only."""
    if config.MINIAPP_ACCESS_MODE == "public":
        return
    try:
        bot_state.refresh_stats()
        tb = bot_state.get_bot_module()
    except bot_state.BotStateUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not tb.is_admin(user_id):
        raise HTTPException(
            status_code=403,
            detail="Мини-приложение пока доступно только администратору VMEDA.",
        )


def get_fresh_bot_module():
    """Depends()-обёртка над bot_state: перечитывает stats.json заново на каждый запрос, который
    её объявляет (см. bot_state.py, пункт 3 докстринга, за тем, почему это не бесплатная, но и не
    дорогая операция) -- эндпоинт получает telegram_bot-модуль с гарантированно свежим `stats`
    внутри текущего запроса, а не то, что было в памяти на момент старта процесса web_api."""
    try:
        bot_state.refresh_stats()
    except bot_state.BotStateUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return bot_state.get_bot_module()
